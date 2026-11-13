"""对外 API 网关：独立审计日志。

企业级规范要求外部调用链「凡请求必留痕」，且审计数据与业务数据隔离：
- MySQL 表 kms_gw_audit：结构化审计记录（供管理端查询/导出，复用 KMS 审计体系）；
- 本地 JSONL 文件 data/gw_audit/gateway_YYYYMMDD.jsonl：追加式写入，
  文件 fsync 失败时阻止业务放行；双写不等于 WORM，不宣称不可篡改或通过合规认证。

记录字段：时间 / 渠道 / 请求ID / 应用 / 外部身份 / 映射员工 / 动作 /
          目标 / 状态码 / 耗时 / IP / 详情（问题摘要脱敏截断）。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from app.logger import get_logger
from app.store import MySQLStore
from config import settings

logger = get_logger("gateway.audit")

GW_AUDIT_DDL = [
    """CREATE TABLE IF NOT EXISTS kms_gw_audit (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        request_id VARCHAR(64) NOT NULL COMMENT '网关请求ID',
        channel VARCHAR(32) NOT NULL COMMENT '渠道: feishu/wecom/embed',
        action VARCHAR(64) NOT NULL COMMENT '动作: qa/webhook/auth_fail/...',
        app_id VARCHAR(64) NULL COMMENT '外部应用ID(kms_apps)',
        external_user VARCHAR(128) NULL COMMENT '平台侧用户标识',
        employee_no VARCHAR(32) NULL COMMENT '映射内部员工工号(未绑定为空)',
        target VARCHAR(255) NULL COMMENT '目标资源/接口',
        status_code INT NOT NULL DEFAULT 200,
        elapsed_ms INT NOT NULL DEFAULT 0,
        ip VARCHAR(64) NULL,
        detail TEXT NULL COMMENT '请求摘要(脱敏截断)',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_channel_time (channel, created_at),
        INDEX idx_request (request_id),
        INDEX idx_employee (employee_no)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对外API网关审计日志';""",
]

_table_ready = False
_file_lock = threading.Lock()


def ensure_gw_audit_table() -> bool:
    global _table_ready
    if _table_ready:
        return True
    try:
        with MySQLStore()._conn() as cur:
            for ddl in GW_AUDIT_DDL:
                cur.execute(ddl)
        _table_ready = True
        return True
    except Exception as e:
        logger.warning(f"网关审计表初始化失败（降级为文件审计）: {e}")
        return False


def new_request_id() -> str:
    return "gw-" + uuid.uuid4().hex


def log_gw_event(
    channel: str,
    action: str,
    request_id: str = "",
    app_id: Optional[str] = None,
    external_user: Optional[str] = None,
    employee_no: Optional[str] = None,
    target: str = "",
    status_code: int = 200,
    elapsed_ms: float = 0.0,
    ip: str = "",
    detail: str = "",
) -> None:
    """文件为强制持久凭证，失败抛异常；MySQL 为可查询副本。禁止传入凭证或问题原文。"""
    record = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "request_id": request_id,
        "channel": channel,
        "action": action,
        "app_id": app_id,
        "external_user": external_user,
        "employee_no": employee_no,
        "target": target[:255],
        "status_code": status_code,
        "elapsed_ms": int(elapsed_ms),
        "ip": ip,
        "detail": detail[:2000],
    }
    # 1) 强制持久审计，磁盘不可写/已满时拒绝业务，禁止静默吞错。
    try:
        day = datetime.now().strftime("%Y%m%d")
        path = settings.gw_audit_dir / f"gateway_{day}.jsonl"
        with _file_lock:
            settings.gw_audit_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
    except Exception:
        logger.error("网关审计持久化不可用，拒绝业务放行")
        raise RuntimeError("审计不可用") from None
    # 2) MySQL 审计（供管理端查询）
    if _table_ready:
        try:
            with MySQLStore()._conn() as cur:
                cur.execute(
                    "INSERT INTO kms_gw_audit (request_id, channel, action, app_id, "
                    "external_user, employee_no, target, status_code, elapsed_ms, ip, detail) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        request_id, channel, action, app_id,
                        external_user, employee_no, record["target"],
                        status_code, int(elapsed_ms), ip, record["detail"],
                    ),
                )
        except Exception as e:
            logger.warning(f"网关审计入库失败（文件审计已留存）: {e}")
