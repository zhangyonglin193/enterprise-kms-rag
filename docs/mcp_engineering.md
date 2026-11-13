# KMS MCP 知识服务升级 — 工程说明文档

版本：1.0，2026-10-17。本文与 `gateway_architecture.md`、`gateway_api_reference.md`、`../DEPLOY.md`
共同构成当前交付基线。

## 1. 目标与边界

把 KMS 已有的企业知识能力以 **MCP（Model Context Protocol）** 标准协议暴露给外部应用与 AI 智能体，
使 KMS 从"内部门户"升级为"可被外部标准接入的知识服务中台"。

| 维度 | 决策 |
|---|---|
| 挂载位置 | KMS 进程（6342）内，路径 `/gw/api/v1/mcp`，**不开新监听器** |
| QA 问答服务（6341） | **零改动**；`app/` 为冻结面，由 CI 守卫强制 |
| 传输 | MCP Streamable HTTP，单端点 POST（Phase 1 不做服务端 SSE 推送） |
| 数据边界 | 仅企业库/企业索引；**不提供任何通往 QA 竞赛语料的代码路径** |
| 默认状态 | `GW_MCP_ENABLED=0`，关闭时路由不注册（等价于功能不存在） |

## 2. 架构

```
外部应用 / 智能体（Cursor、Claude、客服工作台、商户 APP、集团智能体平台）
   │  POST /gw/api/v1/mcp   JSON-RPC 2.0 over HTTP
   ├─ EnterpriseBoundary（已有）：请求ID / IP+身份限流 / 审计 / 响应缓冲 / 体量限制
   ├─ gateway/mcp/auth.py      Bearer 员工 JWT（必需）+ X-API-Key 应用身份（可选）
   ├─ gateway/mcp/tools.py     8 个工具，内部转调既有能力，不复制业务逻辑
   ├─ gateway/mcp/resources.py 3 个资源模板，复用同一批 handler
   └─ gateway/mcp/guard.py     注入中和 + 不可信包裹 + 长度截断
                    │
   既有内核（不改动）：service.allowed / service.answer / routes_kms /
                     kms.recommend / gateway.state / gateway.audit
```

### 2.1 模块职责

| 文件 | 职责 |
|---|---|
| `gateway/mcp/protocol.py` | JSON-RPC 2.0 编解码、版本协商、错误码、最小 JSON Schema 校验、URI 模板匹配 |
| `gateway/mcp/schemas.py` | 工具/资源 schema **单一事实来源**，服务端与契约测试共用 |
| `gateway/mcp/auth.py` | 身份解析：`decode_token` + `_load_user` + `get_app_by_key`；密级取应用/员工交集 |
| `gateway/mcp/tools.py` | 工具 handler，统一 `(identity, args, request)` 签名 |
| `gateway/mcp/resources.py` | `kms://` 资源读取，URI → handler 分发 |
| `gateway/mcp/guard.py` | 输出安全：注入模式中和、`<untrusted_knowledge>` 包裹、截断 |
| `gateway/mcp/server.py` | FastAPI 路由、方法分发、按身份限流、指标、工具级审计 |
| `tests/test_mcp_protocol.py` | 离线回归：协议合规、schema 契约、参数边界、注入防护、开关行为 |

### 2.2 为什么不用官方 MCP SDK

协议面小（十余个方法），手写可把身份、审计、脱敏完全控制在项目既有机制内，符合本仓库
"依赖用范围约束、不锁死"的纪律；传输层差异全部收敛在 `protocol.py`，规范后续变更只换这一层。

## 3. 协议实现

### 3.1 方法集（Phase 1）

| 方法 | 说明 |
|---|---|
| `initialize` | 返回 `protocolVersion` / `capabilities` / `serverInfo` / `instructions` |
| `notifications/initialized`（及同类通知） | 无 id，返回 **202** 且无响应体 |
| `ping` | 健康检查 |
| `tools/list` | 按 `GW_MCP_TOOLS` 白名单过滤后的工具面 |
| `tools/call` | 参数 schema 校验 → 身份解析 → 身份限流 → handler → 审计 |
| `resources/list` / `resources/read` | 授权后的资源 |
| `resources/templates/list` | URI 模板声明 |

`GET`（服务端主动推送流）返回 405，规范允许不支持的服务端如此行为。

### 3.2 错误码

| 码 | 含义 |
|---|---|
| -32700 / -32600 / -32601 / -32602 / -32603 | JSON-RPC 2.0 预定义段 |
| -32001 / -32003 / -32004 / -32005 | 未认证 / 无权限 / 依赖不可用 / 触发限流（服务端自定义段） |

