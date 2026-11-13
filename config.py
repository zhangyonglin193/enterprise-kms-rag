"""全局配置：从 .env 读取，项目内统一通过 settings 使用。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# 两个服务可用不同环境文件隔离评测数据与企业数据；不依赖启动目录。
load_dotenv(os.getenv("RAG_ENV_FILE", str(BASE_DIR / ".env")))


def _get_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip() in ("1", "true", "True", "yes", "YES")


class Settings:
    # ===== 模型服务 =====
    # 仓库不携带任何真实服务地址：实际地址只能由 .env 的 MODEL_API_BASE 提供，
    # 未配置时落到本机占位端口，启动日志与首次调用会立刻暴露「未配置」。
    model_api_base: str = os.getenv("MODEL_API_BASE", "http://127.0.0.1:8289/v1")
    model_api_key: str = os.getenv("MODEL_API_KEY", "")
    # 免费模型组（Embedding/Reranker/OCR）专用 API：有则走专用，无则 fallback 到通用。
    # LLM 始终走通用 model_api_base/key。最终部署时删除 FREE_API_BASE/KEY 即可全部走组委会。
    free_api_base: str = os.getenv("FREE_API_BASE", "") or os.getenv("MODEL_API_BASE", "http://127.0.0.1:8289/v1")
    free_api_key: str = os.getenv("FREE_API_KEY", "") or os.getenv("MODEL_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    ocr_model: str = os.getenv("OCR_MODEL", "PaddlePaddle/PaddleOCR-VL-1.5")

    # ===== MySQL =====
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "")

    # ===== 服务 =====
    qa_port: int = int(os.getenv("QA_PORT", "6341"))
    qa_host: str = os.getenv("QA_HOST", "0.0.0.0")
    kms_port: int = int(os.getenv("KMS_PORT", "6342"))
    kms_host: str = os.getenv("KMS_HOST", "127.0.0.1")
    kms_demo_seed: bool = _get_bool("KMS_DEMO_SEED", "0")
    kms_cors_origins: list[str] = [x.strip() for x in os.getenv("KMS_CORS_ORIGINS", "").split(",") if x.strip()]

    # 唯一保留的名单配置是「谁是运营审计」——它只授只读监控权。
    # 「谁能发起变更」不再配置：所有在职员工均可申请删除/导入/改密级，
    # 把关靠双人审批；「谁能审批」也不配置——改由部门 + 安全职级派生并
    # 随机指派，见 access_control.pick_approver。
    # KMS_APPROVER_EMPLOYEES / KMS_EDITOR_EMPLOYEES 均已废弃：留一个看着
    # 能授予权限、实际不生效的配置项，比没有更容易误导运维。
    kms_auditor_employees: list[str] = [x.strip() for x in os.getenv("KMS_AUDITOR_EMPLOYEES", "").split(",") if x.strip()]

    # ===== 组织目录源（可插拔适配器：seed 内置种子 / ldap 标准目录 / ad 微软活动目录） =====
    kms_directory_source: str = os.getenv("KMS_DIRECTORY_SOURCE", "seed").strip().lower()
    kms_ldap_uri: str = os.getenv("KMS_LDAP_URI", "").strip()
    kms_ldap_bind_dn: str = os.getenv("KMS_LDAP_BIND_DN", "").strip()
    kms_ldap_bind_password: str = os.getenv("KMS_LDAP_BIND_PASSWORD", "")
    kms_ldap_base_dn: str = os.getenv("KMS_LDAP_BASE_DN", "").strip()
    kms_ldap_employee_filter: str = os.getenv("KMS_LDAP_EMPLOYEE_FILTER", "(objectClass=person)")
    kms_ldap_org_filter: str = os.getenv("KMS_LDAP_ORG_FILTER", "(objectClass=organizationalUnit)")
    kms_ldap_employee_no_attr: str = os.getenv("KMS_LDAP_EMPLOYEE_NO_ATTR", "employeeNumber")
    kms_ldap_name_attr: str = os.getenv("KMS_LDAP_NAME_ATTR", "cn")
    kms_ldap_dept_attr: str = os.getenv("KMS_LDAP_DEPT_ATTR", "department")
    kms_ldap_title_attr: str = os.getenv("KMS_LDAP_TITLE_ATTR", "title")
    kms_ldap_level_attr: str = os.getenv("KMS_LDAP_LEVEL_ATTR", "employeeType")
    kms_ldap_timeout: int = int(os.getenv("KMS_LDAP_TIMEOUT", "8"))
    kms_ldap_seed_json: str = os.getenv("KMS_LDAP_SEED_JSON", "").strip()

    # —— HR 系统 HTTP 接入（KMS 作为 Pull 方，只读拉取组织与员工）——
    # 凭据只从本配置注入，客户端无法经业务接口上报人事主数据。
    kms_hr_api_base: str = os.getenv("KMS_HR_API_BASE", "").strip().rstrip("/")
    kms_hr_api_token: str = os.getenv("KMS_HR_API_TOKEN", "").strip()
    kms_hr_api_timeout: float = float(os.getenv("KMS_HR_API_TIMEOUT", "10") or 10)

    # ===== 统一登录 OIDC / OAuth2（可插拔：builtin 内置模拟 IdP / external 外部 OI 平台） =====
    kms_oidc_provider: str = os.getenv("KMS_OIDC_PROVIDER", "builtin").strip().lower()
    kms_oidc_issuer: str = os.getenv("KMS_OIDC_ISSUER", "").strip()
    kms_oidc_jwks_url: str = os.getenv("KMS_OIDC_JWKS_URL", "").strip()
    kms_oidc_client_id: str = os.getenv("KMS_OIDC_CLIENT_ID", "kms-web").strip()
    kms_oidc_client_secret: str = os.getenv("KMS_OIDC_CLIENT_SECRET", "")
    kms_oidc_redirect_uri: str = os.getenv("KMS_OIDC_REDIRECT_URI", "").strip()
    kms_oidc_employee_claim: str = os.getenv("KMS_OIDC_EMPLOYEE_CLAIM", "emp").strip()

    # ===== 权限隔离定向推荐 =====
    kms_rec_enabled: bool = _get_bool("KMS_REC_ENABLED", "1")
    kms_rec_top_n: int = int(os.getenv("KMS_REC_TOP_N", "10"))
    kms_rec_weight_org: float = float(os.getenv("KMS_REC_WEIGHT_ORG", "0.35"))
    kms_rec_weight_semantic: float = float(os.getenv("KMS_REC_WEIGHT_SEMANTIC", "0.35"))
    kms_rec_weight_collab: float = float(os.getenv("KMS_REC_WEIGHT_COLLAB", "0.20"))
    kms_rec_weight_popular: float = float(os.getenv("KMS_REC_WEIGHT_POPULAR", "0.10"))
    kms_rec_collab_min: int = int(os.getenv("KMS_REC_COLLAB_MIN", "3"))
    kms_rec_half_life_days: int = int(os.getenv("KMS_REC_HALF_LIFE_DAYS", "30"))

    # ===== RAG 参数（准确率+性能平衡） =====
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "1024"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "300"))  # 与 MAX_CHARS 对齐，防 400 错误
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "80"))
    # 入库数据卫生：OCR 形近错字清洗（源文件「扫描件转Word」文字层污染，原图丢失无法重 OCR）
    clean_ocr_typos: bool = _get_bool("CLEAN_OCR_TYPOS", "1")  # 设为0可关闭错字清洗
    top_k_retrieve: int = int(os.getenv("TOP_K_RETRIEVE", "20"))
    top_k_rerank: int = int(os.getenv("TOP_K_RERANK", "5"))
    # small-to-big 父块扩展：小块匹配/重排，送 LLM 前对 top 块拼上相邻块，解决答案跨块被斩断
    parent_expand: bool = _get_bool("ENABLE_PARENT_EXPAND", "1")
    parent_expand_topn: int = int(os.getenv("PARENT_EXPAND_TOPN", "3"))  # 只扩展 rerank 前 N 块，防上下文膨胀
    parent_span: int = int(os.getenv("PARENT_SPAN", "1"))  # 每块向前后各取 N 个相邻块
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))  # 1024≈600-800字，覆盖列举/对比类题目
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    # 两段式生成：抽取步逐字抄原句（verbatim 自检）→ 作答步仅基于抽取句组织；不命中自动回落一段式
    enable_two_stage: bool = _get_bool("ENABLE_TWO_STAGE", "1")  # 设为0回退一段式
    extract_max_tokens: int = int(os.getenv("EXTRACT_MAX_TOKENS", "400"))

    # ===== 性能调优 =====
    enable_rerank: bool = _get_bool("ENABLE_RERANK", "1")  # 设为0可跳过重排提速
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    max_context_chars: int = int(os.getenv("MAX_CONTEXT_CHARS", "3000"))  # LLM 上下文上限（5 chunk × 300字 + 标题余量）

    # ===== 混合检索（BM25 + 向量 RRF 融合） =====
    enable_bm25: bool = _get_bool("ENABLE_BM25", "1")  # 设为0可关闭 BM25 退回纯向量检索
    bm25_top_k: int = int(os.getenv("BM25_TOP_K", "20"))  # BM25 检索候选数
    rrf_k: int = int(os.getenv("RRF_K", "60"))  # RRF 常数，标准值 60

    # ===== 结果缓存 =====
    enable_cache: bool = _get_bool("ENABLE_CACHE", "1")  # 相同问题直接返回缓存
    cache_max_size: int = int(os.getenv("CACHE_MAX_SIZE", "200"))

    # ===== 查询改写（检索失败时触发，处理缩写/黑话/同义词） =====
    enable_query_rewrite: bool = _get_bool("ENABLE_QUERY_REWRITE", "1")  # 设为0可关闭
    query_rewrite_max_tokens: int = int(os.getenv("QUERY_REWRITE_MAX_TOKENS", "64"))

    # ===== 线程池（同步路由并发上限） =====
    thread_pool_size: int = int(os.getenv("THREAD_POOL_SIZE", "100"))

    # ===== 多进程 Worker（突破 GIL，并行处理 BM25/jieba 等 CPU 密集任务） =====
    # 每个 worker 独立加载 FAISS/BM25/ChunkCache（内存占用约 70MB/worker）
    uvicorn_workers: int = int(os.getenv("UVICORN_WORKERS", "4"))

    # ===== 对外 API 网关（/gw/api/v1，外部渠道统一入口） =====
    gw_enabled: bool = _get_bool("GW_ENABLED", "1")
    gw_rate_limit_per_minute: int = int(os.getenv("GW_RATE_LIMIT_PER_MINUTE", "60"))
    gw_audit_dir: Path = BASE_DIR / os.getenv("GW_AUDIT_DIR", "data/gw_audit")
    gw_answer_max_chars: int = int(os.getenv("GW_ANSWER_MAX_CHARS", "3000"))  # 机器人回复截断长度

    gw_max_body_bytes: int = 65536
    gw_callback_skew: int = 300
    gw_state_path: Path = BASE_DIR / os.getenv("GW_STATE_PATH", "data/gateway/state.sqlite3")
    gw_model_egress_allowed: bool = _get_bool("GW_MODEL_EGRESS_ALLOWED", "0")

    # ===== MCP 对外知识服务（/gw/api/v1/mcp，默认关闭；见 docs/mcp_engineering.md）=====
    # 关闭时路由根本不注册，等价于功能不存在；开启前须完成模型出域与接入审批。
    gw_mcp_enabled: bool = _get_bool("GW_MCP_ENABLED", "0")
    # 锁定的协议版本列表（MCP 传输层已变更过一次，不自动追新）
    gw_mcp_protocol_versions: list[str] = [x.strip() for x in
                                           os.getenv("GW_MCP_PROTOCOL_VERSIONS", "2025-06-18").split(",") if x.strip()]
    # 工具白名单（对标银联 unionpay-mcp-server 的 UP_AVAILABLE_TOOLS）；空 = 全部启用
    gw_mcp_tools: list[str] = [x.strip() for x in os.getenv(
        "GW_MCP_TOOLS",
        "search_knowledge,ask_question,get_document,list_documents,get_recommendations,"
        "submit_feedback,submit_knowledge_request,get_app_usage").split(",") if x.strip()]
    gw_mcp_max_result_chars: int = int(os.getenv("GW_MCP_MAX_RESULT_CHARS", "4000"))  # 单次返回截断长度

    # ===== 飞书机器人（事件订阅 + 消息回复） =====
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_verification_token: str = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
    feishu_encrypt_key: str = os.getenv("FEISHU_ENCRYPT_KEY", "")  # 为空表示未开启加密事件

    # ===== 企业微信机器人（自建应用回调 + 消息推送） =====
    wecom_corp_id: str = os.getenv("WECOM_CORP_ID", "")
    wecom_agent_id: str = os.getenv("WECOM_AGENT_ID", "")
    wecom_secret: str = os.getenv("WECOM_SECRET", "")
    wecom_token: str = os.getenv("WECOM_TOKEN", "")
    wecom_encoding_aes_key: str = os.getenv("WECOM_ENCODING_AES_KEY", "")

    # ===== 路径 =====
    faiss_index_path: Path = BASE_DIR / os.getenv("FAISS_INDEX_PATH", "data/faiss/index")
    upload_dir: Path = BASE_DIR / os.getenv("UPLOAD_DIR", "data/uploads")
    docs_dir: Path = BASE_DIR / os.getenv("DOCS_DIR", "data/docs")

    # 语料原目录：批量入库脚本导入的历史文档，其 source_path 指向这里
    # （本项目为 RAG_repository/），与 Web 上传的 upload_dir **不同源**。
    # 下载时必须把它与 upload_dir 一并列为受信任根目录；漏登记不会报错，
    # 只会让那一批文档的下载静默变成「原文文件缺失」——故在此显式声明。
    # 注意：不进 ensure_dirs()，它是既定语料目录，不应由程序凭空创建。
    repo_dir: Path = BASE_DIR / os.getenv("RAG_REPOSITORY_DIR", "RAG_repository")

    def validate_ports(self) -> None:
        if self.qa_port != 6341:
            raise ValueError("QA_PORT 必须为 6341，仅供组委会问答评测")
        if not 6342 <= self.kms_port <= 6350:
            raise ValueError("KMS_PORT 必须在 6342～6350，禁止占用评测端口")
        if self.gw_rate_limit_per_minute < 1 or self.gw_answer_max_chars < 64:
            raise ValueError("网关限流必须为正数，回复长度不得小于 64")
        if "*" in self.kms_cors_origins:
            raise ValueError("KMS_CORS_ORIGINS 必须显式列出可信来源，禁止通配符")
        # —— 组织目录适配器 ——
        if self.kms_directory_source not in ("seed", "ldap", "ad", "hr_api", "hr"):
            raise ValueError("KMS_DIRECTORY_SOURCE 只能是 seed / ldap / ad / hr_api")
        if self.kms_directory_source in ("hr_api", "hr") and not self.kms_hr_api_base:
            raise ValueError("选用 hr_api 目录源时必须配置 KMS_HR_API_BASE")
        if self.kms_directory_source in ("ldap", "ad"):
            if not self.kms_ldap_uri or not self.kms_ldap_base_dn:
                raise ValueError("ldap/ad 模式必须配置 KMS_LDAP_URI 与 KMS_LDAP_BASE_DN")
            if not self.kms_ldap_bind_dn or not self.kms_ldap_bind_password:
                raise ValueError("ldap/ad 模式必须配置只读绑定账号 KMS_LDAP_BIND_DN / KMS_LDAP_BIND_PASSWORD")
        if self.kms_ldap_timeout < 1:
            raise ValueError("KMS_LDAP_TIMEOUT 必须为正数")
        # —— 统一登录 OIDC 适配器 ——
        if self.kms_oidc_provider not in ("builtin", "external"):
            raise ValueError("KMS_OIDC_PROVIDER 只能是 builtin / external")
        if self.kms_oidc_provider == "external":
            if not self.kms_oidc_issuer or not self.kms_oidc_jwks_url:
                raise ValueError("external 模式必须配置 KMS_OIDC_ISSUER 与 KMS_OIDC_JWKS_URL")
        # —— 定向推荐 ——
        if not 1 <= self.kms_rec_top_n <= 50:
            raise ValueError("KMS_REC_TOP_N 必须在 1～50")
        weights = (self.kms_rec_weight_org, self.kms_rec_weight_semantic,
                   self.kms_rec_weight_collab, self.kms_rec_weight_popular)
        if any(w < 0 for w in weights) or sum(weights) <= 0:
            raise ValueError("推荐策略权重必须非负且总和为正")
        if self.kms_rec_collab_min < 1 or self.kms_rec_half_life_days < 1:
            raise ValueError("KMS_REC_COLLAB_MIN 与 KMS_REC_HALF_LIFE_DAYS 必须为正整数")
        # —— MCP 对外知识服务 ——
        if not self.gw_mcp_protocol_versions:
            raise ValueError("GW_MCP_PROTOCOL_VERSIONS 不能为空")
        if self.gw_mcp_max_result_chars < 256:
            raise ValueError("GW_MCP_MAX_RESULT_CHARS 不得小于 256")
        if self.gw_mcp_enabled and not self.gw_mcp_tools:
            raise ValueError("GW_MCP_ENABLED=1 时 GW_MCP_TOOLS 不能为空（显式白名单，禁止默认全开）")

    @property
    def auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.model_api_key}"}

    def ensure_dirs(self) -> None:
        for p in (self.upload_dir, self.docs_dir, self.faiss_index_path.parent, self.gw_audit_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.validate_ports()
settings.ensure_dirs()
