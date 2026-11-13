"""清空数据库 + FAISS 索引，重新入库所有文档。

用法（须在停止 QA 服务后执行）：
    python scripts/reingest_all.py --confirm-public-data

流程：
  0. 获取实例锁（防两个重灌进程并发清库互相踩踏）
  1. TRUNCATE MySQL chunks / documents 表
  2. 删除 FAISS 索引文件
  3. 批量重新入库 RAG_repository/ 下所有文档
  4. 输出 data/reingest_report.json 摘要
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.service import ROOT, apply_environment, load_values

from kms.formats import ALLOWED_EXTS, collect_files  # noqa: E402


def collect(root: Path) -> list[Path]:
    """收集待入库文件（实现已统一到 kms.formats.collect_files）。"""
    return collect_files(root, ALLOWED_EXTS)


def _acquire_instance_lock(lock_path: Path):
    """实例锁：同一时刻只允许一个重灌进程（历史事故：双实例并发清库互踩）。

    用 OS 字节锁而非锁文件存在性判断：进程退出（含崩溃）时由内核自动释放，
    不存在残留锁需要人工清理的问题。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.write(f"pid={os.getpid()}\n")
            fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise RuntimeError(f"另一个重灌实例正在运行（锁文件: {lock_path}）") from None
    return fh


def main():
    parser = argparse.ArgumentParser(description="清空并重新入库所有 RAG 文档")
    parser.add_argument("--input", default="RAG_repository", help="入库目录（默认 RAG_repository）")
    parser.add_argument("--env", default=str(ROOT / ".env"), help="配置文件")
    parser.add_argument("--confirm-public-data", action="store_true",
                        help="确认仅导入获批公开评测资料且已停止对应服务")
    args = parser.parse_args()

    if not args.confirm_public_data:
        parser.error("须确认公开数据及维护窗口后指定 --confirm-public-data")

    apply_environment(args.env, load_values(args.env))

    from app.logger import get_logger
    from app.rag import Indexer
    from app.store import MySQLStore
    from config import BASE_DIR, settings

    logger = get_logger("reingest")

    # ---- Step 0: 实例锁（防并发重灌互相清库踩踏）----
    try:
        lock_fh = _acquire_instance_lock(Path(settings.docs_dir).parent / "reingest.lock")
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(2)
    # lock_fh 必须保留引用至 main 结束：文件对象被 GC 关闭会提前释放锁
    assert lock_fh is not None

    # ---- Step 1: 清空 MySQL ----
    logger.info("Step 1: 清空 MySQL chunks / documents 表 ...")
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute("SELECT COUNT(*) cnt FROM chunks")
        old_chunks = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) cnt FROM documents")
        old_docs = cur.fetchone()["cnt"]
    logger.info(f"  清空前：{old_docs} 个文档，{old_chunks} 个分块")
    with mysql._conn() as cur:
        cur.execute("DELETE FROM chunks")
        cur.execute("DELETE FROM documents")
        cur.execute("ALTER TABLE chunks AUTO_INCREMENT = 1")
        cur.execute("ALTER TABLE documents AUTO_INCREMENT = 1")
    logger.info("  MySQL 已清空")

    # ---- Step 2: 删除 FAISS 索引文件 ----
    index_file = Path(str(settings.faiss_index_path) + ".index")
    if index_file.exists():
        index_file.unlink()
        logger.info(f"Step 2: 已删除 FAISS 索引 {index_file}")
    else:
        logger.info(f"Step 2: FAISS 索引文件不存在，跳过 ({index_file})")

    # ---- Step 3: 重新入库 ----
    root = Path(args.input)
    if not root.is_absolute():
        root = BASE_DIR / args.input
    if not root.exists():
        logger.error(f"入库目录不存在: {root}")
        sys.exit(1)

    files = collect(root)
    total = len(files)
    logger.info(f"Step 3: 发现 {total} 个文件，开始重新入库 ...")

    indexer = Indexer()
    report = {"total": total, "success": 0, "skipped": 0, "failed": 0,
              "old_chunks": old_chunks, "old_docs": old_docs, "failures": []}
    start = time.time()

    try:
        from tqdm import tqdm
        iterator = tqdm(files, desc="重灌", ncols=100)
    except ImportError:
        iterator = files

    for f in iterator:
        rel = f.name
        try:
            result = indexer.ingest(f)
            if result.get("skipped"):
                report["skipped"] += 1
                logger.info(f"[跳过] {rel}")
            else:
                report["success"] += 1
                logger.info(f"[成功] {rel} -> doc_id={result['document_id']}, 分块={result['chunk_count']}")
        except Exception as e:
            report["failed"] += 1
            report["failures"].append({"file": rel, "error": str(e)})
            logger.error(f"[失败] {rel}: {e}")

    # ---- Step 3.5: 失败文件重试一轮（OCR/embedding 限流常为瞬时，恢复后重跑）----
    if report["failures"]:
        logger.info(f"Step 3.5: 重试 {len(report['failures'])} 个失败文件 ...")
        retry_failures: list[dict] = []
        for fp in report["failures"]:
            f = root / fp["file"]
            try:
                result = indexer.ingest(f)
                if result.get("skipped"):
                    report["skipped"] += 1
                else:
                    report["success"] += 1
                report["failed"] -= 1
                logger.info(f"[重试成功] {fp['file']} -> 分块={result['chunk_count']}")
            except Exception as e:
                retry_failures.append({"file": fp["file"], "error": str(e)})
                logger.error(f"[重试仍失败] {fp['file']}: {e}")
        report["failures"] = retry_failures

    elapsed = round(time.time() - start, 1)
    report["elapsed_sec"] = elapsed
    report["new_chunks"] = indexer.vector_store.total

    report_path = settings.docs_dir.parent / "reingest_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("=" * 60)
    logger.info(f"重灌完成：成功 {report['success']} / 跳过 {report['skipped']} / 失败 {report['failed']} / 总 {total}")
    logger.info(f"向量库总量：{report['new_chunks']}（原 {old_chunks}）")
    logger.info(f"用时：{elapsed}s  报告：{report_path}")
    if report["failures"]:
        logger.warning("失败文件：")
        for fp in report["failures"]:
            logger.warning(f"  - {fp['file']}: {fp['error']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
