# -*- coding: utf-8 -*-
"""模拟外部 HR 系统的 HTTP 服务（供 KMS 的 hr_api 目录源拉取）。

定位
----
这不是业务接口，而是**演示 / 联调用的人事主数据源头**。真实环境里它对应
甲方 HR 系统；这里用同一套数据结构把行为演出来，用于验证：

  1. KMS 以 Pull 方式接入，凭据只来自 `.env`，客户端无法经业务接口上报人事数据；
  2. 适配器字段兼容规则是否真的生效（中英文列名、未登记取值降级）；
  3. `sync_directory()` → `sync_employees()` → `kms_hr_sync_logs` 全链路是否通。

端点（与 HrApiDirectoryAdapter 约定一致）
--------------------------------------
    GET /health        → {"status": "ok"}
    GET /org/nodes     → {"org_nodes": [...]}
    GET /employees     → {"employees": [...]}

后两者要求 `Authorization: Bearer <KMS_HR_API_TOKEN>`；token 不配时拒绝服务
（宁可起不来，也不要裸奔——模拟源也是源）。

用法
----
    python scripts/mock_hr_service.py --port 6399 --token dev-hr-token

数据来源：直接读 enterprise_kms 的 kms_users / kms_org_nodes，
即"HR 是人事主数据的源头，KMS 只是引用方"这一关系的可运行写照。

安全说明：仅监听 127.0.0.1，不对外暴露；生产不应使用本脚本。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.service import load_values  # noqa: E402

for _k, _v in load_values(".env.kms").items():
    os.environ.setdefault(_k, _v)

from app.store import MySQLStore  # noqa: E402

TOKEN = ""


def _employees() -> list:
    """把 kms_users 翻成 HR 字段名（中英文混排，顺便验证兼容规则）。"""
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT * FROM kms_users WHERE is_active=1 ORDER BY id")
        rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "employee_no": r["employee_no"],
            "工号": r["employee_no"],          # 故意给中文列名，验证兼容
            "username": r["username"],
            "department": r["department"],
            "业务称谓": r.get("business_title") or "",
            "security_level": r["security_level"],
            "is_active": 1,
            "position_type": r.get("hr_position_type") or "staff",
            "hr_status": r.get("hr_status") or "regular",
            "hr_employment_type": r.get("hr_employment_type") or "staff",
            "hr_manager_no": r.get("hr_manager_no") or "",
            "hr_job_family": r.get("hr_job_family") or "professional",
            "hr_job_grade": r.get("hr_job_grade") or "",
            "hr_hire_date": str(r.get("hr_hire_date") or ""),
            "hr_nda_signed": 1 if r.get("hr_nda_signed") else 0,
            "hr_background_cleared": 1 if r.get("hr_background_cleared") else 0,
        })
    return out


def _org_nodes() -> list:
    """按真实 HR 系统的样子吐组织节点：父节点用 **code** 而非 id。

    适配器输出的是 parent_code，由 sync_directory 负责解析成 parent_id；
    这里若直接吐 id，等于替上游做了不该做的转换，也就测不到解析逻辑。
    """
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT n.code, n.name, p.code AS parent, n.org_type, "
            "n.manager_employee_no FROM kms_org_nodes n "
            "LEFT JOIN kms_org_nodes p ON p.id = n.parent_id ORDER BY n.id")
        return [dict(r) for r in cur.fetchall()]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静音默认访问日志
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, {"status": "ok"})
            return
        auth = self.headers.get("authorization") or ""
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or token != TOKEN:
            self._send(401, {"detail": "需要 Bearer Token"})
            return
        path = self.path.split("?")[0]
        if path == "/org/nodes":
            self._send(200, {"org_nodes": _org_nodes()})
        elif path == "/employees":
            self._send(200, {"employees": _employees()})
        else:
            self._send(404, {"detail": f"未知路径: {path}"})


def main() -> int:
    global TOKEN
    ap = argparse.ArgumentParser(description="模拟外部 HR 系统 HTTP 服务")
    ap.add_argument("--port", type=int, default=6399)
    ap.add_argument("--host", default="127.0.0.1", help="仅监听回环，不对外暴露")
    ap.add_argument("--token", default=os.getenv("KMS_HR_API_TOKEN", ""),
                    help="Bearer Token；不提供则拒绝启动")
    args = ap.parse_args()

    if not args.token:
        print("!!! 未提供 --token 且环境变量 KMS_HR_API_TOKEN 为空，拒绝启动"
              "（模拟源也是源，不能裸奔）")
        return 2
    TOKEN = args.token

    srv = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"模拟 HR 服务已启动: http://{args.host}:{args.port}  "
          f"(org_nodes={len(_org_nodes())}, employees={len(_employees())})")
    print("按 Ctrl+C 停止。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
