"""企业工单中心：通用工作流引擎（两段式：申请 → 审批通过即系统自动执行）。

无管理员设计（关键）
-------------------
系统中**不存在管理员角色**。谁能审批工单，取决于是否持有 `ticket_approve` 职责；
而职责本身又通过工单（`user_duty_grant`）授予与回收，形成可审计的授权闭环。

因此本模块刻意**不使用** `gateway/routes_kms.py` 里的 `auditor` 依赖——
它走 `settings.kms_admin_employees` 配置，与本模型的语义冲突。

流程语义（two_step）
-------------------
申请 A → 审批 B → 通过即由**系统**自动执行，不设独立执行人角色。
因此「待我执行 / 重试执行 / 拒执 / 执行人候选」四个执行人视角端点
（`/pending-execution`、`/execute`、`/refuse`、`/executor-candidates`）
已整体移除，不留 409 兜底路由；自动执行失败的工单（status 停在 approved）
在「我的工单」详情中可见失败原因（exec_result），由线下流程处置。

防篡改
------
提交时对 payload 计算 `original_hash`，审批通过时重新计算 `approved_hash`；
**执行前比对**，不一致则标记 `tampered` 并拒绝执行——防止审批后内容被偷换。

超时
----
每个模块有差异化超时（上传 72h / 更新 48h / 删除 24h），`timeout_at` 在建单时写入；
列表接口会先做一次超时清扫，把过期的 pending 工单置为 timeout（超时即驳回）。

并发
----
状态流转一律走 `MySQLStore().transaction()`（审批+执行结果原子提交）；
路由全部为同步 `def`，由 FastAPI 放进线程池执行，不阻塞事件循环。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.store import MySQLStore
from app.logger import get_logger
from gateway import doc_inflight
from kms import access_control as acl
from kms.constants import (
    DOC_DEPT_UNLIMITED,
    AUDIT_TICKET_APPROVE,
    AUDIT_TICKET_CANCEL,
    AUDIT_TICKET_CREATE,
    AUDIT_TICKET_EXECUTE,
    AUDIT_TICKET_REJECT,
    AUDIT_TICKET_TIMEOUT,
    TICKET_CATEGORY_DOC,
    TICKET_FLOW_TWO_STEP,
    TICKET_MODULE_DOC_BATCH_DELETE,
    TICKET_MODULE_DOC_RESTORE,
    TICKET_STATUS_APPROVED,
    TICKET_STATUS_CANCELLED,
    TICKET_STATUS_EXECUTED,
    TICKET_STATUS_LABELS,
    TICKET_STATUS_PENDING,
    TICKET_STATUS_REJECTED,
    TICKET_STATUS_TAMPERED,
    TICKET_STATUS_TIMEOUT,
    TICKET_TIMEOUT_BY_MODULE,
    TICKET_TIMEOUT_DEFAULT,
    normalize_department,
)
from kms.lifecycle import DocState, state_update_parts
from kms.security import AuthUser, require_user

logger = get_logger("gateway.routes_tickets")

router = APIRouter(prefix="/kms/api", tags=["tickets"])

# 回收站宽限期（天）：删除工单执行后文档进入归档（回收站），宽限期内可发起
# 恢复工单找回；期满由列表接口顺带清扫物理销毁。0 表示下个清扫周期立即销毁。
_DELETE_RETENTION_DAYS = max(0, int(os.getenv("KMS_DELETE_RETENTION_DAYS", "7")))
# 回收站文档的归档原因前缀：区分「工单删除→待销毁」与正常业务归档（不清扫）
_PURGE_REASON_PREFIX = "工单删除:"


def _parse_departments(raw) -> list[str]:
    """解析 documents.departments JSON 字段（数组或 JSON 字符串）。
    兼容旧 owner_department 单值回退：若非数组则包装为单元素列表。
    空/NULL → 空列表（fail-closed，与 access_control 语义一致）。
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x is not None]
            return [parsed]  # 单值字符串（旧 owner_department 回退）
        except (TypeError, ValueError):
            return [raw]  # 非 JSON 的普通字符串（旧数据）
    return []

# 终态：不会再流转的状态
_TERMINAL_STATUSES = (
    TICKET_STATUS_EXECUTED,
    TICKET_STATUS_REJECTED,
    TICKET_STATUS_CANCELLED,
    TICKET_STATUS_TIMEOUT,
    TICKET_STATUS_TAMPERED,
)


# ===================== 模块注册表 =====================
# 工单中心只处理管理类任务；文档入库/密级调整等已移至文档中心直接操作。
# 每个模块声明自己的字段 schema（前端据此渲染表单）与超时。
TICKET_MODULES: Dict[str, dict] = {
    TICKET_MODULE_DOC_BATCH_DELETE: {
        "key": TICKET_MODULE_DOC_BATCH_DELETE,
        "label": "批量删除文档",
        "description": "批量移除指定文档（进入回收站，宽限期后自动销毁）",
        "desc": (f"需经审批后由系统移入回收站，宽限 {_DELETE_RETENTION_DAYS} 天内可发起"
                 f"「恢复回收站文档」工单找回，期满自动物理销毁"),
        "category": "mgmt",
        "flow": TICKET_FLOW_TWO_STEP,
        "schema": [
            {"name": "doc_ids", "type": "doc_multi", "label": "待删除文档",
             "required": True, "placeholder": "选择需删除的文档"},
            {"name": "reason", "type": "textarea", "label": "删除原因",
             "required": True, "placeholder": "说明删除事由"},
        ],
    },
    TICKET_MODULE_DOC_RESTORE: {
        "key": TICKET_MODULE_DOC_RESTORE,
        "label": "恢复回收站文档",
        "description": "把回收站（工单删除归档）中的文档恢复到删除前状态",
        "desc": "需经审批后由系统恢复；文档恢复为删除工单快照中冻结的原状态（草稿/已发布）",
        "category": "mgmt",
        "flow": TICKET_FLOW_TWO_STEP,
        "schema": [
            {"name": "doc_ids", "type": "doc_multi", "label": "待恢复文档",
             "required": True, "placeholder": "选择需从回收站恢复的文档"},
            {"name": "reason", "type": "textarea", "label": "恢复原因",
             "required": True, "placeholder": "说明恢复事由"},
        ],
    },
    # 注：员工职责授予（user_duty_grant）模块已移除。
    # 审批权不再由「职责」表达，而是由组织属性（部门 + 安全职级）派生，
    # 因此不再需要一个「授予职责」的动作去维持人员 einzelnotify 名单——
    # 那样只会让两处真相漂移（职责名单说能审，BLP 说看不见）。
}

# 模块 → 超时分钟数（未注册的模块用默认值）
def _timeout_minutes(module: str) -> int:
    return TICKET_TIMEOUT_BY_MODULE.get(module, TICKET_TIMEOUT_DEFAULT)


def _module_or_404(key: str) -> dict:
    m = TICKET_MODULES.get(key)
    if not m:
        raise HTTPException(404, f"未知工单模块: {key}")
    return m


# ===================== 工具 =====================
def _payload_hash(payload: Any) -> str:
    """payload 的规范哈希（键排序，保证同样内容得到同样哈希）。"""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_payload(row: dict) -> Any:
    raw = row.get("payload")
    if not raw:
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _person(user_id: Optional[int], no: str = "", name: str = "") -> Optional[dict]:
    if not user_id:
        return None
    return {"id": user_id, "no": no or "", "employee_no": no or "",
            "name": name or "", "username": name or ""}


