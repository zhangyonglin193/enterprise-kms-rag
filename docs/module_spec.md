# KMS 企业级知识管理系统 — 模块详细说明

> ⚠️ 历史版本材料（2026-10-15 之前）。当前交付基线为 `gateway_architecture.md`、`gateway_api_reference.md`、`enterprise_delivery.md` 与 `../DEPLOY.md`；本文旧模块/旧路由叙述不代表现实现，且不进入发布白名单。

## 一、模块总览

```
kms/
├── __init__.py            # 包初始化，导出常量
├── constants.py           # 全局常量定义
├── security.py            # 认证鉴权（JWT + PBKDF2）
├── interfaces.py          # 用户身份接口抽象
├── access_control.py      # BLP 访问控制 + 审计 + CRUD
├── permission_rules.py    # 权限规则链（BLP + 部门）
├── admin_routes.py        # 管理路由（用户查询/HR同步/审计）
├── routes.py              # 文档管理 + RAG 问答
├── tickets.py             # 工单引擎核心
├── ticket_routes.py       # 工单路由
├── doc_lock.py            # 文档悲观锁
├── hr_sync.py             # HR 数据同步
├── versioning.py          # 文档版本管理
├── archive_store.py       # 归档向量库
├── gateway.py             # API 网关中间件
├── audit_query.py         # 审计日志查询（分级脱敏）
├── analytics.py           # 知识分析
├── knowledge_routes.py    # 知识中心路由
├── enterprise_routes.py   # 企业管理路由
└── web/                   # 前端静态资源
    ├── index.html
    └── app.js
```

---

## 二、各模块详细说明

### 2.1 `constants.py` — 全局常量

**职责**：集中定义系统常量，避免魔法值散落。

**核心常量**：

| 常量组 | 说明 |
|--------|------|
| `SECURITY_LEVELS` | 安全职级定义 `{0: "公开", 1: "内部", 2: "秘密", 3: "机密"}` |
| `ROLE_EMPLOYEE` | 唯一身份角色 `"employee"` |
| `EMPLOYEE_NO_PREFIX` | 工号前缀 `"2026"`，工号格式为 2026+四位数字 |
| `DEPARTMENTS` | 银联商务部门列表（8个部门） |
| `BUSINESS_TITLES` | 银联商务职位体系（13级：初级专员→总经理） |
| `DEPARTMENT_DEFAULT_LEVEL` | 部门默认安全职级映射 |
| `TITLE_DEFAULT_LEVEL` | 职位默认安全职级映射 |
| `TICKET_MODULE_*` | 工单模块：`doc_upload`, `doc_update`, `doc_delete` |
| `TICKET_STATUS_*` | 工单状态：`pending`, `approved`, `rejected`, `executed`, `timeout`, `cancelled`, `tampered` |
| `TICKET_TIMEOUT_BY_MODULE` | 差异化超时配置 `{doc_upload: 72h, doc_update: 48h, doc_delete: 24h}` |
| `TICKET_FLOW_TWO_STEP` | 两段式工单标识 |
| `PUBLIC_LEVEL` | 公开密级 `0` |

**已移除**：`DUTY_*`、`ESCALATION_*`、`BOOTSTRAP_ADMIN_THRESHOLD` 等旧常量。

---

### 2.2 `security.py` — 认证鉴权

**职责**：JWT Token 签发/校验、PBKDF2 密码散列、安全职级鉴权依赖。

**核心类/函数**：

| 接口 | 说明 |
|------|------|
| `AuthUser` | 认证用户对象：id, employee_no, username, department, business_title, security_level, is_active |
| `hash_password(password)` | PBKDF2-HMAC-SHA256 密码散列 |
| `verify_password(password, hash)` | 密码校验 |
| `create_token(user_id)` | JWT Token 签发（HS256） |
| `get_current_user(token)` | FastAPI 依赖：从 Token 解析当前用户 |
| `require_level(min_level)` | 基于安全职级的鉴权依赖工厂 |

**已移除**：`AuthUser.duties`、`is_escalated`、`require_security_admin`、`require_audit_reader` 等。

---

### 2.3 `interfaces.py` — 身份抽象

**职责**：定义 `UserIdentity` 接口，解耦业务层与认证层。

**核心属性**：

```python
class UserIdentity:
    id: int
    employee_no: str
    username: str
    department: str          # 所属部门
    business_title: str      # 业务称谓
    security_level: int      # 安全职级 L0-L3
    is_active: bool
```

**已移除**：`duties`、`is_escalated`、`is_admin`、`is_auditor`、`has_duty` 等。

---

### 2.4 `access_control.py` — 访问控制

**职责**：BLP 强制访问控制 + 部门归属判定 + 审计日志 + 用户/文档 CRUD。

**核心函数**：

