"""访问控制与生命周期契约测试（离线，零 DB / 零模型依赖）。

锁死企业 KMS 的安全核心契约：
  - BLP 强制访问控制（不上读 / 不下写 + 部门规则）
  - 文档生命周期状态机（DocState + VALID_TRANSITIONS）

这些是 access_control.py 与 lifecycle.py 的纯函数层，不触达 MySQL；
一旦未来把 live 路径（gateway/service.allowed）收敛到这些原语，契约不得回归。

注意：必须像 test_collapse_fragments 一样先 apply_environment 再 import kms.*——
config.Settings 类属性在首次导入时求值，导入顺序错误会把 KMS_*_EMPLOYEES 冻结为空，
污染其它离线测试（本文件按字母序最先运行）。
"""
from __future__ import annotations

import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
from kms import constants  # noqa: E402
from kms import lifecycle  # noqa: E402


def _user(security_level: int) -> SimpleNamespace:
    """最小主体：仅提供 BLP 原语所需的 security_level 字段（鸭子类型）。"""
    return SimpleNamespace(security_level=security_level)


class SecurityLevelNamingTests(unittest.TestCase):
    """密级名称：L0 公开 / L1 秘密 / L2 机密 / L3 绝密。

    "公开"指**公司内部**公开（全体在职员工可见），不是对公众公开——KMS 无匿名入口。
    这个测试同时守住"唯一定义"：历史上密级字面量散落在 4 个模块，改名必然漂移，
    表现为前端徽章与后端统计各说各话。
    """

    EXPECTED = {0: "公开", 1: "秘密", 2: "机密", 3: "绝密"}

    def test_canonical_names(self):
        self.assertEqual(self.EXPECTED, constants.SECURITY_LEVELS)

    def test_security_module_reexports_canonical(self):
        """kms.security 不得另存一份密级名称。"""
        from kms import security

        self.assertEqual(constants.SECURITY_LEVELS, security.SECURITY_LEVELS)

    def test_fixed_levels_follow_canonical(self):
        """前端徽章与员工列表读的是 FIXED_LEVELS，必须与唯一定义一致。"""
        for level, name, _desc in acl.FIXED_LEVELS:
            self.assertEqual(constants.SECURITY_LEVELS[level], name)

    def test_employee_clearance_label_is_numeric(self):
        """员工安全职级显示为 L0-L3 数字编号，不沿用文档密级名称「公开/秘密/机密/绝密」。"""
        from kms.security import AuthUser

        u = AuthUser({"id": 1, "employee_no": "E10001", "username": "测试员工",
                      "security_level": 2, "is_active": 1})
        self.assertEqual("L2", u.to_public_dict()["security_level_label"])
        self.assertEqual("机密", constants.SECURITY_LEVELS[2])

    def test_public_level_is_company_internal(self):
        """L0 的名称是"公开"，语义必须写明是公司内部，避免误读为对外公开。"""
        self.assertEqual("公开", constants.SECURITY_LEVELS[0])
        desc = dict((lv, d) for lv, _n, d in acl.FIXED_LEVELS)[0]
        self.assertIn("公司内部", desc)

    def test_no_stray_level_literals(self):
        """模块中不得再出现硬编码的密级名称列表。"""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        bad = []
        for rel in ("gateway/service.py", "kms/security.py", "kms/access_control.py"):
            src = (root / rel).read_text(encoding="utf-8", errors="ignore")
            if re.search(r"\[\s*['\"]公开['\"]", src):
                bad.append(rel)
        self.assertEqual([], bad, "密级名称被硬编码，应改用 constants.SECURITY_LEVELS")


