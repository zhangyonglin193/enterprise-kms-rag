# 企业级知识管理平台（KMS + RAG）

面向企业文档治理的检索增强问答与知识管理系统。在赛题问答接口（`POST /chat`）的基础上，
扩展出一套完整的**受控知识管理链路**：文档入库 → 密级与权限判定 → 变更走工单 → 双人审批 →
全链路审计，检索侧复用同一套向量库与 Embedding/Reranker 能力。

> 一个进程内跑两个服务：`6341` 是对外的赛题问答接口（冻结面，不随业务演进而改），
> `6342` 是企业知识管理门户与网关（工单、权限、审计、MCP、机器人回调）。

## 核心能力

| 领域 | 能力 |
|---|---|
| 检索问答 | 混合检索（向量 + BM25 + RRF）、Query 改写、Reranker 精排、Embedding 缓存 |
| 文档治理 | 多格式解析（PDF/DOCX/XLSX/TXT）、OCR 编排、分块与入库、版本管理、批量导入 |
| 权限模型 | BLP 强制访问控制、文档密级 × 员工安全职级、部门可见范围、权限定向推荐 |
| 变更内控 | 两段式工单（申请 → 审批即执行）、同文档在途单唯一（业务悲观锁）、驳回与撤回 |
| 可信留痕 | 哈希链审计日志（WORM 语义）、站内通知、请求级日志关联 ID |
| 集成能力 | AppKey + 员工双层鉴权的企业网关、MCP 服务端、飞书/企业微信机器人回调、OIDC 单点登录 |
| 前端 | Vue 3 单页工作台（自托管构建产物，运行期零外链） |

## 架构分层

```
接入层    企业网关中间件 · 双层鉴权 · 限流 · 请求审计
路由层    FastAPI（kms/ · gateway/ · app/）
业务层    工单引擎 · 权限规则链 · 文档生命周期 · HR 同步 · 版本管理
领域层    BLP 强制访问控制 · 文档悲观锁 · 归档向量库 · 状态机
基础设施   MySQL 8 · FAISS · Embedding/LLM/Reranker · 本地文件系统
```

### 目录说明

```
app/         赛题问答内核（解析、切块、检索、生成），对外接口冻结
api.py       QA 服务路由（POST /chat、/health）
kms/         知识管理领域：权限、工单、版本、组织目录、OIDC、管理后台
gateway/     企业网关与 MCP 服务端：鉴权、审计、限流、文档在途锁
run_kms.py   KMS 服务入口（lifespan 内建表、回填、目录同步）
frontend/    Vue 3 前端工程源码（Vite 构建，产物输出到 kms/web/dist-app）
kms/web/     前端静态资源与已构建产物（服务端直接挂载）
scripts/     运维脚本：入库、备份、迁移、评测、健康检查、服务启动
tests/       离线回归测试（不依赖外部模型与数据库）
docs/        架构、接口、数据库设计与交付文档
```

## 快速开始

### 1. 环境

- Python **3.11**（3.10 ~ 3.12 可用）
- MySQL **8.0**（InnoDB / utf8mb4）
- Node.js **20+**（仅在需要重新构建前端时使用；仓库已包含构建产物）

### 2. 安装依赖

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
```

### 3. 准备配置

```powershell
Copy-Item .env.example      .env        # 问答服务配置
Copy-Item .env.kms.example  .env.kms    # 知识管理服务配置
```

两份配置都必须**指向不同的数据库与不同的数据目录**（`FAISS_INDEX_PATH` / `UPLOAD_DIR` /
`DOCS_DIR` 不得互相包含），否则启动器会拒绝启动。模型服务地址、数据库口令、平台密钥
一律只写在本地 `.env*` 文件里 —— 这两个文件已在 `.gitignore` 中。

### 4. 启动

```powershell
# 先做只读预检（绑定端口、校验配置，不连库）
.\venv\Scripts\python.exe scripts/service.py qa  --env .env --check
.\venv\Scripts\python.exe scripts/service.py kms --env .env.kms --qa-env .env --check

