"""KMS 安全模块：密码哈希 / 访问令牌 / FastAPI 依赖。

权限架构（BLP 强制访问控制 + 部门归属）
-----------------------------------------
系统中只有一类主体：员工。
- 员工信息（账号、部门、业务称谓、安全职级 L0-L3）基于已批准名单离线初始化，不由客户端自报。
- 内容可见范围由“安全职级 + 所属部门”强制判定；另设维护员/审批员/管理员/审计员四类显式工号名单控制治理动作，与密级相互独立。
- BLP 规则：不上读（读：doc_level <= emp_level）、不下写（写：doc_level >= emp_level）。
- 部门规则：员工属于文档归属部门，或员工部门在文档额外开放部门列表中。

工程约定
--------
1. 密码散列: PBKDF2-HMAC-SHA256（NIST 认可），格式:
       pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
2. 访问令牌: HS256 JWT（RFC 7519），纯标准库实现。
   claims: sub/emp/role/level/dept/iat/exp/jti
3. 可撤销的无状态 Token + 实时鉴权: JWT 本体无会话状态，但登出/改密写入 SQLite 撤销表（单令牌 jti 与用户级），
   配合安全职级/部门/启用状态每次请求实时查库，使禁用、变更、吊销立即生效。
4. 令牌签名密钥: 优先读环境变量 KMS_SECRET_KEY；否则首次启动自动生成
   64 位十六进制密钥并持久化到 data/kms_secret.key。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import time
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.logger import get_logger
from config import settings

# 身份与密级常量的唯一定义在 kms/constants.py，此处统一再导出而非重抄字面量。
# 本模块内部直接使用这些名字，同时保留旧导入路径给上层沿用。
from .constants import (  # noqa: F401  —— 均为刻意再导出，供上层沿用旧导入路径
    HR_EMPLOYMENT_UNKNOWN,
    HR_EMPLOYMENTS,
    HR_EMPLOYMENT_LABELS,
    HR_EMPLOYMENT_STAFF,
    HR_JOB_FAMILIES,
    HR_JOB_FAMILY_LABELS,
    HR_JOB_FAMILY_PROF,
    HR_POSITIONS,
    HR_POSITION_AUDITOR,
    HR_POSITION_LABELS,
    HR_POSITION_STAFF,
    HR_STATUS_UNKNOWN,
    HR_STATUSES,
    HR_STATUS_LABELS,
    HR_STATUS_REGULAR,
    HR_STATUS_TRIAL,
    MAX_EMPLOYEE_LEVEL,
    PUBLIC_LEVEL,
    ROLE_EMPLOYEE,
    ROLE_LABELS,
    SECURITY_LEVELS,
    SECURITY_LEVEL_CONFIDENTIAL,
    SECURITY_LEVEL_PUBLIC,
    SECURITY_LEVEL_SECRET,
    SECURITY_LEVEL_TOPSECRET,
)

logger = get_logger("kms.security")

# ===== 常量 =====
PBKDF2_ITERATIONS = 600_000          # 新密码提升成本；旧散列按保存的迭代数验证
TOKEN_TTL_HOURS = int(os.getenv("KMS_TOKEN_EXPIRE_HOURS", "1"))
if not 1 <= TOKEN_TTL_HOURS <= 8:
    raise ValueError("KMS_TOKEN_EXPIRE_HOURS 必须为 1～8 小时")
TOKEN_ALGORITHM = "HS256"

# 身份（统一实体：所有账号均为"员工"）与密级常量均自 .constants 再导出，见文件头。

_bearer_scheme = HTTPBearer(auto_error=False)


# ===================== 密钥管理 =====================
def _load_or_create_secret_key() -> str:
    """签名密钥：环境变量优先，否则自动生成并持久化。"""
    env_key = os.getenv("KMS_SECRET_KEY", "").strip()
    if env_key:
        if len(env_key) < 32:
            raise RuntimeError("KMS_SECRET_KEY 至少 32 字符")
        return env_key

    key_file = settings.faiss_index_path.parent.parent / "kms_secret.key"
    try:
        if key_file.exists():
            key = key_file.read_text(encoding="utf-8").strip()
            if len(key) >= 32:
                return key
        key = secrets.token_hex(32)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass  # Windows 下 chmod 语义受限，忽略
        logger.info(f"已生成 KMS 签名密钥: {key_file}")
        return key
    except Exception:
        raise RuntimeError("KMS 签名密钥无法持久化，拒绝启动") from None


SECRET_KEY = _load_or_create_secret_key()


# ===================== 密码散列 =====================
def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 散列。"""
    if not password or len(password) < 6:
        raise ValueError("密码长度至少 6 位")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    """恒定时间比较校验密码。"""
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ===================== JWT（HS256, RFC 7519） =====================
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload: dict) -> str:
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    signing_input = "{}.{}".format(
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    )
    signature = hmac.new(
        SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def create_token(
    user_id: int,
    employee_no: str,
    security_level: int,
    department: str = "",
) -> str:
    """签发访问令牌。claims 包含安全职级和部门，鉴权以实时查库为准。"""
    now = time.time()
    payload = {
        "iss": "unionpay-kms",
        "aud": "enterprise-knowledge",
        "sub": str(user_id),
        "emp": employee_no,
        "role": ROLE_EMPLOYEE,
        "level": security_level,
        "dept": department,
        "iat": now,
        "exp": now + TOKEN_TTL_HOURS * 3600,
        "jti": uuid.uuid4().hex,
    }
    return _sign(payload)


def decode_token(token: str) -> Optional[dict]:
    """校验签名与有效期；任何失败返回 None。
    
    会话严格绑定人员：除校验 JWT 签名/有效期外，还需验证会话是否活跃
    （未被撤销且未被新登录替代）。
    """
    try:
        signing_input, _, signature_b64 = token.rpartition(".")
        if not signing_input:
            return None
        expected = hmac.new(
            SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
            return None
        header_b64, payload_b64 = signing_input.split(".", 1)
        if json.loads(_b64url_decode(header_b64)).get("alg") != TOKEN_ALGORITHM:
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        issued, expires = float(payload["iat"]), float(payload["exp"])
        if (not math.isfinite(issued) or not math.isfinite(expires) or issued <= 0
                or expires <= time.time() or issued > time.time() + 30 or not 0 < expires - issued <= 28800
                or payload.get("iss") != "unionpay-kms" or payload.get("aud") != "enterprise-knowledge"
                or int(payload["sub"]) <= 0 or not isinstance(payload.get("jti"), str) or len(payload["jti"]) != 32):
            return None
        from gateway.state import token_allowed, validate_session
        # 先检查令牌是否被撤销（传统机制）
        if not token_allowed(payload):
            return None
        # 再检查会话是否活跃（严格绑定人员：新登录会使旧会话失效）
        if not validate_session(payload["jti"]):
            return None
        return payload
    except Exception:
        return None


def revalidate_bearer(request: Request, user: "AuthUser") -> None:
    """长请求放行前再次核验撤销状态及当前员工属性（含组织扩展）。"""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    payload = decode_token(token) if scheme.lower() == "bearer" else None
    if not payload or int(payload["sub"]) != user.id:
        raise HTTPException(401, "员工令牌已失效")
    # 用 _load_user 加载完整 AuthUser（含 org_path/org_node_id 组织扩展），
    # 避免 AuthUser(row) 缺少组织字段导致误判"权限已变更"
    try:
        fresh = _load_user(user.id)
    except Exception:
        raise HTTPException(503, "身份服务不可用") from None
    if not fresh or not fresh.is_active:
        raise HTTPException(401, "账号不可用")
    if fresh.to_public_dict() != user.to_public_dict():
        raise HTTPException(403, "员工权限已变更")


# ===================== 登录失败限速 =====================
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SECONDS = 300
_login_failures: dict[str, list[float]] = {}


def login_locked(employee_no: str) -> int:
    """返回剩余锁定秒数（0 = 未锁定）。"""
    now = time.time()
    fails = [t for t in _login_failures.get(employee_no, []) if now - t < _LOGIN_LOCK_SECONDS]
    _login_failures[employee_no] = fails
    if len(fails) >= _LOGIN_MAX_FAILS:
        return int(_LOGIN_LOCK_SECONDS - (now - fails[0])) + 1
    return 0


def record_login_failure(employee_no: str) -> None:
    _login_failures.setdefault(employee_no, []).append(time.time())


def clear_login_failures(employee_no: str) -> None:
    _login_failures.pop(employee_no, None)


# ===================== FastAPI 依赖 =====================
def _decide_is_auditor(employee_no: str, position_type: str) -> bool:
    """判定审计员这一**治理身份**。

    优先取 HR 同步来的岗位类别（唯一权威来源）；本地名单
    `settings.kms_auditor_employees` 仅作兜底，用于 HR 尚未同步到位的环境
    （如离线初始化）。二者是「或」关系而非覆盖，这样切换 HR 接入时不会
    突然把已指定的审计员降级。

    注意：本判定**不影响任何内容可读范围**——那只由安全职级 + 部门决定（BLP）。
    """
    if position_type == HR_POSITION_AUDITOR:
        return True
    return employee_no in (settings.kms_auditor_employees or [])


def _norm_hr(value, allowed, labels, fallback: str) -> str:
    """HR 取值归一化：未登记值一律降级到 fallback。

    与 hr_sync.HREmployeeData._pick 同一用意——但这里守的是**已落库**的脏值
    （例如手工改库、历史数据）。两处都要收口，否则任一处漏掉就会出现
    "库里有值、判定不认"的静默失效。
    """
    v = (value or "").strip().lower() if isinstance(value, str) else ""
    return v if v in allowed else fallback


def hr_secret_eligible(status: str, employment_type: str,
                       nda_signed: bool, background_cleared: bool) -> bool:
    """HR 主数据是否允许此人**接触涉密信息**（L2 / L3）。

    这是唯一的判定处，刻意收在一个函数里：把"资格"散到各业务里各自解释，
    迟早出现"上传放行、审批不放行"之类的割裂。

    判据全部来自 HR 主数据（KMS 不自行裁定谁有资格）：

      1. 在职状态：regular / trial 可以；pending_leave / leave 不行
         ——即将离开或长期离岗的人，权限应当先收回；
      2. 用工性质：仅 staff（正式）。派遣 / 实习 / 外包默认不接触涉密，
         需要时由 HR 显式调整为正式而非在此开特例；
      3. 已签署保密承诺书；
      4. 背景审查通过。

    注意与安全职级的关系：**这是准入门槛，不是密级**。职级仍由
    `security_level` 决定（BLP 的"不上读"），本判定只回答"有没有资格进门"。
    二者相乘而非取代——没有资格的人，职级再高也不进。
    """
    if status not in (HR_STATUS_REGULAR, HR_STATUS_TRIAL):
        return False
    if employment_type != HR_EMPLOYMENT_STAFF:
        return False
    return bool(nda_signed) and bool(background_cleared)


class AuthUser:
    """已认证员工上下文（含组织架构信息）。

    数据来自 kms_users（HR 同步镜像表）实时查询 + kms_org_nodes（组织目录）关联。
    权限判定依赖 security_level + department + org_path（上级可看下级继承）。
    """

    def __init__(self, row: dict, org_extra: Optional[dict] = None):
        self.id: int = int(row["id"])
        self.employee_no: str = row["employee_no"]
        self.username: str = row["username"]
        self.role: str = ROLE_EMPLOYEE
        self.security_level: int = int(row.get("security_level", row.get("level", 0)))
        self.level: int = self.security_level  # 兼容旧代码
        self.department: str = row.get("department", "")
        self.business_title: str = row.get("business_title", "")
        self.is_active: bool = bool(row["is_active"])

        # —— 治理身份（源自 HR 岗位类别）——
        # 未知值一律降级为 staff：宁可少给权限，也不让陌生取值混进判定。
        _pt = (row.get("hr_position_type") or HR_POSITION_STAFF).strip().lower()
        self.hr_position_type: str = _pt if _pt in HR_POSITIONS else HR_POSITION_STAFF
        self.is_auditor: bool = _decide_is_auditor(self.employee_no, self.hr_position_type)

        # —— HR 企业维度（人事主数据，只读引用）——
        # 同样走 _norm_hr 归一化：库里可能出现手工改过的脏值。
        # 归一化落点同样是 unknown 而非最宽松档——库里出现脏值/NULL 时
        # 结论必须是"无资格"，不能是"默认有资格"。
        self.hr_status: str = _norm_hr(row.get("hr_status"), HR_STATUSES,
                                       HR_STATUS_LABELS, HR_STATUS_UNKNOWN)
        self.hr_employment_type: str = _norm_hr(row.get("hr_employment_type"),
                                                HR_EMPLOYMENTS, HR_EMPLOYMENT_LABELS,
                                                HR_EMPLOYMENT_UNKNOWN)
        self.hr_manager_no: str = (row.get("hr_manager_no") or "")[:64]
        self.hr_job_family: str = _norm_hr(row.get("hr_job_family"), HR_JOB_FAMILIES,
                                           HR_JOB_FAMILY_LABELS, HR_JOB_FAMILY_PROF)
        self.hr_job_grade: str = (row.get("hr_job_grade") or "")[:32]
        self.hr_hire_date = row.get("hr_hire_date")
        # 缺省 False：HR 没表态 = 无涉密资格（与 hr_sync._as_bool 同向）
        self.hr_nda_signed: bool = bool(row.get("hr_nda_signed", 0))
        self.hr_background_cleared: bool = bool(row.get("hr_background_cleared", 0))
        # 派生：是否具备接触涉密信息的资格（准入门槛，不等于密级）
        self.hr_secret_eligible: bool = hr_secret_eligible(
            self.hr_status, self.hr_employment_type,
            self.hr_nda_signed, self.hr_background_cleared)

        # —— 组织架构扩展（来自 kms_org_nodes 关联）——
        self.org_node_id: Optional[int] = None
        self.org_path: str = row.get("org_path", "") or ""
        self.org_level: int = 0
        self.manager_employee_no: str = row.get("manager_employee_no", "") or ""

        if org_extra:
            self.org_node_id = org_extra.get("id") or row.get("org_node_id")
            self.org_path = org_extra.get("org_path") or self.org_path
            self.org_level = int(org_extra.get("org_level", 0) or 0)
            # manager 优先用组织节点的负责人，其次用 kms_users 上的 manager_employee_no
            self.manager_employee_no = (
                org_extra.get("manager_employee_no")
                or self.manager_employee_no
                or ""
            )

    # ----- 身份判定 -----
    @property
    def is_app(self) -> bool:
        return False

    @property
    def is_employee(self) -> bool:
        return True

    # ----- 组织查询辅助 -----
    @property
    def org_root_name(self) -> str:
        """组织路径根节点（公司名）。"""
        if not self.org_path:
            return ""
        return self.org_path.split("/")[0]

    @property
    def org_department_name(self) -> str:
        """组织路径的部门层（二级）。"""
        if not self.org_path:
            return self.department
        parts = self.org_path.split("/")
        return parts[1] if len(parts) > 1 else parts[-1]

    @property
    def org_team_name(self) -> str:
        """组织路径的团队/科室层（三级及以下）。"""
        if not self.org_path:
            return ""
        parts = self.org_path.split("/")
        return parts[-1] if len(parts) > 2 else ""

    def to_public_dict(self) -> dict:
        """返回前端可见的身份信息（含组织字段）。"""
        return {
            "id": self.id,
            "employee_no": self.employee_no,
            "username": self.username,
            "role": ROLE_EMPLOYEE,
            "role_label": ROLE_LABELS[ROLE_EMPLOYEE],
            "security_level": self.security_level,
            "level": self.security_level,
            "security_level_label": f"L{self.security_level}",
            "department": self.department,
            "business_title": self.business_title,
            "is_active": self.is_active,
            # —— 治理身份 ——
            # 只决定「能否查看系统配置/运行参数/治理审计」，不参与任何 BLP 读权限判定。
            "hr_position_type": self.hr_position_type,
            "hr_position_label": HR_POSITION_LABELS.get(self.hr_position_type, ""),
            "is_auditor": self.is_auditor,
            # —— HR 企业维度（人事主数据）——
            # 随 /auth/me 一并下发，前端做展示与提示；**资格判定仍以服务端为准**，
            # 前端不据此放行任何操作（否则又是一个恒假守卫式的假控制）。
            "hr_status": self.hr_status,
            "hr_status_label": HR_STATUS_LABELS.get(self.hr_status, ""),
            "hr_employment_type": self.hr_employment_type,
            "hr_employment_label": HR_EMPLOYMENT_LABELS.get(self.hr_employment_type, ""),
            "hr_manager_no": self.hr_manager_no,
            "hr_job_family": self.hr_job_family,
            "hr_job_family_label": HR_JOB_FAMILY_LABELS.get(self.hr_job_family, ""),
            "hr_job_grade": self.hr_job_grade,
            "hr_hire_date": (self.hr_hire_date.isoformat()
                             if hasattr(self.hr_hire_date, "isoformat")
                             else (self.hr_hire_date or None)),
            "hr_secret_eligible": self.hr_secret_eligible,
            # —— 组织架构 ——
            "org_node_id": self.org_node_id,
            "org_path": self.org_path,
            "org_level": self.org_level,
            "org_root_name": self.org_root_name,
            "org_department_name": self.org_department_name,
            "org_team_name": self.org_team_name,
            "manager_employee_no": self.manager_employee_no,
        }


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[AuthUser]:
    """解析身份：优先 Bearer Token，其次 X-API-Key（第三方应用）。"""
    if hasattr(request.state, "user"):
        return request.state.user
    # 1. 用户 Token
    if credentials is not None and credentials.credentials:
        payload = decode_token(credentials.credentials)
        if payload is None:
            return None
        user = _load_user(int(payload["sub"]))
        if user is None or not user.is_active:
            return None
        return user

    # 2. 第三方应用 API Key
    try:
        from .apps import authenticate_app, app_to_auth_user
        app = authenticate_app(request)
        if app is not None:
            return app_to_auth_user(app)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"应用鉴权失败: {e}")
        return None

    return None


async def get_optional_user(user: Optional[AuthUser] = Depends(get_current_user)) -> Optional[AuthUser]:
    """显式别名：未认证返回 None（访客态）。"""
    return user


async def require_user(user: Optional[AuthUser] = Depends(get_current_user)) -> AuthUser:
    """强制登录。"""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_auditor(user: AuthUser = Depends(require_user)) -> AuthUser:
    """强制审计员（或管理员）身份。

    审计员是**只读**岗位：看 KMS 运行状况与入库流程状态，不参与内容维护、
    不参与审批。管理员一并放行，避免运维排查时还要换账号。
    刻意不复用 require_level——岗位与职级是两回事，职级高不等于有审计职责。
    """
    if not user.is_auditor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要运营审计权限",
        )
    return user


