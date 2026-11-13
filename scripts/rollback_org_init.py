"""回滚 init_org.py 写入的组织/部门数据（把员工恢复成"无部门"状态）。

背景
----
2026-10-18 误对 QA 库（rag_competition）执行了 init_org.py --apply：
脚本当时未加载 .env.kms，走默认 .env 打到了 QA 库，而非 KMS 治理库
（enterprise_kms）。现按要求还原。

还原基准（不是猜的）
--------------------
同库 3 个**未被触碰**的停用账号（superadmin / auditadmin / emp_test01）保留着
原始形态，可直接作为基准：

    business_title = 空
    data_source    = local
    hr_synced_at   = NULL
    department     = 空（与当时 init_classify --survey 报的"有部门=0"一致）

被改的 16 名在职员工当时均为：department 空、org_path 空。
因此还原目标 = 上述基准 + org_node_id / manager_employee_no 置 NULL。

不删除的内容
------------
- kms_org_nodes 的 19 个节点：seed_org_tree() 幂等写入的组织树。
  它是参考数据、无副作用，且无法确证写入前该表是否已有内容，
  贸然删除可能误删既有数据。确需清理请用 --drop-org-nodes 显式指定。
- kms_hr_sync_logs 由 --drop-sync-log 控制，默认保留以便追溯"发生过同步"。

用法
----
    python scripts/rollback_org_init.py --env .env            # 演练
    python scripts/rollback_org_init.py --env .env --apply    # 真正回滚
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bootstrap_env() -> str:
    """在任何依赖配置的模块被导入**之前**套用环境（config 于 import 期求值）。"""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env", default=str(ROOT / ".env"))
    known, _ = pre.parse_known_args()
    from scripts.service import apply_environment, load_values

    apply_environment(known.env, load_values(known.env))
    return known.env


DEFAULT_ENV = _bootstrap_env()

from app.store import MySQLStore  # noqa: E402

SEPARATOR = "=" * 72

# 由 init_org.py --apply 判定的"被本次同步写入"的判定条件，
# 与还原基准一致：只动 hr_sync 来源且带同步时间的在职员工，绝不波及他人。
TARGET_WHERE = "data_source='hr_sync' AND hr_synced_at IS NOT NULL"


def preview() -> list[dict]:
    with MySQLStore()._conn() as cur:
        cur.execute(f"SELECT id, employee_no, username, department, org_path, "
                    f"business_title FROM kms_users WHERE {TARGET_WHERE} ORDER BY id")
        return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="真正回滚（默认只演练）")
    ap.add_argument("--drop-org-nodes", action="store_true",
                    help="一并清空 kms_org_nodes（无法确证写入前是否已有内容，默认保留）")
    ap.add_argument("--drop-sync-log", action="store_true",
                    help="一并删除本次产生的 HR 同步日志")
    ap.add_argument("--env", default=DEFAULT_ENV,
                    help="环境配置文件（QA 库用 .env，KMS 库用 .env.kms）")
    args = ap.parse_args()

    from config import settings

    print(f"环境文件 = {args.env}")
    print(f"目标库   = {settings.mysql_database}   <-- 确认这是你要回滚的库")
    print()

    targets = preview()
    print(SEPARATOR)
    print(f"回滚对象（{TARGET_WHERE}）· 共 {len(targets)} 人")
    print(SEPARATOR)
    for t in targets:
        print(f"  {t['employee_no']:<11} {str(t['username']):<9} "
              f"dept={t['department'] or '(空)':<10} path={t['org_path'] or '(空)'}")
    if not targets:
        print("  没有符合条件的对象，无需回滚")
        return 0

    print("\n将还原为：department='' / org_path='' / org_node_id=NULL / "
          "manager_employee_no=NULL")
    print("          business_title='' / data_source='local' / hr_synced_at=NULL")

    if not args.apply:
        print("\n（演练模式，未写库。确认无误后加 --apply）")
        return 0

    with MySQLStore().transaction() as cur:
        cur.execute(
            "UPDATE kms_users SET department='', org_path='', org_node_id=NULL, "
            f"manager_employee_no=NULL, business_title='', data_source='local', "
            f"hr_synced_at=NULL WHERE {TARGET_WHERE}")
        n = cur.rowcount
    print(f"\n已还原 {n} 名员工")

    if args.drop_org_nodes:
        with MySQLStore().transaction() as cur:
            cur.execute("DELETE FROM kms_org_nodes")
            print(f"已清空 kms_org_nodes（{cur.rowcount} 个节点）")
    if args.drop_sync_log:
        with MySQLStore().transaction() as cur:
            cur.execute("DELETE FROM kms_hr_sync_logs")
            print(f"已清空 kms_hr_sync_logs（{cur.rowcount} 条）")

    left = preview()
    print(f"复查：仍带部门数据的员工 = {len(left)}")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