class IdentityConstantSingleSourceTests(unittest.TestCase):
    """身份常量同样只有一份定义——与密级常量是同一类漂移问题。"""

    def test_role_label(self):
        self.assertEqual("员工", constants.ROLE_LABELS[constants.ROLE_EMPLOYEE])

    def test_security_reexports_role_constants(self):
        from kms import security

        self.assertEqual(constants.ROLE_EMPLOYEE, security.ROLE_EMPLOYEE)
        self.assertEqual(constants.ROLE_LABELS, security.ROLE_LABELS)

    def test_security_reexports_level_constants(self):
        from kms import security

        for name in ("SECURITY_LEVEL_PUBLIC", "SECURITY_LEVEL_SECRET",
                     "SECURITY_LEVEL_CONFIDENTIAL", "SECURITY_LEVEL_TOPSECRET",
                     "PUBLIC_LEVEL", "MAX_EMPLOYEE_LEVEL"):
            self.assertEqual(getattr(constants, name), getattr(security, name))

    def test_no_redefinition_outside_constants(self):
        """除 constants.py 外，不得再出现身份常量的字面量定义。"""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        bad = []
        for path in sorted((root / "kms").glob("*.py")):
            if path.name == "constants.py":
                continue
            src = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"^ROLE_EMPLOYEE\s*=\s*[\"']", src, re.M):
                bad.append(f"{path.name}: ROLE_EMPLOYEE")
            if re.search(r"^ROLE_LABELS\s*=\s*\{", src, re.M):
                bad.append(f"{path.name}: ROLE_LABELS")
        self.assertEqual([], bad, "身份常量被重复定义，应从 kms.constants 导入")


class BlpReadTests(unittest.TestCase):
    """不上读：doc_level <= emp_level 且（非公开）部门匹配。"""

    def test_public_still_respects_departments(self):
        # 新语义：密级只作「职级上限」，L0 不再绕过归属部门判定。
        # L0 + 归属部门=风险控制部 → 技术研发部不可读（用户明确要求）。
        self.assertFalse(acl.can_read_doc(0, 0, "技术研发部", ["风险控制部"]))
        # 同部门 L0 可读
        self.assertTrue(acl.can_read_doc(0, 0, "风险控制部", ["风险控制部"]))
        # 「不限部门」才全员可读（含 L0）
        self.assertTrue(acl.can_read_doc(0, 0, "技术研发部", ["*"]))

    def test_no_read_up(self):
        # L2 员工不得读 L3 绝密
        self.assertFalse(acl.can_read_doc(2, 3, "风险控制部", ["风险控制部"]))

    def test_read_equal_or_down(self):
        self.assertTrue(acl.can_read_doc(3, 2, "风险控制部", ["风险控制部"]))  # 下读
        self.assertTrue(acl.can_read_doc(2, 2, "风险控制部", ["风险控制部"]))  # 等读

    def test_non_public_cross_department_denied(self):
        self.assertFalse(acl.can_read_doc(2, 1, "技术研发部", ["风险控制部"]))

    def test_multi_departments_grants_cross_department(self):
        self.assertTrue(acl.can_read_doc(2, 1, "技术研发部", ["风险控制部", "技术研发部"]))

    def test_departments_accepts_json_string(self):
        self.assertTrue(acl.can_read_doc(2, 1, "技术研发部", '["风险控制部", "技术研发部"]'))

    def test_missing_department_denied(self):
        self.assertFalse(acl.can_read_doc(2, 1, "", ["风险控制部"]))
        self.assertFalse(acl.can_read_doc(2, 1, "技术研发部", []))


class BlpOrgInheritanceTests(unittest.TestCase):
    """组织层级继承：上级可见下级（doc_org_path 是 emp_org_path 的后代）。"""

    def test_parent_sees_child_department(self):
        self.assertTrue(acl.can_read_doc(
            2, 1, "风险控制部", ["风控策略组"],
            emp_org_path="银联商务/风险控制部",
            doc_org_path="银联商务/风险控制部/风控策略组"))

    def test_exact_org_path_match(self):
        self.assertTrue(acl.can_read_doc(
            2, 1, "风险控制部", ["风控策略组"],
            emp_org_path="银联商务/风险控制部/风控策略组",
            doc_org_path="银联商务/风险控制部/风控策略组"))

    def test_child_does_not_see_parent(self):
        # 下级不可见上级文档（继承是单向的）
        self.assertFalse(acl.can_read_doc(
            2, 1, "风控策略组", ["风险控制部"],
            emp_org_path="银联商务/风险控制部/风控策略组",
            doc_org_path="银联商务/风险控制部"))

    def test_no_org_path_no_inheritance(self):
        # 无组织路径时，跨部门仍拒绝
        self.assertFalse(acl.can_read_doc(2, 1, "风险控制部", ["风控策略组"]))


