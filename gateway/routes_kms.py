"""企业受控业务入口：员工问答、授权文档、双人发布、机器人绑定。

旧管理模块的存储与检索组件保留；未经整改的 HTTP 写入入口不挂载。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import uuid
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from app.logger import get_logger
from app.store import MySQLStore
from config import settings
from kms import access_control as acl
from kms.constants import (AUDIT_DOC_DOWNLOAD, AUDIT_DOC_UPDATE, DOC_DEPT_UNLIMITED,
                           DEPARTMENTS, normalize_department)
from kms.formats import is_allowed
from kms.security import AuthUser, require_user, revalidate_bearer
from . import doc_inflight, identity, service, state
from .routes_embed import EmbedFeedbackRequest

logger = get_logger("gateway.kms")

router = APIRouter(prefix="/kms/api", tags=["enterprise-controlled"])
_ingest_lock = threading.Lock()


class KmsChatRequest(BaseModel):
    """员工问答请求：允许 session_id 继续已有会话（后端校验归属）。"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)
    session_id: Optional[str] = Field(default=None, max_length=64)


def initialize():
    # 治理基础表（员工/工单/密级/审计）先就绪：在途锁回填要读 kms_tickets /
    # kms_users，缺表就回填不了。幂等，已建则直接返回。
    acl.ensure_kms_acl_tables()
    with MySQLStore().transaction() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS kms_policy_requests (
            id VARCHAR(32) PRIMARY KEY, document_id BIGINT NOT NULL,
            requested_by BIGINT NOT NULL, approved_by BIGINT NULL,
            snapshot VARCHAR(64) NOT NULL, policy JSON NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending', request_id VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME NULL, INDEX policy_doc(document_id,status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        # 迁移：新增「随机指派的审批人」。旧行保持 NULL，decide() 会明确拒绝并
        # 提示重新发起——不给历史单据凭空指派一个审批人，那是事后补责任人。
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='kms_policy_requests' "
                    "AND COLUMN_NAME='approver_id'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE kms_policy_requests ADD COLUMN approver_id BIGINT NULL "
                        "COMMENT '随机指派的审批人（同部门且职级可读取该文档）' AFTER requested_by")
            logger.info("Schema 迁移: kms_policy_requests 新增 approver_id")
        # 文档在途业务锁（一篇文档一张待审批单）。锁表缺失时 acquire() 直接报错，
        # 所以必须与服务一起初始化，不能靠「第一次抢锁时再建」。
        doc_inflight.ensure_schema(cur)
        # 把锁表上线前就在审的 pending 单补登记成锁行，否则锁表一开始就是
        # 残缺的（只能靠扫描单据表兜底），排查「为什么提交不了」会绕圈。
        repaired = doc_inflight.backfill(cur)
        if repaired:
            logger.info(f"在途锁回填: 为历史 pending 单补登记 {repaired} 个文档锁")


def auditor(user: AuthUser = Depends(require_user)):
    """运营审计（本系统无「管理员」角色，见 kms/constants.py）。

    守 admin/ 前缀下的只读入口，以及应用注册/密钥轮换等平台治理动作。
    对业务内容（文档、问答）不额外授权——那部分由 BLP 与双人审批决定。
    """
    if not user.is_auditor:
        raise HTTPException(403, "需要运营审计权限")
    return user


def editor(user: AuthUser = Depends(require_user)):
    """发起文档变更的准入。

    本系统**所有在职员工均可申请**删除 / 导入 / 改变密级，把关不靠身份
    白名单，而靠后续双人审批（A/B 分离 + 同部门或不限 + 职级足够 +
    HR 涉密准入）。此处只要求有归属部门——没有部门就无法界定
    「这是谁的地盘」，部门隔离与跨部门审批校验都无从谈起。
    """
    if not user.department:
        raise HTTPException(403, "需要归属部门才能发起文档变更")
    return user


def document_row(cur, doc_id, lock=False):
    cur.execute("SELECT d.id AS document_id,d.filename,d.title,d.file_type,d.content_hash,"
                "d.departments,d.owner_department,d.extra_departments,d.status,d.lifecycle_state,d.expires_at,"
                "d.publication_approved,d.created_at,"
                "(d.expires_at IS NOT NULL AND d.expires_at<=NOW()) AS expired,"
                "l.level AS classification,l.granted_by AS granted_by "
                "FROM documents d LEFT JOIN kms_doc_levels l "
                "ON l.document_id=d.id WHERE d.id=%s" + (" FOR UPDATE" if lock else ""), (doc_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "文档不存在")
    return row


def snapshot(row):
    # expired 是时钟派生值，不参加版本快照；expires_at 已覆盖变更。
    data = {k: v for k, v in row.items() if k != "expired"}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _resolve_departments(row) -> list:
    """从文档行解析归属部门数组。优先新字段 departments，回退旧字段合并。"""
    departments = row.get("departments")
    if departments:
        if isinstance(departments, str):
            try:
                departments = json.loads(departments)
            except (TypeError, ValueError):
                departments = []
        if isinstance(departments, list) and departments:
            return departments
    # 回退：合并旧字段
    old_dept = row.get("owner_department") or ""
    old_extra = row.get("extra_departments") or []
    if isinstance(old_extra, str):
        try:
            old_extra = json.loads(old_extra)
        except (TypeError, ValueError):
            old_extra = []
    result = []
    if old_dept:
        result.append(old_dept)
    if isinstance(old_extra, list):
        result.extend(old_extra)
    return result


def manageable(row, user):
    """能否管理该文档。

    判据(满足任一即可):
    1. 上传者本人(granted_by == user.id):上传者对自己上传的文档始终有管理权,
       即使归属到其他部门——否则跨部门上传的文档会永远卡在 draft 无法提交审批。
    2. acl.can_approve_document:员工部门 IN 文档归属部门数组 + 职级足够(BLP 不上读)。
    """
    if user is None:
        return False
    granted_by = row.get("granted_by")
    if granted_by is not None and int(granted_by) == int(user.id):
        return True
    departments = _resolve_departments(row)
    return acl.can_approve_document(user, row.get("classification"), departments)


def _recommend_call(fn) -> None:
    """推荐埋点统一容错包装：任何埋点失败都不得影响主业务返回。"""
    try:
        from kms import recommend
        fn(recommend)
    except Exception:
        pass


def _s(v) -> Optional[str]:
    return None if v is None else str(v)


def _parse_departments_form(value: str) -> list[str]:
    """解析前端上传表单里的归属部门 JSON 数组字符串。"""
    if not value or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, str):
        return [parsed]
    if isinstance(parsed, list):
        return [str(x) for x in parsed if x is not None]
    return []


@router.post("/chat")
def chat(req: KmsChatRequest, request: Request, user: AuthUser = Depends(require_user)):
    """员工问答。

    默认返回 JSON；当 query 参数 stream=true 时返回 SSE 流式响应（text/event-stream），
    逐块推送答案文本，最后一条 done 事件携带 sources/session_id/message_id。
    """
    from app.store import MySQLStore
    from kms import access_control as acl

    # 会话归属：客户端不传则后端生成；传了则校验归当前用户所有
    session_id = req.session_id or uuid.uuid4().hex
    if req.session_id:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "SELECT user_id FROM kms_chat_owners WHERE session_id=%s",
                (req.session_id,),
            )
            row = cur.fetchone()
            if not row or int(row["user_id"]) != user.id:
                raise HTTPException(403, "会话不存在或不属于当前员工")

    # 流式分支：SSE 逐块返回
    if request.query_params.get("stream", "").lower() in ("1", "true", "yes"):
        def event_generator():
            full_answer = ""
            sources = []
            try:
                for evt in service.answer_stream(req.question, user, 0, user.security_level):
                    if evt["type"] == "chunk":
                        full_answer += evt["content"]
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    elif evt["type"] == "error":
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                        return
                    elif evt["type"] == "done":
                        full_answer = evt.get("answer", full_answer)
                        sources = evt.get("sources", [])
                        # 持久化问答历史并关联用户
                        try:
                            with MySQLStore()._conn() as cur:
                                cur.execute(
                                    "INSERT INTO chat_history (session_id, question, answer, sources) "
                                    "VALUES (%s, %s, %s, %s)",
                                    (session_id, req.question, full_answer,
                                     json.dumps(sources, ensure_ascii=False)),
                                )
                            acl.set_chat_owner(session_id, user.id)
                        except Exception as e:
                            logger.warning(f"问答历史写入失败: {e}")

                        revalidate_bearer(request, user)
                        message_id = state.receipt(f"kms:{user.id}")
                        doc_ids = [s.get("document_id") for s in sources if s.get("document_id")]
                        _recommend_call(lambda rc: rc.record_answer_sources(user, message_id, doc_ids))

                        meta = {
                            "type": "done",
                            "answer": full_answer,
                            "sources": sources,
                            "message_id": message_id,
                            "session_id": session_id,
                        }
                        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
                        return
            except HTTPException as e:
                yield f"data: {json.dumps({'type': 'error', 'message': e.detail}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"流式问答异常: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': '服务异常'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # 非流式分支：原有 JSON 响应
    result = service.answer(req.question, user, 0, user.security_level)

    # 持久化问答历史并关联用户
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "INSERT INTO chat_history (session_id, question, answer, sources) "
                "VALUES (%s, %s, %s, %s)",
                (session_id, req.question, result.get("answer", ""),
                 json.dumps(result.get("sources") or [], ensure_ascii=False)),
            )
        acl.set_chat_owner(session_id, user.id)
    except Exception as e:
        logger.warning(f"问答历史写入失败: {e}")

    revalidate_bearer(request, user)
    message_id = state.receipt(f"kms:{user.id}")
    doc_ids = [s.get("document_id") for s in (result.get("sources") or []) if s.get("document_id")]
    _recommend_call(lambda rc: rc.record_answer_sources(user, message_id, doc_ids))
    return dict(result, message_id=message_id, session_id=session_id, history=True)


