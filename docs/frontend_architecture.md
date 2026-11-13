# KMS 前端架构 — 工程说明文档

版本：2.0，2026-10-23。与 `gateway_architecture.md`、`mcp_engineering.md`、`../DEPLOY.md`
共同构成交付基线。
本版对应**前端整体迁移 Vue 架构完成**：经典脚本工作台（`app.js` + `js/app.js`
装配链）已退役删除，Vue 工作台成为唯一前端。

## 1. 定位与取舍

KMS 前端面向**金融内网单机受控部署**，核心红线是"**运行期零外链**"：
构建产物自包含，浏览器不请求任何公网资源。构建链（vite）只发生在开发/CI
环境，交付物是静态 bundle + 共享层源码。

| 维度 | 决策 | 理由 |
|---|---|---|
| 框架 | Vue 3（`<script setup>` 组合式 API） | 组件化 + 响应式；构建期把共享层打进产物，运行期零依赖 |
| 构建 | vite（`vite.app.config.js`）→ `kms/web/dist-app/` | 产物进发布包；源码 `frontend/` 也进包（可重建） |
| 状态管理 | `reactive` 单店（`src/app/store.js`），不用 Pinia | 当前规模不需要状态库；权限判定集中代理到 `policy.js` 纯函数 |
| 路由 | **不用 vue-router**：视图切换是纯状态切换（`state.view`） | 与既有行为一致（URL 不带状态）；内网零新依赖 |
| 共享层 | `kms/web/js/{core,sdk,ui}` 源码直用（`@kms` 别名） | 工作台构建期复用 + 嵌入组件运行期直用，**单一客户端**不漂移 |
| 样式 | 主站 `style.css` 全量复用 + 产物补少量类 | 亮/暗主题自动跟随；不复制主站类避免漂移 |
| Markdown | **自研最小安全渲染器**（`js/ui/md.js`） | 先转义后渲染；不依赖 CDN 版 marked |
| 测试 | Python 架构约束 + node 行为测试（CI） | 开发机无 node 运行时；行为测试在 CI 执行 |

## 2. 分层架构

```
frontend/                          Vue 源码（构建输入，进发布包）
├── package.json / vite.app.config.js / vite.config.js
└── src/app/
    ├── main.js                    createApp + mount('#kms-app-root')
    ├── App.vue                    外壳：登录/布局/顶栏/通知/轮询
    ├── api.js                     ★ AppClient extends KmsClient（工作台专有端点）
    ├── store.js                   reactive 全局态 + policy.js 派生（me.*）
    ├── components/                StateBox / DocDetailModal
    └── views/                     Dashboard/Documents/Chat/Knowledge/
                                   Personal/System/Tickets/Admin

kms/web/                           运行期资源（服务目录，进发布包）
├── index.html                     唯一入口：挂载 /static/dist-app/kms-app.js
├── style.css                      设计令牌 + 组件样式（两代前端共用）
├── knowledge-widget.js            嵌入式 Web Component（直接 import 共享层）
├── dist-app/                      Vue 构建产物（kms-app.js / kms-app.css）
├── dist/                          试点期产物（KnowledgeList，仅历史保留）
└── js/                            共享层源码
    ├── core/
    │   ├── dom.js                 $ / $$ / escapeHtml（widget 与 md.js 依赖，保留）
    │   ├── http.js                fetchJSON / 错误信封 / 令牌 / 同源硬约束 / SSE
    │   └── policy.js              BLP 权限纯函数（node --test 覆盖）
    ├── ui/
    │   └── md.js                  自包含 Markdown 安全渲染
    └── sdk/
        └── kms-client.js          ★ 知识服务客户端（复用中心）
```

依赖方向严格单向：`views → api/sdk → core`，`ui → core`。
Vue 源码经 `@kms` 别名（指向 `kms/web/js`）在**构建期**消费共享层；
`knowledge-widget.js` 在**运行期**直接 import 同一份源码。

## 3. 复用设计（本架构的核心目标）

### 3.1 单一客户端，三个消费方

| 消费方 | 入口 | 复用方式 |
|---|---|---|
| Vue 工作台 | `frontend/src/app/api.js`（`extends KmsClient`） | 构建期 `@kms` 别名 |
| 嵌入组件 | `knowledge-widget.js` | 运行期直接 import |
| MCP 控制台（规划） | — | 同上 |

**后端新增能力只需在 `sdk/kms-client.js` 加一个方法**（工作台专有端点在
`AppClient` 上扩展），消费方同时获得，零适配。该继承关系由
`tests/test_frontend_architecture.py::test_sdk_is_single_client_for_all_channels`
与 `tests/frontend/modules-load.test.js` 双重校验。

### 3.2 SDK 与后端能力一一对应

| SDK 方法 | REST 端点 | MCP 工具 |
|---|---|---|
| `ask` / `askStream` | `POST /kms/api/chat`（/stream） | `ask_question` |
| `search` | `POST /kms/api/search` | `search_knowledge` |
| `document` / `listDocuments` | `GET /kms/api/documents[/{id}]` | `get_document` / `list_documents` |
| `recommendations` | `GET /kms/api/recommendations` | `get_recommendations` |
| `feedback` | `POST /kms/api/feedback` | `submit_feedback` |
| `propose` / `decide` | `POST /kms/api/policy-requests/...` | `submit_knowledge_request`（decide 不暴露） |
| `mcpCall` / `mcpTools` / `mcpMetrics` | `POST/GET /gw/api/v1/mcp*` | 全量 |
| `appUsage` | 经 MCP | `get_app_usage` |

