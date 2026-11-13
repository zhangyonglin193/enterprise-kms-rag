# 银联商务 RAG 知识管理系统 — 项目详细说明文档

**版本**: 1.0  
**日期**: 2026-10-20  
**项目路径**: `d:\Desktop\银联商务code\rag_project_local`

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [目录结构](#3-目录结构)
4. [模块详解](#4-模块详解)
5. [数据库设计](#5-数据库设计)
6. [文件引用关系](#6-文件引用关系)
7. [函数统计](#7-函数统计)
8. [部署说明](#8-部署说明)

---

## 1. 项目概述

### 1.1 项目定位

本项目是**银联商务 RAG 知识管理系统**，服务于两个核心场景：
- **QA 服务**（竞赛评测）：赛题问答，无员工认证，仅装载竞赛公开资料
- **KMS 服务**（企业知识管理）：企业级权限体系、文档审批、API 网关

### 1.2 技术栈

| 层级 | 技术选型 |
|------|----------|
| 语言 | Python 3.11 |
| Web 框架 | FastAPI + Uvicorn |
| 向量检索 | FAISS (IndexIDMap2 + IndexFlatIP) |
| 关键词检索 | BM25 (rank_bm25) |
| 关系数据库 | MySQL 8.0 (InnoDB, utf8mb4) |
| 状态存储 | SQLite (网关状态) |
| 嵌入模型 | BAAI/bge-m3 (1024 维) |
| LLM | Qwen/Qwen3-32B (QA) / DeepSeek-V4-Flash (KMS) |
| 重排模型 | BAAI/bge-reranker-v2-m3 |
| OCR | PaddleOCR-VL-1.5 |
| 前端 | 原生 HTML/CSS/JS + Vite 构建 |

### 1.3 核心特性

- **BLP 强制访问控制**：不上读（读权限 ≤ 职级）、不下写（写权限 ≥ 职级）
- **双人审批机制**：文档上传/更新/删除均需工单审批
- **会话严格绑定**：单会话模式，新登录使旧会话失效
- **审计留痕**：所有操作记录审计日志
- **数据隔离**：QA/KMS 使用不同数据库、不同 FAISS 索引、不同数据目录

---

## 2. 整体架构

### 2.1 服务架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         客户端层                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ 评测系统      │  │ 员工浏览器    │  │ 飞书/企微机器人       │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
└─────────┼─────────────────┼─────────────────────┼───────────────┘
          │                 │                     │
          ▼                 ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                         服务层                                    │
│  ┌──────────────────┐           ┌──────────────────────────┐    │
│  │   QA 服务        │           │   KMS 服务               │    │
│  │   port: 6341     │           │   port: 6342             │    │
│  │   无认证          │           │   JWT 认证               │    │
│  │   /chat 接口      │           │   /kms/api/* 接口        │    │
│  └────────┬─────────┘           └────────────┬─────────────┘    │
└───────────┼──────────────────────────────────┼──────────────────┘
            │                                  │
            ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         核心层                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  app/ (共享 RAG 引擎)                                      │   │
│  │  - Retriever: 检索器 (FAISS + BM25 + Reranker)            │   │
│  │  - Indexer: 索引器 (文档分块 + 向量化)                      │   │
│  │  - LLMClient: 大模型客户端                                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
            │                                  │
            ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         数据层                                    │
│  ┌──────────────────┐           ┌──────────────────────────┐    │
│  │ MySQL            │           │ MySQL                    │    │
│  │ rag_competition  │           │ enterprise_kms           │    │
│  │ (QA 专用)        │           │ (KMS 专用)               │    │
│  └──────────────────┘           └──────────────────────────┘    │
│  ┌──────────────────┐           ┌──────────────────────────┐    │
│  │ FAISS            │           │ FAISS                    │    │
│  │ data/faiss/      │           │ data/kms/faiss/          │    │
│  └──────────────────┘           └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块边界

| 模块 | 路径 | 职责 | 安全级别 |
|------|------|------|----------|
| QA 问答 | `app/` + `api.py` | 赛题 `/chat` 接口 | 低（公开评测） |
| KMS 核心 | `kms/` | 权限、用户、组织、推荐 | 高（企业数据） |
| API 网关 | `gateway/` | 飞书/企微机器人、嵌入 API、审计 | 高（对外入口） |
| 配置 | `config.py` | 全局配置 + 端口/安全校验 | 关键 |
| 启动器 | `scripts/service.py` | 跨平台受控启动，端口冲突即退出 | 关键 |
| 测试 | `tests/` | 离线安全回归，不连接真实 DB/模型 | — |

---

## 3. 目录结构

```
rag_project_local/
├── app/                    # QA 核心（共享 RAG 引擎）
│   ├── __init__.py         # 模块导出
│   ├── api.py              # FastAPI 路由（/chat, /health）
│   ├── clients.py          # 模型客户端（Embedding/LLM/Reranker/OCR）
│   ├── document.py         # 文档加载与分块（PDF/DOCX/OCR）
│   ├── logger.py           # 日志配置
│   ├── main.py             # QA 服务入口（lifespan）
│   ├── rag.py              # RAG 核心（Retriever/Indexer）
│   ├── store.py            # 存储层（MySQL + FAISS）
│   └── typo_clean.py       # OCR 错别字清洗
│
├── kms/                    # KMS 核心（权限/安全/ACL）
│   ├── __init__.py         # 模块导出
│   ├── access_control.py   # BLP 权限表 + 角色管理
│   ├── admin_routes.py     # 管理路由（登录/用户/审计）
│   ├── apps.py             # 应用管理（API Key）
│   ├── constants.py        # 常量定义（密级/角色/HR）
│   ├── directory.py        # 组织目录同步
│   ├── formats.py          # 格式化工具
│   ├── hr_sync.py          # HR 系统同步
│   ├── lifecycle.py        # 文档生命周期
│   ├── oidc.py             # OIDC 单点登录
│   ├── oidc_provider.py    # OIDC Provider
│   ├── org.py              # 组织架构
│   ├── pagination.py       # 分页工具
│   ├── ratelimit.py        # 速率限制
│   ├── recommend.py        # 推荐系统
│   ├── routes.py           # KMS 路由
│   ├── security.py         # JWT + 密码 + 会话管理
│   ├── versioning.py       # 文档版本管理
│   └── web/                # 前端资源
│       ├── index.html      # 主页面
│       ├── app.js          # 前端逻辑（2831 行）
│       ├── style.css       # 样式（1902 行）
│       ├── js/             # 模块化 JS
│       │   ├── core/       # 核心模块（dom/http/policy）
│       │   ├── sdk/        # SDK（kms-client）
│       │   └── ui/         # UI 组件（md/ui-kit）
│       └── dist/           # Vite 构建产物
│
├── gateway/                # API 网关
│   ├── __init__.py         # 模块导出
│   ├── audit.py            # 审计日志
│   ├── clients.py          # 网关客户端
│   ├── crypto.py           # 飞书/企微加解密
│   ├── identity.py         # 身份解析
│   ├── logctx.py           # 日志上下文
│   ├── middleware.py       # 中间件（限流/认证/审计）
│   ├── routes_bots.py      # 机器人路由（飞书/企微）
│   ├── routes_embed.py     # 嵌入 API 路由
│   ├── routes_kms.py       # KMS 核心路由（967 行）
│   ├── routes_knowledge.py # 知识中心路由
│   ├── routes_tickets.py   # 工单路由（1259 行）
│   ├── routes_upload.py    # 上传路由
│   ├── service.py          # 网关服务层
│   ├── state.py            # 网关状态（SQLite）
│   └── mcp/                # MCP 协议支持
│       ├── auth.py         # MCP 认证
│       ├── guard.py        # MCP 守卫
│       ├── protocol.py     # MCP 协议
│       ├── resources.py    # MCP 资源
│       ├── schemas.py      # MCP Schema
│       ├── server.py       # MCP 服务器
│       └── tools.py        # MCP 工具
│
├── scripts/                # 工具脚本
│   ├── service.py          # 跨平台启动器（关键）
│   ├── ingest_batch.py     # 批量入库
│   ├── reingest_all.py     # 全量重灌
│   ├── bootstrap_employee.py # 员工初始化
│   ├── seed_employees.py   # 演示账号播种
│   ├── package_release.py  # 打包发布
│   ├── eval_accuracy.py    # 准确率评测
│   ├── verify_live.py      # 线上验证
│   └── ...                 # 其他运维脚本
│
├── tests/                  # 测试（301 项）
│   ├── test_enterprise.py  # 企业级安全测试
│   ├── test_access_control.py # 权限测试
│   ├── test_tickets.py     # 工单测试
│   ├── test_ratelimit.py   # 限流测试
│   ├── test_versioning.py  # 版本测试
│   └── ...                 # 其他测试
│
├── data/                   # 数据目录
│   ├── faiss/              # QA FAISS 索引
│   ├── kms/                # KMS 数据（faiss/uploads/docs/audit）
│   ├── uploads/            # QA 上传目录
│   ├── docs/               # QA 文档目录
│   └── .ocr_cache/         # OCR 缓存
│
├── frontend/               # 前端构建配置
│   ├── src/                # 源码
│   └── vite.config.js      # Vite 配置
│
├── docs/                   # 文档
│   ├── architecture.md     # 架构设计
│   ├── database_design.md  # 数据库设计
│   ├── business_flow.md    # 业务流程
│   └── ...                 # 其他文档
│
├── config.py               # 全局配置（240 行）
├── api.py                  # QA 服务入口（125 行）
├── run_kms.py              # KMS 服务入口（338 行）
├── requirements.txt        # Python 依赖
├── .env                    # QA 环境配置
├── .env.kms                # KMS 环境配置
├── DEPLOY.md               # 部署手册
├── AGENTS.md               # AI 代理路由指南
└── start_local.bat         # Windows 启动脚本
```

---

## 4. 模块详解

### 4.1 app/ 模块（QA 核心，168 个函数）

#### 4.1.1 app/api.py（125 行，4 个函数）

| 函数 | 作用 |
|------|------|
| `get_indexer()` | 获取全局 Indexer 单例 |
| `get_retriever()` | 获取全局 Retriever 单例（含预热） |
| `health()` | 健康检查接口 |
| `chat(request)` | 赛题问答接口（兼容 JSON/form/query） |

**关键特性**：
- 支持三种请求格式：JSON body / form-data / query param
- async 路由 + threadpool，不阻塞事件循环
- 单次请求链路：embed(query) → FAISS search → chunk_cache hit → rerank → LLM

#### 4.1.2 app/rag.py（1602 行，核心 RAG 引擎）

**主要类**：
- `Retriever`: 检索器（FAISS + BM25 + Reranker）
- `Indexer`: 索引器（文档分块 + 向量化）

**关键函数**：
| 函数 | 作用 |
|------|------|
| `_chunk_is_garbage(text)` | 块级垃圾检测（7 签名） |
| `Retriever.answer(question)` | 非流式问答 |
| `Retriever.answer_stream(question)` | 流式问答（SSE） |
| `Retriever.retrieve(question)` | 混合检索（向量 + BM25） |
| `Retriever.rerank(question, chunks)` | 重排序 |
| `Indexer.ingest(file_path)` | 文档入库 |
| `Indexer.chunk_text(text)` | 文本分块 |

#### 4.1.3 app/store.py（475 行，存储层）

**主要类**：
- `MySQLStore`: MySQL 存储（文档/分块/历史）
- `VectorStore`: FAISS 向量存储

**MySQLStore 方法**：
| 方法 | 作用 |
|------|------|
| `_get_pool()` | 延迟初始化连接池（DBUtils PooledDB） |
| `_conn()` | 上下文管理器，获取连接 |
| `transaction()` | 事务上下文管理器 |
| `insert_document()` | 插入文档记录 |
| `insert_chunks()` | 批量插入分块 |
| `get_chunk_by_faiss_id()` | 按 faiss_id 查询分块 |

**VectorStore 方法**：
| 方法 | 作用 |
|------|------|
| `add(vectors)` | 添加向量 |
| `search(query, k)` | 向量检索 |
| `remove(ids)` | 删除向量 |
| `save()` | 保存索引到磁盘 |
| `load()` | 从磁盘加载索引 |
| `ids()` | 获取所有向量 ID |

#### 4.1.4 app/document.py（1652 行，文档处理）

**主要功能**：
- PDF 解析（pdfplumber + pypdfium2）
- DOCX 解析（python-docx）
- OCR 处理（PaddleOCR-VL-1.5）
- 文本清洗与去重

**关键函数**：
| 函数 | 作用 |
|------|------|
| `_extract_page_text_colwise(page)` | 多栏 PDF 提取 |
| `_merge_text_and_ocr(pdf_text, ocr_text)` | 文本层与 OCR 合并 |
| `_postprocess_ocr_text(text)` | OCR 后处理 |
| `_clean_layout_tokens(text)` | 清理布局 token |
| `_compress_repeated_text(text)` | 压缩重复文本 |
| `_ocr_vs_pdfplumber_similar(ocr, pdf)` | OCR 与文本层相似度比较 |

#### 4.1.5 app/clients.py（433 行，模型客户端）

**主要类**：
- `EmbeddingClient`: 嵌入模型客户端（含磁盘缓存）
- `LLMClient`: 大模型客户端
- `RerankerClient`: 重排模型客户端
- `OCRClient`: OCR 客户端

**关键方法**：
| 方法 | 作用 |
|------|------|
| `EmbeddingClient.embed(texts)` | 批量嵌入（含缓存） |
| `LLMClient.chat(messages)` | 非流式对话 |
| `LLMClient.chat_stream(messages)` | 流式对话 |
| `RerankerClient.rerank(query, docs)` | 重排序 |
| `OCRClient.recognize(image)` | OCR 识别 |

---

### 4.2 kms/ 模块（KMS 核心，219 个函数）

#### 4.2.1 kms/security.py（623 行，安全模块）

**主要功能**：
- 密码哈希（PBKDF2-HMAC-SHA256）
- JWT 签发与验证（HS256）
- 会话管理（严格绑定人员）
- 登录失败限速

**关键函数**：
| 函数 | 作用 |
|------|------|
| `hash_password(password)` | PBKDF2 密码哈希 |
| `verify_password(password, stored)` | 恒定时间密码校验 |
| `create_token(user_id, employee_no, level, dept)` | 签发 JWT |
| `decode_token(token)` | 校验 JWT（含会话验证） |
| `revalidate_bearer(request, user)` | 长请求二次核验 |
| `login_locked(employee_no)` | 检查登录锁定状态 |
| `record_login_failure(employee_no)` | 记录登录失败 |
| `clear_login_failures(employee_no)` | 清除失败记录 |

#### 4.2.2 kms/access_control.py（855 行，权限控制）

**主要功能**：
- BLP 强制访问控制
- 角色管理（员工/管理员/审计员）
- 审批人候选池派生
- 文档权限判定

**关键函数**：
| 函数 | 作用 |
|------|------|
| `can_read_document(user, doc)` | BLP 不上读判定 |
| `can_write_document(user, level)` | BLP 不下写判定 |
| `can_approve_document(user, level, dept)` | 审批权限判定 |
| `approver_candidates(level, dept, exclude_user_id)` | 审批人候选池 |
| `add_audit(user, action, target, detail)` | 添加审计日志 |
| `get_user_by_id(user_id)` | 按 ID 查询用户 |
| `get_user_by_employee_no(emp_no)` | 按工号查询用户 |
| `list_users()` | 列出所有用户 |

#### 4.2.3 kms/admin_routes.py（589 行，管理路由）

**主要端点**：
| 端点 | 方法 | 作用 |
|------|------|------|
| `/auth/login` | POST | 员工登录 |
| `/auth/logout` | POST | 员工登出 |
| `/auth/me` | GET | 获取当前用户信息 |
| `/auth/change-password` | POST | 修改密码 |
| `/admin/users` | GET | 用户列表（只读） |
| `/admin/levels` | GET | 安全职级列表 |
| `/admin/departments` | GET | 部门列表 |
| `/audit/audit-logs` | GET | 审计日志查询 |

#### 4.2.4 kms/hr_sync.py（423 行，HR 同步）

**主要功能**：
- 从 HR 系统同步员工数据
- 组织架构同步
- 涉密资格校验

**关键函数**：
| 函数 | 作用 |
|------|------|
| `sync_employees()` | 同步员工数据 |
| `sync_org_structure()` | 同步组织架构 |
| `check_security_clearance(user)` | 校验涉密资格 |

---

### 4.3 gateway/ 模块（API 网关，238 个函数）

#### 4.3.1 gateway/middleware.py（136 行，中间件）

**主要功能**：
- 请求限流
- JWT 认证
- 审计日志
- 请求体大小限制

**关键类**：
- `EnterpriseBoundary`: 企业边界中间件

**处理流程**：
```
请求 → 限流检查 → JWT 认证 → 请求体大小检查 → 业务处理 → 审计日志 → 响应
```

#### 4.3.2 gateway/routes_kms.py（967 行，KMS 路由）

**主要端点**：
| 端点 | 方法 | 作用 |
|------|------|------|
| `/chat` | POST | 员工问答（支持流式） |
| `/documents` | GET | 文档列表 |
| `/documents/{id}` | GET | 文档详情 |
| `/documents/{id}/download` | GET | 文档下载 |
| `/documents/approver-candidates` | GET | 审批人候选 |
| `/admin/apps` | POST | 创建应用 |
| `/admin/apps/{id}` | PUT | 更新应用 |

#### 4.3.3 gateway/routes_tickets.py（1259 行，工单路由）

**主要端点**：
| 端点 | 方法 | 作用 |
|------|------|------|
| `/tickets` | POST | 创建工单 |
| `/tickets/mine` | GET | 我的工单 |
| `/tickets/pending-approval` | GET | 待审批工单 |
| `/tickets/{id}/approve` | POST | 审批通过 |
| `/tickets/{id}/reject` | POST | 审批拒绝 |

**工单模块**：
- `doc_batch_delete`: 批量删除文档
- `user_duty_grant`: 员工赋权
- `user_duty_revoke`: 员工撤权
- `escalation_request`: 临时提权申请

#### 4.3.4 gateway/state.py（203 行，网关状态）

**主要功能**：
- SQLite 状态存储
- 令牌撤销表
- 会话管理表
- 任务队列

**关键表**：
| 表名 | 作用 |
|------|------|
| `jobs` | 任务队列 |
| `receipts` | 消息回执 |
| `revoked_tokens` | 撤销的令牌 |
| `user_revocations` | 用户级撤销 |
| `sessions` | 会话管理（严格绑定人员） |

**会话管理函数**：
| 函数 | 作用 |
|------|------|
| `create_session(user_id, employee_no, jti, expires_at)` | 创建会话（使旧会话失效） |
| `validate_session(jti)` | 验证会话是否活跃 |
| `revoke_session(jti)` | 撤销指定会话 |
| `revoke_all_user_sessions(user_id)` | 撤销用户所有会话 |
| `get_active_sessions(user_id)` | 获取用户活跃会话 |

---

### 4.4 scripts/ 模块（工具脚本，117 个函数）

#### 4.4.1 scripts/service.py（189 行，启动器）

**主要功能**：
- 跨平台受控启动
- 端口冲突检测
- 数据隔离校验
- 环境变量加载

**关键函数**：
| 函数 | 作用 |
|------|------|
| `apply_environment(env_file, overrides)` | 加载环境变量 |
| `bind_socket(host, port)` | 绑定端口（冲突即退出） |
| `deployment_values(qa_env, kms_env)` | 校验部署隔离 |
| `start_service(role, env_file)` | 启动服务 |

#### 4.4.2 scripts/ingest_batch.py（109 行，批量入库）

**主要功能**：
- 批量文档入库
- 断点续传（content_hash 去重）
- 进度报告

#### 4.4.3 scripts/bootstrap_employee.py（69 行，员工初始化）

**主要功能**：
- 交互式创建员工
- 密码安全输入（不回显）
- 审批编号记录

---

## 5. 数据库设计

### 5.1 数据库概览

| 数据库 | 用途 | 表数量 |
|--------|------|--------|
| `rag_competition` | QA 服务（竞赛评测） | 21 张 |
| `enterprise_kms` | KMS 服务（企业知识管理） | 22 张 |

### 5.2 QA 数据库表（rag_competition）

#### 5.2.1 核心业务表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `documents` | 文档元数据 | id, filename, source_path, file_type, content_hash, chunk_count, title |
| `chunks` | 文档分块 | id, document_id, chunk_index, text, faiss_id, page, section |
| `chat_history` | 问答历史 | id, session_id, question, answer, sources |
| `chat_feedback` | 问答反馈 | id, message_id, rating, comment |

#### 5.2.2 KMS 历史遗留表（17 张）

这些表是历史误操作写入 QA 库的残留，当前 KMS 不依赖它们：

| 表名 | 原用途 |
|------|--------|
| `kms_users` | 用户表 |
| `kms_doc_levels` | 文档密级表 |
| `kms_audit_logs` | 审计日志表 |
| `kms_tickets` | 工单表 |
| `kms_notifications` | 通知表 |
| `kms_user_duties` | 用户职责表 |
| `kms_upload_batches` | 上传批次表 |
| `kms_upload_batch_items` | 上传批次项表 |
| `kms_apps` | 应用表 |
| `kms_chat_owners` | 会话归属表 |
| `kms_gw_audit` | 网关审计表 |
| `kms_gw_bot_bindings` | 机器人绑定表 |
| `kms_hr_sync_logs` | HR 同步日志表 |
| `kms_metric_counters` | 指标计数表 |
| `kms_org_nodes` | 组织节点表 |
| `kms_rate_buckets` | 限流桶表 |
| `kms_rec_interactions` | 推荐交互表 |

### 5.3 KMS 数据库表（enterprise_kms）

#### 5.3.1 核心业务表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `documents` | 文档元数据 | id, filename, source_path, file_type, content_hash, chunk_count, title |
| `chunks` | 文档分块 | id, document_id, chunk_index, text, faiss_id, page, section |
| `chat_history` | 问答历史 | id, session_id, question, answer, sources |
| `kms_doc_versions` | 文档版本 | id, document_id, version_no, text, created_at |

#### 5.3.2 权限与安全表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `kms_users` | 用户表 | id, employee_no, username, password_hash, security_level, department, is_active |
| `kms_doc_levels` | 文档密级表 | document_id, level, granted_by, granted_at |
| `kms_user_duties` | 用户职责表 | id, user_id, duty, granted_by, granted_at |
| `kms_audit_logs` | 审计日志表 | id, user_id, employee_no, action, target, detail, ip, created_at |

#### 5.3.3 工单与审批表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `kms_tickets` | 工单表 | id, ticket_no, module, payload, status, applicant_id, approver_id |
| `kms_notifications` | 通知表 | id, user_id, ticket_id, type, content, is_read |
| `kms_policy_requests` | 策略请求表 | id, document_id, requested_level, reason, status |

#### 5.3.4 上传与批次表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `kms_upload_batches` | 上传批次表 | id, user_id, department, status, created_at |
| `kms_upload_batch_items` | 上传批次项表 | id, batch_id, seq, filename, status, message |

#### 5.3.5 组织与 HR 表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `kms_org_nodes` | 组织节点表 | id, node_id, parent_id, name, node_type, path |
| `kms_hr_sync_logs` | HR 同步日志表 | id, sync_time, source, employee_count, status |

#### 5.3.6 网关与应用表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `kms_apps` | 应用表 | id, app_id, app_name, api_key_hash, allowed_min_level, allowed_max_level |
| `kms_gw_audit` | 网关审计表 | id, channel, event_type, request_id, employee_no, created_at |
| `kms_gw_bot_bindings` | 机器人绑定表 | id, channel, external_id, user_id, created_at |
| `kms_chat_owners` | 会话归属表 | session_id, user_id, created_at |

#### 5.3.7 限流与指标表

| 表名 | 作用 | 关键字段 |
|------|------|----------|
| `kms_rate_buckets` | 限流桶表 | id, bucket_key, count, window_start |
| `kms_metric_counters` | 指标计数表 | id, metric_name, value, updated_at |
| `kms_rec_interactions` | 推荐交互表 | id, user_id, document_id, interaction_type, created_at |

### 5.4 表关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                         文档域                                    │
│  ┌──────────────┐       ┌──────────────┐       ┌─────────────┐ │
│  │  documents   │◄──────│    chunks    │       │kms_doc_levels│ │
│  │  (文档元数据) │  1:N  │  (文档分块)   │       │ (文档密级)   │ │
│  └──────┬───────┘       └──────────────┘       └──────┬──────┘ │
│         │                                             │         │
│         │ 1:N                                         │ 1:1     │
│         ▼                                             ▼         │
│  ┌──────────────┐                            ┌─────────────┐   │
│  │kms_doc_versions│                          │  documents  │   │
│  │  (文档版本)    │                            │  (关联)     │   │
│  └──────────────┘                            └─────────────┘   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         用户域                                    │
│  ┌──────────────┐       ┌──────────────┐       ┌─────────────┐ │
│  │  kms_users   │◄──────│kms_user_duties│      │kms_chat_owners│
│  │  (用户表)     │  1:N  │  (用户职责)   │       │ (会话归属)   │ │
│  └──────┬───────┘       └──────────────┘       └─────────────┘ │
│         │                                                       │
│         │ 1:N                                                   │
│         ▼                                                       │
│  ┌──────────────┐       ┌──────────────┐                       │
│  │kms_audit_logs│       │kms_notifications│                    │
│  │  (审计日志)   │       │  (通知)       │                       │
│  └──────────────┘       └──────────────┘                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         工单域                                    │
│  ┌──────────────┐       ┌──────────────┐                       │
│  │  kms_tickets │◄──────│kms_notifications│                    │
│  │  (工单表)     │  1:N  │  (通知)       │                       │
│  └──────┬───────┘       └──────────────┘                       │
│         │                                                       │
│         │ N:1                                                   │
│         ▼                                                       │
│  ┌──────────────┐                                               │
│  │  kms_users   │                                               │
│  │  (申请人/审批人)│                                            │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         上传域                                    │
│  ┌──────────────┐       ┌──────────────────┐                   │
│  │kms_upload_batches│◄──│kms_upload_batch_items│                │
│  │  (上传批次)    │  1:N │  (批次项)         │                   │
│  └──────┬───────┘       └──────────────────┘                   │
│         │                                                       │
│         │ N:1                                                   │
│         ▼                                                       │
│  ┌──────────────┐                                               │
│  │  kms_users   │                                               │
│  │  (上传人)     │                                               │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 文件引用关系

### 6.1 核心依赖图

```
config.py (全局配置)
    ▲
    │
    ├──► app/store.py (存储层)
    │       ▲
    │       │
    │       ├──► app/rag.py (RAG 引擎)
    │       │       ▲
    │       │       │
    │       │       ├──► app/api.py (QA 路由)
    │       │       │       ▲
    │       │       │       │
    │       │       │       └──► api.py (QA 入口)
    │       │       │
    │       │       └──► gateway/service.py (网关服务)
    │       │               ▲
    │       │               │
    │       │               ├──► gateway/routes_kms.py (KMS 路由)
    │       │               ├──► gateway/routes_tickets.py (工单路由)
    │       │               └──► gateway/routes_upload.py (上传路由)
    │       │
    │       └──► kms/access_control.py (权限控制)
    │               ▲
    │               │
    │               ├──► kms/admin_routes.py (管理路由)
    │               ├──► kms/security.py (安全模块)
    │               └──► gateway/routes_kms.py (KMS 路由)
    │
    └──► run_kms.py (KMS 入口)
            ▲
            │
            └──► scripts/service.py (启动器)
```

### 6.2 模块间引用

| 源模块 | 目标模块 | 引用内容 |
|--------|----------|----------|
| `app/api.py` | `app/rag.py` | Retriever, Indexer |
| `app/api.py` | `app/store.py` | MySQLStore, VectorStore |
| `app/rag.py` | `app/clients.py` | EmbeddingClient, LLMClient, RerankerClient |
| `app/rag.py` | `app/document.py` | 文档解析函数 |
| `app/rag.py` | `app/store.py` | MySQLStore, VectorStore |
| `gateway/routes_kms.py` | `gateway/service.py` | answer, answer_stream |
| `gateway/routes_kms.py` | `kms/access_control.py` | ACL 函数 |
| `gateway/routes_kms.py` | `kms/security.py` | AuthUser, require_user |
| `gateway/routes_tickets.py` | `kms/access_control.py` | approver_candidates |
| `gateway/middleware.py` | `kms/security.py` | decode_token |
| `gateway/middleware.py` | `gateway/state.py` | token_allowed, validate_session |
| `kms/admin_routes.py` | `kms/security.py` | create_token, verify_password |
| `kms/admin_routes.py` | `kms/access_control.py` | get_user_by_employee_no |
| `kms/admin_routes.py` | `gateway/state.py` | create_session, revoke_session |
| `run_kms.py` | `gateway/routes_kms.py` | router |
| `run_kms.py` | `kms/admin_routes.py` | router |
| `run_kms.py` | `gateway/middleware.py` | EnterpriseBoundary |

---

## 7. 函数统计

### 7.1 按模块统计（实测数据，统计口径：`def`/`async def` 顶层与嵌套函数）

| 模块 | 文件数 | 函数数 | 代码行数 | 说明 |
|------|--------|--------|----------|------|
| `app/` | 9 | 168 | 3,725 | QA 共享 RAG 引擎 |
| `kms/` | 18 | 219 | 4,746 | KMS 核心（含前端目录不含 .js） |
| `gateway/` | 23 | 238 | 4,724 | API 网关（含 mcp/ 子模块） |
| `scripts/` | 28 | 117 | 3,770 | 运维/入库/评测脚本 |
| `tests/` | 21 | 364 | 3,160 | 离线安全回归测试 |
| `data/` | 47 | 16 | 1,811 | 数据目录内嵌工具脚本 |
| 根目录 | 6 | 42 | 1,150 | `config.py`/`api.py`/`run_kms.py` 等入口 |
| **总计** | **152** | **1,164** | **23,086** | 仅统计 `.py` 文件，不含 `venv/`、`__pycache__/`、前端 `.js` |

### 7.2 关键文件函数数

| 文件 | 函数数 | 主要功能 |
|------|--------|----------|
| `app/rag.py` | ~40 | RAG 核心引擎 |
| `app/document.py` | ~35 | 文档处理 |
| `app/store.py` | ~25 | 存储层 |
| `kms/access_control.py` | ~50 | 权限控制 |
| `kms/security.py` | ~30 | 安全模块 |
| `gateway/routes_kms.py` | ~45 | KMS 路由 |
| `gateway/routes_tickets.py` | ~55 | 工单路由 |
| `gateway/middleware.py` | ~10 | 中间件 |
| `scripts/service.py` | ~15 | 启动器 |

---

## 8. 部署说明

### 8.1 端口规则

| 服务 | 端口 | 用途 |
|------|------|------|
| QA | 6341 | 赛题问答（唯一对外暴露） |
| KMS | 6342 | 员工门户、治理、回调 |
| 嵌入 BFF | 6343 | 可选示例 |

### 8.2 数据隔离

- QA/KMS 必须使用**不同数据库**
- QA/KMS 必须使用**不同 FAISS 索引**
- QA/KMS 必须使用**不同上传/文档目录**
- 路径不得相互包含（父子关系也不允许）

### 8.3 启动命令

```bash
# Windows
start_local.bat all

# Linux
bash start.sh all

# 预检
python scripts/service.py qa --env .env --check
python scripts/service.py kms --env .env.kms --qa-env .env --check
```

### 8.4 配置文件

| 文件 | 用途 |
|------|------|
| `.env` | QA 服务配置 |
| `.env.kms` | KMS 服务配置 |
| `config.py` | 全局配置加载 |

---

## 附录

### A. 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYSQL_HOST` | 127.0.0.1 | MySQL 主机 |
| `MYSQL_PORT` | 3306 | MySQL 端口 |
| `MYSQL_DATABASE` | - | 数据库名 |
| `FAISS_INDEX_PATH` | data/faiss/index | FAISS 索引路径 |
| `MODEL_API_BASE` | - | 模型 API 地址 |
| `MODEL_API_KEY` | - | 模型 API 密钥 |
| `TOP_K_RETRIEVE` | 30 | 检索 top K |
| `MAX_CONTEXT_CHARS` | 4000 | 上下文最大字符数 |
| `LLM_MAX_TOKENS` | 1024 | LLM 最大生成 token |
| `GW_MODEL_EGRESS_ALLOWED` | 0 | 模型出域开关 |
| `KMS_DEMO_SEED` | 0 | 演示账号开关 |

### B. 测试覆盖

| 测试类型 | 数量 | 说明 |
|----------|------|------|
| 单元测试 | 301 | 离线安全回归 |
| 权限测试 | ~50 | BLP 矩阵验证 |
| 加密测试 | ~20 | JWT/密码哈希 |
| 部署测试 | ~30 | 隔离/端口校验 |
| 工单测试 | ~40 | 审批流程 |
| 前端测试 | ~20 | 策略/SDK |

### C. 安全特性

| 特性 | 实现 |
|------|------|
| BLP 不上读 | `docLevel <= userLevel` |
| BLP 不下写 | `docLevel >= userLevel` |
| 部门隔离 | 同部门或"不限部门" |
| 自审批禁止 | 排除申请人本人 |
| 双人审批 | 工单流程 |
| 会话绑定 | 单会话模式 |
| 审计留痕 | 所有操作记录 |
| 速率限制 | IP/用户级限流 |
| 令牌撤销 | JWT + 会话双重撤销 |

---

**文档结束**
