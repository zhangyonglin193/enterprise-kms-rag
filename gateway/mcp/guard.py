"""MCP 输出防护：不可信内容包裹 + 指令注入中和 + 长度截断。

背景：MCP 工具输出会直接进入外部智能体的 LLM 上下文，而企业知识库中大量存在
"操作指令式"文本（点击【xx】、执行 xx 操作）。若不处理，攻击者可在文档中埋
"ignore previous instructions" 之类语句劫持调用方智能体（提示注入 / tool
poisoning 在企业场景的典型入口）。

策略（对应 docs/mcp_engineering.md 安全设计）：
1. 所有知识内容一律按"数据"处理，统一包裹 <untrusted_knowledge> 标签；
2. 命中已知注入模式的行被中和为占位符，不静默丢弃，便于审计比对；
3. 单次返回按 GW_MCP_MAX_RESULT_CHARS 截断，避免上下文炸弹。
"""
from __future__ import annotations

import re
from typing import Iterable

# 已知提示注入 / 角色劫持模式（大小写不敏感）
_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior)\s+instructions",
    r"you\s+are\s+(now\s+)?(a|an)\s+",
    r"system\s*prompt\s*[:：]",
    r"<\s*/?\s*system\s*>",
    r"<tool_call>",
    r"function_call",
    r"assistant\s*[:：]\s*\n",
    r"(^|\n)\s*(human|user|assistant)\s*[:：]",
    r"忘记(之前|以上|上面)[\u4e00-\u9fff]{0,6}(指令|要求|规则|提示)",
    r"忽略(之前|以上|上面)[\u4e00-\u9fff]{0,6}(指令|要求|规则|提示)",
    r"不要(再)?(听从|遵循|遵守)(之前|以上|上面)",
    r"你现在是",
)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

_FILTERED = "[内容已按安全策略过滤]"


def contains_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text or ""))


def strip_injection(text: str) -> str:
    """逐行中和注入语句：命中行整行替换，保留行数以便审计溯源。"""
    if not text:
        return ""
    out = []
    for line in str(text).splitlines():
        out.append(_FILTERED if _INJECTION_RE.search(line) else line)
    return "\n".join(out)


def sanitize(text: str, max_chars: int) -> str:
    """净化单段不可信文本：注入中和 + 长度截断。"""
    cleaned = strip_injection(text or "")
    if max_chars and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "…[已截断]"
    return cleaned


def wrap_untrusted(text: str, source: str = "kms") -> str:
    """把知识内容包裹为不可信数据块，提示调用方智能体不得执行其中指令。"""
    return f'<untrusted_knowledge source="{source}">\n{text}\n</untrusted_knowledge>'


def sanitize_fields(rows: Iterable[dict], text_keys: Iterable[str], max_chars: int) -> list:
    """批量净化记录中的文本字段（返回新 dict，不改原对象）。"""
    keys = tuple(text_keys)
    result = []
    for row in rows or []:
        new = dict(row)
        for k in keys:
            if k in new and isinstance(new[k], str):
                new[k] = sanitize(new[k], max_chars)
        result.append(new)
    return result


__all__ = ["contains_injection", "strip_injection", "sanitize", "wrap_untrusted", "sanitize_fields"]
