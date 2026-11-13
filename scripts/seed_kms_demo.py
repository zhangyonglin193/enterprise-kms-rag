"""演示专用：将 RAG_repository 语料批量灌入 KMS 库并构建索引。

与 ingest_batch.py（QA 公开语料）不同，本脚本面向 KMS 治理库 enterprise_kms：
入库后直接补齐治理字段，统一标记为 L0 公开 + 已发布，使工作台问答可检索到内容。

⚠️ 安全边界（治理绕过，仅限本地演示）：
- 强制要求 KMS_HOST=127.0.0.1（本机隔离环境），否则拒绝运行；
- 必须显式 --confirm-demo，杜绝误用于生产/真实金融数据；
- 不模拟双人审批，直接 published，仅供演示。

运行（须先停止 6342 KMS 服务，避免 FAISS 文件争用与缓存不一致）：
    python scripts/seed_kms_demo.py --confirm-demo
    python scripts/seed_kms_demo.py --input RAG_repository --env .env.kms --confirm-demo
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.service import apply_environment, load_values
from kms.formats import TEXT_EXTS, collect_files  # noqa: E402

# 演示数据只收文本格式（刻意不含图片）：避免演示环境触发 OCR 的成本与不确定性。
# 原为本地一份 11 项白名单，现改为从 kms.formats.TEXT_EXTS 派生——策略差异显式，
# 但「支持哪些格式」的定义只有一处。
ALLOWED = TEXT_EXTS

# 演示归属部门与组织路径（L0 可见性不依赖部门，仅为治理数据整洁）
DEMO_DEPARTMENT = "综合管理部"
DEMO_ORG_PATH = "银联商务/综合管理部"


def collect(root: Path) -> list[Path]:
    """收集演示文档（实现已统一到 kms.formats.collect_files）。"""
    return collect_files(root, TEXT_EXTS)


def mark_published(mysql, doc_id: int) -> None:
    """将文档登记为 L0 公开、已发布（双人审批的演示替代）。"""
    with mysql._conn() as cur:
        cur.execute(
            "UPDATE documents SET owner_department=%s, owner_org_path=%s, "
            "extra_departments='[]', status='published', lifecycle_state='published', "
            "publication_approved=1, expires_at=NULL WHERE id=%s",
            (DEMO_DEPARTMENT, DEMO_ORG_PATH, doc_id),
        )
        cur.execute(
            "INSERT INTO kms_doc_levels(document_id, level, granted_by) VALUES(%s, 0, NULL) "
            "ON DUPLICATE KEY UPDATE level=0",
            (doc_id,),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="RAG_repository")
    parser.add_argument("--env", default=str(ROOT / ".env.kms"))
    parser.add_argument("--confirm-demo", action="store_true",
                        help="确认仅用于本机演示（绕过双人审批，直接发布 L0）")
    args = parser.parse_args()

    if not args.confirm_demo:
        parser.error("演示专用脚本：须显式指定 --confirm-demo")

    apply_environment(args.env, load_values(args.env))
    from config import settings
    if settings.kms_host != "127.0.0.1":
        raise SystemExit(f"拒绝运行：KMS_HOST={settings.kms_host} 非本机隔离环境")

    from app.logger import get_logger
    from kms.routes import get_indexer
    from kms import access_control as acl
    from gateway import service as gw_service
    logger = get_logger("seed_kms")

    # 确保治理表/列存在（幂等）
    if not acl.ensure_kms_acl_tables():
        raise SystemExit("KMS 权限表不可用")
    gw_service.migrate()

    root = Path(args.input)
    if not root.is_absolute():
        root = ROOT / args.input
    if not root.exists():
        raise SystemExit(f"入库目录不存在: {root}")
    files = collect(root)
    total = len(files)
    logger.info(f"发现 {total} 个待处理文件，目标库={settings.mysql_database}, FAISS={settings.faiss_index_path}")
    if not files:
        raise SystemExit("没有可导入文件")

    indexer = get_indexer()
    mysql = indexer.mysql
    report = {"total": total, "ingested": 0, "present": 0, "failed": 0, "failures": []}
    start = time.time()

    try:
        from tqdm import tqdm
        iterator = tqdm(files, desc="KMS入库", ncols=100)
    except ImportError:
        iterator = files

    for f in iterator:
        try:
            result = indexer.ingest(f)
            doc_id = int(result["document_id"])
            mark_published(mysql, doc_id)
            if result.get("skipped"):
                report["present"] += 1
                logger.info(f"[已存在→置为公开已发布] {f.name} doc_id={doc_id}")
            else:
                report["ingested"] += 1
                logger.info(f"[成功] {f.name} doc_id={doc_id}, 分块={result['chunk_count']}")
        except Exception as e:
            report["failed"] += 1
            report["failures"].append({"file": str(f), "error": str(e)})
            logger.error(f"[失败] {f.name}: {e}")

    elapsed = round(time.time() - start, 1)
    indexer.vector_store.save()
    logger.info("=" * 60)
    logger.info(f"完成: 新入库 {report['ingested']} / 已存在 {report['present']} / 失败 {report['failed']} / 总 {total}, 用时 {elapsed}s")
    logger.info(f"KMS 向量库总量: {indexer.vector_store.total}")
    if report["failures"]:
        for fp in report["failures"]:
            logger.warning(f"  - {fp['file']}: {fp['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