该对应关系由 `tests/test_frontend_architecture.py::SdkSurfaceTests` 自动校验——
MCP 新增工具而 SDK 未同步实现时测试失败，**复用契约不会静默腐烂**。

### 3.3 嵌入组件契约

```html
<script type="module" src="/static/knowledge-widget.js"></script>
<enterprise-knowledge endpoint="/kms/api/chat"></enterprise-knowledge>
<script type="module">
  document.querySelector('enterprise-knowledge').tokenProvider = () => window.__sessionJwt;
</script>
```

安全约定（`tests/test_frontend_architecture.py::SecurityConstraintTests` 强制）：
- 组件只持**短期员工令牌**，由宿主 SSO 会话经 `tokenProvider` 注入；
- **不接触应用 Key**（`X-API-Key` 必须由宿主 BFF 持有）；
- 仅同源 endpoint（`assertSameOrigin`），禁止把令牌转发到外部站点；
- 回答按不可信数据处理（安全 Markdown 渲染 + 明确提示不执行指令）。

## 4. 测试策略

| 层 | 内容 | 运行位置 | 依赖 |
|---|---|---|---|
| 架构约束 | 零外链 / 入口挂载 Vue 产物 / 源码树完整 / SDK 能力面 / 安全约束 / 打包完整 | 任意环境 | `tests/test_frontend_architecture.py`（纯 Python 静态检查） |
| 行为单元 | Markdown 渲染与 XSS / 权限辅助 / 错误信封 / SDK 请求构造 / 模块可加载 | CI | `tests/frontend/*.test.js`（`node --test`，零 npm 依赖） |
| 构建验证 | `npm run build:app` 产物落 `kms/web/dist-app/` 且自包含 | CI/开发机 | frontend 工程自身 |
| 手工 | 浏览器端到端（登录→问答→审批→通知） | 运维 | `DEPLOY.md` 验收清单 |

## 5. 工程规则（评审 checklist）

1. Vue 模板默认文本插值（`{{ }}`）自带转义；确实要拼 HTML 的场合先过安全渲染器；
2. 新网络调用一律扩展 `AppClient` / `kms-client.js`，禁止在视图里裸写 `fetch`
   （Bearer 鉴权与 401 统一处理会因此旁路）；
3. 禁止在 `kms/web` 下新增任何 `http(s)://` 运行期资源引用；
4. 权限显隐用 `store.me.*`（代理 `policy.js`），**真正判定永远在服务端**；
5. 视图根元素**不得挂 `view` 类**——主站 CSS 该类自带 `display:none`，
   App.vue 外层已包 `.view.active`，重复挂会整页空白（迁移期实际踩过）；
6. 新视图放 `frontend/src/app/views/`，在 `App.vue` 的 VIEWS/TITLES 注册；
7. 后端加能力 → 同步加 SDK 方法 → `SdkSurfaceTests` 自动校验。

## 6. 与既有工程实践的衔接

- 发布：`scripts/package_release.py` 白名单包含 `kms/web/**`（含 `dist-app/`
  产物）与 `frontend/**` 源码（排除 `node_modules`）——产物保运行、源码保重建；
- 入口：根路径 `/` 由 `run_kms.py` 返回 `kms/web/index.html`（Vue 挂载页），
  `/static` 服务 `kms/web` 目录，全部响应带 `Cache-Control: no-cache`；
- CI：`.github/workflows/ci.yml` 依次执行 ruff → Python 全量回归 → node 前端
  测试 → `app/`（QA 6341）冻结守卫 → 发布清单校验；
- 安全：前端不直连数据库/向量库，全部经 `/kms/api` 与 `/gw/api/v1`，
  与 MCP 同一治理层。

## 7. 已知限制

- 无前端端到端测试框架（Playwright 等），端到端仍靠手工验收；
- 无设计系统/组件库，UI 一致性依赖 `style.css` + Vue 侧少量补充类的人工约定；
- 可访问性（WCAG）与 i18n 未系统化处理——内网中文工具的可接受取舍；
- `kms/web/dist/`（试点期 KnowledgeList 产物）仅历史保留，不再演进。

## 8. 已知坑（都实际踩过，改前端前先读）

- **视图根元素挂 `view` 类 → 整页空白**：主站 CSS 的 `.view` 自带
  `display:none`，与 `.active` 的 `display:block` 在同一元素上冲突
  （如 `.chat-layout` 的 grid 会被覆盖塌成一栏）。视图根元素一律裸 `<div>`。
- **reactive 数组里的对象要用代理引用改**：`push(rawObj)` 后从数组里
  重新取出的才是响应式代理，直接改裸引用不触发视图更新（上传进度队列踩过）。
- **`node --test <目录>` 不可用**：Node 22 会把目录当模块加载并报
  `MODULE_NOT_FOUND`，必须写成 glob（见 CI 前端测试步骤注释）。
- **Node 无 `location` 全局**：`core/http.js` 的 `assertSameOrigin` 用
  `location.origin`，Node 里跑测试必须先 stub（见 `tests/frontend/*.test.js` 顶部）。
- **本机 node 不在 PATH**：可用
  `%USERPROFILE%\.workbuddy\binaries\node\versions\<ver>\node.exe` 直接调用。
- **上传接口 Form 形参序**：`Request` 对象必须放在所有 `File/Form` 参数之前，
  否则干扰 FastAPI 依赖注入导致 401（后端侧约束，前端无感但排查耗时）。
