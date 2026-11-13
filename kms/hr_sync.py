"""KMS 人事主数据同步模块。

架构原则
--------
KMS 不维护人事主数据，只做引用。人事主体（账号、部门、业务称谓、安全职级 L0-L3）
单向只读从企业 HR 系统同步导入，KMS 内不能新增、编辑、修改人员原始信息。

数据归属划分
-----------
- HR 系统（权威来源）：工号、姓名、部门、业务称谓、安全职级、在职状态
- KMS（只读引用 + 扩展）：审计日志、文档/知识管理、工单流程、收藏/评分

同步策略
--------
1. 全量同步: 定时从 HR 拉取全量员工列表，upsert 到 KMS
2. 增量同步: 仅同步最近变更的员工
3. 手动触发: L2+ 员工可手动触发一次同步
4. 同步失败告警: 记录失败日志，使用旧缓存数据兜底
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Dict, List, Optional

from app.logger import get_logger
from app.store import MySQLStore

from .constants import (
    HR_EMPLOYMENTS,
    HR_EMPLOYMENT_LABELS,
    HR_EMPLOYMENT_UNKNOWN,
    HR_JOB_FAMILIES,
    HR_JOB_FAMILY_LABELS,
    HR_JOB_FAMILY_PROF,
    HR_POSITIONS,
    HR_POSITION_STAFF,
    HR_STATUS_UNKNOWN,
    HR_STATUSES,
    HR_STATUS_LABELS,
)

logger = get_logger("kms.hr_sync")


# ===================== DDL =====================
HR_SYNC_DDL = [
    # HR 同步日志表
    """CREATE TABLE IF NOT EXISTS kms_hr_sync_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        sync_type VARCHAR(32) NOT NULL COMMENT 'full/incremental/manual',
        source_type VARCHAR(32) NOT NULL COMMENT 'hr_api/hr_db/csv_file',
        total_count INT NOT NULL DEFAULT 0 COMMENT '本次同步总数',
        created_count INT NOT NULL DEFAULT 0 COMMENT '新增数',
        updated_count INT NOT NULL DEFAULT 0 COMMENT '更新数',
        deactivated_count INT NOT NULL DEFAULT 0 COMMENT '停用数',
        error_count INT NOT NULL DEFAULT 0 COMMENT '失败数',
        error_detail TEXT NULL COMMENT '失败详情（JSON）',
        started_at DATETIME NOT NULL COMMENT '同步开始时间',
        finished_at DATETIME NULL COMMENT '同步结束时间',
        triggered_by BIGINT NULL COMMENT '触发人',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_type (sync_type),
        INDEX idx_time (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='HR 同步日志';""",
]


def ensure_hr_sync_columns() -> bool:
    """为 kms_users 表增加 HR 同步字段（幂等）。"""
    mysql = MySQLStore()
    success = 0
    for ddl in HR_SYNC_DDL:
        try:
            with mysql._conn() as cur:
                cur.execute(ddl)
            success += 1
        except Exception as e:
            if "Duplicate column" not in str(e) and "Duplicate key" not in str(e):
                logger.warning(f"HR 同步字段扩展跳过: {e}")
    if success > 0:
        logger.info(f"HR 同步字段就绪（{success} 项 DDL 执行成功）")
    return success == len(HR_SYNC_DDL)


# ===================== HR 员工数据结构 =====================

class HREmployeeData:
    """从 HR 系统同步的员工数据结构。"""
    def __init__(
        self,
        employee_no: str,
        username: str,
        department: str = "",
        business_title: str = "",  # 业务称谓（普通员工/经理等，仅展示）
        security_level: int = 0,   # L0-L3
        is_active: bool = True,
        hr_employee_id: str = "",
        extra: Optional[Dict] = None,
        position_type: str = HR_POSITION_STAFF,
        status: str = HR_STATUS_UNKNOWN,
        employment_type: str = HR_EMPLOYMENT_UNKNOWN,
        manager_no: str = "",
        job_family: str = HR_JOB_FAMILY_PROF,
        job_grade: str = "",
        hire_date=None,
        nda_signed=None,
        background_cleared=None,
    ):
        self.employee_no = employee_no
        self.username = username
        self.department = department
        self.business_title = business_title
        self.security_level = security_level
        self.is_active = is_active
        self.hr_employee_id = hr_employee_id or employee_no
        self.extra = extra or {}
        # 岗位类别决定「审计员」这类治理身份，故取值必须受控：HR 给到未登记的
        # 值时降级为 staff。宁可少给权限，也不能让一个未知值写进库——那会让
        # 后续所有 == 'auditor' 的判定静默失效，且看起来像是「同步成功了」。
        pt = (position_type or "").strip().lower()
        if pt not in HR_POSITIONS:
            if pt:
                logger.warning(
                    f"HR 同步 employee_no={employee_no} 的岗位类别 {pt!r} 未登记，"
                    f"已降级为 {HR_POSITION_STAFF}"
                )
            pt = HR_POSITION_STAFF
        self.position_type = pt
        # 企业维度统一走白名单校验（见 set_org_attrs 的方法注释）
        self.set_org_attrs(status, employment_type, manager_no, job_family,
                           job_grade, hire_date, nda_signed, background_cleared)

    # —— 企业 HR 维度（新增字段统一走 _pick 白名单校验）——
    # 为何不直接赋值：HR 源（CSV / LDAP / 第三方接口）字段拼写与取值并不稳定，
    # 一个未登记的值若原样落库，后续所有判定都会静默按字面量比较而失效——
    # 表现为"明明同步成功了，资格却算不出来"。故一律降级到保守档并告警。
    def _pick(self, value: str, allowed, labels, fallback: str, what: str) -> str:
        v = (value or "").strip().lower()
        if v in allowed:
            return v
        if v:
            logger.warning(
                f"HR 同步 employee_no={self.employee_no} 的{what} {v!r} 未登记，"
                f"已降级为 {fallback}（{labels.get(fallback, fallback)}）"
            )
        return fallback

    def set_org_attrs(self, status: str, employment_type: str, manager_no: str,
                      job_family: str, job_grade: str, hire_date,
                      nda_signed, background_cleared) -> None:
        # 降级方向必须是**收紧**：未知的用工性质落到 unknown（无涉密资格），
        # 而不是落到 staff（最宽松）。若图省事落在 staff 上，"外包驻场"这种
        # 未登记写法就会被静默授予正式员工资格——那正是白名单要防的事。
        self.status = self._pick(status, HR_STATUSES, HR_STATUS_LABELS,
                                 HR_STATUS_UNKNOWN, "在职状态")
        self.employment_type = self._pick(employment_type, HR_EMPLOYMENTS,
                                          HR_EMPLOYMENT_LABELS,
                                          HR_EMPLOYMENT_UNKNOWN, "用工性质")
        self.manager_no = (manager_no or "").strip()[:64]
        self.job_family = self._pick(job_family, HR_JOB_FAMILIES,
                                     HR_JOB_FAMILY_LABELS,
                                     HR_JOB_FAMILY_PROF, "岗位序列")
        self.job_grade = (job_grade or "").strip()[:32]
        self.hire_date = hire_date or None
        # 布尔字段只认 0/1/true/false/是/否。缺省 False（未提供 = 未具备资格）：
        # 这两个是保密准入的前提，HR 没说就等于没有，不能反过来说不清就当有。
        self.nda_signed = _as_bool(nda_signed, default=False)
        self.background_cleared = _as_bool(background_cleared, default=False)


def _as_bool(value, default: bool = True) -> bool:
    """把 HR 侧各种布尔写法归一化。认不出的值返回 default，不抛异常。

    同步是批处理：一行脏数据不该让整批失败（那会表现为"人事一动，全员降级"），
    但也不该被当成 true——所以 default 由调用方按保守程度显式决定。
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "是", "已签署", "通过"):
        return True
    if s in ("0", "false", "no", "n", "否", "未签署", "未通过"):
        return False
    return default


