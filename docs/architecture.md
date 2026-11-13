# KMS 企业级知识管理系统 — 系统分层架构

> ⚠️ 历史版本材料（2026-10-15 之前）。当前交付基线为 `gateway_architecture.md`、`gateway_api_reference.md`、`enterprise_delivery.md` 与 `../DEPLOY.md`；本文的旧分层/旧路由叙述不代表现实现，且不进入发布白名单。

> 甲方：银联商务（China UnionPay Merchant Services）
> 参照 IBM 知识管理系统最佳实践搭建

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        接入层 (API Gateway)                         │
│  API 网关中间件 · AppKey+员工双层鉴权 · 速率限制 · 请求审计日志       │
├─────────────────────────────────────────────────────────────────────┤
│                        路由层 (FastAPI Routes)                       │
│  admin_routes · ticket_routes · knowledge_routes · enterprise_routes│
├─────────────────────────────────────────────────────────────────────┤
│                        业务层 (Business Logic)                       │
│  工单引擎 · 权限规则链 · 文档管理 · HR 同步 · 版本管理 · 知识分析    │
├─────────────────────────────────────────────────────────────────────┤
│                        领域层 (Domain Layer)                         │
│  BLP 强制访问控制 · 文档悲观锁 · 归档向量库 · 生命周期状态机          │
├─────────────────────────────────────────────────────────────────────┤
│                        基础设施层 (Infrastructure)                    │
│  MySQL · FAISS 向量库 · Embedding/LLM/Reranker · 文件系统           │
└─────────────────────────────────────────────────────────────────────┘
```

## 二、各层详细说明

### 2.1 接入层 — API 网关

| 组件 | 文件 | 职责 |
|------|------|------|
| API 网关中间件 | `kms/gateway.py` | 速率限制（60次/分钟）、API 调用审计日志、请求 ID 注入 |
| CORS 中间件 | `run_kms.py` | 跨域资源共享 |
| 认证鉴权 | `kms/security.py` | JWT Token 签发/校验、PBKDF2 密码散列、安全职级鉴权 |

**设计原则**：
- 外部应用不能直接写入底层存储
- 文档变更仅能调用接口发起工单
- 无法绕过 BLP 权限、审计、工单内控
- 全部 API 调用行为写入独立审计日志库

### 2.2 路由层 — FastAPI 路由

| 路由文件 | 前缀 | 职责 |
|----------|------|------|
| `admin_routes.py` | `/kms/api/admin/*`, `/kms/api/auth/*` | 认证登录、用户只读查询、HR 同步、审计日志 |
| `ticket_routes.py` | `/kms/api/tickets/*`, `/kms/api/notifications/*` | 工单发起/审批/驳回/撤回、站内通知 |
| `knowledge_routes.py` | `/kms/api/knowledge/*` | 分类/标签/互动/分析/个人知识中心 |
| `enterprise_routes.py` | `/kms/api/enterprise/*` | 文档生命周期/分类标签/审计导出 |
| `routes.py` | `/kms/api/*` | 文档管理、RAG 问答、批量上传 |

### 2.3 业务层 — 核心业务逻辑

| 模块 | 文件 | 职责 |
|------|------|------|
| 工单引擎 | `kms/tickets.py` | 两段式工单（申请→审批即执行）、自动流转、超时驳回 |
| 权限规则链 | `kms/permission_rules.py` | BLP 规则 + 部门规则 AND 组合 |
| 访问控制 | `kms/access_control.py` | BLP 判定函数、用户/文档密级 CRUD、审计日志、通知 |
| HR 同步 | `kms/hr_sync.py` | 人事主数据单向只读同步（upsert 策略） |
| 文档锁 | `kms/doc_lock.py` | 文档悲观锁（同一 doc_id 同一时刻只允许一条在途工单） |
| 版本管理 | `kms/versioning.py` | 文档版本控制、旧版本归档 |
| 归档存储 | `kms/archive_store.py` | 旧版本 chunk 隔离到归档向量库，防止 RAG 召回冲突 |
| 知识分析 | `kms/analytics.py` | 知识资产概览、使用趋势、健康度评估、贡献排行 |

### 2.4 领域层 — 核心领域模型

#### BLP（Bell-LaPadula）强制访问控制

```
读规则（不上读）：doc_level ≤ emp_security_level
写规则（不下写）：doc_level ≥ emp_security_level
部门规则：emp_dept == doc_dept 或 emp_dept in doc_extra_depts
```

#### 文档悲观锁

```
同一 doc_id → 唯一索引 uk_doc_id
acquire_lock(doc_id, ticket_id) → 加锁
release_lock(doc_id, ticket_id) → 释放
force_release_lock(doc_id) → 超时强制释放
```

#### 工单状态机

```
pending → approved → executed（正常流转）
pending → rejected（审批驳回）
pending → cancelled（申请人撤回）
pending → timeout（超时自动驳回）
pending → tampered（篡改拦截）
```

### 2.5 基础设施层

| 组件 | 技术选型 | 用途 |
|------|----------|------|
| 关系数据库 | MySQL 8.0 | 用户/文档/工单/审计/锁/版本 |
| 向量数据库 | FAISS | 文档 chunk 向量索引 + 归档向量库 |
| Embedding | BGE-M3 (1024维) | 文本向量化 |
| LLM | DeepSeek-V4-Flash | 问答生成 |
| Reranker | BGE-Reranker | 检索精排 |
| 文件系统 | 本地磁盘 | 文档原始文件存储 |

## 三、数据流向

```
员工上传文档 → API 网关 → 路由层 → BLP 写权限校验 → 文档锁检查
    → 暂存文件 → 自动创建工单 → 自动匹配审批人（BLP+部门）
    → 推送通知 → 审批人审批 → 哈希链核验 → 系统自动执行入库
    → 释放文档锁 → 通知申请人
```

## 四、安全架构

1. **人事数据安全**：HR 系统 → KMS 单向只读同步，KMS 不维护人事主数据
2. **访问控制**：BLP 强制访问控制 + 部门归属，权限判定仅依赖安全职级 L0-L3 + 部门
3. **工单内控**：文档变更全部走工单，A/B 两权分立（申请/审批），系统自动执行
4. **文档锁**：悲观锁防止并发变更
5. **审计日志**：独立存储，不可篡改，分级脱敏
6. **API 网关**：速率限制 + 全链路审计
