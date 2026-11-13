"""MCP（Model Context Protocol）对外知识服务面。

把 KMS 已有的企业知识能力以标准协议暴露给外部应用与 AI 智能体：

    Cursor / Claude / 客服工作台 / 商户 APP / 集团智能体平台
        │  POST /gw/api/v1/mcp   （Streamable HTTP，JSON-RPC 2.0）
        ├─ EnterpriseBoundary（已有）：请求ID / 限流 / 审计 / 响应缓冲
        ├─ auth.py：员工 JWT（+可选应用 Key）→ AuthUser，服务端解析
        ├─ tools.py / resources.py：只读能力为主，写路径仅"提交知识需求"
        └─ 复用既有内核：service.allowed / service.answer / recommend / state

硬边界（见 docs/mcp_engineering.md）：
- 挂 KMS 进程 6342，不新开监听、不触碰 QA 6341 任何代码；
- 不暴露底层向量库/数据库路径，不提供任何通往 QA 竞赛语料的通路；
- 双人审批不被旁路：无 approve 类工具，批准永远留在 Web 端由人操作；
- 开关 GW_MCP_ENABLED 默认 0，关闭时本路由根本不注册（等价于功能不存在）。
"""
from __future__ import annotations

from config import settings


def build_mcp_router(force: bool | None = None):
    """构建 MCP 路由；未启用时返回 None，调用方据此跳过注册。

    force 仅供测试使用：True 强制构建，False 强制不构建，None 按配置。
    """
    enabled = settings.gw_mcp_enabled if force is None else force
    if not enabled:
        return None
    from .server import router

    return router


__all__ = ["build_mcp_router"]