| 函数 | 说明 |
|------|------|
| `can_read_doc(emp_level, doc_level, emp_dept, doc_dept, extra_depts)` | BLP 读判定：doc_level ≤ emp_level 且部门匹配 |
| `can_write_doc(emp_level, doc_level, emp_dept, doc_dept)` | BLP 写判定：doc_level ≥ emp_level 且同部门 |
| `find_candidate_approvers(doc_level, doc_dept)` | 筛选满足 BLP 规则的候选审批人 |
| `ensure_kms_acl_tables()` | 幂等建表（kms_users/kms_doc_levels/kms_audit_logs/kms_tickets/kms_notifications/kms_chat_owners） |
| `log_audit(user_id, action, target, detail, ip)` | 写入审计日志 |
| `get_user_by_employee_no(no)` | 按工号查询员工 |
| `list_users()` | 用户列表 |

**数据表**：kms_users, kms_doc_levels, kms_audit_logs, kms_tickets, kms_notifications, kms_chat_owners

---

### 2.5 `permission_rules.py` — 权限规则链

**职责**：实现可组合的权限规则链。

**规则链**：`[OwnershipRule(), BLPRule(), DepartmentRule()]`

| 规则 | 说明 |
|------|------|
| `OwnershipRule` | 文档创建者始终可读 |
| `BLPRule` | Bell-LaPadula 强制访问控制（不上读、不下写） |
| `DepartmentRule` | 部门匹配：emp_dept == doc_dept 或 emp_dept in doc_extra_depts |

**已移除**：`EscalationRule`（临时提权规则）。

---

### 2.6 `tickets.py` — 工单引擎

**职责**：两段式工单（申请 → 审批即执行）、自动流转、文档锁集成、超时驳回。

**角色说明**：系统中只有“员工”一类主体。申请人与审批人不是固定角色，而是工单流程中的临时职能：
- 申请人(A)：发起工单的任何在职员工
- 审批人(B)：系统根据 BLP 职级+部门自动筛选的候选员工
- 工单办结后角色即消失，不存在“管理员”或“审批员”等固定角色

**核心函数**：

| 函数 | 说明 |
|------|------|
| `auto_route_ticket(doc_level, doc_dept)` | 根据 BLP+部门自动筛选候选审批人 |
| `create_ticket_auto(applicant, module_key, payload, doc_id, ip)` | 自动创建工单（系统调用） |
| `approve_ticket(ticket_id, approver, comment, ip)` | 审批通过 → 哈希链核验 → 自动执行 → 释放锁 |
| `reject_ticket(ticket_id, approver, reason, ip)` | 审批驳回 → 释放锁 |
| `cancel_ticket(ticket_id, applicant, ip)` | 申请人撤回 → 释放锁 |
| `check_timeout_tickets()` | 扫描超时工单，自动驳回 |
| `payload_hash(payload)` | 申请内容防篡改哈希 |

**工单模块注册表**：

```python
MODULES = {
    "doc_upload":  {"timeout": 72h, "label": "文档上传"},
    "doc_update":  {"timeout": 48h, "label": "文档更新"},
    "doc_delete":  {"timeout": 24h, "label": "文档删除"},
}
```

**已移除**：`user_duty_grant`, `user_duty_revoke`, `escalation_grant`, `doc_batch_delete`, `doc_level_adjust`, `public_publish` 等旧模块。

---

### 2.7 `ticket_routes.py` — 工单路由

**职责**：工单相关 HTTP 接口。

