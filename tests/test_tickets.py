"""工单中心（gateway/routes_tickets.py）的离线契约回归。

本机为离线环境（禁止真实 MySQL），因此这里不做端到端流程，只守住**设计不变量**——
这些约束一旦被破坏，就意味着「无管理员」「两段式」「防篡改」三个核心语义失效：

  1. 无管理员：模块不得依赖 administrator，审批权只来自 ticket_approve 职责；
  2. 全部鉴权：工单/通知端点必须都带 require_user；
  3. 两段式：执行人视角端点（refuse / execute / executor-candidates /
     pending-execution）必须已从路由表整体移除（不留 409 兜底），提权令牌 404；
  4. 模块注册表形状完整（前端按 schema 渲染，缺字段会白屏）；
  5. 防篡改哈希稳定且与键顺序无关。
"""
from __future__ import annotations

import inspect
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "gateway" / "routes_tickets.py").read_text(encoding="utf-8")


class TicketModuleShapeTests(unittest.TestCase):
    """模块注册表：前端按它渲染发起表单，形状错了就是白屏。"""

    def test_registry_shape(self):
        from gateway.routes_tickets import TICKET_FLOW_TWO_STEP, TICKET_MODULES
        self.assertTrue(TICKET_MODULES, "模块注册表不应为空")
        for key, m in TICKET_MODULES.items():
            self.assertEqual(key, m["key"], f"{key} 的 key 与字典键不一致")
            self.assertEqual(m["category"], "mgmt", f"{key} 应属管理类")
            self.assertEqual(m["flow"], TICKET_FLOW_TWO_STEP, f"{key} 应为两段式")
            self.assertTrue(m["schema"], f"{key} 缺少 schema")
            for f in m["schema"]:
                for field in ("name", "type", "label"):
                    self.assertIn(field, f, f"{key}.{f.get('name')} 缺 {field}")

    def test_every_module_has_timeout(self):
        """超时不能靠默认兜底兜了还不知道——注册表里的模块都应显式或隐式可解析。"""
        from gateway.routes_tickets import TICKET_MODULES, _timeout_minutes
        for key in TICKET_MODULES:
            self.assertGreater(_timeout_minutes(key), 0, f"{key} 超时必须为正")

    def test_batch_modules_are_declared(self):
        """批量删除模块必须留在注册表里。

        发起入口已从工单中心迁到文档库（多选 → 提交本模块工单），但
        `doc_batch_delete` 这个 key 仍是两边的契约：文档库按它提交，
        路由据此指派审批人、大多选王模块->执行器。删掉会让整条删除链断掉。
        """
        from gateway.routes_tickets import TICKET_MODULES
        self.assertIn("doc_batch_delete", TICKET_MODULES)
        # 员工职责授予已下线：审批权改由部门 + 安全职级派生并随机指派。
        # 若有人把它加回来，前端就该重新出现一张指向它的卡片——二者须同步。
        self.assertNotIn("user_duty_grant", TICKET_MODULES)


class NoAdminInvariantTests(unittest.TestCase):
    """无管理员：审批权来自组织属性（部门 + 安全职级）的随机指派，
    不是 is_admin / kms_admin_employees，也不是「持有职责」。
    """

    def test_module_does_not_use_administrator(self):
        # 只禁止「实际使用」，允许文档里解释为什么不用（那是有价值的说明）。
        src = _source()
        for bad in ("Depends(administrator)", "administrator(", "import administrator"):
            self.assertNotIn(bad, src,
                             f"工单审批不得使用 administrator（走 kms_admin_employees 配置）: {bad}")
        # 同理只禁实际取值（.is_admin），允许文档里说明「不看 is_admin」
        self.assertNotIn(".is_admin", src)

    def test_approval_derived_from_organization(self):
        """审批人由 acl 按「同部门 + 职级够读取」匹配并随机指派。"""
        src = _source()
        self.assertIn("acl.pick_approver", src)
        self.assertIn("acl.can_approve_document", src)

    def test_approval_no_longer_gated_by_duty(self):
        """反断言：审批权不得回到职责判据。

        原因不是「职责不好」，而是它会与 BLP 形成两个真相：职责名单说某人能审，
        而 BLP 说他看不见这篇文档。这类不一致正是本轮要消除的东西。
        """
        src = _source()
        for bad in ("acl.has_duty", "find_duty_holders", "DUTY_TICKET_APPROVE"):
            self.assertNotIn(bad, src,
                             f"审批放行不应再依赖职责，请改用 pick_approver/can_approve_document: {bad}")

    def test_ab_separation(self):
        """申请人不能审批自己的工单。"""
        src = _source()
        self.assertIn("审批人不能是申请人本人", src)