def require_level(min_level: int):
    """基于安全职级的鉴权依赖工厂。

    用法: Depends(require_level(2))  -- 要求安全职级 >= L2
    """
    async def _check(user: AuthUser = Depends(require_user)) -> AuthUser:
        if user.security_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要安全职级 L{min_level} 及以上",
            )
        return user
    return _check


def _load_user(user_id: int) -> Optional[AuthUser]:
    """从 kms_users 实时加载员工信息 + 组织扩展（kms_org_nodes 关联）。

    组织扩展是可选增强：如果 org 表未建或用户无部门，退化为纯员工行。
    这样安全层可以独立工作而不依赖 org 模块。
    """
    from .access_control import get_user_by_id

    try:
        row = get_user_by_id(user_id)
        if not row:
            # 去掉 [DEBUG] 前缀：消息本身是异常情况，用 warning 合理；
            # 但前缀会让运维在告警里看到 "[DEBUG]" 而误判为调试残留。
            logger.warning(f"get_user_by_id 未找到用户 user_id={user_id}")
            return None
    except Exception as e:
        logger.error(f"加载员工失败 user_id={user_id}: {e}")
        return None

    org_extra: Optional[dict] = None
    try:
        org_extra = _load_user_org(row)
    except Exception as e:
        logger.warning(f"加载用户组织信息失败 user_id={user_id}: {type(e).__name__}: {e}")

    return AuthUser(row, org_extra)


