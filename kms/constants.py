"""KMS 公共常量定义。

集中管理全系统常量，避免模块间重复定义和硬编码，提升可维护性。

常量分类
--------
- 身份与职级: ROLE_*, SECURITY_LEVELS
- 工单状态/流程/类别: TICKET_*
- 密级层级: PUBLIC_LEVEL, SECURITY_LEVEL_*
- 权限判定结果: PERM_*
- 审计动作: AUDIT_*
- 工单超时: TICKET_TIMEOUT_*

工单模型（重要）
--------------
**每个在职员工都可以发起工单，系统中不存在「管理员」角色。**

审批人不是管理员，也不再是「持有审批职责」的员工，而是**按人员的组织属性匹配**
（部门 + 安全职级）并由系统随机指派的人：

    合格 = 在职 且 归属部门 == 文档归属部门 且 安全职级 >= 文档密级 且 非申请人本人

这条判据与「能不能读到这篇文档」完全一致——审批前必须看得见内容。
不再维护一份独立的审批人名单：那份名单和 BLP 会互相漂移
（名单说张三能审，而 BLP 说张三看不见这篇文档）。

流程为 two_step：申请 → 审批（审批通过由系统自动执行），
因此日常只有「申请人 A」与「审批人 B」两类角色参与，执行由系统完成。
审批人在**建单/提交申请时**由系统随机指派并落库，审批人不可由申请人挑选，
避免选择可被预测或被操纵；审批那一刻再按同一判据复核一次，防止中间人员变动。
"""
from __future__ import annotations

import re

# ===================== 身份（统一实体：仅员工） =====================
ROLE_EMPLOYEE = "employee"                    # 唯一基础身份

ROLE_LABELS = {
    ROLE_EMPLOYEE: "员工",
}

# ===================== HR 岗位类别（单向同步自 HR 系统） =====================
# 人事主数据原则：KMS 不维护人事主数据，只做引用（见 kms/hr_sync.py 架构原则）。
# 岗位类别由 HR 单向同步写入 kms_users.hr_position_type，KMS 只读。
#
# **这条边界必须守住**：岗位类别只决定治理身份（能否查看系统配置、运行参数、
# 治理审计），**不提高可读密级**——内容可见范围仍完全由「安全职级 + 部门」的
# BLP 判定决定。否则治理身份会悄悄变成一把绕过 BLP 的通用钥匙。
HR_POSITION_STAFF = "staff"      # 普通员工（默认值）
HR_POSITION_AUDITOR = "auditor"  # 审计员：可查看系统配置/运行参数与治理审计

HR_POSITION_LABELS = {
    HR_POSITION_STAFF: "员工",
    HR_POSITION_AUDITOR: "审计员",
}

# 白名单：HR 同步给到未登记的值时一律降级为 staff。
# 宁可漏判为普通员工（少给权限），也不要让一个未知值崩掉整批同步。
HR_POSITIONS = frozenset({HR_POSITION_STAFF, HR_POSITION_AUDITOR})

# ===================== 密级名称（文档分级，L0 最低 L3 最高） =====================
# 密级语义由 HR 定义，KMS 只做只读引用。本字典是**文档密级**的名称映射，
# 文档的分类等级用「公开/秘密/机密/绝密」表述。
#
#   L0 公开 —— **公司内部**公开：全体在职员工可见。
#              这里必须强调"内部"二字：KMS 所有内容都要求认证，不存在匿名入口，
#              "公开"绝不等于对公众/互联网公开。误读这个级别会导致把受限资料
#              登记成 L0 从而对全公司敞开，是本项目最需要警惕的赋值错误。
#   L1 秘密 / L2 机密 / L3 绝密 —— 逐级收紧，另受部门与组织归属约束。
#
# 注意：**员工的安全职级**不沿用这些名称，统一显示为 L0/L1/L2/L3（数字编号），
# 以免与文档密级称谓混淆——「公开/秘密/机密/绝密」只用来描述文档，不描述人。
#
# 本段是全系统密级名称的**唯一定义处**。其余模块必须引用本字典，
# 不得另抄一份字面量——多份定义必然在改名时漂移（历史上一度存在 4 份）。
# ===================== 文档归属部门：「不限」的表示 =====================
# 空串 ('') 保留其原有含义 = **未登记部门**（谁都看不见，fail-closed）；
# 「不限部门」另用一个哨兵值显式表示，二者必须可区分。
#
# 若把空串直接当成「不限」，那么任何一处代码漏设 owner_department 都会让
# 该文档**静默对全员敞开**——这正是本项目反复警惕的失效模式。
# 用独立哨兵后，漏设仍然不可见，只有显式选择才会跨部门开放。
DOC_DEPT_UNLIMITED = "*"

