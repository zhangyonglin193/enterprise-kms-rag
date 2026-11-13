"""对外 API 网关：外部身份 → 内部员工映射。

飞书/企业微信用户的平台 ID（open_id / UserId）不代表知识库身份，
必须通过绑定表映射到已批准导入的在职员工（kms_users.employee_no），
才能套用既有 BLP 密级权限体系：

- 已绑定且员工在职启用 → 使用其真实安全职级（可读其密级范围内知识）；
- 未绑定 / 员工已禁用 → 拒绝，禁止匿名降级；
- 密级与部门判定以 kms.access_control 为权威源；嵌入路径另外取应用上下界与员工密级的交集，网关不自行放宽可读范围。
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from app.logger import get_logger
from app.store import MySQLStore
from kms import access_control as acl
from kms.security import AuthUser

logger = get_logger("gateway.identity")

GW_IDENTITY_DDL = [
    """CREATE TABLE IF NOT EXISTS kms_gw_bot_bindings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        platform VARCHAR(16) NOT NULL COMMENT 'feishu / wecom',
        external_user_id VARCHAR(128) NOT NULL COMMENT '平台侧用户ID',
        employee_no VARCHAR(32) NOT NULL COMMENT '内部员工工号',
        bound_by VARCHAR(32) NULL COMMENT '绑定操作人',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_platform_user (platform, external_user_id),
        INDEX idx_employee (employee_no)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='网关机器人身份绑定表';""",
]


def ensure_identity_tables() -> bool:
    try:
        with MySQLStore()._conn() as cur:
            for ddl in GW_IDENTITY_DDL:
                cur.execute(ddl)
        return True
    except Exception:
        logger.warning("身份绑定表初始化失败，机器人拒绝服务")
        return False


# ===================== 绑定管理 =====================

def bind(platform: str, external_user_id: str, employee_no: str, bound_by: str = "") -> None:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "INSERT INTO kms_gw_bot_bindings (platform, external_user_id, employee_no, bound_by) "
            "VALUES (%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE employee_no=VALUES(employee_no), bound_by=VALUES(bound_by)",
            (platform, external_user_id, employee_no, bound_by),
        )


def unbind(platform: str, external_user_id: str) -> None:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "DELETE FROM kms_gw_bot_bindings WHERE platform=%s AND external_user_id=%s",
            (platform, external_user_id),
        )


def lookup_binding(platform: str, external_user_id: str) -> Optional[str]:
    """查询平台用户绑定的工号；无绑定返回 None。"""
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "SELECT employee_no FROM kms_gw_bot_bindings "
                "WHERE platform=%s AND external_user_id=%s",
                (platform, external_user_id),
            )
            row = cur.fetchone()
            return row["employee_no"] if row else None
    except Exception:
        raise HTTPException(503, "身份服务不可用") from None


# ===================== 身份解析 =====================

def resolve_bot_user(platform: str, external_user_id: str, display_name: str = "") -> AuthUser:
    """平台已认证用户还必须有可信员工绑定；无绑定/停用返回 403。"""
    employee_no = lookup_binding(platform, external_user_id) if external_user_id else None
    if not employee_no:
        raise HTTPException(403, "未绑定企业员工身份")
    try:
        row = acl.get_user_by_employee_no(employee_no)
    except Exception:
        raise HTTPException(503, "身份服务不可用") from None
    if not row or not row.get("is_active"):
        raise HTTPException(403, "员工身份不可用")
    return AuthUser(row)