class BlpWriteTests(unittest.TestCase):
    """不下写：doc_level >= emp_level 且严格同部门。"""

    def test_no_write_down(self):
        # L2 员工不得写 L1 文档（不下写）
        self.assertFalse(acl.can_write_doc(2, 1, "风险控制部", ["风险控制部"]))

    def test_write_equal_or_up(self):
        self.assertTrue(acl.can_write_doc(2, 2, "风险控制部", ["风险控制部"]))  # 等写
        self.assertTrue(acl.can_write_doc(2, 3, "风险控制部", ["风险控制部"]))  # 上写

    def test_cross_department_write_denied(self):
        # 写操作要求员工部门在归属部门数组中
        self.assertFalse(acl.can_write_doc(2, 2, "技术研发部", ["风险控制部"]))

    def test_multi_department_write_allowed(self):
        # 归属部门数组包含员工部门即可写
        self.assertTrue(acl.can_write_doc(2, 2, "技术研发部", ["风险控制部", "技术研发部"]))

    def test_missing_department_denied(self):
        self.assertFalse(acl.can_write_doc(2, 2, "", ["风险控制部"]))
        self.assertFalse(acl.can_write_doc(2, 2, "风险控制部", []))


class BlpWritableLevelTests(unittest.TestCase):
    def test_min_writable_level_is_own_level(self):
        self.assertEqual(acl.min_writable_level(_user(2)), 2)

    def test_max_writable_level_is_top(self):
        # BLP 不下写：可写区间为 [self.security_level, L3]，故最高可写恒为 L3
        self.assertEqual(acl.max_writable_level(_user(2)), 3)

    def test_anonymous_writable_none(self):
        self.assertEqual(acl.min_writable_level(None), -1)
        self.assertEqual(acl.max_writable_level(None), -1)


class LifecycleStateMachineTests(unittest.TestCase):
    """文档生命周期状态机：draft/published/archived/expired 的合法转换。"""

    def test_state_enum_values(self):
        self.assertEqual({s.value for s in lifecycle.DocState},
                         {"draft", "published", "archived", "expired"})

    def test_valid_transitions_match_documented_graph(self):
        vt = lifecycle.VALID_TRANSITIONS
        self.assertEqual(vt[lifecycle.DocState.DRAFT],
                         {lifecycle.DocState.PUBLISHED, lifecycle.DocState.ARCHIVED})
        self.assertEqual(vt[lifecycle.DocState.PUBLISHED],
                         {lifecycle.DocState.ARCHIVED, lifecycle.DocState.EXPIRED})
        self.assertEqual(vt[lifecycle.DocState.EXPIRED],
                         {lifecycle.DocState.PUBLISHED, lifecycle.DocState.ARCHIVED})
        # 归档（回收站）恢复：可回发布，也可退回草稿重新编辑——恢复工单按
        # 删除前状态回流，草稿被删的恢复后仍是草稿，不得越过发布闸门
        self.assertEqual(vt[lifecycle.DocState.ARCHIVED],
                         {lifecycle.DocState.PUBLISHED, lifecycle.DocState.DRAFT})

    def test_published_to_draft_is_illegal(self):
        # 已发布文档不可退回草稿（企业 KMS 防回退，只能归档或重新走发布）
        self.assertNotIn(lifecycle.DocState.DRAFT,
                         lifecycle.VALID_TRANSITIONS[lifecycle.DocState.PUBLISHED])

    def test_archived_to_draft_requires_restore_flow(self):
        """归档 → 草稿的恢复转换合法，但只允许通过恢复工单触发。

        状态机放行该转换是为了「误删找回」；恢复目标态必须取自删除工单
        快照冻结的删除前状态，而不是执行时硬编码——草稿被删的恢复后仍是
        草稿，已发布的恢复后仍是已发布，不得借恢复之名静默改状态。
        """
        src = (Path(__file__).resolve().parents[1]
               / "gateway" / "routes_tickets.py").read_text(encoding="utf-8")
        self.assertIn("_pre_delete_states", src,
                      "恢复执行器必须从删除工单快照取删除前状态")
        self.assertIn("DocState(", src)

    def test_state_labels_complete(self):
        self.assertEqual(set(lifecycle.STATE_LABELS), set(lifecycle.DocState))
        # 兼容层标签必须是状态机标签的超集（额外含 review/destroyed 等历史值）
        for s in lifecycle.DocState:
            self.assertIn(s.value, lifecycle.DOC_STATUS_LABELS)

    def test_constants_state_labels_complete(self):
        self.assertEqual(set(constants.DOC_STATE_LABELS),
                         {s.value for s in lifecycle.DocState})


