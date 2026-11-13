# 企业 REST API 契约与办公生态接入

版本：2.0，2026-10-15。以 `run_kms.create_app()` 实际挂载接口为准。默认 KMS Base URL：`http://127.0.0.1:6342`，只用于本机或 SSH 隧道；非本机传输必须经批准的 HTTPS 设施。不要把本例直接当作公网开放配置。

## 1. 身份、权限与响应规范

### 1.1 认证

| 调用者 | 凭据 | 权限边界 |
|---|---|---|
| 员工工作台 | `Authorization: Bearer <JWT>` | 当前在职员工；部门、密级实时查库 |
| 嵌入方服务端 | `X-API-Key: <key>` | 有效应用；仅 Key 最多读取已发布 L0 |
| 嵌入方访问内部知识 | Key + 员工 JWT | 应用密级范围与员工、文档权限的交集 |
| 飞书/企微 | 平台签名、加密配置、平台用户绑定 | 验证平台身份后映射在职员工；未绑定不降级 |
| 6341 评测 | 无员工认证 | 只能使用独立竞赛公开数据 |

JWT：HS256，issuer=`unionpay-kms`，audience=`enterprise-knowledge`，默认 1 小时，配置范围 1～8 小时；包含 sub/emp/role/level/dept/iat/exp/jti。授权不信任 JWT 中的旧部门/密级。登出撤销当前 jti；修改密码撤销员工此前签发的全部 JWT。

禁止把应用 Key 放在浏览器、URL、localStorage 或公开前端配置中。Key 只在创建及轮换响应中返回明文，后续查询不可恢复。应用停用立即阻止后续认证，长问答返回前也复核应用状态。

### 1.2 响应

嵌入 API 成功响应统一为：

```json
{"code":0,"message":"success","request_id":"gw-<32位十六进制>","data":{"answer":"示例答案","sources":[],"message_id":"<32位十六进制>"}}
```

KMS 成功响应保留业务对象，不额外套 data；例如 `{"ok":true}`。平台成功 ACK 按平台协议，不能改成统一业务信封。企业 API 错误统一为：

```json
{"code":403,"message":"无权执行该操作","request_id":"gw-<32位十六进制>","data":null}
```

HTTP 状态是主要判据，错误 code 与状态一致。企业接口响应包含 `X-Request-ID`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。429 包含 `Retry-After: 60`。当前不承诺 `X-RateLimit-Remaining` 或 `X-Response-Time`。

| HTTP/code | 含义 | 客户端处置 |
|---|---|---|
| 400 | 回调格式错误、旧密码错误等 | 校验请求，不重复提交原请求 |
| 401 | 凭据缺失、无效、过期、撤销或平台签名失败 | 重新认证，禁止匿名降级 |
| 403 | 应用停用、部门/职责不符、自批、群聊等 | 申请正确授权，不重试绕过 |
| 404 | 资源不存在或不可见、回执不属于主体 | 不据此区分隐藏资源是否存在 |
| 405 | 方法不支持 | 核对清单 |
| 409 | 已有申请、已处理、快照/文档变化、重复文件或入库忙 | 查询当前状态后重新操作 |
| 413 | 请求超限、上传文件为空或超过 10 MiB | 修正请求 |
| 422 | 字段/长度/密级范围不合法 | 修正请求模型 |
| 429 | IP/应用/账号限流 | 等待后退避 |
| 500/502/503 | 内部/上游/安全依赖不可用、模型出域关闭 | 结合请求号排查；写请求不能盲目重试 |

网关开始审计失败时不执行业务；完成审计失败时不放行正文。但数据库提交可能早于完成审计，503 不等于“未执行”。当前不支持通用 `Idempotency-Key`；治理操作使用申请 ID/状态核对，Key 轮换失败需核对并安全重新轮换，不能假定旧 Key 仍有效。

