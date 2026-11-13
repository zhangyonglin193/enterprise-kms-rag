"""权限隔离的定向推荐 —— 组织画像 / 语义相似 / 协同过滤 / 热度 四路融合。

设计要点
--------
1. 可插拔策略：每路策略实现 Strategy 接口，各自产出 {doc_id: 原始分}；
   归一化后按 config 中的权重加权融合，冷启动由热度策略兜底。
2. 权限硬过滤：融合后的候选在落库校验阶段逐条通过 gateway.service.allowed()，
   未授权（密级/部门/组织层级/生命周期/过期）文档一律剔除，杜绝越权推荐。
3. 行为埋点：问答命中的来源（chat_source）、文档浏览（view）、用户反馈（feedback）
   写入 kms_rec_interactions；feedback 通过 message_id 回溯问答来源文档。
4. 全链路容错：任一策略/查询失败仅降级跳过，绝不影响主业务返回。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.logger import get_logger
from app.store import MySQLStore
from config import settings
from gateway import service
from kms.constants import DOC_DEPT_UNLIMITED, normalize_department
from kms.security import AuthUser, client_ip, require_user

logger = get_logger("kms.recommend")

router = APIRouter(prefix="/kms/api", tags=["recommendation"])


def _user_in_doc_departments(row: dict, emp_dept: str) -> bool:
    """判断用户部门是否命中文档归属部门（优先 departments，回退旧字段）。

    「不限部门」(`*`) 视为命中：该类文档本意就是全员可见，推荐场景
    应给同样的部门相关度权重，否则全员可见的文档反而凑不上部门加分。
    部门名归一化后再比较，容错 HR 台账里的空格。
    """
    if not emp_dept:
        return False
    norm_emp = normalize_department(emp_dept)
    departments = row.get("departments")
    if departments:
        if isinstance(departments, str):
            try:
                departments = json.loads(departments)
            except (TypeError, ValueError):
                departments = []
        if isinstance(departments, list) and departments:
            return any(d == DOC_DEPT_UNLIMITED
                       or normalize_department(d) == norm_emp
                       for d in departments if d)
    old_dept = row.get("owner_department") or ""
    if old_dept and (old_dept == DOC_DEPT_UNLIMITED
                     or normalize_department(old_dept) == norm_emp):
        return True
    old_extra = row.get("extra_departments") or []
    if isinstance(old_extra, str):
        try:
            old_extra = json.loads(old_extra)
        except (TypeError, ValueError):
            old_extra = []
    if isinstance(old_extra, list) and emp_dept in old_extra:
        return True
    return False

# ===== 交互权重 =====
WEIGHT_CHAT_SOURCE = 1.0    # 问答命中来源（强正反馈）
WEIGHT_VIEW = 0.5           # 文档浏览（弱正反馈）
WEIGHT_FEEDBACK_UP = 2.0    # 用户点赞
WEIGHT_FEEDBACK_DOWN = -2.0  # 用户点踩


# ===================== DDL =====================
REC_DDL = """CREATE TABLE IF NOT EXISTS kms_rec_interactions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '员工ID',
    employee_no VARCHAR(64) NULL COMMENT '工号（冗余便于审计）',
    doc_id BIGINT NULL COMMENT '关联文档ID',
    message_id VARCHAR(64) NULL COMMENT '问答回执ID（支持反馈回溯来源）',
    kind VARCHAR(24) NOT NULL COMMENT 'chat_source/view/feedback',
    weight DECIMAL(6,2) NOT NULL DEFAULT 0 COMMENT '交互权重',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_u (user_id, created_at),
    INDEX idx_doc (doc_id),
    INDEX idx_msg (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推荐交互行为（隐式/显式反馈）';"""


def ensure_recommend_tables() -> bool:
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(REC_DDL)
        return True
    except Exception as e:
        logger.warning(f"推荐交互表初始化失败（降级为空推荐）: {e}")
        return False


# ===================== 行为埋点 =====================
def record_interaction(user: Optional[AuthUser], kind: str, doc_id: Optional[int] = None,
                       message_id: str = "", weight: float = 0.0) -> None:
    """写入一条交互行为；失败仅告警，不阻断主流程。"""
    if not user:
        return
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "INSERT INTO kms_rec_interactions (user_id, employee_no, doc_id, message_id, kind, weight) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (user.id, user.employee_no, doc_id, message_id[:64], kind, weight),
            )
    except Exception as e:
        logger.debug(f"交互埋点写入失败 kind={kind}: {e}")