def _ticket_out(row: dict, viewer: Optional["AuthUser"] = None) -> dict:
    """统一工单输出形状（前端 ticketPerson/no/status 徽标都依赖这些字段）。

    `viewer` 用来派生 can_approve / can_cancel：审批人是建单时随机指派的，
    前端拿不到「我是谁的审批人」这层信息，只能由后端判定后下发。缺了这两个
    标记，详情弹窗的「审批通过 / 驳回 / 撤回」按钮会一律不渲染。
    """
    payload = _parse_payload(row)
    refs = row.get("doc_references")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = None
    viewer_id = getattr(viewer, "id", None)
    is_pending = row["status"] == TICKET_STATUS_PENDING
    return {
        "id": row["id"],
        "ticket_no": row["ticket_no"],
        "module": row["module"],
        "module_label": TICKET_MODULES.get(row["module"], {}).get("label", row["module"]),
        "category": row.get("category", TICKET_CATEGORY_DOC),
        "flow": row.get("flow", TICKET_FLOW_TWO_STEP),
        "status": row["status"],
        "status_label": TICKET_STATUS_LABELS.get(row["status"], row["status"]),
        "applicant_id": row.get("applicant_id"),
        "approver_id": row.get("approver_id"),
        "applicant": _person(row.get("applicant_id"), row.get("applicant_no", ""),
                             row.get("applicant_name", "")),
        "approver": _person(row.get("approver_id"), row.get("approver_no", ""),
                            row.get("approver_name", "")),
        "payload": payload,
        "payload_summary": row.get("payload_summary", ""),
        "reason": row.get("reason", ""),
        "exec_result": row.get("exec_result", ""),
        "original_hash": row.get("original_hash") or "",
        "approved_hash": row.get("approved_hash") or "",
        "approve_comment": row.get("approve_comment") or "",
        # 当前查看者的待办资格（权限判定在后端，前端只负责显示按钮）
        "can_approve": bool(is_pending and viewer_id
                            and row.get("approver_id") == viewer_id),
        "can_cancel": bool(is_pending and viewer_id
                           and row.get("applicant_id") == viewer_id),
        "doc_references": refs or [],
        "created_at": _s(row.get("created_at")),
        "updated_at": _s(row.get("updated_at")),
        "timeout_at": _s(row.get("timeout_at")),
        "approved_at": _s(row.get("approved_at")),
        "executed_at": _s(row.get("executed_at")),
    }


def _s(v) -> Optional[str]:
    return None if v is None else str(v)


_TICKET_COLS = (
    "id, ticket_no, module, category, flow, applicant_id, applicant_no, applicant_name, "
    "payload, payload_summary, original_hash, approved_hash, approver_id, approver_no, "
    "approver_name, approve_comment, approved_at, exec_result, executed_at, status, "
    "reason, timeout_at, doc_id, doc_references, created_at, updated_at"
)


def _snapshot_doc_refs(cur, doc_ids: List[str | int]) -> List[dict]:
    """快照 doc_ids 对应的文档元信息，用于写入 kms_tickets.doc_references。

    工单执行（批量删除）后 documents 行会被物理删除，但审计时仍应能还原
    「当初想删的是哪些文档」。这里把建单时文档的关键字段冻结下来。
    """
    valid = []
    for raw in doc_ids:
        try:
            valid.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not valid:
        return []
    placeholders = ",".join(["%s"] * len(valid))
    cur.execute(
        f"SELECT d.id, d.filename, d.title, d.departments, d.status, "
        f"d.lifecycle_state, COALESCE(l.level, 0) AS classification, "
        f"(SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) AS chunk_count "
        f"FROM documents d LEFT JOIN kms_doc_levels l ON l.document_id=d.id "
        f"WHERE d.id IN ({placeholders})",
        tuple(valid),
    )
    return [dict(r) for r in cur.fetchall()]


def _enrich_doc_refs(cur, refs: List[dict], viewer: "AuthUser") -> List[dict]:
    """ticket_detail 时给每条快照加 can_view + (若可视) 内容预览。

    审批人/申请人都已通过「工单归属」校验，但文档内容本身仍须过 BLP：
    审批人能批 ≠ 一定能读文档正文（BLP 不上读）。can_view 标记让前端决定
    是否提供「查看内容」按钮——这和草稿审批人需能查看草稿内容的规则一致。
    """
    from kms import access_control as _acl  # 本地导入避免循环
    if not refs:
        return []
    ids = [int(r["id"]) for r in refs if r.get("id")]
    if not ids:
        return []
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(
        f"SELECT d.id, COALESCE(l.level, 0) AS classification, d.departments, "
        f"d.title, d.filename, d.lifecycle_state, d.archive_reason "
        f"FROM documents d LEFT JOIN kms_doc_levels l ON l.document_id=d.id "
        f"WHERE d.id IN ({placeholders})",
        tuple(ids),
    )
    live = {int(r["id"]): dict(r) for r in cur.fetchall()}
    out = []
    for r in refs:
        item = dict(r)
        live_row = live.get(int(r["id"]))
        if live_row is None:
            item["exists"] = False
            item["recycled"] = False
            item["can_view"] = False
            item["snippet"] = ""
        else:
            item["exists"] = True
            # 回收站标记：工单删除产生的归档（正常业务归档不算）
            item["recycled"] = (
                live_row.get("lifecycle_state") == "archived"
                and str(live_row.get("archive_reason") or "").startswith(_PURGE_REASON_PREFIX))
            # 与 /documents/{id} 详情同一判据：BLP 读（不上读+部门/组织继承），
            # 或可管理（同部门且职级≥密级），或上传者本人。草稿也能被审批人看到。
            departments = _parse_departments(live_row.get("departments"))
            level = int(live_row.get("classification") or 0)
            can_read = _acl.can_read_doc(
                viewer.security_level, level, viewer.department, departments,
                emp_org_path=getattr(viewer, "org_path", "") or "")
            can_manage = _acl.can_approve_document(viewer, level, departments)
            item["can_view"] = bool(can_read or can_manage)
            # 内容预览：取前 3 个 chunk 的正文片段，总长度 <= 400 字
            if item["can_view"]:
                cur.execute(
                    "SELECT text FROM chunks WHERE document_id=%s ORDER BY chunk_index ASC LIMIT 3",
                    (int(r["id"]),),
                )
                snippet_chunks = [c["text"] for c in cur.fetchall() if c.get("text")]
                snippet = "\n".join(snippet_chunks).strip()
                if len(snippet) > 400:
                    snippet = snippet[:400] + "..."
                item["snippet"] = snippet
            else:
                item["snippet"] = ""
        out.append(item)
    return out


_TIMEOUT_REASON = "超过审批时限，自动驳回"


def _sweep_timeouts(cur) -> List[dict]:
    """把已过期的待审批工单置为超时驳回，返回被置为超时的工单行。

    先取出 id 再 UPDATE，是为了能在事务提交后逐条补审计与通知——
    自动驳回也是一次状态流转，不能没有审计痕迹。
    """
    cur.execute(
        "SELECT id, ticket_no, applicant_id FROM kms_tickets "
        "WHERE status=%s AND timeout_at IS NOT NULL AND timeout_at < NOW()",
        (TICKET_STATUS_PENDING,),
    )
    expired = cur.fetchall()
    if expired:
        ids = ",".join(["%s"] * len(expired))
        cur.execute(
            f"UPDATE kms_tickets SET status=%s, reason=%s WHERE id IN ({ids})",
            (TICKET_STATUS_TIMEOUT, _TIMEOUT_REASON) + tuple(r["id"] for r in expired),
        )
        # 超时即驳回：单据不再是 pending，在途席位立刻释放（否则这份文档
        # 要等到锁租约到期才能再发起任何操作）。
        doc_inflight.release_many(
            cur, ref_type=doc_inflight.REF_TICKET,
            ref_ids=[r["id"] for r in expired])
    return expired


