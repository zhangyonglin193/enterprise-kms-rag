# Spec：企业级 OIDC/OAuth2 与 LDAP/AD 适配器 + 权限隔离定向推荐（KMS 增量）

> 目标读者：实现者与评审人。
> 本文为「决策完备」规格：每项改动给出确切文件、接口签名、验证方式与审批点。
> 相关既有文档：`docs/KMS_竞赛系统设计方案.md`（总体设计）、`docs/module_spec.md`（模块规格）、`docs/enterprise_delivery.md`（交付规范）。

---

## 1. 目标

参照 IBM 等企业 KMS 做法，在现有 KMS（`kms/` + `gateway/`，端口 6342）上做**可插拔增量**：

1. **目录同步可插拔**：把当前「seed/JSON 模拟」的 LDAP 同步抽象为标准 `DirectoryAdapter`，并补齐真实 LDAP/AD 客户端骨架（惰性依赖 `ldap3`），通过 `KMS_DIRECTORY_SOURCE` 一键切换 `seed | ldap | ad`。
2. **统一登录可插拔**：把当前内置模拟 IdP 抽象为标准 `OIDCProvider`，新增对接**外部 OI 平台**（真实 IdP）的令牌交换端点 `POST /kms/api/auth/sso/exchange`，通过 `KMS_OIDC_PROVIDER` 切换 `builtin | external`。
3. **权限隔离的定向推荐**：新增 `kms/recommend.py`，融合「组织画像 / 语义相似 / 协同过滤 / 热度」四路策略，产出**必须经 `service.allowed()` 硬过滤**的推荐结果，并提供 `GET /kms/api/recommendations`。

## 2. 非目标（明确不做）

- 不改动赛题问答服务 `app.api`（6341）任何代码与行为。
- 不引入必需的新第三方依赖：`ldap3`、`PyJWT`/`cryptography` 均为**惰性可选**，未安装时对应适配器给出明确报错，其余功能不受影响。
- 不改动现有两段式工单、双人发布、BLP+部门权限模型本身。
- 不新增全局超级管理员、不做物理删除、不做凭据入库（凭据只走 `.env`）。

## 3. 硬约束（工程化标准）

- 所有凭据/连接参数仅通过 `.env` / `.env.kms` 注入，代码零硬编码、零默认明文。
- 推荐候选**必须**逐条通过 `gateway.service.allowed(row, user, 0, user.security_level)`，未授权文档一律不进入结果（防越权推荐）。
- 所有新增写/读端点都落审计（`gateway.audit.log_gw_event` 或 `kms.access_control.add_audit`）。
- 复用现有 `AuthUser`、`hr_sync.sync_employees`、`kms_org_nodes`、`service.allowed`，不重复造轮子。
- 现有离线回归 `tests/test_enterprise.py` 必须保持全绿。

---

## 4. 配置项（`config.py` `Settings`，全部 `os.getenv` 注入）

