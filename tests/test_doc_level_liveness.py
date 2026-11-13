# -*- coding: utf-8 -*-
"""文档密级读取的「实时性」契约测试。

背景：原 kms/access_control.py 有一组带进程内缓存的密级 helper
（get_doc_level / get_doc_levels_map / set_doc_level / clear_doc_level +
_doc_level_cache），已整体删除。删除不是因为它们丑，而是因为它们**从未被调用**，
且带着一个危险特性：缓存无 TTL、实际写入方（routes_kms.py:157/259 的内联 SQL）
不刷新它——一旦有人接入，密级提权后本进程会长期返回旧低值，形成越权窗口。

本测试锁死两件事，防止将来有人「为了方便」重新引入进程内密级缓存：
  1. 模块级不得再出现密级缓存（结构断言）；
  2. 生产读路径必须是实时 SQL JOIN（语义断言，用模拟游标验证 SQL 形态）。
"""
from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from scripts.service import apply_environment

RUN = ROOT / "data" / "test-runs" / uuid.uuid4().hex
apply_environment(RUN / "absent.env", {
    "MYSQL_DATABASE": "offline_test_only",
    "KMS_SECRET_KEY": "offline-test-key-not-for-production-0123456789",
    "KMS_APPROVER_EMPLOYEES": "approver",
    "KMS_ADMIN_EMPLOYEES": "admin", "KMS_AUDITOR_EMPLOYEES": "auditor",
    "FAISS_INDEX_PATH": str(RUN / "faiss" / "index"),
    "UPLOAD_DIR": str(RUN / "uploads"),
    "DOCS_DIR": str(RUN / "docs"),
    "GW_AUDIT_DIR": str(RUN / "audit"),
    "GW_STATE_PATH": str(RUN / "state.sqlite3"),
})

from kms import access_control as acl  # noqa: E402


class NoCachedDocLevelTests(unittest.TestCase):
    """结构断言：模块不得再持有密级缓存状态。"""

    def test_dead_helpers_are_gone(self):
        for name in ("get_doc_level", "get_doc_levels_map",
                     "set_doc_level", "clear_doc_level"):
            self.assertFalse(hasattr(acl, name),
                             f"{name} 已删除，不应重新引入（见模块内注释）")

    def test_no_module_level_doc_level_cache(self):
        """任何「按 document_id 缓存密级」的模块级可变状态都不允许存在。"""
        banned = re.compile(r"doc_level|cache", re.I)
        for name, value in vars(acl).items():
            if name.startswith("__") or callable(value):
                continue
            if isinstance(value, (dict, list, set)) and banned.search(name):
                self.fail(f"发现模块级密级缓存状态: {name} = {value!r}")


class LiveReadPathTests(unittest.TestCase):
    """语义断言：生产读路径必须实时 JOIN kms_doc_levels。"""

    def test_answer_path_joins_doc_levels_live(self):
        """问答路径（current_contexts）必须 JOIN kms_doc_levels，而不是查缓存。"""
        from types import SimpleNamespace
        from app.store import MySQLStore
        from gateway import service
        from contextlib import contextmanager
        from unittest.mock import patch

        executed = []

        class _Cur:
            def execute(self, sql, params=None):
                executed.append(" ".join(sql.split()))

            def fetchall(self):
                return [{"faiss_id": 1, "text": "x", "page": 1, "chunk_index": 0,
                         "document_id": 1, "title": "t", "file_type": "pdf",
                         "classification": 1, "status": "published",
                         "lifecycle_state": "published", "departments": ["d"],
                         "owner_org_path": "",
                         "publication_approved": 1, "expired": 0}]

        @contextmanager
        def _conn(self_store):
            yield _Cur()

        user = SimpleNamespace(is_active=True, department="d", security_level=3,
                              org_path="", employee_no="e")
        with patch.object(MySQLStore, "_conn", _conn):
            service.current_contexts([{"faiss_id": 1, "text": "x"}], user)

        sql = executed[0]
        self.assertIn("JOIN kms_doc_levels", sql,
                      "问答路径必须实时 JOIN kms_doc_levels——走缓存会让密级变更不生效")

    def test_directory_path_joins_doc_levels_live(self):
        """目录路径（documents）同样必须实时 JOIN。"""
        from app.store import MySQLStore
        from gateway import service
        from contextlib import contextmanager
        from unittest.mock import patch
        from types import SimpleNamespace

        executed = []

        class _Cur:
            def execute(self, sql, params=None):
                executed.append(" ".join(sql.split()))

            def fetchone(self):
                return {"total": 0}          # COUNT(*) 查询

            def fetchall(self):
                return []

        @contextmanager
        def _conn(self_store):
            yield _Cur()

        user = SimpleNamespace(is_active=True, department="d", security_level=3,
                              org_path="", employee_no="e")
        with patch.object(MySQLStore, "_conn", _conn):
            service.documents(user, 0, 3, 0, 10)

        sql = executed[0]
        self.assertIn("JOIN kms_doc_levels", sql)
        # INNER JOIN 的 fail-closed 语义：无密级行的文档不出现在结果集
        self.assertNotIn("LEFT JOIN kms_doc_levels", sql,
                         "读路径必须是 INNER JOIN；LEFT JOIN 会让无密级文档以 "
                         "NULL 密级通过，破坏 fail-closed 约定")


if __name__ == "__main__":
    unittest.main()
