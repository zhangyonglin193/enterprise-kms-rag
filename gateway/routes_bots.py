"""飞书自建机器人/企微自建应用：真实性验证→员工绑定→持久入队→ACK。

仅支持文本单聊，不在群聊中回传受限知识；不是单向群机器人 webhook。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from app.logger import get_logger
from config import settings
from . import service, state
from .audit import log_gw_event
from .clients import feishu_client, wecom_client
from .crypto import WeComCrypto, feishu_decrypt, xml_field
from .identity import resolve_bot_user

router = APIRouter(prefix="/bots", tags=["open-gateway-bots"])
logger = get_logger("gateway.bots")


def fresh(timestamp: str) -> None:
    try:
        valid = abs(time.time() - int(timestamp)) <= settings.gw_callback_skew
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(401, "回调时间戳无效或过期")


def object_field(body, key):
    value = body.get(key, {})
    if not isinstance(value, dict):
        raise HTTPException(400, "事件结构无效")
    return value


def text_field(value, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise HTTPException(400, "事件字段缺失或超长")
    return value


async def submit(request, channel, event_id, external_id, question):
    question = text_field(question.strip(), 500)
    user = await run_in_threadpool(resolve_bot_user, channel, external_id)
    request.state.user = user
    # 去重键含渠道与已配置应用，平台重投只能命中同一个任务。
    app_id = settings.feishu_app_id if channel == "feishu" else settings.wecom_corp_id + ":" + settings.wecom_agent_id
    event_key = hashlib.sha256(f"{channel}:{app_id}:{event_id}".encode()).hexdigest()
    await run_in_threadpool(state.enqueue, channel, event_key,
                           {"external_id": external_id, "question": question}, request.state.request_id)


@router.post("/feishu/callback", summary="飞书加密事件回调")
async def feishu_callback(request: Request):
    if not all((settings.feishu_app_id, settings.feishu_app_secret, settings.feishu_verification_token, settings.feishu_encrypt_key)):
        raise HTTPException(503, "飞书渠道安全配置不完整")
    raw = await request.body()
    try:
        outer = json.loads(raw)
        body = feishu_decrypt(outer["encrypt"], settings.feishu_encrypt_key)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "飞书加密事件格式错误") from None
    header = object_field(body, "header")
    token = body.get("token") if body.get("type") == "url_verification" else header.get("token")
    if not isinstance(token, str) or not hmac.compare_digest(token.encode(), settings.feishu_verification_token.encode()):
        raise HTTPException(401, "事件令牌无效")
    # 官方网址验证不携带事件签名，使用加密 challenge + Verification Token。
    if body.get("type") == "url_verification":
        return {"challenge": text_field(body.get("challenge"))}
    timestamp = request.headers.get("x-lark-request-timestamp", "")
    nonce = text_field(request.headers.get("x-lark-request-nonce"))
    fresh(timestamp)
    signature = hashlib.sha256((timestamp + nonce + settings.feishu_encrypt_key).encode() + raw).hexdigest()
    if not hmac.compare_digest(signature, request.headers.get("x-lark-signature", "")):
        raise HTTPException(401, "飞书事件签名无效")
    if header.get("app_id") != settings.feishu_app_id:
        raise HTTPException(403, "事件应用不匹配")
    if header.get("event_type") != "im.message.receive_v1":
        return {"code": 0}
    event = object_field(body, "event")
    message, sender = object_field(event, "message"), object_field(event, "sender")
    if message.get("chat_type") != "p2p" or sender.get("sender_type") != "user":
        raise HTTPException(403, "仅支持员工单聊")
    if message.get("message_type") != "text":
        return {"code": 0}
    try:
        content = json.loads(message.get("content", ""))
        question = text_field(content["text"], 500)
    except (TypeError, ValueError, KeyError):
        raise HTTPException(400, "文本事件格式无效") from None
    external_id = text_field(object_field(sender, "sender_id").get("open_id"))
    await submit(request, "feishu", text_field(message.get("message_id")), external_id, question)
    return {"code": 0}


def wecom_crypto():
    if not all((settings.wecom_token, settings.wecom_encoding_aes_key, settings.wecom_corp_id, settings.wecom_secret, settings.wecom_agent_id)):
        raise HTTPException(503, "企业微信渠道安全配置不完整")
    try:
        return WeComCrypto(settings.wecom_token, settings.wecom_encoding_aes_key, settings.wecom_corp_id)
    except ValueError:
        raise HTTPException(503, "企业微信渠道安全配置无效") from None


def wecom_decode(signature, timestamp, nonce, encrypted):
    fresh(timestamp)
    crypto = wecom_crypto()
    try:
        crypto.verify_signature(signature, timestamp, nonce, encrypted)
        return crypto.decrypt(encrypted)
    except (ValueError, UnicodeError):
        raise HTTPException(401, "企业微信签名或消息校验失败") from None


@router.get("/wecom/callback", summary="企业微信接收服务器验证")
def wecom_verify(msg_signature: str = Query(..., max_length=64), timestamp: str = Query(..., max_length=20),
                 nonce: str = Query(..., min_length=1, max_length=128), echostr: str = Query(..., max_length=8192)):
    return PlainTextResponse(wecom_decode(msg_signature, timestamp, nonce, echostr))


@router.post("/wecom/callback", summary="企业微信加密消息回调")
async def wecom_callback(request: Request, msg_signature: str = Query(..., max_length=64),
                         timestamp: str = Query(..., max_length=20), nonce: str = Query(..., min_length=1, max_length=128)):
    try:
        raw = (await request.body()).decode("utf-8")
    except UnicodeError:
        raise HTTPException(400, "XML 必须使用 UTF-8") from None
    encrypted = xml_field(raw, "Encrypt")
    if not encrypted:
        raise HTTPException(400, "缺少加密消息")
    plain = wecom_decode(msg_signature, timestamp, nonce, encrypted)
    if xml_field(plain, "ToUserName") != settings.wecom_corp_id or xml_field(plain, "AgentID") != settings.wecom_agent_id:
        raise HTTPException(403, "企业或应用不匹配")
    if xml_field(plain, "MsgType") == "text":
        external_id = text_field(xml_field(plain, "FromUserName"))
        # 企微 touser 支持管道符多收件人，入口明确禁止广播/多目标标识。
        if not re.fullmatch(r"[A-Za-z0-9_@.\-]+", external_id) or external_id == "@all":
            raise HTTPException(400, "成员标识无效")
        await submit(request, "wecom", text_field(xml_field(plain, "MsgId")), external_id,
                     text_field(xml_field(plain, "Content"), 500))
    return PlainTextResponse("success")


def process(job):
    channel, payload = job["channel"], job["payload"]
    user = None
    status, retry = 200, True
    try:
        user = resolve_bot_user(channel, payload["external_id"])
        log_gw_event(channel, "job_started", job["request_id"], employee_no=user.employee_no, target=job["event_key"])
        result = service.answer(payload["question"], user, 0, user.security_level)
        current = resolve_bot_user(channel, payload["external_id"])
        if current.to_public_dict() != user.to_public_dict():
            raise HTTPException(403, "员工权限已变更")
        text = result["answer"]
        if result["sources"]:
            text += "\n参考来源：" + "；".join(s["title"] for s in result["sources"])
        # 私聊推送，不向群原消息引用回复。
        client = feishu_client if channel == "feishu" else wecom_client
        if not client.send_text(payload["external_id"], text, job["event_key"]):
            raise HTTPException(502, "平台投递失败")
    except HTTPException as exc:
        status, retry = exc.status_code, exc.status_code >= 500
    except Exception as e:
        status = 503
        # 原为裸吞（无 logger）：机器人任务失败原因完全不可诊断，
        # 平台侧重投也只能看到 503，无法区分是平台故障还是本地缺陷。
        logger.error(
            f"机器人任务处理失败 request_id={job.get('request_id')} "
            f"event_key={job.get('event_key')}: {type(e).__name__}: {e}"
        )
    log_gw_event(channel, "job_finished", job["request_id"], employee_no=user.employee_no if user else None,
                 target=job["event_key"], status_code=status, detail=f"attempt={job['attempts']}")
    state.finish(job, status == 200, retry)


def start_worker():
    stop = threading.Event()
    def work():
        while not stop.wait(1):
            try:
                job = state.claim()
                if job:
                    process(job)
            except Exception:
                logger.error("机器人任务处理暂不可用，待恢复后重试")
    thread = threading.Thread(target=work, name="gateway-delivery", daemon=True)
    thread.start()
    return stop, thread
