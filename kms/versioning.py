"""KMS 文档版本管理。

企业 KMS 最佳实践：文档内容变更必须留痕，支持版本回滚。
- 每次内容更新写入 kms_doc_versions，记录 content_hash / 分块数 / 上传人 / 摘要。
- 同文件名再次上传 = 创建新版本（不新增 documents 行，保持 document_id 稳定）。
- 回滚 = 用历史版本的源文件重新分词向量化，生成新版本号。

事务边界：MySQL 写入（documents / chunks / kms_doc_versions）必须在同一事务内；
FAISS 向量删除在事务提交后执行，避免双存储不一致。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from app.logger import get_logger
from app.store import MySQLStore

logger = get_logger("kms.versioning")


# ===================== DDL =====================

_VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kms_doc_versions (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  document_id   BIGINT        NOT NULL,
  version_no    INT           NOT NULL,
  content_hash  CHAR(64)      NOT NULL,
  chunk_count   INT           NOT NULL DEFAULT 0,
  source_path   VARCHAR(1024) NOT NULL,
  uploaded_by   BIGINT        NULL,
  uploader_no   VARCHAR(64)   NULL,
  summary       VARCHAR(512)  NOT NULL DEFAULT '',
  is_current    TINYINT(1)    NOT NULL DEFAULT 0,
  created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_doc_version (document_id, version_no),
  KEY idx_doc (document_id),
  KEY idx_current (document_id, is_current)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 文档历史版本'
"""


def ensure_version_tables() -> None:
    """幂等建表 kms_doc_versions + documents.current_version_no 列（含回填）。"""
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute(_VERSION_TABLE_DDL)
    # 为 documents 表增加 current_version_no 列
    with mysql._conn() as cur:
        cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' "
            "AND COLUMN_NAME='current_version_no'"
        )
        if not cur.fetchone():
            cur.execute(
                "ALTER TABLE documents ADD COLUMN current_version_no "
                "INT NOT NULL DEFAULT 1 COMMENT '当前版本号'"
            )
            # 回填：所有存量文档视为 v1
            cur.execute(
                "UPDATE documents SET current_version_no=1 "
                "WHERE current_version_no IS NULL"
            )
            logger.info("已为 documents 表增加 current_version_no 列并回填 v1")


# ===================== 版本记录 =====================

def record_version(cur, document_id: int, content_hash: str, chunk_count: int,
                   source_path: str, uploaded_by: Optional[int],
                   uploader_no: Optional[str], summary: str = "") -> int:
    """在事务内写入新版本行，设 is_current=1，并把该文档其他版本的 is_current 置 0。

    返回新版本号。
    """
    # 计算下一个版本号
    cur.execute(
        "SELECT COALESCE(MAX(version_no), 0) AS max_no "
        "FROM kms_doc_versions WHERE document_id=%s",
        (document_id,),
    )
    next_no = int(cur.fetchone()["max_no"]) + 1

    # 把当前版本的 is_current 置 0
    cur.execute(
        "UPDATE kms_doc_versions SET is_current=0 "
        "WHERE document_id=%s AND is_current=1",
        (document_id,),
    )

    # 写入新版本（is_current=1）
    cur.execute(
        "INSERT INTO kms_doc_versions "
        "(document_id, version_no, content_hash, chunk_count, source_path, "
        " uploaded_by, uploader_no, summary, is_current) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)",
        (document_id, next_no, content_hash, chunk_count, source_path,
         uploaded_by, uploader_no, summary),
    )
    return next_no


def list_versions(document_id: int) -> list[dict]:
    """倒序返回该文档全部版本（最新在前）。"""
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute(
            "SELECT version_no, content_hash, chunk_count, source_path, "
            "       uploaded_by, uploader_no, summary, is_current, created_at "
            "FROM kms_doc_versions WHERE document_id=%s "
            "ORDER BY version_no DESC",
            (document_id,),
        )
        return list(cur.fetchall())


def get_current_version(document_id: int) -> Optional[dict]:
    """返回 is_current=1 的版本行。"""
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute(
            "SELECT * FROM kms_doc_versions "
            "WHERE document_id=%s AND is_current=1 LIMIT 1",
            (document_id,),
        )
        row = cur.fetchone()
    return row


def get_version(document_id: int, version_no: int) -> Optional[dict]:
    """返回指定版本号的版本行。"""
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute(
            "SELECT * FROM kms_doc_versions "
            "WHERE document_id=%s AND version_no=%s LIMIT 1",
            (document_id, version_no),
        )
        row = cur.fetchone()
    return row