@router.post("/feedback")
def feedback(req: EmbedFeedbackRequest, user: AuthUser = Depends(require_user)):
    if not state.feedback(f"kms:{user.id}", req.message_id, req.rating, req.comment):
        raise HTTPException(404, "回执不存在或不属于当前员工")
    _recommend_call(lambda rc: rc.apply_feedback(user, req.message_id, req.rating))
    return {"ok": True}


@router.get("/conversations")
def list_conversations(limit: int = Query(50, ge=1, le=200),
                       user: AuthUser = Depends(require_user)):
    """当前员工的会话列表（按最后消息时间倒序）。"""
    from app.store import MySQLStore
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT h.session_id, "
            "  SUBSTRING(MAX(h.question), 1, 50) AS title, "
            "  MAX(h.created_at) AS last_at, "
            "  COUNT(*) AS msg_count "
            "FROM chat_history h "
            "JOIN kms_chat_owners o ON h.session_id = o.session_id "
            "WHERE o.user_id = %s "
            "GROUP BY h.session_id "
            "ORDER BY MAX(h.created_at) DESC "
            "LIMIT %s",
            (user.id, limit),
        )
        rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({
            "session_id": r["session_id"],
            "summary": r["title"] or "(空会话)",
            "last_time": _s(r.get("last_at")),
            "msg_count": int(r["msg_count"]),
            "feedback": {"up": 0, "down": 0},
        })
    return {"items": items}


@router.get("/conversations/{session_id}/history")
def conversation_history(session_id: str, limit: int = Query(100, ge=1, le=500),
                         user: AuthUser = Depends(require_user)):
    """指定会话的消息历史（仅限会话所有者）。"""
    from app.store import MySQLStore
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT user_id FROM kms_chat_owners WHERE session_id=%s",
            (session_id,),
        )
        row = cur.fetchone()
        if not row or int(row["user_id"]) != user.id:
            raise HTTPException(403, "会话不存在或不属于当前员工")
        cur.execute(
            "SELECT id, question, answer, sources, created_at "
            "FROM chat_history WHERE session_id=%s ORDER BY id ASC LIMIT %s",
            (session_id, limit),
        )
        rows = cur.fetchall()
    items = []
    for r in rows:
        src = r.get("sources")
        if isinstance(src, str):
            try:
                src = json.loads(src)
            except Exception:
                src = []
        items.append({
            "id": r["id"],
            "question": r["question"],
            "answer": r["answer"],
            "sources": src or [],
            "created_at": _s(r.get("created_at")),
            "feedback": None,
        })
    return {"items": items}



@router.get("/documents")
def documents(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
              sort: str = Query("asc", pattern="^(asc|desc)$"),
              q: str = Query("", max_length=60),
              user: AuthUser = Depends(require_user)):
    """工作台文档库列表。

    只回已发布文档，**含本人草稿也不回**。产品口径：上传 / 更新 / 回滚这些
    动作的「进行中」状态在**工单中心**看（一条带操作类型的单据），文档库只
    呈现审批通过后的结果。两边各管一件事，不在文档库里重复展示待审草稿。

    sort 默认 asc（按文档编号从小到大）；需要「最新在前」的视图（如仪表盘的
    最近入库）显式传 desc。用 pattern 而非自由字符串，避免入参进入 SQL 拼接。

    q 是标题/文件名的全库关键字过滤（服务端 LIKE），不能交给前端页内筛：
    列表正序分页，新审批通过的文档总在末页，页内筛选会让人以为「审批通过了
    却没入库」。
    """
    return service.documents(user, 0, user.security_level, offset, limit, order=sort, keyword=q)


def _dept_max_levels(depts: list[str]) -> dict[str, int]:
    """各部门在职员工的最高安全职级，**只用于「为什么没人可审」的提示**。

    用户最常遇到的情况不是「系统坏了」，而是「这个部门里根本没这么高职级的人」
    （例如财务管理部最高 L2，却要把文档定成 L3 绝密）。不把这句话讲出来，
    用户只会看到候选人里冒出了别的部门的人，以为匹配逻辑错了。

    归一化口径与 acl.approver_candidates 一致（去空白后比对），否则 HR 台账
    里带空格的部门名会查不到，提示反而错写成「该部门无人」。
    """
    norm = {d: normalize_department(d) for d in depts if d and d != DOC_DEPT_UNLIMITED}
    if not norm:
        return {}
    values = tuple(sorted(set(norm.values())))
    norm_sql = "REPLACE(REPLACE(REPLACE(department,' ',''),'　',''),'\t','')"
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                f"SELECT {norm_sql} AS dept, MAX(security_level) AS lv FROM kms_users "
                f"WHERE is_active=1 AND {norm_sql} IN ({','.join(['%s'] * len(values))}) "
                "GROUP BY dept", values)
            rows = {r["dept"]: int(r["lv"]) for r in cur.fetchall()}
    except Exception:
        return {}
    return {d: rows.get(n, -1) for d, n in norm.items()}


@router.get("/documents/approver-candidates")
def approver_candidates(classification: int = Query(0, ge=0, le=3),
                        departments: str = Query(""),  # JSON 数组字符串
                        user: AuthUser = Depends(require_user)):
    """返回可选审批人列表（根据密级 + 归属部门数组联动匹配）。

    候选条件与 propose / _auto_submit_for_approval 完全一致：
      - 安全职级 >= 文档密级（BLP 不上读）
      - 员工部门 IN 文档归属部门数组（不限部门则全员候选）
      - 涉密文档另需 HR 涉密准入资格
      - 排除当前用户本人（自审批禁止）

    **归属部门是审批人归属的唯一依据，这里不猜。** 曾经在 departments 缺省时
    回落「申请人本人部门」，后果是：用户选了财务管理部、却因为前端漏传或默认值
    残留拿着产品管理部的候选池，表现为「我要财务部审，系统却只给我产品部的人」。
    未声明部门 → 返回空列表 + 可读提示，让前端说得清原因。

    前端上传区下拉框和申请更新/回滚弹窗均消费此接口，保证「能选的人」和
    「后端会接受的人」始终一致——不会出现前端选了、后端却拒的情况。

    注意：此路由必须在 /documents/{doc_id} 之前注册，否则
    "approver-candidates" 会被 FastAPI 当作 doc_id 解析导致 422。
    """
    depts = _parse_departments_form(departments)
    if not depts:
        return {"items": [], "classification": classification, "departments": [],
                "reason": "请先选择归属部门：审批人只从归属部门内派生（职级不低于密级）"}
    candidates = acl.approver_candidates(classification, depts, exclude_user_id=user.id)
    items = [
        {"id": c["id"], "employee_no": c["employee_no"], "username": c["username"],
         "security_level": c["security_level"],
         # HR 台账里部门名常带首尾空格（实测「财务管理部 」），下拉框会显示成
         # 「财务管理部  L2」两个空格。匹配侧已归一化，展示侧只去首尾空格。
         "department": (c.get("department") or "").strip(),
         "business_title": c.get("business_title", "")}
        for c in candidates
    ]
    reason = ""
    if not items:
        if DOC_DEPT_UNLIMITED in depts:
            reason = (f"任意部门内都没有 L{classification} 及以上的在职审批人"
                      "（需非本人；涉密文档还要求已签保密承诺、过背景审查）")
        else:
            levels = _dept_max_levels(depts)
            low = [f"{d}（最高 L{v}）" for d, v in levels.items() if 0 <= v < classification]
            if low:
                reason = (f"{'、'.join(low)} 的职级低于文档密级 L{classification}，"
                          f"该部门内没人能审这篇文档：请降低密级，或指定更高级别的归属部门")
            else:
                reason = (f"{'、'.join(depts)} 内有 L{classification} 及以上员工，"
                          "但都不满足条件（可能只有申请人本人，或未签保密承诺/未过背景审查）")
    return {"items": items, "classification": classification, "departments": depts,
            "reason": reason}


