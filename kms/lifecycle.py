"""KMS 文档生命周期管理。

参考 IBM/企业 KMS 最佳实践：文档应经历完整的生命周期管理，
而非简单的创建/删除。支持草稿、发布、归档、过期等状态流转。

设计原则
--------
1. 状态机: 文档有明确的状态和合法转换路径
2. 软删除: 删除操作改为归档，保留审计完整性
3. 过期管理: 文档可设置过期时间，到期自动标记
4. 与版本管理协同: 生命周期与版本管理互补

状态流转
--------
draft → published → archived
                ↓
             expired → archived
                 
- draft: 草稿，仅创建者和管理员可见
- published: 已发布，按密级可见
- archived: 已归档（软删除），仅管理员可见
- expired: 已过期，按密级可见但标记过期

数据模型
--------
在 documents 表增加字段:
- lifecycle_state: 当前状态
- published_at: 发布时间
- expires_at: 过期时间（NULL=永不过期）
- archived_at: 归档时间
- archived_by: 归档人
- archive_reason: 归档原因
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Tuple

from app.logger import get_logger
from app.store import MySQLStore

logger = get_logger("kms.lifecycle")


class DocState(str, Enum):
    """文档生命周期状态。"""
    DRAFT = "draft"           # 草稿
    PUBLISHED = "published"   # 已发布
    ARCHIVED = "archived"     # 已归档（软删除）
    EXPIRED = "expired"       # 已过期


# 合法状态转换
VALID_TRANSITIONS = {
    DocState.DRAFT: {DocState.PUBLISHED, DocState.ARCHIVED},
    DocState.PUBLISHED: {DocState.ARCHIVED, DocState.EXPIRED},
    DocState.EXPIRED: {DocState.PUBLISHED, DocState.ARCHIVED},
    # 归档（回收站）可恢复为发布或退回草稿重新编辑——恢复工单按删除前状态回流
    DocState.ARCHIVED: {DocState.PUBLISHED, DocState.DRAFT},
}

STATE_LABELS = {
    DocState.DRAFT: "草稿",
    DocState.PUBLISHED: "已发布",
    DocState.ARCHIVED: "已归档",
    DocState.EXPIRED: "已过期",
}


# ===================== DDL（documents 表扩展） =====================
LIFECYCLE_DDL = [
    # 为 documents 表增加生命周期字段（幂等：忽略已存在列的错误）
    # 默认 draft（fail-closed）：与 gateway/service.migrate() 保持一致。
    # 原为 'published'，两个迁移默认值互相矛盾——谁先跑决定新文档默认可见性。
    """ALTER TABLE documents ADD COLUMN lifecycle_state VARCHAR(16) NOT NULL DEFAULT 'draft'
       COMMENT '生命周期状态: draft/published/archived/expired' AFTER file_type""",
    """ALTER TABLE documents ADD COLUMN published_at DATETIME NULL
       COMMENT '发布时间' AFTER lifecycle_state""",
    """ALTER TABLE documents ADD COLUMN expires_at DATETIME NULL
       COMMENT '过期时间（NULL=永不过期）' AFTER published_at""",
    """ALTER TABLE documents ADD COLUMN archived_at DATETIME NULL
       COMMENT '归档时间' AFTER expires_at""",
    """ALTER TABLE documents ADD COLUMN archived_by BIGINT NULL
       COMMENT '归档人 kms_users.id' AFTER archived_at""",
    """ALTER TABLE documents ADD COLUMN archive_reason VARCHAR(512) NULL
       COMMENT '归档原因' AFTER archived_by""",
    # 索引
    """ALTER TABLE documents ADD INDEX idx_lifecycle (lifecycle_state)""",
    """ALTER TABLE documents ADD INDEX idx_expires (expires_at)""",
]


def ensure_lifecycle_columns() -> bool:
    """为 documents 表增加生命周期字段（幂等）。"""
    mysql = MySQLStore()
    success_count = 0
    for ddl in LIFECYCLE_DDL:
        try:
            with mysql._conn() as cur:
                cur.execute(ddl)
            success_count += 1
        except Exception as e:
            # 忽略"列已存在"的错误
            if "Duplicate column" not in str(e) and "Duplicate key" not in str(e):
                logger.warning(f"生命周期字段扩展跳过: {e}")
    
    if success_count > 0:
        logger.info(f"文档生命周期字段已就绪（{success_count} 项 DDL 执行成功）")
    return True


# ===================== 状态转换 =====================

def get_document_state(document_id: int) -> Optional[DocState]:
    """获取文档当前状态。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                "SELECT lifecycle_state FROM documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            if row:
                # MySQLStore 使用 DictCursor，行为 dict；原实现用元组下标 row[0]
                # 必然 KeyError → 被 except 吞掉后恒返回 None，导致所有状态转换
                # 都以「文档不存在」失败。
                return DocState(row["lifecycle_state"])
    except Exception as e:
        logger.error(f"获取文档状态失败: {e}")
    return None


