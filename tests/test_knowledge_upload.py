# -*- coding: utf-8 -*-
"""知识中心与批量上传的离线契约回归。

本机离线（禁止真实 MySQL），因此不做端到端流程，只守住**设计不变量**——
这些约束一旦被破坏，就意味着越权或权限洼地：

  1. 所有新端点必须鉴权；
  2. 批量上传**不得**尊重前端传来的 level（否则成为单文件上传的绕过口）；
  3. 批次查询只能查自己的批次（文件名属于他人行为信息，泄露即越权）。
"""
from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from fastapi import params as fastapi_params

ROOT = Path(__file__).resolve().parents[1]


def _src(name: str) -> str:
    return (ROOT / "gateway" / name).read_text(encoding="utf-8")


def _first_unauthed(router, dependency):
    """返回第一个未挂载指定依赖的路由路径（全部合规则返回 None）。"""
    for route in router.routes:
        sig = inspect.signature(route.endpoint)
        ok = any(isinstance(p.default, fastapi_params.Depends)
                 and p.default.dependency is dependency
                 for p in sig.parameters.values())
        if not ok:
            return route.path
    return None


class KnowledgeContractTests(unittest.TestCase):
    def test_all_routes_require_user(self):
        from gateway.routes_knowledge import router
        from kms.security import require_user

        self.assertIsNone(_first_unauthed(router, require_user),
                          "知识中心端点缺少 require_user 鉴权")

    def test_only_derivable_endpoints_exist(self):
        """只保留有数据基础的 4 个端点——其余 6 个已随无数据基础下线。"""
        from gateway.routes_knowledge import router

        paths = {r.path for r in router.routes}
        for p in ("/kms/api/knowledge/hot",
                  "/kms/api/knowledge/analytics/overview",
                  "/kms/api/knowledge/analytics/trends",
                  "/kms/api/knowledge/personal/stats"):
            self.assertIn(p, paths)
        for p in ("/kms/api/knowledge/categories", "/kms/api/knowledge/tags",
                  "/kms/api/knowledge/top-rated",
                  "/kms/api/knowledge/personal/favorites",
                  "/kms/api/knowledge/analytics/health",
                  "/kms/api/knowledge/analytics/contributors"):
            self.assertNotIn(p, paths, f"{p} 无数据基础，不应实现")

    def test_hot_reuses_allowed(self):
        """热门榜必须复用 service.allowed，不得另写一条权限 SQL。"""
        src = _src("routes_knowledge.py")
        self.assertIn("service.allowed", src)
        self.assertNotIn("WHERE l.level <=", src)


class BatchUploadSecurityTests(unittest.TestCase):
    """批量上传最容易出的问题：成为单文件上传的权限洼地。"""

    def test_routes_require_editor(self):
        from gateway.routes_kms import editor
        from gateway.routes_upload import router

        self.assertIsNone(_first_unauthed(router, editor),
                          "批量上传端点缺少 editor 鉴权")

    def test_level_is_persisted_but_still_draft(self):
        """上传时选的密级会落库，但必须过 BLP「不下写」，且落库仍是草稿。

        本条原为 test_level_is_not_persisted，要求**忽略**前端 level、密级恒为 3。
        它防的是「批量接口尊重 level → 把敏感文档直接登记成 L0 公开，而单文件
        入口始终 L3」，即两个入口规则不一致造成的绕过口。

        该前提已变：按新交互上传者要能**选择**密级，且两个入口（单文件
        POST /documents 与批量 batch-upload）现在遵守**同一条** BLP 规则。
        绕过口因此不再靠「写死 L3」来堵，而靠以下两点，本测试改守这两点：

          1. 不下写——文档密级不得低于本人安全职级，谁都不能把文档压到比自己
             职级更低的可见档位（这是真正的 BLP 约束，比硬编码通用）；
          2. 落库一律是草稿——真正的暴露门槛是发布审批（propose → decide），
             密级选了什么都必须先过审批才可见。
        """
        src = _src("routes_upload.py")
        # 1. 不下写：低于本人职级一律拒绝
        self.assertIn("lv < int(user.security_level)", src)
        # 2. 仍登记为草稿：未经发布审批不可见
        self.assertIn("status='draft',lifecycle_state='draft'", src)

    def test_batch_status_is_owner_only(self):
        src = _src("routes_upload.py")
        self.assertIn('batch["user_id"] != user.id', src)

    def test_total_size_is_capped(self):
        """批量接口必须限制整批字节总量——否则是内存放大入口。"""
        src = _src("routes_upload.py")
        self.assertIn("_MAX_TOTAL", src)
        self.assertIn("整批总量超过上限", src)

    def test_department_is_never_written_as_null(self):
        """员工的 department 可能是 NULL，写入 NOT NULL 列前必须兜底成 ''。

        真实库的教训：`kms_users.department` 全为 NULL，直接把它写进
        `VARCHAR NOT NULL DEFAULT ''` 的列会被 MySQL 拒绝——
        列默认值只在**省略该列**时生效，显式传 NULL 仍然报错。
        """
        import re

        src = _src("routes_upload.py")
        raw = [m for m in re.findall(r"user\.department(?!\s*or\s)", src)]
        self.assertEqual([], raw,
                         "user.department 可能为空，写入前需兜底成 ''：" + str(raw))

    def test_failed_ingest_cleans_up_file(self):
        """入库失败要删掉已落盘的原文，禁止在 upload_dir 留孤儿文件。"""
        src = _src("routes_upload.py")
        self.assertIn("path.unlink(missing_ok=True)", src)


class SqlPlaceholderTests(unittest.TestCase):
    """pymysql 用 Python 的 % 做参数插值，SQL 里未转义的字面量 % 会直接报错。

    真实库上踩过两次，且两次都被 except 吞成「503 / 统计不可用」，现象与根因
    相距极远：
      1. visible_documents_sql 的 LIKE CONCAT(%s, '/%')
      2. personal_stats 的 target LIKE 'document:%'

    离线测试不连库就走不到 mogrify，因此只能用**静态不变量**守住。
    """

    def test_visible_sql_placeholders_are_balanced(self):
        """去掉 %% 之后，剩余的 % 必须恰好等于 %s 的个数。"""
        from gateway import service
        from kms.security import AuthUser

        user = AuthUser({"id": 1, "employee_no": "E", "username": "u",
                         "is_active": 1, "security_level": 3,
                         "department": "d", "org_path": ""})
        sql, _ = service.visible_documents_sql(user, 0, 3)
        stray = sql.replace("%%", "").count("%")
        self.assertEqual(
            stray, sql.count("%s"),
            f"SQL 含 {stray - sql.count('%s')} 个未转义的字面量 %（必须写成 %%）")

    def test_no_unescaped_percent_in_sql_literals(self):
        """SQL 字符串字面量里的 % 必须双写。"""
        import re

        bad = []
        for f in sorted((ROOT / "gateway").glob("*.py")):
            src = f.read_text(encoding="utf-8", errors="ignore")
            for pattern in (r"LIKE\s+'([^']*)'", r"CONCAT\([^)]*?'([^']*)'"):
                for m in re.finditer(pattern, src):
                    lit = m.group(1)
                    if "%" in lit.replace("%%", ""):
                        bad.append(f"{f.name}: '{lit}'")
        self.assertEqual([], bad,
                         "SQL 字面量含未转义的 %（需写成 %%）：\n  "
                         + "\n  ".join(sorted(set(bad))))


if __name__ == "__main__":
    unittest.main()