@router.get("/documents/{doc_id}")
def document(doc_id: int, user: AuthUser = Depends(require_user)):
    with MySQLStore().transaction() as cur:
        row = document_row(cur, doc_id)
        # 已发布文档按 BLP 放行；未发布（草稿/待审批）文档仅管理者/审批人可见，
        # 确保删除/更新/入库审批人能查看文档内容后再做决策。
        can_read = service.allowed(row, user, 0, user.security_level)
        if not can_read and not manageable(row, user):
            raise HTTPException(404, "文档不存在或不可访问")
        cur.execute("SELECT chunk_index,text,page FROM chunks WHERE document_id=%s ORDER BY chunk_index", (doc_id,))
        chunks = cur.fetchall()
    _recommend_call(lambda rc: rc.record_interaction(user, "view", doc_id=doc_id, weight=rc.WEIGHT_VIEW))
    # 详情面板（app.js viewDoc）依赖这些字段。缺列会在面板上显示 undefined。
    # chunk_count 直接取上面已查出的分块长度，无需再发一次 COUNT。
    doc = {k: row[k] for k in ("document_id", "filename", "title", "file_type",
                               "classification", "created_at",
                               "status", "lifecycle_state")}
    doc["chunk_count"] = len(chunks)
    return {"document": doc, "chunks": chunks}


@router.get("/documents/{doc_id}/versions")
def document_versions(doc_id: int, user: AuthUser = Depends(require_user)):
    """获取文档版本历史（倒序）。

    权限：可读（service.allowed）或可管理（同部门且职级≥密级）。
    草稿文档仅所有者/管理者可见版本历史。
    """
    from kms.access_control import can_approve_document
    with MySQLStore().transaction() as cur:
        row = document_row(cur, doc_id)
        if not row:
            raise HTTPException(404, "文档不存在或不可访问")
        level = int(row.get("classification") or 0)
        departments = _resolve_departments(row)
        can_read = service.allowed(row, user, 0, user.security_level)
        can_manage = can_approve_document(user, level, departments)
        if not can_read and not can_manage:
            raise HTTPException(404, "文档不存在或不可访问")
    from kms.versioning import list_versions
    items = list_versions(doc_id)
    # 安全：不向前端暴露 source_path（含绝对路径）
    for it in items:
        it.pop("source_path", None)
        it.pop("content_hash", None)
    return {"items": items}


@router.post("/documents/{doc_id}/versions/{version_no}/rollback", status_code=201)
def rollback_version(doc_id: int, version_no: int,
                     body: Optional[dict] = None,
                     user: AuthUser = Depends(require_user)):
    """申请回滚到指定历史版本 —— **提交审批，不直接执行**。

    回滚是用旧内容替换当前内容，与「上传新版本」一样改写了文档正文。早先的实现
    是「有管理权即可直接执行，事后补一条已办结记录」，等于给内容变更留了一条
    绕过审批的侧门：同一个人可以不经四眼原则把内容退回过期版本，还能在工单
    中心看到一条「已批准」的假象。因此改为与更新版本同一套治理：

        提交申请（action=rollback，policy.target_version=N）
          → 审批人批准 → decide 里执行 rollback_to_version
          → 「我的申请」进行中 / 审批人「待我审批」/ 双方「已完成」

    权限：同部门且职级 >= 文档密级（can_approve_document 派生的管理权），
    与能否「发起」申请同口径；能不能批由审批人资格另行判定（排除本人）。

    审批人与「申请更新」同规则：可自选，但**不是自由填写**——必须在
    approver_candidates() 派生的候选池里（部门 + 职级≥密级 + 涉密准入 + 排除
    本人）；留空则系统随机指派。

    **目标密级 / 归属部门由申请人声明**（与「申请更新」同构）。早先的实现把
    文档当前行的密级、部门原样抄进 policy，工单上看着像有人选过，实际是系统
    替申请人填的——审批人拿到的「目标态」从来没人确认过。现在留空才沿用当前
    值（兼容旧客户端），声明了就按声明的值校验、指派审批人、落库。
    """
    from kms.access_control import can_approve_document
    from kms.constants import AUDIT_DOC_UPDATE
    from kms.versioning import get_version

    payload = body or {}
    reason = str(payload.get("reason") or "").strip()[:400]
    raw_approver = payload.get("approver_id")
    try:
        specified_approver_id = (int(raw_approver)
                                 if raw_approver not in (None, "") else None)
    except (TypeError, ValueError):
        raise HTTPException(422, "审批人参数无效") from None
    # 目标密级：判据与 propose 一致（只能声明不高于本人职级）。
    raw_level = payload.get("classification")
    declared_level: Optional[int] = None
    if raw_level not in (None, ""):
        try:
            declared_level = int(raw_level)
        except (TypeError, ValueError):
            raise HTTPException(422, "密级须为 0-3 的整数") from None
        if not 0 <= declared_level <= 3:
            raise HTTPException(422, "密级须为 L0-L3")
        if declared_level > user.security_level:
            raise HTTPException(403, "只能声明不高于本人安全职级的密级")
    # 目标归属部门：校验口径同样照抄 propose（已登记部门 + 「不限」互斥）。
    # 空数组视为未声明——**不能**当成「不限」：漏传字段不应让文档对全员敞开。
    raw_depts = payload.get("departments")
    declared_depts: Optional[list[str]] = None
    if raw_depts not in (None, ""):
        if not isinstance(raw_depts, list):
            raise HTTPException(422, "归属部门须为数组")
        seen: set[str] = set()
        clean: list[str] = []
        for d in raw_depts:
            d = str(d or "").strip()[:128]
            if not d or d in seen:
                continue
            seen.add(d)
            if d != DOC_DEPT_UNLIMITED and d not in DEPARTMENTS:
                raise HTTPException(422, f"归属部门无效：{d}")
            clean.append(d)
        if DOC_DEPT_UNLIMITED in clean and len(clean) > 1:
            raise HTTPException(422, "「不限部门」不能与其他部门同时选择")
        if not clean:
            raise HTTPException(422, "归属部门不能为空")
        declared_depts = clean
    # 先校验目标版本存在：等审批人点「通过」才发现这一版根本不存在，
    # 等于把一个不可执行的单子推给别人。
    if not get_version(doc_id, version_no):
        raise HTTPException(404, f"历史版本 v{version_no} 不存在")

    with MySQLStore().transaction() as cur:
        row = document_row(cur, doc_id, lock=True)
        if not row:
            raise HTTPException(404, "文档不存在")
        level = int(row.get("classification") or 0)
        departments = _resolve_departments(row)
        if not can_approve_document(user, level, departments):
            raise HTTPException(403, "无权管理该文档（需同部门且职级不低于文档密级）")
        # 目标态：申请人声明值优先，未声明才回退当前值。后续指派审批人、写
        # policy、审批人复核全部按**目标态**走，不再按当前态——否则申请人把
        # 文档改成 L2/技术研发部，审批人却按 L0/产品管理部匹配，等于批的和
        # 改的不是一回事。
        target_level = level if declared_level is None else declared_level
        target_depts = departments if declared_depts is None else declared_depts
        # 借回滚顺手降密是最危险的一种「顺带修改」：内容退回旧版、密级同时
        # 被压低，事后既分不清是回滚出错还是密级填错，也让一次审批覆盖了两件
        # 事。降低密级请走「申请更新」，单独一张单、单独一次审批。
        if target_level < level:
            raise HTTPException(422, "回滚不能顺带降低密级；如需降密请提交「申请更新」")
        # 在途校验：同一文档只允一条变更申请在飞。否则审批人会看到互相矛盾的
        # 多个目标态，批准顺序不同结果就不同；且它必须与工单的删除/恢复互斥，
        # 否则“删掉它”和“改成 L2”会同时压在审批人手里（gateway/doc_inflight.py）。
        conflict = doc_inflight.find_inflight_conflict(cur, [doc_id])
        if conflict:
            raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)
        assign_mode = "系统指派"
        approver = None
        if specified_approver_id is not None:
            # 自选只是把「随机抽一个」换成「从同一个池子里挑一个」，判据不变，
            # 因此不会出现申请人指定一个本无审批资格的人——想让谁批就让谁批不成立。
            candidates = acl.approver_candidates(target_level, target_depts,
                                                 exclude_user_id=user.id)
            approver = next((c for c in candidates
                             if int(c["id"]) == specified_approver_id), None)
            if approver is None:
                raise HTTPException(422, "指定的审批人不在合格候选内，请重新选择")
            assign_mode = "自选"
        else:
            approver = acl.pick_approver(target_level, target_depts,
                                         exclude_user_id=user.id)
        if approver is None:
            scope = ("任意部门（该文档选了「不限」）"
                     if DOC_DEPT_UNLIMITED in target_depts
                     else f"「{', '.join(target_depts)}」内")
            raise HTTPException(409, f"无可用审批人：需要 {scope}、"
                                     f"安全职级不低于 L{target_level} 的其他在职员工")
        # status 只是 Policy 的必填字段：rollback 分支在 decide 里**不会**用它
        # 覆盖文档状态（回滚改内容、不改发布态）；draft 不在枚举内，故兜底为
        # published，仅用于满足模型校验。
        status_val = str(row.get("status") or "published")
        if status_val not in ("published", "archived", "expired"):
            status_val = "published"
        note = f"回滚到历史版本 v{version_no}" + (f"：{reason}" if reason else "")
        policy = Policy(classification=target_level, departments=target_depts,
                        status=status_val, reason=note[:500],
                        action="rollback", target_version=version_no)
        rid = uuid.uuid4().hex
        # 业务悲观锁：抢在 INSERT 之前占座。抢不到就 409 + 回滚——绝不能先插单
        # 再说「已经有在途单」，那等于把冲突推给审批人。
        conflict = doc_inflight.acquire(
            cur, [doc_id], ref_type=doc_inflight.REF_POLICY, ref_id=rid,
            action_label=doc_inflight.policy_action_label("rollback"),
            owner_id=user.id, owner_name=user.username,
            expires_at=doc_inflight.lease_deadline())
        if conflict:
            raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)
        cur.execute("INSERT INTO kms_policy_requests(id,document_id,requested_by,approver_id,"
                    "snapshot,policy,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (rid, doc_id, user.id, approver["id"],
                     snapshot(row), policy.model_dump_json(), ""))
    dept_label = ("不限" if DOC_DEPT_UNLIMITED in target_depts
                  else (", ".join(target_depts) or "未登记"))
    acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{doc_id}",
                  f"申请回滚至 v{version_no}（{assign_mode}）："
                  f"目标 L{target_level} / {dept_label}；"
                  f"审批人={approver['employee_no']}")
    acl.add_notification(approver["id"], "待审批回滚申请",
                         f"{user.username} 申请把《{row.get('title') or row.get('filename', '')}》"
                         f"回滚到历史版本 v{version_no}（目标 L{target_level} / {dept_label}）")
    return {"id": rid, "status": "pending", "action": "rollback",
            "target_version": version_no,
            "classification": target_level, "departments": target_depts,
            "approver": {"id": approver["id"], "employee_no": approver["employee_no"],
                         "username": approver["username"]}}