| 键 | 默认 | 说明 |
|---|---|---|
| `KMS_DIRECTORY_SOURCE` | `seed` | 目录源：`seed`(内置种子) / `ldap` / `ad` |
| `KMS_LDAP_URI` | `""` | 如 `ldaps://ad.corp:636`；`ldap/ad` 模式必填 |
| `KMS_LDAP_BIND_DN` | `""` | 只读绑定账号 DN |
| `KMS_LDAP_BIND_PASSWORD` | `""` | 只读绑定口令（仅 .env） |
| `KMS_LDAP_BASE_DN` | `""` | 如 `DC=corp,DC=com`；`ldap/ad` 模式必填 |
| `KMS_LDAP_EMPLOYEE_FILTER` | `(objectClass=person)` | 员工条目过滤器 |
| `KMS_LDAP_ORG_FILTER` | `(objectClass=organizationalUnit)` | 组织 OU 过滤器 |
| `KMS_LDAP_EMPLOYEE_NO_ATTR` | `employeeNumber` | 工号属性 |
| `KMS_LDAP_NAME_ATTR` | `cn` | 姓名属性 |
| `KMS_LDAP_DEPT_ATTR` | `department` | 部门属性 |
| `KMS_LDAP_TITLE_ATTR` | `title` | 业务称谓属性 |
| `KMS_LDAP_LEVEL_ATTR` | `employeeType` | 密级属性（解析为 L0–L3） |
| `KMS_LDAP_TIMEOUT` | `8` | 连接/查询超时（秒） |
| `KMS_LDAP_SEED_JSON` | `""` | 模拟目录 JSON 路径（`seed`/离线演示用） |
| `KMS_OIDC_PROVIDER` | `builtin` | `builtin`(内置模拟 IdP) / `external`(OI 平台) |
| `KMS_OIDC_ISSUER` | `""` | 外部 issuer；`external` 必填 |
| `KMS_OIDC_JWKS_URL` | `""` | 外部 JWKS 地址；`external` 必填 |
| `KMS_OIDC_CLIENT_ID` | `kms-web` | 客户端 ID（校验 aud） |
| `KMS_OIDC_CLIENT_SECRET` | `""` | 客户端密钥（仅 .env，用于外部换令牌） |
| `KMS_OIDC_REDIRECT_URI` | `""` | 回调地址 |
| `KMS_OIDC_EMPLOYEE_CLAIM` | `emp` | id_token 中映射工号的 claim 名 |
| `KMS_REC_ENABLED` | `1` | 推荐总开关 |
| `KMS_REC_TOP_N` | `10` | 默认返回条数（1–50） |
| `KMS_REC_WEIGHT_ORG` | `0.35` | 组织画像权重 |
| `KMS_REC_WEIGHT_SEMANTIC` | `0.35` | 语义相似权重 |
| `KMS_REC_WEIGHT_COLLAB` | `0.20` | 协同过滤权重 |
| `KMS_REC_WEIGHT_POPULAR` | `0.10` | 热度权重 |
| `KMS_REC_COLLAB_MIN` | `3` | 协同过滤最小交互数（低于则冷启动降权为 0） |
| `KMS_REC_HALF_LIFE_DAYS` | `30` | 热度半衰期（天） |

**轻量校验**（追加进现有 `validate_ports()`，与既有非端口校验风格一致）：

- `KMS_DIRECTORY_SOURCE ∈ {seed, ldap, ad}`，否则 `ValueError`。
- `KMS_OIDC_PROVIDER ∈ {builtin, external}`，否则 `ValueError`。
- `seed`/`ldap`/`ad` 模式：`ldap`/`ad` 时 `KMS_LDAP_URI` 与 `KMS_LDAP_BASE_DN` 必填。
- `external` 时 `KMS_OIDC_ISSUER` 与 `KMS_OIDC_JWKS_URL` 必填。
- 四个 `KMS_REC_WEIGHT_*` 均 `>= 0` 且总和 `> 0`。
- `1 <= KMS_REC_TOP_N <= 50`。

> 默认值下（`seed` + `builtin`）本地启动零配置即可跑通，`validate_ports()` 不因新增项而失败。

---

## 5. 模块设计

### 5.1 新建 `kms/directory.py`（目录适配器）

