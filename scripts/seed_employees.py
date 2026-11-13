"""银联商务 KMS 演示员工种子数据。

工号规则: 2026 + 四位数字（从 0000 开始），如 20260000, 20260001
初始密码: 与工号相同（便于展示和登录）
部门和职位: 参照银联商务组织架构

在 run_kms.py 启动时自动调用 seed_demo_employees()（幂等）。
也可独立运行: python scripts/seed_employees.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    # 数据隔离保护（AGENTS.md）：独立运行时必须先注入 KMS 配置再触发 config 加载。
    # 否则 config 默认读 .env（QA 评测库），会把演示员工误写进赛题数据库。
    import os as _os
    from scripts.service import load_values as _load_values
    for _k, _v in _load_values(str(ROOT / ".env.kms")).items():
        _os.environ.setdefault(_k, _v)

from app.logger import get_logger

logger = get_logger("kms.seed")


# ===================== 演示员工花名册 =====================
# (姓名, 部门, 业务称谓, 安全职级)
# 覆盖 8 个部门、多个职级，确保工单自动流转有足够候选审批人
DEMO_EMPLOYEES = [
    # ---- 产品管理部 ----
    ("张明远", "产品管理部", "初级专员", 0),
    ("李思琪", "产品管理部", "高级专员", 1),
    ("王建华", "产品管理部", "主管", 2),

    # ---- 技术研发部 ----
    ("陈晓峰", "技术研发部", "专员", 0),
    ("刘志强", "技术研发部", "高级专员", 1),
    ("赵海涛", "技术研发部", "资深专员", 1),
    ("孙丽萍", "技术研发部", "副主管", 1),
    ("周国强", "技术研发部", "主管", 2),
    ("吴永明", "技术研发部", "经理", 2),

    # ---- 市场拓展部 ----
    ("郑小红", "市场拓展部", "专员", 0),
    ("黄大伟", "市场拓展部", "高级专员", 1),
    ("林晓东", "市场拓展部", "主管", 2),

    # ---- 运营支撑部 ----
    ("杨秀英", "运营支撑部", "专员", 0),
    ("朱建华", "运营支撑部", "高级专员", 1),
    ("何国强", "运营支撑部", "主管", 2),

    # ---- 风险控制部 ----
    ("马丽娟", "风险控制部", "专员", 0),
    ("胡志远", "风险控制部", "高级专员", 1),
    ("高明辉", "风险控制部", "副主管", 1),
    ("梁国安", "风险控制部", "主管", 2),
    ("谢建华", "风险控制部", "高级经理", 3),

    # ---- 财务管理部 ----
    ("宋美龄", "财务管理部", "专员", 0),
    ("唐国强", "财务管理部", "高级专员", 1),
    ("韩志远", "财务管理部", "主管", 2),

    # ---- 人力资源部 ----
    ("冯丽娟", "人力资源部", "专员", 0),
    ("董建华", "人力资源部", "高级专员", 1),
    ("程国栋", "人力资源部", "主管", 2),

    # ---- 综合管理部 ----
    ("沈小红", "综合管理部", "专员", 0),
    ("魏志远", "综合管理部", "高级专员", 1),
    ("陆国安", "综合管理部", "主管", 2),

    # ---- 竞赛演示补充：风险控制部双 L3（模拟 HR 主数据）----
    # 追加在末尾以保证既有工号索引不变；与 20260019 同部门、同 L3，
    # 保证「维护员 / 审批员 / 审计员」三角色可分，审批链可演示。
    ("高志远", "风险控制部", "高级经理", 3),
    ("秦思远", "风险控制部", "高级经理", 3),
]


def _make_employee_no(index: int) -> str:
    """生成员工工号: 2026 + 四位数字。"""
    return f"2026{index:04d}"


def _guard_not_qa_database() -> None:
    """数据隔离兜底（AGENTS.md）：演示员工只能播种进 KMS 库。

    对照 .env（QA 配置）中的 MYSQL_DATABASE，若当前连接的库与其相同则拒绝执行，
    防止 .env.kms 误配或独立运行缺省时把员工数据写进赛题评测库。
    """
    from config import settings
    from scripts.service import load_values
    qa_db = (load_values(str(ROOT / ".env")) or {}).get("MYSQL_DATABASE", "")
    if qa_db and settings.mysql_database == qa_db:
        raise SystemExit(
            f"拒绝在 QA 评测库({settings.mysql_database})播种演示员工（QA/KMS 数据隔离约束）。"
            "请检查 .env.kms 的 MYSQL_DATABASE，或独立运行前设置 RAG_ENV_FILE 指向 .env.kms。"
        )


def seed_demo_employees() -> dict:
    """播种演示员工（幂等：已存在的工号跳过）。

    Returns:
        {"created": int, "skipped": int, "errors": list}
    """
    from kms import access_control as acl

    _guard_not_qa_database()
    result = {"created": 0, "skipped": 0, "errors": []}

    for idx, (username, department, business_title, security_level) in enumerate(DEMO_EMPLOYEES):
        employee_no = _make_employee_no(idx)
        try:
            existing = acl.get_user_by_employee_no(employee_no)
            if existing:
                result["skipped"] += 1
                continue

            # 初始密码 = 工号（便于展示登录）
            acl.create_user(
                employee_no=employee_no,
                username=username,
                password=employee_no,
                security_level=security_level,
                department=department,
                business_title=business_title,
            )
            result["created"] += 1
            logger.debug(f"创建演示员工: {employee_no} {username} ({department}/{business_title} L{security_level})")

        except Exception as e:
            result["errors"].append({"employee_no": employee_no, "error": str(e)})
            logger.warning(f"创建演示员工失败: {employee_no} - {e}")

    # 补充 HR 同步标记（演示员工来自本地初始化，模拟 HR 同步数据）
    if result["created"] > 0:
        try:
            from app.store import MySQLStore
            from datetime import datetime
            mysql = MySQLStore()
            with mysql._conn() as cur:
                cur.execute(
                    "UPDATE kms_users SET data_source='hr_sync', hr_synced_at=%s "
                    "WHERE data_source='local' AND employee_no LIKE '2026%%'",
                    (datetime.now(),),
                )
        except Exception as e:
            logger.warning(f"更新演示员工数据来源标记失败: {e}")

    logger.info(
        f"演示员工播种完成: created={result['created']}, "
        f"skipped={result['skipped']}, errors={len(result['errors'])}"
    )
    return result


def get_demo_login_guide() -> str:
    """生成演示登录指南（启动日志输出）。"""
    lines = [
        "=" * 60,
        "银联商务 KMS 演示账号（工号即密码）",
        "=" * 60,
        f"{'工号':<12} {'姓名':<10} {'部门':<12} {'职位':<10} {'职级':<6}",
        "-" * 60,
    ]
    for idx, (username, department, business_title, security_level) in enumerate(DEMO_EMPLOYEES):
        emp_no = _make_employee_no(idx)
        lines.append(f"{emp_no:<12} {username:<10} {department:<12} {business_title:<10} L{security_level}")
    lines.append("-" * 60)
    lines.append(f"共 {len(DEMO_EMPLOYEES)} 个演示账号，密码与工号相同")
    lines.append("示例登录: 工号 20260000 密码 20260000（张明远/产品管理部/初级专员）")
    lines.append("=" * 60)
    return "\n".join(lines)


# ===================== 独立运行入口 =====================
if __name__ == "__main__":
    from kms.access_control import ensure_kms_acl_tables
    ensure_kms_acl_tables()
    result = seed_demo_employees()
    print(get_demo_login_guide())
    print(f"\n结果: {result}")
