"""组织与部门数据初始化（模拟真实企业场景）。

为什么需要这一步
----------------
分级判定里 `active = is_active AND department`：员工部门为空时，可见密级上界被压到
**L0**。也就是说——**只要部门数据是空的，L1 及以上的文档没有任何人能看见**，
文档定级做得再对也白做。这是定级的必要配套。

为什么走既有管线而不是自己拼 SQL
--------------------------------
`kms/hr_sync.sync_employees()` 会写 `data_source='hr_sync'`、`hr_synced_at`，
并落一条 `kms_hr_sync_logs`；`kms/org.backfill_user_orgs()` 负责按部门名解析
`org_path` 与直属上级。绕过它们直接 UPDATE 会让"数据来源"失真——
治理界面上会显示成手工改的数据，而实际是同步来的，后续排查无从下手。

本脚本只做三件事：
  1. 播种组织树（复用 kms.org.SEED_ORG_TREE，三级：公司 → 部门 → 组）
  2. 按编制表把员工分到部门（走 sync_employees）
  3. 回填 org_path 与直属上级（走 backfill_user_orgs）

编制表的设计原则
----------------
- **不改动任何人的安全职级**：职级由 HR 定义、KMS 不可修改，本脚本原样带出；
- 职级与岗位匹配：L3 任部门负责人，L2 任经理/主管，L1 为工程师/专员；
- 每个部门至少有一名 L2 及以上，保证部门内部有人能看本级资料；
- 确定性：按 (职级降序, id 升序) 分配，同样的输入必然得到同样的结果。

用法
----
    python scripts/init_org.py --survey   # 只看现状
    python scripts/init_org.py            # 演练
    python scripts/init_org.py --apply    # 真正写入
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bootstrap_env() -> str:
    """在任何依赖配置的模块被导入**之前**套用环境文件，返回所用路径。

    必须早于下方 import：config.Settings 是类属性，在 import 期即完成求值，
    先导入再改配置是无效的。本项目有 QA（rag_competition）与 KMS（enterprise_kms）
    两个独立库，打错库不报错、只静默改到错的数据上。
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env", default=str(ROOT / ".env"))
    known, _ = pre.parse_known_args()
    from scripts.service import apply_environment, load_values

    apply_environment(known.env, load_values(known.env))
    return known.env


DEFAULT_ENV = _bootstrap_env()

from app.store import MySQLStore  # noqa: E402
from kms.constants import DEPARTMENTS  # noqa: E402

SEPARATOR = "=" * 72

# 编制表：(部门, 岗位称谓, 要求的职级)
# 部门名必须取自 kms.constants.DEPARTMENTS —— org_path 的解析是按部门名匹配的，
# 写错名字会导致 backfill 解析不到组织节点。
ROSTER = [
    # --- L3：部门负责人。风控/技术/综合是治理核心部门，负责人须最高职级 ---
    ("风险控制部", "风险控制部总经理", 3),
    ("技术研发部", "技术研发部总经理", 3),
    ("综合管理部", "综合管理部总经理", 3),

    # --- L2：经理/主管，分管具体条线 ---
    ("财务管理部", "财务管理部经理", 2),
    ("产品管理部", "产品管理部经理", 2),
    ("风险控制部", "风控策略组主管", 2),

    # --- L1：工程师/专员，分布在各部门 ---
    ("技术研发部", "后端研发工程师", 1),
    ("技术研发部", "前端研发工程师", 1),
    ("技术研发部", "测试质量工程师", 1),
    ("市场拓展部", "商户服务经理", 1),
    ("市场拓展部", "移动支付专员", 1),
    ("运营支撑部", "运营支撑专员", 1),
    ("运营支撑部", "客户服务专员", 1),
    ("产品管理部", "产品设计专员", 1),
    ("财务管理部", "财务核算专员", 1),
    ("人力资源部", "人力资源专员", 1),
]

# 功能账号的部门必须与职责匹配。
# 若按序号轮转，会出现"公开文档管理员被分到研发部当工程师"这类荒谬结果，
# 与"模拟真实企业场景"的目的相悖，故对这几个职责明确的账号显式指定。
ROLE_OVERRIDES = {
    "publicadmin": ("综合管理部", "公开文档管理员"),
    "admin01": ("综合管理部", "系统管理员"),
    "admin02": ("综合管理部", "系统管理员"),
    "admin03": ("综合管理部", "系统管理员"),
    "aud01": ("风险控制部", "合规审计专员"),
}


