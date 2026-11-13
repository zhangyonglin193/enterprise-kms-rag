"""离线回归：目录适配器 / 统一登录提供方 / 权限隔离定向推荐。

不连接数据库/模型/平台，不启动真实监听服务；沿用 test_enterprise.py 的离线阻断模式。
"""
from __future__ import annotations

import contextlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
from scripts.service import apply_environment

RUN = ROOT / "data" / "test-runs" / uuid.uuid4().hex
apply_environment(RUN / "absent.env", {
    "MYSQL_DATABASE": "offline_test_only",
    "KMS_SECRET_KEY": "offline-test-key-not-for-production-0123456789",
    "KMS_APPROVER_EMPLOYEES": "approver",
    "KMS_ADMIN_EMPLOYEES": "admin", "KMS_AUDITOR_EMPLOYEES": "auditor",
})

from fastapi import HTTPException
from app.store import MySQLStore
from config import settings
from kms import org
from kms import recommend as rec
from kms.directory import (
    SimulatedDirectoryAdapter,
    build_directory_adapter,
)
from kms.oidc_provider import (
    BuiltinOIDCProvider,
    ExternalOIDCProvider,
    build_oidc_provider,
)
from kms.security import AuthUser

USER_ROW = dict(id=7, employee_no="20260019", username="测试经理", security_level=2,
                department="风险控制部", is_active=True,
                org_path="银联商务/风险控制部", manager_employee_no="")


# ===================== 离线伪装 =====================
class FakeCursor:
    """记录执行语句的假游标，用于断言 SQL 形状。"""

    def __init__(self):
        self.calls = []
        self.rows = []
        self.lastrowid = 1

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


@contextlib.contextmanager
def _cm(cur):
    yield cur


def fake_db(cur):
    """同时阻断真实连接池并注入假游标。"""
    return patch.multiple(
        MySQLStore,
        _get_pool=MagicMock(side_effect=AssertionError("离线测试禁止真实 MySQL")),
        _conn=lambda *a, **k: _cm(cur),
    )


class DirectoryTests(unittest.TestCase):
    def test_simulated_seed_adapter(self):
        adapter = build_directory_adapter("seed")
        self.assertIsInstance(adapter, SimulatedDirectoryAdapter)
        self.assertEqual(adapter.name, "simulated-seed")
        nodes = adapter.fetch_org_nodes()
        self.assertGreater(len(nodes), 0)
        self.assertIn("risk", [n["code"] for n in nodes])
        self.assertEqual(adapter.fetch_employees(), [])

    def test_ldap_and_ad_dispatch(self):
        self.assertEqual(build_directory_adapter("ldap").source_type, "ldap")
        self.assertEqual(build_directory_adapter("ad").name, "ad")

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            build_directory_adapter("magic")

    def test_ldap_missing_dependency_is_explicit(self):
        # 模拟未安装 ldap3：sys.modules 置 None → import 抛 ImportError → 明确 RuntimeError
        with patch.dict(sys.modules, {"ldap3": None}, clear=False):
            with self.assertRaises(RuntimeError):
                build_directory_adapter("ldap")._connect()


class OrgPathTests(unittest.TestCase):
    def test_path_level_parent(self):
        nodes = [
            {"code": "root", "name": "银联商务", "parent_code": None},
            {"code": "risk", "name": "风险控制部", "parent_code": "root"},
            {"code": "risk_strategy", "name": "风控策略组", "parent_code": "risk"},
        ]
        paths = org.compute_org_paths(nodes)
        self.assertEqual(paths["root"], ("银联商务", 0, None))
        self.assertEqual(paths["risk"], ("银联商务/风险控制部", 1, "root"))
        self.assertEqual(paths["risk_strategy"], ("银联商务/风险控制部/风控策略组", 2, "risk"))

    def test_cycle_is_bounded(self):
        nodes = [
            {"code": "a", "name": "A", "parent_code": "b"},
            {"code": "b", "name": "B", "parent_code": "a"},
        ]
        paths = org.compute_org_paths(nodes)  # 不应死循环
        self.assertIn("a", paths)
        self.assertIn("b", paths)


class OidcProviderTests(unittest.TestCase):
    def test_builtin_rejects_external_exchange(self):
        with patch.object(settings, "kms_oidc_provider", "builtin"):
            provider = build_oidc_provider()
            self.assertIsInstance(provider, BuiltinOIDCProvider)
            with self.assertRaises(HTTPException) as caught:
                provider.verify_id_token("any")
            self.assertEqual(caught.exception.status_code, 400)

    def test_external_requires_pyjwt(self):
        with patch.object(settings, "kms_oidc_provider", "external"):
            provider = build_oidc_provider()
            self.assertIsInstance(provider, ExternalOIDCProvider)
        with patch.dict(sys.modules, {"jwt": None}, clear=False):
            with self.assertRaises(RuntimeError):
                provider.verify_id_token("header.payload.sig")

    def test_unknown_provider_rejected(self):
        with patch.object(settings, "kms_oidc_provider", "saml"):
            with self.assertRaises(ValueError):
                build_oidc_provider()


