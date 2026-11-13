"""MCP 工具与资源 schema —— 单一事实来源。

服务端 `tools/list` 与契约测试都从本模块读取，避免"手写两份漂移"。
新增工具只需在 TOOLS 注册并在 tools.py 绑定 handler，测试自动覆盖形状。
"""
from __future__ import annotations

from typing import Optional

# ===== 工具定义 =====
# description 一律静态常量：禁止动态拼接，防工具描述注入（tool poisoning）。
TOOLS = [
    {
        "name": "search_knowledge",
        "description": "在企业知识库中检索当前身份有权访问的资料片段，返回带来源的摘要。不调用生成模型，成本低。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 500, "description": "检索问题或关键词"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                "max_classification": {
                    "type": "integer", "minimum": 0, "maximum": 3,
                    "description": "密级上限，只能低于调用者自身职级，不能提权",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_question",
        "description": "基于当前身份有权访问的已发布资料生成带引用的答案。需要服务端已批准模型出域。",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string", "maxLength": 1000}},
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_document",
        "description": "读取指定文档的正文分块与元数据（仅返回授权可见内容）。",
        "inputSchema": {
            "type": "object",
            "properties": {"doc_id": {"type": "integer", "minimum": 1}},
            "required": ["doc_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_documents",
        "description": "列出当前身份有权访问的已发布文档目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recommendations",
        "description": "获取当前身份有权访问的知识推荐（组织画像/语义/协同/热度融合，越权内容已硬过滤）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "top_n": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "seed_text": {"type": "string", "maxLength": 200, "description": "可选：兴趣种子文本"},
                "seed_doc_id": {"type": "integer", "minimum": 1, "description": "可选：兴趣种子文档"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_feedback",
        "description": "对某次问答结果提交评价（up/down），用于推荐与质量改进。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "maxLength": 64},
                "rating": {"type": "string", "enum": ["up", "down"]},
                "comment": {"type": "string", "maxLength": 500},
            },
            "required": ["message_id", "rating"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_knowledge_request",
        "description": "提交知识发布/变更申请（生成工单）。审批必须由审批员在 Web 端人工完成，本工具不执行审批。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "integer", "minimum": 1},
                "classification": {"type": "integer", "minimum": 0, "maximum": 3},
                "owner_department": {"type": "string", "maxLength": 128},
                "reason": {"type": "string", "maxLength": 500},
            },
            "required": ["doc_id", "classification", "owner_department", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_app_usage",
        "description": "查询调用方应用近期的调用量/错误率/配额使用情况（仅应用身份或管理员可用）。",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7}},
            "additionalProperties": False,
        },
    },
]

# ===== 资源模板 =====
RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "kms://documents/{id}",
        "name": "企业文档（授权后可见）",
        "description": "按文档 ID 读取正文分块与元数据；越权返回错误。",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "kms://recommendations",
        "name": "知识推荐",
        "description": "当前身份有权访问的知识推荐列表。",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "kms://app/usage",
        "name": "应用用量",
        "description": "调用方应用近期的调用统计（仅应用身份或管理员）。",
        "mimeType": "application/json",
    },
]

TOOL_NAMES = tuple(t["name"] for t in TOOLS)


def tools_for(whitelist: Optional[list]) -> list:
    """按配置白名单过滤工具面（对标银联 unionpay-mcp-server 的 UP_AVAILABLE_TOOLS）。"""
    if not whitelist:
        return list(TOOLS)
    allowed = {str(x).strip() for x in whitelist}
    return [t for t in TOOLS if t["name"] in allowed]


def tool_schema(name: str) -> Optional[dict]:
    for t in TOOLS:
        if t["name"] == name:
            return t["inputSchema"]
    return None


__all__ = ["TOOLS", "RESOURCE_TEMPLATES", "TOOL_NAMES", "tools_for", "tool_schema"]
