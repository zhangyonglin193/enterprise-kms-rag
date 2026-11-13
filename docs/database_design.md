# KMS 企业级知识管理系统 — 数据表设计

> ⚠️ 历史版本材料（2026-10-15 之前）。当前交付基线为 `gateway_architecture.md`、`gateway_api_reference.md`、`enterprise_delivery.md` 与 `../DEPLOY.md`；本文旧表结构/字段叙述不代表现实现，且不进入发布白名单。

## 一、数据表总览

```
┌─────────────────────────────────────────────────────────────┐
│                     核心业务数据表                            │
├──────────────────┬──────────────────────────────────────────┤
│ kms_users        │ 员工表（HR 同步镜像，只读引用）            │
│ documents        │ 文档主表（当前版本元数据 + 分块索引）       │
│ chunks           │ 文档向量切片表（主向量库，参与 RAG 检索）   │
├──────────────────┼──────────────────────────────────────────┤
│                     工单与流程数据表                          │
├──────────────────┬──────────────────────────────────────────┤
│ kms_tickets      │ 工单表（两段式：申请 → 审批即执行）        │
│ kms_doc_locks    │ 文档悲观锁表（同一 doc_id 唯一在途工单）   │
│ kms_notifications│ 站内通知表（工单流转结果告知）              │
├──────────────────┼──────────────────────────────────────────┤
│                     版本与归档数据表                          │
├──────────────────┬──────────────────────────────────────────┤
│ kms_doc_versions │ 文档版本表（历史版本元数据）               │
│ kms_archive_chunks│ 归档向量切片表（旧版本，不参与 RAG 检索） │
├──────────────────┼──────────────────────────────────────────┤
│                     审计与运维数据表                          │
├──────────────────┼──────────────────────────────────────────┤
│ kms_audit_logs   │ 审计日志表（独立存储，不可篡改）           │
│ kms_hr_sync_logs │ HR 同步日志表                             │
│ kms_doc_levels   │ 文档密级归属表                             │
│ kms_chat_owners  │ 问答会话归属表                             │
└──────────────────┴──────────────────────────────────────────┘
```

---

## 二、表结构详细说明

### 2.1 员工表 — `kms_users`（HR 同步镜像）

> **设计原则**：KMS 不维护人事主数据，仅做只读引用。所有人员信息由 HR 系统单向同步。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `employee_no` | VARCHAR(64) UK | 工号（HR 系统权威来源） |
| `username` | VARCHAR(128) | 姓名（HR 系统） |
| `password_hash` | VARCHAR(255) | PBKDF2-HMAC-SHA256 散列 |
| `role` | VARCHAR(32) | 固定 `employee`（系统中只有员工一类主体） |
| `security_level` | INT | 安全职级 L0-L3（HR 同步，KMS 不可修改） |
| `department` | VARCHAR(128) | 所属部门（HR 同步） |
| `business_title` | VARCHAR(128) | 业务称谓（HR 同步，仅展示） |
| `is_active` | TINYINT(1) | 在职状态（HR 同步） |
| `data_source` | VARCHAR(32) | 数据来源：`hr_sync` / `local` |
| `hr_synced_at` | DATETIME | 最近 HR 同步时间 |
| `last_login_at` | DATETIME | 最近登录时间 |

**索引**：`UNIQUE KEY uk_employee_no (employee_no)`

**工号规则**：`2026` + 四位数字序号（从 0000 开始），如 `20260000`, `20260001`。初始密码与工号相同，便于展示登录。

**银联商务部门架构**（参照企业实际组织层级）：
| 部门 | 默认密级 | 说明 |
|------|----------|------|
| 产品管理部 | L1 | 产品规划与文档管理 |
| 技术研发部 | L2 | 核心技术研发 |
| 市场拓展部 | L1 | 市场推广与商务 |
| 运营支撑部 | L1 | 运营与客服支撑 |
| 风险控制部 | L3 | 风控合规（最高密级） |
| 财务管理部 | L2 | 财务与结算 |
| 人力资源部 | L2 | 人事与培训 |
| 综合管理部 | L1 | 行政与综合事务 |

**业务称谓（职位）体系**（参照银联商务企业实践）：
初级专员(L0) → 专员(L0) → 高级专员(L1) → 资深专员(L1) → 副主管(L1) → 主管(L2) → 高级主管(L2) → 副经理(L2) → 经理(L2) → 高级经理(L3) → 总经理助理(L3) → 副总经理(L3) → 总经理(L3)