```python
class DirectoryAdapter(ABC):
    name: str          # 'simulated-seed' | 'simulated-json' | 'ldap' | 'ad'
    source_type: str   # 'seed' | 'ldap' | 'ad'（写入 hr_sync.sync_logs.source_type）
    def health(self) -> dict: ...                 # {'ok':bool,'adapter':str,'source_type':str,'detail':str}
    def fetch_org_nodes(self) -> list[dict]: ...  # {'code','name','parent_code','org_type','manager_employee_no'}
    def fetch_employees(self) -> list[HREmployeeData]: ...

class SimulatedDirectoryAdapter(DirectoryAdapter):
    # seed: 组织节点取 kms.org.SEED_ORG_TREE；若 KMS_LDAP_SEED_JSON 配置则改取该 JSON 的 org_nodes/employees
    # employees: 取 JSON 的 employees（无则返回 []，员工播种仍由 scripts/seed_employees.py 负责）

class LdapDirectoryAdapter(DirectoryAdapter):
    # 惰性 import ldap3；未安装 → RuntimeError('LDAP 适配器需要 ldap3，请 pip install ldap3 后重试')
    # AD 模式（source_type='ad'）默认走 LDAPS + NTLM 简单绑定，属性映射复用统一 GET，雇员按 employee_no 排序
    # fetch_org_nodes: 按 KMS_LDAP_ORG_FILTER 查询 OU，解析出 code/name/parent_code（由 DN 推导父 OU）
    # fetch_employees: 按 KMS_LDAP_EMPLOYEE_FILTER 查询，映射 工号/姓名/部门/称谓/密级（employeeType→L0-L3）
    # 只读账号绑定；连接超时 KMS_LDAP_TIMEOUT；查询异常向上抛，由 sync_directory 统一兜底为错误结果

def build_directory_adapter(source: str | None = None) -> DirectoryAdapter   # 依 settings.kms_directory_source
def sync_directory(adapter: DirectoryAdapter | None = None, triggered_by: int | None = None) -> dict
    # 1) adapter or build_directory_adapter()
    # 2) org.upsert_org_nodes(adapter.fetch_org_nodes())  # 组织节点 upsert（含 parent_id/org_path/org_level 重算）
    # 3) emps = adapter.fetch_employees(); 若非空 → hr_sync.sync_employees(emps, source_type=adapter.source_type, sync_type='full', triggered_by=triggered_by)
    # 4) org.backfill_user_orgs()  # 批量回填 kms_users.org_node_id/org_path/manager_employee_no
    # 返回 {'adapter':adapter.name,'source_type':adapter.source_type,'org_nodes':int,'employees':dict|None}
```

### 5.2 修复并重构 `kms/org.py`

现状缺陷（已确认）：`sync_from_seed_or_ldap()` 的 `source='ldap'` 分支调用了**未定义**的 `_upsert_nodes_from_ldap`（`org.py` L337），且 `from .hr_sync import ... sync_type` 导入了不存在的符号（L317）。二者都会在 LDAP 分支抛 `NameError`/`ImportError`。

改动：

- 抽出通用 upsert：`upsert_org_nodes(nodes: list[dict]) -> int`，参数即 `SEED_ORG_TREE` 同构列表；内部完成「按 code upsert → BFS 重算 parent_id/org_path/org_level」。**路径/父节点计算改为基于传入的 `nodes`**（不再硬编码读 `SEED_ORG_TREE`）。
- `seed_org_tree()` 变成薄封装：`return {"nodes": upsert_org_nodes(SEED_ORG_TREE), ...}`，保持现有返回结构（`nodes` 键不变，供 `run_kms.py` 日志复用）。
- 新增 `backfill_user_orgs() -> int`：遍历 `kms_users`，对每个员工调用现有 `resolve_user_org(employee_no, department, manager_employee_no)` 并回填 `org_node_id/org_path/manager_employee_no`，返回处理人数。
- 重写 `sync_from_seed_or_ldap(source)` → 委托 `kms.directory.sync_directory()`（函数内 import 以避免循环依赖）；保留该函数名以兼容既有调用方。
- 移除对 `_upsert_nodes_from_ldap` 的调用与 `sync_type` 错误导入。

### 5.3 新建 `kms/oidc_provider.py` + 扩展 `kms/oidc.py`

`kms/oidc_provider.py`：

```python
class OIDCProvider(ABC):
    name: str          # 'builtin' | 'external'
    def verify_id_token(self, id_token: str) -> dict
        # 返回 {'employee_no','name','department','level','iss','aud','sub'}；校验失败抛 HTTPException(401)

class BuiltinOIDCProvider(OIDCProvider):
    # 委派 kms.oidc 既有内部实现（本进程内存模拟 IdP）；用于本地/竞赛演示

class ExternalOIDCProvider(OIDCProvider):
    # 惰性 import jwt（PyJWT）+ jwt.PyJWKClient；未安装 → RuntimeError('外部 OIDC 验签需要 PyJWT 与 cryptography')
    # 流程：PyJWKClient(KMS_OIDC_JWKS_URL).get_signing_key_from_jwt(id_token) → jwt.decode(..., algorithms=['RS256'],
    #       audience=KMS_OIDC_CLIENT_ID, issuer=KMS_OIDC_ISSUER) → 按 KMS_OIDC_EMPLOYEE_CLAIM 提取 employee_no
    # 任何校验失败 → HTTPException(401, '外部令牌校验失败')；JWKS 拉取失败 → HTTPException(503)

def build_oidc_provider() -> OIDCProvider   # 依 settings.kms_oidc_provider
```