# ===================== HR 在职状态 / 用工性质 / 岗位序列 =====================
# 与 hr_position_type 同一原则：人事主数据由 HR 单向同步、KMS 只读引用。
# 这里补齐的是**企业 HR 主数据的常规维度**——它们共同回答一个问题：
# 「这个人是否具备接触涉密信息的资格」。KMS 不自行裁定，只按 HR 结论执行。
#
# 取值一律白名单。HR 给到未登记的值时降级为最保守的一档（见 hr_sync）：
# 宁可少给资格，也不能让一个未知值静默变成"有资格"。
HR_STATUS_REGULAR = "regular"            # 在职
HR_STATUS_TRIAL = "trial"                # 试用
HR_STATUS_PENDING_LEAVE = "pending_leave"  # 待离职
HR_STATUS_LEAVE = "leave"                # 停薪留职 / 长病休
HR_STATUS_UNKNOWN = "unknown"        # 未登记 / 无法识别
HR_STATUSES = frozenset({
    HR_STATUS_REGULAR, HR_STATUS_TRIAL, HR_STATUS_PENDING_LEAVE, HR_STATUS_LEAVE,
    HR_STATUS_UNKNOWN,
})
HR_STATUS_LABELS = {
    HR_STATUS_REGULAR: "在职",
    HR_STATUS_TRIAL: "试用",
    HR_STATUS_PENDING_LEAVE: "待离职",
    HR_STATUS_LEAVE: "停薪留职",
    HR_STATUS_UNKNOWN: "未登记",
}

HR_EMPLOYMENT_STAFF = "staff"        # 正式（劳动合同主体内）
HR_EMPLOYMENT_DISPATCH = "dispatch"  # 劳务派遣
HR_EMPLOYMENT_INTERN = "intern"      # 实习
HR_EMPLOYMENT_OUTSOURCE = "outsource"  # 外包（驻场）
HR_EMPLOYMENT_UNKNOWN = "unknown"    # 未登记 / 无法识别
HR_EMPLOYMENTS = frozenset({
    HR_EMPLOYMENT_STAFF, HR_EMPLOYMENT_DISPATCH,
    HR_EMPLOYMENT_INTERN, HR_EMPLOYMENT_OUTSOURCE, HR_EMPLOYMENT_UNKNOWN,
})
HR_EMPLOYMENT_LABELS = {
    HR_EMPLOYMENT_STAFF: "正式",
    HR_EMPLOYMENT_DISPATCH: "劳务派遣",
    HR_EMPLOYMENT_INTERN: "实习",
    HR_EMPLOYMENT_OUTSOURCE: "外包",
    HR_EMPLOYMENT_UNKNOWN: "未登记",
}

# 岗位序列：与"安全职级"是两件事——职级是保密能力，岗位序列是职业通道。
# 混为一谈会让"提拔"被误读成"提密"。
HR_JOB_FAMILY_MGMT = "management"      # 管理序列
HR_JOB_FAMILY_PROF = "professional"    # 专业序列
HR_JOB_FAMILY_OPS = "operations"       # 操作序列
HR_JOB_FAMILY_SALES = "sales"          # 营销序列
HR_JOB_FAMILIES = frozenset({
    HR_JOB_FAMILY_MGMT, HR_JOB_FAMILY_PROF, HR_JOB_FAMILY_OPS, HR_JOB_FAMILY_SALES,
})
HR_JOB_FAMILY_LABELS = {
    HR_JOB_FAMILY_MGMT: "管理序列",
    HR_JOB_FAMILY_PROF: "专业序列",
    HR_JOB_FAMILY_OPS: "操作序列",
    HR_JOB_FAMILY_SALES: "营销序列",
}