def _settle_timeouts(expired: List[dict]) -> None:
    """事务提交后补记超时审计与通知（审计失败不影响查询返回）。"""
    for r in expired:
        acl.add_audit(None, AUDIT_TICKET_TIMEOUT, f"ticket:{r['ticket_no']}",
                      _TIMEOUT_REASON)
        if r.get("applicant_id"):
            acl.add_notification(r["applicant_id"], "工单超时驳回",
                                 f"{r['ticket_no']} {_TIMEOUT_REASON}",
                                 ticket_id=r["id"])


def _list_with_sweep(where: str, params: tuple, user: AuthUser) -> dict:
    with MySQLStore().transaction() as cur:
        expired = _sweep_timeouts(cur)
        # 回收站宽限期清扫：宽限届满的「工单删除归档」物理销毁（与工单表
        # 同事务提交，向量清理与审计在提交后进行——回滚不留伪审计）
        try:
            purge_faiss, purge_notes = _sweep_recycled_purge(cur)
        except Exception as e:  # 列缺失等结构问题不得阻塞工单列表
            logger.warning(f"回收站清扫跳过: {e}")
            purge_faiss, purge_notes = [], []
        cur.execute(
            f"SELECT {_TICKET_COLS} FROM kms_tickets WHERE {where} "
            "ORDER BY id DESC LIMIT 200", params)
        items = [_ticket_out(r, user) for r in cur.fetchall()]
    _settle_timeouts(expired)
    for target, detail in purge_notes:
        acl.add_audit(None, AUDIT_TICKET_EXECUTE, target, detail)
    if purge_faiss:
        _post_commit_cleanup_faiss(purge_faiss)
    return {"items": items}


def _sweep_recycled_purge(cur) -> tuple[list[int], list[tuple]]:
    """物理销毁回收站中宽限期届满的文档（仅限工单删除产生的归档）。

    归档原因前缀 _PURGE_REASON_PREFIX 把「待销毁」与正常业务归档区分开：
    后者永不自动清理。销毁按 chunks → 密级 → 版本 → documents 顺序执行，
    返回 (待清理的 faiss_id 列表, 提交后写入 WORM 审计的条目)。
    """
    cur.execute(
        "SELECT d.id, d.filename FROM documents d "
        "WHERE d.lifecycle_state='archived' AND d.archive_reason LIKE %s "
        "AND d.archived_at IS NOT NULL "
        "AND d.archived_at <= NOW() - INTERVAL %s DAY",
        (_PURGE_REASON_PREFIX + "%", _DELETE_RETENTION_DAYS),
    )
    due = cur.fetchall()
    if not due:
        return [], []
    ids = [int(r["id"]) for r in due]
    marks = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT faiss_id FROM chunks WHERE document_id IN ({marks})", tuple(ids))
    faiss_ids = [int(r["faiss_id"]) for r in cur.fetchall()]
    cur.execute(f"DELETE FROM chunks WHERE document_id IN ({marks})", tuple(ids))
    cur.execute(f"DELETE FROM kms_doc_levels WHERE document_id IN ({marks})", tuple(ids))
    cur.execute(f"DELETE FROM kms_doc_versions WHERE document_id IN ({marks})", tuple(ids))
    cur.execute(f"DELETE FROM documents WHERE id IN ({marks})", tuple(ids))
    notes = [
        (f"purge:doc#{r['id']}",
         f"回收站宽限期（{_DELETE_RETENTION_DAYS} 天）届满，物理销毁: {r['filename']}")
        for r in due
    ]
    logger.warning(f"回收站清扫: 物理销毁 {len(ids)} 篇宽限期届满文档")
    return faiss_ids, notes


