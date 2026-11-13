"""知识文档管理系统 (KMS) 独立启动器。

复用 RAG 检索组件，挂载受控企业接口与工作台；旧不安全入口不挂载。

端口规划（要求）：
    6341        原赛题问答服务（app.api，评测系统直连，本启动器不占用）
    6342-6350   KMS 系统可用端口（默认 6342，可用环境变量 KMS_PORT 覆盖）

运行：
    python run_kms.py
    或  python scripts/service.py kms --env .env.kms --qa-env .env

访问：
    前端仪表盘:  http://localhost:6342/
    赛题问答接口: POST http://localhost:6341/chat   (原 app.api，未改动)
    KMS 接口前缀: /kms/api/*（认证/用户/层级/审计/文档/问答）
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    os.execv(sys.executable, [sys.executable, str(ROOT / "scripts/service.py"), "kms",
                            "--env", os.getenv("RAG_ENV_FILE", str(ROOT / ".env.kms"))])

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.logger import get_logger
from config import settings
from kms.routes import get_retriever
from gateway.routes_kms import router as kms_router, initialize as initialize_governance
from gateway.routes_tickets import router as kms_ticket_router  # 工单中心（两段式，职责审批）
from gateway.routes_knowledge import router as kms_knowledge_router  # 知识中心（发现与统计）
from gateway.routes_upload import router as kms_upload_router  # 批量上传（批次 + 轮询）
from kms.admin_routes import router as kms_admin_router  # 认证 / 用户 / 层级 / 审计
from kms.oidc import router as kms_sso_router           # SSO OIDC 模拟流（authorize → login → token）
from gateway import openapi_router as gw_router, ensure_gateway_tables  # 对外 API 网关

logger = get_logger("kms_main")

# 端口规划: 问答 6341 归原服务；KMS 默认 6342（可用范围 6342-6350）
KMS_PORT = settings.kms_port
KMS_PORT_MIN, KMS_PORT_MAX = 6342, 6350
if not (KMS_PORT_MIN <= KMS_PORT <= KMS_PORT_MAX):
    raise SystemExit(
        f"KMS_PORT={KMS_PORT} 超出允许范围 [{KMS_PORT_MIN}, {KMS_PORT_MAX}]"
        f"（6341 为赛题问答端口，已被原服务占用）"
    )


def _patch_faiss_unicode_paths() -> None:
    """Windows 兼容补丁：FAISS 的 C++ read_index/write_index 不支持中文/Unicode 路径。

    读写均降级为「Python open（支持 Unicode）+ faiss 字节序列化/反序列化」，
    绕过 C++ fopen 的 ANSI 路径限制。不修改任何原有代码。
    """
    import faiss
    _orig_read = faiss.read_index
    _orig_write = faiss.write_index

    def _read_index(path, *args, **kwargs):
        try:
            return _orig_read(path, *args, **kwargs)
        except RuntimeError as e:
            if "could not open" not in str(e):
                raise
            logger.info(f"FAISS 读取降级（Unicode 路径）: {path}")
            import numpy as np
            with open(str(path), "rb") as f:
                arr = np.frombuffer(f.read(), dtype=np.uint8)
            return faiss.deserialize_index(arr)

    def _write_index(index, path, *args, **kwargs):
        # faiss.serialize_index 内部会以 (index, writer, io_flags) 三参调用
        # 模块级 write_index（内存 writer，与文件路径无关），必须透传参数，
        # 且仅对「写文件路径」失败（C++ fopen 不支持中文路径）时才降级。
        try:
            return _orig_write(index, path, *args, **kwargs)
        except RuntimeError as e:
            if args or kwargs or not isinstance(path, (str, Path)):
                raise
            if "could not open" not in str(e) and "Error" not in str(e):
                raise
            logger.info(f"FAISS 写入降级（Unicode 路径）: {path}")
            data = faiss.serialize_index(index)  # 内存序列化，不经过文件路径
            with open(str(path), "wb") as f:
                f.write(data.tobytes() if hasattr(data, "tobytes") else bytes(data))

    faiss.read_index = _read_index
    faiss.write_index = _write_index
    try:
        import faiss.swigfaiss as swig
        swig.read_index = _read_index
        swig.write_index = _write_index
    except Exception:
        pass


_patch_faiss_unicode_paths()

WEB_DIR = ROOT / "kms" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动预热 + 优雅关闭。"""
    # ===== startup =====
    logger.info("=== 知识文档管理系统启动 ===")

    # 调大线程池，提升并发
    from anyio import to_thread
    to_thread.current_default_thread_limiter().total_tokens = settings.thread_pool_size
    logger.info(f"线程池大小: {settings.thread_pool_size}")

    # 预热 RAG 管线（加载 FAISS + 分块缓存 + BM25）
    retriever = get_retriever()

    # 企业模型连接不在启动阶段发送请求，由出域开关及业务授权控制。
    if not settings.gw_model_egress_allowed:
        logger.info("企业模型出域关闭；仅开放治理和授权接口")
    try:
        if settings.gw_model_egress_allowed:
            retriever.embedder.embed_one("预热")
            logger.info("[预热] Embedding 连接就绪")
    except Exception as e:
        logger.warning(f"Embedding 预热失败（不影响服务）: {e}")

    try:
        if settings.gw_model_egress_allowed:
            retriever.llm.chat(
                messages=[{"role": "user", "content": "预热"}],
                max_tokens=1,
                temperature=0.0,
            )
            logger.info("[预热] LLM 模型就绪")
    except Exception as e:
        logger.warning(f"LLM 预热失败（不影响服务）: {e}")

    try:
        if settings.gw_model_egress_allowed:
            retriever.reranker.rerank("预热", ["a"], top_n=1)
            logger.info("[预热] Reranker 模型就绪")
    except Exception as e:
        logger.warning(f"Reranker 预热失败（不影响服务）: {e}")

    logger.info(
        f"预热完成: 向量={retriever.vector_store.total}, "
        f"分块缓存={len(retriever.chunk_cache._faiss_map)}, "
        f"BM25={retriever.bm25_store.total}"
    )

    # 初始化 KMS 权限体系（kms_* 表 + 默认层级/账号，幂等）
    from kms import access_control as acl
    from kms import apps

    if not acl.ensure_kms_acl_tables():
        raise RuntimeError("KMS 权限表不可用，拒绝启动")
    if not apps.ensure_apps_tables():
        raise RuntimeError("应用鉴权表不可用，拒绝启动")

    # 仅执行受控入口必需的增量迁移；不自动发布旧文档、不清理历史表。
    from kms import hr_sync
    if not hr_sync.ensure_hr_sync_columns():
        raise RuntimeError("HR 镜像结构不可用")

    # 银联商务演示员工播种（幂等：工号 20260000~20260031，密码=工号）
    if settings.kms_demo_seed:
        if settings.kms_host != "127.0.0.1":
            raise RuntimeError("演示账号仅允许本机隔离环境")
        from scripts.seed_employees import seed_demo_employees
        seed_demo_employees()
        logger.warning("已启用演示账号；不得用于生产或真实金融数据")

    # 对外 API 网关：审计表 + 机器人身份绑定表（幂等，MySQL 不可用时降级）
    if not ensure_gateway_tables():
        raise RuntimeError("网关安全依赖不可用，拒绝启动")
    from gateway import service, state
    from gateway.audit import log_gw_event, new_request_id
    from gateway.routes_bots import start_worker
    service.migrate()
    # 回收站依赖 documents 的 lifecycle 列（archived_at/archive_reason 等）——
    # 幂等补列，缺失时工单清扫与恢复工单会静默失效
    from kms.lifecycle import ensure_lifecycle_columns
    ensure_lifecycle_columns()
    state.initialize()

    # 组织目录初始化（可插拔适配器：seed 内置种子 / ldap 标准目录 / ad 活动目录）
    from kms.directory import sync_directory
    from kms.org import ensure_org_tables
    from kms.recommend import ensure_recommend_tables
    from kms.versioning import ensure_version_tables
    ensure_org_tables()
    dir_result = sync_directory()
    logger.info(f"组织目录就绪: adapter={dir_result['adapter']} 节点={dir_result['org_nodes']} "
                f"员工同步={'yes' if dir_result['employees'] else 'no'}")
    ensure_recommend_tables()
    ensure_version_tables()
    logger.info(f"目录源 KMS_DIRECTORY_SOURCE={settings.kms_directory_source} / "
                f"统一登录 KMS_OIDC_PROVIDER={settings.kms_oidc_provider}")

    initialize_governance()
    log_gw_event("kms", "service_started", new_request_id(), target="kms")
    stop, worker = start_worker() if settings.gw_enabled else (None, None)
    app.state.ready = True
    logger.info("外部渠道入口: /gw/api/v1/bots/feishu|wecom + /gw/api/v1/embed/*")

    logger.info(f"前端仪表盘: http://localhost:{KMS_PORT}/")
    logger.info(f"KMS 管理接口: http://localhost:{KMS_PORT}/kms/api/*")
    logger.info("赛题问答接口: POST http://localhost:6341/chat（原服务，未改动）")

    try:
        yield
    finally:
        app.state.ready = False
        if stop is not None:
            stop.set()
            await to_thread.run_sync(lambda: worker.join(timeout=30))
            if worker.is_alive():
                raise RuntimeError("投递线程未在期限内停止，跳过连接关闭；未确认任务由租约恢复，须核对重复投递")

    # ===== shutdown =====
    logger.info("=== 系统关闭，清理连接池 ===")
    for client_name in ("embedder", "reranker", "llm"):
        client = getattr(retriever, client_name, None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    try:
        retriever.mysql.close_all()
        logger.info("MySQL 连接池已关闭")
    except Exception:
        pass
    logger.info("连接池已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="知识文档管理系统 (RAG Knowledge Hub)",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        description="知识文档全生命周期管理 + RAG 增强问答，支持文档入库、检索溯源、系统监控。",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.kms_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 0. API 网关中间件（速率限制 + 审计日志）
    from gateway.middleware import EnterpriseBoundary
    app.add_middleware(EnterpriseBoundary)
    app.state.ready = False

    @app.get("/readyz", include_in_schema=False)
    async def readiness():
        from fastapi.responses import JSONResponse
        ready = app.state.ready
        return JSONResponse({"service": "kms", "ready": ready}, status_code=200 if ready else 503)

    @app.get("/kms/api/admin/openapi.json", include_in_schema=False)
    async def protected_openapi():
        return app.openapi()

    # 2. KMS 管理接口（认证/用户/层级/审计: /kms/api/admin/* + /kms/api/auth/*）
    app.include_router(kms_admin_router)

    # 2.1 SSO OIDC 模拟流（/kms/api/auth/sso/*）
    app.include_router(kms_sso_router)

    # 3. KMS 业务接口（文档/批量上传/问答: /kms/api/*）
    app.include_router(kms_router)

    # 3.1 权限隔离定向推荐（/kms/api/recommendations）
    from kms.recommend import router as kms_rec_router
    app.include_router(kms_rec_router)

    # 3.2 工单中心（/kms/api/tickets + /kms/api/notifications）
    # 审批按「ticket_approve 职责」匹配，无管理员角色；两段式审批通过即系统执行。
    app.include_router(kms_ticket_router)

    # 3.3 知识中心（/kms/api/knowledge/*）——只提供有数据基础的统计
    app.include_router(kms_knowledge_router)

    # 3.4 批量上传（/kms/api/documents/batch-upload + /kms/api/upload/batches/{id}）
    app.include_router(kms_upload_router)

    # 旧的统计与会话历史接口仍不挂载：它们会绕开统一文档授权与双人发布。
    # 对应源代码保留，恢复前必须完成迁移与权限回归测试。

    # 5. 对外 API 网关（飞书/企微机器人 + 嵌入式组件，统一 /gw/api/v1 前缀）
    if settings.gw_enabled:
        app.include_router(gw_router)
    else:
        logger.warning("GW_ENABLED=0，对外 API 网关未启用")

    # 6. 前端静态资源
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(str(WEB_DIR / "index.html"))
    else:
        logger.warning(f"前端目录不存在: {WEB_DIR}")

    # 前端页面与静态资源强制协商缓存（no-cache 仍走 ETag 校验，流量无损），
    # 防止浏览器沿用旧版前端代码调用已下线的接口而报 404。
    # 刻意用**纯 ASGI**而非 @app.middleware("http")（BaseHTTPMiddleware）：
    # 后者会包装 StreamingResponse 的 body_iterator，实测把 SSE 流式响应
    # 缓冲成整包下发（512 帧同刻到达），问答逐字输出失效。纯 ASGI 只在
    # http.response.start 时改 header，不碰响应体，流式零影响。
    class _NoCacheFrontend:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            path = scope.get("path", "")
            if path != "/" and not path.startswith("/static/"):
                await self.app(scope, receive, send)
                return

            async def send_with_no_cache(message):
                if message["type"] == "http.response.start":
                    # 移除已有 cache-control 后追加，避免重复头
                    headers = [(k, v) for k, v in (message.get("headers") or [])
                               if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-cache"))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_no_cache)

    app.add_middleware(_NoCacheFrontend)

    return app


app = create_app()