**安全职级定义**：
| 级别 | 名称 | 说明 |
|------|------|------|
| L0 | 公开 | 所有员工可见 |
| L1 | 内部 | L1 及以上可读 |
| L2 | 秘密 | L2 及以上可读 |
| L3 | 机密 | L3 及以上可读 |

---

### 2.2 文档主表 — `documents`（已有表 + 新增字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `doc_id` | VARCHAR(64) | 文档业务唯一标识 |
| `filename` | VARCHAR(255) | 文件名 |
| `version` | INT | 当前版本号 |
| `doc_level` | INT | 文档密级 L0-L3 |
| `owner_department` | VARCHAR(128) | 归属部门 |
| `extra_departments` | TEXT | 额外开放部门列表（JSON 数组） |
| `content_hash` | VARCHAR(64) | 内容 SHA-256 哈希 |
| `is_archived` | TINYINT(1) | 是否已归档 |
| `source_path` | VARCHAR(512) | 源文件路径 |
| `chunk_count` | INT | 分块数量 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

---

### 2.3 向量切片表 — `chunks`（主向量库）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `document_id` | BIGINT | 关联 documents.id |
| `chunk_index` | INT | 切片序号 |
| `content` | TEXT | 切片文本 |
| `content_hash` | VARCHAR(64) | 内容哈希 |
| `metadata_json` | TEXT | 元数据 JSON |

> **注意**：检索阶段仅从 `chunks` 表召回，已归档切片存储在 `kms_archive_chunks` 中，自动排除。

---

### 2.4 工单表 — `kms_tickets`（两段式）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `ticket_no` | VARCHAR(40) UK | 工单编号 |
| `module` | VARCHAR(32) | 工单模块：`doc_upload` / `doc_update` / `doc_delete` |
| `category` | VARCHAR(16) | 固定 `doc`（文档变更） |
| `flow` | VARCHAR(16) | 固定 `two_step`（审批即执行） |
| `applicant_id` | BIGINT | 申请人 A（员工 ID） |
| `applicant_no` | VARCHAR(64) | 申请人工号 |
| `applicant_name` | VARCHAR(128) | 申请人姓名 |
| `payload` | TEXT | 申请内容 JSON |
| `payload_summary` | VARCHAR(512) | 申请事项摘要 |
| `original_hash` | CHAR(64) | 提交时 SHA-256（防篡改） |
| `approver_id` | BIGINT | 审批人 B（系统自动匹配） |
| `approver_no` | VARCHAR(64) | 审批人工号 |
| `approver_name` | VARCHAR(128) | 审批人姓名 |
| `approved_hash` | CHAR(64) | 审批通过时 SHA-256 |
| `approve_comment` | VARCHAR(512) | 审批意见 |
| `approved_at` | DATETIME | 审批时间 |
| `exec_result` | VARCHAR(1024) | 执行结果 |
| `executed_at` | DATETIME | 执行时间 |
| `status` | VARCHAR(16) | 状态：pending/approved/rejected/executed/timeout/cancelled/tampered |
| `reason` | VARCHAR(512) | 驳回/失败原因 |
| `timeout_at` | DATETIME | 超时时间 |
| `doc_id` | VARCHAR(64) | 关联文档业务 ID（用于文档锁） |

**工单超时配置**：
| 模块 | 超时时间 |
|------|----------|
| doc_upload | 72 小时 |
| doc_update | 48 小时 |
| doc_delete | 24 小时 |

**索引**：`uk_ticket_no`, `idx_t_status`, `idx_t_applicant`, `idx_t_approver`, `idx_t_module`, `idx_t_doc_id`

---

### 2.5 文档悲观锁表 — `kms_doc_locks`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `doc_id` | VARCHAR(64) UK | 文档业务 ID（唯一索引，保证同一时刻只有一条在途工单） |
| `ticket_id` | BIGINT | 持有锁的工单 ID |
| `lock_type` | VARCHAR(32) | 锁类型：`change` |
| `locked_at` | DATETIME | 加锁时间 |
| `locked_by` | BIGINT | 加锁人员工 ID |

**核心约束**：`UNIQUE KEY uk_doc_id (doc_id)` — 同一文档同一时刻只能有一个在途变更工单。

---