def record_answer_sources(user: Optional[AuthUser], message_id: str, doc_ids: List[int],
                          kind: str = "chat_source", weight: float = WEIGHT_CHAT_SOURCE) -> None:
    """记录一次问答命中的来源文档（同一 message_id 关联多条记录）。"""
    if not user or not message_id:
        return
    for doc_id in dict.fromkeys(int(d) for d in doc_ids if d):
        record_interaction(user, kind, doc_id=doc_id, message_id=message_id, weight=weight)


def feedback_docs(message_id: str) -> List[int]:
    """按问答回执 ID 回溯其命中的来源文档（用于反馈加权）。"""
    if not message_id:
        return []
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "SELECT DISTINCT doc_id FROM kms_rec_interactions "
                "WHERE message_id=%s AND kind='chat_source' AND doc_id IS NOT NULL",
                (message_id,),
            )
            return [int(r["doc_id"]) for r in cur.fetchall()]
    except Exception as e:
        logger.debug(f"回溯问答来源失败: {e}")
        return []


def apply_feedback(user: Optional[AuthUser], message_id: str, rating: str) -> int:
    """将用户反馈折算为来源文档的显式权重写入；返回关联文档数。"""
    docs = feedback_docs(message_id)
    weight = WEIGHT_FEEDBACK_UP if rating == "up" else WEIGHT_FEEDBACK_DOWN
    for doc_id in docs:
        record_interaction(user, "feedback", doc_id=doc_id, message_id=message_id, weight=weight)
    return len(docs)


# ===================== 推荐结果 =====================
@dataclass
class Recommendation:
    doc_id: int
    title: str
    file_type: str
    classification: int
    score: float
    reasons: List[str] = field(default_factory=list)
    strategies: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "file_type": self.file_type,
            "classification": self.classification,
            "score": self.score,
            "reasons": self.reasons,
            "strategies": self.strategies,
        }


# ===================== 公共查询 =====================
def _published_pool(limit: int = 300) -> List[dict]:
    """候选池：已发布、已批准、未过期的文档轻量元数据。"""
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT d.id AS document_id, d.title, d.departments, d.owner_department, d.extra_departments, d.owner_org_path, "
            "l.level AS classification FROM documents d JOIN kms_doc_levels l ON l.document_id=d.id "
            "WHERE d.status='published' AND d.lifecycle_state='published' AND d.publication_approved=1 "
            "AND (d.expires_at IS NULL OR d.expires_at>NOW()) ORDER BY d.id DESC LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def _load_rows(doc_ids: List[int]) -> List[dict]:
    """一次性加载候选文档的完整权限元数据（供 service.allowed 判定）。"""
    ids = [int(d) for d in doc_ids]
    if not ids:
        return []
    marks = ",".join(["%s"] * len(ids))
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT d.id AS document_id,d.title,d.file_type,d.departments,d.owner_department,d.extra_departments,"
            "d.owner_org_path,d.status,d.lifecycle_state,d.publication_approved,"
            "(d.expires_at IS NOT NULL AND d.expires_at<=NOW()) AS expired,"
            "l.level AS classification FROM documents d JOIN kms_doc_levels l ON l.document_id=d.id "
            "WHERE d.id IN (" + marks + ")",
            tuple(ids),
        )
        return cur.fetchall()


# ===================== 策略接口 =====================
class Strategy(ABC):
    """推荐策略标准接口：返回 {doc_id: 原始分}。"""

    name: str = "strategy"

    @abstractmethod
    def score(self, user: AuthUser, seed_text: str, seed_doc_id: Optional[int]) -> Dict[int, float]:
        ...