def _level_name(level: int) -> str:
    return f"L{level}"


def survey() -> None:
    print(SEPARATOR)
    print("组织架构 · 现状盘点（只读）")
    print(SEPARATOR)
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) n FROM kms_org_nodes")
        print(f"组织节点         = {cur.fetchone()['n']}")
        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE is_active=1")
        print(f"在职员工         = {cur.fetchone()['n']}")
        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE is_active=1 "
                    "AND department IS NOT NULL AND department<>''")
        print(f"其中有部门       = {cur.fetchone()['n']}")
        cur.execute("SELECT id, employee_no, username, security_level, "
                    "business_title, department, org_path FROM kms_users "
                    "WHERE is_active=1 ORDER BY security_level DESC, id")
        print("\n  在职员工明细：")
        for r in cur.fetchall():
            print(f"    {r['employee_no']:<10} L{r['security_level']} "
                  f"{str(r['username']):<8} dept={r['department'] or '(空)':<10} "
                  f"path={r['org_path'] or '(空)'}")
        cur.execute("SELECT code, name, org_path, manager_employee_no "
                    "FROM kms_org_nodes ORDER BY org_level, id")
        nodes = cur.fetchall()
        print(f"\n  组织树（{len(nodes)} 个节点）：")
        for n in nodes[:20]:
            print(f"    {n['org_path']:<30} 负责人={n['manager_employee_no'] or '(未设)'}")


def build_plan() -> list[dict]:
    """按编制表分配员工（只读，不写库）。"""
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id, employee_no, username, security_level, business_title "
                    "FROM kms_users WHERE is_active=1 "
                    "ORDER BY security_level DESC, id")
        users = cur.fetchall()

    # 编制表按职级分组，员工也按职级从高到低取，保证职级与岗位匹配
    slots_by_level = defaultdict(list)
    for dept, title, level in ROSTER:
        slots_by_level[level].append((dept, title))

    plan, used = [], 0
    for u in users:
        level = int(u["security_level"])
        override = ROLE_OVERRIDES.get(u["employee_no"])
        if override:
            dept, title = override
        else:
            # 本职级有空位就用本职级的；否则向下找（编制表岗位数与实际人数可能不等）
            for lv in range(level, -1, -1):
                if slots_by_level.get(lv):
                    dept, title = slots_by_level[lv].pop(0)
                    break
            else:
                dept, title = None, None
        if dept is None:
            # 编制表用尽：轮转分配到各一级部门，保证部门字段不为空
            dept = DEPARTMENTS[used % len(DEPARTMENTS)]
            title = "员工"
        plan.append({"id": u["id"], "employee_no": u["employee_no"],
                     "username": u["username"], "security_level": level,
                     "department": dept, "business_title": title})
        used += 1
    return plan


def show_plan(plan: list[dict]) -> None:
    print(SEPARATOR)
    print(f"部门编制方案（演练，未写库）· 共 {len(plan)} 人")
    print(SEPARATOR)
    for p in plan:
        print(f"  {p['employee_no']:<10} L{p['security_level']} {_level_name(p['security_level']):<3}"
              f" {p['username']:<8} → {p['department']:<8} {p['business_title']}")

    by_dept = defaultdict(list)
    for p in plan:
        by_dept[p["department"]].append(p["security_level"])
    print("\n  部门人员分布：")
    for dept in DEPARTMENTS:
        if dept in by_dept:
            lv = by_dept[dept]
            print(f"    {dept:<10} {len(lv)} 人  最高 L{max(lv)}({_level_name(max(lv))})")


