"""KMS 访问控制模块：BLP 强制访问控制 + 部门归属 + 审计 + 工单 + 通知。

架构原则
--------
- 系统中只有一类主体：员工。
- 人事主数据（账号、部门、业务称谓、安全职级 L0-L3）从 HR 系统单向只读同步。
- 权限判定不依靠角色或职责，依靠安全职级 + 所属部门。

BLP（Bell-LaPadula）
--------------------
- 安全职级固定 L0(公开，指公司内部公开)~L3(绝密)，由 HR 系统定义，KMS 不可修改。
- 简单性质（不上读）: 员工可读 doc_level <= security_level 的文档。
- *-性质（不下写）: 员工可写 doc_level >= security_level 的文档。
- 部门规则: 员工部门 IN 文档归属部门数组(departments)。

数据表
------
- kms_users           员工（HR 同步镜像，只读引用）
- kms_doc_levels      文档密级归属（缺失视为最高密级，fail-closed 拒绝）
- kms_audit_logs      敏感操作审计（独立存储，不可篡改）
- kms_tickets         工单（两段式：申请 → 审批即执行；审批人按职责匹配，无管理员）
- kms_notifications   站内通知（工单流转结果告知）
- kms_chat_owners     问答会话归属
"""
from __future__ import annotations

import json
import secrets
import threading
from typing import List, Optional, Tuple

from app.logger import get_logger
from app.store import MySQLStore

from .constants import (DOC_DEPT_UNLIMITED, HR_EMPLOYMENT_STAFF, HR_STATUS_REGULAR,
                        HR_STATUS_TRIAL, MAX_EMPLOYEE_LEVEL,
                        SECURITY_LEVELS, SECURITY_LEVEL_CONFIDENTIAL,
                        normalize_department)
from .security import AuthUser, hash_password

logger = get_logger("kms.acl")

