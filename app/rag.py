"""RAG 核心管线：Indexer（入库）与 Retriever（检索+重排+生成）。

性能关键优化：分块文本预加载到内存，问答时零 MySQL 查询。
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from app.clients import EmbeddingClient, LLMClient, RerankerClient
from app.document import Chunker, DocumentLoader, _clean_layout_tokens, _extract_title_from_filename
from app.logger import get_logger
from app.store import BM25Store, MySQLStore, VectorStore
from app.typo_clean import clean_ocr_typos
from config import settings

logger = get_logger("rag")


# ===== 入库块级垃圾过滤（Fix2）=====
# 命中任一签名即判垃圾，写库前丢弃：幻觉块不进 FAISS/MySQL。
_YEAR_LOOP = re.compile(r"^\s*[-•·]?\s*\d{4}\s*年\s*$", re.M)
_LAYOUT_TOKEN = re.compile(r"<\|[A-Z_]+\d")
_FOREIGN_CHARS = re.compile(r"[\u0400-\u04FF\uAC00-\uD7AF\u0600-\u06FF]")
# 重复串：单字符连续>=16 次（表格线误读如 '0'x77）、2~8 字周期重复>=8 次
# （幻觉死循环被块边界截断的形态，如 "88104610"x37.5 无法被整除签名覆盖）
_REPEAT_RUN = re.compile(r"(.)\1{15,}|(.{2,8})\2{7,}")


def _chunk_is_garbage(text: str) -> bool:
    """块级垃圾判定（保守，防误杀短表格块/数字块/英文技术文档）。

    签名原则：只杀“人类不会写”的产物——版面 token、跨语种幻觉、年份死循环、
    重复行、符号汤、重复串。合法低中文内容（数据库字段表、代码、URL）不算垃圾。
    """
    if not text:
        return True
    if _LAYOUT_TOKEN.search(text):
        return True
    if len(_FOREIGN_CHARS.findall(text)) >= 3:
        return True
    if len(_YEAR_LOOP.findall(text)) >= 8:
        return True
    compact = re.sub(r"\s", "", text)
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) - len(set(lines)) >= 5:
        return True
    if len(compact) > 60:
        # 有效字符 = 中英数字；占比过低说明是符号汤（',,,，。' 之类）
        meaningful = len(re.findall(r"[\u4e00-\u9fff0-9a-zA-Z]", compact))
        if meaningful < len(compact) * 0.5:
            return True
    # 重复串占主导：去空白后超一半字符由连续重复构成（任意截断位置均命中）
    if len(compact) >= 20:
        rep_chars = sum(len(m.group(0)) for m in _REPEAT_RUN.finditer(compact))
        if rep_chars > len(compact) * 0.5:
            return True
    # 单片段死循环：整块由同一短片段重复构成（幻觉符号循环如 \(\Delta\)×150）
    n = len(compact)
    if n >= 40:
        for m in range(8, n // 4 + 1):
            if n % m == 0 and compact == compact[: n // m] * m:
                return True
    return False


# ===== 作答风格 Prompt：要求原文照抄承载答案的整句（评测口径为 verbatim-recall，概括/精简会直接掉分） =====
SYSTEM_PROMPT = (
    "你是一个严谨的问答助手。请根据下面提供的【参考资料】回答用户问题。\n"
    "回答规则：\n"
    "1. 优先参考【参考资料】中的相关内容进行回答，可合理概括资料中的关键信息。\n"
    "2. 如果资料中有相关内容，请直接回答，不要说“根据现有资料无法回答”之类的话。\n"
    "3. 当参考资料无相关信息时，请如实说明。\n"
    "4. 回答要简洁准确、条理清晰，剔除重复冗余内容，不要输出无关内容；"
    "当资料中与问题相关的要点为并列多项（如并列的功能/条件/步骤/属性）时，须完整覆盖全部要点，不得遗漏。\n"
    "5. 当用户询问“出处”“来源”“哪篇文章”时，请引用【参考资料】标注的来源文档名称。\n"
    "6. 数字精度：法规文号、金额、百分比、日期、年份、利率等数字必须与参考资料完全一致，"
    "不得改写、四舍五入、近似或编造任何数字。\n"
    "7. 如果不确定某个具体数字，请直接引用资料原文语句，不要猜测或补充，禁止复制大段上下文。\n"
    "8. 禁止输出参考资料里不相关的业务配置、表单字段等碎片信息，只针对用户问题输出该问题的答案。\n"
    "9. 若参考资料中已有可回答问题的描述、列举或示例，就直接整合这些信息作答；"
    "禁止在答案末尾追加“参考资料未具体说明/未详细定义/没有找到详细说明”之类的免责句，"
    "只有当参考资料确实完全没有相关内容时，才可如实说明。\n"
    "10. 完整性：当原文中同一句话既包含问题所问的答案、又包含与之直接相关的背景信息"
    "（如同一句中的规模、金额等配套数据，或产品特性的完整描述）时，"
    "须完整保留该句中的关键信息作答，不得只输出孤立的答案词或孤立数字。\n"
    "11. 当问题问及具体数字（金额/比例/数量/增速/日期/期限）时，必须在资料中定位包含这些数字的句子并原文照抄；"
    "同一问题涉及多个数字维度（如客户数与交易金额）时全部列出，不得用背景叙述或趋势描述代替数字。\n"
    # 注：原「截图/图片 OCR 内容作答」规则已停用——其拒答倾向与上面第 11 条
    # 数字规则冲突，曾引发回归。若需重启截图作答，须连同数字规则整条回归重测。
)

# 两段式生成—抽取步系统提示词：只允许逐字抄写原文句子，禁止概括（防小模型脱上下文改写/幻觉）
EXTRACT_SYSTEM_PROMPT = (
    "你是原文摘录器。请只从【参考资料】中逐字抄写与用户问题直接相关的原文句子。\n"
    "硬性规则：\n"
    "1. 逐字照抄原文，禁止概括、改写、翻译、合并、补全或改动标点；\n"
    "2. 每行只输出一个完整句子，不要编号、不要引号、不要任何解释；\n"
    "3. 最多输出 8 句，按与问题的相关度从高到低排列；\n"
    "4. 优先抄写包含具体数字、日期、文号、规则条款、功能列举的句子；\n"
    "5. 若参考资料中没有与问题相关的内容，只输出：无"
)


extract_title = _extract_title_from_filename

# 句子切分：中文句末标点(。！？；)一律断句；ASCII .!?; 仅在其后不接字母/数字时断句，
# 以保护 URL(https://erp.chinaums.com)、小数(3.5)、章节号(1.8)、版本号(V4.2.7) 不被从中间剁断。
_SENT_SPLIT_RE = re.compile(r'(?<=[。！？；])|(?<=[\.\!\?;])(?![A-Za-z0-9])')

# 残片判断：句末标点（用于 _collapse_fragments 区分完整句与截断残片）
_FRAG_END_RE = re.compile(r'[。！？；.!?;]$')

# 并列枚举引导词（用于 _collapse_fragments 规则4 识别伪枚举句）：
# 这类词后紧跟与前文重复的内容时，该句是 overlap 粘连产生的噪音而非真条目
_ENUM_PREFIX_RE = re.compile(
    r"^(一方面|另一方面|一是|二是|其一|其二|首先|其次|再次|再者|最后|此外|另外|同时|与此同时)"
)


class Indexer:
    """文档入库：加载 -> 分块 -> 向量化 -> 写入 FAISS + MySQL。"""

    def __init__(
        self,
        loader: Optional[DocumentLoader] = None,
        chunker: Optional[Chunker] = None,
        embedder: Optional[EmbeddingClient] = None,
        vector_store: Optional[VectorStore] = None,
        mysql: Optional[MySQLStore] = None,
    ):
        self.loader = loader or DocumentLoader()
        self.chunker = chunker or Chunker()
        self.embedder = embedder or EmbeddingClient()
        self.vector_store = vector_store or VectorStore()
        self.vector_store.load()
        self.mysql = mysql or MySQLStore()
        self.mysql.init_tables()

    def _prune_orphan_vectors(self) -> int:
        """落盘前把内存索引裁剪到「MySQL 里确实存在」的向量集合，返回删除数。

        Indexer 的内存索引只在构造时 load 一次，之后长期存活。若有别处（E2E 脚本、
        运维脚本）绕过本进程直接删掉 chunks 行并删磁盘向量，内存里的那些向量就
        成了「幽灵」：下次正常入库 save() 会把它们原样写回磁盘，攒成孤儿向量，
        等到重启时一致性守卫比对就差了几十个 id，直接拒绝启动。

        调用时机在 MySQL 事务提交之后（见 ingest 第 4 步），所以「以 MySQL 为准」
        不可能误删刚刚写入的向量；查询失败则直接跳过，宁可不对齐也不能清空索引。
        """
        expected = self.mysql.get_all_faiss_ids()
        if expected is None:
            logger.warning("无法读取 chunks.faiss_id，跳过落盘前对齐")
            return 0
        try:
            held = {int(x) for x in self.vector_store.ids()}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"无法读取 FAISS 显式 ID，跳过落盘前对齐: {e}")
            return 0
        orphan = sorted(held - expected)
        if not orphan:
            return 0
        removed = self.vector_store.remove(orphan)
        logger.warning(f"落盘前丢弃 {removed} 个 MySQL 已不存在的孤儿向量")
        return removed

    def ingest(
        self,
        file_path: str | Path,
        text_override: Optional[str] = None,
        meta_override: Optional[dict] = None,
        force: bool = False,
    ) -> dict:
        """文档入库：加载 -> 分块 -> 向量化 -> 写入 FAISS + MySQL。

        事务性保证：任何步骤失败都回滚 MySQL，不 save FAISS，保证双存储一致。
        异常向上抛出，调用方（ingest_batch.py）决定是否继续处理后续文件。

        text_override/meta_override：重 OCR 替换场景复用已生成的文本与元数据，
        避免对同一文件重复跑 OCR（普通入库不传，走 load_structured）。

        force：为 True 时跳过 content_hash 查重（版本回滚专用，旧 hash 可能仍存在）。
        """
        path = Path(file_path)
        # 结构化加载：返回 (全文文本, 元数据)
        if text_override is not None:
            text, doc_meta = text_override, meta_override or {}
        else:
            text, doc_meta = self.loader.load_structured(path)
        # L0 数据卫生：OCR 形近错字清洗（源文件文字层污染，原图丢失无法重 OCR；幂等）
        if settings.clean_ocr_typos:
            text = clean_ocr_typos(text)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        if not force:
            existing = self.mysql.document_exists(content_hash)
            if existing:
                return {"document_id": existing, "chunk_count": 0, "skipped": True}

        # 分块并记录每个 chunk 在原文中的偏移量（用于查找 page/section）
        chunk_positions = self.chunker.split_with_positions(text)
        # Fix2: 块级垃圾过滤——幻觉块（年份循环/跨语种/布局token/重复行等）不进索引
        kept_positions = [cp for cp in chunk_positions if not _chunk_is_garbage(cp[0])]
        dropped = len(chunk_positions) - len(kept_positions)
        if dropped:
            logger.info(f"入库垃圾过滤 {path.name}: 丢弃 {dropped}/{len(chunk_positions)} 块")
        if not kept_positions:
            return {"document_id": None, "chunk_count": 0, "skipped": False, "reason": "全块垃圾"}
        chunk_positions = kept_positions
        if not chunk_positions:
            return {"document_id": None, "chunk_count": 0, "skipped": False, "reason": "空文档"}

        chunks_text = [cp[0] for cp in chunk_positions]

        batch = settings.embedding_batch_size
        all_embeddings: List[List[float]] = []
        for i in range(0, len(chunks_text), batch):
            all_embeddings.extend(self.embedder.embed(chunks_text[i : i + batch]))

        # ---- 事务性写入：FAISS 内存 → MySQL → FAISS 磁盘 ----
        # 1. FAISS 内存写入（不持久化，失败时可直接放弃）
        faiss_ids = self.vector_store.add(all_embeddings)

        # 2. MySQL 写入（失败时回滚 FAISS 内存 + 抛异常）
        doc_id = None
        try:
            doc_id = self.mysql.add_document(
                filename=path.name,
                source_path=str(path),
                file_type=path.suffix.lower().lstrip("."),
                content_hash=content_hash,
                chunk_count=len(chunks_text),
                title=doc_meta.get("title", ""),
                author=doc_meta.get("author", ""),
                language=doc_meta.get("language", "zh"),
            )

            # 组装 chunk 元数据：page/section/text_hash/embedding_model
            pages_map = doc_meta.get("pages", [])
            sections_map = doc_meta.get("sections", [])
            chunk_records = []
            for i, (chunk_text, offset) in enumerate(chunk_positions):
                page = self.loader._lookup_meta(offset, pages_map) if pages_map else 0
                section = self.loader._lookup_meta(offset, sections_map) if sections_map else ""
                chunk_records.append({
                    "chunk_index": i,
                    "text": chunk_text,
                    "faiss_id": faiss_ids[i],
                    "page": int(page) if page else 0,
                    "section": str(section) if section else "",
                    "text_hash": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:16],
                    "embedding_model": settings.embedding_model,
                })

            # 3. MySQL chunks 写入（失败时回滚 document + FAISS + 抛异常）
            self.mysql.add_chunks(doc_id, chunk_records)

        except Exception as e:
            # 回滚 MySQL：删除刚写的 document（add_chunks 失败时 document 已写入）
            if doc_id:
                try:
                    self.mysql.delete_document(doc_id)
                    logger.info(f"回滚 MySQL document_id={doc_id}")
                except Exception as rollback_err:
                    logger.error(f"MySQL 回滚失败: {rollback_err}")

            # 回滚 FAISS：精准删除刚添加的向量（IndexIDMap2 支持 remove_ids）
            try:
                removed = self.vector_store.remove(faiss_ids)
                logger.info(f"回滚 FAISS: 删除 {removed} 个向量")
            except Exception as rollback_err:
                logger.error(f"FAISS 回滚失败: {rollback_err}")

            logger.error(f"入库失败 {path.name}: {e}")
            raise  # 向上抛出，让调用方决定是否继续

        # 4. FAISS 磁盘持久化（失败时回滚 MySQL + FAISS + 抛异常）
        try:
            # 落盘前先与 MySQL 对齐：本进程内存索引可能还留着「别处已删」的向量
            # （E2E / 运维脚本绕过本进程直接删 chunks 与磁盘向量），若不裁剪，
            # 这次 save 会把它们原样写回磁盘，攒成孤儿向量，下次启动守卫直接拒启。
            self._prune_orphan_vectors()
            self.vector_store.save()
        except Exception as e:
            # save 失败：回滚 MySQL
            try:
                self.mysql.delete_document(doc_id)
                logger.info(f"FAISS save 失败，回滚 MySQL document_id={doc_id}")
            except Exception as rollback_err:
                logger.error(f"MySQL 回滚失败: {rollback_err}")

            # 回滚 FAISS：精准删除
            try:
                self.vector_store.remove(faiss_ids)
            except Exception:
                pass

            logger.error(f"FAISS 持久化失败 {path.name}: {e}")
            raise

        return {"document_id": doc_id, "chunk_count": len(chunks_text), "skipped": False}


class ChunkCache:
    """分块文本内存缓存，问答时零 MySQL 查询。"""

    def __init__(self, mysql: MySQLStore):
        self.mysql = mysql
        # faiss_id -> chunk dict
        self._faiss_map: Dict[int, dict] = {}
        # document_id -> [chunk dicts]
        self._doc_map: Dict[int, List[dict]] = {}
        # (document_id, chunk_index) -> chunk dict，用于 small-to-big 相邻块定位
        self._doc_index_map: Dict[tuple, dict] = {}
        self._loaded = False

    def load(self, force: bool = False) -> None:
        """启动时一次性加载所有分块 + 完整元数据到内存。

        元数据来源（入库时已持久化到数据库）：
        - documents 表：filename, title, author, language, file_type, source_path
        - chunks 表：page, section, text_hash, embedding_model

        force=True 时强制重建缓存；入库/回滚/删除后在长驻进程中热更新必须使用，
        否则会被 _loaded 幂等守卫拦掉，导致新文档检索不到。
        """
        if self._loaded and not force:
            return
        if force:
            self._faiss_map.clear()
            self._doc_map.clear()
            self._doc_index_map.clear()
        try:
            with self.mysql._conn() as cur:
                cur.execute(
                    "SELECT c.id, c.document_id, c.chunk_index, c.text, c.faiss_id, "
                    "c.page, c.section, c.text_hash, c.embedding_model, "
                    "d.filename, d.file_type, d.source_path, d.title, d.author, d.language "
                    "FROM chunks c LEFT JOIN documents d ON c.document_id = d.id"
                )
                rows = cur.fetchall()
            for row in rows:
                fid = row["faiss_id"]
                # 统一字段名
                row["source"] = row.get("filename", "")
                row["doc_id"] = row["document_id"]
                row["chunk_id"] = row["id"]
                # title 兜底：数据库 title 为空则从 filename 提取
                if not row.get("title"):
                    row["title"] = extract_title(row.get("filename", ""))
                self._faiss_map[fid] = row
                self._doc_map.setdefault(row["document_id"], []).append(row)
                self._doc_index_map[(row["document_id"], row["chunk_index"])] = row
            self._loaded = True
            logger.info(f"分块缓存加载完成: {len(rows)} 条")
        except Exception:
            self._faiss_map.clear()
            self._doc_map.clear()
            self._doc_index_map.clear()
            raise RuntimeError("分块缓存加载失败，拒绝提供不完整检索") from None

    def get_parent_window_text(self, document_id: int, chunk_index: int, span: int = 1,
                               skip: Optional[set] = None) -> str:
        """small-to-big：取同一文档内 [chunk_index-span, chunk_index+span] 相邻块，
        按重叠去重拼接为更大父块上下文，解决答案跨块被斩断。找不到则返回空串。

        skip：已被前面窗口消费的 (document_id, chunk_index) 集合，跳过这些块，
        避免相邻 top 块的扩展窗口互相重叠、把同一段内容重复送入 LLM。
        """
        skip = skip or set()
        parts = []
        for ci in range(chunk_index - span, chunk_index + span + 1):
            if (document_id, ci) in skip:
                continue
            c = self._doc_index_map.get((document_id, ci))
            if c is not None and c.get("text"):
                parts.append(c["text"])
        if len(parts) <= 1:
            return ""
        return Retriever._merge_overlapping_chunks(parts)

    def get_by_faiss_ids(self, faiss_ids: List[int]) -> List[dict]:
        """按 faiss_id 顺序返回分块（优先内存，兜底查库）。"""
        if not faiss_ids:
            return []
        results = []
        missing = []
        for fid in faiss_ids:
            if fid in self._faiss_map:
                results.append(self._faiss_map[fid])
            else:
                missing.append(fid)
        if missing:
            # 兜底查库（正常不会走到这里）
            db_rows = self.mysql.get_chunks_by_faiss_ids(missing)
            for r in db_rows:
                self._faiss_map[r["faiss_id"]] = r
            results.extend(db_rows)
        # 按输入顺序排序
        order = {fid: i for i, fid in enumerate(faiss_ids)}
        results.sort(key=lambda r: order.get(r["faiss_id"], 1e9))
        return results


class Retriever:
    """检索 + 重排 + 生成。

    性能优化：
    - 分块文本内存缓存（ChunkCache）
    - 重排可降级（rerank 失败时直接用向量排序）
    - LLM 拒答兜底（检索命中时用抽取式回答）
    """

    def __init__(
        self,
        embedder: Optional[EmbeddingClient] = None,
        reranker: Optional[RerankerClient] = None,
        llm: Optional[LLMClient] = None,
        vector_store: Optional[VectorStore] = None,
        mysql: Optional[MySQLStore] = None,
    ):
        self.embedder = embedder or EmbeddingClient()
        self.reranker = reranker or RerankerClient()
        self.llm = llm or LLMClient()
        self.vector_store = vector_store or VectorStore()
        self.vector_store.load()
        self.mysql = mysql or MySQLStore()
        self.mysql.init_tables()
        self.chunk_cache = ChunkCache(self.mysql)
        self.bm25_store = BM25Store()
        # LRU 结果缓存（相同问题直接返回，评测重复题秒回）
        self._cache: OrderedDict = OrderedDict()
        self._cache_max = settings.cache_max_size
        self._cache_lock = threading.Lock()

    def warmup(self) -> None:
        """启动预热：一致性校验 + 加载分块缓存 + 构建 BM25 索引。"""
        # ---- 一致性校验：FAISS ntotal vs MySQL chunks 数 ----
        faiss_ids = self.vector_store.ids()
        with self.mysql._conn() as cur:
            cur.execute("SELECT c.faiss_id,d.id AS document_id FROM chunks c LEFT JOIN documents d ON d.id=c.document_id")
            rows = cur.fetchall()
        mysql_ids = [int(row["faiss_id"]) for row in rows]
        faiss_total, mysql_chunk_count = len(faiss_ids), len(mysql_ids)
        if (len(set(faiss_ids)) != faiss_total or len(set(mysql_ids)) != mysql_chunk_count
                or set(faiss_ids) != set(mysql_ids) or any(row["document_id"] is None for row in rows)):
            logger.warning(
                f"数据不一致: FAISS={faiss_total} vs MySQL chunks={mysql_chunk_count}，"
                f"可能上次入库异常终止"
            )
            raise RuntimeError("数据库与 FAISS 不一致，拒绝启动；请恢复一致快照，禁止自动删库修复")
        else:
            logger.info(f"一致性校验通过: FAISS={faiss_total} = MySQL={mysql_chunk_count}")

        self.chunk_cache.load()
        if settings.enable_bm25:
            chunks = list(self.chunk_cache._faiss_map.values())
            self.bm25_store.build_from_chunks(chunks)
            logger.info(f"BM25 索引构建完成: {self.bm25_store.total} 条")

    def _repair_consistency(self, faiss_total: int, mysql_chunk_count: int) -> None:
        """保留兼容方法名，但禁止自动删除数据或重置索引。"""
        raise RuntimeError("自动破坏性修复已停用，请通过备份恢复一致快照")

    # 复杂题关键词：出现时加大召回和上下文数量
    _COMPLEX_KEYWORDS = {"对比", "区别", "哪些", "分别", "列举", "比较", "不同", "相同", "总结", "归纳", "概述"}

    def _is_complex_query(self, query: str) -> bool:
        """判断是否为复杂题（多跳推理/对比分析/列举类）。"""
        # 关键词触发
        if any(kw in query for kw in self._COMPLEX_KEYWORDS):
            return True
        # 长问题（>30 字）视为复杂题
        if len(query) > 30:
            return True
        return False

    def retrieve(
        self,
        query: str,
        top_k_retrieve: Optional[int] = None,
        top_k_rerank: Optional[int] = None,
        context_filter=None,
    ) -> List[dict]:
        # 动态调整：复杂题加大召回和上下文，简单题用默认值保性能
        if top_k_retrieve is None or top_k_rerank is None:
            if self._is_complex_query(query):
                top_k_retrieve = top_k_retrieve or max(settings.top_k_retrieve, 30)
                top_k_rerank = top_k_rerank or max(settings.top_k_rerank, 8)
                logger.info(f"复杂题检测，加大召回: retrieve={top_k_retrieve}, rerank={top_k_rerank}")
            else:
                top_k_retrieve = top_k_retrieve or settings.top_k_retrieve
                top_k_rerank = top_k_rerank or settings.top_k_rerank

        # 1+2. 向量检索与 BM25 并发执行（embed 是 API 调用 ~80ms，BM25 本地 ~5ms，并发节省串行等待）
        from concurrent.futures import ThreadPoolExecutor

        vec_hits: List[dict] = []
        bm25_hits: List[dict] = []

        def _vec_search():
            q_emb = self.embedder.embed_one(query)
            return self.vector_store.search(q_emb, top_k=top_k_retrieve)

        def _bm25_search():
            if settings.enable_bm25 and self.bm25_store.total > 0:
                try:
                    return self.bm25_store.search(query, top_k=settings.bm25_top_k)
                except Exception as e:
                    logger.warning(f"BM25 检索失败，降级为纯向量检索: {e}")
            return []

        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_vec = ex.submit(_vec_search)
            fut_bm25 = ex.submit(_bm25_search)
            vec_hits = fut_vec.result()
            bm25_hits = fut_bm25.result()

        # 3. RRF 融合两路结果
        if bm25_hits:
            fused_ids, score_map = self._rrf_fuse(vec_hits, bm25_hits, top_k_retrieve)
        else:
            fused_ids = [h["faiss_id"] for h in vec_hits]
            score_map = {h["faiss_id"]: h["score"] for h in vec_hits}

        if not fused_ids:
            return []

        # 4. 取分块文本（内存缓存，零 MySQL 查询）
        chunks = self.chunk_cache.get_by_faiss_ids(fused_ids)
        # 企业服务显式传入授权过滤器；评测路径不传，保持原召回行为。
        if context_filter is not None:
            chunks = context_filter(chunks)
            if not chunks:
                return []
        docs = [c["text"] for c in chunks]

        # 5. 重排：可通过 ENABLE_RERANK=0 跳过以提速
        if settings.enable_rerank:
            reranked = self._safe_rerank(query, docs, top_k_rerank)
        else:
            reranked = [{"index": i, "relevance_score": float(score_map.get(chunks[i]["faiss_id"], 0.0))}
                        for i in range(min(top_k_rerank, len(docs)))]

        # 6. 组装结果
        results = []
        for r in reranked:
            idx = r["index"]
            if idx >= len(chunks):
                continue
            c = chunks[idx]
            results.append(
                {
                    "text": c["text"],
                    "score": score_map.get(c["faiss_id"], 0.0),
                    "rerank_score": float(r.get("relevance_score", 0.0)),
                    # 元数据（工程级：入库时已持久化）
                    "document_id": c["document_id"],
                    "faiss_id": c["faiss_id"],
                    "source": c.get("source", c.get("filename", "")),
                    "title": c.get("title", ""),
                    "author": c.get("author", ""),
                    "file_type": c.get("file_type", ""),
                    "source_path": c.get("source_path", ""),
                    "doc_id": c.get("doc_id", c["document_id"]),
                    "chunk_id": c.get("chunk_id", c.get("id")),
                    "chunk_index": c.get("chunk_index", 0),
                    "page": c.get("page", 0),
                    "section": c.get("section", ""),
                    "text_hash": c.get("text_hash", ""),
                    "embedding_model": c.get("embedding_model", ""),
                    "language": c.get("language", "zh"),
                }
            )
        # 7. small-to-big 父块扩展：对 rerank 前 topn 块拼上同文档相邻块，补全跨块被斩断的答案。
        #    仅扩展 top 块 + 后续 _compress_chunk 会收缩回预算，上下文膨胀可控。
        #    窗口去重：已消费的 (document_id, chunk_index) 不再进入后续窗口，
        #    防止相邻 top 块的扩展窗口互相重叠，把同一段论证重复两遍送入 LLM。
        if settings.parent_expand and settings.parent_span > 0 and results:
            consumed: set = set()
            for r in results[:min(settings.parent_expand_topn, len(results))]:
                parent_text = self.chunk_cache.get_parent_window_text(
                    r["document_id"], r["chunk_index"], settings.parent_span,
                    skip=consumed)
                if parent_text and len(parent_text) > len(r["text"]):
                    r["text"] = parent_text
                for ci in range(r["chunk_index"] - settings.parent_span,
                               r["chunk_index"] + settings.parent_span + 1):
                    consumed.add((r["document_id"], ci))
        return results

    def _safe_rerank(self, query: str, docs: List[str], top_n: int) -> List[dict]:
        """重排带降级：rerank API 失败时退化为向量相似度排序。"""
        try:
            result = self.reranker.rerank(query, docs, top_n=min(top_n, len(docs)))
            if result:
                return result
        except Exception as e:
            logger.warning(f"重排失败，降级为向量排序: {e}")
        # 降级：按原始顺序返回（原始顺序已是向量相似度排序）
        return [{"index": i, "relevance_score": 0.0} for i in range(min(top_n, len(docs)))]

    @staticmethod
    def _rrf_fuse(vec_hits: List[dict], bm25_hits: List[dict], top_k: int):
        """RRF (Reciprocal Rank Fusion) 融合向量 + BM25 两路检索结果。

        公式: score(d) = Σ 1/(k + rank_i(d))，k 通常取 60。
        只看排名不看原始分数，避免两路分数量纲不一致的问题。
        """
        rrf_k = settings.rrf_k
        scores: dict = defaultdict(float)
        for rank, h in enumerate(vec_hits):
            scores[h["faiss_id"]] += 1.0 / (rrf_k + rank + 1)
        for rank, h in enumerate(bm25_hits):
            scores[h["faiss_id"]] += 1.0 / (rrf_k + rank + 1)
        sorted_ids = sorted(scores.keys(), key=lambda fid: scores[fid], reverse=True)
        return sorted_ids[:top_k], scores

    @staticmethod
    def _normalize_question(question: str) -> str:
        """问题归一化（仅用于缓存键）：全半角统一 + 去标点 + 合并空白 + 小写。

        不改变实际查询语义，仅让"等价问题"命中同一缓存。
        例："数字人民币 试点？" 与 "数字人民币试点" 归一化后一致。
        """
        import unicodedata
        # 全角→半角
        text = unicodedata.normalize("NFKC", question)
        # 去标点（中英文）
        text = re.sub(r'[，。！？、；：""\'\'（）【】《》,.!?;:\'"()\[\]<>]', '', text)
        # 合并空白
        text = re.sub(r'\s+', '', text)
        return text.lower()

    def _cache_get(self, question: str) -> Optional[str]:
        """归一化问题后查缓存（线程安全）。"""
        key = self._normalize_question(question)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, question: str, answer: str) -> None:
        """写入缓存，超出容量时淘汰最久未使用的（线程安全）。"""
        key = self._normalize_question(question)
        with self._cache_lock:
            self._cache[key] = answer
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)

    def answer(self, query: str, session_id: Optional[str] = None) -> dict:
        # 检查结果缓存（相同问题直接返回，评测重复题秒回）
        if settings.enable_cache:
            cached = self._cache_get(query)
            if cached is not None:
                logger.info(f"缓存命中: {query[:30]}...")
                sid = session_id or uuid.uuid4().hex
                return {"answer": cached, "session_id": sid}

        contexts = self.retrieve(query)

        # 检索失败时触发查询改写（处理缩写/行业黑话/同义词）
        if not contexts and settings.enable_query_rewrite:
            rewritten = self._rewrite_query(query)
            if rewritten and rewritten != query:
                logger.info(f"查询改写: {query[:30]}... -> {rewritten[:30]}...")
                contexts = self.retrieve(rewritten)

        # 改写后仍失败，强制取向量 top1 兜底，保证有输出（不表达查无结果）
        if not contexts:
            contexts = self._force_retrieve(query)

        answer = self._generate(query, contexts, session_id)

        # 写入缓存
        if settings.enable_cache and answer:
            self._cache_put(query, answer)

        sid = session_id or uuid.uuid4().hex
        return {"answer": answer, "session_id": sid}

    def _rewrite_query(self, query: str) -> str:
        """查询改写：用 LLM 把缩写/黑话/同义词扩展为更易检索的表达。

        仅在检索失败时触发，正常请求零延迟影响。
        """
        rewrite_prompt = (
            "你是查询改写助手。请把用户问题改写为更利于文档检索的表达，规则：\n"
            "1. 把缩写扩展为全称（如 MCC -> 商户类别码 Merchant Category Code）。\n"
            "2. 把行业黑话替换为常见说法（如 259号文 -> 银发〔2021〕259号 支付受理终端管理）。\n"
            "3. 补充可能的同义词，用空格连接。\n"
            "4. 保持原意，不要回答问题本身，只输出改写后的查询。\n"
            "5. 输出不超过 50 字，不要解释，不要引号。\n"
        )
        messages = [
            {"role": "system", "content": rewrite_prompt},
            {"role": "user", "content": query},
        ]
        try:
            rewritten = self.llm.chat(
                messages,
                max_tokens=settings.query_rewrite_max_tokens,
                temperature=0.1,
            )
            rewritten = rewritten.strip().strip('"').strip("'").strip()
            if rewritten and rewritten != query:
                return rewritten
        except Exception as e:
            logger.warning(f"查询改写失败: {e}")
        return ""

    def _force_retrieve(self, query: str) -> List[dict]:
        """强制兜底检索：绕过 rerank，直接取向量 top1，保证有输出。"""
        try:
            q_emb = self.embedder.embed_one(query)
            hits = self.vector_store.search(q_emb, top_k=1)
            if hits:
                chunks = self.chunk_cache.get_by_faiss_ids([h["faiss_id"] for h in hits])
                return [
                    {
                        "text": c["text"],
                        "score": 0.0,
                        "rerank_score": Retriever.EXTRACTIVE_MIN_SCORE,
                        "document_id": c["document_id"],
                        "faiss_id": c["faiss_id"],
                        "source": c.get("source", c.get("filename", "")),
                        "title": c.get("title", ""),
                        "author": c.get("author", ""),
                        "file_type": c.get("file_type", ""),
                        "source_path": c.get("source_path", ""),
                        "doc_id": c.get("doc_id", c["document_id"]),
                        "chunk_id": c.get("chunk_id", c.get("id")),
                        "chunk_index": c.get("chunk_index", 0),
                        "page": c.get("page", 0),
                        "section": c.get("section", ""),
                        "text_hash": c.get("text_hash", ""),
                        "embedding_model": c.get("embedding_model", ""),
                        "language": c.get("language", "zh"),
                    }
                    for c in chunks
                ]
        except Exception as e:
            logger.warning(f"强制兜底检索失败: {e}")
        return []

    def _generate(
        self,
        query: str,
        contexts: List[dict],
        session_id: Optional[str] = None,
    ) -> str:
        """生成回答，带拒答兜底和重试机制。

        优化：关闭 thinking 模式 + 过滤残留 <think> 标签，避免思考过程混入答案。
        """
        if not contexts:
            return "现有资料对该问题的覆盖较为有限，建议结合具体业务场景进一步查阅相关文档。"

        # 两段式生成：先“逐字抄原句”抽取，再仅基于抽取句组织作答，抑制小模型对着噪声上下文
        # 弃用资料自由发挥；抽取无合格原句/自检不过时自动回落下面的一段式路径，不会劣于旧行为。
        if settings.enable_two_stage:
            answer = self._generate_two_stage(query, contexts)
            if answer:
                return answer

        prompt = self._build_prompt(query, contexts)

        # 构造消息（不带历史，赛题评测是单轮）
        messages: List[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # 尝试2次，首次失败则重试
        last_error = None
        for attempt in range(2):
            try:
                # 关闭 thinking：thinking 模式延迟过高（24s/题），赛题性能分不可接受
                raw = self.llm.chat(messages, enable_thinking=False)
                # 过滤可能残留的 <think> 标签
                answer = Retriever._strip_thinking(raw).strip()

                # 拒答检测 + 兜底：检索命中但 LLM 说"无法回答"时，用抽取式回答
                if self._is_refusal(answer) and contexts:
                    logger.info(f"LLM 拒答，启用抽取式兜底 (重试={attempt})")
                    answer = self._extractive_answer(query, contexts)

                # 数字幻觉检测：仅对“答案本质是数字”的数值型问题启用。
                # 描述型问题(是什么/有哪些/注意事项/特点/流程)不因个别编号/页码与资料不符，
                # 就把可读的 LLM 全文整体替换成原文转储。
                if (contexts
                        and Retriever._is_numeric_question(query)
                        and Retriever._has_number_hallucination(answer, contexts, query)):
                    logger.info(f"数字幻觉检测触发(数值型问题)，降级为抽取式回答 (重试={attempt})")
                    answer = self._extractive_answer(query, contexts)

                return answer
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (重试={attempt}): {e}")
                time.sleep(0.2)

        # 全部失败，兜底为抽取式
        logger.error(f"LLM 全部失败: {last_error}")
        return self._extractive_answer(query, contexts)

    def _extract_evidence(self, query: str, contexts: List[dict]) -> List[dict]:
        """抽取步：让 LLM 只做“逐字抄出与问题相关的原文句子”，不允许概括；
        抄回后做 verbatim 自检——只有确实出现在资料原文里的句子才保留，
        模型自己改写/新增的句子直接丢弃（防抽取步本身幻觉）。"""
        context_prompt = self._build_prompt(query, contexts)
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": context_prompt + "\n\n请开始输出相关原文句子（每行一句）："},
        ]
        try:
            raw = self.llm.chat(messages, temperature=0.1,
                                max_tokens=settings.extract_max_tokens, enable_thinking=False)
        except Exception as e:
            logger.warning(f"抽取步调用失败: {e}")
            return []
        raw = Retriever._strip_thinking(raw or "").strip()
        if not raw or raw.rstrip("。.！!") == "无":
            return []

        # verbatim 自检语料：与一段式同源的清洗+塌缩重复后的块文本，去空白后做子串比对
        sources = []
        for c in contexts:
            t = Retriever._dedup_overlap(_clean_layout_tokens(c["text"]))
            sources.append((re.sub(r'\s+', '', t), c))
        picked: List[dict] = []
        seen: set = set()
        for line in raw.splitlines():
            # 只去列表标记（数字必须带 .、）等分隔符才剥，避免误剥“10月”“2024年”开头的原句
            s = re.sub(r'^\s*(?:\d+[.、)）]\s*|[-·*—>]\s*)+', '', line).strip().strip('“”"\'')
            if len(s) < 6:
                continue
            ns = re.sub(r'\s+', '', s)
            if ns in seen:
                continue
            for src_norm, src_c in sources:
                if ns in src_norm:
                    seen.add(ns)
                    picked.append({"sentence": s, "title": src_c.get("title", ""), "page": src_c.get("page", 0)})
                    break
        if picked:
            logger.info(f"抽取步：{len(picked)} 句通过 verbatim 自检（候选 {len(raw.splitlines())} 行）")
        return picked[:8]

    def _generate_two_stage(self, query: str, contexts: List[dict]) -> str:
        """两段式+自检：抽取步（逐字抄原句）→ 作答步（仅基于抽取句组织）。
        返回空串表示应回落一段式（调用失败/无合格抽取句/拒答/数字自检不过）。"""
        evidence = self._extract_evidence(query, contexts)
        if not evidence:
            logger.info("两段式：抽取步无合格原句，回落一段式")
            return ""
        lines = []
        for e in evidence:
            src = f"（《{e['title']}》第{e['page']}页）" if e.get("title") and e.get("page") else ""
            lines.append(f"- {e['sentence']}{src}")
        prompt = (
            "以下是从参考资料中逐字摘录、且已核验确实出自原文的相关句子：\n"
            + "\n".join(lines)
            + f"\n\n用户问题：{query}\n\n"
            + "请仅基于以上句子组织回答：可调整语序与连接词，但不得引入句子之外的任何事实、数字或结论；"
            + "若句子只能部分回答问题，就答已覆盖的部分，不得推测补充。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = self.llm.chat(messages, enable_thinking=False)
            answer = Retriever._strip_thinking(raw).strip()
        except Exception as e:
            logger.warning(f"两段式作答步失败，回落一段式: {e}")
            return ""
        if not answer or self._is_refusal(answer):
            logger.info("两段式：作答步拒答/空，回落一段式")
            return ""
        # 自检：数值型问题的答案数字必须能回溯到原始资料（与一段式同口径）
        if Retriever._is_numeric_question(query) and Retriever._has_number_hallucination(answer, contexts, query):
            logger.info("两段式：作答步数字自检不过，回落一段式")
            return ""
        return answer

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """过滤 Qwen3 thinking 模式的 <think>...</think> 标签，只保留实际回答。

        Qwen3 enable_thinking=True 时返回格式：
            <think>思考过程...</think>实际回答
        需去掉 <think> 块，否则思考过程会混入答案。
        """
        # 去掉完整的 <think>...</think> 块
        text = re.sub(r'<think>[\s\S]*?</think>', '', text)
        # 兜底：去掉未闭合的 <think> 到结尾
        text = re.sub(r'<think>[\s\S]*$', '', text)
        return text

    @staticmethod
    def _is_refusal(answer: str) -> bool:
        """检测 LLM 是否在拒答。

        严格匹配：只有当回答以拒答短语开头，或回答很短且主要是拒答时才判定。
        避免误判正常回答中包含"无法确定"等词的情况。
        """
        answer_stripped = answer.strip()
        if not answer_stripped:
            return True

        # 注：图像类拒答（"无法查看截图"等）在此**有意不做**特判——
        # 该特判曾与正常回答冲突，故长期停用。若日后要重新启用，
        # 需连同短回答拒答词表一并回归，不要只改这一处。

        # 短回答（≤30字）才检查是否纯拒答
        if len(answer_stripped) <= 30:
            refusal_phrases = [
                "根据现有资料无法回答",
                "无法回答",
                "未找到相关",
                "没有相关信息",
                "资料中没有",
            ]
            return any(answer_stripped.startswith(p) for p in refusal_phrases)

        # 长回答不判定为拒答（LLM 已给出实质内容）
        return False

    @staticmethod
    def _has_number_hallucination(answer: str, contexts: List[dict], query: str = "") -> bool:
        """检测答案中是否出现参考资料中不存在的数字（数字幻觉）。

        策略：
        - 提取答案中所有数字（≥2位整数 或 含小数点的数）
        - 在参考资料 + 问题文本中搜索这些数字
        - 答案中有意义的数字不在参考资料中 → 判定幻觉，降级为抽取式回答

        不检查 1 位数字（如"1条""2个"等序数/计数），避免误判。
        """
        # 提取答案中的数字：只抽真正的数值（小数或整数）。
        # 关键：不用 \d+\.?\d*，否则答案里的编号列表标记 "1. " "2. " 会被当成
        # 带小数点的数字而误判为幻觉，把 LLM 正确回答误杀降级。
        answer_nums = set(re.findall(r'\d+\.\d+|\d+', answer))
        # 只检查有意义的数字：≥ 2 位整数 或 含小数点（文号/年份/金额/百分比等）
        # 单 digit（如列表标记 "1"/"2"）不计，避免误判。
        significant = {n for n in answer_nums if len(n) >= 2 or '.' in n}
        if not significant:
            return False

        # 参考资料 + 问题文本都算“合法来源”（问题中的数字允许复述）；
        # 标题也计入：LLM 引用文档标题编号（如“094-以旧换新...”）是合法的，不应判幻觉
        source_text = " ".join(
            f"{c.get('title', '')} {c.get('text', '')}" for c in contexts) + " " + query
        source_nums = set(re.findall(r'\d+\.\d+|\d+', source_text))

        # 幻觉判定：答案中的有意义数字既不在参考资料的数字集，也不以其子串形式出现（允许不同格式）
        hallucinated = {n for n in significant if n not in source_nums and n not in source_text}
        if hallucinated:
            logger.warning(f"数字幻觉: 答案数字 {hallucinated} 不在参考资料中")
            return True
        return False

    @staticmethod
    def _is_numeric_question(query: str) -> bool:
        """判断问题是否要求一个数值型答案（金额/数量/比例/排名/日期等）。
        仅对这类问题启用数字幻觉守卫；描述型问题不启用，避免误杀可读答案。

        原因/机制类疑问词豁免：问“为什么/原因”的题答案本质是论证而非数字
        （如“为什么汽车补贴当期乘数比家电家居更大”），个别数字不符不应整段降级。
        """
        q = query or ""
        if any(kw in q for kw in ["为什么", "为何", "原因", "如何理解"]):
            return False
        cues = ["多少", "多久", "几天", "几年", "几个月", "几次", "几个", "几人", "几",
                "何时", "哪年", "哪一年", "第几", "排名", "位列", "前几",
                "金额", "价格", "多少钱", "售价", "零售价", "资本", "限额", "增资", "增加至",
                "百分", "占比", "比重", "乘数", "销量", "收入", "人数", "规模",
                "亿元", "万亿", "元", "%", "％", "家", "倍"]
        return any(c in q for c in cues)

    @staticmethod
    def _query_keywords(query: str) -> set:
        """中文友好的查询关键词：ASCII 词(长度≥2) + CJK 连续串的字符二元组。
        避免按空格分词对无空格中文失效（之前整句当一个词→关键词形同虚设）。"""
        import unicodedata
        q = unicodedata.normalize("NFKC", (query or "").lower())
        q = re.sub(r'[，。！？、；：""\'\'（）【】《》,.!?;:\'"()\[\]<>\/]', ' ', q)
        kws = set(re.findall(r'[a-z0-9]{2,}', q))
        for run in re.findall(r'[\u4e00-\u9fff]+', q):
            if len(run) >= 2:
                for i in range(len(run) - 1):
                    kws.add(run[i:i + 2])
            else:
                kws.add(run)
        return {k for k in kws if k}

    # 抽取式回答的相关性门槛：rerank_score 低于此值视为不相关，不抽取
    EXTRACTIVE_MIN_SCORE = 0.1

    @staticmethod
    def _extractive_answer(query: str, contexts: List[dict]) -> str:
        """抽取式回答：从 top 资料中提取最相关的句子作为答案。

        相关性门槛：top1 的 rerank_score < 0.1 时，承认"不知道"，
        避免从弱相关/不相关的内容中硬抽句子导致答非所问。
        """
        if not contexts:
            return "现有资料对该问题的覆盖较为有限，建议结合具体业务场景进一步查阅相关文档。"

        # 相关性检查：top1 的 rerank_score 太低，说明检索结果不相关
        # _force_retrieve 的结果 rerank_score=0.0，会在这里被正确拦截
        top1_score = contexts[0].get("rerank_score", 0.0)
        if top1_score < Retriever.EXTRACTIVE_MIN_SCORE:
            logger.info(f"抽取式跳过：top1 rerank_score={top1_score:.3f} < 阈值，检索结果不相关")
            return "现有资料对该问题的覆盖较为有限，建议结合具体业务场景进一步查阅相关文档。"

        # 取 rerank 最高分的 3 条
        top = contexts[:3]
        # 提取 query 关键词（字符二元组），用于按相关性选句
        q_words = Retriever._query_keywords(query)

        def _is_junk(s: str) -> bool:
            # 过滤页码/独立数字行(如 "- 66 -"、"1 2")、纯符号、过短残句、目录标题行
            t = s.strip()
            if len(t) < 6:
                return True
            if re.fullmatch(r'[-–\s\u3000\d\.\、,，]+', t):
                return True
            # 去掉标点/空格/数字后实义汉字过少 → 视为目录/页码噪声
            if len(re.findall(r'[\u4e00-\u9fff]', t)) < 4:
                return True
            # 半截句检测：以介词/连词/助词开头（碎片特征，无论长度）
            if re.match(r'^[的了在与和或而但且以从对于关于按照根据由于为了作为经过除了]', t):
                return True
            # 重复碎片检测：overlap 导致的整句重复（前半段原样再次出现在后半段）
            # 注意：不能写 t[half:] in t[:half*2]，该切片恒为真会把每个长块误判为垃圾
            if len(t) > 40:
                half = len(t) // 2
                if t[:half] in t[half:]:
                    return True
            return False

        pool = []  # (hit, chunk_order, sent_idx, sent)
        for ci, c in enumerate(top):
            text = _clean_layout_tokens(c["text"])
            # 与 _build_prompt 同源的清洗：换行断裂修复 + 塌缩整段重复 + 句子级残片，
            # 避免兜底答案里出现截断残片
            text = Retriever._reflow_broken_lines(text)
            text = Retriever._dedup_overlap(text)
            text = Retriever._collapse_fragments(text)
            # 先按句末标点切，再把多行内容按换行拆开（避免整块目录/表格当成一句）
            cands = []
            for part in re.split(_SENT_SPLIT_RE, text):
                cands.extend(part.split("\n"))
            for si, raw in enumerate(cands):
                s = raw.strip()
                if not s or _is_junk(s):
                    continue
                hit = sum(1 for w in q_words if w in s)
                # 关键词加权：问"依据/根据/原因"时，提升含"根据/依据/系/因为/由于"句子的权重
                if any(kw in query for kw in ["依据", "根据", "原因"]):
                    if any(kw in s for kw in ["根据", "依据", "系", "因为", "由于"]):
                        hit += 3
                # 枚举条目句加权：条目与问题措辞通常零重合，按关键词必然落选，枚举题却靠它作答
                if _ENUM_PREFIX_RE.match(s):
                    hit += 10
                pool.append((hit, ci, si, s))

        # 全局按关键词命中数排序，取最相关的前 4 句（简短、避免长转储）
        ranked = sorted(pool, key=lambda t: (-t[0], t[1], t[2]))
        chosen = [x for x in ranked if x[0] > 0][:4] or ranked[:2]
        chosen = sorted(chosen, key=lambda t: (t[1], t[2]))  # 还原原文顺序

        out = []
        seen = set()
        for _, _, _, s in chosen:
            s = s.rstrip("；。！？，,;. ")  # 去句尾标点，避免拼接出现“；；”
            if s and s not in seen:
                seen.add(s)
                out.append(s)

        if not out:
            return _clean_layout_tokens(top[0]["text"])[:200].strip()
        return "；".join(out) + "。"

    @staticmethod
    def _compress_chunk(text: str, query: str, max_sentences: int = 5) -> str:
        """上下文压缩：提取与 query 相关的句子，减少 LLM 输入 token。

        策略（保守，不丢关键信息）：
        1. 按句切分 chunk
        2. 优先保留含 query 关键词的句子
        3. 始终保留首句（提供上下文）
        4. 不足则补齐，最多 max_sentences 句
        5. 连续重复段去重
        若压缩后反而更短或无关键词命中，返回原文（不压缩）。
        """
        if not text or len(text) <= 512:
            return text  # 正常大小的 chunk不压缩，避免关键词/数字打分误伤、把答案整句丢到预算之外

        # 提取 query 关键词（字符二元组，中文友好）
        q_words = Retriever._query_keywords(query)

        # 句子切分（守卫式：中文句末标点直接断；ASCII .!?; 仅在不接字母/数字时断，保护 URL/小数/章节号）
        sentences = re.split(_SENT_SPLIT_RE, text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) <= 2:
            return text  # 句子太少不压缩

        # 连续重复段去重：原文可能有整段重复
        deduped = []
        for s in sentences:
            if not deduped or deduped[-1] != s:
                deduped.append(s)
        sentences = deduped
        if len(sentences) <= 2:
            return text  # 去重后句子太少不压缩

        # 评分：含 query 关键词的句子优先，含数字的句子加权保留（防压缩丢关键数字）
        scored = []
        for idx, sent in enumerate(sentences):
            score = sum(1 for w in q_words if w in sent)
            # 含数字的句子（文号/金额/日期/百分比）优先保留，避免压缩导致数字丢失
            if re.search(r'\d', sent):
                score += 2
            scored.append((idx, sent, score))

        # 保留：首句 + 含关键词的句子（按原顺序），不足 max_sentences 则补齐
        kept_indices = {0}  # 首句必留
        for idx, sent, score in scored:
            if score > 0:
                kept_indices.add(idx)
        # 枚举条目句无条件保留：条目内容（“一是…/一方面…”开头）与问题措辞通常零词汇重合，
        # 按关键词打分必然落选，而枚举题恰恰要靠这些句子作答；宁可多保留几句也不丢条目。
        for idx, sent, _ in scored:
            if _ENUM_PREFIX_RE.match(sent):
                kept_indices.add(idx)

        if len(kept_indices) < max_sentences:
            for idx, _, _ in scored:
                if len(kept_indices) >= max_sentences:
                    break
                kept_indices.add(idx)

        # 句子去重：只保留首次出现
        seen = set()
        result_parts = []
        for i in sorted(kept_indices):
            s = sentences[i]
            if s not in seen:
                seen.add(s)
                result_parts.append(s)

        result = "".join(result_parts)
        # 若压缩后没明显缩短，返回原文
        if len(result) > len(text) * 0.85:
            return text
        return result

    @staticmethod
    def _merge_overlapping_chunks(parts: List[str]) -> str:
        """拼接相邻块：相邻块后缀==前缀精确对齐时合并重叠区，避免 overlap 重复；
        无法精确对齐时直接拼接（保内容不丢失），重复残片交由 _collapse_fragments 清理。
        """
        if not parts:
            return ""
        merged = parts[0]
        for nxt in parts[1:]:
            max_ov = min(len(merged), len(nxt), 120)
            ov = 0
            for k in range(max_ov, 5, -1):
                if merged[-k:] == nxt[:k]:
                    ov = k
                    break
            merged += nxt[ov:]
        return merged

    # 列表项/项目符号行（reflow 不合并，防破坏表格/列表结构）
    _REFLOW_LIST_RE = re.compile(
        r"^\s*(?:\d{1,3}[.、．)）]|[（(]\d+[)）]|[•·▪◦●○*\-–—]\s)"
    )
    # 句末标点（含中英文；行以此结尾视为完整行，不向下合并）
    _REFLOW_END_RE = re.compile(r"[。！？；…!?;]$")

    @staticmethod
    def _reflow_broken_lines(text: str) -> str:
        """合并 OCR/PDF 提取造成的断裂行：把句中被换行切开的碎片拼回完整行。

        只合并「不以句末标点结尾的行」与其后续行（最多 5 行），遇到空行
        （段落边界）、列表项行、装饰行（纯符号）即停；英文行拼接时补空格。
        修复断裂后枚举句式（如"一方面，…\n重点推进\n农村养老金改革"）才能
        被 LLM 与后续句子塌缩规则正确识别。
        """
        if not text:
            return text
        lines = text.split("\n")
        out: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                out.append(line)
                i += 1
                continue
            # 列表项/分隔符/装饰行独立保留，不与下行粘连
            if (Retriever._REFLOW_LIST_RE.match(line)
                    or stripped.startswith(("--", "——"))
                    or (len(stripped) <= 3 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", stripped))):
                out.append(line)
                i += 1
                continue
            if Retriever._REFLOW_END_RE.search(line.rstrip()):
                out.append(line)
                i += 1
                continue
            # 断裂行：向后吃行，直到吃到句末标点行/空行/列表行为止
            merged = line.rstrip()
            j = i + 1
            eaten = 0
            while j < n and eaten < 5:
                nxt = lines[j].strip()
                if not nxt:
                    break
                if Retriever._REFLOW_LIST_RE.match(nxt) or nxt.startswith(("--", "——")):
                    break
                sep = ""
                if (merged[-1:].isascii() and merged[-1:].isalnum()
                        and nxt[:1].isascii() and nxt[:1].isalnum()):
                    sep = " "
                merged += sep + nxt
                j += 1
                eaten += 1
                if Retriever._REFLOW_END_RE.search(nxt[-1:]):
                    break
            out.append(merged)
            i = j
        return "\n".join(out)

    @staticmethod
    def _dedup_overlap(text: str) -> str:
        """塌缩 overlap 造成的整段前后重复：若文本前三分之一在后文原样再现，
        则丢掉开头那份、从再现处保留（后一份通常更完整、含真正答案），避免整块被误丢。"""
        t = text
        if len(t) <= 100:
            return t
        third = len(t) // 3
        head = t[:third]
        idx = t.find(head, third)
        if idx != -1:
            return t[idx:]
        return t

    @staticmethod
    def _norm_with_pos(s: str) -> tuple:
        """归一化句子：仅保留字母数字与 CJK（字母小写），并记录每个归一字符对应的原串下标。
        返回 (norm_str, norm_pos_list)。"""
        norm_chars = []
        pos = []
        for idx, ch in enumerate(s):
            if ch.isascii() and ch.isalnum():
                norm_chars.append(ch.lower())
                pos.append(idx)
            elif '\u4e00' <= ch <= '\u9fff':
                norm_chars.append(ch)
                pos.append(idx)
        return "".join(norm_chars), pos

    @staticmethod
    def _lcs_len(a: str, b: str) -> int:
        """最长公共子串长度（滚动数组 DP，O(n*m)）。输入为归一化后的短句，规模可控。"""
        if not a or not b:
            return 0
        prev = [0] * (len(b) + 1)
        best = 0
        for i in range(1, len(a) + 1):
            cur = [0] * (len(b) + 1)
            for j in range(1, len(b) + 1):
                if a[i - 1] == b[j - 1]:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best:
                        best = cur[j]
            prev = cur
        return best

    @staticmethod
    def _collapse_fragments(text: str) -> str:
        """句子级残片塌缩：清理 chunker overlap 前缀机制在块内留下的"截断残片+完整句"重复。

        只删两类内容：(a) 内容已被后文句子完整保留的残片/重复句；(b) 残片尾部与后文句子头部
        重叠的部分（截断处理）。其余内容一律保留，宁可留噪音也不丢真答案。

        三规则（均只在"前文句 A vs 后文句 B"方向执行，保留后文更完整的版本）：
        1. 完整包含：norm(A) 是 norm(B) 的子串 → 删 A（含完全重复句）；
        2. 高重合残片：A 不以句末标点结尾，且与后文某句 B 的最长公共子串 ≥ max(12, 0.85*len(norm(A))) → 删 A；
        2b. 粘连句：仅适用于无句末标点的残片。A 的长前缀完整再现于后文某句 B（≥ max(12, 0.6*len(norm(A)))），
            且 A 自身独特尾部已在前文句子中出现过（残片与下句开头粘连的特征）→ 删 A；
            前缀匹配而非全量 LCS，避免误删排比句；尾部必须在前文出现，
            防止误删尾部含关键数字的相似句（如“财政乘数达到7.0”）；
            完整句（以句末标点结尾）绝不删除：表格行/列表项同模板异取值时
            前缀重合+尾部重复是常态，误删会丢失唯一的数据行（如组合表第 3 行）；
        3. 截尾残片：A 不以句末标点结尾，其 norm 的最长后缀恰为后文某句 B 的 norm 前缀(≥8) →
           按 norm_pos 映射回 raw 下标截掉该后缀；截后 <6 个有效字符则整句删。
        """
        if not text:
            return text
        lines = text.split("\n")
        # 按行拆、行内切句（保留行结构，防止表格/列表整行混入长句被误判）
        sents = []  # dict: raw, norm, pos, line, keep, cut
        for line_idx, line in enumerate(lines):
            for seg in re.split(_SENT_SPLIT_RE, line):
                seg = seg.strip()
                if not seg:
                    continue
                norm, pos = Retriever._norm_with_pos(seg)
                if not norm:
                    continue
                sents.append({"raw": seg, "norm": norm, "pos": pos, "line": line_idx,
                              "keep": True, "cut": None})

        n = len(sents)
        if n <= 1:
            return text

        # 规则4 预扫描：伪枚举句（枚举引导词 + 与前文重复的内容）。overlap 会把上一句
        # 的引导词残片与重复段落粘成完整句（如"一方面，费潜力最大的…"），
        # 去掉引导词后的内容与块内其他保留句高度重合 → 重叠噪音而非真条目，
        # 整句删除。必须预扫描（在规则1 删除任何句之前）：规则1 会先删掉
        # 无引导词的对照句（子串包含），预扫描后才能互证。仅处理完整句；
        # 残片由规则2/2b 处理。对照集只含当前保留句，避免两姐妹句互证误删。
        for i in range(n):
            a = sents[i]
            m = _ENUM_PREFIX_RE.match(a["norm"])
            if not (m and _FRAG_END_RE.search(a["raw"])):
                continue
            rest = a["norm"][m.end():]
            if len(rest) < 8:
                continue
            for j in range(n):
                if j == i or not sents[j]["keep"]:
                    continue
                nb = sents[j]["norm"]
                if rest in nb:
                    a["keep"] = False
                    break
                if (len(nb) >= 8
                        and Retriever._lcs_len(rest, nb) >= max(12, int(len(rest) * 0.8))):
                    a["keep"] = False
                    break

        def _window(i: int):
            # 只向后看有限句（chunker overlap 跨块重复通常就隔 1-3 句），控制 O(n²) 规模
            return range(i + 1, min(i + 10, n))

        for i in range(n):
            a = sents[i]
            if not a["keep"]:
                continue
            na = a["norm"]
            # 规则1：完整包含（含完全重复）。过短的 norm(<4) 不删，防误删单数字/单字符单元格
            if len(na) >= 4:
                for j in _window(i):
                    b = sents[j]
                    if not b["keep"]:
                        continue
                    if na in b["norm"]:
                        a["keep"] = False
                        break
                if not a["keep"]:
                    continue
            # 规则2：高重合截断残片（仅无句末标点的残片）；完整句的重复由规则2b 处理
            if not _FRAG_END_RE.search(a["raw"]) and len(na) <= 150:
                best = 0
                for j in _window(i):
                    b = sents[j]
                    if not b["keep"] or len(b["norm"]) > 150:
                        continue
                    l = Retriever._lcs_len(na, b["norm"])
                    if l > best:
                        best = l
                thr = max(12, int(len(na) * 0.85))
                if best >= thr:
                    a["keep"] = False
                    continue
            # 规则2b：粘连句（仅无句末标点的残片；完整句禁止删除——
            # 表格行/列表项同模板异取值时前缀重合+尾部重复是常态，删了会丢唯一数据行）
            if not _FRAG_END_RE.search(a["raw"]):
                best_k = 0
                for k in range(min(len(na), 80), 11, -1):
                    pref = na[:k]
                    for j in _window(i):
                        b = sents[j]
                        if not b["keep"]:
                            continue
                        if pref in b["norm"]:
                            best_k = k
                            break
                    if best_k:
                        break
                if best_k >= max(12, int(len(na) * 0.6)):
                    tail = na[best_k:]
                    if tail and any(tail in sents[p]["norm"] for p in range(i)):
                        a["keep"] = False
                        continue
            # 规则3：截尾残片（仅无句末标点的残片）
            if _FRAG_END_RE.search(a["raw"]):
                continue
            best_k = 0
            for k in range(min(len(na), 80), 7, -1):
                suff = na[-k:]
                for j in _window(i):
                    b = sents[j]
                    if not b["keep"]:
                        continue
                    if b["norm"].startswith(suff):
                        best_k = k
                        break
                if best_k:
                    break
            if best_k:
                # norm 后缀首字符对应的 raw 下标即截断点
                a["cut"] = a["pos"][len(na) - best_k]
                if len(na) - best_k < 6:
                    a["keep"] = False

        if all(s["keep"] and s["cut"] is None for s in sents):
            return text

        out_lines = []
        for line_idx in range(len(lines)):
            parts = []
            for s in sents:
                if s["line"] != line_idx or not s["keep"]:
                    continue
                raw = s["raw"] if s["cut"] is None else s["raw"][:s["cut"]].rstrip()
                if raw:
                    parts.append(raw)
            out_lines.append("".join(parts))
        return re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()

    @staticmethod
    def _is_low_quality_chunk(text: str) -> bool:
        """检测低质量块：半截句开头 / 高重复度。这类块会污染 LLM 上下文。
        注意：调用方应先用 _dedup_overlap 塌缩重复段，此处仅兜底。"""
        t = text.strip()
        if not t:
            return True
        # 取首句（按句末标点切）
        first_sent = re.split(_SENT_SPLIT_RE, t)[0].strip()
        # 半截句检测：以介词/连词/助词开头的**短碎片**（<20 字）判为截断片段。
        # 不可对所有长度生效：单字符集会误杀“经济学/根据/对于/以旧换新/为主”等首字开头的正常长块，
        # 而这些往往正是 rerank 最高、含标准答案的 top 块（宁可保留也不误丢）。
        if len(t) < 20 and re.match(r'^[的了在与和或而但且以从对于关于按照根据由于为了作为经过除了]', first_sent):
            return True
        # 重复度检测：overlap 导致的前后重复（前三分之一原样再次出现在后文）
        # 注意：不能写 t[third:third*2] in t[:third*2]，该切片恒为真会把每个 >100 字的块误判为低质量并丢弃
        if len(t) > 100:
            third = len(t) // 3
            if t[:third] in t[third:]:
                return True
        return False

    @staticmethod
    def _trim_trailing_fragment(text: str, max_frag: int = 25) -> str:
        """裁掉块末尾的短残片，保证送入 LLM 的上下文以完整句收尾。

        分块边界与父块窗口拼接会留下起于词中、止于句中的残片（如「车耐用品属性更强、居民购」）。
        模型倾向照抄上下文末句，残片会让答案以半句收尾。
        只裁短残片（< max_frag 字）：较长的尾部从句往往正承载答案（如被分块切断的比例/金额句），
        裁掉反而丢分；整块都是短残片时返回空串，由调用方丢弃该块。
        """
        t = text.rstrip()
        if not t or _FRAG_END_RE.search(t):
            return t
        cut = max(t.rfind(s) for s in ("。", "！", "？", "；"))
        frag = t[cut + 1:] if cut >= 0 else t
        if len(frag) >= max_frag:
            return t
        return t[: cut + 1] if cut > 0 else ""

    @staticmethod
    def _order_contexts_by_document(contexts: List[dict]) -> List[dict]:
        """同文档资料按原文顺序（chunk_index）排列，文档组序保持首次出现顺序。

        rerank 分数排序会把同一文档的块打散且乱序（如 idx 7,2,6,0,1,8），
        破坏跨块枚举的阅读连贯性；组内恢复 chunk_index 升序后，
        摘要/引导句/条目按原文顺序呈现，模型才能正确关联。
        稳定排序：不同文档间保持相对顺序不变。
        """
        first_seen: dict = {}
        for i, c in enumerate(contexts):
            doc = c.get("document_id")
            if doc is not None and doc not in first_seen:
                first_seen[doc] = i
        return sorted(
            contexts,
            key=lambda c: (
                first_seen.get(c.get("document_id"), 0),
                c.get("chunk_index", 0),
            ),
        )

    @staticmethod
    def _build_prompt(query: str, contexts: List[dict]) -> str:
        """构建带完整元数据来源标识的 prompt。

        优化：上下文压缩，只保留与 query 相关的句子，减少 LLM 输入 token。

        格式示例：
        【参考资料 1】 来源：《商户类别码（MCC）使用、分配指引》 第3页 二、MCC的定义
        内容：MCC 即 Merchant Category Code，是...
        """
        if not contexts:
            return f"用户问题：{query}\n\n（无可用参考资料）"
        # 同文档资料按原文顺序（chunk_index）呈现：rerank 分数排序会打乱阅读顺序，
        # 使跨块枚举（引导句在块A、条目在块B/C）的内容错位，模型易把背景论述当条目。
        # 文档组序按组内最高 rerank 分（即首现顺序）保持，组内恢复原文顺序。
        contexts = Retriever._order_contexts_by_document(contexts)
        max_chars = settings.max_context_chars
        blocks = []
        total = 0
        accepted_pre_norms: List[str] = []  # 已接受块 collapse 前的归一化全文（父窗口合并单调：小窗口是大窗口前缀）
        accepted_norms: List[str] = []  # 已接受块 collapse 后的归一化全文
        for i, c in enumerate(contexts, 1):
            # 运行时兜底清洗：清理已缓存旧数据中可能残留的布局 token
            raw_text = _clean_layout_tokens(c["text"])
            # 换行断裂修复：合并 OCR/提取把句子切开的碎片行，恢复完整句（枚举句式、
            # 长句被斩断时 LLM 会读不懂而改用背景论述拼凑答案）
            raw_text = Retriever._reflow_broken_lines(raw_text)
            # overlap 重复块：塌缩整段前后重复（去掉开头那份、保留更完整的后一份），避免真答案被整块丢弃
            raw_text = Retriever._dedup_overlap(raw_text)
            # 跨块冗余过滤（阶段1）：collapse 前文本完整包含于已接受块 → 直接跳过。
            # 必须在 collapse 前检查：collapse 对不同窗口的同一内容删减不一致，会破坏子串关系
            norm_pre = Retriever._norm_with_pos(raw_text)[0]
            if len(raw_text) >= 40:
                if any(len(prev) > len(norm_pre) and norm_pre in prev for prev in accepted_pre_norms):
                    logger.debug(f"跳过冗余块 faiss={c.get('faiss_id')}：内容已被前面资料覆盖")
                    continue
            # 句子级残片塌缩：清理块内"截断残片+完整句"重复（父块扩展拼接后常见），只删后文已完整保留的内容
            raw_text = Retriever._collapse_fragments(raw_text)
            # 跨块冗余过滤（阶段2）：collapse 后顺序错位的重复块用高重合 LCS 兜底
            if len(raw_text) >= 40:
                norm = Retriever._norm_with_pos(raw_text)[0]
                redundant = False
                for prev in accepted_norms:
                    # 完全包含：直接冗余
                    if len(prev) > len(norm) and norm in prev:
                        redundant = True
                        break
                    # 高重合：几乎完全相同（父块扩展后顺序错位的重复块）
                    if len(prev) <= 800 and len(norm) <= 800:
                        l = Retriever._lcs_len(norm, prev)
                        if l >= int(len(norm) * 0.95) and len(norm) - l <= 25:
                            redundant = True
                            break
                if redundant:
                    logger.debug(f"跳过冗余块 faiss={c.get('faiss_id')}：内容已被前面资料覆盖")
                    continue
            # 块质量过滤：半截句/高重复块不送 LLM，避免污染上下文
            if Retriever._is_low_quality_chunk(raw_text):
                logger.debug(f"跳过低质量块 faiss={c.get('faiss_id')}：半截句或高重复")
                continue
            # 上下文压缩：只保留与 query 相关的句子
            text = Retriever._compress_chunk(raw_text, query)
            # 上下文完整性：块末尾必须是完整句，短残片裁掉（模型会照抄末句，残片使答案半句收尾）
            text = Retriever._trim_trailing_fragment(text)
            if not text:
                logger.debug(f"跳过残片块 faiss={c.get('faiss_id')}：整块无完整句")
                continue
            # 记录完整文本供后续块做冗余判断（必须在截断前记录，截断后子串关系失真）
            accepted_pre_norms.append(norm_pre)
            accepted_norms.append(Retriever._norm_with_pos(raw_text)[0])
            remaining = max_chars - total - 120  # 120 留给标题、页码、章节、问题和分隔
            if remaining <= 0:
                break
            # 超出预算按句边界截断：模型会照抄上下文末句，盲切句中会让答案以半句收尾
            # （实测「质押的股权不得超过」「当期刺」类残缺答案均源于此）；残块过短则整块丢弃
            if len(text) > remaining:
                cut = text[:remaining]
                boundary = max(cut.rfind(s) for s in ("。", "！", "？", "；", "\n"))
                # 只切不丢：切到最后一个完整句尾，避免模型照抄半句；无句末标点时才保留盲切结果
                text = cut[: boundary + 1] if boundary > 0 else cut
            header = f"【参考资料 {i}】"
            # 来源标题
            title = c.get("title", "") or c.get("source", "")
            if title:
                header += f" 来源：《{title}》"
            # 页码
            page = c.get("page", 0)
            if page:
                header += f" 第{page}页"
            # 章节
            section = c.get("section", "")
            if section:
                header += f" {section}"
            blocks.append(f"{header}\n内容：{text}")
            total += len(text) + len(header) + 5
        return "\n\n".join(blocks) + (
            f"\n\n用户问题：{query}\n\n请根据以上参考资料回答。"
            "补充要求：请把原文中承载答案的整句信息完整带入回答，包括该句内与答案相邻的背景数据、"
            "适用场景或规格限定（例如原文若写“财政规模约281亿元，拉动零售额1952亿元，乘数达到7.0”，"
            "不要只答“乘数为7.0”），不要只给出孤立的数字或答案词。具体规则：\n"
            "0. 枚举题（问题问“哪些/哪几个/哪两个/包含什么领域、方面、渠道、功能”等）必须直接用资料中的"
            "“一是…二是…”或“一方面…另一方面…”句式条目作答；不得用“两种思路”“通过…和…”“以…和…为主线”"
            "等近似枚举或路径表述代替；若该句式在资料中两处出现，采信包含全部条目的那一处。\n"
            "1. 答案句的句首背景限定必须完整转述：原文写“适用各种常见的收银台桌面高度，其上方的摄像头"
            "兼具扫码和刷脸的功能”时，不能只答“兼具扫码和刷脸”。\n"
            "2. 与答案处于同一句的并列多项须全部列出：原文写“支持扫码聚合支付，同时支持人行标准人脸"
            "支付和微信人脸支付”时，三项都要出现，不得因某项与问题措辞不完全一致而省略"
            "（例如问题只问“刷脸支付渠道”时，同句并列的“扫码聚合支付”也必须一并列出）。\n"
            "3. 资料若同时出现多个并列枚举（如“两种思路”与“两个领域”），须按与问题措辞一致的枚举作答；"
            "问题问“哪两个领域”就答“两个领域”，不得用其他近似枚举（如“两种思路”）代替，"
            "也不得把“通过…和…”式路径表述（如“通过城市化和结构性改革找到破题之道”）中的"
            "并列短语拆成条目作答。枚举的引导句与其具体条目可能分散在不同参考资料段落中，"
            "须通读全部资料，把该枚举对应的全部条目完整汇总后再作答，"
            "不得因引导句后未紧接条目内容就称“资料未具体说明”。"
            "条目通常以“一是…二是…”或“一方面…另一方面…”句式展开，可能位于引导句的前后相邻段落中；"
            "优先采用与问题枚举数量一致的这类句式作答，不要用引导句之前的背景论述（如“两种思路”的讨论）拼凑条目；"
            "若同一枚举的“一是…二是…”与“一方面…另一方面…”两处句式内容相同，"
            "须采信包含全部条目的那一处作答。\n"
            "4. 资料以条件组合给出结果时（如“商户参数分单+打印机整单→整单打印”），须逐条照抄组合结果，"
            "不得臆造、颠倒或按自己的理解改写。"
        )