def _trusted_source_roots() -> tuple:
    """受信任的原文根目录。

    upload_dir 是 Web 上传的目标；repo_dir 是批量入库脚本写入的语料目录。
    两者都由本系统自己写入，**但必须在此显式登记**——少登记一个不会报错，
    只会表现为那一批文档的下载一律变成「原文文件缺失」，且很难联想到这里。
    """
    roots = []
    for d in (settings.upload_dir, settings.repo_dir):
        try:
            roots.append(d.resolve())
        except OSError:
            continue
    return tuple(roots)


def _resolve_source_file(doc_id: int) -> Optional[Path]:
    """把 documents.source_path 解析成受信任目录内的真实文件。

    三重防护，缺一不可：
    1. 相对路径按 upload_dir 解析，绝对路径原样使用（兼容历史数据）；
    2. resolve() 消除 ../ 后必须仍在**受信任根目录**之内——防目录穿越读到任意文件；
    3. 必须是已存在的普通文件。

    第 2 条是白名单机制：默认拒绝一切，只有登记过的根目录才放行，
    因此扩展目录不会削弱安全性，未登记的越界路径依旧被拒。
    """
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT source_path FROM documents WHERE id=%s", (doc_id,))
        row = cur.fetchone()
    raw = (row or {}).get("source_path")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = settings.upload_dir / path
    try:
        roots = _trusted_source_roots()
        resolved = path.resolve()
    except OSError:
        return None
    # 必须严格位于某个受信任根之内（等于根目录本身也不允许）
    if not any(root in resolved.parents for root in roots):
        logger.warning(f"文档 {doc_id} 的 source_path 越出受信任目录，已拒绝下载")
        return None
    return resolved if resolved.is_file() else None


# ===================== 知识浏览（Vue 试点）所需路径 =====================
# 前端 SDK 走 /managed-documents、/policy-requests/{id} 这套路径，后端既有实现
# 挂在 /governance/ 下。这里做**薄转发**而非复制业务逻辑：复制一份就意味着
# 两处权限判据可能漂移，而「列表看不到、问答搜得到」正是这么来的。
# 注：/documents/{id}/inspect 后端**早已实现**（勿重复定义）——曾据
# "curl /documents/1/inspect 返回 404" 误判为缺失，实际是那个 doc_id 不存在。
# 依赖刻意保留 editor（发起变更仍需归属部门），不放宽成 require_user。
# /documents/{id}/inspect：Vue SDK 要的路径。后端等价实现是 inspect_document()，
# 但它的路由挂在 /governance/documents/{id} 下——曾因**函数名**叫 inspect_document
# 就以为路径已存在，实则没有，别再被函数名骗。
@router.get("/documents/{doc_id}/inspect")
def inspect_document_alias(doc_id: int, user: AuthUser = Depends(require_user)):
    """薄转发到 inspect_document()，权限判据一致（manageable + 404 不泄露存在性）。"""
    return inspect_document(doc_id=doc_id, user=user)


@router.get("/managed-documents")
def managed_documents_alias(limit: int = Query(100, ge=1, le=200),
                            user: AuthUser = Depends(editor)):
    """managed-documents → governance/documents 的别名（薄转发，依赖不变）。"""
    return managed_documents(user=user, limit=limit)