`kms/oidc.py` 追加端点（放在现有 `router` 下，路径 `/kms/api/auth/sso/exchange`）：

- `POST /kms/api/auth/sso/exchange`：body 接受 JSON 或 form-urlencoded 的 `id_token`。
  1. `provider = build_oidc_provider()`；`provider.name != 'external'` → `HTTPException(400, '内置 IdP 请使用 /token 交换')`。
  2. `claims = provider.verify_id_token(id_token)`；`employee_no = claims['employee_no']`。
  3. `row = acl.get_user_by_employee_no(employee_no)`；不存在或 `is_active=0` → `HTTPException(403)`。
  4. `acl.add_audit(AuthUser(row), 'sso_external_exchange', target=employee_no, detail=f"iss={claims['iss']}", ip=client_ip(request))`。
  5. 复用现有 `create_token(...)` 返回 `{'access_token','token_type':'Bearer','expires_in','scope','id_token'}`，字段结构与本文件 `/token` 保持一致。

> 中间件适配：`gateway/middleware.py` 已对 `/kms/api/auth/sso/` 前缀豁免 Bearer 校验（L99），`/exchange` 自动纳入，无需改中间件。

### 5.4 新建 `kms/recommend.py`（权限隔离推荐）

DDL（幂等，不动原表）：

```
kms_rec_interactions(
  id BIGINT PK AI,
  user_id BIGINT NOT NULL,
  employee_no VARCHAR(64) NULL,
  doc_id BIGINT NULL,
  message_id VARCHAR(64) NULL,      -- 关联问答回执，支持按消息回溯来源
  kind VARCHAR(24) NOT NULL,        -- chat_source / view / feedback
  weight DECIMAL(6,2) NOT NULL DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_u (user_id, created_at), INDEX idx_doc (doc_id), INDEX idx_msg (message_id)
)
```

- `ensure_recommend_tables() -> bool`
- `record_interaction(user, kind, doc_id=None, message_id="", weight=0.0) -> None`（失败仅告警，不阻断主流程）
- 权重常量：`chat_source=+1.0`、`view=+0.5`、`feedback 正=+2.0 / 负=-2.0`
- `record_answer_sources(user, message_id, doc_ids)`：一次写入 message 及其来源 doc（供 feedback 回溯）

策略（`Strategy` 协议，`score(user, ctx) -> dict[int, float]`）：

- `OrgProfileStrategy`：候选文档 `owner_org_path` 落在 `user.org_path` 的下级集合（`org.get_descendants_path`）→ 高分；同 `department` 加权。
- `SemanticStrategy`：`seed_text` 或 `seed_doc_id` 对应文本 → `retriever.embedder.embed_one` → `retriever.vector_store.search(emb, k*3)` → `chunk_cache` 映射 `faiss_id→document_id` → 得分。
- `CollaborativeStrategy`：item-item 共现（同用户交互过的 doc 对）；`interactions < KMS_REC_COLLAB_MIN` 时冷启动返回 `{}`（降权）。
- `PopularityStrategy`：近 `created_at` 按 `KMS_REC_HALF_LIFE_DAYS` 半衰期衰减的交互计数。

`Recommender`：