普通企业请求上限 64 KiB；文件请求整体 11 MiB，单文件 10 MiB；响应缓冲上限 16 MiB。应用默认 60 次/分钟，真实 socket IP 默认该值的 5 倍。未信任代理头，反代后的流量可能共享同一个 IP 限额。

## 2. 全量企业接口清单

下表 KMS 路径以 `/kms/api` 开头；所有接口除 login 和合法 OPTIONS 外要求员工 JWT。

| 方法 | 路径 | 额外授权/功能 | 成功状态 |
|---|---|---|---|
| POST | `/kms/api/auth/login` | 工号+密码，失败锁定 | 200 |
| GET | `/kms/api/auth/me` | 当前员工 | 200 |
| POST | `/kms/api/auth/logout` | 撤销当前 JWT | 200 |
| POST | `/kms/api/auth/change-password` | 验证旧密码并撤销旧 JWT | 200 |
| POST | `/kms/api/chat` | 已发布有效知识单轮问答 | 200 |
| POST | `/kms/api/feedback` | 只能反馈本员工回执 | 200 |
| GET | `/kms/api/documents` | 授权目录分页 | 200 |
| GET | `/kms/api/documents/{doc_id}` | 已发布授权正文 | 200 |
| POST | `/kms/api/documents` | 本部门 L3 维护员；模型出域已批准 | 201 |
| GET | `/kms/api/governance/documents` | 维护员、当前部门/密级 | 200 |
| GET | `/kms/api/governance/documents/{doc_id}` | 维护员或审批员、当前部门/密级 | 200 |
| POST | `/kms/api/governance/documents/{doc_id}/requests` | 维护员提出策略 | 201 |
| GET | `/kms/api/governance/requests` | 维护员/审批员，文档和策略均在授权范围 | 200 |
| POST | `/kms/api/governance/requests/{request_id}/decision` | 独立同部门审批员 | 200 |
| GET | `/kms/api/admin/users` | 显式管理员，员工镜像只读 | 200 |
| GET | `/kms/api/admin/levels` | 显式管理员，L0～L3 只读 | 200 |
| GET | `/kms/api/admin/hr-sync/history` | 管理员且 L2+，历史只读 | 200 |
| GET | `/kms/api/admin/apps` | 显式管理员 | 200 |
| POST | `/kms/api/admin/apps` | 显式管理员 | 201 |
| PUT | `/kms/api/admin/apps/{app_id}` | 显式管理员 | 200 |
| POST | `/kms/api/admin/apps/{app_id}/rotate-key` | 管理员且能管理应用密级 | 200 |
| PUT | `/kms/api/admin/bot-bindings` | 显式管理员，目标员工在职 | 200 |
| DELETE | `/kms/api/admin/bot-bindings` | 显式管理员 | 200 |
| GET | `/kms/api/admin/audit-events` | 显式审计员 | 200 |
| GET | `/kms/api/admin/audit-logs` | 显式审计员，旧业务审计查询 | 200 |
| GET | `/kms/api/admin/openapi.json` | 显式管理员，当前机器可读契约 | 200 |

不注册：旧 `/chat`、工单、历史会话、SSE、旧版本覆盖、旧推荐分析和 `POST /kms/api/admin/hr-sync`。未知路由不代表这些能力可用。KMS 的 `/docs`、`/redoc`、公开 `/openapi.json` 关闭。

### 2.1 登录与账号

`POST /auth/login`：

```json
{"employee_no":"<批准的员工工号>","password":"<密码>"}
```

employee_no 长度 2～64，password 长度 1～128。成功为 `{"token":"<JWT>","user":{...}}`；user 包含 id、employee_no、username、role、security_level、department、business_title、is_active 等。失败连续 5 次锁定 5 分钟。没有可公开使用的默认生产账号。

`GET /auth/me` 返回员工公开属性。`POST /auth/logout` 无请求体，成功 `{"ok":true}`。`POST /auth/change-password`：

```json
{"old_password":"<旧密码>","new_password":"<12～128位、字母和数字的新密码>"}
```