@router.post("/policy-requests/{doc_id}", status_code=201)
def propose_alias(doc_id: int, req: Policy, request: Request,
                  user: AuthUser = Depends(editor)):
    """policy-requests/{id} → governance/documents/{id}/requests 的别名。"""
    return propose(doc_id=doc_id, req=req, request=request, user=user)


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: int, request: Request, user: AuthUser = Depends(require_user)):
    """下载文档原文。

    鉴权：已发布文档按 BLP 放行（service.allowed）；未发布文档仅管理者/审批人
    可下载（manageable），确保删除/更新/入库审批人能拿到完整原文审阅后再决策。
    未发布、已过期、密级越权、部门不匹配一律 404 —— 不区分"不存在"和"无权"，
    避免通过响应差异探测文档是否存在。
    """
    ip = request.client.host if request.client else ""
    with MySQLStore().transaction() as cur:
        row = document_row(cur, doc_id)
        can_read = service.allowed(row, user, 0, user.security_level)
        if not can_read and not manageable(row, user):
            raise HTTPException(404, "文档不存在或不可访问")

    path = _resolve_source_file(doc_id)
    if path is None:
        raise HTTPException(404, "原文文件缺失")
    acl.add_audit(user, AUDIT_DOC_DOWNLOAD, f"document:{doc_id}", row.get("filename", ""), ip)
    # filename* 走 RFC 5987，保证中文文件名不被浏览器截断
    quoted = quote(row.get("filename") or path.name)
    return FileResponse(
        path,
        filename=row.get("filename") or path.name,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.post("/documents", status_code=201)
def upload_document(
    request: Request,
    file: UploadFile = File(...),
    classification: Optional[int] = Form(None),
    departments: str = Form(""),  # JSON 数组字符串，["部门A","部门B"]
    approver_id: Optional[int] = Form(None),
    target_document_id: Optional[int] = Form(None),
    update_reason: Optional[str] = Form(None),
    user: AuthUser = Depends(editor),
):
    """单文件入库，登记为草稿；**密级与归属部门由上传者声明**，发布另走双人审批。

    两种语义（版本绑定 doc_id，不绑文件名）：
      · target_document_id 为空 → 创建**新文档**。同名文件不再隐式归并为
        新版本——避免「恰好同名」的不同文档被系统擅自归并；
      · target_document_id 非空 → 为该已有文档上传**新版本**，文件名无需与
        原文件相同。需对该文档具备管理权（上传者本人，或同部门且职级不低于
        文档密级，manageable 单一事实源），归档/销毁态文档不接受内容更新。

    原实现把密级写死为 3、部门写死为上传者部门，并要求 security_level==3，
    等于「选层级」这件事从来不存在，且只有 L3 能入库。

    BLP 写规则（不下写）：文档密级不得低于本人安全职级，
    即 classification < user.security_level 一律 403。

    归属部门：JSON 数组，**必须由上传者显式声明**（一个或多个已登记部门，或「不限」）。
    不再回落本人部门：归属部门是「谁能读、谁来审」的唯一依据，系统猜一次就是一次
    错授权——申请人以为交给了财务部，单据上却写着产品管理部。空值直接 422。
    上传者对所传文档始终保留管理权（granted_by 例外），即使归属到其他部门。
    """
    if not settings.gw_model_egress_allowed:
        raise HTTPException(403, "入库需模型出域授权")
    # 未声明密级时取本人职级——这是满足「不下写」(level >= 本人职级) 的**最严**
    # 取值，故缺省不会放宽权限。也让未升级的旧客户端不至于直接 422。
    if classification is None:
        level = int(user.security_level)
    else:
        try:
            level = int(classification)
        except (TypeError, ValueError):
            raise HTTPException(422, "密级须为 0-3 的整数")
    if not 0 <= level <= 3:
        raise HTTPException(422, "密级须为 L0-L3")
    # BLP 不下写
    if level < user.security_level:
        raise HTTPException(403, f"不能登记低于本人安全职级 L{user.security_level} 的文档")
    # 解析 JSON 数组。**不回落本人部门**：漏传/传空就让用户重选，
    # 而不是替他挑一个——审批人候选是按这里声明的部门派生的，猜错就等于
    # 让别的部门的人来审这份文档。
    raw_depts = _parse_departments_form(departments)
    # 校验：去重、长度、已登记
    seen = set()
    clean: list[str] = []
    for d in raw_depts:
        d = (d or "").strip()[:128]
        if not d or d in seen:
            continue
        seen.add(d)
        if d != DOC_DEPT_UNLIMITED and d not in DEPARTMENTS:
            raise HTTPException(422, f"归属部门无效：{d}")
        clean.append(d)
    if DOC_DEPT_UNLIMITED in clean and len(clean) > 1:
        # 「不限」与其他部门并列无意义，视为仅不限
        clean = [DOC_DEPT_UNLIMITED]
    if not clean:
        raise HTTPException(422, "请选择归属部门（它决定谁能看到、由谁审批）")
    dept_list = clean
    # 显式更新入口：为指定文档上传新版本。校验与回滚接口同款模式——
    # document_row 自带 404；manageable 含上传者例外（单一事实源，无新策略）。
    if target_document_id is not None:
        with MySQLStore().transaction() as cur:
            row = document_row(cur, int(target_document_id))
            if row.get("lifecycle_state") in ("archived", "destroyed"):
                raise HTTPException(400, "归档/销毁文档不接受内容更新")
            if not manageable(row, user):
                raise HTTPException(
                    403, "无权管理该文档（需上传者本人，或同部门且职级不低于文档密级）")
            # 在途互斥前置：先在路由层给出 409，而不是等入库事务才发现
            # ——那里文件已解析、临时文档已生成，只能报 500。真正的原子判定
            # 在 _ingest_new_version 的事务首行（写任何内容之前）。
            conflict = doc_inflight.find_inflight_conflict(cur, [int(target_document_id)])
            if conflict:
                raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)
    name = Path((file.filename or "").replace("\\", "/")).name
    # 格式判据统一走 kms.formats（原为本地硬编码 5 种，与入库脚本的 17 种矛盾：
    # 同一文档入库脚本能收、此处却 422 拒收）
    if not is_allowed(name):
        raise HTTPException(422, "不支持的文件类型")
    if not _ingest_lock.acquire(blocking=False):
        raise HTTPException(409, "已有入库任务，请稍后重试")
    try:
        data = file.file.read(10 * 1024 * 1024 + 1)
        if not data or len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "文件为空或超过 10 MiB")
        from gateway.routes_upload import _ingest_one
        from kms.routes import _hot_update_caches
        ip = request.client.host if request.client else ""
        # 自动提交发布审批**已在 _ingest_one 的入库事务内完成**（审批人按文档
        # 归属部门 + 密级指派），此处直接复用其结果。切勿再重复调用一次：第二次
        # 会命中「已有待审批请求」，向前端谎报 auto_submitted=False，并吞掉
        # 表单里自选的 approver_id。
        result = _ingest_one(name, data, user, level, dept_list,
                             specified_approver_id=approver_id, ip=ip,
                             target_document_id=target_document_id,
                             update_reason=update_reason)
        _hot_update_caches()
        if result["status"] == "skipped":
            raise HTTPException(409, result["message"] or "内容未变化")
        if result["status"] == "conflict":
            # 事务内才被在途互斥拦下（路由层前置校验之后的并发窗口）
            raise HTTPException(409, result["message"] or "已有在途单")
        if result["status"] == "failed":
            raise HTTPException(500, result["message"] or "入库失败")
        doc_id = int(result["document_id"])
        approval = result.get("auto_approval") or {}
        return {"document_id": doc_id, "status": "draft", "classification": level,
                "departments": dept_list,
                "department_unlimited": DOC_DEPT_UNLIMITED in dept_list,
                "auto_approval": approval,
                "version_message": result.get("message", "")}
    finally:
        file.file.close()
        _ingest_lock.release()


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    classification: int = Field(ge=0, le=3)
    # 归属部门数组。可选择一个或多个已登记部门，或「不限部门」哨兵 "*"（DOC_DEPT_UNLIMITED）。
    # 空数组 = 未指定，由业务逻辑回退到申请人本人部门（fail-closed）。
    departments: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["published", "archived", "expired"]
    reason: str = Field(min_length=5, max_length=500)
    # 动作类型：上传 / 更新版本 / 变更属性 / 回滚。仅用于工单中心区分「这是
    # 一次什么操作」——没它的话所有发布类申请一律显示为「发布审批」，用户
    # 在自己申请里根本分不清哪条是上传、哪条是换版本、哪条是改密级。
    # 服务端写入，客户端传值一律忽略（propose 里显式覆写）。
    action: str = Field(default="", max_length=32)
    # 回滚申请的目标版本号（仅 action="rollback" 时填写）。
    # 为什么不把版本号塞进 reason 文本：审批人要在弹窗里看到「回滚到哪一版」，
    # 执行时也要能拿到确定的值；靠解析字符串取参数，一旦措词变了就默默回滚到
    # 错误的版本——这是不可接受的失败模式。
    target_version: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    # 申请人在前端下拉框里自选的审批人。**刻意不是自由填写**：
    # 后端会拿它去 approver_candidates() 派生的池子里比对，不在池内一律 422。
    # 否则"自选审批人"就等于绕过了审批资格判据——想让谁批就让谁批。
    # 留空则回退到随机指派（兼容既有调用方）。
    approver_id: Optional[int] = None


@router.get("/governance/documents")
def managed_documents(user: AuthUser = Depends(editor), limit: int = Query(100, ge=1, le=200)):
    # 部门名归一化：容错 HR 台账空格，否则 JSON_CONTAINS 恒不命中
    dept = normalize_department(user.department or "")
    with MySQLStore().transaction() as cur:
        # 多部门（JSON 数组）+ 旧字段回退：
        #   · 归属部门含「*」（不限部门）→ 全员可管理；
        #   · 本部门在 departments 数组中 → 可管理；
        #   · 旧数据（departments IS NULL）回退单值 + 额外部门列表；
        #   · 本人上传的文档始终可管理（避免跨部门上传后卡在 draft）。
        cur.execute("""
            SELECT d.id AS document_id,d.title,d.filename,d.status,
                   d.departments,d.owner_department,d.extra_departments,
                   l.level AS classification,l.granted_by AS granted_by
            FROM documents d LEFT JOIN kms_doc_levels l ON l.document_id=d.id
            WHERE (
                JSON_CONTAINS(COALESCE(d.departments,JSON_ARRAY()), JSON_QUOTE(%s))
                OR JSON_CONTAINS(COALESCE(d.departments,JSON_ARRAY()), JSON_QUOTE(%s))
                OR (d.departments IS NULL AND (
                    d.owner_department=%s OR d.owner_department=%s
                    OR JSON_CONTAINS(COALESCE(d.extra_departments,JSON_ARRAY()), JSON_QUOTE(%s))
                ))
                OR l.granted_by=%s
            )
            AND (l.level<=%s OR (l.level IS NULL AND %s=3))
            ORDER BY d.id DESC LIMIT %s
        """, (DOC_DEPT_UNLIMITED, dept, dept, DOC_DEPT_UNLIMITED, dept,
              user.id, user.security_level, user.security_level, limit))
        return {"items": cur.fetchall()}


