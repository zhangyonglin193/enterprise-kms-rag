"""FastAPI 入口：在 QA_PORT 启动服务，启动时预热，停止时关闭连接。

运行：
    python -m app.main
    python app/main.py  (也支持)
    python scripts/service.py qa --env .env
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 确保项目根目录在 sys.path 中，支持直接运行 python app/main.py
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import os
    os.execv(sys.executable, [sys.executable, str(ROOT / "scripts/service.py"), "qa",
                            "--env", os.getenv("RAG_ENV_FILE", str(ROOT / ".env"))])

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router, get_retriever
from app.logger import get_logger
from config import settings

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期：启动预热 + 停止时关闭连接池。"""
    # ===== startup =====
    logger.info("=== 服务启动预热 ===")
    # 调大线程池（默认 40 → 100，提升并发处理能力）
    from anyio import to_thread
    to_thread.current_default_thread_limiter().total_tokens = settings.thread_pool_size
    logger.info(f"线程池大小: {settings.thread_pool_size}")

    logger.info(f"加载 FAISS 索引: {settings.faiss_index_path}")
    logger.info(f"加载分块缓存 + BM25 索引...")
    retriever = get_retriever()

    # ===== 全链路连接预热（消除硅基流动 MaaS 平台冷启动延迟） =====
    # 预热 1/3：Embedding（建立 TCP 长连接）
    try:
        retriever.embedder.embed_one("预热")
        logger.info("[预热 1/3] Embedding 连接预热完成")
    except Exception as e:
        logger.warning(f"Embedding 预热失败（不影响服务）: {e}")

    # 预热 2/3：LLM（max_tokens=1 轻量请求，触发模型实例加载）
    # 硅基流动存在冷启动，首次调用可能需 2-4 秒加载模型到显存
    try:
        retriever.llm.chat(
            messages=[{"role": "user", "content": "预热"}],
            max_tokens=1,
            temperature=0.0,
        )
        logger.info("[预热 2/3] LLM 模型预热完成")
    except Exception as e:
        logger.warning(f"LLM 预热失败（不影响服务）: {e}")

    # 预热 3/3：Reranker（top_n=1 最小请求，触发模型加载）
    try:
        retriever.reranker.rerank("预热", ["a"], top_n=1)
        logger.info("[预热 3/3] Reranker 模型预热完成")
    except Exception as e:
        logger.warning(f"Reranker 预热失败（不影响服务）: {e}")

    logger.info(
        f"预热完成: 向量总数={retriever.vector_store.total}, "
        f"分块缓存={len(retriever.chunk_cache._faiss_map)}, "
        f"BM25索引={retriever.bm25_store.total}"
    )
    logger.info(f"全链路预热就绪: http://0.0.0.0:{settings.qa_port}/chat")

    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False

    # ===== shutdown：关闭 HTTP 连接池 + MySQL 连接池，防止泄漏 =====
    logger.info("=== 服务关闭，清理连接池 ===")
    for client_name in ("embedder", "reranker", "llm"):
        client = getattr(retriever, client_name, None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    # 关闭 MySQL 连接池
    try:
        retriever.mysql.close_all()
        logger.info("MySQL 连接池已关闭")
    except Exception:
        pass
    logger.info("连接池已关闭")


def create_app() -> FastAPI:
    app = FastAPI(title="RAG 问答服务", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.state.ready = False

    @app.get("/readyz", include_in_schema=False)
    async def readiness():
        from fastapi.responses import JSONResponse
        ready = app.state.ready
        return JSONResponse({"service": "qa", "ready": ready}, status_code=200 if ready else 503)
    return app


app = create_app()
