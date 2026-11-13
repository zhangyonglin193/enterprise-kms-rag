# -*- coding: utf-8 -*-
"""前后端点契约门禁（防复发）。

背景
----
KMS 前端曾调用 46 个端点，其中 38 个后端**从未实现**（工单 17 个、知识库 12 个、
通知 4 个等）。根因是竞赛演示期先堆前端 UI、后端只做核心链路，交付后无人察觉——
因为没有任何机制比对「前端调用了什么」与「后端提供了什么」。

本测试把该比对固化为 CI 门禁，采用**棘轮（ratchet）**策略：
  1. 新增缺失端点 → 直接失败（不允许再欠新债）；
  2. 缺失端点被修好或前端删掉 → 也失败，提示从 KNOWN_MISSING 移除
     （基线只许变小，不许悄悄变大）。

已知局限（诚实记录，后续可加强）
------------------------------
- **只比路径，不比 HTTP 方法**。故 `DELETE /documents/{id}` 若后端只有 GET 同路径，
  会被判为存在。补方法维度需要解析 fetchJSON 的 opts.method，留待后续。
- 只覆盖 Vue 工作台源码（frontend/src）与共享 SDK `kms-client.js` 的可静态
  捕获调用（_get/_post 首参、${this.base} 模板、fetchJSON 字面量）；
  动态拼接的 URL 无法静态捕获。
"""
from __future__ import annotations

import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "kms" / "web"
FRONTEND_SRC = ROOT / "frontend" / "src"

# ---------------------------------------------------------------------------
# 基线：曾确认缺失、尚未决策的端点（棘轮策略：只许变小，不许变大）。
#
# 现已全部清零——三项各自按「要么补后端、要么删前端」收口：
#   · /kms/api/chat/stream    → SDK askStream 改用 /chat?stream=true（后端已有 /chat）
#   · /kms/api/admin/hr-sync  → 后端**刻意从未注册**（客户端可自报密级的人事写入口，
#                               见 tests/test_enterprise.py::test_old_routes_and_hr_write_are_absent）；
#                               前端「HR 同步」表单已整体下线
#   · /kms/api/auth/de-escalate → 提权（JIT）概念整体移除；前端登出不再探测该端点
# 基线为空，即「前端调用的端点，后端全部提供」。若再欠新债，棘轮方向一会直接失败。
# ---------------------------------------------------------------------------
KNOWN_MISSING: set[str] = set()

ROUTE_RE = re.compile(r"""@\w+\.(get|post|put|delete|patch)\(\s*["']([^"']+)["']""")
PREFIX_RE = re.compile(r"""APIRouter\([^)]*prefix\s*=\s*["']([^"']+)["']""", re.S)
# Vue 工作台 AppClient：_get/_post 首参为双引号字面量（无插值）
VUE_QUOTED_RE = re.compile(r"""(?:this\._get|this\._post)\(\s*"([^"]*)""")
# _get/_post 首参为反引号模板（可含 ${...} 插值，norm() 归一为 {}）
VUE_TPL_RE = re.compile(r"""(?:this\._get|this\._post)\(\s*`([^`]*)""")
# 原始 fetch / streamSSE / postForm 的 ${this.base} 模板（与 SDK 同形）
SDK_RE = re.compile(r"""\$\{this\.base\}(/[^`'"`,\s]*)""")


def norm(path: str) -> str:
    """归一化路径：任意 ${param} / {param} → {}，去尾斜杠。"""
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path.rstrip("/") or "/"


def backend_paths() -> set[str]:
    """扫描 kms/ 与 gateway/ 下所有注册路由（解析 APIRouter 前缀后拼接）。"""
    found: set[str] = set()
    for base in ("kms", "gateway"):
        for f in (ROOT / base).rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            pm = PREFIX_RE.search(text)
            prefix = pm.group(1) if pm else ""
            for m in ROUTE_RE.finditer(text):
                found.add(norm(prefix + m.group(2)))
    return found


def frontend_paths() -> set[str]:
    """Vue 工作台（frontend/src/**/*.js）+ 共享 SDK 的静态可捕获调用。

    覆盖三类形态：
      1. AppClient 的 this._get("...") / this._post("...") 双引号字面量；
      2. this._get(`/tickets/${id}`) 反引号模板（插值归一为 {}）；
      3. fetch/streamSSE/postForm 的 `${this.base}/...` 模板（含 SDK 本体）。
    """
    paths: set[str] = set()
    for f in sorted(FRONTEND_SRC.rglob("*.js")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        # _get/_post 首参是相对 this.base（=/kms/api）的路径，须补前缀再比对
        for m in VUE_QUOTED_RE.finditer(text):
            paths.add(norm("/kms/api" + m.group(1).split("?")[0]))
        for m in VUE_TPL_RE.finditer(text):
            paths.add(norm("/kms/api" + m.group(1).split("?")[0]))
        for m in SDK_RE.finditer(text):
            # 路径可能带 query（如 /chat?stream=true），先去掉再比对
            paths.add(norm("/kms/api" + m.group(1).split("?")[0]))

    sdk = WEB / "js" / "sdk" / "kms-client.js"
    if sdk.exists():
        for m in SDK_RE.finditer(sdk.read_text(encoding="utf-8", errors="ignore")):
            paths.add(norm("/kms/api" + m.group(1).split("?")[0]))
    return {p for p in paths if p.startswith("/kms/api")}


class EndpointContractTests(unittest.TestCase):
    """前端调用的端点必须由后端提供（基线只允许收紧）。"""

    def test_backend_has_routes(self):
        """守卫：解析逻辑本身不能退化成空集，否则门禁形同虚设。"""
        self.assertGreater(len(backend_paths()), 20)
        self.assertGreater(len(frontend_paths()), 20)

    def test_no_new_missing_endpoints(self):
        """棘轮方向一：不允许出现基线之外的新缺失端点。"""
        missing = sorted(frontend_paths() - backend_paths())
        new = [p for p in missing if p not in KNOWN_MISSING]
        self.assertEqual(
            [], new,
            "前端调用了后端没有的端点，且不在已知基线内。"
            "要么补后端实现，要么删掉前端调用（不要直接加进 KNOWN_MISSING——"
            "那是欠新债）：\n  " + "\n  ".join(new),
        )

    def test_baseline_shrinks_when_fixed(self):
        """棘轮方向二：基线里的项一旦修好/删除，必须从 KNOWN_MISSING 移除。"""
        missing = frontend_paths() - backend_paths()
        stale = sorted(p for p in KNOWN_MISSING if p not in missing)
        # 端点若彻底消失（前端也不再调用），同样应清理基线
        alive = frontend_paths()
        stale += sorted(p for p in KNOWN_MISSING if p in missing and p not in alive)
        self.assertEqual(
            [], stale,
            "以下端点已不再缺失，请把它们从 KNOWN_MISSING 移除（基线只许变小）：\n  "
            + "\n  ".join(sorted(set(stale))),
        )


if __name__ == "__main__":
    unittest.main()
