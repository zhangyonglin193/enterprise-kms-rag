"""跨实例共享限流/计数契约测试（离线，零 DB / 零模型依赖）。

锁死 kms/ratelimit.py 的核心语义——它替换了原先散落在三处的**进程内**状态：

  - 固定窗口内恰好放行 limit 次（依赖原子条件 UPDATE，而非先读后写）；
  - 窗口翻页自动重置；
  - 限流非安全边界：存储不可用时 fail-open；
  - 指标按工具聚合、可跨实例累加（原子 ODKU 自增）。

注意：必须像 test_collapse_fragments 一样先 apply_environment 再 import kms.*——
config.Settings 类属性在首次导入时求值，导入顺序错误会把 KMS_*_EMPLOYEES 冻结为空，
污染其它离线测试。
"""
from __future__ import annotations

import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

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

from app.store import MySQLStore  # noqa: E402
from kms import ratelimit  # noqa: E402
import kms.apps  # noqa: E402
import kms.constants  # noqa: E402


class _FakeCursor:
    """最小 SQL 语义模拟器：只实现被测模块依赖的 MySQL 行为。

    说明：MySQL 的 ODKU / 条件 UPDATE 原子性无法在离线单测里真实验证（项目红线
    禁止连真实 DB），这里模拟其**可观察语义**，从而锁死调用方的逻辑（语句顺序、
    窗口计算、rowcount 判定、翻页重置、fail-open）。
    """

    def __init__(self, buckets: dict, metrics: dict):
        self._buckets = buckets
        self._metrics = metrics
        self.rowcount = 0
        self._rows: list = []
        self.deletes = 0

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        params = params or ()
        self.rowcount = 0
        if sql.startswith("INSERT INTO kms_rate_buckets"):
            # ODKU：窗口变化则重置计数，随后推进窗口
            key, window = params
            row = self._buckets.setdefault(key, {"window_start": None, "count": 0})
            if row["window_start"] != window:
                row["window_start"] = window
                row["count"] = 0
            self.rowcount = 1
        elif sql.startswith("UPDATE kms_rate_buckets SET count = count + 1"):
            # 条件自增：仅当同窗口且未达上限才 +1
            key, window, limit = params
            row = self._buckets.get(key)
            if row and row["window_start"] == window and row["count"] < limit:
                row["count"] += 1
                self.rowcount = 1
        elif sql.startswith("DELETE FROM kms_rate_buckets"):
            cutoff, = params
            self.deletes += 1
            for key in [k for k, v in self._buckets.items()
                        if v["window_start"] is not None and v["window_start"] < cutoff]:
                del self._buckets[key]
        elif sql.startswith("SELECT metric_key"):
            self._rows = [{"metric_key": k, "val": v} for k, v in self._metrics.items()]
        elif sql.startswith("CREATE TABLE"):
            pass
        return self.rowcount

    def executemany(self, sql, seq):
        sql = " ".join(sql.split())
        if sql.startswith("INSERT INTO kms_metric_counters"):
            for key, val in seq:
                self._metrics[key] = self._metrics.get(key, 0.0) + float(val)

    def fetchall(self):
        return list(self._rows)


class _SharedLimiterCase(unittest.TestCase):
    def setUp(self):
        self.buckets: dict = {}
        self.metrics: dict = {}
        self.cursor = _FakeCursor(self.buckets, self.metrics)

        @contextmanager
        def _conn(self_store):
            yield self.cursor

        # 表已就绪（离线不建真表）+ 连接走模拟器
        self.enterContext(patch.object(ratelimit, "ensure_ratelimit_tables", return_value=True))
        self.enterContext(patch.object(MySQLStore, "_conn", _conn))
        # 模块级 GC 记录跨用例残留，需重置
        self.enterContext(patch.object(ratelimit, "_last_gc_window", -1))


class FixedWindowTests(_SharedLimiterCase):
    def test_allows_exactly_limit_per_window(self):
        self.assertEqual(
            [ratelimit.allow("ip:1.1.1.1", 3) for _ in range(5)],
            [True, True, True, False, False])

    def test_different_keys_are_independent(self):
        self.assertTrue(ratelimit.allow("ip:1.1.1.1", 1))
        self.assertFalse(ratelimit.allow("ip:1.1.1.1", 1))
        self.assertTrue(ratelimit.allow("ip:2.2.2.2", 1))  # 互不影响

    def test_window_rollover_resets_quota(self):
        base = ratelimit._window_index(60)
        with patch.object(ratelimit.time, "time", return_value=base * 60):
            self.assertTrue(ratelimit.allow("k", 1))
            self.assertFalse(ratelimit.allow("k", 1))
        # 推进一个窗口 → 配额重置
        with patch.object(ratelimit.time, "time", return_value=(base + 1) * 60):
            self.assertTrue(ratelimit.allow("k", 1))

    def test_non_positive_limit_always_denies(self):
        self.assertFalse(ratelimit.allow("k", 0))
        self.assertFalse(ratelimit.allow("k", -1))

    def test_garbage_collection_runs_once_per_window(self):
        base = ratelimit._window_index(60)
        with patch.object(ratelimit.time, "time", return_value=base * 60):
            for _ in range(4):
                ratelimit.allow("k", 100)
        # 同一窗口内只清理一次，不随请求数放大
        self.assertEqual(self.cursor.deletes, 1)

    def test_expired_rows_are_reclaimed(self):
        base = ratelimit._window_index(60)
        with patch.object(ratelimit.time, "time", return_value=base * 60):
            ratelimit.allow("old", 100)
        # 推进 3 个窗口后再请求 → 旧窗口行被清理
        with patch.object(ratelimit.time, "time", return_value=(base + 3) * 60):
            ratelimit.allow("new", 100)
        self.assertNotIn("old", self.buckets)
        self.assertIn("new", self.buckets)