class OrgProfileStrategy(Strategy):
    """组织画像：优先推荐用户本部门 / 组织层级范围内的文档。"""

    name = "organization"

    def score(self, user: AuthUser, seed_text: str, seed_doc_id: Optional[int]) -> Dict[int, float]:
        if not user or not user.org_path:
            return {}
        result: Dict[int, float] = {}
        for row in _published_pool():
            owner_path = row.get("owner_org_path") or ""
            if owner_path == user.org_path or (owner_path and owner_path.startswith(user.org_path + "/")):
                result[int(row["document_id"])] = 1.0
            elif user.department and _resolve_departments(row, user.department):
                result[int(row["document_id"])] = 0.5
        return result


class SemanticStrategy(Strategy):
    """语义相似：以查询文本或种子文档为锚，向量检索取相似文档。"""

    name = "semantic"

    def score(self, user: AuthUser, seed_text: str, seed_doc_id: Optional[int]) -> Dict[int, float]:
        text = (seed_text or "").strip()
        if not text and seed_doc_id:
            text = self._seed_doc_text(int(seed_doc_id))
        if not text:
            return {}
        try:
            from kms.routes import get_retriever
            retriever = get_retriever()
            emb = retriever.embedder.embed_one(text)
            hits = retriever.vector_store.search(emb, max(settings.kms_rec_top_n * 3, 15))
            faiss_ids = [int(h["faiss_id"]) for h in hits]
            chunks = retriever.chunk_cache.get_by_faiss_ids(faiss_ids)
        except Exception as e:
            logger.debug(f"语义策略跳过: {e}")
            return {}

        result: Dict[int, float] = {}
        for chunk in chunks:
            doc_id = chunk.get("document_id")
            if not doc_id:
                continue
            result[int(doc_id)] = max(result.get(int(doc_id), 0.0), 1.0)
        return result

    @staticmethod
    def _seed_doc_text(doc_id: int) -> str:
        try:
            with MySQLStore()._conn() as cur:
                cur.execute("SELECT text FROM chunks WHERE document_id=%s ORDER BY chunk_index LIMIT 1", (doc_id,))
                row = cur.fetchone()
                return (row["text"] or "")[:300] if row else ""
        except Exception:
            return ""


class CollaborativeStrategy(Strategy):
    """协同过滤（item-item 共现）：与用户已交互文档共现的文档；冷启动降权为 0。"""

    name = "collaborative"

    def score(self, user: AuthUser, seed_text: str, seed_doc_id: Optional[int]) -> Dict[int, float]:
        if not user:
            return {}
        try:
            with MySQLStore()._conn() as cur:
                cur.execute("SELECT COUNT(DISTINCT doc_id) AS c FROM kms_rec_interactions "
                            "WHERE user_id=%s AND doc_id IS NOT NULL", (user.id,))
                if int(cur.fetchone()["c"]) < settings.kms_rec_collab_min:
                    return {}  # 冷启动：交互不足，降权
                cur.execute(
                    "SELECT i2.doc_id AS doc_id, COUNT(*) AS c FROM kms_rec_interactions i1 "
                    "JOIN kms_rec_interactions i2 ON i2.user_id=i1.user_id "
                    "AND i2.doc_id IS NOT NULL AND i2.doc_id<>i1.doc_id "
                    "WHERE i1.user_id=%s AND i1.doc_id IS NOT NULL "
                    "GROUP BY i2.doc_id ORDER BY c DESC LIMIT %s",
                    (user.id, max(settings.kms_rec_top_n * 3, 15)),
                )
                return {int(r["doc_id"]): float(r["c"]) for r in cur.fetchall()}
        except Exception as e:
            logger.debug(f"协同策略跳过: {e}")
            return {}


class PopularityStrategy(Strategy):
    """热度：按半衰期衰减的交互热度排序；无交互时以最新发布文档兜底。"""

    name = "popular"

    def score(self, user: AuthUser, seed_text: str, seed_doc_id: Optional[int]) -> Dict[int, float]:
        try:
            with MySQLStore()._conn() as cur:
                cur.execute(
                    "SELECT doc_id, SUM(weight * POW(0.5, TIMESTAMPDIFF(DAY, created_at, NOW())/%s)) AS s "
                    "FROM kms_rec_interactions WHERE doc_id IS NOT NULL "
                    "GROUP BY doc_id ORDER BY s DESC LIMIT %s",
                    (settings.kms_rec_half_life_days, max(settings.kms_rec_top_n * 3, 15)),
                )
                rows = cur.fetchall()
            if rows:
                return {int(r["doc_id"]): max(float(r["s"] or 0), 0.0) for r in rows}
        except Exception as e:
            logger.debug(f"热度策略跳过: {e}")
        # 冷启动兜底：按最新发布顺序给分，保证首次访问也有可用推荐
        try:
            pool = _published_pool(limit=max(settings.kms_rec_top_n * 2, 20))
            return {int(r["document_id"]): 1.0 / (i + 1) for i, r in enumerate(pool)}
        except Exception:
            return {}