def _auto_submit_for_approval(cur, doc_id: int, user: AuthUser,
                              level: int, departments: list[str], ip: str = "",
                              specified_approver_id: Optional[int] = None,
                              action: str = "upload") -> dict:
    """文档上传入库后自动提交发布审批。

    action 区分「上传新文档」与「上传新版本」——两者走同一套审批，但
    工单中心需要能看出用户到底做了什么（否则全是「发布审批」）。

    审批人指派规则（多部门）：
      - 若 specified_approver_id 非空，校验其在候选名单中后直接使用（申请人自选）；
      - 否则由系统随机指派（pick_approver，单一事实源）。
      候选条件与 propose 完全一致：
      - 员工部门 IN 文档 departments 数组（不限部门则全员候选）
      - 安全职级 >= 文档密级（BLP 不上读）
      - 涉密文档另需 HR 涉密准入资格
      - 排除申请人本人（自审批禁止）

    审计留痕区分「自选」与「系统指派」，便于事后追溯指派模式。

    若部门内无可用审批人，不阻断上传——文档保持 draft，返回提示让用户
    后续手动处理或联系管理员补充审批人。
    """
    # 在途互斥覆盖两条链路（工单的删除/恢复 + 文档库的变更/回滚申请），
    # 见 gateway/doc_inflight.py。上传已落库，不因审批位被占而整体失败，
    # 降级为「不自动提交 + 说清原因」。
    conflict = doc_inflight.find_inflight_conflict(cur, [doc_id])
    if conflict:
        return {"auto_submitted": False,
                "reason": conflict + doc_inflight.CONFLICT_TAIL}
    # 审批人确定：优先使用申请人指定的人选，否则系统随机指派
    assign_mode = "自选"
    if specified_approver_id is not None:
        candidates = acl.approver_candidates(level, departments, exclude_user_id=user.id)
        approver = next((c for c in candidates if c["id"] == specified_approver_id), None)
        if approver is None:
            return {"auto_submitted": False,
                    "reason": "指定的审批人不在合格候选名单中（职级/部门/涉密资格不满足）"}
    else:
        assign_mode = "系统指派"
        approver = acl.pick_approver(level, departments, exclude_user_id=user.id)
    if approver is None:
        scope = ("任意部门（该文档选了「不限」）"
                 if DOC_DEPT_UNLIMITED in departments
                 else f"「{', '.join(departments)}」内")
        return {"auto_submitted": False,
                "reason": f"无可用审批人：需要 {scope}、安全职级不低于 L{level} 的其他在职员工"}
    row = document_row(cur, doc_id, lock=True)
    rid = uuid.uuid4().hex
    # 业务悲观锁：在锁表上原子抢位。抢不到就不建单——内容已入库，不因此整体
    # 失败，只降级为「不自动提交」并向调用方说清原因（前端能看到草稿待处理）。
    busy = doc_inflight.acquire(
        cur, [doc_id], ref_type=doc_inflight.REF_POLICY, ref_id=rid,
        action_label=doc_inflight.policy_action_label(action),
        owner_id=user.id, owner_name=user.username,
        expires_at=doc_inflight.lease_deadline())
    if busy:
        return {"auto_submitted": False, "reason": busy + doc_inflight.CONFLICT_TAIL}
    policy = Policy(classification=level, departments=departments,
                    status="published",
                    reason="上传入库自动提交审批", action=action)
    cur.execute("INSERT INTO kms_policy_requests(id,document_id,requested_by,approver_id,"
                "snapshot,policy,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (rid, doc_id, user.id, approver["id"],
                 snapshot(row), policy.model_dump_json(), ""))
    dept_label = "不限" if DOC_DEPT_UNLIMITED in departments else ", ".join(departments)
    acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{doc_id}",
                  f"上传入库自动提交审批（{assign_mode}）：L{level} / {dept_label}；"
                  f"审批人={approver['employee_no']}", ip)
    # 与 decide 端点对齐：审批人必须收到待办通知，否则被指派了也无从知晓
    # （工单中心发布审批 tab 与通知中心均可见）。
    acl.add_notification(approver["id"], "待审批发布申请",
                         f"{user.username} 上传的《{row.get('title') or row.get('filename', '')}》"
                         f"已自动提交发布审批（L{level} / {dept_label}）")
    return {"auto_submitted": True, "request_id": rid,
            "approver": {"id": approver["id"], "employee_no": approver["employee_no"],
                         "username": approver["username"]}}


@router.post("/governance/documents/{doc_id}/requests", status_code=201)
def propose(doc_id: int, req: Policy, request: Request, user: AuthUser = Depends(editor)):
    if req.classification > user.security_level:
        raise HTTPException(403, "只能申请不高于本人安全职级的密级")
    # 校验归属部门数组
    if any(d == DOC_DEPT_UNLIMITED for d in req.departments) and len(req.departments) > 1:
        raise HTTPException(422, "「不限部门」不能与其他部门同时选择")
    for d in req.departments:
        if d != DOC_DEPT_UNLIMITED and d not in DEPARTMENTS:
            raise HTTPException(422, f"归属部门无效：{d}")
        if not d.strip() or len(d) > 128:
            raise HTTPException(422, "归属部门格式无效")
    ip = request.client.host if request.client else ""
    with MySQLStore().transaction() as cur:
        row = document_row(cur, doc_id, True)
        if not manageable(row, user):
            raise HTTPException(403, "无权管理此文档")
        conflict = doc_inflight.find_inflight_conflict(cur, [doc_id])
        if conflict:
            raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)
        # 审批人：申请人从候选池里自选；未指定则回退随机指派（兼容既有调用方）。
        # 关键：自选**不是自由填写**——候选池仍由 approver_candidates() 按
        # 「部门 + 职级≥密级 + HR 涉密准入 + 排除申请人本人」派生，自选只是把
        # 「随机抽一个」换成「从同一个池子里挑一个」。判据没变，因此不会出现
        # 申请人指定一个本无权审批的人这种情况——想让谁批就让谁批是不成立的。
        candidates = acl.approver_candidates(req.classification, req.departments,
                                             exclude_user_id=user.id)
        approver = None
        assign_mode = "系统指派"
        if req.approver_id is not None:
            approver = next((c for c in candidates
                             if int(c["id"]) == int(req.approver_id)), None)
            if approver is None:
                raise HTTPException(422, "指定的审批人不在合格候选内，请重新选择")
            assign_mode = "自选"
        elif candidates:
            approver = acl.pick_approver(req.classification, req.departments,
                                         exclude_user_id=user.id)
        if approver is None:
            scope = ("任意部门（该文档选了「不限」）"
                     if DOC_DEPT_UNLIMITED in req.departments
                     else f"「{', '.join(req.departments)}」内")
            raise HTTPException(409, f"无可用审批人：需要 {scope}、"
                                     f"安全职级不低于 L{req.classification} 的其他在职员工")
        rid = uuid.uuid4().hex
        # 业务悲观锁：INSERT 之前先抢座（与工单的删除/恢复共用一张在途席位）。
        # 抢不到直接 409，事务回滚，单子不落库。
        conflict = doc_inflight.acquire(
            cur, [doc_id], ref_type=doc_inflight.REF_POLICY, ref_id=rid,
            action_label=doc_inflight.policy_action_label("update_policy"),
            owner_id=user.id, owner_name=user.username,
            expires_at=doc_inflight.lease_deadline())
        if conflict:
            raise HTTPException(409, conflict + doc_inflight.CONFLICT_TAIL)
        # 动作类型由服务端定：客户端传什么 action 一律覆写，防止前端伪造口径。
        policy_in = req.model_copy(update={"action": "update_policy"})
        cur.execute("INSERT INTO kms_policy_requests(id,document_id,requested_by,approver_id,"
                    "snapshot,policy,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (rid, doc_id, user.id, approver["id"],
                     snapshot(row), policy_in.model_dump_json(), request.state.request_id))
    dept_label = ', '.join(req.departments) or '不限'
    # 安全关键操作可审计：密级/部门/状态变更申请必须留痕，且区分自选/系统指派
    acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{doc_id}",
                  f"申请变更（{assign_mode}）：L{req.classification} / {dept_label} / {req.status}；"
                  f"审批人={approver['employee_no']}", ip)
    # 审批人待办通知：与上传自动提交审批同口径
    acl.add_notification(approver["id"], "待审批变更申请",
                         f"{user.username} 提交了《{row.get('title') or row.get('filename', '')}》"
                         f"的属性变更申请（L{req.classification} / {dept_label}）")
    return {"id": rid, "status": "pending",
            "approver": {"id": approver["id"], "employee_no": approver["employee_no"],
                         "username": approver["username"]}}