**接口列表**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/tickets/upload` | 文件暂存并创建工单（multipart/form-data） |
| GET | `/tickets/mine` | 我的申请列表 |
| GET | `/tickets/pending-approval` | 待我审批列表 |
| GET | `/tickets/done` | 已完成列表 |
| POST | `/tickets/{id}/approve` | 审批通过 |
| POST | `/tickets/{id}/reject` | 审批驳回 |
| POST | `/tickets/{id}/cancel` | 撤回申请 |
| GET | `/tickets/timeout-check` | 超时工单检查（调试） |
| GET | `/tickets/doc-locks` | 文档锁状态（调试） |
| GET | `/notifications/mine` | 我的通知 |
| POST | `/notifications/{id}/read` | 标记已读 |

---

### 2.8 `doc_lock.py` — 文档悲观锁

**职责**：保证同一 doc_id 同一时刻只允许一条在途变更工单。

**核心函数**：

| 函数 | 说明 |
|------|------|
| `ensure_tables()` | 幂等建表 kms_doc_locks |
| `check_lock(doc_id)` | 检查文档是否有在途工单，返回 ticket_id 或 None |
| `acquire_lock(doc_id, ticket_id, user_id)` | 获取文档锁 |
| `release_lock(doc_id, ticket_id)` | 释放文档锁（校验 ticket_id 一致性） |
| `force_release_lock(doc_id)` | 强制释放（超时场景） |

**数据表**：`kms_doc_locks`（`UNIQUE KEY uk_doc_id (doc_id)`）

---

### 2.9 `hr_sync.py` — HR 数据同步

**职责**：人事主数据单向只读同步（upsert 策略）。

**核心函数**：

| 函数 | 说明 |
|------|------|
| `ensure_hr_sync_columns()` | 幂等建表 kms_hr_sync_logs |
| `sync_full(triggered_by)` | 全量同步 |
| `sync_incremental(triggered_by)` | 增量同步 |
| `upsert_employee(emp_data)` | 单条员工 upsert |
| `get_sync_history()` | 同步历史查询 |

**同步字段**：employee_no, username, department, business_title, security_level, is_active

**失败策略**：记录失败日志 → 使用旧缓存数据兜底 → 告警通知

---

### 2.10 `versioning.py` — 文档版本管理

**职责**：基于 doc_id 的版本控制 + 旧版本归档。

**核心函数**：

| 函数 | 说明 |
|------|------|
| `ensure_tables()` | 幂等建表 kms_doc_versions |
| `check_and_archive(document_id, new_hash)` | 上传前检查：相同哈希跳过，不同哈希归档旧版本 |
| `archive_current_version(document_id)` | 将当前版本归档到版本表 + 归档向量库 |
| `rollback_version(document_id, target_version)` | 回滚到指定版本 |
| `get_version_history(document_id)` | 版本历史查询 |

---

### 2.11 `archive_store.py` — 归档向量库

**职责**：旧版本 chunk 从主向量库移入归档库，检索阶段自动过滤。

**核心函数**：

| 函数 | 说明 |
|------|------|
| `ensure_tables()` | 幂等建表 kms_archive_chunks |
| `archive_chunks(doc_id, version, chunks)` | 将 chunk 移入归档库 |
| `is_archived(chunk_id)` | 检查 chunk 是否已归档 |
| `get_archive_stats(doc_id)` | 归档统计信息 |

**设计要点**：归档数据保留可查（审计/合规），但不参与 RAG 检索。

---

### 2.12 `gateway.py` — API 网关

**职责**：速率限制 + 全链路审计 + 请求 ID 注入。

**核心类/函数**：

| 接口 | 说明 |
|------|------|
| `RateLimiter` | 滑动窗口限流器（60次/分钟） |
| `APIGatewayMiddleware` | FastAPI 中间件：限流 + 审计 + 请求 ID |
| `setup_gateway(app)` | 注册网关中间件到 FastAPI 应用 |

**限流策略**：基于 AppKey 的滑动窗口，60 次/分钟，超限返回 429。

---

### 2.13 `audit_query.py` — 审计日志查询

**职责**：审计日志独立查询 + 分级脱敏。

**核心函数**：

| 函数 | 说明 |
|------|------|
| `query_audit_logs(filters, viewer_security_level)` | 分级脱敏查询审计日志 |
| `_desensitize_item(item, viewer_level)` | 单条记录脱敏处理 |

**分级脱敏规则**：

| 查看人职级 | 可见内容 |
|-----------|---------|
| L0 | 仅动作类型 + 时间 |
| L1 | 动作 + 对象 + 操作人 |
| L2 | 完整（详情截断 200 字） |
| L3 | 完整（详情截断 2000 字） |

---

### 2.14 `admin_routes.py` — 管理路由

**职责**：用户只读查询、HR 同步触发、审计日志查询。

**接口列表**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 员工登录 |
| GET | `/auth/me` | 当前用户信息 |
| GET | `/admin/users` | 用户列表（L2+） |
| POST | `/admin/hr-sync` | 手动触发 HR 同步（L2+） |
| GET | `/admin/hr-sync/history` | 同步历史（L2+） |
| GET | `/admin/audit/logs` | 审计日志查询（分级脱敏） |

**已移除**：职责配置、提权管理、提权审计等接口。

---

### 2.15 `routes.py` — 文档管理 + RAG 问答

**职责**：文档列表/详情/搜索、RAG 问答、批量上传。

**核心接口**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/documents` | 文档列表（BLP 过滤） |
| GET | `/documents/{id}` | 文档详情 |
| POST | `/chat` | RAG 问答（检索 + 生成） |
| GET | `/search` | 文档搜索 |

---

## 三、模块依赖关系

```
ticket_routes.py ──→ tickets.py ──→ access_control.py
                         │               │
                         ├──→ doc_lock.py ├──→ constants.py
                         │               │
                         └──→ constants.py├──→ security.py
                                          │
gateway.py ──→ audit_query.py             │
                                          │
admin_routes.py ──→ hr_sync.py ───────────┘
       │
       └──→ audit_query.py

routes.py ──→ versioning.py ──→ archive_store.py
       │
       └──→ permission_rules.py ──→ access_control.py
```
