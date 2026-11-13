# 安全 RAG 知识管理竞赛系统 · 设计方案

> ⚠️ 历史版本材料（v1.0，2026-10-14）。当前交付基线为 `gateway_architecture.md`、`gateway_api_reference.md`、`enterprise_delivery.md` 与 `../DEPLOY.md`；本文旧设计叙述不代表现实现，且不进入发布白名单。

> 对标 IBM FileNet / Content Manager 企业级知识管理规范，业务安全逻辑全自研。
> 版本：v1.0 | 日期：2026-10-14

---

## 目录

1. [系统架构](#1-系统架构)
2. [数据表设计](#2-数据表设计)
3. [业务流程](#3-业务流程)
4. [答辩话术](#4-答辩话术)
5. [评委问题预判](#5-评委问题预判)

---

## 1. 系统架构

### 1.1 总体架构（五层模型）

```
┌─────────────────────────────────────────────────────────────────┐
│  L5 外部应用层（第三方系统/移动端/合作伙伴）                        │
│      ↓ 仅 RESTful API，双层鉴权 + 限流，禁止直连底层存储            │
├─────────────────────────────────────────────────────────────────┤
│  L4 API 网关层                                                    │
│      ├─ 鉴权过滤器（AppKey + HMAC 签名 / 用户 JWT 双层校验）        │
│      ├─ 限流过滤器（令牌桶：应用级 QPS + 用户级 QPS）               │
│      ├─ 审计埋点（全量请求/响应摘要入审计流）                       │
│      └─ 路由守卫：变更类请求（写/删）强制转入工单服务               │
├─────────────────────────────────────────────────────────────────┤
│  L3 应用服务层（自研安全内核）                                      │
│      ├─ 工单引擎：三权分立状态机 + 文档悲观锁 + 超时自动驳回        │
│      ├─ 权限引擎：BLP 强制访问控制 + 部门约束叠加判定               │
│      ├─ 检索引擎：向量召回 → 密级过滤 → 部门过滤 → 归档过滤 → 重排 │
│      ├─ HR 同步服务：人员/部门/职位/密级定时全量对账（只读消费）    │
│      └─ 版本服务：doc_id 主线 + version 快照 + 归档隔离            │
├─────────────────────────────────────────────────────────────────┤
│  L2 数据访问层                                                    │
│      ├─ MySQL 主库（工单/权限/审计，事务强一致）                    │
│      ├─ 向量库（FAISS 本地索引，仅存 chunk 向量 + doc_version_id） │
│      └─ 对象存储/文件系统（文档原文，按 doc_id/version 隔离目录）   │
├─────────────────────────────────────────────────────────────────┤
│  L1 基础设施层                                                    │
│      └─ 审计 WORM 存储（Write Once Read Many，日志落盘只追加）     │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 关键设计决策（对应 IBM KMS 规范映射）

| IBM KMS 规范 | 本系统落地 | 决策理由 |
|---|---|---|
| 人员主数据单一权威源 | HR 数据表只读导入，本系统**零维护**账号/部门/职位/密级 | 避免双写不一致，人事变更由 HR 系统单向驱动 |
| 强制访问控制（MAC） | BLP 格模型：不上读、不下写 | 密级 L0-L3 偏序格，数学上可证明无越级通道 |
| 职责分离（SoD） | 文档变更 A申请/B审批/C执行三账号互斥 | 同一人不得兼任同一工单的任意两角 |
| 最小权限 + 按需知密 | 默认仅本部门+本密级及以下；跨部门需文档级授权 | 部门约束是 BLP 的**与**叠加，不突破格规则 |
| 变更互斥 | 文档悲观锁：同 doc_id 全局仅一条在途工单 | 防止并发变更产生版本分叉 |
| 时效约束 | 工单超时自动驳回，锁自动释放 | 防止死锁，保证可用性 |
| 全量审计 | 网关→服务→存储三段留痕，分级脱敏 | 满足等保/赛题"全程留痕"要求 |
| 开放但受控 | 外部应用仅经 API 网关，变更只能发起工单 | 写路径唯一入口，杜绝旁路 |

### 1.3 安全边界

```
可信边界1 [HR域]  ──单向同步──▶  可信边界2 [KMS域]
                                        │
                  外部应用 ──网关──▶ 只读API / 工单申请API
                                        │
                              执行器（系统内部，C 触发）
                                        ▼
                              向量库 / 文件存储（内部直连，不对外）
```

- **HR → KMS**：单向只读，KMS 不回写 HR。
- **外部 → 网关**：唯一入口，无网关签名直连 MySQL/向量库在网络层不可达。
- **写路径**：外部任何"写"意图 = 生成一条工单记录，不产生实际变更；实际变更仅由"执行器"在工单流转到 C 执行节点时触发。

---

## 2. 数据表设计

> 命名约定：`hr_` 前缀 = HR 同步只读表；`kms_` 前缀 = 本系统自有表。
> 所有表 `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`。

### 2.1 HR 同步只读表（本系统不维护）

**hr_users — 人员主数据（HR 权威源）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| employee_no | VARCHAR(32) | PK | 工号（一人一号，全局唯一） |
| username | VARCHAR(64) | NOT NULL | 姓名 |
| dept_id | INT | NOT NULL, FK→hr_departments | 所属部门 |
| position | VARCHAR(64) | NOT NULL | 职位（用于审批人候选推荐） |
| sec_level | TINYINT | NOT NULL, CHECK 0-3 | 人员密级 L0-L3（HR 定级） |
| is_active | TINYINT(1) | NOT NULL DEFAULT 1 | 在职状态（离职=0，同步后立即失效） |
| synced_at | DATETIME | NOT NULL | 最近同步时间（对账用） |
| row_hash | CHAR(64) | NOT NULL | 行内容 SHA-256（增量同步依据） |

> 口令不落地本表；登录由统一认证服务（LDAP/OIDC）完成，本系统只消费身份断言。

**hr_departments — 部门表**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT | PK AUTO_INCREMENT | 部门ID |
| name | VARCHAR(64) | NOT NULL | 部门名 |
| parent_id | INT | NULL | 父部门（树形，用于"含子部门"授权） |
| path | VARCHAR(255) | NOT NULL | 物化路径 `/1/4/7/`（子树查询 O(1)） |
| is_active | TINYINT(1) | NOT NULL DEFAULT 1 | 启用状态 |

### 2.2 文档域

**kms_documents — 文档主线（doc_id 唯一标识一份文档）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| doc_id | BIGINT | PK AUTO_INCREMENT | 文档全局标识（贯穿所有版本） |
| title | VARCHAR(255) | NOT NULL | 标题 |
| sec_level | TINYINT | NOT NULL | 当前生效密级 L0-L3 |
| owner_dept_id | INT | NOT NULL, FK | 归属部门（默认仅本部门可见） |
| current_version | INT | NOT NULL DEFAULT 1 | 当前生效版本号 |
| status | VARCHAR(16) | NOT NULL | 状态：active / locked（有在途工单） |
| created_by | VARCHAR(32) | NOT NULL | 创建人工号（快照，HR 无关化） |
| created_at / updated_at | DATETIME | NOT NULL | 时间戳 |

**kms_document_versions — 文档版本（旧版本归档，检索过滤）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGINT | PK AUTO_INCREMENT | 版本记录ID |
| doc_id | BIGINT | NOT NULL, FK | 所属文档 |
| version | INT | NOT NULL | 版本号（自增） |
| content_hash | CHAR(64) | NOT NULL | 内容 SHA-256（防篡改+去重） |
| file_path | VARCHAR(512) | NOT NULL | 原文存储路径 |
| lifecycle | VARCHAR(16) | NOT NULL | **current / archived**（检索只查 current） |
| change_ticket_id | BIGINT | NULL, FK | 产生本版本的工单 |
| created_at | DATETIME | NOT NULL | |
| | | UNIQUE(doc_id, version) | 版本唯一约束 |

**kms_doc_departments — 文档跨部门授权（BLP 叠加层）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| doc_id | BIGINT | NOT NULL, FK | 文档 |
| dept_id | INT | NOT NULL, FK | 被授权部门（含其子部门，按 path 展开） |
| include_children | TINYINT(1) | DEFAULT 1 | 是否含子部门 |
| | | PK(doc_id, dept_id) | 联合主键 |

> 可见性公式：`BLP通过(sec_level≤人员密级) AND (本部门 OR 在授权表命中)`

### 2.3 工单域（三权分立 + 悲观锁 + 超时驳回）

**kms_tickets — 变更工单**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| ticket_id | BIGINT | PK AUTO_INCREMENT | 工单号 |
| ticket_no | VARCHAR(32) | UNIQUE | 业务单号 GD20261014-XXXXXX |
| change_type | VARCHAR(16) | NOT NULL | create / update / delete |
| doc_id | BIGINT | NULL, FK | 目标文档（create 时为 NULL，执行后回填） |
| payload | JSON | NOT NULL | 变更内容（新内容hash/目标密级/授权部门等） |
| applicant_no | VARCHAR(32) | NOT NULL | A 申请人工号 |
| approver_no | VARCHAR(32) | NOT NULL | B 审批人工号 |
| executor_no | VARCHAR(32) | NULL | C 执行人工号（B 通过时指定） |
| status | VARCHAR(16) | NOT NULL | pending / approved / executed / rejected / expired |
| payload_hash | CHAR(64) | NOT NULL | 申请内容哈希（防篡改基准） |
| approved_hash | CHAR(64) | NULL | 审批时哈希（执行前复核一致性） |
| deadline_at | DATETIME | NOT NULL | 超时时间（创建时 +N 小时） |
| created_at / closed_at | DATETIME | | |

> 三账号互斥约束：`applicant_no <> approver_no AND approver_no <> executor_no AND applicant_no <> executor_no`

**kms_doc_locks — 文档悲观锁（在途工单互斥）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| doc_id | BIGINT | **PK** | 被锁文档（主键即互斥） |
| ticket_id | BIGINT | NOT NULL, FK UNIQUE | 持锁工单 |
| locked_at | DATETIME | NOT NULL | 加锁时间 |
| expires_at | DATETIME | NOT NULL | 锁超时（与工单 deadline 同步） |

> 加锁方式：`INSERT INTO kms_doc_locks ...` 依赖主键冲突实现互斥，无需 SELECT FOR UPDATE，避免长事务。工单关闭（executed/rejected/expired）即 DELETE 释放。

### 2.4 网关与应用域

**kms_api_apps — 外部应用注册**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| app_id | VARCHAR(32) | PK | 应用标识 |
| app_secret_hash | CHAR(64) | NOT NULL | 密钥仅存 SHA-256 |
| allowed_scopes | VARCHAR(255) | NOT NULL | 授权范围：read / ticket_apply |
| qps_limit | INT | NOT NULL DEFAULT 20 | 应用级 QPS |
| max_sec_level | TINYINT | NOT NULL | 应用可触达的最高密级（二次封顶） |
| is_active | TINYINT(1) | DEFAULT 1 | |

### 2.5 审计域（分级脱敏）

**kms_audit_logs — 全量审计日志**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGINT | PK AUTO_INCREMENT | |
| trace_id | CHAR(32) | NOT NULL, INDEX | 全链路追踪ID（网关生成，贯穿各服务） |
| actor | VARCHAR(32) | NOT NULL | 操作者（工号或 app_id） |
| sensitivity | TINYINT | NOT NULL | **脱敏级别：0公开 1内部 2敏感** |
| action | VARCHAR(48) | NOT NULL | 动作（login/read/ticket_create/execute…） |
| target | VARCHAR(128) | | 对象（doc_id/ticket_id，敏感级仅存hash） |
| detail | TEXT | | 摘要（按 sensitivity 分级脱敏后落盘） |
| result | VARCHAR(16) | NOT NULL | success / denied / failure |
| prev_hash | CHAR(64) | NOT NULL | 上一条日志哈希 |
| entry_hash | CHAR(64) | NOT NULL | 本条哈希 = SHA256(prev_hash+内容) |
| created_at | DATETIME | NOT NULL | |

> **哈希链 + WORM 存储**：日志表仅 INSERT（数据库账号无 UPDATE/DELETE 权限），文件层追加写只读卷；任意删改都会导致链式校验断裂。
> **分级脱敏规则**：L1 脱敏工号中段、IP 后两段；L2 仅存哈希指纹，明文进独立保密库（双人双控查询）。

---

## 3. 业务流程

### 3.1 HR 数据同步流程（单向对账）

```
HR系统（权威源）
   │ 每日02:00 全量快照 + 每小时增量
   ▼
同步适配器：逐行计算 row_hash，与库内比对
   ├─ hash 一致 → 跳过
   ├─ hash 变更 → UPDATE（部门/职位/密级跟随 HR）
   ├─ 新增     → INSERT
   └─ HR侧删除 → is_active=0（即时生效：该人 JWT 下次校验即拒）
   ▼
对账报告：不一致行数、同步耗时 → 审计日志（sensitivity=1）
```

### 3.2 文档变更工单流程（核心写路径）

```
A(申请人)                B(审批人)               C(执行人)              系统
  │                        │                      │                    │
  │── ①提交变更申请 ───────▶│                      │                    │
  │   (create/update/delete)│                      │                    │
  │                        │                      │           ②校验: BLP可写?
  │                        │                      │           ③加悲观锁:
  │                        │                      │     INSERT doc_locks(doc_id)
  │                        │                      │     冲突→拒绝"已有在途工单"
  │                        │                      │           ④生成 payload_hash
  │                        │                      │           ⑤设置 deadline
  │                        │                      │                    │
  │                        │── ⑥审阅完整内容 ─────▶│                    │
  │                        │   通过(指定C)         │                    │
  │                        │                      │           ⑦生成 approved_hash
  │                        │                      │                    │
  │                        │                      │── ⑧盲执行视图 ─────▶│
  │                        │                      │   (只见核验清单,    │
  │                        │                      │    不见具体内容)    │
  │                        │                      │   确认执行          │
  │                        │                      │           ⑨复核 hash 一致
  │                        │                      │           ⑩执行变更:
  │                        │                      │             version+1 落库
  │                        │                      │             旧版本 lifecycle→archived
  │                        │                      │             向量库重建(current only)
  │                        │                      │           ⑪释放锁+通知A
  ▼                        ▼                      ▼                    ▼
【超时守护】定时扫描 deadline_at < now() 且未关闭的工单:
   → status=expired → DELETE doc_locks → 通知 A/B"工单超时自动驳回"
```

**关键不变式**：
- 同一 doc_id 任意时刻最多一条 `status IN (pending, approved)` 的工单（由 `kms_doc_locks` 主键保证）。
- C 执行前强制 `approved_hash == SHA256(当前payload)`，不一致则工单作废（防 A 提交后篡改、防 B 审批内容被改）。

### 3.3 检索问答流程（读路径，四重过滤）

```
用户/应用 ──▶ 网关(鉴权+限流) ──▶ 检索引擎
                                     │
                              ① 向量召回 topK×3（放大召回）
                                     │
                              ② BLP 过滤：chunk密级 ≤ 人员密级
                                     │
                              ③ 部门过滤：归属本部门 OR 命中授权表
                                     │
                              ④ 归档过滤：version.lifecycle='current'
                                     │
                              ⑤ 应用封顶：app.max_sec_level 二次过滤（应用调用时）
                                     │
                              ⑥ 重排取 topK → 拼装上下文 → LLM
                                     │
                              ⑦ 引用标注 [doc_id@version] 可溯源
                                     ▼
                        审计日志（query 摘要，sensitivity=1）
```

### 3.4 外部应用接入流程

```
① 注册：管理员在网关注册 app_id，签发 app_secret（仅展示一次，库存哈希）
② 调用：每次请求携带
    - X-App-Id + X-Timestamp + X-Nonce
    - X-Signature = HMAC-SHA256(app_secret, 方法+路径+时间戳+nonce+body)
③ 网关校验：签名(防伪) → 时间窗±5min(防重放) → nonce 缓存(防重放二次) → QPS 令牌桶
④ 写意图拦截：POST/PUT/DELETE /documents/** → 强制改写为 POST /tickets（发起工单）
   —— 外部应用物理上无法触达文档直写接口
```

---

## 4. 答辩话术

### 4.1 开场（60 秒）

> "各位评委好。我们的系统是一套对标 IBM FileNet 企业知识管理规范的安全 RAG 平台。与直接部署开源方案不同，我们把竞赛的核心——**业务安全逻辑**——全部自研：用 Bell-LaPadula 格模型做强制访问控制，用三权分立工单管住每一次文档变更，用悲观锁和超时驳回保证变更互斥与系统可用。人员数据我们不维护，单向从 HR 权威源同步，从源头消灭越权账号。一句话总结：**读，有 BLP 和部门双重闸门；写，只有工单一条路；全程，审计哈希链留痕。**"

### 4.2 三大核心亮点（每个 45 秒）

**亮点一：写路径唯一化 + 三权分立**
> "外部应用和内部用户都无法直接写文档。所有变更收敛为工单：A 申请、B 审批、C 执行，三个角色必须三个不同账号，C 执行时看到的是盲视图——只知道'该做什么'，不知道'内容是什么'，执行前系统强制比对申请哈希与审批哈希，任何环节篡改都会导致工单自动作废。这就是 IBM 规范里的职责分离（SoD）和不可抵赖。"

**亮点二：BLP + 部门的双重访问控制**
> "读取侧，我们实现了 BLP 格模型：不上读、不下写，L1 员工看 L1 及以下，这是数学上可证明无越级通道的。在此基础上叠加部门约束：文档默认只对本部门可见，跨部门要在文档级显式授权，而且授权只能在 BLP 通过的前提下生效——部门授权永远不能突破密级天花板。两个条件是与的关系，取交集，不会放大权限。"

**亮点三：悲观锁 + 超时驳回的可用性设计**
> "并发变更同一份文档会产生版本分叉。我们的解法是文档悲观锁：工单创建时向锁表插入 doc_id 主键，撞主键即拒绝，保证一份文档全局只有一条在途变更。同时每条工单有截止时间，超时未闭环自动驳回、自动释放锁——既防并发冲突，又防锁被挂起的工单拖死，兼顾了一致性和可用性。"

### 4.3 收尾（30 秒）

> "从 HR 单向同步的人员主数据，到网关的双层鉴权限流，到版本归档与检索隔离，再到审计哈希链的分级脱敏，整条链路没有依赖任何现成的开源权限框架，每一行安全逻辑都可解释、可验证、可答辩。谢谢各位评委，请提问。"

---

## 5. 评委问题预判

### Q1：为什么不用 Spring Security / Apache Ranger / Keycloak 这类成熟方案？

**答**：三个原因。第一，赛题考察的是对安全模型的理解深度，黑盒引入框架无法展示 BLP 格模型的形式化实现过程；第二，企业真实场景中，BLP 密级格与部门叠加的复合判定在通用框架里没有开箱支持，仍需大量定制，自研反而更可控；第三，我们的安全内核只有约两千行代码，全部可审计——而引入一个 Ranger 等于引入几十万行无法逐行验证的代码，攻击面反而扩大。当然，非安全逻辑如 HTTP 框架我们使用了成熟组件，自研的是安全决策点（PDP）。

### Q2：BLP"不下写"会不会影响协作？比如高密级领导想给低密级部门发文？

**答**：这是 BLP 的经典问题，我们按 IBM 规范用**受控降密**解决：高密级人员不能直接写低密级文档，但可以在工单中申请"降密发布"，payload 里声明目标密级，由对应低密级部门的 B 审批、C 执行。降密这个动作本身被工单三权分立和审计链管起来，既保住了 BLP 的数学性质，又满足了业务下行发文的需求。绝不开"高写低"的口子，那是 BLP 最著名的隐蔽通道来源。

### Q3：悲观锁在分布式部署下怎么保证？性能会不会是瓶颈？

**答**：锁的互斥不依赖应用内存，而是依赖 MySQL 主键唯一约束——INSERT 撞主键即抢锁失败，这在单库和分库（按 doc_id 取模路由）下都成立，天然支持水平扩展。性能上，加锁是单次 INSERT，释放是单次 DELETE，都是毫秒级主键操作；且锁记录数上限 = 在途工单数，实际并发变更同一文档的场景在企业里本来就是低频。真正高频的是读，读路径完全无锁，用 MVCC。

### Q4：审计日志如何保证不被管理员篡改？

**答**：三层防护。第一层**哈希链**：每条日志包含上一条的哈希，改动任何历史记录都会使后续全链条校验失败，篡改可检测；第二层**WORM 存储**：日志数据库账号只授予 INSERT 权限，没有 UPDATE/DELETE，文件层落只追加卷；第三层**分级脱敏+双人双控**：敏感级日志明文存独立保密库，查询需要两名授权人同时操作。即便 DBA 物理拿到库，他能删库但删得"留痕迹"——链断了本身就是最强告警。

### Q5：人员密级由 HR 定，如果 HR 数据错了怎么办？你们把安全寄托在外部系统上？

**答**：恰恰相反，这是**单一权威源**原则——密级多头维护才是最大风险。HR 定级有行政流程背书，比技术系统自封密级更可靠。我们的防护在于：一，同步是单向只读，本系统无法反向污染 HR；二，每日全量对账 + 行哈希比对，异常变更加告警；三，即使 HR 误将某人密级调高，他能读到的也只是"更高密级但仍是本部门或授权部门"的文档——部门约束这层闸门不受密级错误影响，风险被第二重闸门收敛。

### Q6：RAG 检索会泄漏密级信息吗？比如通过模型回答侧信道推断出高密级文档内容？

**答**：我们在检索层就做了硬隔离，高密级 chunk 对低密级用户**根本不进入候选集**——不是"召回了再删掉答案"，而是向量查询结果在进入 LLM 上下文前已经过了 BLP、部门、归档三重过滤，低密级用户的上下文窗口里物理上不存在越权内容，模型无从泄露。同时答案中强制携带 `[doc_id@version]` 引用标注，评委可以抽查任何一条回答逐条溯源到具体文档版本。

### Q7：工单超时时长怎么定的？自动驳回会不会影响正常长流程？

**答**：超时是可配置的，默认申请→审批 24 小时、审批→执行 24 小时。设计上我们参考了 ITIL 变更管理的 SLA 思路：变更窗口本就应有时效约束，无限期的审批等于无限期持锁。超时驳回不是粗暴失败——系统会提前 2 小时通知 B 催办，驳回后申请人可以基于原 payload 一键重新发起，业务连续性不受影响，但锁一定被释放，这是可用性底线。

### Q8：双层鉴权具体指什么？为什么要两层？

**答**：第一层**应用身份**（app_id + HMAC 签名），回答"这个请求来自哪个注册应用、报文有没有被改"；第二层**用户身份**（终端用户 JWT，应用代用户调用时透传），回答"操作者是谁、他的密级和部门是什么"。只验应用层，网关无法做 BLP——因为 BLP 判定的是"人"的密级；只验用户层，又管不住"哪个应用在调"。两层组合才能同时实现传输防伪与细粒度授权，这也是 IBM API Connect 网关的标准模式。

### Q9：版本归档后，旧版本还能查吗？历史审计需要回看怎么办？

**答**：检索问答只查 `lifecycle='current'`，保证 RAG 答案永远基于最新生效版本；但归档版本**物理保留**，审计和合规场景可以通过工单申请调阅历史版本，调阅动作本身也走审批并留痕。即"检索隔离，但审计可达"——可用性与可追溯性各取所需。

### Q10：如果让你继续迭代，下一步做什么？

**答**：三个方向。一是**组织树规则引擎**：目前部门约束是显式授权表，下一步引入"经理可见下属文档"等基于 HR 汇报线的动态规则，规则做成可配置的策略链；二是**内容级 DLP**：在工单审批环节接入敏感信息识别，比如身份证、银行卡号自动打标，审批人能看到"该文档含 N 处敏感实体"的风险提示；三是**检索质量与安全联动**：监控低密级用户对高密级主题的集中试探性提问，异常模式触发风控告警，把安全从事后审计前移到实时检测。

---

> 文档结束。本方案安全决策点（PDP）全部自研，未引入现成开源权限/工单框架，符合竞赛"业务安全逻辑自研"要求。