# ===================== DDL（幂等） =====================
KMS_DDL: List[str] = [
    """CREATE TABLE IF NOT EXISTS kms_users (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        employee_no VARCHAR(64) NOT NULL COMMENT '工号（HR 系统）',
        username VARCHAR(128) NOT NULL COMMENT '姓名（HR 系统）',
        password_hash VARCHAR(255) NOT NULL COMMENT 'PBKDF2 散列',
        role VARCHAR(32) NOT NULL DEFAULT 'employee' COMMENT '基础身份(固定employee)',
        security_level INT NOT NULL DEFAULT 0 COMMENT '安全职级 L0-L3（HR 同步）',
        department VARCHAR(128) NOT NULL DEFAULT '' COMMENT '所属部门（HR 同步）',
        business_title VARCHAR(128) NOT NULL DEFAULT '' COMMENT '业务称谓（HR 同步，仅展示）',
        is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '在职状态（HR 同步）',
        data_source VARCHAR(32) NOT NULL DEFAULT 'local' COMMENT '数据来源: hr_sync/local',
        hr_synced_at DATETIME NULL COMMENT '最近 HR 同步时间',
        last_login_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_employee_no (employee_no)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 员工表（HR 同步镜像）';""",
    """CREATE TABLE IF NOT EXISTS kms_doc_levels (
        document_id BIGINT PRIMARY KEY COMMENT 'documents.id',
        level INT NOT NULL DEFAULT 0 COMMENT '密级层级 L0-L3',
        granted_by BIGINT NULL COMMENT '设置人员工ID',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 文档密级';""",
    """CREATE TABLE IF NOT EXISTS kms_audit_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NULL,
        employee_no VARCHAR(64) NULL,
        action VARCHAR(64) NOT NULL,
        target VARCHAR(512) NOT NULL DEFAULT '',
        detail TEXT NULL,
        ip VARCHAR(64) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_audit_time (created_at),
        INDEX idx_audit_user (user_id),
        INDEX idx_audit_action (action)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 审计日志（独立存储，不可篡改）';""",
    """CREATE TABLE IF NOT EXISTS kms_chat_owners (
        session_id VARCHAR(64) PRIMARY KEY COMMENT 'chat_history.session_id',
        user_id BIGINT NOT NULL COMMENT '会话归属员工',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_owner (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 会话归属';""",
    """CREATE TABLE IF NOT EXISTS kms_tickets (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ticket_no VARCHAR(40) NOT NULL COMMENT '工单编号',
        module VARCHAR(32) NOT NULL COMMENT '工单模块',
        category VARCHAR(16) NOT NULL DEFAULT 'doc' COMMENT 'doc文档变更',
        flow VARCHAR(16) NOT NULL DEFAULT 'two_step' COMMENT 'two_step两段(审批即执行)',
        applicant_id BIGINT NOT NULL COMMENT '申请人A（员工）',
        applicant_no VARCHAR(64) NOT NULL DEFAULT '',
        applicant_name VARCHAR(128) NOT NULL DEFAULT '',
        payload TEXT NULL COMMENT '申请内容 JSON',
        payload_summary VARCHAR(512) NOT NULL DEFAULT '' COMMENT '申请事项摘要',
        original_hash CHAR(64) NOT NULL DEFAULT '' COMMENT '提交时 SHA-256',
        approver_id BIGINT NULL COMMENT '审批人B（按审批职责匹配，非管理员）',
        approver_no VARCHAR(64) NOT NULL DEFAULT '',
        approver_name VARCHAR(128) NOT NULL DEFAULT '',
        approved_hash CHAR(64) NULL COMMENT '审批通过时 SHA-256',
        approve_comment VARCHAR(512) NOT NULL DEFAULT '',
        approved_at DATETIME NULL,
        exec_result VARCHAR(1024) NOT NULL DEFAULT '',
        executed_at DATETIME NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected/executed/timeout/cancelled/tampered',
        reason VARCHAR(512) NOT NULL DEFAULT '' COMMENT '驳回/失败原因',
        timeout_at DATETIME NULL COMMENT '超时时间',
        doc_id VARCHAR(64) NULL COMMENT '关联文档业务ID（用于文档锁）',
        doc_references JSON NULL COMMENT '关联文档快照（建单时写入，文档被执行删除后仍可审计查看）',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_ticket_no (ticket_no),
        INDEX idx_t_status (status),
        INDEX idx_t_applicant (applicant_id),
        INDEX idx_t_approver (approver_id),
        INDEX idx_t_module (module),
        INDEX idx_t_doc_id (doc_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 工单（两段式）';""",
    """CREATE TABLE IF NOT EXISTS kms_notifications (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL COMMENT '接收人员工',
        ticket_id BIGINT NULL COMMENT '关联工单',
        ntype VARCHAR(32) NOT NULL DEFAULT 'ticket',
        title VARCHAR(255) NOT NULL DEFAULT '',
        content VARCHAR(1024) NOT NULL DEFAULT '',
        is_read TINYINT(1) NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_n_user (user_id, is_read)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 站内通知';""",

    # 员工职责：工单审批权按职责授予，**系统中不存在管理员角色**。
    # 归一化存储（而非 kms_users 上的 JSON 列）是为了让「谁有 ticket_approve」
    # 这类反查能走索引，审批人匹配每次开单都要查。
    """CREATE TABLE IF NOT EXISTS kms_user_duties (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL COMMENT '员工',
        duty VARCHAR(32) NOT NULL COMMENT '职责键，如 ticket_approve',
        granted_by BIGINT NULL COMMENT '授予人（工单执行时写入）',
        granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_user_duty (user_id, duty),
        INDEX idx_ud_duty (duty)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 员工职责';""",

    # 批量上传批次：入库是耗时操作（Embedding/索引），不能挂在 HTTP 请求里同步跑完，
    # 故拆成「批次记录 + 后台线程处理 + 前端轮询」。
    """CREATE TABLE IF NOT EXISTS kms_upload_batches (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT NOT NULL COMMENT '上传人',
        department VARCHAR(128) NOT NULL DEFAULT '' COMMENT '归属部门（上传时快照）',
        total INT NOT NULL DEFAULT 0,
        finished TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=全部处理完毕',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_ub_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 批量上传批次';""",
    """CREATE TABLE IF NOT EXISTS kms_upload_batch_items (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        batch_id BIGINT NOT NULL,
        seq INT NOT NULL COMMENT '提交顺序，前端按此对齐进度条',
        filename VARCHAR(512) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/processing/success/skipped/failed',
        message VARCHAR(512) NOT NULL DEFAULT '' COMMENT '失败原因',
        chunk_count INT NOT NULL DEFAULT 0,
        document_id BIGINT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_bi_batch (batch_id, seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 批量上传明细';""",
]

# 安全职级固定定义（来自 HR 系统，KMS 只读引用）
# 名称取自 constants.SECURITY_LEVELS，避免改名时此处遗漏而与徽章显示不一致。
FIXED_LEVELS = [
    (0, SECURITY_LEVELS[0], "公司内部公开：全体在职员工可见"),
    (1, SECURITY_LEVELS[1], "L1 及以上可读"),
    (2, SECURITY_LEVELS[2], "L2 及以上可读"),
    (3, SECURITY_LEVELS[3], "L3 及以上可读"),
]

_tables_ready = False
_tables_lock = threading.Lock()


def ensure_kms_acl_tables() -> bool:
    """建 KMS 权限表（幂等），含旧 Schema 迁移。MySQL 不可用时返回 False。"""
    global _tables_ready
    if _tables_ready:
        return True
    with _tables_lock:
        if _tables_ready:
            return True
        mysql = MySQLStore()
        try:
            with mysql._conn() as cur:
                for ddl in KMS_DDL:
                    cur.execute(ddl)
                _migrate_schema(cur)
            _tables_ready = True
            logger.info("KMS 权限表就绪（users/doc_levels/audit/tickets/notifications/chat_owners/duties）")
            return True
        except Exception as e:
            logger.warning(f"KMS 权限表初始化失败（MySQL 不可用？）: {e}")
            return False