class FailOpenTests(_SharedLimiterCase):
    def test_storage_outage_fails_open(self):
        """限流不是安全边界：DB 不可用时应放行，而非把故障放大为全面拒绝。"""
        @contextmanager
        def _broken(self_store):
            raise OSError("mysql down")

        with patch.object(MySQLStore, "_conn", _broken):
            self.assertTrue(ratelimit.allow("ip:1.1.1.1", 1))
            self.assertTrue(ratelimit.allow("ip:1.1.1.1", 1))  # 连续放行

    def test_metrics_outage_does_not_raise(self):
        @contextmanager
        def _broken(self_store):
            raise OSError("mysql down")

        with patch.object(MySQLStore, "_conn", _broken):
            ratelimit.record_metrics("search", True, 10.0)          # 不抛错
            self.assertEqual(ratelimit.metrics_snapshot()["calls"], 0)


class MetricsTests(_SharedLimiterCase):
    def test_counters_accumulate_across_instances(self):
        # 模拟两个实例各自上报：共享计数应当叠加
        ratelimit.record_metrics("search", True, 100.0)
        ratelimit.record_metrics("search", False, 200.0)
        snap = ratelimit.metrics_snapshot()
        self.assertEqual(snap["calls"], 2)
        self.assertEqual(snap["errors"], 1)
        self.assertEqual(snap["avg_ms"], 150.0)
        self.assertEqual(snap["by_tool"]["search"]["calls"], 2)
        self.assertEqual(snap["by_tool"]["search"]["errors"], 1)
        self.assertEqual(snap["by_tool"]["search"]["avg_ms"], 150.0)

    def test_per_tool_breakdown_is_isolated(self):
        ratelimit.record_metrics("search", True, 10.0)
        ratelimit.record_metrics("recommend", True, 30.0)
        snap = ratelimit.metrics_snapshot()
        self.assertEqual(set(snap["by_tool"]), {"search", "recommend"})
        self.assertEqual(snap["by_tool"]["recommend"]["avg_ms"], 30.0)

    def test_empty_snapshot_is_zeroed_not_divided_by_zero(self):
        snap = ratelimit.metrics_snapshot()
        self.assertEqual((snap["calls"], snap["errors"], snap["avg_ms"]), (0, 0, 0.0))

    def test_tool_name_is_sanitized(self):
        """工具名进入主键，必须限制字符集与长度，避免无界基数/异常键。"""
        ratelimit.record_metrics("weird name/with spaces", True, 5.0)
        self.assertTrue(all(ch.isalnum() or ch in "._-" for ch in
                            "".join(self.metrics).replace("tool.", "").replace(".calls", "")))


class PolicyTests(unittest.TestCase):
    """策略注册表契约——限流「可复用」的核心保证。

    改造前配额散落在 middleware（魔法数 *5）、routes_embed、mcp、kms/apps
    （硬编码 60）四处，同一个应用级限流存在两个互不知情的配额来源。
    以下断言锁死：配额与键构造规则只有一份，且新增端点接入不必接触数字。
    """

    def test_registered_policies_cover_every_call_site(self):
        self.assertTrue({"gw.ip", "gw.app", "gw.mcp", "kms.apikey"}
                        <= set(ratelimit.policies()))

    def test_key_spaces_are_isolated(self):
        """同名主体在不同策略下不得共用桶——否则会互相挤占对方配额。"""
        keys = {name: p.key_for("abc") for name, p in ratelimit.policies().items()}
        self.assertEqual(len(set(keys.values())), len(keys))

    def test_empty_subject_does_not_collapse_into_one_bucket(self):
        """主体缺失时若用空串，所有匿名主体会共用一个桶，把「按主体限流」
        退化成「全局限流」。必须落到显式 anonymous。"""
        p = ratelimit.policy("gw.app")
        self.assertEqual(p.key_for(""), p.key_for(None))
        self.assertTrue(p.key_for("").endswith(":anonymous"))

    def test_unknown_policy_degrades_instead_of_raising(self):
        """限流不该成为新的故障点：漏登记时降级为基准配额，不抛 KeyError。"""
        self.assertGreater(ratelimit.policy("nonexistent").limit, 0)

    def test_ip_policy_is_more_permissive_than_base(self):
        """IP 被 NAT/出口网关共享，配额需按倍率放宽（该倍率此前是散落的魔法数）。"""
        base = ratelimit.policy("gw.app").limit
        self.assertEqual(ratelimit.policy("gw.ip").limit,
                         base * ratelimit.IP_LIMIT_MULTIPLIER)

    def test_check_delegates_with_policy_key_and_limit(self):
        """调用方只给 (策略名, 主体)，键与配额由策略注入。"""
        with patch.object(ratelimit, "allow", return_value=True) as mocked:
            ratelimit.check("gw.app", "A1")
        mocked.assert_called_once_with("app:A1",
                                       ratelimit.policy("gw.app").limit,
                                       ratelimit.DEFAULT_WINDOW)

    def test_quota_has_single_source_of_truth(self):
        """配额不得在调用点硬编码——两处历史常量必须已移除。"""
        self.assertFalse(hasattr(kms.apps, "RATE_LIMIT_PER_MINUTE"))
        self.assertFalse(hasattr(kms.constants, "RATE_LIMIT_PER_MINUTE"))


if __name__ == "__main__":
    unittest.main()