成功返回 ok/message，随后必须重新登录。首次密码由受控初始化工具交付；本版未实现强制首次改密工作流或自助找回密码。

`GET /admin/users` 返回 total/items，不含密码散列。`GET /admin/levels` 返回 level/name/description。`GET /admin/hr-sync/history?limit=20` 仅查看历史，不能说明已经接通 HR 数据源。

### 2.2 问答、反馈与目录

两种问答接口仅接受：

```json
{"question":"商户如何处理结算差错？"}
```

question 去首尾空白后长度 1～500；拒绝多余字段，尤其 session_id/use_history/end_user。工作台响应：

```json
{"answer":"依据授权资料生成的答案","sources":[{"document_id":12,"title":"结算操作说明","page":3}],"message_id":"0123456789abcdef0123456789abcdef","history":false}
```

嵌入响应 data 中包含 answer/sources/message_id；history 能力由 config 返回 false。没有可访问资料时正常返回明确拒答和空 sources，不伪造参考文档。

反馈请求（工作台和嵌入 API 共用模型）：

```json
{"message_id":"0123456789abcdef0123456789abcdef","rating":"down","comment":"资料可能过期，请复核"}
```

message_id 为 32 位小写十六进制，rating=up/down，comment 最长 500；禁止额外字段。相同回执再次提交更新反馈。跨员工、跨应用、跨工作台/嵌入渠道的回执不能互用，返回404。

`GET /documents?offset=0&limit=50`：offset≥0，limit=1～100；嵌入默认 limit=20，工作台默认50。结果 total/items/offset/limit，item 为 document_id/title/file_type/classification。查询在数据库授权过滤后分页。

`GET /documents/{doc_id}`：返回 document 的四项元数据和 chunks（chunk_index/text/page）。这是受认证员工的正文接口，不是向外部应用开放的裸分块检索；应用 Key 不能调用。超大正文可能触发响应上限。

### 2.3 草稿与双人治理

上传使用 `multipart/form-data`，字段 `file`；接受 pdf/docx/txt/md/xlsx。不允许覆盖同名或同哈希文档，单文件串行，无持久上传队列。响应：

```json
{"document_id":12,"status":"draft","classification":3}
```

入库不等于发布。模型开关关闭时上传403；受控试点应只上传已完成线下文件安全审查的文件。

治理目录：`GET /governance/documents?limit=100`，limit=1～200；items 含 document_id/title/filename/status/owner_department/classification。治理正文额外显示当前策略、有效期及最多1000分块，不输出磁盘路径；更长文档不得在缺少完整审阅条件下批准。

申请：`POST /governance/documents/12/requests`：

```json
{"classification":1,"owner_department":"商户服务部","extra_departments":["客户服务部"],"status":"published","reason":"已完成业务与合规复核，允许内部使用"}
```

- classification：0～3，不能超过申请人可管理密级。
- owner_department：1～128字符且等于当前员工部门；当前不支持跨部门移交。
- extra_departments：默认空数组，最多30项，每项非空且≤128字符。
- status：published/archived/expired；reason：5～500字符。
- 文档必须属于本部门，未分类只能由本部门 L3 治理。无归属资产需线下补正。
- 返回 `{"id":"<申请ID>","status":"pending"}`；相同文档已有 pending 则409。

`GET /governance/requests` 最多200条，按创建时间降序。items 含 id/document_id/requested_by/status/created_at/policy。policy 为持久化JSON，驱动可能返回JSON字符串；工作台按当前返回呈现。文档当前分类、归属及申请中的拟定分类、归属必须均在查看者权限范围内。

审批：`POST /governance/requests/<申请ID>/decision`，正文 `{"approve":true}` 或 `{"approve":false}`。返回 id/status，状态为 approved/rejected。不得自批、跨部门、越级；批准前检查申请人在职与职责、当前文档快照、过期时间。冲突后先驳回，再发起新申请。本版没有取消申请、直接修改 expires_at 或物理删除文档 API。

### 2.4 应用与机器人绑定

创建/完整替换应用模型：