def _migrate_schema(cur) -> None:
    """Schema 迁移：旧 level → security_level，添加新列，清理旧表。"""
    # 检查 kms_users 是否有 security_level 列
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='kms_users' AND COLUMN_NAME='security_level'")
    has_security_level = cur.fetchone() is not None

    if not has_security_level:
        # 检查是否有旧 level 列
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='kms_users' AND COLUMN_NAME='level'")
        has_old_level = cur.fetchone() is not None

        if has_old_level:
            cur.execute("ALTER TABLE kms_users ADD COLUMN security_level INT NOT NULL DEFAULT 0 "
                        "COMMENT '安全职级 L0-L3（HR 同步）' AFTER role")
            cur.execute("UPDATE kms_users SET security_level = level WHERE security_level = 0")
            # 保留旧列用于回滚；移除旧结构需单独审批迁移。
            logger.info("Schema 迁移: level → security_level")

        # 添加新列
        _add_column_if_missing(cur, "kms_users", "department",
                               "VARCHAR(128) NOT NULL DEFAULT '' COMMENT '所属部门（HR 同步）'")
        _add_column_if_missing(cur, "kms_users", "business_title",
                               "VARCHAR(128) NOT NULL DEFAULT '' COMMENT '业务称谓（HR 同步，仅展示）'")
        _add_column_if_missing(cur, "kms_users", "data_source",
                               "VARCHAR(32) NOT NULL DEFAULT 'local' COMMENT '数据来源'")
        _add_column_if_missing(cur, "kms_users", "hr_synced_at",
                               "DATETIME NULL COMMENT '最近 HR 同步时间'")

    # 工单表新增字段
    _add_column_if_missing(cur, "kms_tickets", "timeout_at",
                           "DATETIME NULL COMMENT '超时时间'")
    _add_column_if_missing(cur, "kms_tickets", "doc_id",
                           "VARCHAR(64) NULL COMMENT '关联文档业务ID'")
    # 关联文档快照：在建单时把 payload.doc_ids 对应的文档元信息序列化
    # 下来——删除工单执行后文档会物理删除，审计时仍能看到「当初想删的是啥」。
    _add_column_if_missing(cur, "kms_tickets", "doc_references",
                           "JSON NULL COMMENT '关联文档快照（建单时写入）'")

    # HR 岗位类别——决定「审计员」这类**治理身份**（不提高可读密级）。
    #
    # 必须放在上面 `if not has_security_level:` 分支**之外**：那个分支只在旧库
    # （尚无 security_level）升级时才进入，已运行过的库若把这一列写在里面，
    # 永远不会被添加——表现为「明明同步了岗位，查出来却总是空」。
    _add_column_if_missing(cur, "kms_users", "hr_position_type",
                           "VARCHAR(32) NOT NULL DEFAULT 'staff' "
                           "COMMENT '岗位类别（HR 单向同步）：staff 普通员工 / auditor 审计员'")

    # —— HR 企业维度（同上：单向同步、只读引用、白名单取值）——
    # 这些字段合起来回答一个问题：「此人是否具备接触涉密信息的资格」。
    # 判据本身收在 kms/security.py 的 hr_secret_eligible()，避免散落多处。
    #
    # 默认值一律取**最保守**一档：hr_status / hr_employment_type 默认 unknown，
    # hr_nda_signed / hr_background_cleared 默认 0。任何"忘了设这几个字段"的
    # 插入路径都应得到「无资格」，而不是「默认有资格」。
    _add_column_if_missing(cur, "kms_users", "hr_status",
                           "VARCHAR(32) NOT NULL DEFAULT 'unknown' "
                           "COMMENT '在职状态（HR同步）：regular/trial/pending_leave/leave/unknown'")
    _add_column_if_missing(cur, "kms_users", "hr_employment_type",
                           "VARCHAR(32) NOT NULL DEFAULT 'unknown' "
                           "COMMENT '用工性质（HR同步）：staff/dispatch/intern/outsource/unknown'")
    _add_column_if_missing(cur, "kms_users", "hr_manager_no",
                           "VARCHAR(64) NOT NULL DEFAULT '' "
                           "COMMENT '直属上级工号（HR同步，汇报线）'")
    _add_column_if_missing(cur, "kms_users", "hr_job_family",
                           "VARCHAR(32) NOT NULL DEFAULT 'professional' "
                           "COMMENT '岗位序列（HR同步）：management/professional/operations/sales'")
    _add_column_if_missing(cur, "kms_users", "hr_job_grade",
                           "VARCHAR(32) NOT NULL DEFAULT '' COMMENT '职等（HR同步），如 P5/M3'")
    _add_column_if_missing(cur, "kms_users", "hr_hire_date",
                           "DATE NULL COMMENT '入职日期（HR同步）'")
    _add_column_if_missing(cur, "kms_users", "hr_nda_signed",
                           "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否签署保密承诺书（HR同步）'")
    _add_column_if_missing(cur, "kms_users", "hr_background_cleared",
                           "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '背景审查是否通过（HR同步）'")

    # _add_column_if_missing 在列已存在时直接跳过，因此**已建过的库**仍带着旧的
    # 宽松默认值。这里显式收敛一次（幂等，可反复执行）——否则老库会一直
    # "忘了设字段 = 默认有资格"，与新库行为不一致。
    for _col, _ddl in (
        ("hr_status", "VARCHAR(32) NOT NULL DEFAULT 'unknown' "
                      "COMMENT '在职状态（HR同步）'"),
        ("hr_employment_type", "VARCHAR(32) NOT NULL DEFAULT 'unknown' "
                               "COMMENT '用工性质（HR同步）'"),
        ("hr_nda_signed", "TINYINT(1) NOT NULL DEFAULT 0 "
                          "COMMENT '是否签署保密承诺书（HR同步）'"),
        ("hr_background_cleared", "TINYINT(1) NOT NULL DEFAULT 0 "
                                  "COMMENT '背景审查是否通过（HR同步）'"),
    ):
        try:
            # 复用 _migrate_schema(cur) 传入的游标（同一连接），不开新连接
            cur.execute(f"ALTER TABLE kms_users MODIFY COLUMN {_col} {_ddl}")
        except Exception as e:  # 列不存在等情况：不影响启动，交由同步补齐
            logger.warning(f"收敛 kms_users.{_col} 默认值跳过: {e}")

    # 清理旧表（职责/提权/动态层级 —— 已移除）
    # 旧表保留供审计回溯，不在服务启动阶段删除。

    # 迁移旧 kms_doc_levels 数据到 documents.doc_level（如果 documents 有 doc_level 列）
    #
    # 原实现是 `except Exception: pass` —— 静默吞掉迁移失败。后果不是"少搬点数据"：
    # get_doc_level() 对无密级文档 fail-closed 判为 level=4 不可读，表现为
    # 「文档突然全部消失」，且日志里毫无线索，极难排查。密级迁移失败必须显眼。
    try:
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND COLUMN_NAME='doc_level'")
        if cur.fetchone() is not None:
            cur.execute("SELECT COUNT(*) AS c FROM kms_doc_levels")
            if int(cur.fetchone()["c"]) > 0:
                cur.execute(
                    "UPDATE documents d JOIN kms_doc_levels dl ON d.id = dl.document_id "
                    "SET d.doc_level = dl.level WHERE d.doc_level IS NULL OR d.doc_level = 0"
                )
                logger.info("Schema 迁移: kms_doc_levels → documents.doc_level")
    except Exception as e:
        # error 级 + 明确影响面：失败会导致无密级文档被判不可读（静默消失）
        logger.error(
            "Schema 迁移失败 kms_doc_levels → documents.doc_level: "
            f"{type(e).__name__}: {e}。"
            "未迁移密级的文档将被 fail-closed 判为不可读（表现为文档消失），"
            "请人工核对 kms_doc_levels 与 documents.doc_level。"
        )


