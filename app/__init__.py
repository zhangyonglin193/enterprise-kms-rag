"""RAG 问答系统应用包。

模块划分：
- main.py：FastAPI 入口 + 生命周期管理
- api.py：路由定义（/chat + /health）
- rag.py：RAG 核心管线（Indexer + Retriever）
- store.py：存储层（MySQL + FAISS + BM25）
- clients.py：模型客户端（LLM / Embedding / Reranker / OCR）
- document.py：文档加载与分块
- logger.py：统一日志配置
"""