def _load_user_org(row: dict) -> Optional[dict]:
    """根据员工行加载组织扩展。优先用 kms_users.org_node_id 关联，
    否则通过 org.resolve_user_org 从 department 字符串推断。"""
    from .org import ensure_org_tables, resolve_user_org
    from app.store import MySQLStore

    ensure_org_tables()
    org_node_id = row.get("org_node_id")

    if org_node_id:
        mysql = MySQLStore()
        try:
            with mysql._conn() as cur:
                cur.execute(
                    "SELECT id, org_path, org_level, manager_employee_no "
                    "FROM kms_org_nodes WHERE id=%s",
                    (int(org_node_id),),
                )
                r = cur.fetchone()
                if r:
                    return dict(r)
        except Exception as e:
            logger.debug(f"按 org_node_id 查节点失败: {e}")

    resolved = resolve_user_org(
        employee_no=row["employee_no"],
        department=row.get("department", "") or "",
        manager_employee_no=row.get("manager_employee_no", "") or "",
    )
    if resolved.get("org_path") and resolved.get("org_node_id"):
        mysql = MySQLStore()
        try:
            with mysql._conn() as cur:
                cur.execute(
                    "SELECT id, org_path, org_level, manager_employee_no "
                    "FROM kms_org_nodes WHERE id=%s",
                    (int(resolved["org_node_id"]),),
                )
                r = cur.fetchone()
                if r:
                    cur.execute(
                        "UPDATE kms_users SET org_node_id=%s, org_path=%s, manager_employee_no=%s WHERE id=%s",
                        (int(resolved["org_node_id"]), resolved["org_path"],
                         resolved["manager_employee_no"], int(row["id"])),
                    )
                    return dict(r)
        except Exception as e:
            logger.debug(f"回写 org 信息失败: {e}")

    return None


def client_ip(request: Request) -> str:
    """提取客户端 IP。"""
    return request.client.host if request.client else "unknown"