@router.get("/governance/requests")
def requests(status: str = None, user: AuthUser = Depends(require_user)):
    """我可见的策略申请：我发起的，或被随机指派由我审批的。

    可见范围仍按 BLP 收口（部门 + 密级）；审批资格不再来自配置名单，
    而取决于「这单是否指派给我」+「我当前是否仍够资格读取」。

    status 可选过滤（白名单枚举，支持逗号分隔多值，如 "approved,rejected"）：
    前端据此拆分视角——「发布审批」只看进行中（pending），已决策的历史
    并入工单中心「已完成」，避免两个 tab 重复展示同类记录。
    """
    if not user.department:
        raise HTTPException(403, "无部门信息")
    allowed = ("pending", "approved", "rejected")
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
    for s in statuses:
        if s not in allowed:
            raise HTTPException(422, f"不支持的状态过滤值: {s}")
    with MySQLStore().transaction() as cur:
        # 密级过滤按**请求目标密级**而非文档当前密级：
        # 申请人只能申请 <= 本人职级的密级（propose 已校验），审批人按目标密级
        # 指派（pick_approver 已校验 security_level >= 目标密级）。若此处仍按
        # 文档当前密级过滤，会出现「L3 文档申请降为 L1，L1 审批人却看不见单子」
        # 的死锁——审批人被指派了却无从审批。
        # 可见性分两档：
        #   1) 我发起的（p.requested_by）—— 无条件可见，即使 policy.departments
        #      不包含我的部门（跨部门申请更新的常见场景：申请人只需要跟踪自己
        #      提交过什么，不涉及越权读取）；
        #   2) 指派我审批的（p.approver_id）—— 仍按 BLP 收口：
        #      部门匹配（或不限部门 / 空数组）+ 目标密级 <= 本人职级，
        #      防止"看不见文档却要审批"或"低职级看见高职级单"这类越权审批。
        where = (
            "WHERE (p.requested_by=%s OR ("
            "  p.approver_id=%s "
            "  AND (JSON_CONTAINS(JSON_EXTRACT(p.policy,'$.departments'), JSON_QUOTE(%s)) "
            "       OR JSON_UNQUOTE(JSON_EXTRACT(p.policy,'$.departments'))='[]' "
            "       OR JSON_UNQUOTE(JSON_EXTRACT(p.policy,'$.departments')) IS NULL "
            "       OR JSON_CONTAINS(JSON_EXTRACT(p.policy,'$.departments'), JSON_QUOTE(%s))) "
            "  AND JSON_TYPE(JSON_EXTRACT(p.policy,'$.classification'))='INTEGER' "
            "  AND CAST(JSON_UNQUOTE(JSON_EXTRACT(p.policy,'$.classification')) AS SIGNED) BETWEEN 0 AND %s"
            "))"
        )
        params = [user.id, user.id, user.department, DOC_DEPT_UNLIMITED, user.security_level]
        if statuses:
            where += f" AND p.status IN ({','.join(['%s'] * len(statuses))})"
            params.extend(statuses)
        cur.execute("SELECT p.id,p.document_id,p.requested_by,p.approver_id,p.status,p.created_at,p.policy,"
                    # action 从 policy JSON 提出来单独返回：前端要靠它区分
                    # 「上传 / 换版本 / 改属性 / 回滚」，而不是全部显为发布审批。
                    "JSON_UNQUOTE(JSON_EXTRACT(p.policy,'$.action')) AS action,"
                    "d.title,d.filename,"
                    "ru.username AS requester_name,ru.employee_no AS requester_no,"
                    "ap.username AS approver_name,ap.employee_no AS approver_no "
                    "FROM kms_policy_requests p JOIN documents d ON d.id=p.document_id "
                    "LEFT JOIN kms_users ru ON ru.id=p.requested_by "
                    "LEFT JOIN kms_users ap ON ap.id=p.approver_id "
                    f"{where} ORDER BY p.created_at DESC LIMIT 200",
                    tuple(params))
        return {"items": cur.fetchall()}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool


@router.post("/governance/requests/{request_id}/decision")
def decide(request_id: str, req: Decision, user: AuthUser = Depends(require_user)):
    # 回滚类申请不在本事务内执行（要重新入库 + 向量化），先记下来，提交后再跑。
    rollback_job = None
    # 审批资格不再查 kms_approver_employees 配置名单，改由「该单是否被指派给我」决定。
    with MySQLStore().transaction() as cur:
        # 所有路径先锁文档再锁请求，保持锁顺序一致。
        cur.execute("SELECT document_id FROM kms_policy_requests WHERE id=%s", (request_id,))
        target = cur.fetchone()
        if not target:
            raise HTTPException(404)
        row = document_row(cur, target["document_id"], True)
        cur.execute("SELECT * FROM kms_policy_requests WHERE id=%s FOR UPDATE", (request_id,))
        item = cur.fetchone()
        if item["status"] != "pending":
            raise HTTPException(409, "申请已处理")
        if not item.get("approver_id"):
            raise HTTPException(409, "该申请未指派审批人（历史单据），须重新发起")
        if item["approver_id"] != user.id:
            raise HTTPException(403, "本单已指派给其他审批人")
        policy = Policy.model_validate_json(item["policy"] if isinstance(item["policy"], str) else json.dumps(item["policy"]))
        if item["requested_by"] == user.id:
            raise HTTPException(403, "不得自批")
        # 审批资格按**目标态**校验：pick_approver 是按 policy 的密级+部门指派的，
        # 此处用目标态构造一行再判，审批口径与指派口径一致（含跨部门/不限部门）。
        target_row = dict(row)
        target_row["departments"] = policy.departments
        target_row["classification"] = policy.classification
        if not manageable(target_row, user):
            raise HTTPException(403, "审批人无文档管理权限")
        if req.approve:
            cur.execute("SELECT * FROM kms_users WHERE id=%s", (item["requested_by"],))
            author = cur.fetchone()
            # 申请人须同时能管理「当前态」和「目标态」：前者防其权限已变，后者防
            # 其申请了自己实际够不到的密级/部门。统一走 manageable 单一判据。
            if not author or not author["is_active"]:
                raise HTTPException(409, "申请人权限已失效")
            au = AuthUser(author)
            if not manageable(row, au) or not manageable(target_row, au):
                raise HTTPException(409, "申请人权限已失效")
            if snapshot(row) != item["snapshot"]:
                raise HTTPException(409, "文档已变更，须驳回后重新申请")
            if policy.action == "rollback":
                # 回滚只换内容，不改密级/部门/发布态：这里不覆盖 documents 的
                # 任何字段，只把目标版本记下来，事务提交后再执行。放到事务里做
                # 会长时间持锁，而且 rollback_to_version 内部自带事务与入库流程，
                # 两边互等就是死锁。
                if not policy.target_version:
                    raise HTTPException(409, "回滚申请缺少目标版本号（历史单据），须重新发起")
                rollback_job = (row["document_id"], int(policy.target_version), au,
                                int(policy.classification), list(policy.departments))
            else:
                if policy.status == "published" and row["expired"]:
                    raise HTTPException(409, "文档已过期，不得重新发布")
                cur.execute("INSERT INTO kms_doc_levels(document_id,level,granted_by) VALUES(%s,%s,%s) "
                            "ON DUPLICATE KEY UPDATE level=VALUES(level),granted_by=VALUES(granted_by)",
                            (row["document_id"], policy.classification, user.id))
                cur.execute("UPDATE documents SET departments=%s,status=%s,lifecycle_state=%s,publication_approved=%s WHERE id=%s",
                            (json.dumps(policy.departments, ensure_ascii=False),
                             policy.status, policy.status, int(policy.status == "published"), row["document_id"]))
        outcome = "approved" if req.approve else "rejected"
        cur.execute("UPDATE kms_policy_requests SET status=%s,approved_by=%s,resolved_at=NOW() WHERE id=%s",
                    (outcome, user.id, request_id))
        # 单据已离开 pending → 释放业务锁。回滚执行失败的退回分支会把锁抢回来，
        # 所以这里不必区分 action。
        doc_inflight.release(cur, ref_type=doc_inflight.REF_POLICY, ref_id=request_id)

    # 回滚执行：放在事务外。rollback_to_version 内部自带事务，还要重新分词并写
    # 向量；留在上面那个事务里会长时间持锁，且它自己再开事务会与本事务互等。
    if rollback_job:
        rb_doc, rb_ver, rb_author, rb_level, rb_depts = rollback_job
        from kms.versioning import rollback_to_version
        try:
            ok, msg, new_no = rollback_to_version(rb_doc, rb_ver, rb_author)
        except Exception as e:  # noqa: BLE001
            ok, msg, new_no = False, f"执行异常: {e}", 0
        if not ok:
            # 审批已落库但执行失败：把单子退回 pending，审批人可重试。留在
            # approved 等于「批准了却什么都没发生」，比直接报错更难排查。
            with MySQLStore().transaction() as cur:
                cur.execute("UPDATE kms_policy_requests SET status='pending',approved_by=NULL,"
                            "resolved_at=NULL WHERE id=%s", (request_id,))
                # 单据退回待审批：重新占住席位。中间那一下释放到抢回之间留了个
                # 瞬时窗口，若彼时有别人抢走，这里抢不到也无妨——它手里那张单
                # 本身就是合法在途单，后来者仍会被兜底扫描拦住。
                doc_inflight.acquire(
                    cur, [rb_doc], ref_type=doc_inflight.REF_POLICY, ref_id=request_id,
                    action_label=doc_inflight.policy_action_label("rollback"),
                    owner_id=item["requested_by"],
                    owner_name=getattr(rb_author, "username", ""),
                    expires_at=doc_inflight.lease_deadline())
            acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{rb_doc}",
                          f"回滚执行失败，单据退回待审批：{msg[:200]}")
            acl.add_notification(item["requested_by"], "回滚执行失败，已退回待审批",
                                 f"文档《{row.get('title') or row.get('filename', '')}》"
                                 f"回滚到 v{rb_ver} 执行失败：{msg[:120]}")
            raise HTTPException(500, f"审批已记录，但回滚执行失败：{msg}")
        # 属性变更与内容回滚一并落库：工单上的「目标密级/归属部门」是申请人
        # 声明的、审批人按目标态复核过的值，不落库就会出现「单子写 L2、文档
        # 还是 L0」——审批记录与实际状态对不上，比不批更难排查。
        # 必须放在内容回滚**成功之后**：先改密级而内容没回去，会同时出现
        # 「密级已改」与「内容未变」两个错误状态。
        cur_level = int(row.get("classification") or 0)
        cur_depts = _resolve_departments(row)
        if rb_level != cur_level or sorted(rb_depts) != sorted(cur_depts):
            with MySQLStore().transaction() as cur:
                cur.execute("INSERT INTO kms_doc_levels(document_id,level,granted_by) "
                            "VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE level=VALUES(level),"
                            "granted_by=VALUES(granted_by)",
                            (rb_doc, rb_level, user.id))
                cur.execute("UPDATE documents SET departments=%s WHERE id=%s",
                            (json.dumps(rb_depts, ensure_ascii=False), rb_doc))
            acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{rb_doc}",
                          f"回滚同时调整属性：L{cur_level}→L{rb_level}；"
                          f"{', '.join(cur_depts) or '不限'}→{', '.join(rb_depts) or '不限'}")
        acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{rb_doc}",
                      f"审批通过并执行回滚：目标 v{rb_ver} → 新版本 v{new_no}；"
                      f"申请人ID={item['requested_by']}")
    # 安全关键操作可审计：审批结果（含密级/部门变更）必须留痕
    acl.add_audit(user, AUDIT_DOC_UPDATE, f"document:{row['document_id']}",
                  f"{'审批通过' if req.approve else '审批驳回'}：L{policy.classification} / "
                  f"{(', '.join(policy.departments) or '不限')} / {policy.status}；申请人ID={item['requested_by']}")
    # 与工单中心对齐：审批结果通知申请人，否则申请人无从得知发布/驳回结果
    dept_label = ', '.join(policy.departments) or '不限'
    if req.approve and policy.action == "rollback":
        what = (f"回滚申请已通过，内容已回退到历史版本 v{policy.target_version}"
                f"（目标 L{policy.classification} / {dept_label}）")
    elif req.approve:
        what = "发布/变更申请已通过"
    else:
        what = "申请被驳回"
    acl.add_notification(item["requested_by"],
                         "文档审批通过" if req.approve else "文档审批被驳回",
                         f"文档《{row.get('title') or row.get('filename', '')}》的"
                         f"{what}"
                         f"（审批人 {user.username} / 部门 {dept_label}）")
    return {"id": request_id, "status": outcome}


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["feishu", "wecom"]
    external_user_id: str = Field(min_length=1, max_length=128)
    employee_no: str = Field(min_length=1, max_length=32)