class _ScriptedCursor:
    """按调用顺序回放 fetchall 结果的最小假游标（记录全部 SQL 供断言）。"""

    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self._results.pop(0) if self._results else []

    def fetchone(self):
        return None


class RecycleBinPurgeTests(unittest.TestCase):
    """回收站宽限期清扫：物理销毁必须只命中「工单删除」产生的归档。"""

    def test_purge_destroys_due_docs_and_collects_faiss_ids(self):
        from gateway.routes_tickets import _sweep_recycled_purge
        cur = _ScriptedCursor([
            [{"id": 42, "filename": "过期文档.txt"}],           # 宽限届满列表
            [{"faiss_id": 7}, {"faiss_id": 8}],                  # 对应向量
        ])
        faiss_ids, notes = _sweep_recycled_purge(cur)
        self.assertEqual(faiss_ids, [7, 8], "应收集全部待清理向量")
        self.assertEqual(len(notes), 1, "每篇销毁文档应生成一条审计")
        sqls = [s for s, _ in cur.statements]
        for table in ("chunks", "kms_doc_levels", "kms_doc_versions", "documents"):
            self.assertTrue(any(f"DELETE FROM {table}" in s for s in sqls),
                            f"销毁必须清 {table}")

    def test_purge_scope_is_limited_to_ticket_deletions(self):
        """防误伤：SELECT 必须限定 archive_reason LIKE '工单删除:%'，
        正常业务归档（无该前缀）永不被自动物理销毁。"""
        from gateway.routes_tickets import _PURGE_REASON_PREFIX, _sweep_recycled_purge
        cur = _ScriptedCursor([[]])  # 无届满文档
        faiss_ids, notes = _sweep_recycled_purge(cur)
        self.assertEqual((faiss_ids, notes), ([], []))
        sel, sel_params = next((s, p) for s, p in cur.statements
                               if s.startswith("SELECT d.id"))
        self.assertIn("archive_reason LIKE", sel, "清扫范围必须限定工单删除归档")
        # 前缀是**参数化**传入的（SQL 里只有 `LIKE %s`），故断言要落在参数上。
        # 只查 LIKE 子句存在是不够的：有人把前缀改宽，清扫会波及正常业务归档，
        # 而这条测试发现不了——这正是要钉住的地方。
        params = sel_params if isinstance(sel_params, (list, tuple)) else (sel_params,)
        self.assertTrue(
            any(isinstance(p, str) and p.startswith(_PURGE_REASON_PREFIX)
                for p in params),
            "清扫必须限定工单删除前缀，不得波及其它归档原因",
        )
        self.assertIn("lifecycle_state='archived'", sel)
        self.assertIn("INTERVAL", sel, "必须按宽限期天数过滤")

    def test_purge_params_carry_retention_days(self):
        from gateway.routes_tickets import _DELETE_RETENTION_DAYS, _sweep_recycled_purge
        cur = _ScriptedCursor([[]])
        _sweep_recycled_purge(cur)
        sel_params = next(p for s, p in cur.statements if s.startswith("SELECT d.id"))
        self.assertEqual(tuple(sel_params)[-1], _DELETE_RETENTION_DAYS,
                         "宽限期天数应参数化传入（env KMS_DELETE_RETENTION_DAYS）")


