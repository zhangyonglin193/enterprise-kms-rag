"""SSO 单点登录（OIDC 模拟流）。

竞赛环境无真实企业 IdP/AD，本模块实现标准 OIDC Relying Party 协议流程，
全部 302 浏览器重定向，评委能在浏览器里亲眼看到 SSO 跑通。

协议流程（标准 OIDC Authorization Code Flow）
---------------------------------------------
1. 浏览器 → GET  /kms/api/auth/sso/authorize?redirect_uri=...&state=...
   → KMS 检查 KMS_SESSION cookie（KMS 自己内置的模拟 IdP 会话）
   → 若已登录：302 回 redirect_uri?code=CODE&state=STATE
   → 若未登录：302 到 /auth/sso/login?code_challenge=...&redirect_uri=...&state=...

2. 用户在 /auth/sso/login 页面输入工号+密码（或已有 cookie 自动跳过）
   → 验证后 302 回 redirect_uri?code=CODE&state=STATE

3. 第三方应用（或 KMS 自己前端）POST /kms/api/auth/sso/token
   {code: CODE, client_id: "kms-web", redirect_uri: "..."}
   → KMS 用一次性 code 换 KMS JWT

安全设计
--------
- code 一次性、60 秒过期、绑定 redirect_uri
- state 参数原样透传防 CSRF
- 登录 cookie HTTP-only + SameSite=Lax
- 演示 client_id "kms-web" 对应 KMS 前端
"""
from __future__ import annotations

import json
import secrets
import time
from http.cookies import SimpleCookie
from typing import Optional
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from app.logger import get_logger
from config import settings
from . import access_control as acl
from .security import (
    TOKEN_TTL_HOURS,
    AuthUser,
    client_ip,
    create_token,
    verify_password,
)

logger = get_logger("kms.sso")

router = APIRouter(prefix="/kms/api/auth/sso", tags=["sso"])

# 令牌有效期单一来源：原 4 处硬编码 expires_in=3600，改 KMS_TOKEN_EXPIRE_HOURS 时
# 不会同步，导致对外声明的有效期与实际 JWT 过期时间脱节。
TOKEN_TTL_SECONDS = TOKEN_TTL_HOURS * 3600

# ===================== 内存存储（竞赛用） =====================
# code → {employee_no, redirect_uri, expires_at}
_pending_codes: dict[str, dict] = {}
# session_cookie → employee_no（KMS 内置 IdP 会话）
_idp_sessions: dict[str, dict] = {}
_COOKIE_NAME = "KMS_SSO_SESSION"
_CODE_TTL_SECONDS = 60
_SESSION_TTL_SECONDS = 3600


# ===================== 基础工具 =====================
def _cleanup_expired() -> None:
    now = time.time()
    for code in [c for c, v in _pending_codes.items() if v["expires_at"] < now]:
        _pending_codes.pop(code, None)
    for sid in [s for s, v in _idp_sessions.items() if v["expires_at"] < now]:
        _idp_sessions.pop(sid, None)


def _issue_code(employee_no: str, redirect_uri: str) -> str:
    _cleanup_expired()
    code = secrets.token_urlsafe(32)
    _pending_codes[code] = {
        "employee_no": employee_no,
        "redirect_uri": redirect_uri,
        "expires_at": time.time() + _CODE_TTL_SECONDS,
    }
    return code


def _consume_code(code: str, redirect_uri: str) -> Optional[str]:
    """一次性消费 code → 返回 employee_no。任何不匹配都返回 None。"""
    _cleanup_expired()
    item = _pending_codes.pop(code, None)
    if not item:
        return None
    if item["redirect_uri"] != redirect_uri:
        logger.warning("SSO code redirect_uri 不匹配")
        return None
    if item["expires_at"] < time.time():
        return None
    return item["employee_no"]


