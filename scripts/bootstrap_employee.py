"""受控试点的离线员工初始化：依据已复核 HR 清单，不覆盖现有员工。"""
from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.service import apply_environment, deployment_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=str(ROOT / ".env.kms"))
    parser.add_argument("--qa-env", default=str(ROOT / ".env"))
    parser.add_argument("--employee-no", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--department", required=True)
    parser.add_argument("--level", required=True, type=int, choices=range(4))
    parser.add_argument("--approval-ref", required=True, help="线下人事及权限审批凭据编号，不是系统自动审批")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", args.employee_no):
            raise ValueError("工号格式无效")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", args.approval_ref):
            raise ValueError("审批编号格式无效")
        if not args.name.strip() or len(args.name) > 64 or not args.department.strip() or len(args.department) > 128:
            raise ValueError("姓名或部门格式无效")
        _, values = deployment_values(args.qa_env, args.env)
        apply_environment(args.env, values)
        from app.store import MySQLStore
        from kms.security import hash_password
        from gateway.audit import ensure_gw_audit_table, log_gw_event, new_request_id
        if not ensure_gw_audit_table():
            raise RuntimeError("审计表未就绪，请先完成 KMS 首次启动")
        password = getpass.getpass("输入员工初始密码（不回显，12～128位、字母及数字）：")
        if not 12 <= len(password) <= 128 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise ValueError("密码强度不符合要求")
        if password != getpass.getpass("再次输入："):
            raise ValueError("两次密码不一致")
        digest = hash_password(password)
        password = ""
        rid = new_request_id()
        target = f"employee:{args.employee_no}"
        detail = f"approval={args.approval_ref};os_operator={getpass.getuser()}"
        log_gw_event("kms", "bootstrap_started", rid, target=target, detail=detail)
        with MySQLStore().transaction() as cur:
            cur.execute("SELECT id FROM kms_users WHERE employee_no=%s FOR UPDATE", (args.employee_no,))
            if cur.fetchone():
                raise ValueError("员工已存在，拒绝覆盖；请走单独的身份恢复流程")
            cur.execute("INSERT INTO kms_users(employee_no,username,password_hash,role,security_level,department,is_active,data_source) "
                        "VALUES(%s,%s,%s,'employee',%s,%s,1,'approved_import')",
                        (args.employee_no, args.name.strip(), digest, args.level, args.department.strip()))
        log_gw_event("kms", "bootstrap_finished", rid, target=target, detail=detail)
        print(f"员工初始化完成，请通过保密渠道交付密码并要求登录后修改。审计请求号：{rid}")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"初始化未完成：{exc}；如已提交数据库，请先核对记录，勿盲目重试。", file=sys.stderr)
        return 1
    except Exception:
        print("初始化失败，请运维核对数据库与审计；不输出连接凭据或 SQL。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
