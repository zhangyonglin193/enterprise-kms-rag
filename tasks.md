# Tasks：OIDC/LDAP 适配器 + 权限隔离定向推荐（KMS 增量）

> 依赖顺序自上而下；每项完成后勾选，并跑对应验证。规格依据：`spec.md`。

- [x] **T1 配置项与校验（`config.py`）**
  - `Settings` 新增目录源 / LDAP / OIDC / 推荐全部 env（默认 `seed`+`builtin`，零配置可跑）。
  - `validate_ports()` 追加枚举、必填项、权重非负、`1<=KMS_REC_TOP_N<=50` 校验。
  - 验证：`python -c "from config import settings; ..."` 正常。

- [x] **T2 组织模块修复与重构（`kms/org.py`）**
  - 抽出纯函数 `compute_org_paths(nodes)`；`upsert_org_nodes(nodes)` 基于入参重算 parent_id/org_path/org_level。
  - `seed_org_tree()` 改薄封装；新增 `backfill_user_orgs()`。
  - `sync_from_seed_or_ldap()` 委托 `kms.directory.sync_directory()`；删除 `_upsert_nodes_from_ldap` 调用与 `sync_type` 错误导入。

- [x] **T3 目录适配器（新 `kms/directory.py`）**
  - `DirectoryAdapter`(ABC) / `SimulatedDirectoryAdapter` / `LdapDirectoryAdapter`（惰性 `ldap3`）/ `build_directory_adapter()` / `sync_directory()`。
  - 未装 `ldap3` → 明确 `RuntimeError`。

- [x] **T4 OIDC 提供方（新 `kms/oidc_provider.py` + 改 `kms/oidc.py`）**
  - `OIDCProvider`(ABC) / `BuiltinOIDCProvider` / `ExternalOIDCProvider`（惰性 PyJWT + JWKS，RS256，校验 iss/aud/exp）/ `build_oidc_provider()`。
  - `POST /kms/api/auth/sso/exchange`：仅 external 生效；校验→映射工号→查库→审计→`create_token`。

- [x] **T5 推荐引擎（新 `kms/recommend.py`）**
  - `kms_rec_interactions` DDL + 埋点（`record_interaction` / `record_answer_sources` / `feedback_docs` / `apply_feedback`）。
  - 四策略 + `Recommender.recommend()`：归一化→加权融合→元数据查询→**`service.allowed()` 硬过滤**→截断。
  - `GET /kms/api/recommendations`（`require_user`）+ 审计。

- [x] **T6 业务埋点（`gateway/routes_kms.py`）**
  - `chat()` 记录 `chat_source`；`document()` 记录 `view`；`feedback()` 按 message_id 回溯写 `feedback`。
  - `_recommend_call` 容错包装，埋点失败不影响主返回。

- [x] **T7 启动装配（`run_kms.py`）**
  - lifespan 改用 `sync_directory()` + `ensure_recommend_tables()` + 打印 adapter/OIDC 模式。
  - `include_router(kms.recommend.router)`。

- [x] **T8 离线测试（新 `tests/test_directory_recommend.py`）**
  - 覆盖适配器分发与缺依赖报错、组织路径计算、OIDC 分发、推荐融合与权限过滤、埋点 SQL 形状。
  - 验证：`python -m unittest tests.test_directory_recommend` → 15 tests OK；`tests.test_enterprise` 37 tests OK。

- [x] **T9 文档更新（`docs/`）**
  - `docs/gateway_architecture.md` 增补「统一登录与目录适配（可插拔）」「权限隔离定向推荐」两节。
  - `docs/enterprise_delivery.md` 演示顺序与准入矩阵补充统一登录/目录同步/定向推荐，凭据章节补充 `.env` 注入说明。
  - `.env.kms.example` 追加目录源/LDAP/OIDC/推荐全部键（口令与密钥留空占位）。

- [x] **T10 端到端冒烟（仅 6342）**
  - 按 `spec.md` §6 执行：`readyz` 200、`login` 200、`me` 含组织字段、`documents`/`document` 200、`chat` 200 且带 `message_id`、`recommendations` 200 且每条带 `reasons`。
  - 越权校验：低职级账号（20260001）推荐返回空；SSO `authorize` 302、`exchange`(builtin) 400。
  - 离线回归 `unittest discover -s tests` → 52 tests OK；确认 `app/`（6341）零改动。

---

## 里程碑
- **M1**：T1–T4（适配层）→ 离线测试可跑。✅
- **M2**：T5–T7（推荐 + 装配）→ 服务可启动、端点可用。✅
- **M3**：T8–T10（测试 + 文档 + 冒烟）→ 可交付。✅