def _create_session(employee_no: str) -> str:
    sid = secrets.token_urlsafe(32)
    _idp_sessions[sid] = {
        "employee_no": employee_no,
        "created_at": time.time(),
        "expires_at": time.time() + _SESSION_TTL_SECONDS,
    }
    return sid


def _resolve_session(request: Request) -> Optional[str]:
    cookie_header = request.headers.get("cookie", "")
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        return None
    morsel = jar.get(_COOKIE_NAME)
    if not morsel:
        return None
    _cleanup_expired()
    item = _idp_sessions.get(morsel.value)
    if not item or item["expires_at"] < time.time():
        return None
    return item["employee_no"]


# ===================== OIDC 端点 =====================
@router.get("/authorize")
def sso_authorize(
    request: Request,
    redirect_uri: str = Query(...),
    state: str = Query(""),
    client_id: str = Query("kms-web"),
    response_type: str = Query("code"),
):
    """OIDC Authorization Endpoint（302 重定向）。

    有 KMS_SESSION cookie → 已登录：直接发 code 并 302 回 redirect_uri
    否则 → 302 到 /auth/sso/login，带完整返回参数
    """
    if response_type != "code":
        raise HTTPException(400, "仅支持 response_type=code")

    employee_no = _resolve_session(request)
    if employee_no:
        code = _issue_code(employee_no, redirect_uri)
        params = {"code": code}
        if state:
            params["state"] = state
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(redirect_uri + sep + urlencode(params), status_code=302)

    # 未登录 → 302 到 KMS 内置登录页（模拟 IdP 登录）
    login_params = {
        "redirect_uri": redirect_uri,
        "state": state,
        "client_id": client_id,
    }
    sep = "&" if "?" in str(request.url_for("sso_authorize_login_page")) else "?"
    login_url = str(request.url_for("sso_authorize_login_page")) + sep + urlencode(login_params)
    return RedirectResponse(login_url, status_code=302)


