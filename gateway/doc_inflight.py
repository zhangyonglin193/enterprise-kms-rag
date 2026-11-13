"""文档在途操作互斥 —— 业务悲观锁（单一事实源）。

语义
----
同一篇文档在同一时间**只允许存在一张待审批单**，无论它来自哪条链路：

  - 工单中心的「删除文档」（`kms_tickets` / module=doc_batch_delete）
  - 工单中心的「恢复文档」（`kms_tickets` / module=doc_restore）
  - 文档库的「申请更新 / 变更属性 / 上传新版本」（`kms_policy_requests`）
  - 文档库的「申请回滚到历史版本」（`kms_policy_requests` / action=rollback）

实现
----
不是「先查有没有、再插入」（check-then-act 在并发下会双双通过），而是一行
**业务锁** `kms_doc_locks`，`document_id` 为主键：

    建单事务内：INSERT IGNORE 锁行 → rowcount=1 抢到 / =0 已被占用 → 409
    单据办结（通过/驳回/撤回/超时）→ 删除锁行

`INSERT IGNORE` 撞主键是**原子**的，两个并发请求只可能有一个拿到；另一个
读到锁行后直接 409。抢锁失败时本事务回滚，单据不会落库。

锁行带 `expires_at`（与单据超时对齐），只是**防呆**：万一单据状态被手工改库
或进程崩在释放之前，过期锁不会永久占位。过期不等于放行——仍会回退到
「扫描两张单据表」兜底，所以「单据还在审批中」永远不会被绕过。

为什么还要先 `SELECT ... FROM documents ... FOR UPDATE`
---------------------------------------------------
锁表管「同一文档并发抢锁」，文档行锁管「同批文档的建单顺序」：多文档批量
建单时逐行加锁，避免两个批次交叉持锁。两者都在建单事务内，任一异常整体
回滚。

回填
----
锁表上线那一刻，库里已经有一批 pending 单（没有锁行）。`backfill()` 在服务
启动时把它们补登记进来（`INSERT IGNORE`，同文档多张历史单只留先到的一行），
从此锁表就是完整事实；扫描两张单据表退化为纯兜底。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

TICKET_MODULES = ("doc_batch_delete", "doc_restore")
_TICKET_ACTION = {"doc_batch_delete": "删除工单", "doc_restore": "恢复工单"}
_POLICY_ACTION = {
    "rollback": "版本回滚申请",
    "upload": "上传入库审批",
    "update_version": "新版本上传审批",
    "update_policy": "变更申请",
}
# 与常量模块保持字面一致；此处不 import kms.constants，避免与 kms 层形成环。
# （tests/test_doc_inflight.py 会断言两边取值一致。）
_STATUS_PENDING = "pending"
REF_TICKET = "ticket"
REF_POLICY = "policy"
# 回填时从 policy JSON 里取 action 的 SQL 表达式（与 _POLICY_ACTION 的键对应）
_POLICY_ACTION_EXPR = "JSON_UNQUOTE(JSON_EXTRACT(p.policy,'$.action'))"

LOCK_TABLE = "kms_doc_locks"
LOCK_DDL = f"""CREATE TABLE IF NOT EXISTS {LOCK_TABLE} (
    document_id BIGINT NOT NULL COMMENT '被锁定的文档',
    action_label VARCHAR(32) NOT NULL DEFAULT '' COMMENT '在途单类型（删除工单/变更申请…）',
    ref_type VARCHAR(16) NOT NULL COMMENT 'ticket / policy',
    ref_id VARCHAR(64) NOT NULL COMMENT '单号主键',
    ref_no VARCHAR(64) NOT NULL DEFAULT '' COMMENT '对外展示的单号',
    owner_id BIGINT NULL COMMENT '申请人',
    owner_name VARCHAR(64) NOT NULL DEFAULT '',
    expires_at DATETIME NOT NULL COMMENT '锁租约（防呆，非放行条件）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id),
    KEY lock_ref (ref_type, ref_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档在途业务锁（一篇文档一张待审批单）'"""

CONFLICT_TAIL = "：同一篇文档同时只允许一张待审批单，请等它办结或撤回后再发起"
# 变更类申请的锁租约：与 kms_policy_requests 的实际超时口径一致（宽松取值，
# 租约只用于「进程崩在释放之前」的兜底，到期仍靠扫描单据表判定）。
POLICY_LEASE_HOURS = 72


def ensure_schema(cur) -> None:
    """建锁表（幂等）。由 KMS 启动时的 initialize() 调用。"""
    cur.execute(LOCK_DDL)


def lease_deadline(hours: int = POLICY_LEASE_HOURS) -> datetime:
    """变更类申请的锁租约截止时间。"""
    return datetime.now() + timedelta(hours=hours)


def ticket_action_label(module: str) -> str:
    """工单模块 → 锁行上的中文动作名（删除工单 / 恢复工单）。"""
    return _TICKET_ACTION.get(module, "工单")


def policy_action_label(action: str) -> str:
    """policy.action → 锁行上的中文动作名（变更申请 / 版本回滚申请 …）。"""
    return _POLICY_ACTION.get(str(action or ""), "变更申请")


def _case_sql(expr: str, mapping: dict[str, str], default: str) -> str:
    """把「取值 → 中文动作名」编译成 SQL CASE（供回填使用）。"""
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {expr} {whens} ELSE '{default}' END"


def _count(cur) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM {LOCK_TABLE}")
    return int(cur.fetchone()["n"])


def backfill(cur) -> int:
    """把锁表上线前就已存在的 pending 单补登记成锁行（幂等，返回新增行数）。

    不补的话，历史单只靠扫描两张单据表兜底：功能上拦得住，但锁表就不再是
    完整事实——运维查锁表看不到那些正占着座位的单，排查「为什么我不能提交」
    时得绕一圈。`INSERT IGNORE` 让「同文档多张历史单」（历史 bug 遗留）
    只保留先到的一行，与运行时抢锁的语义一致。

    必须在 `ensure_schema()` 之后、且 `kms_tickets` / `kms_users` 已建好后调用。
    """
    before = _count(cur)
    cur.execute(
        f"INSERT IGNORE INTO {LOCK_TABLE}"
        "(document_id,action_label,ref_type,ref_id,ref_no,owner_id,owner_name,expires_at) "
        f"SELECT ids.doc_id, {_case_sql('t.module', _TICKET_ACTION, '工单')}, "
        "       %s, CAST(t.id AS CHAR), t.ticket_no, t.applicant_id, "
        "       COALESCE(t.applicant_name,''), "
        "       COALESCE(t.timeout_at, DATE_ADD(NOW(), INTERVAL %s HOUR)) "
        "FROM kms_tickets t "
        "JOIN JSON_TABLE(COALESCE(t.payload,'{}'), '$.doc_ids[*]' "
        "     COLUMNS (doc_id BIGINT PATH '$')) ids "
        "WHERE t.status=%s AND t.module IN (%s,%s) "
        "  AND JSON_VALID(COALESCE(t.payload,'{}')) "
        "ORDER BY t.created_at, t.id",
        (REF_TICKET, POLICY_LEASE_HOURS, _STATUS_PENDING) + TICKET_MODULES)
    cur.execute(
        f"INSERT IGNORE INTO {LOCK_TABLE}"
        "(document_id,action_label,ref_type,ref_id,ref_no,owner_id,owner_name,expires_at) "
        "SELECT p.document_id, "
        f"       {_case_sql(_POLICY_ACTION_EXPR, _POLICY_ACTION, '变更申请')}, "
        "       %s, p.id, '', p.requested_by, COALESCE(u.username,''), "
        "       DATE_ADD(NOW(), INTERVAL %s HOUR) "
        "FROM kms_policy_requests p LEFT JOIN kms_users u ON u.id=p.requested_by "
        "WHERE p.status=%s ORDER BY p.created_at, p.id",
        (REF_POLICY, POLICY_LEASE_HOURS, _STATUS_PENDING))
    return _count(cur) - before


# ---------------------------------------------------------------- 基础工具
def _ids(doc_ids: Any) -> list[int]:
    out: list[int] = []
    for raw in doc_ids or []:
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def _marks(items) -> str:
    return ",".join(["%s"] * len(items))


def _doc_names(cur, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    cur.execute(f"SELECT id, filename FROM documents WHERE id IN ({_marks(ids)})", tuple(ids))
    return {int(r["id"]): r["filename"] for r in cur.fetchall()}


def lock_documents(cur, doc_ids: Any) -> dict[int, str]:
    """锁住目标文档行并返回 `{doc_id: filename}`（同批文档的建单在此串行化）。"""
    ids = _ids(doc_ids)
    if not ids:
        return {}
    cur.execute(f"SELECT id, filename FROM documents WHERE id IN ({_marks(ids)}) "
                "ORDER BY id FOR UPDATE", tuple(ids))
    return {int(r["id"]): r["filename"] for r in cur.fetchall()}


def _purge_expired(cur, ids: list[int]) -> None:
    """清掉目标文档上已过期的锁行（租约只是防呆，不构成放行条件）。"""
    if not ids:
        return
    cur.execute(f"DELETE FROM {LOCK_TABLE} WHERE document_id IN ({_marks(ids)}) "
                "AND expires_at < NOW()", tuple(ids))


def _titles(hit: list[int], names: dict[int, str]) -> str:
    shown = "、".join(f"「{names.get(i, '#' + str(i))}」" for i in hit[:3])
    return shown + (f" 等 {len(hit)} 篇" if len(hit) > 3 else "")


# ---------------------------------------------------------------- 抢锁 / 释放
def acquire(cur, doc_ids: Any, *, ref_type: str, ref_id, ref_no: str = "",
            action_label: str = "", owner_id: Optional[int] = None,
            owner_name: str = "", expires_at: datetime) -> str:
    """抢占文档锁。成功返回空串；被占用返回「谁占着」的人话描述。

    **必须在建单事务内调用**：抢到部分文档后若后续失败，调用方抛异常即可让
    整个事务回滚（已抢到的锁随事务一起消失）。
    """
    ids = _ids(doc_ids)
    if not ids:
        return ""
    lock_documents(cur, ids)          # 行锁串行化，避免批量交叉持锁
    _purge_expired(cur, ids)
    for did in ids:
        cur.execute(
            f"INSERT IGNORE INTO {LOCK_TABLE}"
            "(document_id,action_label,ref_type,ref_id,ref_no,owner_id,owner_name,expires_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (did, (action_label or "在途操作")[:32], ref_type, str(ref_id),
             (ref_no or "")[:64], owner_id, (owner_name or "")[:64], expires_at))
        if getattr(cur, "rowcount", 1):
            continue
        return _describe_lock(cur, did)
    return ""


def release(cur, *, ref_type: str, ref_id) -> None:
    """释放本单持有的锁（办结/驳回/撤回/超时都走这里）。"""
    cur.execute(f"DELETE FROM {LOCK_TABLE} WHERE ref_type=%s AND ref_id=%s",
                (ref_type, str(ref_id)))


def release_many(cur, *, ref_type: str, ref_ids) -> None:
    """批量释放（超时清扫用）。"""
    ids = [str(x) for x in ref_ids or []]
    if not ids:
        return
    cur.execute(f"DELETE FROM {LOCK_TABLE} WHERE ref_type=%s AND ref_id IN ({_marks(ids)})",
                (ref_type,) + tuple(ids))


def _describe_lock(cur, doc_id: int) -> str:
    """把锁行翻译成人话：哪篇文档、什么单、谁发起。"""
    cur.execute(f"SELECT document_id,action_label,ref_type,ref_id,ref_no,owner_name "
                f"FROM {LOCK_TABLE} WHERE document_id=%s FOR UPDATE", (doc_id,))
    row = cur.fetchone()
    if not row:
        # 极端竞态：刚被判占用，读的时候又被释放了。按「可重试」处理，
        # 交给调用方的 409 文案兜住（不静默放行）。
        return f"文档 #{doc_id} 的在途状态刚刚变化，请稍后重试"
    names = _doc_names(cur, [int(row["document_id"])])
    label = row.get("action_label") or "在途操作"
    who = row.get("owner_name") or "—"
    no = row.get("ref_no") or ""
    return (f"文档{_titles([int(row['document_id'])], names)} 已有进行中的{label}"
            f"{(' ' + no) if no else ''}（申请人：{who}）")


# ---------------------------------------------------------------- 判定（含历史兜底）
def _locked_conflict(cur, target: set[int]) -> str:
    ids = sorted(target)
    _purge_expired(cur, ids)
    cur.execute(f"SELECT document_id,action_label,ref_no,owner_name FROM {LOCK_TABLE} "
                f"WHERE document_id IN ({_marks(ids)}) "
                "ORDER BY document_id LIMIT 1 FOR UPDATE", tuple(ids))
    row = cur.fetchone()
    if not row:
        return ""
    return _describe_lock(cur, int(row["document_id"]))


def _ticket_conflict(cur, target: set[int], names: dict[int, str]) -> str:
    cur.execute(
        "SELECT ticket_no, module, applicant_name, payload FROM kms_tickets "
        "WHERE status=%s AND module IN (%s,%s) FOR UPDATE",
        (_STATUS_PENDING,) + TICKET_MODULES)
    for row in cur.fetchall():
        try:
            held = {int(x) for x in (json.loads(row.get("payload") or "{}").get("doc_ids") or [])
                    if str(x).strip().isdigit()}
        except (TypeError, ValueError, AttributeError):
            continue
        hit = sorted(held & target)
        if not hit:
            continue
        action = _TICKET_ACTION.get(row["module"], "工单")
        return (f"文档{_titles(hit, names)} 已有进行中的{action} {row['ticket_no']}"
                f"（申请人：{row.get('applicant_name') or '—'}）")
    return ""


def _policy_conflict(cur, target: set[int], names: dict[int, str]) -> str:
    ids = sorted(target)
    cur.execute(
        "SELECT p.id, p.document_id, p.created_at, "
        "       JSON_UNQUOTE(JSON_EXTRACT(p.policy,'$.action')) AS action, "
        "       ru.username AS req_name, ap.username AS appr_name "
        "FROM kms_policy_requests p "
        "LEFT JOIN kms_users ru ON ru.id=p.requested_by "
        "LEFT JOIN kms_users ap ON ap.id=p.approver_id "
        f"WHERE p.document_id IN ({_marks(ids)}) AND p.status=%s "
        "ORDER BY p.created_at LIMIT 1 FOR UPDATE",
        tuple(ids) + (_STATUS_PENDING,))
    row = cur.fetchone()
    if not row:
        return ""
    did = int(row["document_id"])
    action = _POLICY_ACTION.get(str(row.get("action") or ""), "变更申请")
    who = row.get("req_name") or "他人"
    when = str(row.get("created_at") or "")[:16]
    appr = row.get("appr_name")
    tail = f"（审批人：{appr}）" if appr else ""
    stamp = f"于 {when} " if when else ""
    return f"文档{_titles([did], names)} 已有 {who} {stamp}发起的{action}在审批中{tail}"


def find_inflight_conflict(cur, doc_ids: Any) -> str:
    """返回「已有在途单」的人话描述；无冲突返回空串。

    判定顺序：
      1. 文档行锁（串行化同一批文档的建单）；
      2. 业务锁表（权威，`INSERT IGNORE` 抢的就是它）；
      3. 两张单据表扫描（兜底：加锁表之前建的历史单没有锁行）。

    注意：**会执行 `FOR UPDATE`**，必须在建单事务内调用。
    """
    target = set(_ids(doc_ids))
    if not target:
        return ""
    names = lock_documents(cur, sorted(target))
    return (_locked_conflict(cur, target)
            or _ticket_conflict(cur, target, names)
            or _policy_conflict(cur, target, names))
