"""存储层：MySQL（文档/分块/历史元数据）+ FAISS（向量检索）。

FAISS 向量层使用 IndexIDMap2 包装 IndexFlatIP（内积 + L2 归一化，等价于余弦相似度）。
faiss_id 为显式单调 ID（非向量位置下标），与 chunks.faiss_id 关联；旧平坦索引仅作为位置下标只读兼容，写入前需迁移为 IDMap2。
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import List, Optional

import faiss
import numpy as np
import pymysql

from config import settings


# ===================== MySQL =====================

class MySQLStore:
    """文档元数据、分块文本、问答历史的持久化。"""

    DDL = [
        """CREATE TABLE IF NOT EXISTS documents (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            filename VARCHAR(512) NOT NULL,
            source_path VARCHAR(1024) NOT NULL,
            file_type VARCHAR(32) NOT NULL,
            content_hash CHAR(64) NOT NULL,
            chunk_count INT NOT NULL DEFAULT 0,
            title VARCHAR(512) NOT NULL DEFAULT '',
            author VARCHAR(256) NOT NULL DEFAULT '',
            language VARCHAR(10) NOT NULL DEFAULT 'zh',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_content_hash (content_hash)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",
        """CREATE TABLE IF NOT EXISTS chunks (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            document_id BIGINT NOT NULL,
            chunk_index INT NOT NULL,
            text TEXT NOT NULL,
            faiss_id BIGINT NOT NULL,
            page INT NOT NULL DEFAULT 0,
            section VARCHAR(512) NOT NULL DEFAULT '',
            text_hash CHAR(16) NOT NULL DEFAULT '',
            embedding_model VARCHAR(128) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_document (document_id),
            INDEX idx_faiss (faiss_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",
        """CREATE TABLE IF NOT EXISTS chat_history (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(64) NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources JSON NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_session (session_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",
    ]

    def __init__(self):
        self._conn_kwargs = dict(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            charset="utf8mb4",
            autocommit=True,
        )
        self._pool = None

    def _get_pool(self):
        """延迟初始化连接池（DBUtils PooledDB）。"""
        if self._pool is None:
            from dbutils.pooled_db import PooledDB
            self._pool = PooledDB(
                creator=pymysql,
                mincached=2,       # 常驻连接数
                maxcached=10,      # 池中最大空闲连接
                maxconnections=20, # 最大连接数（高并发上限）
                blocking=True,     # 池满时等待，不报错
                maxusage=100,      # 单连接最大复用次数（防泄漏）
                **self._conn_kwargs,
            )
        return self._pool

    @contextmanager
    def _conn(self):
        """从连接池获取连接，用完归还（不关闭）。"""
        pool = self._get_pool()
        conn = pool.connection()
        try:
            with conn.cursor(cursor=pymysql.cursors.DictCursor) as cur:
                yield cur
        finally:
            conn.close()  # 归还到连接池（不是真关闭）

    @contextmanager
    def transaction(self):
        """显式事务：用于文档治理的行锁、状态及审批结果原子提交。"""
        conn = self._get_pool().connection()
        try:
            conn.begin()
            with conn.cursor(cursor=pymysql.cursors.DictCursor) as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def close_all(self) -> None:
        """关闭连接池（服务停止时调用）。"""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def ping(self) -> bool:
        """检测 MySQL 连接是否可用。"""
        try:
            with self._conn() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:
            return False

    def init_tables(self) -> None:
        try:
            with self._conn() as cur:
                for ddl in self.DDL:
                    cur.execute(ddl)
        except Exception as e:
            from app.logger import get_logger
            get_logger("store").warning(f"MySQL 初始化失败（可忽略，服务仍可启动）: {e}")

    def get_max_faiss_id(self) -> int:
        """获取 chunks 表中最大的 faiss_id，用于启动时一致性校验。

        返回 -1 表示表为空或查询失败。
        """
        try:
            with self._conn() as cur:
                cur.execute("SELECT COALESCE(MAX(faiss_id), -1) AS max_id FROM chunks")
                row = cur.fetchone()
                return int(row["max_id"]) if row else -1
        except Exception:
            return -1

    def get_chunk_count(self) -> int:
        """获取 chunks 表总行数，用于启动时一致性校验。"""
        try:
            with self._conn() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM chunks")
                row = cur.fetchone()
                return int(row["cnt"]) if row else 0
        except Exception:
            return 0

    def get_all_faiss_ids(self) -> Optional[set]:
        """返回 chunks 表里的全部 faiss_id，供入库落盘前裁剪孤儿向量。

        查询失败时返回 None 而不是空集合：调用方必须能区分「表是空的」和
        「查询失败」，否则一次数据库抖动就会把整个索引清空。
        """
        try:
            with self._conn() as cur:
                cur.execute("SELECT faiss_id FROM chunks")
                return {int(r["faiss_id"]) for r in cur.fetchall()}
        except Exception:
            return None

    def delete_chunks_by_faiss_ids(self, faiss_ids: List[int]) -> None:
        """删除指定 faiss_id 的 chunks 记录（一致性修复用）。"""
        if not faiss_ids:
            return
        placeholders = ",".join(["%s"] * len(faiss_ids))
        with self._conn() as cur:
            cur.execute(
                f"DELETE FROM chunks WHERE faiss_id IN ({placeholders})",
                faiss_ids,
            )

    # ---- 文档 ----
    def add_document(
        self, filename: str, source_path: str, file_type: str, content_hash: str,
        chunk_count: int, title: str = "", author: str = "", language: str = "zh",
    ) -> int:
        """插入文档记录，返回自增 ID。失败时抛出异常（不静默吞没）。"""
        with self._conn() as cur:
            cur.execute(
                "INSERT INTO documents (filename, source_path, file_type, content_hash, "
                "chunk_count, title, author, language) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (filename, source_path, file_type, content_hash,
                 chunk_count, title, author, language),
            )
            return cur.lastrowid

    def delete_document(self, document_id: int) -> None:
        """回滚用：删除文档及其所有分块记录。"""
        if not document_id:
            return
        with self._conn() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id=%s", (document_id,))
            cur.execute("DELETE FROM documents WHERE id=%s", (document_id,))

    def document_exists(self, content_hash: str) -> Optional[int]:
        try:
            with self._conn() as cur:
                cur.execute(
                    "SELECT id FROM documents WHERE content_hash=%s LIMIT 1", (content_hash,)
                )
                row = cur.fetchone()
                return row["id"] if row else None
        except Exception:
            return None

    # ---- 分块 ----
    def add_chunks(self, document_id: int, chunks: List[dict]) -> None:
        """插入分块记录。失败时抛出异常（不静默吞没）。

        chunks: [{"chunk_index": int, "text": str, "faiss_id": int,
                  "page": int, "section": str, "text_hash": str, "embedding_model": str}, ...]
        """
        if not chunks:
            return
        rows = [(
            document_id, c["chunk_index"], c["text"], c["faiss_id"],
            c.get("page", 0), c.get("section", ""),
            c.get("text_hash", ""), c.get("embedding_model", ""),
        ) for c in chunks]
        with self._conn() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, text, faiss_id, "
                "page, section, text_hash, embedding_model) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                rows,
            )

    def get_chunks_by_faiss_ids(self, faiss_ids: List[int]) -> List[dict]:
        if not faiss_ids:
            return []
        try:
            placeholders = ",".join(["%s"] * len(faiss_ids))
            with self._conn() as cur:
                cur.execute(
                    f"SELECT id, document_id, chunk_index, text, faiss_id, "
                    f"page, section, text_hash, embedding_model FROM chunks "
                    f"WHERE faiss_id IN ({placeholders})",
                    faiss_ids,
                )
                rows = cur.fetchall()
            # 保持传入顺序
            order = {fid: i for i, fid in enumerate(faiss_ids)}
            rows.sort(key=lambda r: order.get(r["faiss_id"], 1e9))
            return rows
        except Exception:
            return []

    # ---- 历史 ----
    def add_chat(
        self, session_id: str, question: str, answer: str, sources: Optional[List[dict]] = None
    ) -> int:
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        try:
            with self._conn() as cur:
                cur.execute(
                    "INSERT INTO chat_history (session_id, question, answer, sources) "
                    "VALUES (%s, %s, %s, %s)",
                    (session_id, question, answer, sources_json),
                )
                return cur.lastrowid
        except Exception:
            return 0

    def get_history(self, session_id: str, limit: int = 20) -> List[dict]:
        try:
            with self._conn() as cur:
                cur.execute(
                    "SELECT question, answer, sources, created_at FROM chat_history "
                    "WHERE session_id=%s ORDER BY id DESC LIMIT %s",
                    (session_id, limit),
                )
                rows = cur.fetchall()
            rows.reverse()
            return rows
        except Exception:
            return []


