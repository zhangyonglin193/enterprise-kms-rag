"""分页参数归一化（单一事实源）。

改造前 offset/limit 在 8 处各自定义，**默认值与上限互不相同**：

    gateway/routes_kms.py:107    limit 默认 50  上限 100
    gateway/routes_kms.py:354    limit 默认 50  上限 200
    gateway/routes_kms.py:175    limit 默认 100 上限 200
    gateway/routes_embed.py:126  limit 默认 20  上限 100
    gateway/mcp/tools.py:147     int(args.get("limit") or 20)   ← 无上限
    kms/admin_routes.py:214      裸参数 + max(1, min(limit, 1000))
    kms/recommend.py:372         top_n 上限 50
    kms/hr_sync.py:249           limit=20

后果：同一语义「每页多少条」在不同入口有 6 种边界，且 MCP 入口**完全没有上限**——
外部传 limit=999999 即可触发全表扫描。此处收敛为一份默认值/上限 + 一个归一化函数。
"""
from __future__ import annotations

from typing import Tuple

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_pagination(offset=0, limit=DEFAULT_LIMIT,
                     max_limit: int = MAX_LIMIT) -> Tuple[int, int]:
    """归一化分页参数，返回 (offset, limit)。

    保证 offset >= 0 且 1 <= limit <= max_limit。非数字/None 一律退回默认值，
    绝不向上抛出——分页参数不该成为请求失败的原因。

    供非 FastAPI 声明式入口使用（MCP tools、裸函数参数、脚本）。
    FastAPI 路由请直接用 `pagination_params` 依赖以获得 OpenAPI 文档。
    """
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(0, offset), max(1, min(limit, int(max_limit)))


def pagination_params(offset: int = 0, limit: int = DEFAULT_LIMIT) -> Tuple[int, int]:
    """FastAPI 路由的共享分页依赖（带 OpenAPI 约束与统一边界）。

    用法::

        @router.get("/x")
        def list_x(page: Tuple[int, int] = Depends(pagination_params)):
            offset, limit = page
    """
    from fastapi import Depends, Query

    def _dep(offset: int = Query(0, ge=0),
             limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> Tuple[int, int]:
        return offset, limit

    return Depends(_dep)  # type: ignore[return-value]
