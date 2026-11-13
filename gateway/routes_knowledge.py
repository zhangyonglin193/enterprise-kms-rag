# -*- coding: utf-8 -*-
"""知识中心（/kms/api/knowledge/*）——文档之上的发现与统计层。

收敛决策（为什么只有这 4 个端点）
--------------------------------
前端原本调用 10 个 knowledge 端点，后端零实现。取证后发现数据库**没有任何
categories / tags / ratings / favorites 表**，即其中 6 个连数据基础都不存在，
不是"接口没写"而是"这个功能不存在"。

按「有数据就做、没数据就下线」收敛：

  实现（4 个，可由既有数据推导）
    hot                 ← kms_rec_interactions(kind='view')
    analytics/overview  ← 可见文档计数
    analytics/trends    ← rec_interactions 按日聚合
    personal/stats      ← 审计日志 + rec_interactions 按用户聚合

  下线（6 个，无数据基础）
    categories / tags / top-rated / personal/favorites
    analytics/health / analytics/contributors

  恢复前提：categories、tags、favorites、ratings 需要先建数据模型，并先回答
  「分类体系从哪来」这个产品问题；health 的"健康度"与 contributors 的"贡献者"
  当时也没有指标口径。二者都不是接口问题，因此不实现——**用真实数字表达错误
  的语义，比不给这个数字更糟**。

  另注：`documents` 表没有上传者字段（只有 owner_department），
  因此「我上传的文档」改由审计日志 kms_audit_logs 推导。

授权
----
统计一律在**当前用户可见的文档集合**内计算，复用 service.visible_documents_sql，
与文档列表同源，避免「列表里看不到、统计里数得到」的越权。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.store import MySQLStore
from gateway import service
from gateway.routes_kms import document_row
from kms.constants import AUDIT_DOC_UPLOAD
from kms.security import AuthUser, require_user

router = APIRouter(prefix="/kms/api", tags=["knowledge"])

# 热门榜先按交互数取候选、再逐个鉴权，故需放大取样；上限防止大库拖垮查询
_HOT_SAMPLE_FACTOR = 5
_HOT_SAMPLE_CAP = 200


@router.get("/knowledge/hot")
def hot_documents(limit: int = Query(10, ge=1, le=50),
                  user: AuthUser = Depends(require_user)):
    """热门文档：按浏览量降序，**只返回当前用户有权查看的**。

    先按交互次数取候选，再逐个过 service.allowed（与文档详情同源的判定）。
    宁可多取几行再过滤，也不为"热门"另写一条权限 SQL——那会让权限策略出现
    第二份实现，迟早漂移成越权。
    """
    sample = min(limit * _HOT_SAMPLE_FACTOR, _HOT_SAMPLE_CAP)
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "SELECT doc_id, COUNT(*) AS view_count FROM kms_rec_interactions "
                "WHERE kind='view' AND doc_id IS NOT NULL "
                "GROUP BY doc_id ORDER BY view_count DESC, doc_id LIMIT %s", (sample,))
            candidates = cur.fetchall()
    except Exception:
        raise HTTPException(503, "统计不可用") from None
    if not candidates:
        return {"items": []}

    items = []
    with MySQLStore()._conn() as cur:
        for c in candidates:
            try:
                row = document_row(cur, c["doc_id"])
            except HTTPException:
                continue  # 文档已被删除，交互记录还没清
            if not service.allowed(row, user, 0, user.security_level):
                continue
            items.append({
                "document_id": row["document_id"],
                "filename": row["filename"],
                "title": row["title"],
                "classification": row["classification"],
                "view_count": int(c["view_count"]),
            })
            if len(items) >= limit:
                break
    return {"items": items}


@router.get("/knowledge/analytics/overview")
def analytics_overview(user: AuthUser = Depends(require_user)):
    """知识库概览：当前用户可见的文档总数。

    刻意**不提供**「生命周期分布」：可见集合本身已被过滤为「已发布且未过期」，
    再统计 published/archived/expired 只会有 published 一项有数——
    那是用真实数字表达错误语义，不如不给。
    """
    predicate, params = service.visible_documents_sql(user, 0, user.security_level)
    try:
        with MySQLStore()._conn() as cur:
            cur.execute("SELECT COUNT(*) AS total " + predicate, params)
            total = int(cur.fetchone()["total"])
    except Exception:
        raise HTTPException(503, "统计不可用") from None
    return {"total_documents": total}


@router.get("/knowledge/analytics/trends")
def analytics_trends(days: int = Query(30, ge=1, le=365),
                     user: AuthUser = Depends(require_user)):
    """知识活跃趋势：活跃用户数 + 每日浏览量。

    这是**不含文档标识的纯聚合**（只暴露数量，不暴露哪些文档被谁看），
    故不做逐文档鉴权。若将来要按文档下钻，必须重新引入可见性过滤。
    """
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT user_id) AS active_users FROM kms_rec_interactions "
                "WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)", (days,))
            active_users = int(cur.fetchone()["active_users"])
            cur.execute(
                "SELECT DATE(created_at) AS day, COUNT(*) AS views "
                "FROM kms_rec_interactions WHERE kind='view' "
                "AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) "
                "GROUP BY DATE(created_at) ORDER BY day", (days,))
            series = [{"date": str(r["day"]), "views": int(r["views"])}
                      for r in cur.fetchall()]
    except Exception:
        raise HTTPException(503, "统计不可用") from None
    return {"days": days, "active_users": active_users, "items": series}


@router.get("/knowledge/personal/stats")
def personal_stats(user: AuthUser = Depends(require_user)):
    """我的知识统计。

    刻意**不提供** documents_favorited / documents_rated / average_rating：
    收藏与评分没有数据基础（无对应表）。返回 0 会让人误以为"我有 0 个收藏"，
    而实际是这个功能不存在——**不存在的东西不该给数字**。

    uploaded_documents 由审计日志推导：documents 表没有上传者字段。
    """
    try:
        with MySQLStore()._conn() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM kms_audit_logs "
                        "WHERE user_id=%s AND action=%s", (user.id, AUDIT_DOC_UPLOAD))
            uploaded = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(*) AS n FROM kms_rec_interactions "
                        "WHERE user_id=%s AND kind='view'", (user.id,))
            views_given = int(cur.fetchone()["n"])
            cur.execute(
                "SELECT COUNT(*) AS n FROM kms_rec_interactions WHERE kind='view' "
                "AND doc_id IN (SELECT CAST(SUBSTRING_INDEX(target, ':', -1) AS UNSIGNED) "
                "FROM kms_audit_logs WHERE user_id=%s AND action=%s "
                # '%%' 必须双写：pymysql 用 Python % 插值，未转义的字面量 % 会被
                # 当成占位符，直接报 "not enough arguments for format string"
                "AND target LIKE 'document:%%')", (user.id, AUDIT_DOC_UPLOAD))
            views_received = int(cur.fetchone()["n"])
    except Exception:
        raise HTTPException(503, "统计不可用") from None
    return {
        "uploaded_documents": uploaded,
        "total_views_given": views_given,
        "total_views_received": views_received,
    }