# ===================== 融合引擎 =====================
def _active_strategies() -> List[tuple]:
    """按配置权重组装启用中的策略（权重 <=0 视为关闭）。"""
    return [
        ("organization", settings.kms_rec_weight_org, OrgProfileStrategy()),
        ("semantic", settings.kms_rec_weight_semantic, SemanticStrategy()),
        ("collaborative", settings.kms_rec_weight_collab, CollaborativeStrategy()),
        ("popular", settings.kms_rec_weight_popular, PopularityStrategy()),
    ]


def recommend(user: AuthUser, top_n: Optional[int] = None,
              seed_text: str = "", seed_doc_id: Optional[int] = None) -> List[Recommendation]:
    """融合各路策略 → 权限硬过滤 → 返回 top_n 推荐。"""
    if not settings.kms_rec_enabled or not user or not user.is_active:
        return []
    top_n = top_n or settings.kms_rec_top_n

    merged: Dict[int, float] = {}
    reasons: Dict[int, List[str]] = {}
    for name, weight, strategy in _active_strategies():
        if weight <= 0:
            continue
        try:
            raw = strategy.score(user, seed_text, seed_doc_id) or {}
        except Exception as e:
            logger.warning(f"推荐策略 {name} 失败，跳过: {e}")
            continue
        if not raw:
            continue
        top = max(raw.values())
        if top <= 0:
            continue
        for doc_id, value in raw.items():
            merged[doc_id] = merged.get(doc_id, 0.0) + weight * (value / top)
            reasons.setdefault(doc_id, []).append(name)

    if not merged:
        return []

    ranked = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)[: top_n * 3]
    try:
        rows = _load_rows([doc_id for doc_id, _ in ranked])
    except Exception as e:
        logger.warning(f"加载推荐候选元数据失败: {e}")
        return []
    by_id = {int(r["document_id"]): r for r in rows}

    out: List[Recommendation] = []
    for doc_id, score in ranked:
        row = by_id.get(doc_id)
        if not row:
            continue
        # —— 权限硬过滤：未授权候选一律剔除 ——
        if not service.allowed(row, user, 0, user.security_level):
            continue
        hits = list(dict.fromkeys(reasons.get(doc_id, [])))
        level = row.get("classification")
        out.append(Recommendation(
            doc_id=doc_id,
            title=row.get("title") or "",
            file_type=row.get("file_type") or "",
            classification=int(level) if level is not None else 0,
            score=round(score, 4),
            reasons=hits,
            strategies=hits,
        ))
        if len(out) >= top_n:
            break
    return out


# ===================== 路由 =====================
@router.get("/recommendations")
def recommendations(
    request: Request,
    top_n: int = Query(0, ge=0, le=50),
    seed_doc_id: Optional[int] = Query(None, ge=1),
    seed_text: str = Query("", max_length=200),
    user: AuthUser = Depends(require_user),
):
    """定向推荐：仅返回当前员工有权访问的已发布文档。"""
    if not settings.kms_rec_enabled:
        return {"enabled": False, "items": []}
    items = recommend(user, top_n=(top_n or settings.kms_rec_top_n),
                      seed_text=seed_text, seed_doc_id=seed_doc_id)
    try:
        from gateway.audit import log_gw_event
        log_gw_event(
            "kms", "recommendations", request_id=getattr(request.state, "request_id", ""),
            employee_no=user.employee_no, target=f"reco:{len(items)}",
            ip=client_ip(request),
        )
    except Exception as e:
        logger.debug(f"推荐审计写入失败: {e}")
    return {"enabled": True, "items": [r.to_dict() for r in items]}