def _add_column_if_missing(cur, table: str, column: str, definition: str) -> None:
    """幂等添加列。"""
    try:
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
            (table, column),
        )
        if cur.fetchone() is None:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            logger.info(f"Schema 迁移: 添加 {table}.{column}")
    except Exception as e:
        logger.warning(f"添加列 {table}.{column} 失败: {e}")


# ===================== 用户数据访问 =====================
def get_user_by_id(user_id: int) -> Optional[dict]:
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT * FROM kms_users WHERE id=%s", (user_id,))
        return cur.fetchone()


def get_user_by_employee_no(employee_no: str) -> Optional[dict]:
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT * FROM kms_users WHERE employee_no=%s", (employee_no,))
        return cur.fetchone()


def list_users() -> List[dict]:
    """员工列表（只读，来自 HR 同步镜像）。按工号升序——展示口径统一，
    员工表/筛选下拉/工单选项（routes_tickets options）均为工号序。"""
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT id, employee_no, username, role, security_level, department, "
            "business_title, is_active, data_source, hr_synced_at, last_login_at, created_at "
            "FROM kms_users ORDER BY employee_no"
        )
        users = cur.fetchall()
        for u in users:
            # 兼容旧代码: level 别名
            u["level"] = u.get("security_level", 0)
            # 安全职级标签（员工层级统一显示 L0-L3，不沿用文档密级名称）
            u["security_level_label"] = f"L{u.get('security_level', 0)}"
        return users


def create_user(
    employee_no: str,
    username: str,
    password: str,
    security_level: int = 0,
    department: str = "",
    business_title: str = "",
) -> int:
    """创建员工记录（通常由 HR 同步触发，此处用于初始化/测试）。"""
    with MySQLStore()._conn() as cur:
        cur.execute(
            "INSERT INTO kms_users (employee_no, username, password_hash, role, "
            "security_level, department, business_title) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (employee_no, username, hash_password(password), "employee",
             security_level, department, business_title),
        )
        return int(cur.lastrowid)