# ===================== FAISS =====================

class VectorStore:
    """FAISS 向量库（余弦相似度，Inner Product + L2 归一化）。

    使用 IndexIDMap2 包装 IndexFlatIP，支持 remove_ids() 精准删除。
    faiss_id 是自定义递增 ID（从 0 开始），不再是位置下标。
    """

    def __init__(self, dim: Optional[int] = None):
        self.dim = dim or settings.embedding_dim
        self._next_id = 0  # 下一个可用的 faiss_id
        self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))
        self._loaded = False

    @property
    def index_file(self) -> str:
        return str(settings.faiss_index_path) + ".index"

    def add(self, embeddings: List[List[float]]) -> List[int]:
        """添加向量，返回对应的 faiss_id 列表（自定义递增 ID）。"""
        if not embeddings:
            return []
        vecs = np.asarray(embeddings, dtype="float32")
        if vecs.shape[1] != self.dim:
            raise ValueError(f"向量维度不匹配: 期望 {self.dim}, 实际 {vecs.shape[1]}")
        faiss.normalize_L2(vecs)
        # 分配前必须与索引里**已存在**的 ID 对齐。_next_id 是进程内计数器，只在
        # load() 时从 id_map 恢复一次；若期间有别的写入方（另一个进程、运维脚本、
        # 或本进程 load() 之后被外部改写并落盘），计数器就会落后。此时继续按旧
        # 值分配，IndexIDMap2 是「同 ID 覆盖」而非报错：新文档入库成功，被顶掉的
        # 那篇文档向量却凭空消失，MySQL 里还会出现两行 chunks 共用一个 faiss_id，
        # 下次启动一致性校验直接拒启（实际发生过）。
        if self.index.ntotal > 0:
            existing_max = max(self.ids())
            if self._next_id <= existing_max:
                self._next_id = existing_max + 1
        # 分配递增 ID
        ids = np.arange(self._next_id, self._next_id + vecs.shape[0], dtype="int64")
        self.index.add_with_ids(vecs, ids)
        self._next_id += vecs.shape[0]
        return list(ids)

    def remove(self, faiss_ids: List[int]) -> int:
        """按 faiss_id 删除向量，返回实际删除数量。"""
        if not faiss_ids:
            return 0
        ids_to_remove = np.asarray(faiss_ids, dtype="int64")
        removed = self.index.remove_ids(ids_to_remove)
        return int(removed)

    def search(self, query_embedding: List[float], top_k: int = 20) -> List[dict]:
        """返回 [{"faiss_id": int, "score": float}, ...] 按分数降序。"""
        if self.index.ntotal == 0:
            return []
        q = np.asarray([query_embedding], dtype="float32")
        faiss.normalize_L2(q)
        k = min(top_k, self.index.ntotal)
        scores, ids = self.index.search(q, k)
        return [
            {"faiss_id": int(ids[0][i]), "score": float(scores[0][i])}
            for i in range(k)
            if ids[0][i] >= 0
        ]

    def save(self) -> None:
        # 防御性保证：索引目录必须存在，否则 faiss.write_index 直接报
        # "could not open ... index.index for writing: No such file or directory"
        import os
        os.makedirs(os.path.dirname(self.index_file) or ".", exist_ok=True)
        # Windows / 中文路径兼容：C++ 层 fopen 不支持 Unicode 路径，
        # 失败时降级为 Python 字节序列化（Python open 支持 Unicode）。
        try:
            faiss.write_index(self.index, self.index_file)
            return
        except RuntimeError as e:
            if "could not open" not in str(e) and "Error" not in str(e):
                raise
            with open(self.index_file, "wb") as f:
                data = faiss.serialize_index(self.index)
                f.write(data.tobytes() if hasattr(data, "tobytes") else bytes(data))

    def load(self) -> None:
        import os
        if os.path.exists(self.index_file):
            try:
                self.index = faiss.read_index(self.index_file)
            except RuntimeError as e:
                # Windows / 中文路径兼容：降级为 Python 读取 + 反序列化
                if "could not open" not in str(e) and "Error" not in str(e):
                    raise
                import numpy as np
                with open(self.index_file, "rb") as f:
                    arr = np.frombuffer(f.read(), dtype=np.uint8)
                self.index = faiss.deserialize_index(arr)
            # 从已加载的索引恢复 _next_id
            # IDMap2 的 id_map 包含所有已分配的 ID
            try:
                id_map = self.index.id_map
                if id_map is not None and id_map.size() > 0:
                    self._next_id = int(faiss.vector_to_array(id_map).max()) + 1
                else:
                    self._next_id = self.index.ntotal
            except Exception:
                self._next_id = self.index.ntotal
        self._loaded = True

    def ids(self) -> List[int]:
        """显式 ID 映射用于启动校验；旧平坦索引按位置兼容只读检索。"""
        if hasattr(self.index, "id_map"):
            return faiss.vector_to_array(self.index.id_map).tolist()
        if isinstance(self.index, faiss.IndexFlat):
            return list(range(self.index.ntotal))
        raise RuntimeError("不支持的索引格式，需在离线迁移后启动")

    @property
    def total(self) -> int:
        return self.index.ntotal