```json
{"app_name":"商户服务门户","allowed_min_level":0,"allowed_max_level":1,"is_active":true}
```

app_name 为1～128字符；min/max为0～3且min≤max≤操作者密级。创建返回上述字段及 app_id/api_key；PUT 返回 ok。省略可选字段会使用模型默认值（0/0/true），因此更新必须发送完整预期配置。停用使用 is_active=false，无物理删除 API。

轮换：`POST /admin/apps/{app_id}/rotate-key` 无正文，返回 app_id/api_key，旧Key失效，无双Key过渡期。应用查询不会返回Key或Key哈希。创建与启停状态同事务落库，轮换通过行锁确认应用存在。

绑定：`PUT /admin/bot-bindings`：

```json
{"platform":"feishu","external_user_id":"<该应用下的open_id>","employee_no":"<真实工号>"}
```

platform=feishu/wecom；external_user_id长度1～128；employee_no长度1～32。企微使用成员 UserID。管理员必须线下核实平台账号归属；接口不能代替身份核验。

解绑：`DELETE /admin/bot-bindings?platform=wecom&external_user_id=<URL编码后的UserID>`，返回 ok；对已不存在的绑定仍成功。绑定变更审计记录平台、外部ID哈希和目标工号，不记录密钥。

### 2.5 审计查询

`GET /admin/audit-events?request_id=&offset=0&limit=50`，request_id最长64，offset≥0，limit=1～200。返回 items/offset/limit，item 含 request_id/channel/action/app_id/employee_no/target/status_code/elapsed_ms/created_at。

`GET /admin/audit-logs?action=&employee_no=&limit=200&offset=0` 是旧业务审计查询，limit被限制到1～1000。两者不是相同数据集。JSONL是强制凭证，MySQL是查询副本，数据库副本可能缺记录；不能把空查询当作“从未发生”。

## 3. 嵌入式开放接口

所有以下端点都要求有效 `X-API-Key`，包括 health；可追加员工 JWT。成功均套第1节的信封。

| 方法 | 路径 | data |
|---|---|---|
| GET | `/gw/api/v1/embed/health` | `{"status":"alive"}`，不证明模型可用 |
| GET | `/gw/api/v1/embed/config` | app_name、features、visible_level_range、rate_limit_per_minute |
| POST | `/gw/api/v1/embed/chat` | answer、sources、message_id |
| GET | `/gw/api/v1/embed/documents` | 授权分页目录 |
| POST | `/gw/api/v1/embed/feedback` | `{"ok":true}` |

config 示例：

```json
{"app_name":"商户服务门户","features":{"chat":true,"history":false,"feedback":true},"visible_level_range":[0,1],"rate_limit_per_minute":60}
```

如果应用min大于当前员工max，区间可能倒置，表示无可读范围，不是自动提升员工权限。

Web Component：`kms/web/knowledge-widget.js`，元素 `<enterprise-knowledge>`，endpoint 必须同源，宿主设置异步或同步 tokenProvider。示例：

```html
<enterprise-knowledge endpoint="/api/chat"></enterprise-knowledge>
<script type="module">
  import '/widget.js';
  document.querySelector('enterprise-knowledge').tokenProvider = () => hostSessionToken();
</script>
```

`hostSessionToken()` 由宿主实现，不是本项目的SSO SDK。动态答案使用 textContent，不渲染模型 HTML。

可运行同源示例：`examples/embed_bff.py`，默认6343，只监听127.0.0.1。`POST /api/chat`要求Bearer、最多64KiB，服务端附加EMBED_API_KEY转发；本地错误为简单message，网关错误透传。BFF `/api/*`独立记录开始/完成审计，使用X-BFF-Request-ID关联下游X-Request-ID，审计不可写时503。`GET /`和`GET /widget.js`仅提供无秘密静态演示资源。

该示例仅演示问答转发，不包含反馈/文档代理、完整宿主SSO、生产代理限流和用户会话管理。使用 `python examples/embed_bff.py` 启动，不直接用 uvicorn 导入方式绕过初始化与端口校验。

