"""MCP 协议层：JSON-RPC 2.0 编解码、版本协商、错误码、参数校验。

设计取舍：不引入第三方 MCP SDK。协议面小（initialize / ping / tools / resources
十余个方法），手写可把身份、审计、脱敏完全控制在项目既有机制内，也符合本仓库
"依赖用范围约束、不锁死"的纪律。传输层（HTTP/SSE）差异全部收敛在本模块，
MCP 规范后续变更只换这一层，业务代码不受影响。

错误码遵循 JSON-RPC 2.0 预定义段 + 服务端自定义段（-32000 ~ -32099）：
    -32700 解析失败 / -32600 非法请求 / -32601 方法不存在
    -32602 参数不符 schema / -32603 内部错误
    -32001 未认证 / -32003 无权限
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

# ===== JSON-RPC 2.0 预定义错误码 =====
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# ===== 服务端自定义错误码（-32000 ~ -32099）=====
AUTH_REQUIRED = -32001
PERMISSION_DENIED = -32003
SERVICE_UNAVAILABLE = -32004
RATE_LIMITED = -32005

# 服务端支持的协议版本：锁定，不自动追新（MCP 传输层已从 SSE 变更过一次）
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

SERVER_INFO = {"name": "unionpay-merchant-kms-mcp", "version": "1.0.0"}

MCP_PROTOCOL_HEADER = "MCP-Protocol-Version"
MCP_SESSION_HEADER = "Mcp-Session-Id"


class RPCError(Exception):
    """JSON-RPC 错误；http_status 用于认证/权限类错误返回对应 HTTP 状态码。"""

    def __init__(self, code: int, message: str, data: Any = None, http_status: int = 200):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status

    def to_dict(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


def auth_error(message: str = "缺少或无效的员工令牌") -> RPCError:
    return RPCError(AUTH_REQUIRED, message, http_status=401)


def permission_error(message: str = "当前身份无权访问该资源") -> RPCError:
    return RPCError(PERMISSION_DENIED, message, http_status=403)


def unavailable_error(message: str = "依赖服务不可用") -> RPCError:
    return RPCError(SERVICE_UNAVAILABLE, message, http_status=503)


def rate_limit_error(message: str = "调用过于频繁，请稍后重试") -> RPCError:
    return RPCError(RATE_LIMITED, message, http_status=429)


def http_status_for(error: "RPCError") -> int:
    """JSON-RPC 错误对外的 HTTP 状态码。

    关键约束：EnterpriseBoundary 中间件会把所有 >=400 的响应体替换为网关统一
    错误信封（有意为之的防泄密设计），这会销毁 JSON-RPC 错误信封，导致 MCP
    客户端无法按 id 关联错误。因此协议级错误一律以 HTTP 200 + JSON-RPC error
    返回（MCP Streamable HTTP 规范允许），仅传输层问题（请求体过大 413）保留
    非 200 状态码。
    """
    return error.http_status if error.http_status == 413 else 200


def parse_message(body: bytes) -> dict:
    """解析并做最基本的 JSON-RPC 2.0 结构校验。"""
    try:
        msg = json.loads(body.decode("utf-8"))
    except Exception:
        raise RPCError(PARSE_ERROR, "JSON 解析失败", http_status=400) from None
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        raise RPCError(INVALID_REQUEST, "不是合法的 JSON-RPC 2.0 请求", http_status=400)
    if "id" in msg and not isinstance(msg["id"], (str, int, type(None))):
        raise RPCError(INVALID_REQUEST, "id 必须是字符串、数字或 null", http_status=400)
    return msg


def is_notification(msg: dict) -> bool:
    """通知（无 id）按规范不产生响应体。"""
    return "id" not in msg


def negotiate_version(requested: Optional[str]) -> str:
    """版本协商：请求版本受支持则原样采用，否则回退服务端首选版本。"""
    if requested and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return SUPPORTED_PROTOCOL_VERSIONS[0]


def build_result(msg: dict, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}


def build_error(msg: dict, error: RPCError) -> dict:
    return {"jsonrpc": "2.0", "id": msg.get("id"), "error": error.to_dict()}


# ===== 参数校验（最小 JSON Schema 子集，覆盖本项目工具面所需约束）=====
_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def validate_against(schema: dict, value: Any, path: str = "$") -> None:
    """按 schema 校验参数；不满足抛 -32602。刻意保持小巧，不引 jsonschema 依赖。

    支持：type / required / properties / additionalProperties / enum /
          maxLength / minimum / maximum / items。
    """
    expected = schema.get("type")
    if expected:
        # bool 是 int 子类，integer/number 校验需排除 bool
        if expected in ("integer", "number") and isinstance(value, bool):
            raise RPCError(INVALID_PARAMS, f"{path}: 期望 {expected}，得到布尔值")
        py = _TYPE_MAP.get(expected)
        if py and not isinstance(value, py):
            raise RPCError(INVALID_PARAMS, f"{path}: 期望 {expected}，实际 {type(value).__name__}")

    if expected == "object" and isinstance(value, dict):
        allowed = set((schema.get("properties") or {}).keys())
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value.keys()) - allowed)
            if extra:
                raise RPCError(INVALID_PARAMS, f"{path}: 不允许的字段 {extra}")
        for key in schema.get("required") or []:
            if key not in value:
                raise RPCError(INVALID_PARAMS, f"{path}: 缺少必填字段 {key}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value and value[key] is not None:
                validate_against(sub, value[key], f"{path}.{key}")

    if expected == "string" and isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise RPCError(INVALID_PARAMS, f"{path}: 超过最大长度 {schema['maxLength']}")
        if "enum" in schema and value not in schema["enum"]:
            raise RPCError(INVALID_PARAMS, f"{path}: 必须是 {schema['enum']} 之一")

    if expected in ("integer", "number") and isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise RPCError(INVALID_PARAMS, f"{path}: 不得小于 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise RPCError(INVALID_PARAMS, f"{path}: 不得大于 {schema['maximum']}")
        if "enum" in schema and value not in schema["enum"]:
            raise RPCError(INVALID_PARAMS, f"{path}: 必须是 {schema['enum']} 之一")

    if expected == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                validate_against(item_schema, item, f"{path}[{i}]")


_URI_TEMPLATE_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def match_resource_uri(template: str, uri: str) -> Optional[dict]:
    """把具体 URI 匹配到资源模板，返回路径参数；不匹配返回 None。

    例：match_resource_uri("kms://documents/{id}", "kms://documents/42") -> {"id": "42"}
    """
    if not uri.startswith("kms://"):
        return None
    names = _URI_TEMPLATE_RE.findall(template)
    if not names:
        return {} if uri == template else None
    tpl_parts = template.split("/")
    uri_parts = uri.split("/")
    if len(tpl_parts) != len(uri_parts):
        return None
    params: dict = {}
    for tpl_part, uri_part in zip(tpl_parts, uri_parts):
        m = _URI_TEMPLATE_RE.fullmatch(tpl_part)
        if m:
            params[m.group(1)] = uri_part
        elif tpl_part != uri_part:
            return None
    return params


def digest(value: Any) -> str:
    """参数摘要（用于审计，不明文落盘）。"""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