def update_user(user_id: int, fields: dict) -> None:
    """按白名单字段更新员工（不含密码，密码走 change_password）。"""
    allowed = {"username", "security_level", "department", "business_title", "is_active"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=%s")
            params.append(v)
    if not sets:
        return
    params.append(user_id)
    with MySQLStore()._conn() as cur:
        cur.execute(f"UPDATE kms_users SET {', '.join(sets)} WHERE id=%s", tuple(params))


def reset_password(user_id: int, new_password: str) -> None:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "UPDATE kms_users SET password_hash=%s WHERE id=%s",
            (hash_password(new_password), user_id),
        )


def update_password(user_id: int, new_password: str) -> None:
    reset_password(user_id, new_password)


def delete_user(user_id: int) -> None:
    """物理删除员工（由 HR 同步触发离职清理，一般不手动调用）。"""
    with MySQLStore()._conn() as cur:
        cur.execute("DELETE FROM kms_users WHERE id=%s", (user_id,))
        cur.execute("DELETE FROM kms_chat_owners WHERE user_id=%s", (user_id,))


def touch_last_login(user_id: int) -> None:
    try:
        with MySQLStore()._conn() as cur:
            cur.execute("UPDATE kms_users SET last_login_at=NOW() WHERE id=%s", (user_id,))
    except Exception as e:
        logger.warning(f"更新最后登录时间失败: {e}")


# ===================== BLP 访问控制 =====================
def can_read_doc(
    emp_security_level: int,
    doc_level: int,
    emp_dept: str,
    doc_departments,  # JSON 数组或列表,所有归属部门平等
    emp_org_path: str = "",
    doc_org_path: str = "",
) -> bool:
    """BLP 读权限(不上读)+ 部门可见范围 + 组织层级继承。

    这是「用户能否读取某文档」的**单一事实源**,gateway/service.allowed 复用其
    部门/组织判定,避免策略双实现漂移。

    方案 A:所有归属部门平等,无主次之分。

    **判定顺序与语义（重要）**:
      密级(classification)只充当「职级上限」门槛，**不再**让 L0 绕过部门判定。
      归属部门才是可见范围的唯一开关——「L0 + 归属部门=综合管理部」的文档
      产品管理部同样读不到；只有「归属部门=不限（*）」才全员可见。

    条件(全部为「与」关系):
    0. doc_level <= emp_security_level(密级校验,不上读)
    1. doc_departments 包含「*」= 选了「不限部门」→ 视为全员可见（至密级门槛）
    2. emp_dept IN doc_departments(员工部门在归属部门数组中)
    3. doc_org_path 是 emp_org_path 的后代(组织层级继承,上级可见下级)
       例 emp_org_path='银联商务/风险控制部',
          doc_org_path='银联商务/风险控制部/风控策略组' → 可见
    """
    # 密级校验:不上读（这是唯一由密级决定的判定）
    if doc_level > emp_security_level:
        return False
    # 解析 departments 参数
    departments = doc_departments or []
    if isinstance(departments, str):
        try:
            departments = json.loads(departments)
        except (json.JSONDecodeError, TypeError):
            departments = []
    if not isinstance(departments, list):
        departments = []
    # 显式「不限部门」:密级已通过,可见范围扩到全员（含未登录 L0 读者）
    if DOC_DEPT_UNLIMITED in departments:
        return True
    # 部门精确匹配:员工部门 IN 归属部门数组（归一化后比较，容错 HR 脏数据空格）
    if emp_dept and normalize_department(emp_dept) in {
            normalize_department(d) for d in departments if d}:
        return True
    # 组织层级继承(上级看下级)
    if emp_org_path and doc_org_path and (
        doc_org_path == emp_org_path or doc_org_path.startswith(emp_org_path + "/")
    ):
        return True
    return False


def can_write_doc(
    emp_security_level: int,
    doc_level: int,
    emp_dept: str,
    doc_departments,  # JSON 数组或列表
) -> bool:
    """BLP 写权限(不下写)+ 部门规则。

    方案 A:员工部门 IN 文档归属部门数组即可写。

    条件:
    1. doc_level >= emp_security_level(密级校验)
    2. emp_dept IN doc_departments(部门校验:写操作要求员工部门在归属部门数组中)
    """
    # 密级校验:不下写
    if doc_level < emp_security_level:
        return False
    # 解析 departments
    departments = doc_departments or []
    if isinstance(departments, str):
        try:
            departments = json.loads(departments)
        except (json.JSONDecodeError, TypeError):
            departments = []
    if not isinstance(departments, list):
        departments = []
    # 部门校验:员工部门 IN 归属部门数组（归一化后比较，容错 HR 脏数据空格）
    if not departments or not emp_dept:
        return False
    norm_emp = normalize_department(emp_dept)
    return norm_emp in {normalize_department(d) for d in departments if d}


