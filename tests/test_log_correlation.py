"""日志 request_id 关联（P2 可观测）：不修改 app/ 冻结面，运行时注入 rid。

锁定：install() 为 logger 的 handler 追加 RequestIdFilter 并替换为带 rid= 的 Formatter；
request_id_var 被中间件逐请求写入后，一次请求的全链路日志可凭 rid 关联审计 JSONL。
"""
from __future__ import annotations

import logging
import unittest
import uuid
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from scripts.service import apply_environment

RUN = ROOT / "data" / "test-runs" / uuid.uuid4().hex
apply_environment(RUN / "absent.env", {
    "MYSQL_DATABASE": "offline_test_only",
    "KMS_SECRET_KEY": "offline-test-key-not-for-production-0123456789",
    "KMS_APPROVER_EMPLOYEES": "approver",
    "KMS_ADMIN_EMPLOYEES": "admin", "KMS_AUDITOR_EMPLOYEES": "auditor",
})

from gateway.logctx import install, request_id_var, RequestIdFilter  # noqa: E402


class RequestIdCorrelationTests(unittest.TestCase):
    def _fresh_logger(self, name: str):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        buf = StringIO()
        h = logging.StreamHandler(buf)
        logger.addHandler(h)
        logger.propagate = False
        logger.setLevel(logging.INFO)
        return logger, buf, h

    def test_install_attaches_filter_and_rid_formatter(self):
        logger, _, h = self._fresh_logger("test.correlation.a")
        install()
        self.assertTrue(any(isinstance(f, RequestIdFilter) for f in h.filters))
        self.assertIn("rid=", h.formatter._fmt)

    def test_request_id_var_propagates_to_log(self):
        logger, buf, _ = self._fresh_logger("test.correlation.b")
        install()
        token = request_id_var.set("RID-ABC")
        try:
            logger.warning("hello")
        finally:
            request_id_var.reset(token)
        out = buf.getvalue()
        self.assertIn("rid=RID-ABC", out)
        self.assertIn("hello", out)

    def test_non_request_context_defaults_to_dash(self):
        logger, buf, _ = self._fresh_logger("test.correlation.c")
        install()
        logger.warning("boot")
        self.assertIn("rid=-", buf.getvalue())

    def test_filter_reads_contextvar(self):
        rec = logging.LogRecord("x", logging.INFO, "p", 1, "m", None, None)
        token = request_id_var.set("RID-9")
        try:
            self.assertTrue(RequestIdFilter().filter(rec))
        finally:
            request_id_var.reset(token)
        self.assertEqual(rec.request_id, "RID-9")


if __name__ == "__main__":
    unittest.main()
