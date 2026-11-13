"""知识管理系统 —— RAG 核心单例与热更新辅助。

本模块仅暴露三个被活跃链路 import 的函数：
- get_retriever()         — run_kms.py / gateway/service.py
- get_indexer()           — gateway/routes_kms.py
- _hot_update_caches()    — gateway/routes_kms.py（入库后强制刷新内存缓存）

历史上此文件承载过 17 个路由端点（上传/列表/版本/问答/SSE 等），
但 router 从未被 run_kms.py include；文档治理统一迁移到 gateway/routes_kms.py。
"""
from __future__ import annotations

from typing import Optional

from app.logger import get_logger
from app.rag import Indexer, Retriever
from app.store import VectorStore
from config import settings

logger = get_logger("kms")

# ===== 模块级单例（与 app.api 解耦，KMS 独立维护） =====
_indexer: Optional[Indexer] = None
_retriever: Optional[Retriever] = None
_vector_store: Optional[VectorStore] = None


def get_indexer() -> Indexer:
    global _indexer
    if _indexer is None:
        # 与 Retriever 共享同一个 VectorStore 实例，避免入库/检索两侧内存态
        # 不同步导致 save 互相覆盖（新向量丢失或旧向量残留）。
        _indexer = Indexer(vector_store=get_vector_store())
    return _indexer


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever(vector_store=get_vector_store())
        _retriever.warmup()
    return _retriever


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
        _vector_store.load()
    return _vector_store


def _hot_update_caches() -> None:
    """入库后热更新 retriever 内存分块缓存 + BM25（失败不影响入库结果）。"""
    try:
        retriever = get_retriever()
        # 长驻进程需强制重载缓存并刷新 FAISS 内存索引，否则入库后检索不到新文档
        retriever.chunk_cache.load(force=True)
        retriever.vector_store.load()
        if settings.enable_bm25:
            chunks = list(retriever.chunk_cache._faiss_map.values())
            retriever.bm25_store.build_from_chunks(chunks)
    except Exception as e:
        logger.warning(f"热更新缓存/BM25 失败（重启后生效）: {e}")
