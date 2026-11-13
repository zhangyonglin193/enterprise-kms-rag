"""请求级日志关联：把 request_id 注入业务日志（不修改 app/ 冻结面）。

原理
----
KMS 中间件为每次请求生成 rid 并写入 `contextvars`；本模块在 KMS 服务启动时把
`RequestIdFilter` 挂到所有 logger 的 handler 上，并将 Formatter 替换为带 `rid=` 的版本，
从而使一次请求的全链路日志（含 `app/rag` 检索、DB 调用）能凭 rid 关联到审计 JSONL。

约束
----
`app/` 为冻结面，由 CI 守卫强制（见 `docs/mcp_engineering.md`）。本模块**不修改
`app/logger.py` 任何源码**，仅在运行时调整已存在 handler 的 Formatter/Filter，属可逆的
进程内状态变更，不影响评测确定性。
"""
from __future__ import annotations

import logging
from contextvars import ContextVar

# 默认 "-"：非请求上下文（启动 / 后台任务）的日志也能正常输出，只是无可关联 rid。
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


_CORRELATION_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s | rid=%(request_id)s | %(message)s"
)


def install() -> None:
    """为全部已注册 logger 的 handler 追加 request_id 关联（幂等）。

    须在应用模块导入之后调用，确保各模块的 module-level logger 已创建。
    """
    for name in list(logging.Logger.manager.loggerDict):
        _patch(logging.getLogger(name))
    _patch(logging.getLogger())  # 根 logger（若有 handler）


def _patch(logger: logging.Logger) -> None:
    if getattr(logger, "_rid_patched", False):
        return
    for h in logger.handlers:
        h.addFilter(RequestIdFilter())
        h.setFormatter(logging.Formatter(_CORRELATION_FORMAT))
    logger._rid_patched = True