# ===================== BM25 =====================

class BM25Store:
    """BM25 关键词检索（jieba 分词 + rank_bm25）。

    启动时从 ChunkCache 一次性构建，运行时零磁盘 I/O。
    用于混合检索：向量召回（语义） + BM25 召回（关键词），RRF 融合。
    """

    def __init__(self):
        self._faiss_ids: List[int] = []       # BM25 索引位置 -> faiss_id
        self._corpus_tokens: List[List[str]] = []  # 分词后的语料
        self._bm25 = None                     # BM25Okapi 实例（延迟构建）
        self._jieba = None                    # jieba 模块（延迟加载）

    @property
    def jieba(self):
        """延迟加载 jieba，避免启动时卡顿。"""
        if self._jieba is None:
            import jieba
            # 静默模式，不打印加载日志
            jieba.setLogLevel(20)
            self._jieba = jieba
        return self._jieba

    def _tokenize(self, text: str) -> List[str]:
        """jieba 分词，过滤空白 token。"""
        return [w for w in self.jieba.cut(text) if w.strip()]

    def build_from_chunks(self, chunks: List[dict]) -> None:
        """从分块列表构建 BM25 索引。

        chunks: [{"faiss_id": int, "text": str}, ...]
        """
        from rank_bm25 import BM25Okapi

        self._faiss_ids = []
        self._corpus_tokens = []
        for c in chunks:
            fid = c.get("faiss_id")
            text = c.get("text", "")
            if fid is not None and text:
                self._faiss_ids.append(fid)
                self._corpus_tokens.append(self._tokenize(text))

        if self._corpus_tokens:
            self._bm25 = BM25Okapi(self._corpus_tokens)
        else:
            self._bm25 = None

    def add(self, faiss_id: int, text: str) -> None:
        """增量添加单个文档（运行时入库用）。"""
        self._faiss_ids.append(faiss_id)
        self._corpus_tokens.append(self._tokenize(text))
        # rank_bm25 不支持增量更新，需重建
        if self._corpus_tokens:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(self._corpus_tokens)

    def search(self, query: str, top_k: int = 20) -> List[dict]:
        """BM25 检索，返回 [{"faiss_id": int, "score": float}, ...] 按分数降序。"""
        if self._bm25 is None or not self._faiss_ids:
            return []

        tokenized_query = self._tokenize(query)
        if not tokenized_query:
            return []

        scores = self._bm25.get_scores(tokenized_query)

        # 取 top_k，过滤零分文档
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({
                    "faiss_id": self._faiss_ids[idx],
                    "score": float(scores[idx]),
                })
        return results

    @property
    def total(self) -> int:
        return len(self._faiss_ids)
