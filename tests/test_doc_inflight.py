"""文档在途业务悲观锁（gateway/doc_inflight.py）的离线契约。

要守住的语义：
  1. 同一篇文档同时只允许一张待审批单——**跨两条链路**（工单的删除/恢复
     与文档库的变更/回滚申请共用一张“在途席位”）；
  2. 席位由 `kms_doc_locks` 的唯一主键**原子**抢占（INSERT IGNORE），
     不是「先查有没有、再插入」；
  3. 单据办结（通过/驳回/撤回/超时）必须释放锁行，否则文档被永久占位；
  4. 判定必须先锁文档行、再对锁表与在途单据做加锁读，绕开 RR 快照；
  5. 冲突描述必须说清「哪张单、谁发起」，否则申请人不知道该找谁催。
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class _Cur:
    """按 SQL 内容路由结果的假游标。

    不用「按调用顺序回放结果集」那种写法：锁表上线后同一条链路上会有
    DELETE（清过期租约）+ SELECT（读锁行）交替，按序号回放极易假通过。
    """

    def __init__(self, documents=(), locks=(), tickets=(), policies=(), taken=()):
        self.documents = list(documents)
        self.locks = list(locks)
        self.tickets = list(tickets)
        self.policies = list(policies)
        self.taken = set(taken)            # 已被别人占座的 document_id
        self.statements = []
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.statements.append((s, params))
        self._rows = []
        self.rowcount = 1
        if s.startswith("INSERT IGNORE"):
            doc_id = params[0]
            if doc_id in self.taken:
                self.rowcount = 0          # 撞主键 = 席位已被占用
            else:
                self.taken.add(doc_id)
        elif "FROM kms_doc_locks" in s:
            wanted = {int(x) for x in (params or ()) if str(x).isdigit()}
            self._rows = [r for r in self.locks if int(r["document_id"]) in wanted]
        elif "FROM kms_tickets" in s:
            self._rows = list(self.tickets)
        elif "FROM kms_policy_requests" in s:
            self._rows = list(self.policies)
        elif "FROM documents" in s:
            self._rows = list(self.documents)
        return self.rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def sqls(self):
        return [s for s, _ in self.statements]


class TicketSideTests(unittest.TestCase):
    def test_second_delete_ticket_reports_holder(self):
        from gateway import doc_inflight
        cur = _Cur(
            documents=[{"id": 3, "filename": "快手月付.txt"}],
            tickets=[{"ticket_no": "T20261025A4F0881B", "module": "doc_batch_delete",
                      "applicant_name": "张明远",
                      "payload": json.dumps({"doc_ids": ["3"]})}],
        )
        msg = doc_inflight.find_inflight_conflict(cur, [3])
        self.assertIn("T20261025A4F0881B", msg)
        self.assertIn("张明远", msg)
        self.assertIn("删除工单", msg)
        self.assertIn("快手月付.txt", msg)

    def test_other_document_does_not_block(self):
        from gateway import doc_inflight
        cur = _Cur(
            documents=[{"id": 9, "filename": "别的.txt"}],
            tickets=[{"ticket_no": "T1", "module": "doc_batch_delete",
                      "applicant_name": "张明远",
                      "payload": json.dumps({"doc_ids": ["9"]})}],
        )
        self.assertEqual(doc_inflight.find_inflight_conflict(cur, [3]), "")


class CrossChannelTests(unittest.TestCase):
    """工单在途时，变更/回滚申请必须被同一道闸门挡住（反之亦然）。"""

    def test_policy_request_blocks_when_no_ticket(self):
        from gateway import doc_inflight
        cur = _Cur(
            documents=[{"id": 3, "filename": "快手月付.txt"}],
            policies=[{"id": "abc", "document_id": 3,
                       "created_at": "2026-10-25 14:41:35", "action": "rollback",
                       "req_name": "赵明远", "appr_name": "宁宁"}],
        )
        msg = doc_inflight.find_inflight_conflict(cur, [3])
        self.assertIn("版本回滚申请", msg)
        self.assertIn("赵明远", msg)
        self.assertIn("宁宁", msg)
        self.assertIn("快手月付.txt", msg)

    def test_unknown_action_falls_back_to_change_request(self):
        from gateway import doc_inflight
        cur = _Cur(policies=[{"document_id": 3, "action": None,
                              "req_name": "赵明远"}])
        self.assertIn("变更申请", doc_inflight.find_inflight_conflict(cur, [3]))

    def test_lock_row_wins_over_scanner(self):
        """锁表是权威判据：锁行在，就必须先报锁行（哪怕单据表还没扫）。"""
        from gateway import doc_inflight
        cur = _Cur(
            documents=[{"id": 3, "filename": "快手月付.txt"}],
            locks=[{"document_id": 3, "action_label": "新版本上传审批",
                    "ref_no": "", "owner_name": "李思琪"}],
        )
        msg = doc_inflight.find_inflight_conflict(cur, [3])
        self.assertIn("新版本上传审批", msg)
        self.assertIn("李思琪", msg)
        # 锁行命中后不必再扫两张单据表
        self.assertFalse(any("kms_tickets" in s for s in cur.sqls()))

    def test_guard_locks_documents_first_then_lock_table_then_both(self):
        from gateway import doc_inflight
        cur = _Cur(documents=[{"id": 3, "filename": "a.txt"}])
        doc_inflight.find_inflight_conflict(cur, [3])
        sqls = cur.sqls()
        self.assertIn("FROM documents", sqls[0])
        self.assertIn("FOR UPDATE", sqls[0])       # 先锁文档行，串行化同一文档建单
        # 清过期租约 → 读锁表 → 扫工单 → 扫变更申请
        self.assertIn("DELETE FROM kms_doc_locks", sqls[1])
        self.assertIn("FROM kms_doc_locks", sqls[2])
        self.assertIn("FOR UPDATE", sqls[2])
        self.assertIn("kms_tickets", sqls[3])
        self.assertIn("FOR UPDATE", sqls[3])       # 加锁读，绕开 RR 快照
        self.assertIn("kms_policy_requests", sqls[4])
        self.assertIn("FOR UPDATE", sqls[4])
        self.assertEqual(cur.statements[3][1][0], "pending")

    def test_ids_are_normalised_and_deduplicated(self):
        from gateway import doc_inflight
        cur = _Cur()
        doc_inflight.find_inflight_conflict(cur, ["3", 3, "bad", None])
        self.assertEqual(cur.statements[0][1], (3,))

    def test_no_ids_short_circuits_without_sql(self):
        from gateway import doc_inflight
        cur = _Cur()
        self.assertEqual(doc_inflight.find_inflight_conflict(cur, []), "")
        self.assertEqual(cur.statements, [])


class AcquireReleaseTests(unittest.TestCase):
    """业务悲观锁本体：INSERT IGNORE 原子抢座 + 显式释放。"""

    def test_acquire_inserts_lock_row(self):
        from gateway import doc_inflight
        cur = _Cur(documents=[{"id": 3, "filename": "a.txt"}])
        conflict = doc_inflight.acquire(
            cur, [3], ref_type=doc_inflight.REF_POLICY, ref_id="rid1",
            ref_no="R1", action_label="版本回滚申请", owner_id=7,
            owner_name="赵明远", expires_at=doc_inflight.lease_deadline())
        self.assertEqual(conflict, "")
        ins = [p for s, p in cur.statements if s.startswith("INSERT IGNORE")]
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0][0], 3)
        self.assertEqual(ins[0][2], doc_inflight.REF_POLICY)
        self.assertEqual(ins[0][3], "rid1")
        # 抢座前必须先锁文档行（批量建单顺序一致，避免交叉持锁）
        self.assertIn("FOR UPDATE", cur.sqls()[0])

    def test_acquire_reports_holder_when_taken(self):
        from gateway import doc_inflight
        cur = _Cur(
            documents=[{"id": 3, "filename": "快手月付.txt"}],
            locks=[{"document_id": 3, "action_label": "删除工单",
                    "ref_no": "T20261025A4F0881B", "owner_name": "张明远"}],
            taken={3},
        )
        conflict = doc_inflight.acquire(
            cur, [3], ref_type=doc_inflight.REF_POLICY, ref_id="rid2",
            action_label="变更申请", owner_id=8, owner_name="李思琪",
            expires_at=doc_inflight.lease_deadline())
        self.assertIn("删除工单", conflict)
        self.assertIn("T20261025A4F0881B", conflict)
        self.assertIn("张明远", conflict)
        # 冲突描述由调用方补尾巴：这里只给「谁占着」
        self.assertNotIn(doc_inflight.CONFLICT_TAIL, conflict)

    def test_acquire_batch_is_all_or_nothing(self):
        """批量抢座：任一篇被占就要报出来，由调用方整事务回滚。"""
        from gateway import doc_inflight
        cur = _Cur(
            documents=[{"id": 3, "filename": "a.txt"}, {"id": 4, "filename": "b.txt"}],
            locks=[{"document_id": 4, "action_label": "恢复工单",
                    "ref_no": "T9", "owner_name": "宁宁"}],
            taken={4},
        )
        conflict = doc_inflight.acquire(
            cur, [3, 4], ref_type=doc_inflight.REF_TICKET, ref_id=11,
            action_label="删除工单", expires_at=doc_inflight.lease_deadline())
        self.assertIn("恢复工单", conflict)
        self.assertIn("b.txt", conflict)

    def test_release_deletes_by_ref(self):
        from gateway import doc_inflight
        cur = _Cur()
        doc_inflight.release(cur, ref_type=doc_inflight.REF_TICKET, ref_id=11)
        sql, params = cur.statements[0]
        self.assertIn("DELETE FROM kms_doc_locks", sql)
        self.assertIn("ref_type=%s AND ref_id=%s", sql)
        self.assertEqual(params, (doc_inflight.REF_TICKET, "11"))

    def test_release_many_skips_empty(self):
        from gateway import doc_inflight
        cur = _Cur()
        doc_inflight.release_many(cur, ref_type=doc_inflight.REF_TICKET, ref_ids=[])
        self.assertEqual(cur.statements, [])

    def test_lease_deadline_is_future(self):
        from datetime import datetime
        from gateway import doc_inflight
        self.assertGreater(doc_inflight.lease_deadline(), datetime.now())

    def test_action_labels_are_human_readable(self):
        from gateway import doc_inflight
        self.assertEqual(doc_inflight.ticket_action_label("doc_batch_delete"), "删除工单")
        self.assertEqual(doc_inflight.ticket_action_label("doc_restore"), "恢复工单")
        self.assertEqual(doc_inflight.policy_action_label("rollback"), "版本回滚申请")
        self.assertEqual(doc_inflight.policy_action_label("update_policy"), "变更申请")
        self.assertEqual(doc_inflight.policy_action_label("unknown"), "变更申请")


class WiringTests(unittest.TestCase):
    """四个建单入口必须抢锁、五个办结点必须释放，常量必须与 kms 层同值。"""

    def _src(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_call_sites_use_shared_guard(self):
        kms_src = self._src("gateway/routes_kms.py")
        ticket_src = self._src("gateway/routes_tickets.py")
        # 回滚 / 申请更新 / 上传后自动提交 三处 + 工单建单一处
        self.assertEqual(kms_src.count("doc_inflight.find_inflight_conflict"), 4)
        self.assertEqual(ticket_src.count("doc_inflight.find_inflight_conflict"), 1)
        # 旧的「只查 kms_policy_requests」局部实现必须已下线，
        # 否则删除单在途时仍能提交变更申请（正是本次修复的缺口）。
        self.assertNotIn("_pending_conflict_text", kms_src)

    def test_every_creation_point_acquires_the_lock(self):
        kms_src = self._src("gateway/routes_kms.py")
        ticket_src = self._src("gateway/routes_tickets.py")
        upload_src = self._src("gateway/routes_upload.py")
        # 四个 INSERT 点：滚回 / 申请更新 / 上传自动提交 / 工单建单
        self.assertEqual(kms_src.count("cur.execute(\"INSERT INTO kms_policy_requests"),
                         3)
        self.assertEqual(kms_src.count("doc_inflight.acquire("), 4)  # 3 处 + 回滚失败退回
        # 1 处真抢锁 + 1 处出现在 _assert_no_pending_doc_ticket 的文档字符串里
        self.assertEqual(ticket_src.count("doc_inflight.acquire("), 2)
        self.assertEqual(ticket_src.count("INSERT INTO kms_tickets"), 1)
        # 上传新版本：事务首行判定（写任何内容之前）
        self.assertIn("doc_inflight.find_inflight_conflict", upload_src)

    def test_decision_points_release_the_lock(self):
        kms_src = self._src("gateway/routes_kms.py")
        ticket_src = self._src("gateway/routes_tickets.py")
        # 变更申请：decide 释放
        self.assertIn("doc_inflight.release(cur, ref_type=doc_inflight.REF_POLICY",
                      kms_src)
        # 工单：通过 / 驳回 / 撤回 / 超时清扫
        self.assertEqual(ticket_src.count("doc_inflight.release(cur"), 4)
        self.assertIn("doc_inflight.release_many(", ticket_src)

    def test_lock_table_is_created_on_startup(self):
        kms_src = self._src("gateway/routes_kms.py")
        self.assertIn("doc_inflight.ensure_schema(cur)", kms_src)
        from gateway import doc_inflight
        self.assertIn(doc_inflight.LOCK_TABLE, doc_inflight.LOCK_DDL)
        self.assertIn("PRIMARY KEY (document_id)", doc_inflight.LOCK_DDL)

    def test_history_backfill_runs_at_startup(self):
        """锁表上线前就在审的 pending 单，必须在启动时补登记成锁行。"""
        import inspect
        from gateway import doc_inflight
        kms_src = self._src("gateway/routes_kms.py")
        self.assertIn("doc_inflight.backfill(cur)", kms_src)
        # 回填要读 kms_tickets / kms_users，必须先确保治理基础表已就绪
        self.assertIn("acl.ensure_kms_acl_tables()", kms_src)
        src = inspect.getsource(doc_inflight.backfill)
        self.assertIn("INSERT IGNORE", src)      # 同文档多张历史单只留先到的一行
        self.assertIn("JSON_TABLE", src)         # 工单的 doc_ids 在 payload JSON 里
        self.assertIn("_STATUS_PENDING", src)    # 只补在审的单

    def test_constants_match_kms_layer(self):
        from gateway import doc_inflight
        from kms.constants import (TICKET_MODULE_DOC_BATCH_DELETE,
                                   TICKET_MODULE_DOC_RESTORE, TICKET_STATUS_PENDING)
        self.assertEqual(set(doc_inflight.TICKET_MODULES),
                         {TICKET_MODULE_DOC_BATCH_DELETE, TICKET_MODULE_DOC_RESTORE})
        self.assertEqual(doc_inflight._STATUS_PENDING, TICKET_STATUS_PENDING)


if __name__ == "__main__":
    unittest.main()
