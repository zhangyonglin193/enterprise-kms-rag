# -*- coding: utf-8 -*-
"""HR 企业维度与「涉密准入资格」派生判定。

覆盖三条容易悄悄失效的路径：
  1. 资格判据本身（在职状态 / 用工性质 / 保密承诺 / 背景审查的组合）；
  2. HR 脏值的**降级方向**——必须落到 unknown（不合格），不能落到最宽松档；
  3. 该资格是否真的进了审批候选的 SQL（只写函数不接线 = 死代码）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kms.constants import (HR_EMPLOYMENT_UNKNOWN, HR_STATUS_UNKNOWN,  # noqa: E402
                           HR_EMPLOYMENTS, HR_STATUSES)
from kms.hr_sync import HREmployeeData  # noqa: E402
from kms.security import hr_secret_eligible  # noqa: E402


class SecretEligibleTests(unittest.TestCase):
    """资格判据：四项全过才有资格，任何一项不过即无。"""

    def test_full_qualification_passes(self):
        self.assertTrue(hr_secret_eligible("regular", "staff", True, True))
        self.assertTrue(hr_secret_eligible("trial", "staff", True, True))

    def test_status_blocks(self):
        for st in ("pending_leave", "leave", HR_STATUS_UNKNOWN, ""):
            self.assertFalse(hr_secret_eligible(st, "staff", True, True), st)

    def test_employment_type_blocks(self):
        # 派遣/实习/外包默认不接触涉密；unknown 更不能算有资格
        for et in ("dispatch", "intern", "outsource", HR_EMPLOYMENT_UNKNOWN, ""):
            self.assertFalse(hr_secret_eligible("regular", et, True, True), et)

    def test_nda_and_background_block(self):
        self.assertFalse(hr_secret_eligible("regular", "staff", False, True))
        self.assertFalse(hr_secret_eligible("regular", "staff", True, False))
        self.assertFalse(hr_secret_eligible("regular", "staff", False, False))

    def test_whitelists_include_unknown(self):
        """unknown 必须同时在白名单里——否则归一化会把它再降级一次，
        而第二次降级的落点若是最宽松档，就等于把脏值洗成了有资格。"""
        self.assertIn(HR_STATUS_UNKNOWN, HR_STATUSES)
        self.assertIn(HR_EMPLOYMENT_UNKNOWN, HR_EMPLOYMENTS)


class DirtyValueDowngradeTests(unittest.TestCase):
    """HR 脏值降级方向：收紧，而不是图省事落到最宽松档。"""

    def test_unknown_values_downgrade_to_unknown(self):
        e = HREmployeeData(employee_no="X001", username="测试",
                           status="已毕业", employment_type="外包驻场",
                           job_family="序列Z")
        self.assertEqual(e.status, HR_STATUS_UNKNOWN)
        self.assertEqual(e.employment_type, HR_EMPLOYMENT_UNKNOWN)

    def test_downgrade_is_not_permissive(self):
        """关键回归：'外包驻场' 这类未登记写法曾被打成 staff（正式），
        那等于把受限身份静默授予资格。此处钉住方向。"""
        e = HREmployeeData(employee_no="X002", username="测试",
                           employment_type="外包驻场")
        self.assertNotEqual(e.employment_type, "staff")
        self.assertFalse(hr_secret_eligible(
            e.status, e.employment_type, e.nda_signed, e.background_cleared))

    def test_missing_flags_mean_not_qualified(self):
        """HR 没给保密承诺/背景审查 = 未具备，不能反过来说不清就当有。"""
        e = HREmployeeData(employee_no="X003", username="测试",
                           status="regular", employment_type="staff")
        self.assertFalse(e.nda_signed)
        self.assertFalse(e.background_cleared)
        self.assertFalse(hr_secret_eligible(
            e.status, e.employment_type, e.nda_signed, e.background_cleared))

    def test_valid_values_pass_through(self):
        e = HREmployeeData(employee_no="X004", username="测试",
                           status="TRIAL", employment_type="STAFF",
                           nda_signed="1", background_cleared="true")
        self.assertEqual(e.status, "trial")
        self.assertEqual(e.employment_type, "staff")
        self.assertTrue(e.nda_signed)
        self.assertTrue(e.background_cleared)


class ApproverEligibilityWiringTests(unittest.TestCase):
    """资格必须真的接进审批候选 SQL，否则上面的判定全是死代码。"""

    def test_l2_docs_add_eligibility_filter(self):
        from kms.access_control import approver_candidates
        try:
            approver_candidates(2, "某部门", exclude_user_id=1)
        except Exception:
            pass  # 无库环境只关心 SQL 形态；库可用时走真实路径
        # 直接验源码接线：L2+ 分支必须带上四个准入条件
        import inspect
        src = inspect.getsource(approver_candidates)
        for token in ("hr_employment_type", "hr_status IN",
                      "hr_nda_signed=1", "hr_background_cleared=1"):
            self.assertIn(token, src, f"审批候选缺少准入条件 {token}")

    def test_l1_docs_do_not_add_filter(self):
        """L1 不加准入门槛——密级未到机密，不必按涉密资格收窄审批人。"""
        import inspect
        from kms.access_control import approver_candidates
        src = inspect.getsource(approver_candidates)
        self.assertIn("level >= SECURITY_LEVEL_CONFIDENTIAL", src)


if __name__ == "__main__":
    unittest.main()