class PendingDocTicketExclusionTests(unittest.TestCase):
    """同一篇文档不允许并存两个进行中的删除/恢复工单。

    现场问题：赵明远发起删除后，宁宁用自己账号对同一文档再发起删除，两单
    都能建、都能批——第二单只是重复第一单的效果，A/B 分离形同虚设。
    """

    def _call(self, held, doc_ids=(42,)):
        from gateway.routes_tickets import _assert_no_pending_doc_ticket
        cur = _ScriptedCursor([
            [{"id": i, "filename": f"文档{i}"} for i in doc_ids],
            held,
        ])
        _assert_no_pending_doc_ticket(cur, list(doc_ids))
        return cur

    def test_second_delete_ticket_is_rejected(self):
        from fastapi import HTTPException
        held = [{"id": 9, "ticket_no": "T20261025ABCD1234", "module": "doc_batch_delete",
                 "applicant_name": "赵明远",
                 "payload": '{"doc_ids": ["42"], "reason": "清理"}'}]
        with self.assertRaises(HTTPException) as caught:
            self._call(held)
        self.assertEqual(caught.exception.status_code, 409)
        detail = str(caught.exception.detail)
        self.assertIn("T20261025ABCD1234", detail)
        self.assertIn("赵明远", detail)
        self.assertIn("文档42", detail)

    def test_unrelated_ticket_does_not_block(self):
        # 另一篇文档的工单不应阻止本次建单（互斥按文档求交集，不是整表单锁）
        self._call([{"id": 9, "ticket_no": "T1", "module": "doc_batch_delete",
                      "applicant_name": "赵明远", "payload": '{"doc_ids": ["7"]}'}])

    def test_check_locks_rows_and_only_counts_pending(self):
        cur = self._call([])
        sqls = [" ".join(s.split()) for s, _ in cur.statements]
        # 先锁文档行（串行化同一文档的建单），再对在途工单做加锁读（绕开快照）。
        # 锁表上线后中间多了「清过期租约 + 读锁行」两条 SQL，故按内容定位，
        # 不按序号——序号写死会在加一个查询时假失败。
        self.assertIn("FROM documents", sqls[0])
        self.assertIn("FOR UPDATE", sqls[0])
        ticket_idx = next(i for i, s in enumerate(sqls) if "kms_tickets" in s)
        self.assertIn("FOR UPDATE", sqls[ticket_idx])
        self.assertIn("status=%s", sqls[ticket_idx])
        self.assertEqual(cur.statements[ticket_idx][1][0], "pending")

    def test_create_ticket_runs_guard_inside_transaction(self):
        src = _source()
        self.assertIn("_assert_no_pending_doc_ticket(cur, payload.get(\"doc_ids\")", src)


class AuthCoverageTests(unittest.TestCase):
    """工单/通知端点可以挂载，但每一个都必须带鉴权。"""

    def test_all_routes_require_user(self):
        from fastapi import params as fastapi_params

        from gateway.routes_tickets import router
        from kms.security import require_user

        for route in router.routes:
            sig = inspect.signature(route.endpoint)
            authed = any(
                isinstance(p.default, fastapi_params.Depends)
                and p.default.dependency is require_user
                for p in sig.parameters.values()
            )
            self.assertTrue(authed, f"{route.path}（{route.name}）缺少 require_user 鉴权")


class TwoStepSemanticsTests(unittest.TestCase):
    """两段式（审批通过即系统执行）下不存在执行人视角，相关端点必须已移除。"""

    def test_executor_endpoints_are_removed(self):
        """执行人四端点不得再注册路由（不留 409 兜底，直接 404）。"""
        from gateway import routes_tickets as rt

        banned = ("/pending-execution", "/execute", "/refuse", "/executor-candidates")
        registered = {getattr(r, "path", "") for r in rt.router.routes}
        for frag in banned:
            hit = [p for p in registered if p.endswith(frag)]
            self.assertFalse(hit, f"执行人端点仍被注册: {hit}")

    def test_escalation_token_removed(self):
        from fastapi import HTTPException

        from gateway import routes_tickets as rt

        with self.assertRaises(HTTPException) as ctx:
            rt.escalation_token(1, None)
        self.assertEqual(ctx.exception.status_code, 404)


class TamperGuardTests(unittest.TestCase):
    """防篡改：哈希必须稳定且与键顺序无关，否则审批后内容被换无法发现。"""

    def test_hash_is_order_insensitive(self):
        from gateway.routes_tickets import _payload_hash

        self.assertEqual(_payload_hash({"b": 1, "a": [1, 2]}),
                         _payload_hash({"a": [1, 2], "b": 1}))

    def test_hash_detects_change(self):
        from gateway.routes_tickets import _payload_hash

        self.assertNotEqual(_payload_hash({"doc_ids": [1]}),
                            _payload_hash({"doc_ids": [2]}))

    def test_tampered_status_on_mismatch(self):
        src = _source()
        self.assertIn("TICKET_STATUS_TAMPERED", src)
        self.assertIn("提交后内容被修改，已拦截执行", src)