def _load_ticket(cur, ticket_id: int, lock: bool = False) -> dict:
    cur.execute(f"SELECT {_TICKET_COLS} FROM kms_tickets WHERE id=%s"
                + (" FOR UPDATE" if lock else ""), (ticket_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "工单不存在")
    return row


# ===================== 执行器 =====================
def _execute(cur, row: dict, operator: AuthUser) -> tuple[bool, str, list]:
    """按模块执行已批准的工单。返回 (是否成功, 结果说明, 待清理的 faiss_id 列表)。

    执行是**系统**行为，不依赖执行人角色（two_step）。
    仅做 MySQL 变更；FAISS 等非事务性资源由调用方在事务提交后清理。
    """
    module = row["module"]
    payload = _parse_payload(row)

    if module == TICKET_MODULE_DOC_BATCH_DELETE:
        doc_ids = payload.get("doc_ids") or []
        if not doc_ids:
            return False, "payload 中没有 doc_ids", []

        # 解析并校验 doc_id 格式（非法 ID 直接判失败，不进入删除循环）
        valid_ids: list[int] = []
        invalid: list[str] = []
        for raw_id in doc_ids:
            try:
                valid_ids.append(int(raw_id))
            except (TypeError, ValueError):
                invalid.append(str(raw_id))
        if invalid:
            return False, f"存在非法文档 ID: {', '.join(invalid)}", []

        # 申请人权限复核：建单到审批期间人员/职级可能变动，
        # 执行前再次确认申请人对批次内每篇文档仍有管理权限。
        from kms.security import _load_user
        from kms import access_control as _acl
        applicant_id = int(row["applicant_id"])
        applicant = _load_user(applicant_id)
        if applicant is None:
            return False, f"申请人（ID={applicant_id}）已不存在，拒绝执行", []

        # 批量预查：确认文档仍存在；已被物理销毁的视为「终态已达成」跳过，
        # 不视为失败；真正的 DB 异常才判失败并整体回滚。
        placeholders = ",".join(["%s"] * len(valid_ids))
        cur.execute(
            f"SELECT d.id, d.departments, d.lifecycle_state, "
            f"COALESCE(l.level, 3) AS level "
            f"FROM documents d LEFT JOIN kms_doc_levels l ON l.document_id = d.id "
            f"WHERE d.id IN ({placeholders})",
            tuple(valid_ids),
        )
        existing = {int(r["id"]): r for r in cur.fetchall()}
        missing = [str(i) for i in valid_ids if i not in existing]

        # 权限复核：申请人须能管理批次内每一篇现存文档
        for r in existing.values():
            if not _acl.can_approve_document(
                applicant, int(r["level"]), _parse_departments(r["departments"])
            ):
                return False, (f"申请人 {applicant.username} 对文档 #{r['id']} "
                               f"已无管理权限，拒绝执行"), []

        # 回收站：移入归档态而非物理删除。chunks/kms_doc_versions/FAISS 向量
        # 全部保留——恢复工单可原样找回（零重嵌入），可见性由 allowed() 的
        # lifecycle != 'published' 判据整体拦截。宽限期（_DELETE_RETENTION_DAYS）
        # 届满由 _sweep_recycled_purge 物理销毁。
        already = [str(i) for i, r in existing.items()
                   if r["lifecycle_state"] == "archived"]
        to_recycle = [i for i in valid_ids
                      if i in existing and existing[i]["lifecycle_state"] != "archived"]

        sp = f"sp_del_{row['id']}"
        try:
            cur.execute(f"SAVEPOINT {sp}")
            if to_recycle:
                marks = ",".join(["%s"] * len(to_recycle))
                updates, params = state_update_parts(
                    DocState.ARCHIVED, applicant_id,
                    f"{_PURGE_REASON_PREFIX}{row['ticket_no']} "
                    f"{str(payload.get('reason') or '')[:400]}")
                cur.execute(
                    f"UPDATE documents SET {', '.join(updates)} "
                    f"WHERE id IN ({marks})",
                    tuple(params) + tuple(to_recycle),
                )
        except Exception as e:
            cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            return False, f"移入回收站失败（已回滚）: {e}", []

        done = len(to_recycle)
        msg = f"已移入回收站 {done} 篇（宽限 {_DELETE_RETENTION_DAYS} 天后自动销毁）"
        if already:
            msg += f"；其中 {len(already)} 篇已在回收站（跳过）"
        if missing:
            msg += f"；{len(missing)} 篇已不存在（视为已销毁）"
        return True, msg[:1024], []

    if module == TICKET_MODULE_DOC_RESTORE:
        ok, msg = _execute_restore(cur, row)
        return ok, msg, []

    # 员工职责授予（user_duty_grant）的执行分支已随模块一并移除。
    return False, f"模块 {module} 没有注册执行器", []


def _execute_restore(cur, row: dict) -> tuple[bool, str]:
    """恢复工单执行器：把回收站（工单删除归档）文档恢复到删除前状态。

    恢复目标态取自**原删除工单**建单时冻结的 doc_references 快照
    （status/lifecycle_state），而不是拍脑袋定为 published——草稿被删的
    恢复后仍是草稿，不越过「发布须审批」的闸门。向量与分块从未删除，
    恢复零重嵌入。
    """
    payload = _parse_payload(row)
    doc_ids = payload.get("doc_ids") or []
    valid_ids: list[int] = []
    for raw_id in doc_ids:
        try:
            valid_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    if not valid_ids:
        return False, "payload 中没有有效的文档 ID"

    # 申请人权限复核：与删除同判据（同部门 + 职级可读）
    from kms.security import _load_user
    from kms import access_control as _acl
    applicant = _load_user(int(row["applicant_id"]))
    if applicant is None:
        return False, f"申请人（ID={row['applicant_id']}）已不存在，拒绝执行"

    placeholders = ",".join(["%s"] * len(valid_ids))
    cur.execute(
        f"SELECT d.id, d.departments, d.lifecycle_state, d.archive_reason, "
        f"COALESCE(l.level, 3) AS level "
        f"FROM documents d LEFT JOIN kms_doc_levels l ON l.document_id = d.id "
        f"WHERE d.id IN ({placeholders})",
        tuple(valid_ids),
    )
    existing = {int(r["id"]): r for r in cur.fetchall()}

    # 只恢复「工单删除」产生的归档；正常业务归档与已物理销毁的文档不在此列
    restorable: dict[int, dict] = {}
    for i in valid_ids:
        r = existing.get(i)
        if r and r["lifecycle_state"] == "archived" \
                and str(r.get("archive_reason") or "").startswith(_PURGE_REASON_PREFIX):
            restorable[i] = r
    if not restorable:
        return False, "没有可恢复的文档（均不在回收站或已物理销毁）"

    for i, r in restorable.items():
        if not _acl.can_approve_document(applicant, int(r["level"]),
                                         _parse_departments(r["departments"])):
            return False, (f"申请人 {applicant.username} 对文档 #{i} "
                           f"已无管理权限，拒绝执行")

    # 从最近的已执行删除工单快照中还原每篇文档的删除前状态
    pre_state = _pre_delete_states(cur, list(restorable))

    sp = f"sp_rst_{row['id']}"
    restored: list[int] = []
    try:
        cur.execute(f"SAVEPOINT {sp}")
        for i in restorable:
            target_raw = pre_state.get(i) or {}
            try:
                target = DocState(target_raw.get("lifecycle_state") or "published")
            except ValueError:
                target = DocState.PUBLISHED
            updates, params = state_update_parts(target)
            cur.execute(
                f"UPDATE documents SET {', '.join(updates)} WHERE id = %s",
                tuple(params) + (i,),
            )
            restored.append(i)
    except Exception as e:
        cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
        return False, f"恢复失败（已回滚）: {e}"

    msg = f"恢复成功 {len(restored)} 篇"
    skipped = len(valid_ids) - len(restored)
    if skipped:
        msg += f"；{skipped} 篇不在回收站或已物理销毁（跳过）"
    return True, msg[:1024]


def _pre_delete_states(cur, doc_ids: list[int]) -> dict[int, dict]:
    """从最近的已执行删除工单快照还原「删除前状态」映射。

    快照在建单时冻结 status/lifecycle_state，是删除前状态的可信来源；
    逐单解析（LIMIT 200）后按 doc_id 取最近一次的快照值。
    """
    want = {int(i) for i in doc_ids}
    out: dict[int, dict] = {}
    cur.execute(
        "SELECT doc_references FROM kms_tickets "
        "WHERE module=%s AND status=%s ORDER BY id DESC LIMIT 200",
        (TICKET_MODULE_DOC_BATCH_DELETE, TICKET_STATUS_EXECUTED),
    )
    for r in cur.fetchall():
        raw = r.get("doc_references")
        if not raw:
            continue
        if isinstance(raw, str):
            try:
                refs = json.loads(raw)
            except (TypeError, ValueError):
                continue
        else:
            refs = raw
        if not isinstance(refs, list):
            continue
        for ref in refs:
            try:
                did = int(ref.get("id"))
            except (TypeError, ValueError):
                continue
            if did in want and did not in out:
                out[did] = {"status": ref.get("status"),
                            "lifecycle_state": ref.get("lifecycle_state")}
    return out


def _run_execution(cur, row: dict, operator: AuthUser) -> tuple[str, str, list]:
    """执行并写回状态；成功→executed，失败→保持 approved 待重试。

    返回 (status, msg, faiss_ids_to_remove)：FAISS 清理必须在事务提交后
    进行，故把待删 faiss_id 列表交回调用方在 with transaction() 退出后处理。
    """
    ok, msg, faiss_ids = _execute(cur, row, operator)
    status = TICKET_STATUS_EXECUTED if ok else TICKET_STATUS_APPROVED
    cur.execute(
        "UPDATE kms_tickets SET status=%s, exec_result=%s, "
        "executed_at = CASE WHEN %s THEN NOW() ELSE executed_at END "
        "WHERE id=%s",
        (status, msg, ok, row["id"]),
    )
    return status, msg, faiss_ids


def _post_commit_cleanup_faiss(faiss_ids: list[int]) -> None:
    """事务提交后清理 FAISS 向量并热更新缓存。

    非事务性资源（FAISS）只能在 MySQL 提交成功后再改；失败仅产生孤立向量，
    检索时因 documents 行不存在而被过滤，warmup 也会拦截，不影响数据安全。

    关键：Indexer 与 Retriever 持有不同的 VectorStore 实例。ingest 写入新向量
    后持久化到磁盘，此处必须先从磁盘 reload，否则会用旧内存态覆盖磁盘，
    导致新向量丢失（MySQL chunks 仍在但 FAISS 无对应向量）。
    """
    if not faiss_ids:
        return
    try:
        from kms.routes import get_retriever as _get_retriever
        store = _get_retriever().vector_store
        store.load()  # 从磁盘加载最新状态（含 ingest 刚写入的新向量）
        removed = store.remove(faiss_ids)
        if removed != len(faiss_ids):
            logger.warning(f"FAISS 清理：期望删 {len(faiss_ids)} 条，实际删 {removed} 条"
                           f"（孤立向量可由 warmup 检测）")
        store.save()
    except Exception as e:
        logger.warning(f"FAISS 向量清理失败（重启后 warmup 会检测到孤立向量）: {e}")
    # 删除后热更新内存缓存与 BM25（失败不影响删除结果，重启后自然一致）
    try:
        from kms.routes import _hot_update_caches
        _hot_update_caches()
    except Exception as e:
        logger.warning(f"删除后缓存热更新失败（重启后生效）: {e}")


# ===================== 请求模型 =====================
class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: str = Field(min_length=1, max_length=32)
    payload: Dict[str, Any] = Field(default_factory=dict)
    # 留空则由系统按「同部门 + 职级够读取」随机指派；显式指定仅保留给历史调用方。
    approver_id: Optional[int] = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comment: str = Field(default="", max_length=512)


class Reject(Decision):
    reason: str = Field(default="", max_length=512)


# ===================== 建单 =====================
def _require_doc_lifecycle(module_key: str, doc_ids: list) -> None:
    """建单前置校验：文档生命周期与模块语义一致。

    - 删除工单：目标文档必须存在且**不在回收站**（已归档的应走恢复）；
    - 恢复工单：目标文档必须存在且**在回收站**（工单删除产生的归档），
      正常业务归档与已物理销毁的文档不在此列。
    """
    ids: list[int] = []
    for raw in doc_ids:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return  # 空列表由必填校验兜底
    marks = ",".join(["%s"] * len(ids))
    with MySQLStore()._conn() as cur:
        cur.execute(
            f"SELECT d.id, d.lifecycle_state, d.archive_reason, d.filename "
            f"FROM documents d WHERE d.id IN ({marks})", tuple(ids))
        rows = {int(r["id"]): r for r in cur.fetchall()}
    for did in ids:
        r = rows.get(did)
        if r is None:
            raise HTTPException(422, f"文档 #{did} 不存在")
        if module_key == TICKET_MODULE_DOC_BATCH_DELETE \
                and r["lifecycle_state"] == "archived":
            raise HTTPException(422, f"文档「{r['filename']}」已在回收站，"
                                     f"如需找回请发起恢复工单")
        if module_key == TICKET_MODULE_DOC_RESTORE:
            if r["lifecycle_state"] != "archived":
                raise HTTPException(422, f"文档「{r['filename']}」不在回收站，"
                                         f"无需恢复")
            if not str(r.get("archive_reason") or "").startswith(_PURGE_REASON_PREFIX):
                raise HTTPException(422, f"文档「{r['filename']}」是正常归档，"
                                         f"不属于工单删除，不可通过恢复工单找回")


def _batch_delete_context(payload: Dict[str, Any]) -> tuple[int, list[str]]:
    """批量删除涉及的文档上下文：`(审批所需职级, 归属部门)`。

    职级取批次内**最高**密级——审批人必须能读取批次里的每一篇文档；
    缺密级记录的按最高密级（fail-closed），与其他判据口径一致。
    """
    ids = [int(x) for x in (payload or {}).get("doc_ids") or [] if str(x).strip().isdigit()]
    if not ids:
        raise HTTPException(400, "payload 中没有有效的文档 ID")
    placeholders = ",".join(["%s"] * len(ids))
    with MySQLStore()._conn() as cur:
        cur.execute(
            f"SELECT COALESCE(l.level, 3) AS level, d.departments FROM documents d "
            f"LEFT JOIN kms_doc_levels l ON l.document_id = d.id WHERE d.id IN ({placeholders})",
            tuple(ids))
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(400, "未找到 payload 中指定的文档")

    # 取所有文档部门集合的交集
    common_depts = None
    for r in rows:
        doc_depts = set(_parse_departments(r["departments"]))
        if common_depts is None:
            common_depts = doc_depts
        else:
            common_depts &= doc_depts
    common_depts = common_depts or set()

    if not common_depts:
        raise HTTPException(400, "批量删除的文档没有共同归属部门（审批人须来自共同部门），"
                                 "请按部门分别发起")
    return max(int(r["level"]) for r in rows), sorted(common_depts)


def _approver_for_batch_delete(payload: Dict[str, Any], exclude_user_id: int) -> dict:
    """批量删除工单的随机审批人：从合格候选里挑一个。"""
    level, departments = _batch_delete_context(payload)
    approver = acl.pick_approver(level, departments, exclude_user_id=exclude_user_id)
    if approver is None:
        raise HTTPException(409, f"无可用审批人：需要「{chr(44).join(departments)}」内、"
                                 f"安全职级不低于 L{level} 的其他在职员工")
    return approver


def _assert_no_pending_doc_ticket(cur, doc_ids: list) -> None:
    """同一文档不允许并存两张待审批单。

    现场问题：赵明远发起删除后，宁宁用自己账号对**同一篇文档**再发起删除，
    两张单都建成了、都能被批——第二张只是在重复第一张的动作，审批人却以为
    自己在独立把关，「A/B 分离」形同虚设。

    互斥范围覆盖两条链路（见 `gateway/doc_inflight.py`）：工单的删除/恢复
    与文档库的更新/回滚申请共用一个“在途席位”，否则审批人手里会同时压着
    「删掉它」和「改成 L2」两张都合规的单。判定必须在本事务内、INSERT 之前，
    且 `find_inflight_conflict` 内部会对文档行/在途单加锁读。

    这一步只兜历史单（锁表上线前创建、没有锁行的 pending 单）；真正的并发
    防线是 INSERT 之后的 `doc_inflight.acquire()`——锁行主键原子抢占。
    """
    conflict = doc_inflight.find_inflight_conflict(cur, doc_ids)
    if conflict:
        raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)


