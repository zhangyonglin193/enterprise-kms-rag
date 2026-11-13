"""跨实例共享限流与指标计数（企业级：把共享状态移出进程内存）。

为什么需要这个模块
------------------
原实现把限流桶与 MCP 指标存在**进程内存**里（gateway/middleware._buckets、
kms/apps._rate_buckets、gateway/mcp/server._METRICS）。单实例下正确，但一旦
按企业常规方式部署为多 worker / 多实例，语义就错了：

  - 限流配额被放大成 N 倍（每个进程各自计数）→ 限流形同虚设；
  - `/metrics` 只能看到请求恰好命中的那一个实例，无法跨实例聚合。

本模块把共享状态下沉到 **MySQL**（已部署，零新增基础设施），用「原子条件更新」
保证并发正确性——语义等价于 Redis 的 INCR/EXPIRE，但不引入新组件与运维负担。

为什么放在 kms/
---------------
按工程实践这属于基础设施层，但 `app/` 是冻结面（CI 守卫）不可改动；既有依赖
方向为 `gateway -> kms -> app`。放在 kms 可让 gateway 与 kms/apps 同时复用，
且不产生反向依赖或导入环（gateway/__init__ 会导入 routes→kms，反向导入会成环）。

分层
----
    策略层  check(name, subject) / policies()   —— 命名配额，唯一事实源
    算法层  allow(key, limit, window)           —— 固定窗口，原子取令牌
    存储层  _conn()                             —— 唯一存储接缝

新增端点接入限流只需两步：在 `_POLICY_SPECS` 登记一行，在端点调 `check()`。
调用方无需知道配额数字、窗口长度或键的构造规则。

失败语义
--------
**限流不是安全边界**（认证与授权才是）。MySQL 不可用时 fail-open：放行并告警，
避免把基础设施抖动放大成全面不可用；同理指标写入失败只告警不计入。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.logger import get_logger
from app.store import MySQLStore
from config import settings

logger = get_logger("kms.ratelimit")

DEFAULT_WINDOW = 60  # 秒

# ===================== DDL（幂等） =====================
_DDL: List[str] = [
    """CREATE TABLE IF NOT EXISTS kms_rate_buckets (
        bucket_key VARCHAR(191) NOT NULL COMMENT '限流键（如 ip:1.2.3.4 / app:xxx）',
        window_start BIGINT NOT NULL COMMENT '窗口序号 = floor(unixtime/window)',
        count INT NOT NULL DEFAULT 0 COMMENT '当前窗口已用配额',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (bucket_key),
        INDEX idx_rl_window (window_start)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='跨实例限流计数（固定窗口）';""",
    """CREATE TABLE IF NOT EXISTS kms_metric_counters (
        metric_key VARCHAR(191) NOT NULL COMMENT '计数键（calls/errors/tool.<name>.calls...）',
        val DOUBLE NOT NULL DEFAULT 0 COMMENT '累计值',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (metric_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='跨实例指标累加计数';""",
]


# ===================== 存储层：唯一接缝 =====================
def _conn():
    """限流/计数的存储访问接缝——全模块只此一处与存储耦合。

    当前复用业务连接池。理由（实测权衡，非默认选择）：
      - 判定只需 1~2 条主键 SQL，占用连接为亚毫秒级；网关量级（默认 60 次/分钟）
        下 20 个连接的业务池远不会成为争抢点；
      - 复用可继承 `tests/` 对 `MySQLStore._get_pool` 的离线保护网，不会出现
        「忘了打桩就真连库」的测试空洞。

    何时该换成独立 PooledDB（舱壁隔离 bulkhead）：观测到网关 QPS 上升到使业务
    连接池成为瓶颈（限流判定自身开始排队等待连接）。届时只改本函数即可，
    但**必须同步扩展 tests 的离线保护网**，否则测试会真的尝试连接 MySQL。
    """
    return MySQLStore()._conn()


_ready = False
_ready_lock = threading.Lock()
_warned = False

# 过期窗口行清理：每进程每窗口最多执行一次 DELETE，避免表无界增长
_gc_lock = threading.Lock()
_last_gc_window = -1


def ensure_ratelimit_tables() -> bool:
    """建共享限流/计数表（幂等）。MySQL 不可用时返回 False 并降级。"""
    global _ready, _warned
    if _ready:
        return True
    with _ready_lock:
        if _ready:
            return True
        try:
            with _conn() as cur:
                for ddl in _DDL:
                    cur.execute(ddl)
            _ready = True
            logger.info("共享限流/指标计数表就绪（跨实例一致）")
            return True
        except Exception as e:
            if not _warned:
                logger.warning(f"共享限流表初始化失败（将 fail-open 降级）: {e}")
                _warned = True
            return False


def _window_index(window: int, now: float | None = None) -> int:
    """当前窗口序号（固定窗口，按 unix 时间整除，多实例天然对齐）。"""
    return int((now if now is not None else time.time()) // window)


def allow(key: str, limit: int, window: int = DEFAULT_WINDOW) -> bool:
    """跨实例固定窗口限流：True 表示放行（并占用一个配额）。

    两条原子语句，靠 InnoDB 行锁串行化并发：
      1. ODKU 保证行存在；窗口翻页时把 count 归零。
      2. 条件 UPDATE —— 仅当 `count < limit` 才自增，用 rowcount 判定是否抢到令牌。
         因此并发下恰好 limit 个请求拿到 rowcount=1。

    为何固定 2 条 SQL 而不做「先 UPDATE、失败再建行」的单条快路径：
    快路径在正常流量下是 1 条，但**配额耗尽时会退化成 3 条**；而配额耗尽恰恰
    发生在突发流量/刷接口时——限流最该省资源的时刻反而最慢，与限流目的相悖。
    恒定 2 条使开销与攻击强度无关，行为可预测。
    """
    if limit <= 0:
        return False
    ensure_ratelimit_tables()
    w = _window_index(window)
    try:
        with _conn() as cur:
            # 1) 开行 / 翻页重置。
            #    注意：ODKU 的赋值按书写顺序求值——count 表达式里的 window_start
            #    仍是旧值，故可据此判断是否翻页；随后才把 window_start 推进到新窗口。
            cur.execute(
                "INSERT INTO kms_rate_buckets (bucket_key, window_start, count) "
                "VALUES (%s, %s, 0) ON DUPLICATE KEY UPDATE "
                "count = IF(window_start <> VALUES(window_start), 0, count), "
                "window_start = VALUES(window_start)",
                (key, w),
            )
            # 2) 原子取令牌
            cur.execute(
                "UPDATE kms_rate_buckets SET count = count + 1 "
                "WHERE bucket_key = %s AND window_start = %s AND count < %s",
                (key, w, limit),
            )
            granted = cur.rowcount == 1
            _gc(cur, w)
            return granted
    except Exception as e:
        # 限流非安全边界：存储不可用时放行，避免基础设施抖动放大成全面故障。
        # 带上异常类型——否则编程错误（如参数个数不匹配）也会被静默降级成"不限流"，
        # 这是必须可诊断的安全可观测缺口。
        logger.warning(f"共享限流不可用，本次放行（fail-open）: {type(e).__name__}: {e}")
        return True


def _gc(cur, current_window: int) -> None:
    """删除过期窗口的计数行（每进程每窗口最多一次）。"""
    global _last_gc_window
    if _last_gc_window == current_window:
        return
    with _gc_lock:
        if _last_gc_window == current_window:
            return
        try:
            cur.execute(
                "DELETE FROM kms_rate_buckets WHERE window_start < %s",
                (current_window - 2,),
            )
        except Exception as e:
            logger.warning(f"限流表清理失败（可忽略）: {e}")
            return
        _last_gc_window = current_window


# ===================== 策略层：命名配额（唯一事实源） =====================
# 改造前配额散落在 4 处：middleware 里 `base * 5`（魔法数）、routes_embed 与 mcp
# 各自读 settings、kms/apps.py 硬编码 60（且 kms/constants.py 另有一个同名零引用
# 常量）。同一个「应用级」限流存在两个互不知情的配额来源，改配置只生效一半。
# 现收敛为注册表：配额数字与键构造规则各只有一份，可集中审计与调整。

# IP 维度天然被 NAT/出口网关共享（一个 IP 背后是多个用户），配额需放宽；
# 而 app / mcp / apikey 都是「一个主体 = 一个调用方」，直接用基准配额。
IP_LIMIT_MULTIPLIER = 5


@dataclass(frozen=True)
class Policy:
    """一条限流策略。

    scope 参与键构造，保证不同策略的键空间互不冲突——否则同名主体（如
    app_id 与 employee_no 恰好同值）会互相挤占对方的配额。
    """

    name: str
    limit: int
    scope: str
    window: int = DEFAULT_WINDOW

    def key_for(self, subject: str) -> str:
        """构造限流键。主体缺失时不能用空串——那会让所有匿名主体共用一个桶，
        把「按主体限流」退化成「全局限流」；统一落到 'anonymous' 以显式区分。"""
        return f"{self.scope}:{subject or 'anonymous'}"


# (策略名, 键前缀, 相对基准配额的倍率)
_POLICY_SPECS: Tuple[Tuple[str, str, int], ...] = (
    ("gw.ip", "ip", IP_LIMIT_MULTIPLIER),      # 网关：按来源 IP
    ("gw.app", "app", 1),                      # 网关：按嵌入应用
    ("gw.mcp", "mcp", 1),                      # 网关：按员工工号（MCP 单 IP 多员工）
    ("kms.apikey", "apikey", 1),               # KMS：按第三方应用 API Key
)

_policies: Optional[Dict[str, Policy]] = None
_policies_lock = threading.Lock()


def _build_policies() -> Dict[str, Policy]:
    base = max(1, int(settings.gw_rate_limit_per_minute))
    return {name: Policy(name, base * mult, scope) for name, scope, mult in _POLICY_SPECS}


def policies() -> Dict[str, Policy]:
    """全部策略（延迟构建：避免在模块导入阶段就把配额冻结成默认值）。"""
    global _policies
    if _policies is None:
        with _policies_lock:
            if _policies is None:
                _policies = _build_policies()
    return _policies


def policy(name: str) -> Policy:
    """取命名策略。未登记的策略名**不抛错**——限流不该成为新的故障点，
    退化为按基准配额判定并告警，便于发现漏登记。"""
    found = policies().get(name)
    if found is not None:
        return found
    logger.warning(f"未登记的限流策略 '{name}'，按基准配额判定（请在 _POLICY_SPECS 登记）")
    return Policy(name, max(1, int(settings.gw_rate_limit_per_minute)), "unregistered")


def check(name: str, subject: str) -> bool:
    """按命名策略判定：True 表示放行。

    这是接入限流的**唯一入口**——调用方不需要知道配额数字、窗口长度或键构造
    规则。新增端点只需在 `_POLICY_SPECS` 登记一行，再在此处调用一次。
    含 DB I/O，异步上下文中请用 run_in_threadpool 调用。
    """
    p = policy(name)
    return allow(p.key_for(subject), p.limit, p.window)


# ===================== 跨实例指标计数 =====================
def _tool_key(tool: str) -> str:
    """工具名归一为计数键，避免注入/无界基数。"""
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(tool))[:64]
    return f"tool.{safe}"


def record_metrics(tool: str, ok: bool, elapsed_ms: float) -> None:
    """累加一次工具调用指标到共享计数器（跨实例可聚合）。失败仅告警。"""
    ensure_ratelimit_tables()
    tk = _tool_key(tool)
    ms = float(elapsed_ms or 0.0)
    rows: List[Tuple[str, float]] = [
        ("calls", 1.0),
        ("total_ms", ms),
        (f"{tk}.calls", 1.0),
        (f"{tk}.total_ms", ms),
    ]
    if not ok:
        rows.append(("errors", 1.0))
        rows.append((f"{tk}.errors", 1.0))
    try:
        with _conn() as cur:
            cur.executemany(
                "INSERT INTO kms_metric_counters (metric_key, val) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE val = val + VALUES(val)",
                rows,
            )
    except Exception as e:
        logger.warning(f"指标计数写入失败（不计入本次）: {e}")


def metrics_snapshot() -> dict:
    """跨实例聚合快照。存储不可用时返回零值快照，不抛错。"""
    ensure_ratelimit_tables()
    try:
        with _conn() as cur:
            cur.execute("SELECT metric_key, val FROM kms_metric_counters")
            rows = cur.fetchall()
    except Exception as e:
        logger.warning(f"指标快照读取失败: {e}")
        rows = []
    vals = {r["metric_key"]: float(r["val"]) for r in rows}

    def _avg(ms_key: str, calls_key: str) -> float:
        calls = vals.get(calls_key, 0.0)
        return round(vals.get(ms_key, 0.0) / calls, 1) if calls else 0.0

    calls = int(vals.get("calls", 0.0))
    by_tool = {}
    prefix, suffix = "tool.", ".calls"
    for key in vals:
        if key.startswith(prefix) and key.endswith(suffix):
            name = key[len(prefix):-len(suffix)]
            t_calls = int(vals.get(key, 0.0))
            if t_calls <= 0:
                continue
            by_tool[name] = {
                "calls": t_calls,
                "errors": int(vals.get(f"{prefix}{name}.errors", 0.0)),
                "avg_ms": _avg(f"{prefix}{name}.total_ms", key),
            }
    return {
        "calls": calls,
        "errors": int(vals.get("errors", 0.0)),
        "avg_ms": _avg("total_ms", "calls"),
        "by_tool": by_tool,
    }
