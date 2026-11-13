"""入口审计与限流：覆盖失败、未知路由、超大请求和异常；不记录查询串/凭证/正文。

X-Forwarded-For 不直接信任，代理信任由 Uvicorn 的配置承担。
"""
from __future__ import annotations

import json
import time

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from app.logger import get_logger
from kms.security import decode_token
from kms import ratelimit
from .audit import log_gw_event, new_request_id
from .logctx import request_id_var

logger = get_logger("gw")
# 限流统一走 kms.ratelimit.check(策略名, 主体)：配额与键构造规则集中在策略注册表，
# 端点侧不再出现魔法数或硬编码配额。


_ERRORS = {400: "请求格式无效", 401: "身份认证失败", 403: "无权执行该操作", 404: "资源不存在或不可访问",
           405: "不支持的请求方法", 409: "资源状态已变更", 413: "请求体过大", 422: "请求参数无效",
           429: "请求过于频繁", 500: "内部服务异常", 502: "上游服务不可用", 503: "服务暂不可用"}


def _detail_text(detail) -> str:
    """把 HTTPException.detail（字符串 / Pydantic 校验列表）压成一句可读文案。"""
    if isinstance(detail, str):
        return detail.strip()[:300]
    if isinstance(detail, list):
        parts = []
        for item in detail[:3]:
            if isinstance(item, dict):
                msg = item.get("msg") or ""
                loc = ".".join(str(x) for x in (item.get("loc") or ())
                                if x not in ("body", "query", "path"))
                parts.append(f"{loc} {msg}".strip())
            elif item:
                parts.append(str(item))
        return "；".join(p for p in parts if p)[:300]
    return ""


def error_response(status, rid, detail: str = ""):
    # 4xx 几乎都是用户可自助纠正的业务原因（内容未变化 / 已有入库任务 / 归属部门无效…），
    # 必须原样透出——否则前端只看到「资源状态已变更」，无从判断该怎么改。
    # 5xx 保持笼统文案，不泄露内部实现与路径。
    message = detail if (detail and status < 500) else _ERRORS.get(status, "请求失败")
    return JSONResponse({"code": status, "message": message, "request_id": rid, "data": None},
                        status_code=status, headers={"X-Request-ID": rid, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                                     **({"Retry-After": "60"} if status == 429 else {})})