def _create_ticket(
    user: AuthUser, module_key: str, payload: Dict[str, Any],
    approver_id: Optional[int], request: Request, summary: str = "",
) -> dict:
    mod = _module_or_404(module_key)
    _validate_payload(mod, payload)

    # 模块级业务校验：事由须有实际内容且长度合理（审计留痕需要）
    if module_key in (TICKET_MODULE_DOC_BATCH_DELETE, TICKET_MODULE_DOC_RESTORE):
        reason_label = "删除原因" if module_key == TICKET_MODULE_DOC_BATCH_DELETE else "恢复原因"
        reason = str(payload.get("reason") or "").strip()
        if len(reason) < 2:
            raise HTTPException(400, f"{reason_label}至少 2 个字")
        if len(reason) > 500:
            raise HTTPException(400, f"{reason_label}不能超过 500 字")
        payload["reason"] = reason
        _require_doc_lifecycle(module_key, payload.get("doc_ids") or [])

    # 审批人确定逻辑：
    #   - 显式指定时，**必须**通过 approver_candidates() 候选池校验（与上传/更新一致）
    #     防止申请人指定一个职级不够或部门不对的人审批——等于绕过 BLP。
    #   - 未指定时，按模块规则随机指派（doc_batch_delete 走 _approver_for_batch_delete）。
    assign_mode = "系统指派"
    doc_modules = (TICKET_MODULE_DOC_BATCH_DELETE, TICKET_MODULE_DOC_RESTORE)
    if approver_id:
        if approver_id == user.id:
            raise HTTPException(400, "审批人不能是申请人本人（A/B 分离）")
        # 安全关键：校验指定审批人是否在合格候选池内（BLP + 部门 + 涉密准入）
        if module_key in doc_modules:
            level, departments = _batch_delete_context(payload)
        else:
            raise HTTPException(400, f"模块 {module_key} 不支持显式指定审批人")
        candidates = acl.approver_candidates(level, departments, exclude_user_id=user.id)
        approver = next((c for c in candidates if int(c["id"]) == int(approver_id)), None)
        if approver is None:
            raise HTTPException(
                422,
                f"指定的审批人不在合格候选名单中"
                f"（需「{', '.join(departments)}」内、安全职级不低于 L{level}、且排除本人）")
        assign_mode = "自选"
    elif module_key in doc_modules:
        approver = _approver_for_batch_delete(payload, exclude_user_id=user.id)
    else:
        raise HTTPException(400, f"模块 {module_key} 尚未定义自动指派审批人规则，请显式指定")

    ticket_no = "T" + datetime.now().strftime("%Y%m%d") + uuid.uuid4().hex[:8].upper()
    now = datetime.now()
    timeout_at = now + timedelta(minutes=_timeout_minutes(module_key))
    digest = _payload_hash(payload)
    ip = request.client.host if request.client else ""

    with MySQLStore().transaction() as cur:
        # 文档类工单互斥：同一篇文档已有在途的删除/恢复单时直接 409。
        # 必须在事务内、INSERT 之前（判据 + 插入要原子，否则并发建单会双双通过）。
        if module_key in (TICKET_MODULE_DOC_BATCH_DELETE, TICKET_MODULE_DOC_RESTORE):
            _assert_no_pending_doc_ticket(cur, payload.get("doc_ids") or [])
        # 关联文档快照：建单时把元信息冻结下来，避免后续（回收/销毁）文档
        # 不可见时详情页只剩一份裸 payload JSON——申请人/审批人都没法看清楚
        # "当初要操作的是啥"。快照是 WORM 审计链的一部分，只读不改；
        # 恢复工单还依赖它还原「删除前状态」。
        doc_refs_snapshot = None
        if module_key in (TICKET_MODULE_DOC_BATCH_DELETE, TICKET_MODULE_DOC_RESTORE):
            doc_refs_snapshot = _snapshot_doc_refs(cur, payload.get("doc_ids") or [])

        cur.execute(
            "INSERT INTO kms_tickets (ticket_no, module, category, flow, applicant_id, "
            "applicant_no, applicant_name, payload, payload_summary, original_hash, "
            "approver_id, approver_no, approver_name, doc_references, status, timeout_at, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
            (ticket_no, module_key, mod["category"], mod["flow"], user.id,
             user.employee_no, user.username,
             json.dumps(payload, ensure_ascii=False),
             (summary or mod["label"])[:512], digest,
             approver["id"], approver.get("employee_no", ""), approver.get("username", ""),
             json.dumps(doc_refs_snapshot, ensure_ascii=False) if doc_refs_snapshot is not None else None,
             TICKET_STATUS_PENDING, timeout_at),
        )
        ticket_id = cur.lastrowid
        if module_key in doc_modules:
            # 业务悲观锁：在锁表上原子抢位（INSERT IGNORE + 主键冲突即已被占），
            # 抢不到就抛 409 让整个事务回滚——工单行与已抢到的锁行一起消失。
            conflict = doc_inflight.acquire(
                cur, payload.get("doc_ids") or [],
                ref_type=doc_inflight.REF_TICKET, ref_id=ticket_id, ref_no=ticket_no,
                action_label=doc_inflight.ticket_action_label(module_key),
                owner_id=user.id, owner_name=user.username, expires_at=timeout_at)
            if conflict:
                raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)
        cur.execute(f"SELECT {_TICKET_COLS} FROM kms_tickets WHERE id=%s", (ticket_id,))
        row = cur.fetchone()

    # 快照哈希入 WORM 审计：工单表本身可被 DBA 改动，但 WORM 审计日志
    # 只追加。此后任何人核对 doc_references 是否被篡改，重算哈希对账即可。
    snapshot_audit = ""
    if doc_refs_snapshot is not None:
        snap_sha = hashlib.sha256(
            json.dumps(doc_refs_snapshot, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        snapshot_audit = f" 快照SHA256={snap_sha}"
    acl.add_audit(user, AUDIT_TICKET_CREATE, f"ticket:{ticket_no}",
                  f"模块={module_key}（{assign_mode}）审批人={approver.get('employee_no','')}"
                  f"{snapshot_audit}", ip)
    acl.add_notification(
        # 通知实际指派的审批人（approver["id"]），不能用请求参数 approver_id——
        # 随机指派时它为 None，会导致通知写入失败（user_id 非空约束）。
        approver["id"], "待审批工单",
        f"{user.username} 提交了「{mod['label']}」工单 {ticket_no}",
        ticket_id=ticket_id,
    )
    return _ticket_out(row, user)


def _validate_payload(mod: dict, payload: Dict[str, Any]) -> None:
    """按模块 schema 校验必填字段；未知字段不做拒绝（schema 可能演进）。"""
    for f in mod.get("schema", []):
        if not f.get("required"):
            continue
        v = payload.get(f["name"])
        if v is None or v == "" or (isinstance(v, list) and not v):
            raise HTTPException(400, f"缺少必填项: {f['label']}")


# ===================== 端点：目录与选项 =====================
@router.get("/tickets/modules")
def ticket_modules(user: AuthUser = Depends(require_user)):
    """工单模块目录（前端按 category / flow / schema 渲染发起表单）。"""
    return {"items": list(TICKET_MODULES.values())}


@router.get("/tickets/recycle-bin")
def recycle_bin(user: AuthUser = Depends(require_user)):
    """回收站列表：工单删除产生、宽限期内可恢复的归档文档。

    只返回当前用户可管理的（上传者本人或同部门且职级可读——与删除工单
    申请人同判据），每篇附带剩余宽限天数，供恢复工单表单与审计展示。
    """
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT d.id AS document_id, d.filename, d.title, d.departments, "
            "COALESCE(l.level, 3) AS classification, d.status, d.lifecycle_state, "
            "d.archived_at, d.archive_reason, l.granted_by, "
            f"GREATEST(0, {_DELETE_RETENTION_DAYS} - "
            "DATEDIFF(NOW(), d.archived_at)) AS days_left "
            "FROM documents d "
            "LEFT JOIN kms_doc_levels l ON l.document_id = d.id "
            "WHERE d.lifecycle_state='archived' AND d.archive_reason LIKE %s "
            "ORDER BY d.archived_at DESC LIMIT 200",
            (_PURGE_REASON_PREFIX + "%",),
        )
        items = []
        for r in cur.fetchall():
            if not (acl.can_approve_document(
                    user, int(r["classification"]), _parse_departments(r["departments"]))
                    or (r.get("granted_by") is not None
                        and int(r["granted_by"]) == int(user.id))):
                continue
            items.append(r)
    return {"items": items, "retention_days": _DELETE_RETENTION_DAYS}


@router.get("/tickets/options")
def ticket_options(user: AuthUser = Depends(require_user)):
    """表单选项数据源：密级 / 文档 / 员工。

    职责（duties）选项已随 user_duty_grant 模块一并下线——审批权改由
    部门 + 安全职级派生，不再需要表单里挑职责。

    文档只返回**当前用户按 BLP 可读**的：缺密级记录视为最高密级（fail-closed）。
    可见范围以归属部门为准——“*”（不限部门）全员可见；指定部门的文档
    只出现在该部门用户的候选列表里；L0 也不再因密级而绕过部门。
    """
    levels = [{"level": lv, "label": label} for lv, label, _ in acl.FIXED_LEVELS]
    # 部门名归一化后入参，容错 HR 台账里的空格（「综合 管理部」≡「综合管理部」）
    dept = normalize_department(user.department or "")
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT d.id, d.filename AS label FROM documents d "
            "LEFT JOIN kms_doc_levels l ON l.document_id = d.id "
            "WHERE COALESCE(l.level, 3) <= %s "
            "  AND ("
            "    JSON_CONTAINS(COALESCE(d.departments,JSON_ARRAY()), JSON_QUOTE(%s)) "
            "    OR JSON_CONTAINS(COALESCE(d.departments,JSON_ARRAY()), JSON_QUOTE(%s)) "
            "    OR (d.departments IS NULL AND ("
            "         d.owner_department = %s OR d.owner_department = %s "
            "         OR JSON_CONTAINS(COALESCE(d.extra_departments,JSON_ARRAY()), JSON_QUOTE(%s))"
            "    ))"
            "  ) "
            "ORDER BY d.id DESC LIMIT 200",
            (user.security_level, DOC_DEPT_UNLIMITED, dept, dept, DOC_DEPT_UNLIMITED, dept),
        )
        documents = cur.fetchall()
        cur.execute(
            "SELECT id, username, employee_no, security_level AS level, department "
            "FROM kms_users WHERE is_active = 1 ORDER BY employee_no LIMIT 500",
        )
        employees = cur.fetchall()
    for e in employees:
        e["level_name"] = f"L{e.get('level', 0)}"
    return {"levels": levels, "documents": documents,
            "employees": employees}