def state_update_parts(target_state: DocState,
                       user_id: Optional[int] = None,
                       reason: Optional[str] = None) -> tuple[list, list]:
    """构造一次状态转换的 SET 子句与参数（供事务内执行器复用）。

    必须同时写 status 与 lifecycle_state：读取侧（gateway/service.allowed 与
    documents() SQL）要求两列同时为 'published'，只写其一会让文档静默不可见
    ——最典型的是归档后恢复：lifecycle 回到 published 而 status 仍是 archived。
    """
    updates = ["lifecycle_state = %s", "status = %s"]
    params: list = [target_state.value, target_state.value]

    if target_state == DocState.PUBLISHED:
        updates.append("published_at = COALESCE(published_at, NOW())")
        updates.append("archived_at = NULL")
        updates.append("archived_by = NULL")
        updates.append("archive_reason = NULL")
    elif target_state == DocState.DRAFT:
        # 退回草稿同样要清掉归档痕迹，否则 purge 清扫会按 archived_at 误判
        updates.append("archived_at = NULL")
        updates.append("archived_by = NULL")
        updates.append("archive_reason = NULL")
    elif target_state == DocState.ARCHIVED:
        updates.append("archived_at = NOW()")
        updates.append("archived_by = %s")
        updates.append("archive_reason = %s")
        params.extend([user_id, reason or ""])
    elif target_state == DocState.EXPIRED:
        pass  # 仅改状态
    return updates, params


def transition_state(document_id: int, target_state: DocState,
                     user_id: Optional[int] = None,
                     reason: Optional[str] = None) -> Tuple[bool, str]:
    """转换文档状态。

    Args:
        document_id: 文档 ID
        target_state: 目标状态
        user_id: 操作人 ID
        reason: 操作原因（归档时建议填写）
    """
    mysql = MySQLStore()
    current_state = get_document_state(document_id)
    if current_state is None:
        return False, "文档不存在"

    # 检查转换合法性
    if target_state not in VALID_TRANSITIONS.get(current_state, set()):
        return False, f"不允许从 {STATE_LABELS[current_state]} 转换到 {STATE_LABELS[target_state]}"

    updates, params = state_update_parts(target_state, user_id, reason)
    params.append(document_id)

    try:
        with mysql._conn() as cur:
            cur.execute(
                f"UPDATE documents SET {', '.join(updates)} WHERE id = %s",
                params,
            )
        logger.info(f"文档状态转换: doc_id={document_id}, {current_state.value} -> {target_state.value}")
        return True, f"文档已{STATE_LABELS[target_state]}"
    except Exception as e:
        return False, f"状态转换失败: {e}"


def soft_delete(document_id: int, user_id: int, reason: str = "") -> Tuple[bool, str]:
    """软删除文档（归档）。
    
    企业 KMS 最佳实践：不物理删除文档，而是归档保留审计完整性。
    """
    return transition_state(document_id, DocState.ARCHIVED, user_id, reason)


def restore_document(document_id: int) -> Tuple[bool, str]:
    """恢复已归档文档。"""
    return transition_state(document_id, DocState.PUBLISHED)