**HTTP 状态码约定**：协议级错误一律以 **HTTP 200 + JSON-RPC error** 返回。原因是
`EnterpriseBoundary` 中间件会把所有 ≥400 的响应体替换为网关统一错误信封（有意的防泄密设计），
这会销毁 JSON-RPC 错误信封、使客户端无法按 `id` 关联错误。仅传输层问题（请求体过大 413）
保留非 200 状态码。实现见 `protocol.http_status_for()`，并有单测锁定该行为。

### 3.3 版本协商

客户端可带 `MCP-Protocol-Version` 头；服务端支持列表由 `GW_MCP_PROTOCOL_VERSIONS` 配置
（默认锁定 `2025-06-18`），不自动追新——MCP 传输层已从 SSE 变更过一次。

## 4. 身份与权限

- **员工 JWT（必需）**：Bearer，服务端解析；**忽略客户端声明的任何部门/密级字段**。
- **应用 Key（可选）**：`X-API-Key`；与员工身份取密级交集，复用
  `gateway/routes_embed.py:ApplicationContext` 的同一模型，不发明第二套。
- **每次调用重新解析**：令牌撤销/改密即时生效；长链路（`ask_question`）前后各复核一次
  （复用 `security.revalidate_bearer`）。
- **参数不能提权**：`max_classification` 等参数与身份职级取 `min()`，只能收窄。
- **`Mcp-Session-Id`** 仅用于审计关联与限流分桶，不承载授权。

## 5. 工具面（Phase 1，只读为主）

| 工具 | 底层复用 | 写入？ |
|---|---|---|
| `search_knowledge` | `Retriever.retrieve` + `service.current_contexts` | 否 |
| `ask_question` | `service.answer`（检索即授权 + 返回前复核） | 否 |
| `get_document` | `routes_kms.document_row` + `service.allowed` | 否 |
| `list_documents` | `service.documents` | 否 |
| `get_recommendations` | `kms.recommend.recommend`（越权内容已硬过滤） | 否 |
| `submit_feedback` | `state.feedback` + `recommend.apply_feedback` | 否 |
| `submit_knowledge_request` | `routes_kms.propose`（**只建工单**） | 建工单 |
| `get_app_usage` | `kms_gw_audit` 聚合（仅应用身份或管理员） | 否 |

资源：`kms://documents/{id}`、`kms://recommendations`、`kms://app/usage`。

### 明确不暴露

审批通过/驳回、上传、删除、用户管理、HR 主数据、审计全量、原始文件字节、QA 竞赛库任何路径。
**双人审批不被旁路**：无 approve 类工具，批准永远留在 Web 端由审批员人工操作。

## 6. 安全设计

| 威胁 | 缓解 |
|---|---|
| 提示注入 / tool poisoning | `guard.py` 逐行中和已知注入模式；所有知识内容按数据处理并包裹 `<untrusted_knowledge>`；工具 `description` 为静态常量，禁止动态拼接 |
| 越权访问 | 每次调用过 `service.allowed()`；参数只能收窄；`additionalProperties: false` 严格校验 |
| 身份伪造 | 服务端解析令牌，忽略客户端声明字段；无 token 直接 -32001 |
| 审计泄敏 | 工具级审计只落 `args_digest`（sha256 前 16 位），**不明文落盘** |
| 滥用/刷量 | IP 级（中间件）+ 身份级（`mcp:{employee_no}` 桶）双重限流；`GW_MCP_TOOLS` 白名单 |
| 上下文炸弹 | `GW_MCP_MAX_RESULT_CHARS` 单次返回截断；请求体 64KiB 上限 |
| 数据出域 | `ask_question` 沿用 `GW_MODEL_EGRESS_ALLOWED` 闸门，未批准不出域 |

## 7. 配置项

| 键 | 默认 | 说明 |
|---|---|---|
| `GW_MCP_ENABLED` | `0` | 总开关；0 时路由不注册 |
| `GW_MCP_PROTOCOL_VERSIONS` | `2025-06-18` | 锁定支持的协议版本（逗号分隔） |
| `GW_MCP_TOOLS` | 8 个工具全开 | 工具白名单；启用时不可为空（禁止默认全开） |
| `GW_MCP_MAX_RESULT_CHARS` | `4000` | 单次返回文本截断长度（≥256） |

配置在 `config.py:validate_ports()` 同风格校验，非法值启动即失败。

## 8. 可观测性

- **日志**：`request_id / employee_no / app_id / tool / args_digest / latency / status`，复用 `get_logger`。
- **审计**：中间件记录 HTTP 级 `request_started` / `request_finished`（强制凭证）；
  handler 追加工具级 `mcp/tools/call` 事件（补充性质，失败仅告警——强制凭证已由中间件保证）。