def find_candidate_approvers(doc_level: int, doc_departments) -> List[dict]:
    """筛选满足 BLP + 部门规则的候选审批人。

    方案 A:审批人可来自任意一个归属部门。

    条件:
    1. security_level >= doc_level(满足 BLP 读规则)
    2. department IN doc_departments(员工部门在归属部门数组中)
    3. is_active = 1(在职)
    """
    # 解析 departments
    departments = doc_departments or []
    if isinstance(departments, str):
        try:
            departments = json.loads(departments)
        except (json.JSONDecodeError, TypeError):
            departments = []
    if not isinstance(departments, list):
        departments = []
    if not departments:
        return []
    # 构建 IN 子句
    # SQL 侧同步去除空白（ASCII 空格 + 全角空格），与 normalize_department 口径一致：
    # 否则「综合 管理部」的审批人会被漏掉，表现为「无合格审批人」。
    norm_depts = [normalize_department(d) for d in departments if d]
    if not norm_depts:
        return []
    placeholders = ",".join(["%s"] * len(norm_depts))
    norm_sql = "REPLACE(REPLACE(REPLACE(department,' ',''),'　',''),'\t','')"
    with MySQLStore()._conn() as cur:
        cur.execute(
            f"SELECT id, employee_no, username, security_level, department, business_title "
            f"FROM kms_users "
            f"WHERE security_level >= %s AND {norm_sql} IN ({placeholders}) AND is_active = 1 "
            f"ORDER BY security_level DESC, employee_no",
            [doc_level] + norm_depts,
        )
        return cur.fetchall()


# ===================== 员工职责 =====================
# 系统中不存在「管理员」角色：谁能审批工单，由是否持有 ticket_approve 职责决定，
# 职责通过工单（user_duty_grant）授予与回收，全程可审计。
def list_user_duties(user_id: int) -> List[str]:
    """某员工的职责键列表。"""
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT duty FROM kms_user_duties WHERE user_id=%s ORDER BY duty",
                    (user_id,))
        return [r["duty"] for r in cur.fetchall()]


def has_duty(user_id: int, duty: str) -> bool:
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT 1 FROM kms_user_duties WHERE user_id=%s AND duty=%s LIMIT 1",
                    (user_id, duty))
        return cur.fetchone() is not None


def grant_duty(user_id: int, duty: str, granted_by: Optional[int] = None) -> None:
    """授予职责（幂等）。"""
    with MySQLStore().transaction() as cur:
        cur.execute(
            "INSERT INTO kms_user_duties (user_id, duty, granted_by) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE granted_by=VALUES(granted_by), "
            "granted_at=CURRENT_TIMESTAMP",
            (user_id, duty, granted_by),
        )


def revoke_duty(user_id: int, duty: str) -> None:
    with MySQLStore().transaction() as cur:
        cur.execute("DELETE FROM kms_user_duties WHERE user_id=%s AND duty=%s",
                    (user_id, duty))


def find_duty_holders(duty: str, exclude_user_id: Optional[int] = None) -> List[dict]:
    """持有指定职责的在职员工——工单审批人候选来源。

    只按职责匹配，不看 is_admin：系统中没有管理员，审批权是授予出来的职责。
    exclude_user_id 用于排除申请人本人，保证 A/B 分离（自己不能审自己）。
    """
    sql = (
        "SELECT u.id, u.employee_no, u.username, u.security_level, u.department, "
        "u.business_title FROM kms_user_duties d "
        "JOIN kms_users u ON u.id = d.user_id "
        "WHERE d.duty = %s AND u.is_active = 1"
    )
    params: list = [duty]
    if exclude_user_id is not None:
        sql += " AND u.id <> %s"
        params.append(exclude_user_id)
    sql += " ORDER BY u.security_level DESC, u.employee_no"
    with MySQLStore()._conn() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchall()