# 注：原 GET /tickets/candidates（返回持 ticket_approve 职责的人）已移除。
# 审批人不再由申请人挑选——可预测的选择会让人钻空子，也让两处真相漂移
# （职责名单说能审，BLP 说看不见）。新建单统一走系统随机指派。


# ===================== 端点：列表 =====================
@router.get("/tickets/mine")
def tickets_mine(user: AuthUser = Depends(require_user)):
    """我发起的工单。

    注：策略变更申请（申请更新文档）由前端并行调 /governance/requests 后合并展示，
    此处**不**重复 merge，避免同一记录在工单中心出现两次。
    """
    return _list_with_sweep("applicant_id=%s", (user.id,), user)


@router.get("/tickets/pending-approval")
def tickets_pending_approval(user: AuthUser = Depends(require_user)):
    """待我审批的工单（策略变更申请由前端 governance 通道并入，不在此 merge）。"""
    return _list_with_sweep("approver_id=%s AND status=%s",
                            (user.id, TICKET_STATUS_PENDING), user)


@router.get("/tickets/done")
def tickets_done(user: AuthUser = Depends(require_user)):
    """已结束的工单（策略变更申请的历史记录由前端 governance 通道并入）。"""
    placeholders = ",".join(["%s"] * len(_TERMINAL_STATUSES))
    return _list_with_sweep(
        f"(applicant_id=%s OR approver_id=%s) AND status IN ({placeholders})",
        (user.id, user.id) + _TERMINAL_STATUSES, user)


