"""批量入库脚本（工程化）：遍历目录，逐文件入库，错误隔离，进度与摘要。

用法（仅用于已批准的公开竞赛语料，须在停止对应 QA 服务的维护窗口执行）：
    python scripts/ingest_batch.py --confirm-public-data
    python scripts/ingest_batch.py --input RAG_repository --env .env --confirm-public-data
    python scripts/ingest_batch.py --input D:/some/dir --confirm-public-data   # 绝对路径

特点：
- 未指定 --confirm-public-data 直接拒绝；本脚本不得用于企业知识发布（企业走上传+双人审批）
- 导入前用 --env 选定的配置做数据隔离预检，并对已有数据先做一致性 warmup 校验
- 不会修改/覆盖原始文件，仅读取；基于 content_hash 去重，重复文件自动跳过（可断点续跑）
- 逐文件错误隔离，但只要存在失败就以非零码退出，避免把不完整入库误报为成功
- 输出 data/ingest_report.json 摘要
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.service import ROOT, apply_environment, load_values
from kms.formats import ALLOWED_EXTS, collect_files  # noqa: E402


def collect(root: Path) -> list[Path]:
    """收集待入库文件（实现已统一到 kms.formats.collect_files）。"""
    return collect_files(root, ALLOWED_EXTS)


def main():
    parser = argparse.ArgumentParser(description="批量入库 RAG 文档")
    parser.add_argument("--input", default="RAG_repository", help="入库目录（默认 RAG_repository）")
    parser.add_argument("--env", default=str(ROOT / ".env"), help="评测专用配置文件")
    parser.add_argument("--confirm-public-data", action="store_true", help="确认仅导入获批公开评测资料且已停止对应服务")
    args = parser.parse_args()
    if not args.confirm_public_data:
        parser.error("须确认公开数据及维护窗口后指定 --confirm-public-data；本脚本不得用于企业知识发布")
    apply_environment(args.env, load_values(args.env))
    from app.logger import get_logger
    from app.rag import Indexer, Retriever
    from config import BASE_DIR, settings
    logger = get_logger("ingest")

    root = Path(args.input)
    if not root.is_absolute():
        root = BASE_DIR / args.input
    if not root.exists():
        logger.error(f"入库目录不存在: {root}")
        sys.exit(1)

    files = collect(root)
    total = len(files)
    logger.info(f"发现 {total} 个待处理文件，目录: {root}")

    if not files:
        raise SystemExit("没有可导入文件，未执行入库")
    checker = Retriever()
    checker.warmup()
    checker.mysql.close_all()
    for client in (checker.embedder, checker.reranker, checker.llm):
        client.close()
    indexer = Indexer()
    report = {"total": total, "success": 0, "skipped": 0, "failed": 0, "failures": []}
    start = time.time()

    try:
        from tqdm import tqdm
        iterator = tqdm(files, desc="入库", ncols=100)
    except ImportError:
        iterator = files

    for f in iterator:
        rel = f.name
        try:
            result = indexer.ingest(f)
            if result.get("skipped"):
                report["skipped"] += 1
                logger.info(f"[跳过] {rel} (已存在 doc_id={result['document_id']})")
            else:
                report["success"] += 1
                logger.info(f"[成功] {rel} -> doc_id={result['document_id']}, 分块={result['chunk_count']}")
        except Exception as e:
            report["failed"] += 1
            report["failures"].append({"file": str(f), "error": str(e)})
            logger.error(f"[失败] {rel}: {e}")

    elapsed = round(time.time() - start, 1)
    report["elapsed_sec"] = elapsed

    report_path = settings.docs_dir.parent / "ingest_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("=" * 60)
    logger.info(f"入库完成: 成功 {report['success']} / 跳过 {report['skipped']} / 失败 {report['failed']} / 总 {total}，用时 {elapsed}s")
    logger.info(f"向量库总量: {indexer.vector_store.total}")
    logger.info(f"摘要报告: {report_path}")
    if report["failures"]:
        logger.warning("失败文件:")
        for fp in report["failures"]:
            logger.warning(f"  - {fp['file']}: {fp['error']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
