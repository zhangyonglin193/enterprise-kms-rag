"""对外 API 网关：飞书 / 企业微信开放平台 HTTP 客户端。

- token 内存缓存（提前 5 分钟过期刷新），避免频繁换取；
- 同步 httpx 调用由 SQLite 持久任务 worker 承载（回调先入队再 ACK，不阻塞事件循环，进程重启后由租约恢复）；
- 回复失败仅告警 + 审计，不向上抛出（回调侧必须尽快返回 200 防平台重试）。
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Optional

import httpx

from app.logger import get_logger
from config import settings

logger = get_logger("gateway.clients")

FEISHU_BASE = "https://open.feishu.cn/open-apis"
WECOM_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

# 平台消息长度上限（字节/字符）
FEISHU_TEXT_MAX_CHARS = 30_000
WECOM_TEXT_MAX_BYTES = 2048


class _TokenCache:
    """access_token 缓存（线程安全，提前 300 秒刷新）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expire_at: float = 0.0

    def get(self, fetch) -> str:
        with self._lock:
            if self._token and time.time() < self._expire_at - 300:
                return self._token
            token, expires_in = fetch()
            self._token = token
            self._expire_at = time.time() + expires_in
            return token


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n\n（内容过长，已截断，详情请登录知识库查看）"


# ===================== 飞书客户端 =====================

class FeishuClient:
    """飞书自建应用 API 客户端（tenant_access_token 模式）。"""

    def __init__(self) -> None:
        self._cache = _TokenCache()

    def _fetch_token(self) -> tuple:
        resp = httpx.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            },
            timeout=10, trust_env=False,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError("获取飞书访问令牌失败")
        return data["tenant_access_token"], int(data.get("expire", 7200))

    @property
    def token(self) -> str:
        return self._cache.get(self._fetch_token)

    def reply_text(self, message_id: str, text: str) -> bool:
        """回复指定消息（会话内引用回复）。"""
        body = {
            "content": json.dumps({"text": _truncate(text, FEISHU_TEXT_MAX_CHARS)}, ensure_ascii=False),
            "msg_type": "text",
        }
        return self._post(
            f"{FEISHU_BASE}/im/v1/messages/{message_id}/reply", body
        )

    def send_text(self, open_id: str, text: str, event_key: str = "") -> bool:
        """单聊主动推送（备用通道）。"""
        body = {
            "receive_id": open_id,
            "content": json.dumps({"text": _truncate(text, FEISHU_TEXT_MAX_CHARS)}, ensure_ascii=False),
            "msg_type": "text",
        }
        if event_key:
            body["uuid"] = event_key[:50]
        return self._post(f"{FEISHU_BASE}/im/v1/messages?receive_id_type=open_id", body)

    def _post(self, url: str, body: dict) -> bool:
        try:
            resp = httpx.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=15, trust_env=False,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("飞书消息发送失败")
                return False
            return True
        except Exception:
            logger.error("飞书 API 调用异常")
            return False


# ===================== 企业微信客户端 =====================

class WeComClient:
    """企业微信自建应用 API 客户端（access_token 模式）。"""

    def __init__(self) -> None:
        self._cache = _TokenCache()

    def _fetch_token(self) -> tuple:
        resp = httpx.get(
            f"{WECOM_BASE}/gettoken",
            params={"corpid": settings.wecom_corp_id, "corpsecret": settings.wecom_secret},
            timeout=10, trust_env=False,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError("获取企业微信访问令牌失败")
        return data["access_token"], int(data.get("expires_in", 7200))

    @property
    def token(self) -> str:
        return self._cache.get(self._fetch_token)

    def send_text(self, to_user: str, text: str, event_key: str = "") -> bool:
        """应用消息推送（成员收消息，异步于回调，规避企微 5 秒超时）。"""
        if not re.fullmatch(r"[A-Za-z0-9_@.\-]+", to_user) or to_user == "@all":
            return False
        # 企微 text 内容上限 2048 字节，按 UTF-8 字节数截断
        encoded = text.encode("utf-8")
        if len(encoded) > WECOM_TEXT_MAX_BYTES:
            text = encoded[: WECOM_TEXT_MAX_BYTES - 60].decode("utf-8", "ignore") + "\n…（已截断，全文请入知识库）"
        body = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(settings.wecom_agent_id or 0),
            "text": {"content": text},
            "safe": 1,
            "enable_duplicate_check": 1,
            "duplicate_check_interval": 1800,
        }
        try:
            resp = httpx.post(
                f"{WECOM_BASE}/message/send",
                params={"access_token": self.token},
                json=body,
                timeout=15, trust_env=False,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                logger.warning("企业微信消息推送失败")
                return False
            return True
        except Exception:
            logger.error("企业微信 API 调用异常")
            return False


# ===== 模块级单例（token 缓存复用） =====
feishu_client = FeishuClient()
wecom_client = WeComClient()