# ===================== 同步核心逻辑 =====================

def sync_employees(
    employees: List[HREmployeeData],
    source_type: str = "hr_api",
    sync_type: str = "full",
    triggered_by: Optional[int] = None,
) -> Dict:
    """将 HR 员工数据同步到 KMS（upsert 策略）。

    规则:
    1. 工号已存在 → 更新 HR 字段（姓名/部门/业务称谓/密级/在职状态）
    2. 工号不存在 → 新建账号（初始密码随机生成，须首次登录修改）
    3. HR 标记离职 → KMS 自动停用（is_active=0）
    4. 不触碰 KMS 扩展字段（密码/审计等）

    Returns:
        {total, created, updated, deactivated, errors}
    """
    mysql = MySQLStore()
    started_at = datetime.now()
    result = {"total": len(employees), "created": 0, "updated": 0, "deactivated": 0, "errors": []}

    from . import access_control as acl

    for emp in employees:
        try:
            existing = acl.get_user_by_employee_no(emp.employee_no)

            if existing:
                # 更新 HR 字段（不触碰 role/duties/password）
                updates = {
                    "username": emp.username,
                    "department": emp.department,
                    "business_title": emp.business_title,
                    "security_level": emp.security_level,
                    "hr_position_type": emp.position_type,
                    "hr_status": emp.status,
                    "hr_employment_type": emp.employment_type,
                    "hr_manager_no": emp.manager_no,
                    "hr_job_family": emp.job_family,
                    "hr_job_grade": emp.job_grade,
                    "hr_hire_date": emp.hire_date,
                    "hr_nda_signed": int(emp.nda_signed),
                    "hr_background_cleared": int(emp.background_cleared),
                    "data_source": "hr_sync",
                    "hr_synced_at": started_at,
                }
                # HR 标记离职 → 停用
                if not emp.is_active and existing.get("is_active"):
                    updates["is_active"] = 0
                    result["deactivated"] += 1
                elif emp.is_active and not existing.get("is_active"):
                    # HR 重新入职 → 恢复
                    updates["is_active"] = 1

                set_clause = ", ".join(f"{k} = %s" for k in updates)
                params = list(updates.values()) + [existing["id"]]

                with mysql._conn() as cur:
                    cur.execute(f"UPDATE kms_users SET {set_clause} WHERE id = %s", params)
                result["updated"] += 1

            else:
                # 新建：初始密码随机生成（不落盘不返回），须由本人经安全渠道首次登录后修改
                initial_password = secrets.token_urlsafe(32)
                user_id = acl.create_user(
                    emp.employee_no, emp.username, initial_password,
                    security_level=emp.security_level,
                    department=emp.department,
                    business_title=emp.business_title,
                )
                # 补充 HR 同步标记（create_user 不接人事维度，故在此补写）
                with mysql._conn() as cur:
                    cur.execute(
                        "UPDATE kms_users SET data_source='hr_sync', hr_synced_at=%s,"
                        "is_active=%s, hr_position_type=%s, hr_status=%s,"
                        "hr_employment_type=%s, hr_manager_no=%s, hr_job_family=%s,"
                        "hr_job_grade=%s, hr_hire_date=%s, hr_nda_signed=%s,"
                        "hr_background_cleared=%s WHERE id=%s",
                        (started_at, int(emp.is_active), emp.position_type, emp.status,
                         emp.employment_type, emp.manager_no, emp.job_family,
                         emp.job_grade, emp.hire_date, int(emp.nda_signed),
                         int(emp.background_cleared), user_id),
                    )
                result["created"] += 1

        except Exception as e:
            result["errors"].append({
                "employee_no": emp.employee_no,
                "error": str(e),
            })
            logger.error(f"HR 同步失败: {emp.employee_no} - {e}")

    # 记录同步日志
    finished_at = datetime.now()
    try:
        with mysql._conn() as cur:
            cur.execute(
                """INSERT INTO kms_hr_sync_logs
                   (sync_type, source_type, total_count, created_count,
                    updated_count, deactivated_count, error_count,
                    error_detail, started_at, finished_at, triggered_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (sync_type, source_type, result["total"], result["created"],
                 result["updated"], result["deactivated"], len(result["errors"]),
                 json.dumps(result["errors"][:50]), started_at, finished_at, triggered_by),
            )
    except Exception as e:
        logger.error(f"记录同步日志失败: {e}")

    logger.info(
        f"HR 同步完成: total={result['total']}, created={result['created']}, "
        f"updated={result['updated']}, deactivated={result['deactivated']}, "
        f"errors={len(result['errors'])}"
    )
    return result


# ===================== 同步数据源适配器 =====================

def parse_csv_employees(rows: List[dict]) -> List[HREmployeeData]:
    """从 CSV/Excel 行数据解析 HR 员工列表。

    支持的列名（中英文均可）:
    - employee_no / 工号
    - username / 姓名
    - department / 部门
    - position / 职位
    - security_level / 密级 / level
    - is_active / 在职
    - position_type / 岗位类别（staff / auditor）
    - hr_status / 在职状态（regular / trial / pending_leave / leave）
    - hr_employment_type / 用工性质（staff / dispatch / intern / outsource）
    - hr_manager_no / 直属上级工号
    - hr_job_family / 岗位序列（management / professional / operations / sales）
    - hr_job_grade / 职等（如 P5、M3）
    - hr_hire_date / 入职日期
    - hr_nda_signed / 保密承诺（0/1）
    - hr_background_cleared / 背景审查（0/1）

    未登记的取值一律降级到保守档并记 warning，不让脏数据静默通过。
    """
    employees = []
    for row in rows:
        emp_no = (row.get("employee_no") or row.get("工号") or "").strip()
        if not emp_no:
            continue

        username = (row.get("username") or row.get("姓名") or emp_no).strip()
        department = (row.get("department") or row.get("部门") or "").strip()
        business_title = (row.get("business_title") or row.get("业务称谓") or row.get("position") or row.get("职位") or "").strip()

        level_str = str(row.get("security_level") or row.get("密级") or row.get("level") or "0")
        try:
            level = int(level_str)
        except ValueError:
            level = 1

        active_str = str(row.get("is_active") or row.get("在职") or "1")
        is_active = active_str.lower() not in ("0", "false", "否", "离职")

        hr_id = (row.get("hr_employee_id") or row.get("HR工号") or emp_no).strip()

        employees.append(HREmployeeData(
            employee_no=emp_no,
            username=username,
            department=department,
            business_title=business_title,
            security_level=level,
            is_active=is_active,
            hr_employee_id=hr_id,
            position_type=(row.get("position_type") or row.get("岗位类别") or "").strip(),
            status=(row.get("hr_status") or row.get("status") or row.get("在职状态") or ""),
            employment_type=(row.get("hr_employment_type") or row.get("employment_type")
                             or row.get("用工性质") or ""),
            manager_no=(row.get("hr_manager_no") or row.get("manager_no")
                        or row.get("直属上级") or row.get("上级工号") or ""),
            job_family=(row.get("hr_job_family") or row.get("job_family")
                        or row.get("岗位序列") or ""),
            job_grade=(row.get("hr_job_grade") or row.get("job_grade")
                       or row.get("职等") or ""),
            hire_date=(row.get("hr_hire_date") or row.get("hire_date")
                       or row.get("入职日期") or None),
            nda_signed=(row.get("hr_nda_signed") if row.get("hr_nda_signed") is not None
                        else row.get("保密承诺")),
            background_cleared=(row.get("hr_background_cleared")
                                if row.get("hr_background_cleared") is not None
                                else row.get("背景审查")),
        ))
    return employees


# ===================== 查询辅助 =====================

def get_sync_history(limit: int = 20) -> List[dict]:
    """获取 HR 同步历史。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                """SELECT id, sync_type, source_type, total_count, created_count,
                          updated_count, deactivated_count, error_count,
                          started_at, finished_at, triggered_by, created_at
                   FROM kms_hr_sync_logs
                   ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            # MySQLStore 使用 DictCursor，fetchall() 已是 dict。
            # 原实现再 dict(zip(cols, row))：zip 会按 dict 的 key 迭代，
            # 产出 {"id": "id", "total_count": "total_count", ...} 的列名映射，
            # 管理端看到的统计全是列名而非数值（同款 bug 已在 kms/lifecycle.py 修过两处）。
            return list(cur.fetchall())
    except Exception as e:
        logger.error(f"获取同步历史失败: {e}")
        return []


def get_user_data_source(user_id: int) -> str:
    """查询用户数据来源。"""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute("SELECT data_source FROM kms_users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return row["data_source"] if row else "unknown"
    except Exception:
        return "unknown"


def is_hr_synced(user_id: int) -> bool:
    """判断用户是否来自 HR 同步。"""
    return get_user_data_source(user_id) == "hr_sync"