SECURITY_LEVEL_PUBLIC = 0        # L0 公开（公司内部公开）
SECURITY_LEVEL_SECRET = 1        # L1 秘密
SECURITY_LEVEL_CONFIDENTIAL = 2  # L2 机密
SECURITY_LEVEL_TOPSECRET = 3     # L3 绝密

SECURITY_LEVELS = {
    SECURITY_LEVEL_PUBLIC: "公开",
    SECURITY_LEVEL_SECRET: "秘密",
    SECURITY_LEVEL_CONFIDENTIAL: "机密",
    SECURITY_LEVEL_TOPSECRET: "绝密",
}

PUBLIC_LEVEL = 0        # 公开层固定为 0
MIN_EMPLOYEE_LEVEL = 0  # 员工最低层级（L0 公开）
MAX_EMPLOYEE_LEVEL = 3  # 员工最高层级（L3 绝密）

# ===================== 工单状态 =====================
TICKET_STATUS_PENDING = "pending"              # 待审批
TICKET_STATUS_APPROVED = "approved"            # 审批通过（待执行/已执行）
TICKET_STATUS_REJECTED = "rejected"            # 已驳回
TICKET_STATUS_EXECUTED = "executed"            # 已执行
TICKET_STATUS_TIMEOUT = "timeout"              # 超时自动驳回
TICKET_STATUS_CANCELLED = "cancelled"          # 已撤回
TICKET_STATUS_TAMPERED = "tampered"            # 篡改拦截

TICKET_STATUS_LABELS = {
    TICKET_STATUS_PENDING: "待审批",
    TICKET_STATUS_APPROVED: "审批通过",
    TICKET_STATUS_REJECTED: "已驳回",
    TICKET_STATUS_EXECUTED: "已执行",
    TICKET_STATUS_TIMEOUT: "超时驳回",
    TICKET_STATUS_CANCELLED: "已撤回",
    TICKET_STATUS_TAMPERED: "篡改拦截",
}

# ===================== 工单流程 =====================
TICKET_FLOW_TWO_STEP = "two_step"  # 申请 → 审批（通过即系统自动执行）

# ===================== 工单类别 =====================
TICKET_CATEGORY_DOC = "doc"  # 文档变更工单（上传/更新/删除）

# ===================== 工单模块 =====================
# 键名必须与调用方完全一致，改动前先同步：
#   · gateway/routes_tickets.py 的 TICKET_MODULES 注册表（可否发起）
#   · kms/web/app.js 文档库的多选删除（按此 key 提交工单）
#
# 历史上前端还有一张「发起工单」表单会按 key 渲染卡片并决定是否显示
# 「文件批量发起」按钮，该入口已随交互调整移除——批量删除改为在文档库勾选
# 文档直接发起，不必再让用户手工拼一份 document_id 表格。
#
# 对外可发起的模块以 gateway/routes_tickets.py 的 TICKET_MODULES 为准（目前仅
# doc_batch_delete）。员工职责授予（user_duty_grant）已移除：审批权不再由职责
# 表达，改由「所属部门 + 安全职级」派生，见 access_control.pick_approver。
TICKET_MODULE_DOC_UPLOAD = "doc_upload"
TICKET_MODULE_DOC_UPDATE = "doc_update"
TICKET_MODULE_DOC_DELETE = "doc_delete"
TICKET_MODULE_DOC_BATCH_DELETE = "doc_batch_delete"  # 批量删除文档（前端 fileImportModules）
TICKET_MODULE_DOC_RESTORE = "doc_restore"  # 恢复回收站文档（归档态 → 删除前状态）

TICKET_MODULE_LABELS = {
    TICKET_MODULE_DOC_UPLOAD: "文档上传",
    TICKET_MODULE_DOC_UPDATE: "文档更新",
    TICKET_MODULE_DOC_DELETE: "文档删除",
    TICKET_MODULE_DOC_BATCH_DELETE: "批量删除文档",
    TICKET_MODULE_DOC_RESTORE: "恢复回收站文档",
}

