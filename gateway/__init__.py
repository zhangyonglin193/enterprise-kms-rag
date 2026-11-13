"""对外 API 网关（Open Gateway）—— 企业知识库统一对外服务层。

对标 IBM / 微软 / SAP 等大型 EKMS 厂商的「外部服务治理」规范：

        外部渠道                    网关层（本包）                  内部核心（不改动）
  ┌─────────────────┐      ┌──────────────────────────┐      ┌──────────────────┐
  │ 飞书机器人       │─────▶│ /gw/api/v1/bots/feishu    │      │                  │
  │ 企业微信机器人   │─────▶│ /gw/api/v1/bots/wecom     │─────▶│ kms 问答管线      │
  │ 嵌入式前端组件   │─────▶│ /gw/api/v1/embed/*        │      │ (BLP 密级过滤)    │
  └─────────────────┘      │  验签→鉴权→权限→审计→限流  │      │ FAISS / BM25 /   │
        X-API-Key          └──────────────────────────┘      │ MySQL(内部独占)   │
                           外部请求不可直达底层向量库/数据库    └──────────────────┘

职责边界：
- 本包承担渠道适配与安全治理：应用 Key 与员工 JWT 分离、身份沿调用链传递、出域闸门（默认关）、
  Rerank/生成前回源授权过滤、审计与限流；不直接暴露底层向量库/数据库；
- 检索与生成复用 kms 既有管线，但企业问答强制单轮（不接受 session/history）；
- 原有 /chat（赛题评测）保留；不符合安全边界的旧 /kms/api 写入口（如客户端自报密级）已隔离不注册。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.logger import get_logger

from .routes_bots import router as bots_router
from .routes_embed import router as embed_router
from .mcp import build_mcp_router

logger = get_logger("gateway")

# 对外统一前缀（版本化，符合大型系统工程 API 演进规范）
openapi_router = APIRouter(prefix="/gw/api/v1")
openapi_router.include_router(bots_router)
openapi_router.include_router(embed_router)

# MCP 知识服务面：GW_MCP_ENABLED=0（默认）时路由不注册，等价于功能不存在。
_mcp_router = build_mcp_router()
if _mcp_router is not None:
    openapi_router.include_router(_mcp_router)
    logger.info("MCP 知识服务已启用: /gw/api/v1/mcp")


def ensure_gateway_tables() -> bool:
    """初始化网关专属表（审计 + 身份绑定），幂等，MySQL 不可用时优雅降级。"""
    from .audit import ensure_gw_audit_table
    from .identity import ensure_identity_tables
    from kms import ratelimit

    ok_audit = ensure_gw_audit_table()
    ok_ident = ensure_identity_tables()
    ok_ratelimit = ratelimit.ensure_ratelimit_tables()
    return ok_audit and ok_ident and ok_ratelimit


__all__ = ["openapi_router", "ensure_gateway_tables"]