## 4. 飞书自建机器人

`POST /gw/api/v1/bots/feishu/callback`。必须配置 App ID、App Secret、Verification Token、Encrypt Key。仅支持加密事件：

```json
{"encrypt":"<平台生成的Base64密文>"}
```

解密算法：SHA256派生AES256密钥，Base64解码后的前16字节为IV，其余为CBC/PKCS7密文。官方独立测试向量已加入回归，不再使用固定IV自回环证明兼容性。

- URL验证：解密后type=url_verification，验证token，返回 `{"challenge":"..."}`；不接受未加密验证请求。
- 消息事件：校验X-Lark-Request-Timestamp、X-Lark-Request-Nonce和X-Lark-Signature；签名为SHA256(timestamp+nonce+encrypt_key+原始请求体)，时间偏差≤300秒。
- 校验header.token、header.app_id；事件须为im.message.receive_v1。
- 仅员工sender_type=user、chat_type=p2p、message_type=text；文本≤500字符。
- 平台open_id绑定员工后事务入队，再返回 `{"code":0}`；后台主动私聊发送，不向群原消息引用回复。
- 非目标事件/非文本按协议ACK而不问答；未绑定/群聊403；签名错误401；配置缺失503。

配置步骤：创建企业自建应用 → 开启机器人 → 在平台申请实际所需收消息/以机器人发消息权限 → 填入批准的HTTPS回调 → 配置加密 → 订阅消息事件并发布到测试可见范围 → 管理员核实并绑定测试员工 → 做真实单聊及重投验收。权限名称随平台控制台版本变化，以官方页面为准。

官方协议来源：https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/encrypt-key-encryption-configuration-case

## 5. 企业微信自建应用

不是单向群机器人Webhook。必须配置CorpID、AgentID、Secret、Token、43字符EncodingAESKey。

| 方法 | 路径/参数 | 成功响应 |
|---|---|---|
| GET | `/gw/api/v1/bots/wecom/callback?msg_signature=&timestamp=&nonce=&echostr=` | 解密后的echostr纯文本 |
| POST | `/gw/api/v1/bots/wecom/callback?msg_signature=&timestamp=&nonce=` | `success`纯文本 |

参数限制：msg_signature≤64，timestamp≤20，nonce=1～128，echostr≤8192。POST正文是UTF-8 XML，含Encrypt字段。

验签SHA1(sort(token,timestamp,nonce,encrypt)) → 校验时间偏差≤300秒 → AES-CBC解密 → 校验receive_id → 校验XML的ToUserName及AgentID。拒绝DTD/实体声明、广播`@all`和管道分隔的多收件人；FromUserName只能是一个成员ID。text类型提取Content/MsgId并绑定员工，持久入队后ACK；其他类型不回答。

后台使用应用message/send私聊，safe标志和平台重复检查作为辅助，按UTF-8字节限长。端到端不保证exactly-once。

配置步骤：创建自建应用 → 限定测试可见范围 → 配置接收服务器URL、Token、EncodingAESKey → URL验证 → 配置平台要求的可信IP/发送权限 → 管理员绑定成员UserID → 测试单聊、错Corp/Agent、重复事件、员工停用。

## 6. 评测与就绪端点

- 6341：`POST /chat`，JSON `{"question":"..."}`，响应严格为 `{"answer":"..."}`。保留form-data和query兼容；无企业JWT，不提供企业知识。
- 6341：`GET /health`，原模型和索引摘要；`GET /readyz`，初始化就绪。
- 6342：`GET /readyz`，无需凭据，只返回service/ready；未就绪503。它不是外部应用授权或模型健康证明。
- 6342：`GET /`及`/static/*`提供静态工作台，无数据目录挂载。

平台可达性、HTTPS证书、真实企业身份、模型准入和数据库事务联调均需在甲方批准环境完成；本接口文档不把离线测试结果当作这些验收结果。