class BatchFileParsingTests(unittest.TestCase):
    """批量上传解析（csv 路径可离线验证）。"""

    def test_csv_parsing(self):
        from gateway.routes_tickets import _rows_from_file

        rows = _rows_from_file(
            b"document_id,reason\n1,old\n2,old\n", "b.csv", "doc_batch_delete")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["document_id"], "1")

    def test_unsupported_extension(self):
        from fastapi import HTTPException

        from gateway.routes_tickets import _rows_from_file

        with self.assertRaises(HTTPException) as ctx:
            _rows_from_file(b"x", "a.txt", "doc_batch_delete")
        self.assertEqual(ctx.exception.status_code, 415)


class NoBootstrapNeededTests(unittest.TestCase):
    """冷启动死锁已不存在：审批人由组织属性派生，不需要任何「初始播种」。

    原先 DutyBootstrapTests 守的是旧模型——审批人来自 kms_user_duties，而该表
    初始为空，必须靠配置播下第一批职责，否则一张工单都建不出来。
    现在人选天然来自 HR 同步的员工表（部门 + 职级），播种与否都不影响可用性。
    这里反过来钉住：别再把那种播种加回来。
    """

    def test_no_duty_seed_function(self):
        from kms import access_control as acl

        self.assertFalse(hasattr(acl, "seed_ticket_duties"),
                         "审批人已由组织属性派生，不应再依赖职责播种")

    def test_no_approver_seed_config(self):
        """废弃的配置项必须真的删掉：留着一个看着能授予审批权、实际不生效的
        开关，比没有这个开关更容易误导运维。"""
        from config import settings

        for attr in ("kms_ticket_approver_employees", "kms_approver_employees"):
            self.assertFalse(hasattr(settings, attr),
                             f"配置项 {attr} 已失效，请一并删除）")


class TicketOutputDecisionFlagsTests(unittest.TestCase):
    """can_approve / can_cancel 是前端「审批通过 / 驳回 / 撤回」按钮的唯一渲染依据。

    曾经漏发这两个字段，前端 `v-if="dlg.ticket.can_approve"` 永远为假——审批人
    点「审批」进来只看得到「当前身份无待办操作，仅可查看」，工单再也办不下去。
    这里钉住派生口径：pending + 身份匹配才给标记，终态一律不给。
    """

    def _row(self, status="pending", applicant_id=1, approver_id=2):
        return {
            "id": 50, "ticket_no": "T1", "module": "doc_batch_delete",
            "category": "doc", "flow": "two_step", "status": status,
            "applicant_id": applicant_id, "applicant_no": "20260000",
            "applicant_name": "张明远", "approver_id": approver_id,
            "approver_no": "20260020", "approver_name": "宋美龄",
            "payload": '{"doc_ids": ["3"]}', "payload_summary": "删除 1 篇",
            "reason": "", "exec_result": "", "original_hash": "abc",
            "approved_hash": "", "approve_comment": "", "doc_references": "[]",
            "created_at": None, "updated_at": None, "timeout_at": None,
            "approved_at": None, "executed_at": None,
        }

    def test_approver_gets_can_approve_only(self):
        from types import SimpleNamespace

        from gateway.routes_tickets import _ticket_out

        out = _ticket_out(self._row(), SimpleNamespace(id=2))
        self.assertTrue(out["can_approve"])
        self.assertFalse(out["can_cancel"])
        self.assertEqual(out["approver_id"], 2)
        self.assertEqual(out["original_hash"], "abc")

    def test_applicant_gets_can_cancel_only(self):
        from types import SimpleNamespace

        from gateway.routes_tickets import _ticket_out

        out = _ticket_out(self._row(), SimpleNamespace(id=1))
        self.assertFalse(out["can_approve"])
        self.assertTrue(out["can_cancel"])

    def test_outsider_gets_neither(self):
        from types import SimpleNamespace

        from gateway.routes_tickets import _ticket_out

        out = _ticket_out(self._row(), SimpleNamespace(id=99))
        self.assertFalse(out["can_approve"])
        self.assertFalse(out["can_cancel"])

    def test_closed_ticket_gets_neither(self):
        """已办结的工单即便身份匹配也不给按钮（否则前端会重复提交）。"""
        from types import SimpleNamespace

        from gateway.routes_tickets import _ticket_out

        out = _ticket_out(self._row(status="executed"), SimpleNamespace(id=2))
        self.assertFalse(out["can_approve"])
        self.assertFalse(out["can_cancel"])

    def test_no_viewer_means_no_flags(self):
        from gateway.routes_tickets import _ticket_out

        out = _ticket_out(self._row())
        self.assertFalse(out["can_approve"])
        self.assertFalse(out["can_cancel"])


if __name__ == "__main__":
    unittest.main()
