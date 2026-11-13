"""嵌入方 BFF 示例：应用 Key 只留服务端，员工令牌每次交给网关验证。
运行前设置 EMBED_API_KEY、KMS_BASE_URL；默认本机 6343，不替代 6341 主服务。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_audit_lock = threading.Lock()


def audit_event(event, rid, path, status=0, downstream=""):
    directory = Path(os.getenv("BFF_AUDIT_DIR", str(ROOT / "data/bff/audit")))
    now = datetime.now(timezone.utc)
    record = dict(time=now.isoformat(), event=event, request_id=rid, path=path[:255], status=status, downstream=downstream[:64])
    with _audit_lock:
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / (now.strftime("%Y%m%d") + ".jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


@app.middleware("http")
async def audit_boundary(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    rid = "bff-" + uuid.uuid4().hex
    try:
        await run_in_threadpool(audit_event, "started", rid, request.url.path)
        response = await call_next(request)
        body, size = [], 0
        async for chunk in response.body_iterator:
            size += len(chunk)
            if size > 16 * 1024 * 1024:
                raise RuntimeError("响应过大")
            body.append(chunk)
        await run_in_threadpool(audit_event, "finished", rid, request.url.path, response.status_code, response.headers.get("X-Request-ID", ""))
        response = Response(b"".join(body), status_code=response.status_code, headers=dict(response.headers))
    except Exception:
        response = JSONResponse({"message": "服务或审计暂不可用", "request_id": rid}, status_code=503)
    response.headers["X-BFF-Request-ID"] = rid
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/chat")
async def chat(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or len(auth) > 4096:
        return JSONResponse({"message": "需要有效员工令牌"}, status_code=401)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 65536:
            return JSONResponse({"message": "请求体过大"}, status_code=413)
        chunks.append(chunk)
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(app.state.gateway + "/gw/api/v1/embed/chat",
                content=b"".join(chunks), headers={"X-API-Key": app.state.key, "Authorization": auth, "Content-Type": "application/json"})
        return JSONResponse(response.json(), status_code=response.status_code,
                            headers={"Cache-Control": "no-store", "X-Request-ID": response.headers.get("X-Request-ID", "")})
    except Exception:
        return JSONResponse({"message": "知识服务暂不可用"}, status_code=503)


@app.get("/widget.js")
def widget():
    return FileResponse(ROOT / "kms/web/knowledge-widget.js", media_type="text/javascript")


@app.get("/")
def page():
    return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>嵌入方 BFF 示例</title>
    <main style="max-width:800px;margin:40px auto;font-family:system-ui"><h1>嵌入式知识助手</h1>
    <p>演示时粘贴短期员工令牌；正式集成由宿主 SSO 会话提供，不将应用 Key 放入浏览器。</p>
    <input id="token" type="password" autocomplete="off" placeholder="短期员工 Bearer Token">
    <enterprise-knowledge endpoint="/api/chat"></enterprise-knowledge></main>
    <script type="module">import '/widget.js';document.querySelector('enterprise-knowledge').tokenProvider=()=>document.getElementById('token').value;</script></html>''', headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn
    from scripts.service import bind_socket
    key = os.getenv("EMBED_API_KEY", "")
    gateway = os.getenv("KMS_BASE_URL", "http://127.0.0.1:6342").rstrip("/")
    target = urlparse(gateway)
    port = int(os.getenv("EMBED_PORT", "6343"))
    if not key or not 6342 <= (target.port or 0) <= 6350 or not 6342 <= port <= 6350 or port == target.port:
        raise SystemExit("应用 Key、网关地址或附加模块端口配置无效")
    if target.username or target.password or target.path or target.query or target.fragment:
        raise SystemExit("网关地址不得包含用户信息、路径、查询或片段")
    if target.scheme != "https" and not (target.scheme == "http" and target.hostname == "127.0.0.1"):
        raise SystemExit("非本机网关必须使用 HTTPS")
    app.state.key, app.state.gateway = key, gateway
    with bind_socket("kms", "127.0.0.1", port) as sock:
        uvicorn.Server(uvicorn.Config(app, access_log=False, proxy_headers=False)).run(sockets=[sock])