# ===================== 工单职责 =====================
# 无管理员。但审批权**不再来自职责**，而是由组织属性派生：候选审批人须满足
# 「归属部门 == 文档归属部门」且「安全职级 >= 文档密级」（即能读到这篇文档），
# 由系统在合格候选人中随机指派，见 access_control.pick_approver / can_approve_document。
#
# 下方职责键仅作兼容与审计留痕：当前没有任何端点以「持有某职责」为放行条件，
# 也不再存在授予职责的入口（原 user_duty_grant 工单模块已移除）。
DUTY_TICKET_APPLY = "ticket_apply"      # 申请职责（在职员工默认具备）
DUTY_TICKET_APPROVE = "ticket_approve"  # 审批职责（已不作为放行判据）
DUTY_TICKET_EXECUTE = "ticket_execute"  # 执行职责（two_step 下由系统自动执行）

DUTY_LABELS = {
    DUTY_TICKET_APPLY: "工单申请",
    DUTY_TICKET_APPROVE: "工单审批",
    DUTY_TICKET_EXECUTE: "工单执行",
}

# ===================== 工单超时（分钟） =====================
TICKET_TIMEOUT_DOC_UPLOAD = 72 * 60    # 文档上传 72 小时
TICKET_TIMEOUT_DOC_UPDATE = 48 * 60    # 文档更新 48 小时
TICKET_TIMEOUT_DOC_DELETE = 24 * 60    # 文档删除 24 小时

TICKET_TIMEOUT_DEFAULT = 48 * 60       # 默认 48 小时

TICKET_TIMEOUT_BY_MODULE = {
    TICKET_MODULE_DOC_UPLOAD: TICKET_TIMEOUT_DOC_UPLOAD,
    TICKET_MODULE_DOC_UPDATE: TICKET_TIMEOUT_DOC_UPDATE,
    TICKET_MODULE_DOC_DELETE: TICKET_TIMEOUT_DOC_DELETE,
    TICKET_MODULE_DOC_BATCH_DELETE: TICKET_TIMEOUT_DOC_DELETE,
    TICKET_MODULE_DOC_RESTORE: TICKET_TIMEOUT_DOC_UPDATE,  # 恢复 48 小时
}

# ===================== 权限判定结果 =====================
PERM_ALLOW = "allow"
PERM_DENY = "deny"
PERM_REQUIRE_TICKET = "require_ticket"  # 需要走工单

# ===================== 审计动作 =====================
# 认证
AUDIT_LOGIN = "login"
AUDIT_LOGOUT = "logout"
AUDIT_CHANGE_PASSWORD = "change_password"
AUDIT_LOGIN_FAILED = "login_failed"

# HR 同步
AUDIT_HR_SYNC = "hr_sync"
AUDIT_HR_SYNC_FAILED = "hr_sync_failed"

# 文档操作（通过工单）
AUDIT_DOC_UPLOAD = "doc_upload"
AUDIT_DOC_UPDATE = "doc_update"
AUDIT_DOC_DELETE = "doc_delete"
AUDIT_DOC_VIEW = "doc_view"
AUDIT_DOC_DOWNLOAD = "doc_download"  # 原文下载：与 doc_view 区分，外带比浏览更强
AUDIT_DOC_SEARCH = "doc_search"

# 工单流转
AUDIT_TICKET_CREATE = "ticket_create"
AUDIT_TICKET_APPROVE = "ticket_approve"
AUDIT_TICKET_REJECT = "ticket_reject"
AUDIT_TICKET_EXECUTE = "ticket_execute"
AUDIT_TICKET_CANCEL = "ticket_cancel"
AUDIT_TICKET_TIMEOUT = "ticket_timeout"

# API 调用
AUDIT_API_CALL = "api_call"

# ===================== 标签映射 =====================
SECURITY_LEVEL_LABELS = SECURITY_LEVELS  # 别名

# ===================== 工号规则 =====================
# 工号格式: 2026 + 四位数字序号（从 0000 开始），如 20260000, 20260001
EMPLOYEE_NO_PREFIX = "2026"
EMPLOYEE_NO_DIGITS = 4
EMPLOYEE_NO_START = 0  # 起始序号