### 2.6 文档版本表 — `kms_doc_versions`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `document_id` | BIGINT | 关联 documents.id |
| `version_no` | INT | 版本号（从 1 自增） |
| `filename` | VARCHAR(255) | 文件名 |
| `content_hash` | VARCHAR(64) | SHA-256 内容哈希 |
| `chunk_count` | INT | 分块数量 |
| `source_path` | VARCHAR(512) | 源文件路径 |
| `uploaded_by` | BIGINT | 上传人员工 ID |
| `uploader_no` | VARCHAR(64) | 上传人工号 |
| `summary` | VARCHAR(512) | 版本变更说明 |
| `is_current` | TINYINT(1) | 是否当前版本 |

**唯一约束**：`UNIQUE KEY uk_doc_version (document_id, version_no)`

---

### 2.7 归档向量切片表 — `kms_archive_chunks`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `doc_id` | VARCHAR(64) | 文档业务 ID |
| `version` | INT | 归档版本号 |
| `chunk_index` | INT | 切片序号 |
| `content` | TEXT | 切片文本 |
| `content_hash` | VARCHAR(64) | 内容哈希 |
| `metadata_json` | TEXT | 元数据 JSON |
| `archived_at` | DATETIME | 归档时间 |
| `archived_by` | BIGINT | 归档操作人 |
| `original_chunk_id` | BIGINT | 原 chunks.id |

> **设计要点**：归档数据保留可查（审计/合规），但 **不参与 RAG 检索**，防止召回冲突内容。

---

### 2.8 审计日志表 — `kms_audit_logs`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `user_id` | BIGINT | 操作人 ID |
| `employee_no` | VARCHAR(64) | 操作人工号 |
| `action` | VARCHAR(64) | 操作类型 |
| `target` | VARCHAR(512) | 操作对象 |
| `detail` | TEXT | 操作详情 |
| `ip` | VARCHAR(64) | 操作 IP |
| `created_at` | DATETIME | 操作时间 |

**分级脱敏规则**：
| 查看人职级 | 可见内容 |
|-----------|---------|
| L0 | 仅动作类型 + 时间 |
| L1 | 动作 + 对象 + 操作人 |
| L2 | 动作 + 对象 + 操作人 + IP + 截断详情（≤200字） |
| L3 | 完整信息（详情≤2000字） |

---

### 2.9 HR 同步日志表 — `kms_hr_sync_logs`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `sync_type` | VARCHAR(32) | 同步类型：full/incremental/manual |
| `source_type` | VARCHAR(32) | 数据源：hr_api/hr_db/csv_file |
| `total_count` | INT | 本次同步总数 |
| `created_count` | INT | 新增数 |
| `updated_count` | INT | 更新数 |
| `deactivated_count` | INT | 停用数 |
| `error_count` | INT | 失败数 |
| `error_detail` | TEXT | 失败详情 JSON |
| `started_at` | DATETIME | 同步开始时间 |
| `finished_at` | DATETIME | 同步结束时间 |
| `triggered_by` | BIGINT | 触发人 |

---

### 2.10 辅助表

**文档密级表 — `kms_doc_levels`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `document_id` | BIGINT PK | 关联 documents.id |
| `level` | INT | 密级 L0-L3 |
| `granted_by` | BIGINT | 设置人 |

**站内通知表 — `kms_notifications`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | 自增主键 |
| `user_id` | BIGINT | 接收人 |
| `ticket_id` | BIGINT | 关联工单 |
| `ntype` | VARCHAR(32) | 通知类型 |
| `title` | VARCHAR(255) | 标题 |
| `content` | VARCHAR(1024) | 内容 |
| `is_read` | TINYINT(1) | 已读标记 |

**会话归属表 — `kms_chat_owners`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | VARCHAR(64) PK | 会话 ID |
| `user_id` | BIGINT | 归属员工 |

---

## 三、表关系 ER 图

```
kms_users (1) ──── (N) kms_tickets (applicant_id)
kms_users (1) ──── (N) kms_tickets (approver_id)
kms_users (1) ──── (N) kms_audit_logs
kms_users (1) ──── (N) kms_notifications
kms_users (1) ──── (N) kms_doc_versions (uploaded_by)

documents (1) ──── (N) chunks (document_id)
documents (1) ──── (N) kms_doc_versions (document_id)
documents (1) ──── (1) kms_doc_levels (document_id)

kms_tickets (N) ──── (1) kms_doc_locks (doc_id → ticket_id)

doc_id ──────────── 文档业务标识，贯穿 documents / chunks / doc_locks / archive_chunks
```
