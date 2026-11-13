# AGENTS.md — AI 代理路由指南

> 本文件帮助 AI 代理快速理解项目结构、核心约束和变更风险。修改代码前务必通读。

## 项目概述

RAG 问答 + 知识文档管理双服务系统，服务于银联商务竞赛评测和企业知识管理。

- **QA 服务** (port 6341): 赛题问答，无员工认证，仅装载竞赛公开资料
- **KMS 服务** (port 6342): 企业知识管理，含权限体系、文档审批、API 网关

## 模块边界（不可混淆）

| 模块 | 路径 | 职责 | 安全级别 |
|---|---|---|---|
| QA 问答 | `app/` + `api.py` | 赛题 `/chat` 接口 | 低（公开评测） |
| KMS 核心 | `kms/` | 权限、用户、组织、推荐 | 高（企业数据） |
| API 网关 | `gateway/` | 飞书/企微机器人、嵌入 API、审计 | 高（对外入口） |
| 配置 | `config.py` | 全局配置 + 端口/安全校验 | 关键 |
| 启动器 | `scripts/service.py` | 跨平台受控启动，端口冲突即退出 | 关键 |
| 测试 | `tests/` | 离线安全回归，不连接真实 DB/模型 | — |

**QA 与 KMS 必须使用不同数据库、不同 FAISS 索引、不同数据目录，启动器自动校验。**

## 核心变更风险（修改前必读）

### 1. 端口规则（不可违反）
- QA 端口固定 6341，不可更改
- KMS 端口 6342~6350，不可与 QA 冲突
- 端口冲突即退出，不自动换端口、不终止其他进程
- 校验逻辑: `config.py:validate_ports()` + `scripts/service.py:bind_socket()`

### 2. 数据隔离（强制）
- QA/KMS 的 MySQL 数据库、FAISS 索引、上传目录、文档目录必须完全独立
- 路径不得相互包含（父子关系也不允许）
- 校验逻辑: `scripts/service.py:deployment_values()`

### 3. 权限矩阵（安全关键）
- BLP 强制访问控制: 密级 + 部门 + 审批状态 + 生命周期状态
- 自审批禁止: 作者不能审批自己的文档
- 管理员/审计员角色不可重叠，维护员/审批员不可重叠
- 核心文件: `kms/security.py`, `gateway/service.py:allowed()`, `gateway/routes_kms.py`

### 4. CORS 限制
- KMS CORS  origins 必须显式列出，禁止通配符 `*`
- QA 服务当前允许所有来源（因无认证），KMS 不可效仿

## 安全关键路径（变更需额外谨慎）

```
config.py                  → 端口/角色/CORS 校验
scripts/service.py         → 启动前环境隔离 + 端口绑定
gateway/middleware.py       → API 网关速率限制 + 审计
gateway/service.py          → 文档权限判定 (allowed())
gateway/crypto.py           → 飞书/企微消息加解密
kms/security.py             → JWT 签发/验证 + AuthUser
kms/access_control.py       → BLP 权限表 + 角色管理
app/main.py                → QA 服务生命周期
run_kms.py                 → KMS 服务生命周期 + FAISS Unicode 补丁
```

## 测试入口

```bash
# 离线安全回归（不连接数据库/模型）
python -m unittest discover -s tests -v

# 单文件运行
python -m unittest tests.test_enterprise -v
```

测试覆盖: 权限矩阵、加密向量、部署隔离、端口约束、事务回滚、令牌撤销。
测试不覆盖: 文档上传/审批流程、端到端问答、前端交互。

## 启动与预检

```bash
# 配置预检（不连接 DB/模型）
python scripts/service.py qa --env .env --check
python scripts/service.py kms --env .env.kms --qa-env .env --check

# 启动服务
start_local.bat all        # Windows
bash start.sh all          # Linux
```

## 编码约定

- Python 3.11，FastAPI + uvicorn
- 配置从 `.env` / `.env.kms` 读取，不硬编码
- 中文注释和错误信息
- 离线测试使用 `unittest.mock`，禁止连接真实 MySQL/模型
- 依赖版本用 `>=` 范围约束，不用 `==` 锁死

## 禁止事项

1. 不得将 QA 评测数据与企业数据混用
2. 不得在 KMS 服务上开放 `/chat` 接口（应返回 404）
3. 不得绕过启动器的端口/数据隔离校验
4. 不得在代码中硬编码密钥、密码、API Key
5. 不得删除或修改 `tests/test_enterprise.py` 中的安全断言
