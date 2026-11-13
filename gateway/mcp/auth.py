"""MCP 身份解析：员工 JWT（必需）+ 应用 Key（可选）→ AuthUser。

与 gateway/routes_embed.py 的双身份模型完全一致，不发明第二套：
- 员工令牌：Bearer，服务端解析，**忽略客户端声明的任何部门/密级字段**；
- 应用 Key：X-API-Key，与员工身份取密级交集（复用 ApplicationContext）；
- 每次调用都重新解析，令牌撤销/改密即时生效（复用 revalidate_bearer 思路）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Request

from kms.apps import get_app_by_key
from kms.security import AuthUser, _load_user, decode_token, revalidate_bearer

from . import protocol


class McpIdentity:
    """一次 MCP 调用对应身份：员工（必需）+ 应用（可选）。"""

    def __init__(self, user: AuthUser, app: Optional[dict] = None):
        self.user = user
        self.app = app

    # —— 密级区间：应用上下界与员工职级取交集（与 embed 一致）——
    @property
    def minimum(self) -> int:
        if self.app:
            return int(self.app["allowed_min_level"])
        return 0

    @property
    def maximum(self) -> int:
        if self.app:
            return min(int(self.app["allowed_max_level"]), self.user.security_level)
        return self.user.security_level

    @property
    def principal(self) -> str:
        """回执/反馈归属标识。应用调用走 app 维度，员工直连走 kms 维度。"""
        if self.app:
            return f"mcp:{self.app['app_id']}:{self.user.id}"
        return f"kms:{self.user.id}"

    @property
    def app_id(self) -> Optional[str]:
        return self.app["app_id"] if self.app else None

    def is_auditor(self) -> bool:
        """运营审计身份（本系统无「管理员」角色，见 kms/constants.py）。"""
        return bool(self.user.is_auditor)

    def revalidate(self, request: Request) -> None:
        """长任务前后复核令牌（与 routes_kms.chat 同模式）。"""
        revalidate_bearer(request, self.user)


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "") or ""
    scheme, _, token = auth.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def resolve_identity(request: Request) -> McpIdentity:
    """解析调用身份；失败抛 RPCError（401/403）。"""
    token = _bearer_token(request)
    payload = decode_token(token) if token else None
    try:
        uid = int(payload["sub"]) if isinstance(payload, dict) else 0
    except (KeyError, TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise protocol.auth_error("缺少或无效的员工令牌（Bearer）")

    user = _load_user(uid)
    if not user or not user.is_active:
        raise protocol.auth_error("员工不存在或已停用")

    app = None
    key = (request.headers.get("x-api-key") or "").strip()
    if key:
        if len(key) > 256:
            raise protocol.auth_error("无效的应用 Key")
        try:
            app = get_app_by_key(key)
        except Exception:
            raise protocol.unavailable_error("应用身份服务不可用") from None
        if not app:
            raise protocol.auth_error("无效的应用 Key")
        if not app["is_active"]:
            raise protocol.permission_error("应用已停用")
        if not 0 <= int(app["allowed_min_level"]) <= int(app["allowed_max_level"]) <= 3:
            raise protocol.permission_error("应用密级配置非法")

    return McpIdentity(user, app)


__all__ = ["McpIdentity", "resolve_identity"]
