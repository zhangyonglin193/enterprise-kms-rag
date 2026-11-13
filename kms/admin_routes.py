"""KMS 管理端路由：认证 / 用户只读查询 / 运营审计查询。

路由前缀: /kms/api
- POST /auth/login               登录（工号+密码 → JWT）
- GET  /auth/me                  当前用户信息（安全职级/部门/业务称谓）
- POST /auth/change-password     修改本人密码（同时用户级吊销旧令牌）
- POST /auth/logout              登出（吊销当前 jti）
- GET  /admin/users              用户列表（只读）
- GET  /admin/levels             安全职级列表（只读，固定 L0-L3）
- GET  /audit/audit-logs         旧运营审计日志（运营审计可查；治理级审计走网关 /admin/audit-events，仅审计员）
- GET  /audit/audit-actions      审计操作类型候选（运营审计）
- GET  /audit/hr-sync/history    人事导入历史（只读）    [运营审计]
- GET  /audit/ingest-status      入库流程状态总览（只读）[运营审计]

（注：POST /admin/hr-sync 客户端自报密级的写入口未注册，人事主数据改由带审批编号的离线初始化写入。）

人事主数据原则:
    KMS 不维护人事主数据，只做引用。人事主体（账号、部门、业务称谓、安全职级）
    基于已批准名单离线导入，不开放给客户端任意上报。

权限模型:
    内容可见范围仅由安全职级 L0-L3 + 所属部门决定（BLP 强制访问控制），不因职务而扩张；
    另设维护员/审批员/管理员/审计员四类显式工号名单只控制治理动作，不提高可读密级；无临时提权。
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.logger import get_logger

from . import access_control as acl
from . import hr_sync
from .pagination import clamp_pagination
from .security import (
    ROLE_EMPLOYEE,
    ROLE_LABELS,
    AuthUser,
    client_ip,
    clear_login_failures,
    create_token,
    login_locked,
    record_login_failure,
    require_auditor,
    require_level,
    require_user,
    verify_password,
)

logger = get_logger("kms.admin")

router = APIRouter(prefix="/kms/api", tags=["kms-admin"])


# ===================== 请求模型 =====================
class LoginRequest(BaseModel):
    employee_no: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)


def _user_payload(row: dict) -> dict:
    """员工公开信息（前端展示用）。"""
    sec_level = int(row.get("security_level", row.get("level", 0)))
    return {
        "id": int(row["id"]),
        "employee_no": row["employee_no"],
        "username": row["username"],
        "role": ROLE_EMPLOYEE,
        "role_label": ROLE_LABELS.get(ROLE_EMPLOYEE, "员工"),
        "security_level": sec_level,
        "level": sec_level,  # 兼容旧代码
        "security_level_label": f"L{sec_level}",
        "department": row.get("department", ""),
        "business_title": row.get("business_title", ""),
        "is_active": bool(row["is_active"]),
        "data_source": row.get("data_source", "local"),
        "last_login_at": str(row.get("last_login_at") or "") or None,
        "created_at": str(row.get("created_at") or "") or None,
    }


# ===================== 密码强度策略 =====================
def _validate_password_strength(password: str) -> None:
    """密码强度校验：长度 12-128，必须同时包含字母和数字。"""
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(status_code=422, detail="密码长度须为 12-128 位")
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        raise HTTPException(status_code=422, detail="密码必须同时包含字母和数字")


# ===================== 认证 =====================
@router.post("/auth/login")
def login(req: LoginRequest, request: Request):
    """工号 + 密码登录，签发 JWT。失败限速: 连续 5 次失败锁定 5 分钟。
    
    会话严格绑定人员：每次登录使该用户所有旧会话失效（单会话模式）。
    """
    emp_no = req.employee_no.strip()
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:255]

    remain = login_locked(emp_no)
    if remain > 0:
        raise HTTPException(status_code=429, detail=f"失败次数过多，请 {remain} 秒后重试")

    row = None
    try:
        row = acl.get_user_by_employee_no(emp_no)
    except Exception as e:
        logger.warning(f"登录查询失败（MySQL 不可用？）: {e}")
        raise HTTPException(status_code=503, detail="数据库不可用，暂无法登录")

    if row is None or not verify_password(req.password, row["password_hash"]):
        record_login_failure(emp_no)
        acl.add_audit(None, "login_failed", target=emp_no, detail="工号或密码错误", ip=ip)
        raise HTTPException(status_code=401, detail="工号或密码错误")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="账号已停用（HR 标记离职）")

    clear_login_failures(emp_no)
    user = AuthUser(row)
    request.state.user = user
    acl.touch_last_login(user.id)
    token = create_token(user.id, user.employee_no, user.security_level, user.department)
    
    # 创建会话记录并使旧会话失效（严格绑定人员）
    from gateway.state import create_session
    import json
    import base64
    # 从 JWT 中提取 jti 和过期时间
    payload_b64 = token.split(".")[1]
    payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
    payload = json.loads(payload_json)
    jti = payload["jti"]
    expires_at = float(payload["exp"])
    create_session(user.id, user.employee_no, jti, expires_at, ip_address=ip, user_agent=user_agent)
    
    acl.add_audit(user, "login", target=user.employee_no, detail="新会话已创建，旧会话已失效", ip=ip)
    user_payload = _user_payload(row)
    return {"token": token, "user": user_payload}


@router.get("/auth/me")
def whoami(user: AuthUser = Depends(require_user)):
    """当前登录员工信息（前端用于会话恢复与页面渲染）。"""
    payload = user.to_public_dict()
    return payload


@router.post("/auth/logout")
def logout(request: Request, user: AuthUser = Depends(require_user)):
    """登出并撤销当前会话。
    
    会话严格绑定人员：登出后立即失效当前会话，用户需重新登录。
    """
    from gateway.state import revoke_session
    import json
    import base64
    
    # 从请求头提取 JWT 并获取 jti
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload_b64 = token.split(".")[1]
            payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
            payload = json.loads(payload_json)
            jti = payload["jti"]
            revoke_session(jti)
            acl.add_audit(user, "logout", target=user.employee_no, detail="会话已撤销")
        except Exception as e:
            logger.warning(f"登出时撤销会话失败: {e}")
    
    return {"message": "已登出"}


# ===================== 存活探测（所有登录员工） =====================
@router.get("/health")
def health(user: AuthUser = Depends(require_user)):
    """前端状态轮询用轻量存活探测。

    只返回 MySQL 连通性，不涉及任何敏感指标；供前端状态栏判断
    「运行正常 / MySQL 异常 / 服务离线」。
    """
    from app.store import MySQLStore
    try:
        with MySQLStore()._conn() as cur:
            cur.execute("SELECT 1")
        mysql = "ok"
    except Exception:
        mysql = "error"
    return {"status": "ok", "mysql": mysql}


# ===================== 系统运行信息（仅审计员） =====================
@router.get("/stats")
def system_stats(user: AuthUser = Depends(require_user)):
    """系统统计。

    **按身份裁剪下发**，而不是简单地全盘 403：

    - 所有员工都能拿到「文档数 / 分块数 / 类型分布」——这是业务口径统计，
      有用且非敏感，收掉会让仪表盘失去价值；
    - 「模型名 / 检索参数 / 向量规模」属于运维敏感信息，**仅审计员可见**，
      且是**真的不在响应里下发**。只在前端隐藏按钮是假安全——挡不住直接请求接口。

    取值一律来自真实系统状态。拿不到的字段返回 None，而不是编一个占位数字——
    本项目的原则是"用真实数字表达错误的语义，比不给这个数字更糟"
    （见 tests/test_knowledge_upload.py），一个编出来的 0 会让人误以为索引是空的。
    """
    # 延迟导入：避免模块级引入 kms.routes 造成启动期循环依赖
    from app.store import MySQLStore
    from config import settings
    from kms.routes import get_retriever

    try:
        with MySQLStore()._conn() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM documents")
            documents = int(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM chunks")
            chunks = int(cur.fetchone()["c"])
            cur.execute("SELECT file_type, COUNT(*) AS c FROM documents "
                        "GROUP BY file_type ORDER BY c DESC")
            file_types = {str(r["file_type"]): int(r["c"]) for r in cur.fetchall()}
        mysql = "ok"
    except Exception as e:
        logger.error(f"/stats 读取 MySQL 失败: {e}")
        raise HTTPException(status_code=503, detail="系统统计暂不可用（数据库异常）")

    # 基础统计：业务口径，所有在职员工可见
    out = {
        "status": "ok",
        "mysql": mysql,
        "documents": documents,
        "chunks": chunks,
        "file_types": file_types,
        # 前端据此决定要不要渲染「系统配置」类面板，省掉一次额外试探请求
        "is_auditor": bool(getattr(user, "is_auditor", False)),
    }

    # 敏感部分只有审计员才取：非审计员在这里就返回，**字段根本不会出现在响应里**
    if not getattr(user, "is_auditor", False):
        return out

    # 检索层规模：可能触及尚未预热的资源，失败时留下 None 而不是 0
    vectors = bm25 = None
    try:
        retriever = get_retriever()
        vectors = int(retriever.vector_store.total)
        bm25 = int(retriever.bm25_store.total)
    except Exception as e:
        logger.warning(f"/stats 读取检索层失败（向量/BM25 不下发）: {e}")

    out["vectors"] = vectors
    out["bm25"] = bm25
    out["models"] = {
        "llm": settings.llm_model,
        "embedding": settings.embedding_model,
        "reranker": settings.reranker_model,
        "ocr": settings.ocr_model,
    }
    # key 与前端 RAG_PARAM_META 对齐，改动任一处须同步另一侧
    out["rag_params"] = {
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k_retrieve": settings.top_k_retrieve,
        "top_k_rerank": settings.top_k_rerank,
        "max_context_chars": settings.max_context_chars,
        "enable_rerank": bool(settings.enable_rerank),
        "enable_bm25": bool(settings.enable_bm25),
        "enable_cache": bool(settings.enable_cache),
        "llm_temperature": settings.llm_temperature,
        "llm_max_tokens": settings.llm_max_tokens,
    }
    return out


# 注：此处原本还有一个 @router.post("/auth/logout") 的重复实现（用
# revoke_token 写 revoked_tokens 表）。FastAPI 按注册顺序匹配同路径路由，
# 先注册的那个（上方）才是真正生效的，后注册的是**永不匹配的死代码**。
# 两套吊销机制都在：revoke_session 通过 validate_session 拦截，
# revoke_token 通过 token_allowed 拦截，任一有效即可让令牌失效——
# 故删除死代码不改变现有行为（保留先注册者，零行为变化）。
@router.post("/auth/change-password")
def change_password(
    req: ChangePasswordRequest, request: Request, user: AuthUser = Depends(require_user)
):
    """修改本人密码（需验证旧密码，且新密码不得与旧密码相同）。
    
    会话严格绑定人员：修改密码后撤销所有会话，用户需重新登录。
    """
    row = acl.get_user_by_id(user.id)
    if row is None or not verify_password(req.old_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="旧密码错误")
    _validate_password_strength(req.new_password)
    if verify_password(req.new_password, row["password_hash"]):
        raise HTTPException(status_code=422, detail="新密码不能与旧密码相同")
    from gateway.state import revoke_user, revoke_all_user_sessions
    revoke_user(user.id)  # 撤销所有令牌
    revoke_all_user_sessions(user.id)  # 撤销所有会话（严格绑定人员）
    acl.update_password(user.id, req.new_password)
    acl.add_audit(user, "change_password", target=user.employee_no, detail="所有会话已撤销", ip=client_ip(request))
    return {"ok": True, "message": "密码已修改，所有会话已撤销，请使用新密码重新登录"}


# ===================== 用户管理（只读查询，人事主数据来自 HR 同步） =====================
@router.get("/admin/users")
def get_users(user: AuthUser = Depends(require_user)):
    """员工列表（只读）。人事主数据由 HR 系统同步，KMS 不可新增/编辑/删除。"""
    acl.ensure_kms_acl_tables()
    items = []
    for r in acl.list_users():
        items.append(_user_payload(r))
    return {"total": len(items), "items": items}


# 注意：POST /admin/users（创建用户）已移除
# 人事主数据由 HR 系统同步，KMS 不可新增员工。

# 注意：PUT /admin/users/{id}/duties（职责配置）已移除
# 内容可读范围不依赖职务（仅依安全职级+部门）；治理职责由配置名单控制动作，不开放给 API 自改。

# 注意：POST /admin/users/{id}/reset-password 已移除
# 密码由员工自助修改（POST /auth/change-password）。

# 注意：DELETE /admin/users/{id} 已移除
# 人事主数据由 HR 系统管理，KMS 不可停用/删除员工。


# ===================== 安全职级列表（只读，固定 L0-L3） =====================
@router.get("/admin/levels")
def get_levels():
    """安全职级列表（只读，固定 L0-L3，由 HR 系统定义）。"""
    items = [
        {"level": lv, "name": name, "description": desc}
        for lv, name, desc in acl.FIXED_LEVELS
    ]
    return {"total": len(items), "items": items}


# 注意：POST/PATCH/DELETE /admin/levels 已移除
# 安全职级由 HR 系统维护，固定 L0(公开，指公司内部公开)~L3(绝密)，KMS 不可修改。


# ===================== 部门列表（只读，主数据来自 HR 同步） =====================
@router.get("/admin/departments")
def get_departments(user: AuthUser = Depends(require_user)):
    """部门列表（只读）。

    与 /admin/levels 对称：职级取自 HR 定义的固定 L0-L3；部门取自**HR 同步落地的数据**
    （组织树 + 在职员工实际部门），而不是 constants.DEPARTMENTS 这份静态常量。

    用静态常量做下拉选项会与真实组织脱节：HR 新增部门后下拉里不出现，
    撤销后却仍留在候选里，前端无从分辨。改为读实际数据后，下拉始终等于
    当前组织与人员的真实状态。

    每条回带在职人数 / 文档数 / 是否已在组织树，前端可直接展示，
    避免"选了一个没有人的部门"或"选了一个组织树里不存在的部门"。
    """
    from app.store import MySQLStore

    from . import org as org_mod

    acl.ensure_kms_acl_tables()
    org_mod.ensure_org_tables()

    with MySQLStore()._conn() as cur:
        # 组织树里的一级部门（根下直属），带负责人
        cur.execute(
            "SELECT name, manager_employee_no FROM kms_org_nodes "
            "WHERE org_level=1 AND is_active=1")
        tree = {r["name"]: r["manager_employee_no"] for r in cur.fetchall()}

        # 在职员工的实际部门：覆盖尚未建组织节点的部门
        cur.execute(
            "SELECT department, COUNT(*) n FROM kms_users "
            "WHERE is_active=1 AND department IS NOT NULL AND department<>'' "
            "GROUP BY department")
        emp = {r["department"]: r["n"] for r in cur.fetchall()}

        # 文档归属部门统计。优先新字段 departments(JSON 数组)，回退 owner_department。
        # 全新库上可能还没有该列——显式判断而不是靠异常兜底，缺列时只是不统计文档数。
        cur.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME='documents' AND COLUMN_NAME='departments'")
        has_depts = cur.fetchone() is not None
        docs: dict[str, int] = {}
        if has_depts:
            cur.execute(
                "SELECT d.department, COUNT(*) n FROM documents doc, "
                "JSON_TABLE(doc.departments, '$[*]' COLUMNS (department VARCHAR(128) PATH '$')) AS d "
                "WHERE doc.departments IS NOT NULL AND JSON_LENGTH(doc.departments)>0 "
                "GROUP BY d.department")
            docs = {r["department"]: r["n"] for r in cur.fetchall()}
        else:
            cur.execute(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='documents' AND COLUMN_NAME='owner_department'")
            has_owner = cur.fetchone() is not None
            if has_owner:
                cur.execute(
                    "SELECT owner_department d, COUNT(*) n FROM documents "
                    "WHERE owner_department IS NOT NULL AND owner_department<>'' "
                    "GROUP BY owner_department")
                docs = {r["d"]: r["n"] for r in cur.fetchall()}

        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE data_source='hr_sync'")
        hr_synced = cur.fetchone()["n"] > 0

    items = [
        {
            "name": name,
            "employee_count": emp.get(name, 0),
            "doc_count": docs.get(name, 0),
            "manager_employee_no": tree.get(name),
            "in_org_tree": name in tree,
        }
        for name in sorted(set(tree) | set(emp) | set(docs))
    ]
    return {"total": len(items), "items": items, "hr_synced": hr_synced}


# 注意：POST/PATCH/DELETE /admin/departments 已移除
# 部门由 HR 系统维护并经组织树同步，KMS 不可增删改部门。


# ===================== 审计操作类型候选（供筛选下拉，替代手打） =====================
@router.get("/audit/audit-actions")
def get_audit_actions(user: AuthUser = Depends(require_auditor)):
    """审计日志中出现过的操作类型（只读）。

    取自库中实际落过的 action，而不是前端写死一份常量清单：
    新增审计动作后下拉会自己出现，写死的话新动作永远筛不到。
    """
    from app.store import MySQLStore

    acl.ensure_kms_acl_tables()
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT action, COUNT(*) n FROM kms_audit_logs "
            "WHERE action IS NOT NULL AND action<>'' GROUP BY action ORDER BY n DESC")
        rows = cur.fetchall()
    return {"total": len(rows),
            "items": [{"action": r["action"], "count": r["n"]} for r in rows]}


# ===================== 旧运营审计日志（运营审计可查） =====================
@router.get("/audit/audit-logs")
def get_audit_logs(
    request: Request,
    action: Optional[str] = None,
    employee_no: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    user: AuthUser = Depends(require_auditor),
):
    """旧运营审计日志查询（kms_audit_logs）；治理级全量审计走网关 /admin/audit-events（仅审计员）。"""
    # 分页归一化统一走 kms.pagination（原为本地 max/min，上限 1000 与其它入口不一致）
    offset, limit = clamp_pagination(offset, limit)
    items = acl.list_audit_logs(action, employee_no, limit, offset)
    acl.add_audit(user, "audit_query", target="audit_logs",
                  detail=f"action={action}, employee_no={employee_no}",
                  ip=client_ip(request))
    return {"total": len(items), "items": items}


# ===================== 入库流程状态（审计员/管理员只读） =====================
@router.get("/audit/ingest-status")
def get_ingest_status(user: AuthUser = Depends(require_auditor)):
    """入库流程状态总览（只读）。

    回答审计员最关心的两个问题：「库里到底入进去了没有」「入得全不全」。
    全部从现有派生，不新增表——单次运行的失败明细需要新增入库运行表才
    拿得到，当前未做，故**不提供伪指标**（宁可没有，也不要编一个出来）。

    其中最关键的是 faiss_total == chunks_total：两者不等即脏数据，
    服务本应在这种状态下拒绝启动。
    """
    from app.store import MySQLStore, VectorStore

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT status, COUNT(*) n FROM documents GROUP BY status")
        by_status = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) n FROM documents")
        doc_total = int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) n FROM chunks")
        chunk_total = int(cur.fetchone()["n"])
        cur.execute("SELECT level, COUNT(*) n FROM kms_doc_levels GROUP BY level")
        by_level = {int(r["level"]): r["n"] for r in cur.fetchall()}
        # 按归属部门统计：优先 departments 数组，回退 owner_department
        cur.execute(
            "SELECT d.department, COUNT(*) n FROM documents doc, "
            "JSON_TABLE(doc.departments, '$[*]' COLUMNS (department VARCHAR(128) PATH '$')) AS d "
            "WHERE doc.departments IS NOT NULL AND JSON_LENGTH(doc.departments)>0 "
            "GROUP BY d.department")
        dept_rows = cur.fetchall()
        if dept_rows:
            by_dept = {(r["department"] or "(未归属)"): r["n"] for r in dept_rows}
        else:
            cur.execute("SELECT owner_department, COUNT(*) n FROM documents "
                        "GROUP BY owner_department")
            by_dept = {(r["owner_department"] or "(未归属)"): r["n"]
                       for r in cur.fetchall()}
        # 近 24h 入库量：created_at 并非所有版本都有，缺则给 None 而不是报错
        recent_24h = None
        try:
            cur.execute("SELECT COUNT(*) n FROM documents "
                        "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)")
            recent_24h = int(cur.fetchone()["n"])
        except Exception as e:
            logger.warning(f"近 24h 入库量不可用（缺 created_at?）: {e}")

    faiss_total = None
    try:
        vs = VectorStore()
        vs.load()
        faiss_total = int(vs.total)
    except Exception as e:
        logger.warning(f"读取 FAISS 索引失败: {e}")

    return {
        "documents_total": doc_total,
        "documents_by_status": by_status,
        "documents_by_level": by_level,
        "documents_by_department": by_dept,
        "chunks_total": chunk_total,
        "ingested_last_24h": recent_24h,
        "faiss_total": faiss_total,
        "faiss_mysql_consistent": (
            faiss_total == chunk_total if faiss_total is not None else None),
    }


# 注意：GET /admin/escalations（提权会话审计）已移除
# 系统中无临时提权概念。


# ===================== HR 同步（人事主数据单向只读导入） =====================
class HRSyncRequest(BaseModel):
    """HR 同步请求体。"""
    source_type: str = Field("csv_file", description="数据源类型: hr_api/hr_db/csv_file")
    employees: List[dict] = Field(default_factory=list, description="员工数据列表")


# 未接入可信 HR 源之前，不注册客户端可任意上报密级的人事写入接口。
async def trigger_hr_sync(
    req: HRSyncRequest,
    request: Request,
    admin: AuthUser = Depends(require_level(2)),
):
    """手动触发 HR 同步（从 HR 系统拉取员工数据到 KMS）。

    权限：安全职级 L2（机密）及以上。
    注意：这是单向只读同步，KMS 不会向 HR 回写任何数据。
    """
    hr_sync.ensure_hr_sync_columns()

    employees = hr_sync.parse_csv_employees(req.employees)
    if not employees:
        raise HTTPException(status_code=422, detail="未提供有效的员工数据")

    result = hr_sync.sync_employees(
        employees,
        source_type=req.source_type,
        sync_type="manual",
        triggered_by=admin.id,
    )

    acl.add_audit(
        admin, "hr_sync_manual",
        target=f"total={result['total']}",
        detail=f"created={result['created']}, updated={result['updated']}, "
               f"deactivated={result['deactivated']}, errors={len(result['errors'])}",
        ip=client_ip(request),
    )

    return {
        "ok": True,
        "message": f"HR 同步完成：新增 {result['created']}，更新 {result['updated']}，"
                   f"停用 {result['deactivated']}，失败 {len(result['errors'])}",
        "detail": result,
    }


@router.get("/audit/hr-sync/history")
def get_hr_sync_history(
    limit: int = 20,
    user: AuthUser = Depends(require_auditor),
):
    """查询 HR 同步历史（运营审计，只读）。

    原挂在 /admin/ 下并叠加「管理员且 L2+」，与「无管理员」的角色模型
    冲突：员工被 L2+ 挡、审计员被管理员门闸挡，实际无人可访问。
    现移入 /audit/ 命名空间，改由运营审计只读。
    """
    history = hr_sync.get_sync_history(limit)
    return {"total": len(history), "items": history}