def approver_candidates(classification: Optional[int], departments,
                        exclude_user_id: Optional[int] = None) -> List[dict]:
    """可审批该文档的在职员工候选。

    方案 A:审批人可来自任意一个归属部门。

    判据与「能不能读到这篇文档」**完全一致**,这也是整套改动的核心:
    审批权不该来自一份单独维护的职责名单,否则会漂移——
    职责名单说张三能审,而 BLP 说张三看不见这篇文档,这就是不一致的来源。

      - 安全职级 >= 文档密级(BLP 不上读)
      - 在职,且非申请人本人(A/B 分离)
      - **涉密文档(L2/L3)另加准入门槛**:审批人本人也须具备涉密准入资格
        (正式员工 + 在职/试用 + 已签保密承诺 + 背景审查通过,判定见
        security.hr_secret_eligible)。让没有资格的人去审批一篇他无权接触的
        文档,等于把把关的人换成门外汉——形式上是双人审批,实质上是单人决定。
      - 员工部门 IN 文档归属部门数组(跨部门审批等于让看不见的人签字)。
        **departments 包含「*」时不校验部门**——
        这类文档对所有职级足够的员工可见,自然也不该限定审批人出自某个部门。
        departments 为空(未登记)则无人可审,保持 fail-closed。

    classification 为 None 表示缺密级记录,按最高密级处理(fail-closed),
    与 manageable() 等既有判据口径一致。
    """
    level = MAX_EMPLOYEE_LEVEL if classification is None else int(classification)
    # 解析 departments
    dept_list = departments or []
    if isinstance(dept_list, str):
        try:
            dept_list = json.loads(dept_list)
        except (json.JSONDecodeError, TypeError):
            dept_list = []
    if not isinstance(dept_list, list):
        dept_list = []
    # 三态:不限(哨兵)→ 只按职级;有部门 → 限该部门;未登记(空)→ 无人可审。
    if DOC_DEPT_UNLIMITED in dept_list:
        sql = ("SELECT id, employee_no, username, security_level, department, business_title "
               "FROM kms_users "
               "WHERE is_active = 1 AND security_level >= %s")
        params: list = [level]
    elif dept_list:
        # SQL 侧同步去除空白（ASCII/全角/制表符），与 normalize_department 同口径：
        # 否则 HR 台账里「综合 管理部」的用户会从审批人候选里消失。
        norm_depts = [normalize_department(d) for d in dept_list if d]
        if not norm_depts:
            return []
        placeholders = ",".join(["%s"] * len(norm_depts))
        norm_sql = "REPLACE(REPLACE(REPLACE(department,' ',''),'　',''),'\t','')"
        sql = ("SELECT id, employee_no, username, security_level, department, business_title "
               "FROM kms_users "
               f"WHERE is_active = 1 AND {norm_sql} IN ({placeholders}) "
               "AND security_level >= %s")
        params: list = norm_depts + [level]
    else:
        return []
    # 涉密文档(L2/L3)的审批人本人也须具备涉密准入资格。
    # 这一条对「不限部门」同样生效——不限只是放开部门维度,不放开保密资格。
    if level >= SECURITY_LEVEL_CONFIDENTIAL:
        sql += (" AND hr_employment_type=%s AND hr_status IN (%s,%s) "
                "AND hr_nda_signed=1 AND hr_background_cleared=1")
        params += [HR_EMPLOYMENT_STAFF, HR_STATUS_REGULAR, HR_STATUS_TRIAL]
    if exclude_user_id is not None:
        sql += " AND id <> %s"
        params.append(exclude_user_id)
    sql += " ORDER BY security_level DESC, employee_no"
    with MySQLStore()._conn() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchall()


def pick_approver(classification: Optional[int], departments,
                  exclude_user_id: Optional[int] = None) -> Optional[dict]:
    """从候选中随机指派一名审批人;无合格候选人时返回 None(由调用方明确报错)。

    方案 A:审批人可来自任意一个归属部门。

    用 secrets 而非 random:指派结果事后是可观测的,若序列可预测,
    申请人就能提前推算出谁会审自己的单。这里虽非密钥,但让选择不可预测
    能抬高这类操纵成本。
    """
    candidates = approver_candidates(classification, departments, exclude_user_id)
    return secrets.choice(candidates) if candidates else None


def can_approve_document(user: Optional[AuthUser], classification: Optional[int],
                         departments) -> bool:
    """某人是否具备审批/管理该文档的资格(与 approver_candidates 同一判据)。

    方案 A:员工部门 IN 文档归属部门数组即可审批。

    这是「能否管理一篇文档」的单一事实源,routes_kms.manageable() 直接委托
    于此,避免策略双实现漂移。

    三态部门判定:数组含 * = 不限部门(只按职级);空 = 未登记(fail-closed)。
    """
    if user is None or not getattr(user, "is_active", True) or not user.department:
        return False
    # 解析 departments
    dept_list = departments or []
    if isinstance(dept_list, str):
        try:
            dept_list = json.loads(dept_list)
        except (json.JSONDecodeError, TypeError):
            dept_list = []
    if not isinstance(dept_list, list):
        dept_list = []
    if not dept_list:
        return False
    # 归一化后比较，容错 HR 台账复制带来的空格（「综合 管理部」≡「综合管理部」）
    norm_user = normalize_department(user.department)
    norm_depts = {normalize_department(d) for d in dept_list if d}
    if DOC_DEPT_UNLIMITED not in dept_list and norm_user not in norm_depts:
        return False
    level = MAX_EMPLOYEE_LEVEL if classification is None else int(classification)
    return user.security_level >= level


# ===================== 可写密级区间 =====================
# 说明：原有的「仅判密级、不判部门」兼容接口（can_read / can_write）已删除。
# 它们虽标为兼容层，但语义比线上策略（can_read_doc / can_write_doc）**更宽松**
# ——跨部门也能通过，且线上零调用。留着只会诱导误用、绕过部门隔离。
def max_writable_level(user: Optional[AuthUser]) -> int:
    """用户可写的最高密级。

    BLP 不下写：可写区间为 [security_level, L3]，故最高可写恒为最高密级 L3。
    该返回值与身份无关，是 BLP 语义的自然结果（非失效代码）。
    """
    if user is None:
        return -1
    return 3  # L3 绝密


def min_writable_level(user: Optional[AuthUser]) -> int:
    """用户可写的最低密级。"""
    if user is None:
        return -1
    return user.security_level


