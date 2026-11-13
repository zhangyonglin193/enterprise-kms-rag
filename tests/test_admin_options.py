# -*- coding: utf-8 -*-
"""下拉选项接口的契约门禁（防"手打/写死常量"回归）。

背景
----
前端的「部门 / 密级 / 审计操作类型」三类选项，过去要么让人手打，要么在前端
写死一份常量清单。两种做法都会静默失效：

- 手打：拼错不报错，只会筛出空结果（审计筛选曾因此"查什么都查不到"）；
- 写死常量：与库中真实数据脱节——HR 新增部门后下拉里选不到，新增审计动作后
  永远筛不到，且前端无从察觉自己已经过期。

因此这三个选项改为**取自库中真实数据**（`/admin/levels` 已是如此，本次补上
`/admin/departments` 与 `/admin/audit-actions`）。

本测试守住这条契约：接口可达、字段齐全、部门条目自带在职人数与文档数
（供前端避免选到空部门）。

刻意只校验**结构不校验内容**：QA 库（rag_competition）与 KMS 库
（enterprise_kms）的数据量不同，断言具体数量会让测试随库切换而红。

运行前提
--------
本文件是**连真库**的契约门禁，不属于离线单测。库不可达时，两个依赖
库数据的用例会被**显式跳过**（skip 原因可见），而不是伪装成通过。
CI 的 offline-tests job 不提供 MySQL，也没有 .env（已 gitignore），因此
在那里这两项按设计跳过；本地配好 .env 并启动 MySQL 后它们照常执行。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

# 契约测试连真库：discover 模式下同目录离线测试会在模块导入期用 apply_environment
# 把 MYSQL_* 环境变量清空，且 config.Settings 类属性首导即冻结；这里从 .env 直接
# 回填 settings 实例属性，保证本文件无论以什么顺序被导入都能连上库。
from dotenv import dotenv_values  # noqa: E402
from config import settings  # noqa: E402

_env = dotenv_values(ROOT / ".env")
for _key in ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"):
    if _env.get(_key):
        setattr(settings, _key.lower(),
                int(_env[_key]) if _key == "MYSQL_PORT" else _env[_key])

from kms import admin_routes, security  # noqa: E402


def _contract_db_reachable() -> bool:
    """探测契约库是否可达。

    不用 mock 顶替数据库：本文件要守的正是「选项取自库中真实数据」，
    一旦用假数据喂进去，「把查询换成写死常量清单」这类回归也会照样
    通过，等于废掉门禁。所以保留真库依赖，仅在库确实不可达时跳过。
    """
    import pymysql
    try:
        conn = pymysql.connect(
            host=settings.mysql_host,
            port=int(settings.mysql_port),
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            connect_timeout=3,
        )
    except Exception:
        return False
    conn.close()
    return True


_DB_OK = _contract_db_reachable()
_SKIP_NO_DB = "契约库不可达（缺 .env 或 MySQL 未启动）：本用例需连真库，跳过而非伪造通过"


def _build_client() -> TestClient:
    """构造客户端并绕过登录。

    levels / departments 只要求已登录员工；audit-actions 已归运营审计，
    因此注入一个 L0 员工即可覆盖全部分支。
    """
    app = FastAPI()
    app.include_router(admin_routes.router)
    fake = security.AuthUser({
        "id": 1,
        "employee_no": "option-contract",
        "username": "契约测试",
        "security_level": 0,
        "level": 0,
        "department": "",
        "org_path": "",
        "is_active": 1,
        # audit-actions 已归运营审计（本系统无「管理员」角色），
        # levels / departments 仍只要求登录；注入审计员身份以覆盖全部分支。
        "hr_position_type": "auditor",
    })
    app.dependency_overrides[security.require_user] = lambda: fake
    return TestClient(app)


class OptionEndpointContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _build_client()
        self.addCleanup(self.client.close)

    def test_levels_are_fixed_four_tiers(self) -> None:
        """密级固定 L0-L3，由 HR 定义，KMS 不可增删——滑动条依赖这个前提。"""
        r = self.client.get("/kms/api/admin/levels")
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertEqual([i["level"] for i in items], [0, 1, 2, 3])
        for i in items:
            self.assertTrue(i["name"], "每档都必须有名称，滑动条刻度要用")

    @unittest.skipUnless(_DB_OK, _SKIP_NO_DB)
    def test_departments_carry_counts(self) -> None:
        """部门来自 HR 同步数据，且回带人数/文档数供前端避免选到空部门。"""
        r = self.client.get("/kms/api/admin/departments")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("hr_synced", body, "前端要据此外提示'HR 尚未同步'")
        self.assertIsInstance(body["items"], list)
        for it in body["items"]:
            self.assertTrue(it["name"])
            for key in ("employee_count", "doc_count", "in_org_tree"):
                self.assertIn(key, it, f"{it['name']} 缺少字段 {key}")

    @unittest.skipUnless(_DB_OK, _SKIP_NO_DB)
    def test_audit_actions_come_from_real_logs(self) -> None:
        """审计操作类型取自库中实际出现过的动作，不是写死的常量清单。"""
        r = self.client.get("/kms/api/audit/audit-actions")
        self.assertEqual(r.status_code, 200)
        for it in r.json()["items"]:
            self.assertTrue(it["action"])
            self.assertIsInstance(it["count"], int)
            self.assertGreater(it["count"], 0, "按出现次数分组，计数不应为 0")


if __name__ == "__main__":
    unittest.main()
