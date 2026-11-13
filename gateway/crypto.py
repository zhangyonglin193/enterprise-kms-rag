"""对外 API 网关：开放平台消息加解密与签名校验。

- 飞书（Feishu/Lark）：事件订阅 AES-256-CBC 解密（官方 Encrypt Key 方案）
- 企业微信（WeCom）：回调消息签名校验 + AES-CBC 加解密（BizMsgCrypt 官方算法）

仅依赖 cryptography（项目 requirements 已含），不引入额外依赖。
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
import xml.etree.ElementTree as ET
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.logger import get_logger

logger = get_logger("gateway.crypto")

# ===================== 飞书事件解密 =====================

def feishu_decrypt_text(encrypt_text: str, encrypt_key: str) -> str:
    """官方协议：Base64 解码后前 16 字节为 IV，后续为 PKCS7 密文。"""
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    data = base64.b64decode(encrypt_text, validate=True)
    if len(data) < 32 or len(data) % 16:
        raise ValueError("飞书密文长度非法")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(data[:16])).decryptor()
    padded = decryptor.update(data[16:]) + decryptor.finalize()
    amount = padded[-1]
    if not 1 <= amount <= 16 or padded[-amount:] != bytes([amount]) * amount:
        raise ValueError("飞书密文填充非法")
    return padded[:-amount].decode("utf-8")


def feishu_decrypt(encrypt_text: str, encrypt_key: str) -> dict:
    """解密飞书加密事件，返回内层 JSON dict。

    SHA-256 密钥派生，IV 由消息携带；拒绝非对象事件。
    """
    body = json.loads(feishu_decrypt_text(encrypt_text, encrypt_key))
    if not isinstance(body, dict):
        raise ValueError("事件必须为 JSON 对象")
    return body


# ===================== 企业微信 BizMsgCrypt =====================

class WeComCrypto:
    """企业微信回调消息加解密（对齐官方 WXBizMsgCrypt 算法）。

    - 签名: SHA1(sort(token, timestamp, nonce, encrypt))
    - 加密: AES-256-CBC，key = Base64Decode(EncodingAESKey + "=")，iv = key 前 16 字节
    - 明文: random(16) + msg_len(4B 网络序) + msg + receive_id(corp_id)
    """

    BLOCK_SIZE = 32  # 企微官方 PKCS7 分块长度

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str):
        if len(encoding_aes_key) != 43:
            raise ValueError("EncodingAESKey 长度应为 43 位 Base64 字符")
        self.token = token
        if not token or not receive_id:
            raise ValueError("企微签名令牌和企业 ID 不得为空")
        self.key = base64.b64decode(encoding_aes_key + "=", validate=True)
        if len(self.key) != 32:
            raise ValueError("企业微信 AES 密钥无效")
        self.iv = self.key[:16]
        self.receive_id = receive_id

    # ----- 签名 -----
    def signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        items = sorted([self.token, timestamp, nonce, encrypt])
        raw = "".join(items).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def verify_signature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypt: str
    ) -> None:
        """校验失败抛 ValueError。"""
        expected = self.signature(timestamp, nonce, encrypt)
        if not secrets.compare_digest(expected, msg_signature or ""):
            raise ValueError("企业微信消息签名校验失败")

    # ----- 加解密 -----
    def decrypt(self, encrypted_b64: str) -> str:
        """解密 Base64 密文，返回明文消息体（XML 或 echostr 原文）。"""
        data = base64.b64decode(encrypted_b64, validate=True)
        if len(data) % 16 != 0 or len(data) == 0:
            raise ValueError("企业微信密文长度非法")
        decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).decryptor()
        padded = decryptor.update(data) + decryptor.finalize()
        plain = self._pkcs7_strip(padded)
        # 结构跳过头部随机串与长度字段，并校验尾部 receive_id
        if len(plain) < 20:
            raise ValueError("企业微信明文长度非法")
        content = plain[16:]
        msg_len = struct.unpack("!I", content[:4])[0]
        if msg_len > len(content) - 4:
            raise ValueError("企业微信消息长度非法")
        msg = content[4 : 4 + msg_len].decode("utf-8")
        recv_id = content[4 + msg_len :].decode("utf-8")
        if self.receive_id and recv_id != self.receive_id:
            raise ValueError("企业微信 receive_id 不匹配")
        return msg

    def encrypt(self, text: str) -> str:
        """加密明文消息体，返回 Base64 密文（被动回复场景使用）。"""
        raw = text.encode("utf-8")
        body = (
            secrets.token_bytes(16)
            + struct.pack("!I", len(raw))
            + raw
            + self.receive_id.encode("utf-8")
        )
        padded = self._pkcs7_pad(body)
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).encryptor()
        return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()

    def reply_encrypted_xml(self, plain_xml: str, nonce: str) -> str:
        """构造企微被动回复 XML（加密 + 签名）。"""
        encrypt = self.encrypt(plain_xml)
        timestamp = str(int(_now()))
        signature = self.signature(timestamp, nonce, encrypt)
        nonce = nonce.replace("]]>", "]]]]><![CDATA[>")
        return (
            "<xml>"
            f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce>"
            "</xml>"
        )

    # ----- PKCS7（企微分块 32 字节） -----
    def _pkcs7_pad(self, data: bytes) -> bytes:
        amount = self.BLOCK_SIZE - len(data) % self.BLOCK_SIZE
        if amount == 0:
            amount = self.BLOCK_SIZE
        return data + bytes([amount]) * amount

    def _pkcs7_strip(self, data: bytes) -> bytes:
        amount = data[-1]
        if not 1 <= amount <= self.BLOCK_SIZE or data[-amount:] != bytes([amount]) * amount:
            raise ValueError("企业微信密文填充非法")
        return data[:-amount]


# ===================== XML 辅助 =====================

def xml_field(xml_text: str, tag: str) -> Optional[str]:
    """从企微回调 XML 中提取指定节点文本（不存在返回 None）。

    安全：拒绝含 DTD/实体声明的 XML，防 XXE/实体膨胀攻击
    （密文虽经验签解密，仍按不可信输入处理）。
    """
    upper = (xml_text or "").upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        logger.warning("企微回调 XML 含 DTD/实体声明，已拒绝解析")
        return None
    try:
        root = ET.fromstring(xml_text)
        node = root.find(tag)
        if node is not None and node.text is not None:
            return node.text.strip()
    except ET.ParseError as e:
        logger.warning(f"企微回调 XML 解析失败: {e}")
    return None


def build_text_reply_xml(
    to_user: str, from_user: str, content: str, msg_type: str = "text"
) -> str:
    """构造企微被动回复明文 XML。to_user=成员 openid，from_user=企业 corpid/机器人 id。"""
    timestamp = int(_now())
    to_user, from_user, content, msg_type = [
        value.replace("]]>", "]]]]><![CDATA[>")
        for value in (to_user, from_user, content, msg_type)
    ]
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{timestamp}</CreateTime>"
        f"<MsgType><![CDATA[{msg_type}]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


def _now() -> float:
    """时间戳（避免顶层重复 import time）。"""
    import time
    return time.time()