# ===================== 端点：建单 =====================
@router.post("/tickets", status_code=201)
def create_ticket(req: TicketCreate, request: Request,
                  user: AuthUser = Depends(require_user)):
    """发起工单（任何在职员工都可以发起——工单不是管理员特权）。"""
    out = _create_ticket(user, req.module, req.payload, req.approver_id, request)
    return {**out, "message": f"工单已提交：{out['ticket_no']}"}


def _rows_from_file(content: bytes, filename: str, module: str) -> List[dict]:
    """解析批量上传文件（csv / xlsx）。"""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [dict(r) for r in csv.DictReader(io.StringIO(text))]
    if name.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise HTTPException(415, "服务端未安装 openpyxl，无法解析 xlsx，请改用 csv")
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return []
        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        out = []
        for r in rows[1:]:
            if r is None or all(c is None or str(c).strip() == "" for c in r):
                continue
            out.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
        return out
    raise HTTPException(415, "仅支持 .csv / .xlsx / .xlsm 文件")


@router.post("/tickets/batch-upload", status_code=201)
def batch_upload_ticket(
    file: UploadFile = File(...),
    module: str = Form(...),
    # 留空则由系统随机指派审批人（推荐）；显式指定仅保留给历史调用方。
    approver_id: Optional[int] = Form(None),
    reason: str = Form(""),
    request: Request = None,
    user: AuthUser = Depends(require_user),
):
    """文件批量发起工单。

    解析出的行内容**写进工单 payload**（数据库持久化），原始附件不落盘，
    因此 `/tickets/{id}/files/{index}` 不提供下载——内容以 payload 为准。
    """
    mod = _module_or_404(module)
    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "批量文件不能超过 5MB")
    rows = _rows_from_file(content, file.filename, module)
    if not rows:
        raise HTTPException(400, "文件中没有有效数据行")

    if module == TICKET_MODULE_DOC_BATCH_DELETE:
        ids = []
        for r in rows:
            v = r.get("document_id") or r.get("文档ID") or r.get("id")
            if v is None or str(v).strip() == "":
                continue
            ids.append(str(v).strip())
        if not ids:
            raise HTTPException(400, "未找到 document_id/文档ID 列")
        payload = {"doc_ids": ids, "reason": reason}
    else:
        # 员工职责授予（user_duty_grant）的批量分支已随模块移除。
        raise HTTPException(400, f"模块 {module} 不支持文件批量导入")

    out = _create_ticket(user, module, payload, approver_id, request,
                         summary=f"{mod['label']}（批量 {len(rows)} 行）")
    return {**out, "message": f"批量工单已提交：{out['ticket_no']}"}


# ===================== 端点：详情与流转 =====================
@router.get("/tickets/{ticket_id}")
def ticket_detail(ticket_id: int, user: AuthUser = Depends(require_user)):
    with MySQLStore()._conn() as cur:
        row = _load_ticket(cur, ticket_id)
        if row["applicant_id"] != user.id and row["approver_id"] != user.id:
            raise HTTPException(403, "只能查看自己发起或由自己审批的工单")
        out = _ticket_out(row, user)
        # 详情页 enrich：给快照加 can_view + 内容预览片段——申请人/审批人
        # 都通过了工单归属校验，但文档正文仍须过 BLP 读权限（BLP 不上读）。
        refs = out.get("doc_references") or []
        if not refs:
            # 兼容历史工单（建单时还没有 doc_references 快照列）：从 payload.doc_ids
            # 实时查询文档元信息用于展示，不回写库。已被删除的文档查不到即为不存在，
            # 与「冻结快照」相比少了删除后的留痕能力，故标记 snapshot=False 供前端区分。
            payload = out.get("payload")
            doc_ids = payload.get("doc_ids") if isinstance(payload, dict) else None
            if doc_ids:
                refs = _snapshot_doc_refs(cur, doc_ids)
                for r in refs:
                    r["snapshot"] = False
        if refs:
            out["doc_references"] = _enrich_doc_refs(cur, refs, user)
    return out