# 同时拉起两个服务
.\start_local.bat all
```

也可以只起其一：`.\start_local.bat qa` 或 `.\start_local.bat kms`。

启动完成后：

- 知识管理门户：<http://127.0.0.1:6342/>
- 问答接口：`POST http://127.0.0.1:6341/chat`，请求体 `{"question": "..."}`

Linux 下用法见 [DEPLOY.md](DEPLOY.md)。

### 5. 首次使用

空用户表可以启动但无法登录。创建第一个账号：

```powershell
.\venv\Scripts\python.exe scripts/bootstrap_employee.py --env .env.kms --qa-env .env `
  --employee-no E1001 --name 系统维护员 --department 商户服务部 --level 3 --approval-ref HR-TEST-001
```

密码在交互式提示中输入，不进命令行、不进日志。本系统没有「超级管理员」白名单：身份只有
「员工」与「运营审计」两类，删除、导入、改密级一律通过工单双人审批把关，审批人由
「同部门或上级 + 安全职级 ≥ 文档密级 + 排除申请人本人」的规则自动派单。

演示数据（虚构花名册，工号 `20260000` 起、密码与工单号规则见脚本头部注释）可通过
`KMS_DEMO_SEED=1` 在启动时幂等播种，仅用于本地演示，**切勿用于真实数据环境**。

## 前端二次开发

仓库内的 `kms/web/dist-app/` 是已构建的自包含产物（Vue 运行时已打进 `kms-app.js`），
服务端直接挂载该目录，所以**克隆后开箱即用**。修改 `frontend/src` 后需要重新构建：

```powershell
npm --prefix frontend ci
npm --prefix frontend run build:app
```

产物文件名不含哈希，改完务必对浏览器强制刷新（Ctrl+Shift+R）。

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
.\venv\Scripts\python.exe -m compileall -q app kms gateway scripts config.py
node --test tests/frontend/*.test.js     # 前端行为测试，零 npm 依赖
```

测试全部离线运行，不访问模型服务、不连数据库。CI 定义见
[.github/workflows/ci.yml](.github/workflows/ci.yml)，包含单元回归、ruff 检查、
前端构建、运行期外链守卫与 `app/` 冻结面守卫。

## 数据与合规说明

本仓库**只包含代码与文档**，不包含任何业务语料：

- `RAG_repository/`（监管文件、银行操作手册、财报等第三方与内部资料）、`test_file/`、
  `kms-test-cases/`、`data/`、`交付文档/` 均已在 `.gitignore` 中排除。
- 知识库需要自备语料，并按 `scripts/ingest_batch.py` 的入参格式批量入库。
- `scripts/seed_employees.py` 中的员工姓名、部门、职级均为**虚构演示数据**，工号与初始
  密码仅用于本地演示。
- 仓库不携带任何真实服务地址、数据库口令或平台密钥；`.env`、`.env.kms`、
  `deploy_prod.env` 与自动生成的 `kms_secret.key` 均不入库。
- 企业部署时请按下述默认策略保持收敛：模型出口默认关闭
  （`GW_MODEL_EGRESS_ALLOWED=0`）、KMS 仅监听本机（`KMS_HOST=127.0.0.1`）、
  单 worker 启动。

## 文档

| 文档 | 内容 |
|---|---|
| [DEPLOY.md](DEPLOY.md) | 端口与数据隔离红线、Windows/Linux 部署、迁移与回滚 |
| [docs/gateway_architecture.md](docs/gateway_architecture.md) | 企业网关分层与鉴权、审计设计 |
| [docs/gateway_api_reference.md](docs/gateway_api_reference.md) | 网关接口参考 |
| [docs/enterprise_delivery.md](docs/enterprise_delivery.md) | 交付清单、验收口径与运行保障 |
| [docs/database_design.md](docs/database_design.md) | 表结构、索引与工号/权限建模 |
| [docs/business_flow.md](docs/business_flow.md) | 工单流转、审批派单与变更执行流程 |
| [docs/frontend_architecture.md](docs/frontend_architecture.md) | 前端工程与构建约束 |
| [docs/mcp_engineering.md](docs/mcp_engineering.md) | MCP 服务端实现说明 |

## 许可

内部交付项目，未采用开源许可。未经授权不得复制、分发或用于商业用途。