# ===================== 回滚 =====================

def resolve_version_source(source_path: str) -> Optional[Path]:
    """校验历史版本源文件是否仍存在于受信任目录。

    复用 gateway.routes_kms._resolve_source_file 的目录白名单逻辑，
    防止回滚时越权读取任意文件。
    """
    from config import settings
    try:
        roots = []
        for d in (settings.upload_dir, settings.repo_dir):
            try:
                roots.append(d.resolve())
            except OSError:
                continue
        roots = tuple(roots)
    except Exception:
        return None

    path = Path(source_path)
    if not path.is_absolute():
        path = settings.upload_dir / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not any(root in resolved.parents for root in roots):
        return None
    return resolved if resolved.is_file() else None


def rollback_to_version(document_id: int, target_version_no: int,
                        operator) -> Tuple[bool, str, int]:
    """回滚到指定历史版本。

    实质：用旧版本的源文件重新分词向量化，生成新版本号（content_hash 回到旧值）。
    返回 (ok, message, new_version_no)。
    """
    target = get_version(document_id, target_version_no)
    if not target:
        return False, f"版本 v{target_version_no} 不存在", 0

    source_file = resolve_version_source(target["source_path"])
    if source_file is None:
        return False, "历史版本源文件不存在或已越出受信任目录，无法回滚", 0

    # 重新入库（force=True 跳过 content_hash 查重，因为旧 hash 可能仍存在于 documents）
    from kms.routes import get_indexer
    try:
        result = get_indexer().ingest(source_file, force=True)
    except Exception as e:
        return False, f"重新入库失败: {e}", 0

    if result.get("skipped"):
        return False, "重新入库被跳过（内容可能与当前版本相同）", 0

    new_doc_id = int(result["document_id"])
    new_chunk_count = int(result.get("chunk_count", 0))

    mysql = MySQLStore()
    old_faiss_ids: list[int] = []
    with mysql.transaction() as cur:
        # 1. 收集旧 chunks 的 faiss_id（事务提交后清理 FAISS）
        cur.execute(
            "SELECT faiss_id FROM chunks WHERE document_id=%s",
            (document_id,),
        )
        old_faiss_ids = [int(r["faiss_id"]) for r in cur.fetchall()]

        # 2. 删除旧 chunks
        cur.execute("DELETE FROM chunks WHERE document_id=%s", (document_id,))

        # 3. 把新 doc 的 chunks 迁移到旧 document_id
        cur.execute(
            "UPDATE chunks SET document_id=%s WHERE document_id=%s",
            (document_id, new_doc_id),
        )

        # 4. 用新行数据覆盖旧 documents 行的**内容字段**
        #    不能覆盖 title / author / language：重新入库这行的 title 取自
        #    源文件名，而历史版本的源文件在入库时已被改名为 content_hash
        #    （如 03f66f65….md），直接覆盖会让文档标题变成一串十六进制——
        #    回滚一次标题就丢了，且工单中心的对象列跟着显示成哈希，用户
        #    根本认不出是哪篇文档。回滚回的是「内容」，不是元数据。
        cur.execute(
            "UPDATE documents d JOIN documents nd ON nd.id=%s SET "
            " d.content_hash=nd.content_hash, d.source_path=nd.source_path, "
            " d.file_type=nd.file_type, d.chunk_count=nd.chunk_count "
            "WHERE d.id=%s",
            (new_doc_id, document_id),
        )

        # 5. 删除新建的 documents 行（其 chunks 已迁移走）
        cur.execute("DELETE FROM documents WHERE id=%s", (new_doc_id,))

        # 6. 留痕新版本
        new_no = record_version(
            cur, document_id, target["content_hash"], new_chunk_count,
            target["source_path"], getattr(operator, "id", None),
            getattr(operator, "employee_no", None),
            summary=f"回滚至 v{target_version_no}",
        )

        # 7. 递增 documents.current_version_no
        cur.execute(
            "UPDATE documents SET current_version_no=%s WHERE id=%s",
            (new_no, document_id),
        )

    # 事务提交后清理旧 FAISS 向量
    if old_faiss_ids:
        try:
            from gateway.routes_tickets import _post_commit_cleanup_faiss
            _post_commit_cleanup_faiss(old_faiss_ids)
        except Exception as e:
            logger.warning(f"回滚后 FAISS 清理失败: {e}")

    logger.info(
        f"文档 {document_id} 回滚至 v{target_version_no}，生成新版本 v{new_no}"
    )
    return True, f"已回滚至版本 v{target_version_no}（新版本号 v{new_no}）", new_no