@router.post("/tickets/{ticket_id}/approve")
def approve_ticket(ticket_id: int, req: Decision, request: Request,
                   user: AuthUser = Depends(require_user)):
    """审批通过 → 系统自动执行（two_step 无独立执行人）。

    执行前比对 payload 哈希：审批后内容若被改动，标记 tampered 并拒绝执行。
    """
    ip = request.client.host if request.client else ""
    with MySQLStore().transaction() as cur:
        row = _load_ticket(cur, ticket_id, lock=True)
        if row["approver_id"] != user.id:
            raise HTTPException(403, "只有指定的审批人可以审批该工单")
        if row["status"] != TICKET_STATUS_PENDING:
            raise HTTPException(409, f"工单当前状态为 {row['status']}，不可审批")
        # 建单后人员可能变动（部门/职级），审批时按同一判据重新校验，
        # 而不是信任建单那一刻的结果。
        if row["module"] in (TICKET_MODULE_DOC_BATCH_DELETE, TICKET_MODULE_DOC_RESTORE):
            level, department = _batch_delete_context(_parse_payload(row))
            if not acl.can_approve_document(user, level, department):
                raise HTTPException(403, "你的部门或安全职级已变动，不再具备审批该工单的资格")

        digest = _payload_hash(_parse_payload(row))
        if digest != (row.get("original_hash") or ""):
            cur.execute(
                "UPDATE kms_tickets SET status=%s, reason=%s, approved_hash=%s, "
                "approve_comment=%s WHERE id=%s",
                (TICKET_STATUS_TAMPERED, "提交后内容被修改，已拦截执行", digest,
                 req.comment[:512], ticket_id),
            )
            acl.add_audit(user, AUDIT_TICKET_APPROVE, f"ticket:{row['ticket_no']}",
                          "哈希不一致，篡改拦截", ip)
            # 单据落入 tampered 终态，在途席位不再需要
            doc_inflight.release(cur, ref_type=doc_inflight.REF_TICKET,
                                 ref_id=ticket_id)
            return {"status": TICKET_STATUS_TAMPERED, "message": "内容已被修改，已拦截执行"}

        cur.execute(
            "UPDATE kms_tickets SET status=%s, approved_hash=%s, approve_comment=%s, "
            "approved_at=NOW() WHERE id=%s",
            (TICKET_STATUS_APPROVED, digest, req.comment[:512], ticket_id),
        )
        row["status"] = TICKET_STATUS_APPROVED
        status, msg, faiss_ids = _run_execution(cur, row, user)
        # 审批已落库（executed，或执行失败停在 approved 待重试），在途席位随即
        # 释放：「一篇文档一张待审批单」约束的只是 pending。
        doc_inflight.release(cur, ref_type=doc_inflight.REF_TICKET, ref_id=ticket_id)

    # 事务提交成功后再清理 FAISS（非事务性资源，失败仅产生无害孤立向量）
    _post_commit_cleanup_faiss(faiss_ids)
    acl.add_audit(user, AUDIT_TICKET_APPROVE, f"ticket:{row['ticket_no']}",
                  f"审批通过并自动执行: {msg}", ip)
    acl.add_notification(row["applicant_id"], "工单已审批",
                         f"{row['ticket_no']} 审批通过，执行结果: {msg}",
                         ticket_id=ticket_id)
    return {"status": status, "message": msg}


@router.post("/tickets/{ticket_id}/reject")
def reject_ticket(ticket_id: int, req: Reject, request: Request,
                  user: AuthUser = Depends(require_user)):
    ip = request.client.host if request.client else ""
    with MySQLStore().transaction() as cur:
        row = _load_ticket(cur, ticket_id, lock=True)
        if row["approver_id"] != user.id:
            raise HTTPException(403, "只有指定的审批人可以驳回该工单")
        if row["status"] != TICKET_STATUS_PENDING:
            raise HTTPException(409, f"工单当前状态为 {row['status']}，不可驳回")
        cur.execute(
            "UPDATE kms_tickets SET status=%s, reason=%s, approve_comment=%s WHERE id=%s",
            (TICKET_STATUS_REJECTED, (req.reason or req.comment)[:512],
             req.comment[:512], ticket_id),
        )
        doc_inflight.release(cur, ref_type=doc_inflight.REF_TICKET, ref_id=ticket_id)
    acl.add_audit(user, AUDIT_TICKET_REJECT, f"ticket:{row['ticket_no']}",
                  req.reason or req.comment, ip)
    acl.add_notification(row["applicant_id"], "工单被驳回",
                         f"{row['ticket_no']} 已被驳回: {req.reason or req.comment}",
                         ticket_id=ticket_id)
    return {"status": TICKET_STATUS_REJECTED, "message": "已驳回"}


@router.post("/tickets/{ticket_id}/cancel")
def cancel_ticket(ticket_id: int, request: Request,
                  user: AuthUser = Depends(require_user)):
    """申请人撤回（仅限自己发起且仍在待审批的工单）。"""
    ip = request.client.host if request.client else ""
    with MySQLStore().transaction() as cur:
        row = _load_ticket(cur, ticket_id, lock=True)
        if row["applicant_id"] != user.id:
            raise HTTPException(403, "只能撤回自己发起的工单")
        if row["status"] != TICKET_STATUS_PENDING:
            raise HTTPException(409, f"工单当前状态为 {row['status']}，不可撤回")
        cur.execute("UPDATE kms_tickets SET status=%s WHERE id=%s",
                    (TICKET_STATUS_CANCELLED, ticket_id))
        doc_inflight.release(cur, ref_type=doc_inflight.REF_TICKET, ref_id=ticket_id)
    acl.add_audit(user, AUDIT_TICKET_CANCEL, f"ticket:{row['ticket_no']}", "", ip)
    return {"status": TICKET_STATUS_CANCELLED, "message": "已撤回"}


@router.get("/tickets/{ticket_id}/escalation-token")
def escalation_token(ticket_id: int, user: AuthUser = Depends(require_user)):
    """提权令牌——提权概念已从系统中移除，不再发放。"""
    raise HTTPException(404, "提权功能已移除，不再提供提权令牌")


@router.get("/tickets/{ticket_id}/files/{index}")
def ticket_file(ticket_id: int, index: int, user: AuthUser = Depends(require_user)):
    """批量上传的原始附件。

    批量内容在建单时已解析进工单 payload 并持久化，原始文件不落盘，
    故此处不提供下载——请从工单详情的 payload 查看。
    """
    raise HTTPException(404, "批量内容已解析进工单 payload，原始附件未持久化")


# ===================== 站内通知（工单流转结果告知） =====================
@router.get("/notifications")
def list_notifications(limit: int = Query(50, ge=1, le=200),
                       user: AuthUser = Depends(require_user)):
    items = acl.list_notifications(user.id, limit)
    for n in items:
        n["created_at"] = _s(n.get("created_at"))
    return {"items": items}


@router.get("/notifications/unread-count")
def unread_count(user: AuthUser = Depends(require_user)):
    return {"count": acl.unread_notification_count(user.id)}


@router.post("/notifications/{notif_id}/read")
def read_notification(notif_id: int, user: AuthUser = Depends(require_user)):
    if not acl.mark_notification_read(notif_id, user.id):
        raise HTTPException(404, "通知不存在")
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all_notifications(user: AuthUser = Depends(require_user)):
    return {"updated": acl.mark_all_notifications_read(user.id)}