# ===================== 银联商务部门架构 =====================
# 参照银联商务（China UnionPay Merchant Services）企业组织架构
DEPARTMENTS = [
    "产品管理部",
    "技术研发部",
    "市场拓展部",
    "运营支撑部",
    "风险控制部",
    "财务管理部",
    "人力资源部",
    "综合管理部",
]

# 部门名规范化：HR 台账（Excel/PDF 复制）常把「综合管理部」写成「综合 管理部」
# 或「综合\t管理部」——空白字符混进部门名后，与 documents.departments 的
# JSON 数组做 JSON_CONTAINS 比较永远不相等，表现为「审批人候选为空」
# 「本部门文档看不见」这类无报错的静默失效。此处统一收敛到白名单标准名。
_DEPT_WHITESPACE_RE = re.compile(r"[\s\u3000]+")
_DEPT_LOOKUP = {_DEPT_WHITESPACE_RE.sub("", d): d for d in DEPARTMENTS}


def normalize_department(raw: str) -> str:
    """把任意来源的部门名收敛到 DEPARTMENTS 白名单中的标准写法。

    - 去掉全部空白字符（含全角空格 U+3000、制表符、换行）后再匹配；
    - 命中白名单 → 返回标准名；未命中 → 返回去空白后的原值（保留未知部门，
      交由上层白名单校验拒绝，不静默丢弃信息）；
    - 空值 → 返回空字符串（调用方据此跳过或按 fail-closed 处理）。
    """
    if not raw:
        return ""
    cleaned = _DEPT_WHITESPACE_RE.sub("", str(raw))
    return _DEPT_LOOKUP.get(cleaned, cleaned)

# 部门默认安全职级（部门最高密级，实际员工职级由 HR 系统定义）
DEPARTMENT_DEFAULT_LEVEL = {
    "产品管理部": 1,
    "技术研发部": 2,
    "市场拓展部": 1,
    "运营支撑部": 1,
    "风险控制部": 3,
    "财务管理部": 2,
    "人力资源部": 2,
    "综合管理部": 1,
}

# ===================== 业务称谓（职位） =====================
# 参照银联商务企业实践职级体系
BUSINESS_TITLES = [
    "初级专员",
    "专员",
    "高级专员",
    "资深专员",
    "副主管",
    "主管",
    "高级主管",
    "副经理",
    "经理",
    "高级经理",
    "总经理助理",
    "副总经理",
    "总经理",
]

# 业务称谓与安全职级的默认映射（HR 同步时可覆盖）
TITLE_DEFAULT_LEVEL = {
    "初级专员": 0,
    "专员": 0,
    "高级专员": 1,
    "资深专员": 1,
    "副主管": 1,
    "主管": 2,
    "高级主管": 2,
    "副经理": 2,
    "经理": 2,
    "高级经理": 3,
    "总经理助理": 3,
    "副总经理": 3,
    "总经理": 3,
}

# ===================== 数值常量 =====================
# 注：PBKDF2_ITERATIONS / TOKEN_TTL_HOURS / TOKEN_ALGORITHM 原先在本处各有一份
# （100_000 / 12h / "HS256"），但与 kms/security.py 的实际取值（600_000 / 1h / "HS256"）
# **不一致且零引用** —— 谁改这里都不会生效，是典型的「改一处不生效」陷阱。
# 密码学参数以 kms/security.py 为唯一来源，此处不再重复定义。

# ===================== 文档生命周期状态 =====================
DOC_STATE_DRAFT = "draft"
DOC_STATE_PUBLISHED = "published"
DOC_STATE_ARCHIVED = "archived"
DOC_STATE_EXPIRED = "expired"

DOC_STATE_LABELS = {
    DOC_STATE_DRAFT: "草稿",
    DOC_STATE_PUBLISHED: "已发布",
    DOC_STATE_ARCHIVED: "已归档",
    DOC_STATE_EXPIRED: "已过期",
}

# ===================== 知识分析 =====================
KNOWLEDGE_HEALTH_LEVELS = {
    (90, 100): ("优秀", "#10b981"),
    (70, 89): ("良好", "#3b82f6"),
    (50, 69): ("一般", "#f59e0b"),
    (0, 49): ("较差", "#ef4444"),
}

RATING_MIN = 1
RATING_MAX = 5