- **指标**：进程内 per-tool 调用数/错误数/平均延迟，`GET /gw/api/v1/mcp/metrics`（仅管理员身份）。
- **健康**：`/readyz` 契约不变；启用状态通过指标端点与启动日志确认。

## 9. 部署与发布

1. 代码随发布包进入（`scripts/package_release.py` 已白名单 `gateway/mcp/` 与本文档）。
2. **第一阶段**：`GW_MCP_ENABLED=0` 上线——代码就位但不生效，验证存量行为零变化。
3. **第二阶段**：内网 `GW_MCP_ENABLED=1`，完成 §10 验收。
4. **第三阶段**：经甲方批准外部接入后，再评估对公网/外部智能体开放。

回滚：`GW_MCP_ENABLED=0` + 重启，**无需回滚代码**。

## 10. 验收标准

| 项 | 判定 |
|---|---|
| 单元/契约 | `python -m unittest discover -s tests` 全绿（含协议/schema/注入/开关用例） |
| QA 隔离 | CI 守卫：`app/` 与 `api.py` 有 diff 即失败 |
| 协议一致性 | `initialize` 能力协商；坏 JSON→-32700；未知方法→-32601；缺参→-32602；均带 `id` |
| 权限 | 无 token→-32001；低密级/跨部门→零泄漏；`max_classification` 不能提权；全部落审计 |
| 注入 | 含 `ignore previous instructions` / `忽略之前的所有指令` 的文档内容被中和后才进上下文 |
| 隔离 | 应用 A 看不到应用 B 的用量与审计 |
| 不影响存量 | embed / bots / Web 三套行为零变化（`test_enterprise.py` 全绿佐证） |
| 连通 | Cursor / Claude Desktop 填一段 `mcpServers` 配置即可调用 |

### 客户端接入示例（内部试点）

```jsonc
{
  "mcpServers": {
    "kms-knowledge": {
      "type": "http",
      "url": "http://127.0.0.1:6342/gw/api/v1/mcp",
      "headers": {
        "Authorization": "Bearer <员工JWT>",
        "MCP-Protocol-Version": "2025-06-18"
      }
    }
  }
}
```

## 11. 测试策略

| 层 | 内容 | 位置 |
|---|---|---|
| L1 单元 | 协议编解码、错误码、schema 契约、参数边界、guard 净化、URI 匹配、开关 | `tests/test_mcp_protocol.py`（离线，禁连真实 DB/模型） |
| L2 集成 | `TestClient` 端到端 `initialize` / `tools/list` / `tools/call` 错误路径 | 同文件 + 冒烟脚本 |
| L3 手工 | Cursor / Claude Desktop 实连，`DEPLOY.md` 级 curl 验收 | 运维 |

新增工具只需在 `schemas.py` 注册并在 `tools.py` 绑定 handler，契约测试自动覆盖形状。

## 12. 风险登记册

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 提示注入致智能体泄露 | 中 | 高 | guard 净化 + untrusted 包裹 + 只读工具 |
| 身份传递缺失致越权 | 中 | 高 | 每调用重校验、服务端解析、权限矩阵测试 |
| MCP 规范变动 | 高 | 中 | `protocol.py` 单层隔离 + 版本锁定 |
| 对外暴露扩大攻击面 | 中 | 高 | 默认关闭 + 工具白名单 + 出域审批 |
| 波及 6341 | 低 | 极高 | `app/` 冻结 + CI 守卫 |
| 审计明文泄密 | 中 | 中 | `args_digest` 只落哈希 |

## 13. 路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 协议层 + 8 工具 + 3 资源 + 身份/权限/审计/限流/guard，默认关闭 | **已完成（本文对应）** |
| Phase 2 | `submit_knowledge_request` 之外的治理面：应用自助配额、审计查询 API | 规划 |
| Phase 3 | MCP Client 模式：RAG 调用 `unionpay-mcp-server` 等外部工具（需出域批准） | 规划 |
| Phase 4 | 三座烟囱收敛：embed / bots / MCP 统一走 `gateway/knowledge/` 服务层 | 规划 |

## 14. 与集团 MCP 生态的关系

语料 `078-MCP接入服务指引` 显示银联已把支付能力包装为 `unionpay-mcp-server` 供智能体调用。
KMS MCP 化后，二者可组合成"智能体既能调用银联支付能力、又能检索企业知识"的完整场景；
工具白名单机制（`GW_MCP_TOOLS`）即对标其 `UP_AVAILABLE_TOOLS`。