```python
@dataclass
class Recommendation:
    doc_id: int; title: str; file_type: str; classification: int
    score: float; reasons: list[str]; strategies: list[str]

def recommend(user: AuthUser, top_n: int | None = None,
              seed_text: str = "", seed_doc_id: int | None = None) -> list[Recommendation]
    # 1) 各路策略产出 {doc_id: raw}
    # 2) 每路归一化到 [0,1]（除以该路 max，max<=0 则跳过该路）
    # 3) 按 settings 权重加权求和；冷启动时由 PopularityStrategy 兜底
    # 4) 取候选 top (top_n*3)，一次性查 documents+kms_doc_levels 元数据
    # 5) 硬过滤：service.allowed(row, user, 0, user.security_level) 为真才保留（含 status/lifecycle/publication/expired/部门/组织继承）
    # 6) 截断 top_n，附 reasons（命中策略名，如 'organization'/'semantic'/'collaborative'/'popular'）
```

路由（挂在 `kms_router` 所在 app，prefix `/kms/api`）：

- `GET /kms/api/recommendations`，Query：`top_n`(1–50，默认 `KMS_REC_TOP_N`)、`seed_doc_id`(可选)、`seed_text`(可选，≤200 字)。
- `Depends(require_user)`；`KMS_REC_ENABLED=0` → 返回 `{'items': [], 'enabled': False}`。
- 响应 `{'enabled': True, 'items': [ {doc_id,title,file_type,classification,score,reasons,strategies} ]}`。
- 审计：`gateway.audit.log_gw_event('kms','recommendations', request_id=request.state.request_id, employee_no=user.employee_no, target=f'reco:{len(items)}', status_code=200, ip=client_ip(request))`。

### 5.5 `gateway/routes_kms.py` 埋点（不改原有权限判定）

- `chat()`：拿到 `result['sources']` 后，`mid = state.receipt(f"kms:{user.id}")`，调用 `recommend.record_answer_sources(user, mid, [s['document_id'] for s in sources], kind='chat_source')`。
- `document(doc_id)`：通过 `service.allowed` 后，`recommend.record_interaction(user, kind='view', doc_id=doc_id, weight=0.5)`。
- `feedback()`：`state.feedback` 成功后，按 `message_id` 查 `kms_rec_interactions` 中 `kind='chat_source'` 的 doc_id，写 `kind='feedback'`，`rating='up'→+2.0 / 'down'→-2.0`。

> 埋点全部 `try/except` 包裹，任何埋点失败不得影响主业务返回。

### 5.6 `run_kms.py` 装配

- lifespan 组织初始化段落（现 L192–197）替换为：

```python
from kms.directory import sync_directory
from kms.recommend import ensure_recommend_tables
ensure_org_tables()
dir_result = sync_directory()
logger.info(f"组织目录就绪: adapter={dir_result['adapter']} 节点={dir_result['org_nodes']}")
ensure_recommend_tables()
```

- `include_router` 段落（现 L269–282）追加推荐路由：
  `from kms.recommend import router as kms_rec_router` → `app.include_router(kms_rec_router)`（紧随 `kms_router` 之后）。
- 日志新增一行打印 `KMS_DIRECTORY_SOURCE` / `KMS_OIDC_PROVIDER`，便于评委现场确认适配器模式。

### 5.7 测试（离线、不连库/不连模型/不起监听）

新增 `tests/test_directory_recommend.py`（沿用 `test_enterprise.py` 的 `MySQLStore._get_pool` 阻断模式），覆盖：

1. `build_directory_adapter`：`seed` → `SimulatedDirectoryAdapter`；`ldap`/`ad` 在 `ldap3` 缺失时抛 `RuntimeError`（通过 patch `sys.modules`/import 模拟缺失）。
2. `upsert_org_nodes`：给定 3 节点小树，路径/层级/父节点计算正确（纯函数式断言，用 mock 游标或抽出的纯计算函数）。
3. `build_oidc_provider`：`builtin`/`external` 分发；`ExternalOIDCProvider.verify_id_token` 在 PyJWT 缺失时抛 `RuntimeError`。
4. `Recommender.recommend`：mock 四路策略分数 + mock 元数据查询，断言 (a) 融合后排序正确；(b) **未过 `allowed()` 的候选被剔除**；(c) 冷启动协同返回空时由热度兜底。
5. `kms_rec_interactions` 的 `record_answer_sources` 写入与 feedback 回溯（mock 游标断言 SQL 形状）。

