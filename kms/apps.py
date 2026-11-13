"""KMS 多应用 API Key（参考 OpenAI / Dify 应用密钥模型）。

用途：为第三方应用/服务提供程序化接入能力，每个应用有独立 API Key，
可绑定可访问的密级范围（[min_level, max_level]），实现应用级数据隔离。

设计
----
- kms_apps 表存储应用元数据；api_key 仅存 SHA-256 哈希，明文只在创建时返回一次；
- 应用通过请求头 X-API-Key 接入，身份映射为虚拟 AuthUser（role=employee，
  level=allowed_max_level，readable_max_level 自动收敛到 max_level）；
- 速率限制：跨实例共享计数（kms/ratelimit.py），每应用每分钟 60 次（可配），超限返回 429；
- 与用户登录 Token 并存：优先 Bearer Token，其次 X-API-Key。

表结构
------
CREATE TABLE kms_apps (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    app_id VARCHAR(32) NOT NULL UNIQUE COMMENT '公开应用ID',
    app_name VARCHAR(128) NOT NULL,
    api_key_hash VARCHAR(64) NOT NULL COMMENT 'SHA-256(api_key)',
    allowed_min_level INT NOT NULL DEFAULT 0,
    allowed_max_level INT NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_by BIGINT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at DATETIME NULL
);
"""
from __future__ import annotations

import hashlib
import secrets
from typing import List, Optional

from fastapi import Request

from app.logger import get_logger
from app.store import MySQLStore
from . import ratelimit

logger = get_logger("kms.apps")

APPS_DDL: List[str] = [
    """CREATE TABLE IF NOT EXISTS kms_apps (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        app_id VARCHAR(32) NOT NULL UNIQUE,
        app_name VARCHAR(128) NOT NULL,
        api_key_hash VARCHAR(64) NOT NULL,
        allowed_min_level INT NOT NULL DEFAULT 0,
        allowed_max_level INT NOT NULL DEFAULT 0,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_by BIGINT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_used_at DATETIME NULL,
        INDEX idx_app_id (app_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 第三方应用 API Key';""",
]

# 速率限制配额不再在此硬编码：统一由 kms/ratelimit.py 的策略注册表给出，
# 避免与 gateway 侧的 gw_rate_limit_per_minute 形成两个互不知情的配额来源。


def ensure_apps_tables() -> bool:
    try:
        with MySQLStore()._conn() as cur:
            for ddl in APPS_DDL:
                cur.execute(ddl)
        return True
    except Exception as e:
        logger.warning(f"应用表初始化失败: {e}")
        return False


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _check_rate_limit(app_id: str) -> bool:
    """应用级限流：返回 True 表示允许。

    原为进程内令牌桶，多实例部署时配额被放大 N 倍；现委托共享计数。
    注意：本函数含 DB I/O，异步路由中请用 run_in_threadpool 调用。
    """
    return ratelimit.check("kms.apikey", app_id)


# ===================== 应用 CRUD =====================
def create_app(
    app_name: str,
    allowed_min_level: int,
    allowed_max_level: int,
    created_by: Optional[int],
) -> dict:
    """创建应用，返回含明文 api_key 的字典（仅此次返回）。"""
    app_id = secrets.token_hex(8)
    api_key = "sk-" + secrets.token_hex(24)
    with MySQLStore()._conn() as cur:
        cur.execute(
            "INSERT INTO kms_apps (app_id, app_name, api_key_hash, allowed_min_level, "
            "allowed_max_level, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
            (app_id, app_name, _hash_key(api_key), allowed_min_level,
             allowed_max_level, created_by),
        )
    return {"app_id": app_id, "app_name": app_name, "api_key": api_key,
            "allowed_min_level": allowed_min_level, "allowed_max_level": allowed_max_level}