class LifecycleDualWriteTests(unittest.TestCase):
    """双生命周期字段必须同写。

    documents 表有 status 与 lifecycle_state 两个语义重复的列，读取侧
    （gateway/service.allowed 与 documents() SQL）要求**两列同时为 published**。
    若某条写入路径只改其一，文档就会静默不可见——最典型的是「归档后恢复」：
    lifecycle 回到 published 而 status 仍是 archived，恢复看似成功但文档找不到。
    """

    def _capture(self, current_state="archived"):
        """拦截 lifecycle 发出的 SQL，返回 (语句列表, 游标, 连接桩)。"""
        executed: list[tuple[str, tuple]] = []
        cur = MagicMock()
        cur.execute.side_effect = lambda sql, params=None: executed.append(
            (" ".join(sql.split()), params))
        cur.fetchone.return_value = {"lifecycle_state": current_state}
        cur.rowcount = 1

        @contextmanager
        def _conn(self_store):
            yield cur

        return executed, _conn

    def _updates(self, executed):
        return [(s, p) for s, p in executed if s.startswith("UPDATE documents")]

    def test_restore_writes_both_status_and_lifecycle(self):
        executed, _conn = self._capture("archived")
        with patch.object(lifecycle.MySQLStore, "_conn", _conn):
            ok, _ = lifecycle.transition_state(1, lifecycle.DocState.PUBLISHED)
        self.assertTrue(ok)
        sql, params = self._updates(executed)[0]
        self.assertIn("lifecycle_state = %s", sql)
        self.assertIn("status = %s", sql)
        # 两个占位符都要写入同一个目标状态
        self.assertEqual(params.count("published"), 2)

    def test_archive_writes_both_columns(self):
        executed, _conn = self._capture("published")
        with patch.object(lifecycle.MySQLStore, "_conn", _conn):
            lifecycle.soft_delete(1, 100, "过期下线")
        sql, params = self._updates(executed)[0]
        self.assertIn("status = %s", sql)
        self.assertEqual(params.count("archived"), 2)

    def test_expiry_sweep_writes_both_columns(self):
        executed, _conn = self._capture("published")
        with patch.object(lifecycle.MySQLStore, "_conn", _conn):
            lifecycle.check_expired_documents()
        sql, params = self._updates(executed)[0]
        self.assertIn("SET lifecycle_state = %s, status = %s", sql)
        self.assertEqual(params.count("expired"), 2)

    def test_no_write_to_phantom_history_table(self):
        """kms_doc_status_history 表不存在，写入应彻底移除而非静默吞异常。"""
        executed, _conn = self._capture("archived")
        with patch.object(lifecycle.MySQLStore, "_conn", _conn):
            lifecycle.transition_document(1, "published", 100)
        self.assertFalse(any("kms_doc_status_history" in s for s, _ in executed))
        self.assertFalse(hasattr(lifecycle, "get_status_history"))


if __name__ == "__main__":
    unittest.main()