@router.get("/login-page")
def sso_authorize_login_page(
    request: Request,
    redirect_uri: str = Query(...),
    state: str = Query(""),
    client_id: str = Query("kms-web"),
):
    """KMS 内置模拟 IdP 登录页（HTML，工号+密码表单）。"""
    post_url = str(request.url_for("sso_authorize_login_submit"))
    # 注：redirect_uri/state/client_id 由下方三个 <input type="hidden"> 逐个传递；
    # 曾用 urlencode() 拼成整串，改为独立 input 后该变量已无引用，故删除。
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>KMS 单点登录（SSO）</title>
<style>
body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f5f7fa;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{background:#fff;padding:36px 40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.08);width:360px}}
h2{{margin:0 0 4px;color:#1a2b4a}}
.sub{{color:#6b7a90;font-size:13px;margin-bottom:24px}}
label{{display:block;font-size:13px;color:#4a5568;margin-bottom:4px}}
input{{width:100%;padding:10px 12px;border:1px solid #d1dce5;border-radius:6px;font-size:14px;box-sizing:border-box;margin-bottom:14px}}
input:focus{{outline:none;border-color:#4299e1}}
button{{width:100%;padding:11px;background:#2b6cb0;color:#fff;border:0;border-radius:6px;font-size:14px;cursor:pointer}}
button:hover{{background:#2c5282}}
.err{{color:#c53030;font-size:13px;margin-bottom:10px}}
.hint{{font-size:12px;color:#a0aec0;margin-top:16px;text-align:center}}
.hint code{{background:#edf2f7;padding:1px 5px;border-radius:3px}}
</style></head><body>
<div class="box">
<h2>KMS 单点登录</h2>
<p class="sub">KMS 内置模拟 IdP · Authorization Code Flow</p>
<form method="post" action="{post_url}">
<input type="hidden" name="redirect_uri" value="{redirect_uri}">
<input type="hidden" name="state" value="{state}">
<input type="hidden" name="client_id" value="{client_id}">
<label>工号</label>
<input name="employee_no" placeholder="20260019" required>
<label>密码</label>
<input name="password" type="password" required>
<button type="submit">登录并继续</button>
</form>
<p class="hint">演示账号：<code>20260019</code>/<code>20260019</code> <code>20260029</code>/<code>20260029</code> <code>20260030</code>/<code>20260030</code></p>
</div></body></html>""")


@router.post("/login-submit")
async def sso_authorize_login_submit(
    request: Request,
    redirect_uri: str = Query(...),
    state: str = Query(""),
    client_id: str = Query("kms-web"),
):
    """处理登录表单 → 验证 → 发 session cookie → 发 code → 302 回 redirect_uri。

    原实现是同步 def 且直接调 `request.body()` —— Starlette 的 body() 是协程，
    同步路由里漏 await 拿到的是 coroutine 对象，`.decode()` 抛 AttributeError 后被
    `except Exception` 吞掉转成 400，导致**本端点恒返回 400**，整个 OIDC 流程断裂。
    现改为 async def + `await request.body()`；函数体内的同步 DB/密码校验则统一
    包进 run_in_threadpool，避免把阻塞带进事件循环。
    """

    try:
        body = await request.body()
        qs = parse_qs(body.decode("utf-8"))
        employee_no = (qs.get("employee_no") or [""])[0]
        password = qs.get("password", [""])[0]
    except Exception:
        raise HTTPException(400, "无效表单")

    row = await run_in_threadpool(acl.get_user_by_employee_no, employee_no.strip())
    ok = bool(row) and await run_in_threadpool(
        verify_password, password, row["password_hash"])
    if not ok:
        # 登录失败 → 回登录页显示错误
        params = urlencode({
            "redirect_uri": redirect_uri,
            "state": state,
            "client_id": client_id,
            "error": "工号或密码错误",
        })
        return RedirectResponse(
            str(request.url_for("sso_authorize_login_page")) + "?" + params,
            status_code=302,
        )
    if not row["is_active"]:
        raise HTTPException(403, "账号已停用")

    # 创建 KMS 内置 IdP session（cookie）
    sid = await run_in_threadpool(_create_session, employee_no.strip())
    await run_in_threadpool(
        acl.add_audit, AuthUser(row), "sso_login", target=employee_no,
        detail="SSO authorize→login→code", ip=client_ip(request))

    code = await run_in_threadpool(_issue_code, employee_no.strip(), redirect_uri)
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    response = RedirectResponse(redirect_uri + sep + urlencode(params), status_code=302)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=sid,
        httponly=True,
        samesite="lax",
        max_age=_SESSION_TTL_SECONDS,
        path="/kms/api/auth/sso",
    )
    return response


@router.post("/token")
async def sso_token(request: Request):
    """Token Endpoint（code → KMS JWT）。

    竞赛演示版：form-urlencoded → JSON。
    真实 OIDC 这里会从 IdP 换 access_token + id_token，
    本系统直接用 code 换内部 KMS JWT（等价于 SP 换本地会话令牌）。

    同 login-submit：原为同步 def 且漏 `await request.body()`，恒返回 400。
    """
    try:
        body = parse_qs((await request.body()).decode("utf-8"))
    except Exception:
        raise HTTPException(400, "无效请求体")

    code = (body.get("code") or [""])[0]
    redirect_uri = (body.get("redirect_uri") or [""])[0]
    client_id = (body.get("client_id") or ["kms-web"])[0]

    if not code or not redirect_uri:
        raise HTTPException(400, "code 和 redirect_uri 必填")

    employee_no = _consume_code(code, redirect_uri)
    if not employee_no:
        raise HTTPException(400, {"error": "invalid_grant", "message": "code 无效或已过期"})

    row = await run_in_threadpool(acl.get_user_by_employee_no, employee_no)
    if not row or not row["is_active"]:
        raise HTTPException(403, "账号不可用")

    token = await run_in_threadpool(
        create_token,
        user_id=int(row["id"]),
        employee_no=row["employee_no"],
        security_level=int(row["security_level"]),
        department=row.get("department", "") or "",
    )

    await run_in_threadpool(
        acl.add_audit, AuthUser(row), "sso_token_exchange", target=employee_no,
        detail="code→KMS JWT", ip=client_ip(request))

    return {
        "access_token": token,
        "token_type": "Bearer",
        # 与 kms/security.TOKEN_TTL_HOURS 同源，避免改令牌有效期时此处不同步
        "expires_in": int(TOKEN_TTL_SECONDS),
        "scope": "openid profile email",
        "id_token": json.dumps({
            "sub": str(row["id"]),
            "emp": row["employee_no"],
            "name": row["username"],
            "department": row.get("department", "") or "",
            "level": int(row["security_level"]),
            "iss": "unionpay-kms-oidc-sim",
            "aud": client_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }, ensure_ascii=False),
    }


@router.post("/exchange")
async def sso_external_exchange(request: Request):
    """外部 OI 平台令牌交换：校验外部 id_token → 映射内部员工 → 签发 KMS JWT。

    仅 KMS_OIDC_PROVIDER=external 时可用；内置模拟 IdP 请改用 /token。
    body 支持 application/json 与 form-urlencoded 的 id_token 字段。
    """
    from urllib.parse import parse_qs

    try:
        raw = (await request.body()).decode("utf-8")
    except Exception:
        raise HTTPException(400, "无效请求体") from None

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            id_token = (json.loads(raw or "{}") or {}).get("id_token", "") or ""
        except (ValueError, AttributeError):
            raise HTTPException(400, "无效 JSON 请求体") from None
    else:
        id_token = (parse_qs(raw).get("id_token") or [""])[0]

    if not id_token:
        raise HTTPException(400, "缺少 id_token")

    from .oidc_provider import build_oidc_provider
    provider = build_oidc_provider()
    if provider.name != "external":
        raise HTTPException(400, "内置模拟 IdP 请使用 /kms/api/auth/sso/token 交换")

    claims = provider.verify_id_token(id_token)
    employee_no = claims["employee_no"]
    row = acl.get_user_by_employee_no(employee_no)
    if not row or not row["is_active"]:
        raise HTTPException(403, "账号不存在或已停用")

    token = create_token(
        user_id=int(row["id"]),
        employee_no=row["employee_no"],
        security_level=int(row["security_level"]),
        department=row.get("department", "") or "",
    )
    acl.add_audit(AuthUser(row), "sso_external_exchange", target=employee_no,
                  detail=f"iss={claims.get('iss')}", ip=client_ip(request))
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": int(TOKEN_TTL_SECONDS),
        "scope": "openid profile email",
        "id_token": json.dumps({
            "sub": str(row["id"]),
            "emp": row["employee_no"],
            "name": row["username"],
            "department": row.get("department", "") or "",
            "level": int(row["security_level"]),
            "iss": settings.kms_oidc_issuer or "unionpay-kms-oidc-ext",
            "aud": settings.kms_oidc_client_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }, ensure_ascii=False),
    }


@router.post("/logout")
def sso_logout(request: Request):
    """模拟 IdP logout：清 cookie + 返回前端跳转 URL。"""
    employee_no = _resolve_session(request)
    if employee_no:
        acl.add_audit(None, "sso_logout", target=employee_no, ip=client_ip(request))

    response = RedirectResponse("/auth/sso/login-page", status_code=302)
    response.delete_cookie(_COOKIE_NAME, path="/kms/api/auth/sso")
    return response


# ===================== 便捷辅助 =====================
def sso_authorize_url(redirect_uri: str, state: str = "", client_id: str = "kms-web") -> str:
    """构造 authorize URL（供前端/第三方生成跳转链接）。"""
    params = urlencode({
        "redirect_uri": redirect_uri,
        "state": state,
        "client_id": client_id,
        "response_type": "code",
    })
    return f"/kms/api/auth/sso/authorize?{params}"
