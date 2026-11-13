"""单机网关持久化状态：回调去重/任务队列/反馈归属。SQLite 不监听端口。

事务提交后才 ACK；仅支持单个 KMS worker，任务失败有界重试。
状态目录应加密备份并限制 OS 访问，不能放在静态资源目录或 NFS。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

from config import settings


@contextmanager
def connection():
    path = settings.gw_state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA synchronous=FULL")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                event_key TEXT PRIMARY KEY, channel TEXT NOT NULL,
                payload TEXT NOT NULL, request_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                available_at REAL NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS receipts (
                message_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
                created_at REAL NOT NULL, rating TEXT, comment TEXT
            );
            CREATE INDEX IF NOT EXISTS job_pending ON jobs(status, available_at);
            CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS user_revocations (user_id TEXT PRIMARY KEY, revoked_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                employee_no TEXT NOT NULL,
                jti TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_sessions_jti ON sessions(jti);
        """)
    if os.name != "nt":
        os.chmod(settings.gw_state_path.parent, 0o700)
        os.chmod(settings.gw_state_path, 0o600)


def enqueue(channel: str, event_key: str, payload: dict, request_id: str) -> bool:
    now = time.time()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM jobs WHERE event_key=?", (event_key,)).fetchone():
            return False
        count = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('pending','running')").fetchone()[0]
        if count >= 1000:
            raise RuntimeError("机器人任务队列已满")
        db.execute("INSERT INTO jobs(event_key,channel,payload,request_id,available_at,created_at) VALUES(?,?,?,?,?,?)",
                   (event_key, channel, json.dumps(payload, ensure_ascii=False), request_id, now, now))
    return True


def claim():
    now = time.time()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        # 进程崩溃的在途任务以租约恢复；配合客户端请求超时使用。
        db.execute("UPDATE jobs SET status='failed',payload='{}' WHERE status IN ('running','pending') AND attempts>=3 AND available_at<?", (now,))
        db.execute("UPDATE jobs SET status='pending' WHERE status='running' AND available_at<? AND attempts<3", (now,))
        row = db.execute("SELECT * FROM jobs WHERE status='pending' AND available_at<=? ORDER BY created_at LIMIT 1", (now,)).fetchone()
        if not row:
            return None
        db.execute("UPDATE jobs SET status='running', attempts=attempts+1, available_at=? WHERE event_key=?",
                   (now + 1800, row["event_key"]))
        result = dict(row)
        result["attempts"] += 1
        result["payload"] = json.loads(result["payload"])
        return result


def finish(job: dict, success: bool, retry: bool = True) -> None:
    terminal = success or not retry or job["attempts"] >= 3
    status = "done" if success else ("failed" if terminal else "pending")
    with connection() as db:
        db.execute("UPDATE jobs SET status=?,payload=?,available_at=? WHERE event_key=?",
                   (status, "{}" if terminal else json.dumps(job["payload"], ensure_ascii=False),
                    time.time() + 30 * job["attempts"], job["event_key"]))
        # 保留去重键 7 天；完成即清除问题明文。失败仅保留状态，审计独立留存。
        db.execute("DELETE FROM jobs WHERE status IN ('done','failed') AND created_at<?", (time.time() - 604800,))


def receipt(principal: str) -> str:
    mid = uuid.uuid4().hex
    with connection() as db:
        db.execute("INSERT INTO receipts(message_id,principal,created_at) VALUES(?,?,?)", (mid, principal, time.time()))
        db.execute("DELETE FROM receipts WHERE created_at<?", (time.time() - 2592000,))
    return mid


def revoke_token(jti: str, expires: float):
    with connection() as db:
        db.execute("INSERT OR REPLACE INTO revoked_tokens(jti,expires) VALUES(?,?)", (jti, expires))
        db.execute("DELETE FROM revoked_tokens WHERE expires<?", (time.time(),))


def revoke_user(user_id: int):
    with connection() as db:
        db.execute("INSERT OR REPLACE INTO user_revocations(user_id,revoked_at) VALUES(?,?)", (str(user_id), time.time()))


def token_allowed(payload):
    with connection() as db:
        if db.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (payload["jti"],)).fetchone():
            return False
        row = db.execute("SELECT revoked_at FROM user_revocations WHERE user_id=?", (payload["sub"],)).fetchone()
        return not row or float(payload["iat"]) > row["revoked_at"]


# ===================== 会话管理（严格绑定人员） =====================
def create_session(user_id: int, employee_no: str, jti: str, expires_at: float,
                   ip_address: str = "", user_agent: str = "") -> str:
    """创建新会话并使该用户所有旧会话失效（单会话模式）。"""
    session_id = uuid.uuid4().hex
    now = time.time()
    with connection() as db:
        # 使该用户所有旧会话失效（严格绑定：同一时刻仅一个活跃会话）
        db.execute("UPDATE sessions SET is_active=0 WHERE user_id=? AND is_active=1",
                   (user_id,))
        # 创建新会话
        db.execute(
            "INSERT INTO sessions(session_id,user_id,employee_no,jti,created_at,expires_at,ip_address,user_agent,is_active) "
            "VALUES(?,?,?,?,?,?,?,?,1)",
            (session_id, user_id, employee_no, jti, now, expires_at, ip_address, user_agent)
        )
        # 清理过期会话（保留最近 30 天记录用于审计）
        db.execute("DELETE FROM sessions WHERE expires_at<?", (now - 2592000,))
    return session_id


def validate_session(jti: str) -> bool:
    """验证会话是否有效（活跃且未过期）。"""
    now = time.time()
    with connection() as db:
        row = db.execute(
            "SELECT is_active,expires_at FROM sessions WHERE jti=?",
            (jti,)
        ).fetchone()
        if not row:
            return False
        return bool(row["is_active"]) and float(row["expires_at"]) > now


def revoke_session(jti: str):
    """撤销指定会话。"""
    with connection() as db:
        db.execute("UPDATE sessions SET is_active=0 WHERE jti=?", (jti,))


def revoke_all_user_sessions(user_id: int):
    """撤销用户所有会话（用于密码修改、账号停用等场景）。"""
    with connection() as db:
        db.execute("UPDATE sessions SET is_active=0 WHERE user_id=?", (user_id,))


def get_active_sessions(user_id: int) -> list[dict]:
    """获取用户所有活跃会话（用于会话管理界面）。"""
    now = time.time()
    with connection() as db:
        rows = db.execute(
            "SELECT session_id,employee_no,created_at,expires_at,ip_address,user_agent "
            "FROM sessions WHERE user_id=? AND is_active=1 AND expires_at>? "
            "ORDER BY created_at DESC",
            (user_id, now)
        ).fetchall()
        return [dict(r) for r in rows]


def feedback(principal: str, message_id: str, rating: str, comment: str) -> bool:
    with connection() as db:
        cur = db.execute("UPDATE receipts SET rating=?,comment=? WHERE message_id=? AND principal=?",
                         (rating, comment, message_id, principal))
        return cur.rowcount == 1
