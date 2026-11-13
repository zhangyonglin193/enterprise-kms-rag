"""FastAPI 路由：/chat（赛题规范） + /health。

赛题接口规范：
- POST /chat
- 请求参数: question (String，评测问题)
- 返回格式: JSON
- 返回字段: answer (String，模型生成的答案)

兼容性：同时支持 JSON body / form-data / query param 三种请求方式，
       避免评测系统请求格式不确定导致 422 错误。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.logger import get_logger
from app.rag import Indexer, Retriever
from config import settings

logger = get_logger("api")

router = APIRouter()

# 全局单例，启动时初始化
_indexer: Indexer | None = None
_retriever: Retriever | None = None


def get_indexer() -> Indexer:
    global _indexer
    if _indexer is None:
        _indexer = Indexer()
    return _indexer


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
        _retriever.warmup()
    return _retriever


# ---- 赛题响应模型 ----
class ChatResponse(BaseModel):
    answer: str = Field(..., description="模型生成的答案")


# ---- 路由 ----
@router.get("/health")
def health():
    retriever = get_retriever()
    return {
        "status": "ok",
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "vectors_total": retriever.vector_store.total,
        "chunks_cached": len(retriever.chunk_cache._faiss_map),
        "bm25_indexed": retriever.bm25_store.total,
        "cache_size": len(retriever._cache),
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request):
    """赛题标准问答接口。

    兼容三种请求格式（评测系统格式不确定，全兼容避免 422）：
    1. JSON body:        {"question": "xxx"}
    2. form-data:        question=xxx
    3. query parameter:  ?question=xxx

    性能关键：单次请求链路 = embed(query) + FAISS search + chunk_cache hit + rerank + LLM
    分块文本已预加载到内存，零 MySQL 查询。
    async 路由 + threadpool：不阻塞事件循环，支持评测系统 100 条连续请求并发。
    """
    from anyio import to_thread

    # ---- 解析 question 参数（兼容 JSON / form-data / query param）----
    question = ""

    # 1. 尝试 JSON body
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
            question = body.get("question", "") if isinstance(body, dict) else ""
        except Exception:
            question = ""

    # 2. 尝试 form-data
    if not question and ("form-data" in content_type or "x-www-form-urlencoded" in content_type):
        try:
            form = await request.form()
            question = form.get("question", "")
        except Exception:
            question = ""

    # 3. 尝试 query param（兜底）
    if not question:
        question = request.query_params.get("question", "")

    # 4. 校验
    if not question or not question.strip():
        logger.warning(f"请求缺少 question 参数: content_type={content_type}")
        raise HTTPException(status_code=422, detail="缺少 question 参数")

    question = question.strip()

    # ---- 调用 RAG 问答 ----
    retriever = get_retriever()
    t0 = time.time()
    try:
        result = await to_thread.run_sync(retriever.answer, question)
    except Exception as e:
        logger.error(f"问答失败: {e}")
        raise HTTPException(status_code=500, detail=f"问答失败: {e}")
    elapsed = (time.time() - t0) * 1000
    logger.info(f"Q={question[:30]}... | 耗时={elapsed:.0f}ms")
    return ChatResponse(answer=result["answer"])
