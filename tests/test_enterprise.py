"""离线安全回归：不连接数据库/模型/平台，不启动真实监听服务。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
from scripts.service import apply_environment, bind_socket, deployment_values

RUN = ROOT / "data" / "test-runs" / uuid.uuid4().hex
apply_environment(RUN / "absent.env", {
    "MYSQL_DATABASE": "offline_test_only", "KMS_SECRET_KEY": "offline-test-key-not-for-production-0123456789",
    "FAISS_INDEX_PATH": str(RUN / "faiss" / "index"), "UPLOAD_DIR": str(RUN / "uploads"),
    "DOCS_DIR": str(RUN / "docs"), "GW_AUDIT_DIR": str(RUN / "audit"),
    "GW_STATE_PATH": str(RUN / "state.sqlite3"), "GW_MODEL_EGRESS_ALLOWED": "0",
    "KMS_APPROVER_EMPLOYEES": "approver",
    "KMS_ADMIN_EMPLOYEES": "admin", "KMS_AUDITOR_EMPLOYEES": "auditor",
})

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from config import settings
from app.rag import Retriever
from app.store import MySQLStore, VectorStore
from gateway import crypto, identity, middleware, routes_bots, routes_embed, routes_kms, service, state
from kms import security
from run_kms import create_app

ROW = dict(id=1, employee_no="editor", username="测试员工", security_level=3, department="商户服务", is_active=True)
APP = dict(app_id="test-app", app_name="测试宿主", allowed_min_level=0, allowed_max_level=3, is_active=True)


def request(token=""):
    return Request({"type": "http", "method": "POST", "path": "/kms/api/chat", "headers":
                    [(b"authorization", ("Bearer " + token).encode())] if token else []})


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.block = patch.object(MySQLStore, "_get_pool", side_effect=AssertionError("离线测试禁止真实 MySQL"))
        self.block.start()
        self.addCleanup(self.block.stop)
        self.state_patch = patch.object(settings, "gw_state_path", RUN / (uuid.uuid4().hex + ".sqlite3"))
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        state.initialize()
        self.user = security.AuthUser(ROW)

    def assertHTTP(self, code, function, *args, **kwargs):
        with self.assertRaises(HTTPException) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status_code, code)


class CryptoTests(OfflineCase):
    def test_feishu_official_vector(self):
        # 飞书官方 Encrypt Key 文档给出的独立固定向量，不依赖本项目加密器。
        self.assertEqual(crypto.feishu_decrypt_text("P37w+VZImNgPEO1RBhJ6RtKl7n6zymIbEG1pReEzghk=", "test key"), "hello world")

    def test_feishu_rejects_invalid_ciphertext(self):
        for ciphertext in ("???", "YQ==", ""):
            with self.subTest(ciphertext=ciphertext), self.assertRaises(ValueError):
                crypto.feishu_decrypt_text(ciphertext, "key")

    def test_wecom_signature_recipient_and_xml(self):
        key = base64.b64encode(bytes(range(32))).decode().rstrip("=")
        c = crypto.WeComCrypto("test-token", key, "corp")
        encrypted = c.encrypt("中文消息")
        self.assertEqual(c.decrypt(encrypted), "中文消息")
        c.verify_signature(c.signature("123", "nonce", encrypted), "123", "nonce", encrypted)
        with self.assertRaises(ValueError):
            c.verify_signature("bad", "123", "nonce", encrypted)
        with self.assertRaises(ValueError):
            crypto.WeComCrypto("test-token", key, "other-corp").decrypt(encrypted)
        nonce = "x]]><injected/>"
        self.assertEqual(crypto.xml_field(c.reply_encrypted_xml("text", nonce), "Nonce"), nonce)
        self.assertIsNone(crypto.xml_field('<!DOCTYPE x [<!ENTITY y "z">]><xml/>', "x"))

    def test_timestamp_expiry(self):
        routes_bots.fresh(str(int(time.time())))
        for value in ("0", "not-time", None):
            self.assertHTTP(401, routes_bots.fresh, value)

    def test_identity_never_falls_back_to_anonymous(self):
        with patch.object(identity, "lookup_binding", return_value=None):
            self.assertHTTP(403, identity.resolve_bot_user, "feishu", "external")
        with patch.object(identity, "lookup_binding", return_value="editor"), patch.object(identity.acl, "get_user_by_employee_no", return_value=dict(ROW, is_active=False)):
            self.assertHTTP(403, identity.resolve_bot_user, "feishu", "external")


class PermissionTests(OfflineCase):
    def test_document_permission_matrix(self):
        good = dict(classification=2, publication_approved=1, status="published", lifecycle_state="published",
                    expired=False, departments=["商户服务"])
        self.assertTrue(service.allowed(good, self.user, 0, 3))
        for field, value in (("classification", None), ("classification", 4), ("publication_approved", 0),
                             ("status", "draft"), ("lifecycle_state", "archived"), ("expired", True),
                             ("departments", ["其他部门"])):
            with self.subTest(field=field, value=value):
                self.assertFalse(service.allowed(dict(good, **{field: value}), self.user, 0, 3))
        self.assertFalse(service.allowed(good, None, 0, 3))
        self.assertFalse(service.allowed(good, self.user, 3, 3))
        # 匿名读者（未登录）：只有「不限部门」的 L0 文档可读——
        # 密级只作职级上限，不再作为 L0 全员可见的短路条件。
        self.assertTrue(service.allowed(dict(good, classification=0, departments=["*"]), None, 0, 0))
        self.assertFalse(service.allowed(dict(good, classification=0), None, 0, 0))
        self.assertTrue(service.allowed(dict(good, departments=["其他部门", "商户服务"]), self.user, 0, 3))
        self.assertFalse(service.allowed(dict(good, departments="bad"), self.user, 0, 3))

    def test_allowed_org_inheritance(self):
        # 上级可见下级文档（部门不同但组织路径为祖先）
        parent = security.AuthUser(dict(ROW, department="风险控制部", org_path="银联商务/风险控制部"))
        child_row = dict(classification=2, publication_approved=1, status="published",
                         lifecycle_state="published", expired=False, departments=["风控策略组"],
                         owner_org_path="银联商务/风险控制部/风控策略组")
        self.assertTrue(service.allowed(child_row, parent, 0, 3))
        # 反向：下级不可见上级文档（继承单向）
        child = security.AuthUser(dict(ROW, department="风控策略组", org_path="银联商务/风险控制部/风控策略组"))
        parent_row = dict(child_row, departments=["风险控制部"],
                          owner_org_path="银联商务/风险控制部")
        self.assertFalse(service.allowed(parent_row, child, 0, 3))

    def test_documents_sql_includes_org_inheritance(self):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        with patch.object(MySQLStore, "_conn") as conn:
            conn.return_value.__enter__.return_value = cur
            result = service.documents(self.user, 0, 3, 0, 20)
        self.assertEqual(result["total"], 0)
        sql = cur.execute.call_args_list[0].args[0]
        self.assertIn("d.owner_org_path", sql)
        self.assertIn("LIKE CONCAT", sql)
        # SELECT 参数：新版 SQL 采用「新字段主判 + 旧字段兜底」双分支，
        # WHERE 占位 = minimum+maximum（2） + DOC_DEPT_UNLIMITED（1）
        #   + active+department 主判（2） + active 兜底门槛（1）
        #   + department+DOC_DEPT_UNLIMITED 旧主（2） + department 旧 extra（1）
        #   + org_path 非空+等值+LIKE（3） = 12；再加 limit + offset = 14。
        self.assertEqual(len(cur.execute.call_args_list[1].args[1]), 14)
        # 括号必须配平：这段谓词嵌套了 4 层 OR/AND，漏一个右括号时
        # 参数个数校验仍然通过（占位符没变），但 MySQL 报 1064，
        # 表现为整个 /documents 恒 503。
        self.assertEqual(sql.count("("), sql.count(")"))

    def test_documents_keyword_filters_on_server(self):
        """关键字必须进 SQL（全库过滤），不能只在前端当页 20 条里筛。

        现场反例：文档审批通过后落在列表末页（列表按 id 正序、每页 20），
        用户在首页搜索框里搜不到，表现得像「已通过却没入库」。
        """
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        with patch.object(MySQLStore, "_conn") as conn:
            conn.return_value.__enter__.return_value = cur
            service.documents(self.user, 0, 3, 0, 20, keyword="快手月付")
        count_sql, count_params = cur.execute.call_args_list[0].args
        self.assertIn("d.title LIKE %s OR d.filename LIKE %s", count_sql)
        # 可见性谓词 12 个 + 关键字 2 个
        self.assertEqual(len(count_params), 14)
        self.assertEqual(count_params[-2:], ("%快手月付%", "%快手月付%"))
        # 计数与取页必须用同一套谓词，否则会「总数 1、列表空」
        page_sql = cur.execute.call_args_list[1].args[0]
        self.assertIn("d.title LIKE %s", page_sql)

    def test_documents_keyword_escapes_like_wildcards(self):
        # 不转义时搜 "100%" 会退化成通配，命中几乎全部文档
        self.assertEqual(service._like_pattern("100%_"), "%100\\%\\_%")
        self.assertEqual(service._like_pattern("a\\b"), "%a\\\\b%")

    def test_documents_route_forwards_keyword(self):
        with patch.object(service, "documents", return_value={"items": [], "total": 0}) as mocked:
            routes_kms.documents(offset=0, limit=20, sort="asc", q=" 快手 ", user=self.user)
        self.assertEqual(mocked.call_args.kwargs["keyword"], " 快手 ")

    def test_approver_pool_requires_declared_departments(self):
        """未声明归属部门时**不得回落本人部门**，而是空池 + 提示。

        现场反例：用户选了财务管理部，却看到产品管理部的候选人——因为
        (1) 前端默认勾着本人部门，加选变成并集；(2) 后端在 depts 缺省时
        回落本人部门，替用户猜了一个错部门。
        """
        with patch.object(routes_kms.acl, "approver_candidates") as pool:
            out = routes_kms.approver_candidates(classification=3, departments="", user=self.user)
        pool.assert_not_called()
        self.assertEqual(out["items"], [])
        self.assertIn("归属部门", out["reason"])

    def test_approver_pool_follows_declared_departments_and_level(self):
        with patch.object(routes_kms.acl, "approver_candidates", return_value=[]) as pool, \
                patch.object(routes_kms, "_dept_max_levels", return_value={"财务管理部": 2}):
            out = routes_kms.approver_candidates(
                classification=3,
                departments=json.dumps(["财务管理部"], ensure_ascii=False),
                user=self.user)
        # 交给单一事实源的是**申请人声明的部门**，不是本人部门（商户服务部）
        self.assertEqual(pool.call_args.args[:2], (3, ["财务管理部"]))
        # 空池时必须解释「该部门没人够职级」，而不是笼统一句无候选
        self.assertIn("财务管理部（最高 L2）", out["reason"])
        self.assertIn("L3", out["reason"])

    def test_upload_rejects_missing_departments(self):
        """两个入库入口都不再替用户猜部门。"""
        for name in ("routes_kms.py", "routes_upload.py"):
            src = (ROOT / "gateway" / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotIn("= [user.department] if user.department else []", src)
                self.assertNotIn("= [d for d in [user.department or \"\"] if d]", src)
                self.assertIn("请选择归属部门", src)

    def test_upload_pool_is_scoped_to_selected_departments(self):
        """上传区的候选池只含所选归属部门的人，且不得默认预选本人部门。

        现场反例：上传区默认勾着本人（产品管理部），用户再加选财务管理部→
        变成并集，审批人下拉框里全是产品管理部的人，用户以为系统没按他选的
        部门匹配。候选池 = 所选部门 ∩ 职级≥密级 − 本人，人数不限。
        """
        src = (ROOT / "frontend" / "src" / "app" / "views" / "DocumentsView.vue").read_text(encoding="utf-8")
        self.assertIn("const upDepts = ref([])", src)
        self.assertNotIn("[state.user.department]", src)
        self.assertIn("wanted.has(deptKey(a.department))", src)

    def test_application_clearance_is_intersection(self):
        user = security.AuthUser(dict(ROW, security_level=1))
        self.assertEqual(routes_embed.ApplicationContext(APP, user).maximum, 1)
        self.assertEqual(routes_embed.ApplicationContext(APP, None).maximum, 0)

    def test_governance_has_no_clearance_or_owner_bypass(self):
        self.assertHTTP(403, routes_kms.auditor, self.user)
        self.assertFalse(routes_kms.manageable(dict(classification=3, departments=[]), self.user))
        self.assertFalse(routes_kms.manageable(dict(classification=3, departments=["其他部门"]), self.user))
        self.assertFalse(routes_kms.manageable(dict(classification=3, departments=["商户服务"]), security.AuthUser(dict(ROW, security_level=1))))
        self.assertTrue(routes_kms.manageable(dict(classification=None, departments=["商户服务"]), self.user))

    def test_policy_list_filters_before_limit(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        with patch.object(MySQLStore, "transaction") as tx:
            tx.return_value.__enter__.return_value = cur
            # user 用关键字传：端点新增 status 查询参数（首参），位置传参会错位
            self.assertEqual(routes_kms.requests(user=self.user), {"items": []})
        sql, params = cur.execute.call_args.args
        # 密级按请求目标密级（policy.classification）过滤，非文档当前密级
        self.assertIn("$.classification", sql)
        self.assertIn("$.departments", sql)
        # 可见范围分两档：申请人无条件可见自己发起的（即使跨部门申请），
        # 审批人须通过部门 + 目标密级双重校验才可见指派给自己的单。
        # 因此 SQL 中 requested_by 与 approver_id 都出现，但 approver_id
        # 被嵌在带 BLP 判定的括号分支内。
        self.assertIn("p.requested_by=%s", sql)
        self.assertIn("p.approver_id=%s", sql)
        self.assertIn("JSON_CONTAINS(JSON_EXTRACT(p.policy,'$.departments')", sql)
        self.assertEqual(
            params,
            (self.user.id, self.user.id,
             self.user.department, routes_kms.DOC_DEPT_UNLIMITED,
             self.user.security_level),
        )

    def test_prohibition_of_self_approval_and_snapshot_conflict(self):
        policy = dict(classification=2, departments=["商户服务"], status="published", reason="经复核允许发布")
        row = dict(document_id=1, classification=3, departments=["商户服务"], expired=False)
        approver = security.AuthUser(dict(ROW, id=2, employee_no="approver"))
        # approver_id=2 表示该单已指派给 approver（其在 ROW 基础上 id=2）；
        # 缺此字段时 decide() 会以 409 明确拒绝「历史未指派单据」。
        for author_id, snap, expected in ((2, "unused", 403), (1, "stale", 409)):
            cur = MagicMock()
            cur.fetchone.side_effect = [dict(document_id=1),
                                        dict(requested_by=author_id, approver_id=2,
                                             status="pending", policy=policy, snapshot=snap),
                                        ROW]
            with patch.object(MySQLStore, "transaction") as tx, patch.object(routes_kms, "document_row", return_value=row):
                tx.return_value.__enter__.return_value = cur
                self.assertHTTP(expected, routes_kms.decide, "id", routes_kms.Decision(approve=True), approver)
                self.assertFalse(any(call.args[0].lstrip().startswith("UPDATE") for call in cur.execute.call_args_list))

    def test_decision_only_by_assigned_approver(self):
        """审批权来自「这单被指派给谁」，而不是任何够格的人都能批。

        随机指派的意义就是让选择不可被规避：若同部门且职级够的人都能审批，
        指派就形同虚设，随机也就没有意义了。
        """
        policy = dict(classification=2, departments=["商户服务"], status="published", reason="经复核允许发布")
        row = dict(document_id=1, classification=2, departments=["商户服务"], expired=False)
        approver = security.AuthUser(dict(ROW, id=2, employee_no="approver"))
        cases = [
            (None, 409),   # 历史单据没有指派信息 → 明确要求重新发起
            (99, 403),     # 指派给了别人 → 不得审批
        ]
        for approver_id, expected in cases:
            cur = MagicMock()
            item = dict(requested_by=1, status="pending", policy=policy, snapshot="x")
            if approver_id is not None:
                item["approver_id"] = approver_id
            cur.fetchone.side_effect = [dict(document_id=1), item, ROW]
            with patch.object(MySQLStore, "transaction") as tx, patch.object(routes_kms, "document_row", return_value=row):
                tx.return_value.__enter__.return_value = cur
                self.assertHTTP(expected, routes_kms.decide, "id",
                                routes_kms.Decision(approve=True), approver)
                self.assertFalse(any(call.args[0].lstrip().startswith("UPDATE")
                                     for call in cur.execute.call_args_list))

    def test_rerank_receives_only_authorized_text(self):
        r = Retriever.__new__(Retriever)
        r.embedder, r.vector_store, r.bm25_store, r.chunk_cache, r.reranker = [MagicMock() for _ in range(5)]
        r.embedder.embed_one.return_value = [1.0, 0.0]
        r.vector_store.search.return_value = [dict(faiss_id=1, score=1), dict(faiss_id=2, score=.9)]
        r.bm25_store.total = 0
        r.chunk_cache.get_by_faiss_ids.return_value = [dict(faiss_id=1, text="已授权", document_id=1), dict(faiss_id=2, text="未授权", document_id=2)]
        r.reranker.rerank.return_value = [dict(index=0, relevance_score=1)]
        with patch.object(settings, "enable_rerank", True):
            result = r.retrieve("问题", context_filter=lambda chunks: chunks[:1])
            self.assertEqual(r.reranker.rerank.call_args.args[1], ["已授权"])
            self.assertEqual(result[0]["faiss_id"], 1)
            r.reranker.reset_mock()
            self.assertEqual(r.retrieve("问题", context_filter=lambda _: []), [])
            r.reranker.rerank.assert_not_called()
            r.retrieve("问题")
            self.assertEqual(r.reranker.rerank.call_args.args[1], ["已授权", "未授权"])

    def test_model_egress_default_closed(self):
        self.assertHTTP(503, service.answer, "问题", self.user)


class ApplicationGovernanceTests(OfflineCase):
    def _tx(self, cur):
        patcher = patch.object(MySQLStore, "transaction")
        tx = patcher.start()
        tx.return_value.__enter__.return_value = cur
        self.addCleanup(patcher.stop)

    def test_create_application_is_atomic_and_audited(self):
        admin = security.AuthUser(dict(ROW, employee_no="admin"))
        cur = MagicMock()
        self._tx(cur)
        http = request()
        payload = routes_kms.Application(app_name="宿主", allowed_min_level=0, allowed_max_level=2, is_active=False)
        result = routes_kms.create_application(payload, http, admin)
        self.assertTrue(result["api_key"].startswith("sk-"))
        self.assertTrue(http.state.audit_target.startswith("application:"))
        inserts = [c for c in cur.execute.call_args_list if c.args[0].lstrip().upper().startswith("INSERT")]
        self.assertEqual(len(inserts), 1)
        self.assertIs(inserts[0].args[1][5], False)  # is_active 随创建同事务落库，不再二次 UPDATE。
        self.assertFalse(any(c.args[0].lstrip().upper().startswith("UPDATE") for c in cur.execute.call_args_list))

    def test_create_application_cannot_exceed_admin_clearance(self):
        admin = security.AuthUser(dict(ROW, employee_no="admin", security_level=1))
        payload = routes_kms.Application(app_name="宿主", allowed_min_level=0, allowed_max_level=2)
        self.assertHTTP(422, routes_kms.create_application, payload, request(), admin)

    def test_rotate_key_missing_or_over_clearance(self):
        cur = MagicMock()
        self._tx(cur)
        cur.fetchone.return_value = None
        self.assertHTTP(404, routes_kms.rotate_application, "missing", security.AuthUser(dict(ROW, employee_no="admin")))
        cur.reset_mock()
        cur.fetchone.return_value = {"allowed_max_level": 3}
        self.assertHTTP(403, routes_kms.rotate_application, "high", security.AuthUser(dict(ROW, employee_no="admin", security_level=1)))
        self.assertFalse(any(c.args[0].lstrip().upper().startswith("UPDATE") for c in cur.execute.call_args_list))


class StateTests(OfflineCase):
    def test_receipt_owner(self):
        mid = state.receipt("app1:1")
        self.assertFalse(state.feedback("app2:1", mid, "up", ""))
        self.assertFalse(state.feedback("app1:2", mid, "up", ""))
        self.assertTrue(state.feedback("app1:1", mid, "up", ""))

    def test_dedup_retry_and_scrubbing(self):
        self.assertTrue(state.enqueue("feishu", "event", {"question": "测试"}, "request"))
        self.assertFalse(state.enqueue("feishu", "event", {}, "other"))
        for attempt in range(1, 4):
            with state.connection() as db:
                db.execute("UPDATE jobs SET available_at=0")
            job = state.claim()
            self.assertEqual(job["attempts"], attempt)
            state.finish(job, False)
        self.assertIsNone(state.claim())
        with state.connection() as db:
            row = db.execute("SELECT * FROM jobs").fetchone()
            self.assertEqual((row["status"], row["payload"]), ("failed", "{}"))

    def test_crashed_lease_stops_after_three_attempts(self):
        state.enqueue("wecom", "event", {}, "request")
        with state.connection() as db:
            db.execute("UPDATE jobs SET status='running',attempts=3,available_at=0")
        self.assertIsNone(state.claim())

    def test_token_claims_and_revocation(self):
        token = security.create_token(1, "editor", 3, "商户服务")
        # 创建会话记录（严格绑定人员）
        from gateway.state import create_session
        payload_b64 = token.split(".")[1]
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        payload = json.loads(payload_json)
        create_session(1, "editor", payload["jti"], float(payload["exp"]))
        
        decoded = security.decode_token(token)
        self.assertIsNotNone(decoded)
        for changes in ({"iss": "other"}, {"aud": "other"}, {"exp": 1}, {"iat": float("nan")}, {"exp": float("inf")}, {"jti": ""}):
            self.assertIsNone(security.decode_token(security._sign(dict(decoded, **changes))))
        state.revoke_token(decoded["jti"], decoded["exp"])
        self.assertIsNone(security.decode_token(token))
        token = security.create_token(1, "editor", 3, "商户服务")
        payload_b64 = token.split(".")[1]
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        payload = json.loads(payload_json)
        create_session(1, "editor", payload["jti"], float(payload["exp"]))
        state.revoke_user(1)
        self.assertIsNone(security.decode_token(token))
        token = security.create_token(1, "editor", 3, "商户服务")
        payload_b64 = token.split(".")[1]
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        payload = json.loads(payload_json)
        create_session(1, "editor", payload["jti"], float(payload["exp"]))
        self.assertIsNotNone(security.decode_token(token))

    def test_long_request_rechecks_token(self):
        token = security.create_token(1, "editor", 3, "商户服务")
        # 创建会话记录（严格绑定人员）
        from gateway.state import create_session
        payload_b64 = token.split(".")[1]
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        payload = json.loads(payload_json)
        create_session(1, "editor", payload["jti"], float(payload["exp"]))
        
        with patch.object(identity.acl, "get_user_by_id", return_value=ROW):
            security.revalidate_bearer(request(token), self.user)
            state.revoke_user(1)
            self.assertHTTP(401, security.revalidate_bearer, request(token), self.user)


class BoundaryTests(OfflineCase):
    def setUp(self):
        super().setUp()
        # 限流已下沉到共享存储（kms/ratelimit）；离线测试用桩替代，避免真实 DB 访问。
        # 打 check （策略层入口）而非 allow，可覆盖全部端点的限流调用。
        self.enterContext(patch.object(middleware.ratelimit, "check", return_value=True))
        self.audit = self.enterContext(patch.object(middleware, "log_gw_event"))
        self.enterContext(patch.object(identity.acl, "get_user_by_id", return_value=ROW))
        self.app_lookup = self.enterContext(patch.object(routes_embed, "get_app_by_key", side_effect=lambda key: dict(APP) if key == "valid" else None))
        self.answer = self.enterContext(patch.object(service, "answer", return_value={"answer": "受控答案", "sources": []}))
        self.client = TestClient(create_app())  # 不进入真实 lifespan。
        self.addCleanup(self.client.close)
        self.token = security.create_token(1, "editor", 3, "商户服务")
        # 创建会话记录（严格绑定人员）
        from gateway.state import create_session
        payload_b64 = self.token.split(".")[1]
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        payload = json.loads(payload_json)
        create_session(1, "editor", payload["jti"], float(payload["exp"]))
        self.headers = {"X-API-Key": "valid", "Authorization": "Bearer " + self.token}
        self.url = "/gw/api/v1/embed/chat"

    def test_authenticated_chat_and_forbidden_history_fields(self):
        result = self.client.post(self.url, headers=self.headers, json={"question": "问题"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["data"]["answer"], "受控答案")
        for field in ("session_id", "use_history", "end_user"):
            result = self.client.post(self.url, headers=self.headers, json={"question": "问题", field: "forbidden"})
            self.assertEqual(result.status_code, 422)
            self.assertEqual(result.json()["request_id"], result.headers["X-Request-ID"])

    def test_invalid_disabled_and_missing_keys(self):
        for headers in ({}, {"X-API-Key": "bad"}):
            self.assertEqual(self.client.post(self.url, headers=headers, json={"question": "问题"}).status_code, 401)
        self.app_lookup.side_effect = None
        self.app_lookup.return_value = dict(APP, is_active=False)
        self.assertEqual(self.client.post(self.url, headers=self.headers, json={"question": "问题"}).status_code, 403)
        self.answer.assert_not_called()

    def test_audit_start_failure_blocks_business(self):
        self.audit.side_effect = OSError("disk full")
        self.assertEqual(self.client.post(self.url, headers=self.headers, json={"question": "问题"}).status_code, 503)
        self.answer.assert_not_called()

    def test_audit_finish_failure_withholds_answer(self):
        self.audit.side_effect = [None, OSError("disk full")]
        result = self.client.post(self.url, headers=self.headers, json={"question": "问题"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("受控答案", result.text)
        self.answer.assert_called_once()

    def test_body_limit_unknown_route_and_rate_limit(self):
        result = self.client.post(self.url, headers=self.headers, content=b"x" * 65537)
        self.assertEqual(result.status_code, 413)
        self.assertEqual(self.client.get("/gw/api/v1/absent").status_code, 404)
        with patch.object(middleware.ratelimit, "check", return_value=False):
            result = self.client.get("/gw/api/v1/absent")
            self.assertEqual(result.status_code, 429)
            self.assertEqual(result.headers["Retry-After"], "60")
        self.answer.assert_not_called()

    def test_old_routes_and_hr_write_are_absent(self):
        paths = self.client.app.openapi()["paths"]
        # 注：/kms/api/tickets 已从「禁止挂载的旧接口」列表中移除——工单中心已按
        # 企业级重新实现（gateway/routes_tickets.py，审批按职责匹配、无管理员）。
        # 原本"不允许挂载"的顾虑是绕开授权，现由 test_ticket_routes_require_bearer
        # 用更强的断言守住：端点可以存在，但必须全部带鉴权。
        for path in ("/chat", "/kms/api/chat/stream", "/kms/api/admin/hr-sync"):
            self.assertNotIn(path, paths)
        self.assertEqual(self.client.post("/chat", json={"question": "问题"}).status_code, 404)
        self.assertEqual(self.client.get("/kms/api/admin/openapi.json", headers=self.headers).status_code, 403)

    def test_ticket_routes_require_bearer(self):
        """工单/通知端点必须全部带鉴权声明。

        工单中心不再靠「不挂载」来防绕过，而是靠「挂载了也必须认证」——
        既满足业务需求（每个员工都能发起工单），又不放宽边界。
        """
        paths = self.client.app.openapi()["paths"]
        guarded = [p for p in paths
                   if p.startswith("/kms/api/tickets") or p.startswith("/kms/api/notifications")]
        self.assertTrue(guarded, "工单/通知端点应已挂载")
        for p in guarded:
            for method, spec in paths[p].items():
                self.assertTrue(spec.get("security"),
                                f"{method.upper()} {p} 缺少鉴权声明")

    def test_qa_evaluation_contract_remains_separate(self):
        from app import api
        app = FastAPI()
        app.include_router(api.router)
        retriever = MagicMock()
        retriever.answer.return_value = {"answer": "评测答案"}
        with patch.object(api, "get_retriever", return_value=retriever), TestClient(app) as client:
            for kwargs in ({"json": {"question": "问题"}}, {"data": {"question": "问题"}}, {"params": {"question": "问题"}}):
                result = client.post("/chat", **kwargs)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json(), {"answer": "评测答案"})

    def test_bff_rejections_are_audited_and_key_not_in_page(self):
        from examples import embed_bff
        with patch.object(embed_bff, "audit_event") as audit, TestClient(embed_bff.app) as client:
            result = client.post("/api/chat", json={"question": "问题"})
            self.assertEqual(result.status_code, 401)
            self.assertEqual(audit.call_count, 2)
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            self.assertNotIn("EMBED_API_KEY", client.get("/").text)
            self.assertEqual(client.get("/widget.js").status_code, 200)
            audit.side_effect = OSError("full")
            self.assertEqual(client.post("/api/chat").status_code, 503)

    def test_wecom_callback_valid_dedup_wrong_agent_and_recipient(self):
        key = base64.b64encode(bytes(range(32))).decode().rstrip("=")
        values = dict(wecom_token="token", wecom_encoding_aes_key=key, wecom_corp_id="corp", wecom_secret="secret", wecom_agent_id="7")
        with patch.multiple(settings, **values), patch.object(routes_bots, "resolve_bot_user", return_value=self.user):
            c = routes_bots.wecom_crypto()
            for agent, sender, expected in (("7", "member", 200), ("8", "member", 403), ("7", "@all", 400), ("7", "a|b", 400)):
                plain = f"<xml><ToUserName>corp</ToUserName><AgentID>{agent}</AgentID><FromUserName>{sender}</FromUserName><MsgType>text</MsgType><MsgId>1</MsgId><Content>问题</Content></xml>"
                encrypted, timestamp = c.encrypt(plain), str(int(time.time()))
                params = dict(timestamp=timestamp, nonce="nonce", msg_signature=c.signature(timestamp, "nonce", encrypted))
                for _ in range(2):
                    result = self.client.post("/gw/api/v1/bots/wecom/callback", params=params, content=f"<xml><Encrypt>{encrypted}</Encrypt></xml>")
                    self.assertEqual(result.status_code, expected)
            with state.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_feishu_signed_event_enqueues_only_valid_p2p(self):
        values = dict(feishu_app_id="app", feishu_app_secret="secret", feishu_verification_token="verify", feishu_encrypt_key="key")
        body = dict(header=dict(token="verify", app_id="app", event_type="im.message.receive_v1"), event=dict(
            message=dict(chat_type="p2p", message_type="text", message_id="msg1", content=json.dumps({"text": "问题"})),
            sender=dict(sender_type="user", sender_id=dict(open_id="open1"))))
        raw = b'{"encrypt":"mock-for-signature-test"}'
        timestamp = str(int(time.time()))
        headers = {"X-Lark-Request-Timestamp": timestamp, "X-Lark-Request-Nonce": "nonce",
                   "X-Lark-Signature": hashlib.sha256((timestamp + "noncekey").encode() + raw).hexdigest()}
        with patch.multiple(settings, **values), patch.object(routes_bots, "feishu_decrypt", return_value=body), patch.object(routes_bots, "resolve_bot_user", return_value=self.user):
            url = "/gw/api/v1/bots/feishu/callback"
            self.assertEqual(self.client.post(url, content=raw, headers=headers).status_code, 200)
            self.assertEqual(self.client.post(url, content=raw, headers=dict(headers, **{"X-Lark-Signature": "bad"})).status_code, 401)
            body["event"]["message"]["chat_type"] = "group"
            self.assertEqual(self.client.post(url, content=raw, headers=headers).status_code, 403)


class DeploymentTests(OfflineCase):
    def test_environment_does_not_inherit_enterprise_secrets_or_paths(self):
        with patch.dict(os.environ, {"GW_MODEL_EGRESS_ALLOWED": "1", "MYSQL_PASSWORD": "parent", "DOCS_DIR": "parent"}):
            apply_environment(RUN / "test.env", {"MYSQL_DATABASE": "child"})
            self.assertNotIn("MYSQL_PASSWORD", os.environ)
            self.assertNotIn("GW_MODEL_EGRESS_ALLOWED", os.environ)
            self.assertNotIn("DOCS_DIR", os.environ)
            self.assertEqual(os.environ["MYSQL_DATABASE"], "child")

    def test_data_isolation_including_cross_kind_paths(self):
        qa = dict(MYSQL_DATABASE="qa", FAISS_INDEX_PATH="data/qa/index", UPLOAD_DIR="data/qa/uploads", DOCS_DIR="data/qa/docs")
        kms = dict(MYSQL_DATABASE="kms", FAISS_INDEX_PATH="data/kms/index", UPLOAD_DIR="data/kms/uploads", DOCS_DIR="data/kms/docs")
        with patch("scripts.service.load_values", side_effect=[qa, kms]):
            deployment_values("qa", "kms")
        for change in ({"MYSQL_DATABASE": "qa"}, {"DOCS_DIR": "data/qa/uploads"}, {"KMS_PORT": "6341"}):
            with patch("scripts.service.load_values", side_effect=[qa, dict(kms, **change)]), self.assertRaises(ValueError):
                deployment_values("qa", "kms")

    def test_ports_are_fixed_and_conflict_does_not_retry(self):
        for role, port in (("qa", 6342), ("kms", 6341), ("kms", 6351), ("other", 6343)):
            with self.assertRaises(ValueError):
                bind_socket(role, "127.0.0.1", port)
        with patch("scripts.service.socket.socket") as factory:
            sock = factory.return_value
            sock.bind.side_effect = OSError("occupied")
            with self.assertRaises(OSError):
                bind_socket("qa", "127.0.0.1", 6341)
            sock.bind.assert_called_once_with(("127.0.0.1", 6341))
            sock.close.assert_called_once()

    def test_faiss_reload_does_not_reuse_live_id(self):
        with patch.object(settings, "faiss_index_path", RUN / uuid.uuid4().hex):
            v = VectorStore(dim=2)
            v.add([[1, 0], [0, 1], [1, 1]])
            v.remove([1])
            v.save()
            loaded = VectorStore(dim=2)
            loaded.load()
            self.assertEqual(loaded.ids(), [0, 2])
            self.assertEqual(loaded.add([[1, 0]]), [3])

    def test_same_count_different_ids_or_orphan_document_rejected(self):
        for rows in ([dict(faiss_id=2, document_id=1)], [dict(faiss_id=1, document_id=None)]):
            r = Retriever.__new__(Retriever)
            r.vector_store, r.mysql, r.chunk_cache = MagicMock(), MagicMock(), MagicMock()
            r.vector_store.ids.return_value = [1]
            r.mysql._conn.return_value.__enter__.return_value.fetchall.return_value = rows
            with self.assertRaises(RuntimeError):
                r.warmup()
            r.chunk_cache.load.assert_not_called()

    def test_release_allowlist_excludes_runtime_and_credentials(self):
        from scripts.package_release import release_files
        files = [p.relative_to(ROOT).as_posix() for p in release_files()]
        self.assertIn(".env.kms.example", files)
        self.assertIn("gateway/routes_kms.py", files)
        self.assertNotIn(".env", files)
        self.assertNotIn(".env.kms", files)
        for name in files:
            self.assertFalse(name.startswith(("data/", "venv/", "RAG_repository/", ".workbuddy/")))

    def test_transaction_commit_and_rollback(self):
        for fail in (False, True):
            store = MySQLStore()
            connection = MagicMock()
            with patch.object(store, "_get_pool") as pool:
                pool.return_value.connection.return_value = connection
                try:
                    with store.transaction():
                        if fail:
                            raise ValueError("rollback")
                except ValueError:
                    pass
            connection.begin.assert_called_once()
            connection.close.assert_called_once()
            (connection.rollback if fail else connection.commit).assert_called_once()
            (connection.commit if fail else connection.rollback).assert_not_called()


if __name__ == "__main__":
    unittest.main()