def apply_plan(plan: list[dict]) -> int:
    from kms import org as kms_org
    from kms.hr_sync import HREmployeeData, sync_employees

    # 1. 播种组织树
    kms_org.ensure_org_tables()
    seeded = kms_org.seed_org_tree()
    print(f"\n  组织树：{seeded['nodes']} 个节点")

    # 2. 走 HR 同步管线写入部门/称谓（不动密码、不动职级以外的治理字段）
    employees = [
        HREmployeeData(employee_no=p["employee_no"], username=p["username"],
                       department=p["department"], business_title=p["business_title"],
                       security_level=p["security_level"], is_active=True)
        for p in plan
    ]
    res = sync_employees(employees, source_type="csv_file", sync_type="full")
    print(f"  HR 同步：新建 {res['created']} / 更新 {res['updated']} / 失败 {len(res['errors'])}")
    for e in res["errors"]:
        print(f"    [失败] {e['employee_no']}: {e['error']}")

    # 3. 把各部门职级最高者设为该部门负责人，再回填 org_path / 直属上级
    best: dict[str, dict] = {}
    for p in plan:
        cur_best = best.get(p["department"])
        if cur_best is None or p["security_level"] > cur_best["security_level"]:
            best[p["department"]] = p
    with MySQLStore().transaction() as cur:
        for dept, p in best.items():
            cur.execute("UPDATE kms_org_nodes SET manager_employee_no=%s "
                        "WHERE org_path=%s", (p["employee_no"], f"银联商务/{dept}"))
    print(f"  已为 {len(best)} 个部门设置负责人")

    updated = kms_org.backfill_user_orgs()
    print(f"  组织回填：{updated} 人获得 org_path / 直属上级")
    return 1 if res["errors"] else 0


def check_visibility() -> int:
    """逐个员工统计可见文档数——这是验证初始化是否真的生效的唯一硬指标。

    分级 + 分部门 + 组织继承三者的结果都落在"这个用户能看见几篇"上。
    只改了员工部门但没给文档归属部门的话，L1 以上文档依旧 0 篇可见。
    """
    from gateway import service
    from kms import access_control as acl
    from kms.security import AuthUser

    print(SEPARATOR)
    print("可见性验证（真实库，只读）")
    print(SEPARATOR)

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) n FROM documents")
        total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM documents "
                    "WHERE owner_department IS NOT NULL AND owner_department<>''")
        with_dept = cur.fetchone()["n"]
        cur.execute("SELECT id, employee_no, username, security_level, department "
                    "FROM kms_users WHERE is_active=1 ORDER BY security_level DESC, id")
        users = cur.fetchall()

    # 发布闸门：status / lifecycle_state / publication_approved / expires_at
    # 任一不满足都会让文档不可见，且四者的失败表现完全一样（列表里没有），
    # 不打出来根本无法区分是哪一道闸挡住的。
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT d.id, d.status, d.lifecycle_state, d.publication_approved, "
                    "d.expires_at, l.level FROM documents d "
                    "LEFT JOIN kms_doc_levels l ON l.document_id=d.id ORDER BY d.id LIMIT 10")
        print("  发布闸门状态：")
        for r in cur.fetchall():
            print(f"    id={r['id']:<3} level={r['level']} status={r['status']:<10} "
                  f"lifecycle={str(r['lifecycle_state']):<10} "
                  f"approved={r['publication_approved']} expires={r['expires_at']}")

    print(f"\n文档总数 = {total}，其中有归属部门 = {with_dept}")
    if with_dept == 0 and total:
        print("  [!] 文档都没有归属部门：L1 以上文档仍然 0 篇可见")
        print("      （L1+ 需要 文档.owner_department 与员工部门匹配，或组织路径继承）")

    bad = 0
    for u in users:
        user = AuthUser(acl.get_user_by_id(u["id"]))
        try:
            r = service.documents(user, 0, user.security_level, 0, 200)
            n = r["total"]
        except Exception as e:
            n = f"错误 {type(e).__name__}"
            bad += 1
        print(f"  {u['employee_no']:<11} L{u['security_level']} "
              f"{str(u['username']):<9} {str(u['department'] or '(空)'):<10} → 可见 {n} 篇")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--survey", action="store_true", help="只读盘点")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只演练）")
    ap.add_argument("--check", action="store_true", help="逐个员工验证可见文档数")
    ap.add_argument("--env", default=DEFAULT_ENV,
                    help="环境配置文件（默认 .env=QA 库 rag_competition；"
                         "KMS 治理库须指定 .env.kms=enterprise_kms）")
    args = ap.parse_args()

    from config import settings

    print(f"环境文件 = {args.env}")
    print(f"目标库   = {settings.mysql_database}   <-- 确认这是你要操作的库")
    print()

    if args.check:
        return check_visibility()
    if args.survey:
        survey()
        return 0

    plan = build_plan()
    show_plan(plan)
    if args.apply:
        return apply_plan(plan)
    print("\n（演练模式，未写库。确认无误后加 --apply）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
