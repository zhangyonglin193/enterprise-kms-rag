"""MCP 资源读取：URI 模板匹配 + 复用工具处理器（单一实现，双协议暴露）。"""
from __future__ import annotations

from typing import Optional

from fastapi import Request

from . import protocol
from . import tools as tool_impl
from .auth import McpIdentity
from .schemas import RESOURCE_TEMPLATES


def read_resource(identity: McpIdentity, uri: str, request: Optional[Request] = None) -> dict:
    """按 URI 读取资源；不匹配或无权访问时抛 RPCError。"""
    params = protocol.match_resource_uri("kms://documents/{id}", uri)
    if params is not None:
        try:
            doc_id = int(params["id"])
        except (TypeError, ValueError):
            raise protocol.RPCError(protocol.INVALID_PARAMS, "文档 ID 必须为整数") from None
        return tool_impl.get_document(identity, {"doc_id": doc_id}, request)

    if protocol.match_resource_uri("kms://recommendations", uri) is not None:
        return tool_impl.get_recommendations(identity, {}, request)

    if protocol.match_resource_uri("kms://app/usage", uri) is not None:
        return tool_impl.get_app_usage(identity, {}, request)

    raise protocol.RPCError(protocol.INVALID_PARAMS, f"未知资源 URI: {uri}")


def list_resources(identity: McpIdentity) -> list:
    """资源清单：按身份过滤（app/usage 仅应用身份或管理员可见由读取时把关）。"""
    return [
        {"uri": t["uriTemplate"], "name": t["name"], "description": t["description"], "mimeType": t["mimeType"]}
        for t in RESOURCE_TEMPLATES
    ]


def list_templates() -> list:
    return [
        {"uriTemplate": t["uriTemplate"], "name": t["name"], "description": t["description"], "mimeType": t["mimeType"]}
        for t in RESOURCE_TEMPLATES
    ]


__all__ = ["read_resource", "list_resources", "list_templates"]