def list_apps() -> list:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT id, app_id, app_name, allowed_min_level, allowed_max_level, "
            "is_active, created_by, created_at, last_used_at FROM kms_apps ORDER BY id DESC"
        )
        rows = cur.fetchall()
    for r in rows:
        if r.get("created_at") and not isinstance(r["created_at"], str):
            r["created_at"] = str(r["created_at"])
        if r.get("last_used_at") and not isinstance(r["last_used_at"], str):
            r["last_used_at"] = str(r["last_used_at"])
    return rows


def update_app(app_id: str, fields: dict) -> None:
    allowed = {"app_name", "allowed_min_level", "allowed_max_level", "is_active"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=%s")
            params.append(v)
    if not sets:
        return
    params.append(app_id)
    with MySQLStore()._conn() as cur:
        cur.execute(f"UPDATE kms_apps SET {', '.join(sets)} WHERE app_id=%s", tuple(params))


def regenerate_api_key(app_id: str) -> str:
    """重新生成 API Key，旧 Key 立即失效，返回新明文。"""
    new_key = "sk-" + secrets.token_hex(24)
    with MySQLStore()._conn() as cur:
        cur.execute(
            "UPDATE kms_apps SET api_key_hash=%s WHERE app_id=%s",
            (_hash_key(new_key), app_id),
        )
    return new_key


def delete_app(app_id: str) -> None:
    with MySQLStore()._conn() as cur:
        cur.execute("DELETE FROM kms_apps WHERE app_id=%s", (app_id,))


def get_app_by_key(api_key: str) -> Optional[dict]:
    """按明文 api_key 查应用（校验哈希）。"""
    if not api_key:
        return None
    h = _hash_key(api_key)
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT * FROM kms_apps WHERE api_key_hash=%s", (h,))
        return cur.fetchone()


def touch_app_used(app_id: str) -> None:
    try:
        with MySQLStore()._conn() as cur:
            cur.execute("UPDATE kms_apps SET last_used_at=NOW() WHERE app_id=%s", (app_id,))
    except Exception as e:
        logger.warning(f"更新应用最后使用时间失败: {e}")


# ===================== 请求鉴权：X-API-Key =====================
def authenticate_app(request: Request) -> Optional[dict]:
    """从请求头 X-API-Key 解析应用身份。返回应用行或 None。

    若请求头带了 X-API-Key 但校验失败（无效/停用），抛出 401（不降级为公开访客）。
    """
    from fastapi import HTTPException

    api_key = request.headers.get("x-api-key", "").strip()
    if not api_key:
        return None
    app = get_app_by_key(api_key)
    if app is None:
        raise HTTPException(status_code=401, detail="无效的 API Key")
    if not app["is_active"]:
        raise HTTPException(status_code=403, detail="该应用已被停用")
    if not _check_rate_limit(app["app_id"]):
        raise HTTPException(status_code=429, detail=(
            f"应用 {app['app_name']} 请求频率超限"
            f"（{ratelimit.policy('kms.apikey').limit}次/分钟）"))
    touch_app_used(app["app_id"])
    return app


def app_to_auth_user(app: dict):
    """把应用映射为虚拟 AuthUser（供 BLP 规则复用）。

    - role 固定 employee（应用无管理权限）；
    - level = allowed_max_level（可读范围上界）；
    - 写入权限由 allowed_min_level 控制（在 can_write 判定时额外处理）。
    """
    from .security import AuthUser

    class _AppUser(AuthUser):
        """应用身份：继承 AuthUser，覆盖 readable_max_level 与写入判定。"""

        def __init__(self, app_row: dict):
            super().__init__({
                "id": -int(app_row["id"]),  # 负数区分应用与真实用户
                "employee_no": f"app:{app_row['app_id']}",
                "username": app_row["app_name"],
                "role": "employee",
                "level": int(app_row["allowed_max_level"]),
                "is_active": bool(app_row["is_active"]),
            })
            self._app_id = app_row["app_id"]
            self._min_level = int(app_row["allowed_min_level"])

        @property
        def is_app(self) -> bool:
            return True

    return _AppUser(app)