并保持 `tests/test_enterprise.py` 全绿。

### 5.8 文档更新（沿用现有 docs 风格，中文）

- `docs/KMS_竞赛系统设计方案.md`：新增「外部 OIDC/LDAP 适配」与「定向推荐」两节（含配置项表、切换方式、演示话术）。
- 在 `docs/enterprise_delivery.md` 的凭据章节补充：`KMS_LDAP_BIND_PASSWORD`、`KMS_OIDC_CLIENT_SECRET` 仅经 `.env` 注入，`.env.kms.example` 只留空占位。

---

## 6. 验证步骤（验收）

1. `python -m pytest tests/ -q`（或 `python -m unittest discover tests`）→ 全绿。
2. 重启 **仅 6342**（勿动 6341 `app.api`）：`python run_kms.py`，等待启动完成（约 40–55s）。
3. `GET http://127.0.0.1:6342/readyz` → 200，日志出现 `adapter=simulated-seed`。
4. `POST /kms/api/auth/login` 取 token（工号 20260019/密码 20260019）→ `GET /kms/api/auth/me` 含 `org_path/org_node_id/manager_employee_no` 组织字段。
5. `POST /kms/api/chat`（Bearer）→ 200，返回 `sources`；对应 `kms_rec_interactions` 出现 `kind='chat_source'` 行。
6. `GET /kms/api/documents/{id}`（有权限文档）→ 200；`kms_rec_interactions` 出现 `kind='view'`。
7. `GET /kms/api/recommendations`（Bearer）→ 200，`items` 全部为**已授权**文档（每条带 `reasons`）。
8. 越权校验：用低职级账号（如 20260001）请求推荐，确认不会出现其无权访问的 L2+ 文档。
9. SSO 回归：`GET /kms/api/auth/sso/authorize?...&state=x` → 302（内置流不变）；`POST /kms/api/auth/sso/exchange`（未配置 external）→ 400 且提示走 `/token`。
10. 适配器切换冒烟：设 `KMS_DIRECTORY_SOURCE=ldap` 启动 → 因缺 `ldap3` 或未配 URI，启动信息给出**明确报错**而非静默失败（不改默认配置）。

## 7. 风险与回滚

- 风险：真实 LDAP/外部 IdP 无法在本机验证 → 仅做**骨架 + 明确报错**，默认仍走 `seed`/`builtin`，不影响竞赛演示。
- 风险：推荐策略依赖 embedding/向量库 → 全部包 `try/except`，任一路失败降级为其余策略，绝不 500。
- 回滚：设置 `KMS_REC_ENABLED=0` 关推荐；`KMS_DIRECTORY_SOURCE=seed`、`KMS_OIDC_PROVIDER=builtin` 回到现状；代码改动均为新增模块 + 小幅装配，不动原权限/工单逻辑。

## 8. 待实现文件清单

| 类型 | 文件 | 动作 |
|---|---|---|
| 改 | `config.py` | 新增 §4 配置项 + `validate_ports()` 校验 |
| 改 | `kms/org.py` | 抽出 `upsert_org_nodes`、新增 `backfill_user_orgs`、修复 LDAP 分支 bug |
| 新 | `kms/directory.py` | DirectoryAdapter + Simulated/Ldap + build + sync_directory |
| 新 | `kms/oidc_provider.py` | OIDCProvider + Builtin/External + build |
| 改 | `kms/oidc.py` | 追加 `/sso/exchange` |
| 新 | `kms/recommend.py` | 交互表 + 四策略 + Recommender + 路由 |
| 改 | `gateway/routes_kms.py` | chat/document/feedback 埋点 |
| 改 | `run_kms.py` | 装配 sync_directory / 推荐表 / 推荐路由 |
| 新 | `tests/test_directory_recommend.py` | 离线回归 |
| 改 | `docs/*.md` | 设计/交付文档补充 |

## 9. 审批点

**需要批准后才会进入编码**。批准即表示：同意上述文件清单、接口签名、配置项、验证步骤与默认（零配置可跑）行为。