# ===================== 审计日志 =====================
#
# 注：原此处有 5 个「文档密级」helper（get_doc_level / get_doc_levels_map /
# set_doc_level / clear_doc_level + 一个进程内 _doc_level_cache），已整体删除。
#
# 删除理由（三重，缺一不可）：
#   1. 零调用方——生产读路径全部走实时 SQL JOIN，不经此缓存：
#      gateway/service.py 的 current_contexts() 与 documents() 均
#      `JOIN kms_doc_levels l ON l.document_id=d.id`，密级变更本就立即生效；
#   2. 缓存无 TTL、无跨进程失效，且 set_doc_level() 会刷新缓存而实际写入方
#      （routes_kms.py:157/259 的内联 SQL）不刷新——一旦有人接入，密级提权后
#      本进程会长期返回旧低值，形成越权读取窗口；
#   3. 「文档缺密级 → fail-closed 判不可读」这一安全约定由 INNER JOIN 天然保证
#      （无 kms_doc_levels 行的文档根本不在结果集里），无需 helper 再实现一遍。
#
# 若将来确需按 ID 单查密级，请直接查 kms_doc_levels，不要重新引入进程内缓存。
def add_audit(
    user: Optional[AuthUser],
    action: str,
    target: str = "",
    detail: str = "",
    ip: str = "",
) -> None:
    """记录审计日志；失败仅告警不影响主流程。"""
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "INSERT INTO kms_audit_logs (user_id, employee_no, action, target, detail, ip) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    user.id if user else None,
                    user.employee_no if user else None,
                    action,
                    target[:512],
                    detail[:2000],
                    ip[:64],
                ),
            )
    except Exception as e:
        logger.warning(f"审计日志写入失败: {e}")


def list_audit_logs(
    action: Optional[str] = None,
    employee_no: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[dict]:
    query = (
        "SELECT id, user_id, employee_no, action, target, detail, ip, created_at "
        "FROM kms_audit_logs"
    )
    conds, params = [], []
    if action:
        conds.append("action=%s")
        params.append(action)
    if employee_no:
        conds.append("employee_no=%s")
        params.append(employee_no)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY id DESC LIMIT %s OFFSET %s"
    params.extend([int(limit), int(offset)])
    with MySQLStore()._conn() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
    for r in rows:
        if r.get("created_at") and not isinstance(r["created_at"], str):
            r["created_at"] = str(r["created_at"])
    return rows


# ===================== 站内通知 =====================
def add_notification(
    user_id: int,
    title: str,
    content: str = "",
    ticket_id: Optional[int] = None,
    ntype: str = "ticket",
) -> None:
    """发送站内通知；失败仅告警不影响主流程。"""
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "INSERT INTO kms_notifications (user_id, ticket_id, ntype, title, content) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, ticket_id, ntype, title[:255], content[:1024]),
            )
    except Exception as e:
        logger.warning(f"站内通知写入失败: {e}")


def list_notifications(user_id: int, limit: int = 50) -> List[dict]:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT id, ticket_id, ntype, title, content, is_read, created_at "
            "FROM kms_notifications WHERE user_id=%s ORDER BY id DESC LIMIT %s",
            (user_id, int(limit)),
        )
        rows = cur.fetchall()
    for r in rows:
        if r.get("created_at") and not isinstance(r["created_at"], str):
            r["created_at"] = str(r["created_at"])
    return rows


def unread_notification_count(user_id: int) -> int:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM kms_notifications WHERE user_id=%s AND is_read=0",
            (user_id,),
        )
        return int(cur.fetchone()["c"])


def mark_notification_read(notif_id: int, user_id: int) -> bool:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "UPDATE kms_notifications SET is_read=1 WHERE id=%s AND user_id=%s",
            (notif_id, user_id),
        )
        return cur.rowcount > 0


def mark_all_notifications_read(user_id: int) -> int:
    with MySQLStore()._conn() as cur:
        cur.execute(
            "UPDATE kms_notifications SET is_read=1 WHERE user_id=%s AND is_read=0",
            (user_id,),
        )
        return cur.rowcount


# ===================== 会话归属（问答历史隔离） =====================
def set_chat_owner(session_id: str, user_id: int) -> None:
    try:
        with MySQLStore()._conn() as cur:
            cur.execute(
                "INSERT IGNORE INTO kms_chat_owners (session_id, user_id) VALUES (%s, %s)",
                (session_id, user_id),
            )
    except Exception as e:
        logger.warning(f"会话归属写入失败: {e}")


def visible_sessions_sql(user: Optional[AuthUser]) -> Tuple[Optional[str], tuple]:
    """会话可见性 SQL 条件。

    返回:
        ("1=0", ())     — 不可见（未认证）
        (cond, params)  — 仅本人会话
    """
    if user is None:
        return "1=0", ()
    return (
        "session_id IN (SELECT session_id FROM kms_chat_owners WHERE user_id=%s)",
        (user.id,),
    )


# 注：原 readable_where() / filter_contexts_by_clearance() 已删除——
# 二者只按密级过滤、不含部门约束，比线上策略宽松且零调用，属易被误用的影子实现。
# 检索上下文与目录列表的可见性判定统一走 gateway/service.allowed() 与 documents()。