def check_expired_documents() -> int:
    """检查并标记过期文档。
    
    扫描 expires_at 已过期的 published 文档，自动标记为 expired。
    返回本次标记的文档数量。
    """
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                """UPDATE documents
                   SET lifecycle_state = %s, status = %s
                   WHERE lifecycle_state = %s
                     AND expires_at IS NOT NULL
                     AND expires_at < NOW()""",
                (DocState.EXPIRED.value, DocState.EXPIRED.value, DocState.PUBLISHED.value),
            )
            count = cur.rowcount
        if count > 0:
            logger.info(f"已标记 {count} 份文档为过期")
        return count
    except Exception as e:
        logger.error(f"检查过期文档失败: {e}")
        return 0


def set_expiration(document_id: int, expires_at: Optional[datetime]) -> Tuple[bool, str]:
    """设置文档过期时间。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                "UPDATE documents SET expires_at = %s WHERE id = %s",
                (expires_at, document_id),
            )
        return True, "过期时间已设置"
    except Exception as e:
        return False, f"设置失败: {e}"


# ===================== 查询辅助 =====================

def list_documents_by_state(state: DocState, limit: int = 100, offset: int = 0) -> List[dict]:
    """按状态列出文档。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                """SELECT id, filename, file_type, classification, chunk_count,
                          lifecycle_state, published_at, expires_at, created_at
                   FROM documents
                   WHERE lifecycle_state = %s
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (state.value, limit, offset),
            )
            # DictCursor 已返回 dict 行；原 dict(zip(cols, row)) 会把「列名」与
            # 「dict 的 key（同样是列名）」配对，结果是 {列名: 列名} 的垃圾数据。
            return list(cur.fetchall())
    except Exception as e:
        logger.error(f"按状态列出文档失败: {e}")
        return []


def count_by_state() -> dict:
    """统计各状态文档数量。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                "SELECT lifecycle_state, COUNT(*) as cnt FROM documents GROUP BY lifecycle_state"
            )
            return {row["lifecycle_state"]: row["cnt"] for row in cur.fetchall()}
    except Exception as e:
        logger.error(f"统计文档状态失败: {e}")
        return {}


# ===================== 兼容层（enterprise_routes.py 依赖） =====================

DOC_STATUS_LABELS = {s.value: label for s, label in STATE_LABELS.items()}
DOC_STATUS_LABELS.update({
    "draft": "草稿",
    "review": "审核中",
    "published": "已发布",
    "archived": "已归档",
    "destroyed": "已销毁",
    "expired": "已过期",
})


def transition_document(doc_id: int, to_status: str, user_id: int, reason: str = None) -> bool:
    """兼容 enterprise_routes 的状态转换接口。"""
    try:
        target = DocState(to_status)
    except ValueError:
        logger.warning(f"无效状态: {to_status}")
        return False
    # 原实现会往 kms_doc_status_history 写状态历史，但该表在当前 schema 中并不存在，
    # 靠 try/except: pass 静默吞掉异常——"已记录历史"是假象。现改为不写幻影表，
    # 状态流转的留痕由 gateway 审计日志（kms_audit_logs）承担。
    ok, _ = transition_state(doc_id, target, user_id, reason)
    return ok


def get_document_status(doc_id: int) -> Optional[str]:
    """兼容 enterprise_routes 的状态查询接口。"""
    state = get_document_state(doc_id)
    return state.value if state else None


def list_documents_by_status(status: Optional[str] = None, limit: int = 100) -> List[dict]:
    """兼容 enterprise_routes 的按状态查询接口。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            if status:
                cur.execute(
                    """SELECT id, filename, file_type, classification, chunk_count,
                              lifecycle_state, created_at
                       FROM documents WHERE lifecycle_state = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (status, limit),
                )
            else:
                cur.execute(
                    """SELECT id, filename, file_type, classification, chunk_count,
                              lifecycle_state, created_at
                       FROM documents ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )
            # DictCursor 已返回 dict 行；原 dict(zip(cols, row)) 会把「列名」与
            # 「dict 的 key（同样是列名）」配对，结果是 {列名: 列名} 的垃圾数据。
            return list(cur.fetchall())
    except Exception as e:
        logger.error(f"按状态列出文档失败: {e}")
        return []