async def kms_user(request: Request):
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    payload = await run_in_threadpool(decode_token, token) if scheme.lower() == "bearer" else None
    try:
        uid = int(payload["sub"]) if isinstance(payload, dict) else 0
    except (KeyError, TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise HTTPException(401)
    try:
        from kms.security import _load_user
        user = await run_in_threadpool(_load_user, uid)
    except Exception as e:
        logger.error(f"kms_user _load_user threw: {e}")
        raise HTTPException(503)
    if not user or not user.is_active:
        raise HTTPException(401)
    request.state.user = user
    if request.url.path.startswith("/kms/api/admin/"):
        # admin/ 前缀下分两类：
        #   1. 只读基础数据（层级/部门/员工列表）——所有在职员工都需要，用于上传下拉、
        #      仪表盘展示、工单选人；不包含敏感信息，不应被审计员身份卡住。
        #   2. 运营审计专属（机器人绑定/应用密钥/网关审计事件）——仍要求 is_auditor。
        # 具体某接口是否真的对非审计员放行，仍由路由层 Depends 二次判定，这里只是
        # 避免一刀切把基础数据也挡掉（否则非审计员登录后连密级/部门下拉都加载不到）。
        _auditor_only_admin = ("/admin/bot-bindings", "/admin/apps",
                               "/admin/audit-events", "/admin/openapi.json")
        path = request.url.path
        if any(path.startswith(f"/kms/api{a}") for a in _auditor_only_admin):
            if not user.is_auditor:
                raise HTTPException(403)


class EnterpriseBoundary(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(("/gw/", "/kms/api/")):
            return await call_next(request)
        rid = new_request_id()
        request.state.request_id = rid
        # 写入上下文变量：一次请求的全链路日志（含线程池内的 DB/检索调用）凭此关联。
        request_id_var.set(rid)
        channel = "kms" if path.startswith("/kms/") else ("feishu" if "/feishu/" in path else "wecom" if "/wecom/" in path else "embed")
        ip = request.client.host if request.client else "unknown"
        start = time.monotonic()
        # 无法写入开始凭证时根本不进入业务逻辑。
        try:
            await run_in_threadpool(log_gw_event, channel, "request_started", rid, target=path[:255], ip=ip, detail=request.method)
        except Exception as e:
            logger.error(f"log_gw_event started failed: {e}")
            return error_response(503, rid)
        try:
            # 限流已含 DB I/O，必须走线程池，避免阻塞事件循环。
            # 配额与键构造规则由策略注册表统一给出（见 kms/ratelimit.py）。
            if not await run_in_threadpool(ratelimit.check, "gw.ip", ip):
                raise HTTPException(429)
            if path.startswith("/kms/api/") and path != "/kms/api/auth/login" and not path.startswith("/kms/api/auth/sso/") and request.method != "OPTIONS":
                await kms_user(request)
            limit = 11 * 1024 * 1024 if path == "/kms/api/documents" and request.method == "POST" \
                else 65 * 1024 * 1024 if path == "/kms/api/documents/batch-upload" and request.method == "POST" \
                else settings.gw_max_body_bytes
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            response = await call_next(request)
            # SSE 流式响应（/chat?stream=true 等）豁免整包缓冲，逐段转发。
            # 「先审计后放行」对流式天然失效——内容已逐帧送达前端、无法撤回，
            # 硬缓冲只会让用户等全量生成完才一次性看到。安全边界调整为：
            # request_started 已先行留痕（上方），流结束在生成器 finally 里
            # 补记 request_finished，审计链路完整性与非流式口径一致。
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                user = getattr(request.state, "user", None)

                async def sse_relay():
                    try:
                        async for chunk in response.body_iterator:
                            yield chunk
                    finally:
                        try:
                            await run_in_threadpool(log_gw_event, channel, "request_finished", rid,
                                                    app_id=getattr(request.state, "gw_app_id", None),
                                                    employee_no=user.employee_no if user else None,
                                                    target=getattr(request.state, "audit_target", path)[:255],
                                                    status_code=response.status_code, ip=ip,
                                                    elapsed_ms=(time.monotonic() - start) * 1000,
                                                    detail=request.method)
                        except Exception:
                            logger.error(f"SSE 完成审计记录失败 rid={rid}")

                relay = StreamingResponse(sse_relay(), status_code=response.status_code,
                                          headers=dict(response.headers))
                relay.headers["X-Request-ID"] = rid
                relay.headers["Cache-Control"] = "no-store"
                relay.headers["X-Content-Type-Options"] = "nosniff"
                return relay
            # 受控 API 不提前流出正文：完整生成并记完成审计后才放行。
            body, size = [], 0
            async for chunk in response.body_iterator:
                size += len(chunk)
                if size > 16 * 1024 * 1024:
                    raise HTTPException(503)
                body.append(chunk)
            response = Response(b"".join(body), status_code=response.status_code, headers=dict(response.headers))
        except HTTPException as exc:
            response = error_response(exc.status_code, rid, _detail_text(exc.detail))
        except Exception as e:
            logger.error(f"middleware exception path={path}: {type(e).__name__}: {e}", exc_info=True)
            response = error_response(503, rid)
        user = getattr(request.state, "user", None)
        try:
            await run_in_threadpool(log_gw_event, channel, "request_finished", rid,
                                    app_id=getattr(request.state, "gw_app_id", None),
                                    employee_no=user.employee_no if user else None,
                                    target=getattr(request.state, "audit_target", path)[:255], status_code=response.status_code, ip=ip,
                                    elapsed_ms=(time.monotonic() - start) * 1000, detail=request.method)
        except Exception:
            return error_response(503, rid)
        if response.status_code >= 400:
            # 路由层抛出的 HTTPException 由 FastAPI 转成 {"detail": ...}，
            # 这里取回原文，避免二次包装时丢掉业务原因。
            detail = ""
            if response.status_code < 500:
                try:
                    detail = _detail_text(json.loads(response.body).get("detail"))
                except Exception:
                    detail = ""
            cors = {k: v for k, v in response.headers.items() if k.startswith("access-control-") or k == "vary"}
            response = error_response(response.status_code, rid, detail)
            response.headers.update(cors)
        response.headers["X-Request-ID"] = rid
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
