"""嵌入 API：服务端 BFF 保存应用 Key，内部知识另需员工 Bearer Token。

不接受客户端自报员工/密级；无历史上下文复用；每个答案回执绑定应用及员工。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

from kms import access_control as acl
from kms import ratelimit
from kms.apps import get_app_by_key
from kms.security import AuthUser, decode_token, revalidate_bearer
from . import service, state

router = APIRouter(prefix="/embed", tags=["open-gateway-embed"])
key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class ApplicationContext:
    app: dict
    user: AuthUser | None

    @property
    def principal(self):
        return f"{self.app['app_id']}:{self.user.id if self.user else 'service'}"

    @property
    def minimum(self):
        return int(self.app["allowed_min_level"])

    @property
    def maximum(self):
        return min(int(self.app["allowed_max_level"]), self.user.security_level if self.user else 0)


def require_app(request: Request, key: str | None = Depends(key_header)) -> ApplicationContext:
    if not key or len(key) > 256:
        raise HTTPException(401, "缺少或无效的 X-API-Key")
    try:
        app = get_app_by_key(key)
    except Exception:
        raise HTTPException(503, "应用身份服务不可用") from None
    if not app:
        raise HTTPException(401, "无效的 API Key")
    if not app["is_active"]:
        raise HTTPException(403, "应用已停用")
    if not 0 <= int(app["allowed_min_level"]) <= int(app["allowed_max_level"]) <= 3:
        raise HTTPException(403, "应用权限配置无效")
    # 配额与键构造规则由策略注册表给出（kms/ratelimit.py），端点侧不出现魔法数。
    if not ratelimit.check("gw.app", app["app_id"]):
        raise HTTPException(429, "应用请求频率超限", headers={"Retry-After": "60"})
    user = None
    auth = request.headers.get("authorization", "")
    if auth:
        scheme, _, token = auth.partition(" ")
        payload = decode_token(token) if scheme.lower() == "bearer" else None
        try:
            uid = int(payload["sub"]) if isinstance(payload, dict) else 0
        except (KeyError, TypeError, ValueError):
            uid = 0
        if uid <= 0:
            raise HTTPException(401, "员工令牌无效")
        try:
            row = acl.get_user_by_id(uid)
        except Exception:
            raise HTTPException(503, "员工身份服务不可用") from None
        if not row or not row.get("is_active"):
            raise HTTPException(403, "员工身份不可用")
        user = AuthUser(row)
    request.state.gw_app_id = app["app_id"]
    request.state.user = user
    return ApplicationContext(app, user)


def envelope(request: Request, data):
    return {"code": 0, "message": "success", "request_id": request.state.request_id, "data": data}


class EmbedChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)
    # 嵌入入口明确拒绝会话/历史字段：外部应用无法指定 session_id，
    # 避免跨主体或撤权后的历史泄露。


class EmbedFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=500)


@router.get("/health", summary="经认证的网关存活探测")
def health(request: Request, ctx: ApplicationContext = Depends(require_app)):
    return envelope(request, {"status": "alive"})


@router.get("/config", summary="嵌入组件配置")
def config(request: Request, ctx: ApplicationContext = Depends(require_app)):
    return envelope(request, {"app_name": ctx.app["app_name"], "features": {"chat": True, "history": False, "feedback": True},
                              "visible_level_range": [ctx.minimum, ctx.maximum],
                              # 取自策略注册表，保证对外声明的配额与实际生效值同源
                              "rate_limit_per_minute": ratelimit.policy("gw.app").limit})


@router.post("/chat", summary="权限受控的单轮知识问答")
def chat(request: Request, req: EmbedChatRequest, ctx: ApplicationContext = Depends(require_app)):
    result = service.answer(req.question, ctx.user, ctx.minimum, ctx.maximum)
    # 返回前复核主体与应用状态；长请求期间发生撤权也不发送答案。
    key = request.headers.get("x-api-key", "")
    current = get_app_by_key(key)
    if not current or not current["is_active"] or any(current[k] != ctx.app[k] for k in ("allowed_min_level", "allowed_max_level")):
        raise HTTPException(403, "应用授权已变更")
    if ctx.user:
        revalidate_bearer(request, ctx.user)
    result["message_id"] = state.receipt(ctx.principal)
    return envelope(request, result)


@router.get("/documents", summary="已授权且有效的文档元数据")
def documents(request: Request, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
              ctx: ApplicationContext = Depends(require_app)):
    return envelope(request, service.documents(ctx.user, ctx.minimum, ctx.maximum, offset, limit))


@router.post("/feedback", summary="提交当前主体的答案反馈")
def feedback(request: Request, req: EmbedFeedbackRequest, ctx: ApplicationContext = Depends(require_app)):
    if not state.feedback(ctx.principal, req.message_id, req.rating, req.comment):
        raise HTTPException(404, "答案回执不存在或无权访问")
    return envelope(request, {"ok": True})