class FakeStrategy:
    def __init__(self, data):
        self.name = "fake"
        self.data = data

    def score(self, user, seed_text, seed_doc_id):
        return dict(self.data)


def _row(doc_id, level, dept, status="published", approved=1, expired=False):
    return {
        "document_id": doc_id, "title": f"文档{doc_id}", "file_type": "pdf",
        "departments": [dept] if dept else [],
        "owner_org_path": "银联商务/风险控制部",
        "status": status, "lifecycle_state": status,
        "publication_approved": approved, "expired": expired, "classification": level,
    }


class RecommenderTests(unittest.TestCase):
    def setUp(self):
        self.user = AuthUser(dict(USER_ROW))

    def test_fusion_order_and_permission_filter(self):
        strategies = [
            ("organization", 1.0, FakeStrategy({1: 2.0, 3: 10.0})),
            ("popular", 1.0, FakeStrategy({2: 5.0, 1: 5.0})),
        ]
        rows = [_row(1, 0, "风险控制部"), _row(2, 2, "风险控制部"), _row(3, 3, "风险控制部")]
        with patch.object(rec, "_active_strategies", lambda: strategies), \
             patch.object(rec, "_load_rows", lambda ids: rows):
            items = rec.recommend(self.user, top_n=10)
        ids = [i.doc_id for i in items]
        # doc3 密级 3 > 用户等级 2 → 被硬过滤剔除；余下按融合分排序
        self.assertEqual(ids, [1, 2])
        self.assertGreater(items[0].score, items[1].score)
        self.assertIn("organization", items[0].reasons)

    def test_draft_candidate_excluded(self):
        strategies = [("popular", 1.0, FakeStrategy({4: 1.0}))]
        rows = [_row(4, 1, "风险控制部", status="draft")]
        with patch.object(rec, "_active_strategies", lambda: strategies), \
             patch.object(rec, "_load_rows", lambda ids: rows):
            items = rec.recommend(self.user, top_n=10)
        self.assertEqual(items, [])

    def test_empty_strategy_is_skipped(self):
        strategies = [
            ("collaborative", 1.0, FakeStrategy({})),   # 冷启动：空结果
            ("popular", 1.0, FakeStrategy({1: 3.0})),   # 兜底供给
        ]
        rows = [_row(1, 0, "风险控制部")]
        with patch.object(rec, "_active_strategies", lambda: strategies), \
             patch.object(rec, "_load_rows", lambda ids: rows):
            items = rec.recommend(self.user, top_n=10)
        self.assertEqual([i.doc_id for i in items], [1])
        self.assertEqual(items[0].reasons, ["popular"])

    def test_disabled_returns_empty(self):
        with patch.object(settings, "kms_rec_enabled", False):
            self.assertEqual(rec.recommend(self.user, top_n=10), [])


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.user = AuthUser(dict(USER_ROW))

    def test_record_answer_sources_dedups(self):
        cur = FakeCursor()
        with fake_db(cur):
            rec.record_answer_sources(self.user, "mid-1", [10, 10, 20])
        inserts = [c for c in cur.calls if c[0].startswith("INSERT INTO kms_rec_interactions")]
        self.assertEqual(len(inserts), 2)  # 去重后仅 2 条
        self.assertTrue(all(p[3] == "mid-1" and p[4] == "chat_source" for _, p in inserts))

    def test_feedback回溯并写入权重(self):
        cur = FakeCursor()
        cur.rows = [{"doc_id": 10}, {"doc_id": 20}]
        with fake_db(cur):
            self.assertEqual(rec.feedback_docs("mid-1"), [10, 20])
        self.assertIn("chat_source", cur.calls[0][0])

        cur2 = FakeCursor()
        cur2.rows = [{"doc_id": 10}]
        with fake_db(cur2):
            linked = rec.apply_feedback(self.user, "mid-1", "up")
        self.assertEqual(linked, 1)
        feedback_inserts = [c for c in cur2.calls if c[0].startswith("INSERT INTO kms_rec_interactions")]
        self.assertEqual(len(feedback_inserts), 1)
        self.assertEqual(feedback_inserts[0][1][4], "feedback")
        self.assertEqual(float(feedback_inserts[0][1][5]), rec.WEIGHT_FEEDBACK_UP)


if __name__ == "__main__":
    unittest.main()