@router.put("/admin/bot-bindings")
def bind(req: Binding, request: Request, user: AuthUser = Depends(auditor)):
    employee = acl.get_user_by_employee_no(req.employee_no)
    if not employee or not employee["is_active"]:
        raise HTTPException(404, "在职员工不存在")
    request.state.audit_target = f"binding:{req.platform}:{hashlib.sha256(req.external_user_id.encode()).hexdigest()}:employee:{req.employee_no}"
    identity.bind(req.platform, req.external_user_id, req.employee_no, user.employee_no)
    return {"ok": True}


@router.delete("/admin/bot-bindings")
def unbind(request: Request, platform: Literal["feishu", "wecom"], external_user_id: str = Query(..., max_length=128),
           user: AuthUser = Depends(auditor)):
    request.state.audit_target = f"binding:{platform}:{hashlib.sha256(external_user_id.encode()).hexdigest()}"
    identity.unbind(platform, external_user_id)
    return {"ok": True}


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = Field(min_length=1, max_length=128)
    allowed_min_level: int = Field(0, ge=0, le=3)
    allowed_max_level: int = Field(0, ge=0, le=3)
    is_active: bool = True


def check_application(req, user):
    if not req.allowed_min_level <= req.allowed_max_level <= user.security_level:
        raise HTTPException(422, "应用范围不得超过管理者可读范围")


@router.get("/admin/apps")
def applications(user: AuthUser = Depends(auditor)):
    from kms import apps
    return {"items": apps.list_apps()}


@router.post("/admin/apps", status_code=201)
def create_application(req: Application, request: Request, user: AuthUser = Depends(auditor)):
    check_application(req, user)
    app_id, key = secrets.token_hex(8), "sk-" + secrets.token_hex(24)
    request.state.audit_target = "application:" + app_id
    with MySQLStore().transaction() as cur:
        cur.execute("INSERT INTO kms_apps(app_id,app_name,api_key_hash,allowed_min_level,allowed_max_level,is_active,created_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)", (app_id, req.app_name, hashlib.sha256(key.encode()).hexdigest(),
                    req.allowed_min_level, req.allowed_max_level, req.is_active, user.id))
    return dict(req.model_dump(), app_id=app_id, api_key=key)


@router.put("/admin/apps/{app_id}")
def update_application(app_id: str, req: Application, user: AuthUser = Depends(auditor)):
    check_application(req, user)
    with MySQLStore().transaction() as cur:
        cur.execute("UPDATE kms_apps SET app_name=%s,allowed_min_level=%s,allowed_max_level=%s,is_active=%s WHERE app_id=%s",
                    (req.app_name, req.allowed_min_level, req.allowed_max_level, req.is_active, app_id))
        cur.execute("SELECT app_id FROM kms_apps WHERE app_id=%s", (app_id,))
        if not cur.fetchone():
            raise HTTPException(404)
    return {"ok": True}


@router.post("/admin/apps/{app_id}/rotate-key")
def rotate_application(app_id: str, user: AuthUser = Depends(auditor)):
    key = "sk-" + secrets.token_hex(24)
    with MySQLStore().transaction() as cur:
        cur.execute("SELECT allowed_max_level FROM kms_apps WHERE app_id=%s FOR UPDATE", (app_id,))
        app = cur.fetchone()
        if not app:
            raise HTTPException(404)
        if int(app["allowed_max_level"]) > user.security_level:
            raise HTTPException(403)
        cur.execute("UPDATE kms_apps SET api_key_hash=%s WHERE app_id=%s", (hashlib.sha256(key.encode()).hexdigest(), app_id))
    return {"app_id": app_id, "api_key": key}


@router.get("/admin/audit-events")
def audit_events(request_id: str = Query("", max_length=64), offset: int = Query(0, ge=0),
                 limit: int = Query(50, ge=1, le=200), user: AuthUser = Depends(require_user)):
    if user.employee_no not in settings.kms_auditor_employees:
        raise HTTPException(403)
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT request_id,channel,action,app_id,employee_no,target,status_code,elapsed_ms,created_at "
                    "FROM kms_gw_audit WHERE (%s='' OR request_id=%s) ORDER BY id DESC LIMIT %s OFFSET %s",
                    (request_id, request_id, limit, offset))
        return {"items": cur.fetchall(), "offset": offset, "limit": limit}


@router.get("/governance/documents/{doc_id}")
def inspect_document(doc_id: int, user: AuthUser = Depends(require_user)):
    # 不再按 KMS_APPROVER_EMPLOYEES 配置名单放行：能否查看文档内容由 manageable()
    # 按部门 + 密级判定。无权限者收到 404 而非 403，避免泄露文档是否存在。
    with MySQLStore().transaction() as cur:
        row = document_row(cur, doc_id)
        if not manageable(row, user):
            raise HTTPException(404)
        cur.execute("SELECT chunk_index,text,page FROM chunks WHERE document_id=%s ORDER BY chunk_index LIMIT 1000", (doc_id,))
        return {"document": row, "chunks": cur.fetchall()}
