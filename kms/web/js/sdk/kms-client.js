/* ===== sdk/kms-client.js · 知识服务客户端 SDK（复用中心）=====
 * 与后端能力一一对应的单一客户端，**三处复用**：
 *   1) 工作台（kms/web/index.html）
 *   2) 嵌入组件（knowledge-widget.js，宿主 BFF 同源引用）
 *   3) MCP 控制台 / 未来任何内部工具
 *
 * 设计约定：
 *   - 后端新增能力只在这里加一个方法，三个消费方同步获得；
 *   - 不持有任何业务规则，权限判定全部在服务端；
 *   - 错误统一抛 Error(可读消息)，调用方 try/catch 即可；
 *   - 禁往非同源发请求（core/http 已强制）。
 *
 * 与 MCP 工具面对应关系（docs/mcp_engineering.md §5）：
 *   ask <-> ask_question        search <-> search_knowledge
 *   document <-> get_document   list <-> list_documents
 *   recommend <-> get_recommendations  feedback <-> submit_feedback
 *   propose <-> submit_knowledge_request
 */

import { clearToken, fetchJSON, getToken, postForm, setToken, streamSSE } from "../core/http.js";

export class KmsClient {
  /**
   * @param {object} opts
   * @param {string} [opts.base]    KMS 业务 API 前缀，默认 /kms/api
   * @param {string} [opts.gateway] 网关前缀，默认 /gw/api/v1
   * @param {(info:object)=>void} [opts.onUnauthorized] 401 回调（工作台用于回退登录态）
   */
  constructor(opts = {}) {
    this.base = opts.base || "/kms/api";
    this.gateway = opts.gateway || "/gw/api/v1";
    this.onUnauthorized = opts.onUnauthorized;
  }

  #req(path, init = {}) {
    return fetchJSON(this.base + path, { onUnauthorized: this.onUnauthorized, ...init });
  }

  /* ================= 认证 ================= */
  async login(employeeNo, password) {
    const data = await this.#req("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee_no: employeeNo, password }),
    });
    // 后端 /auth/login 返回 { token, user }；SDK 兼容 token / access_token 两种键名
    const token = data.token || data.access_token;
    if (token) setToken(token);
    return data;
  }

  logout() { clearToken(); }

  me() { return this.#req("/auth/me"); }

  changePassword(oldPassword, newPassword) {
    return this.#req("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
  }

  /* ================= 问答（单轮，企业路径） ================= */
  ask(question) {
    return this.#req("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  }

  /** 流式问答；onEvent 收到单条 JSON 帧。后端复用 /chat 端点，以 ?stream=true 触发 SSE */
  askStream(question, onEvent) {
    return streamSSE(`${this.base}/chat?stream=true`, { question }, onEvent, {});
  }

  feedback(messageId, rating, comment = "") {
    return this.#req("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId, rating, comment }),
    });
  }

  /* ================= 知识检索与目录 ================= */
  /** 授权过滤后的资料片段（对应 MCP search_knowledge） */
  search(query, topK = 5, maxClassification) {
    return this.#req("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: topK, max_classification: maxClassification }),
    });
  }

  /** 文档列表。sort="asc"（默认）按文档编号从小到大，与列表展示口径一致；
   *  「最近入库」类视图必须显式传 "desc"，否则会拿到最旧的一批。
   *
   *  keyword 走服务端全库过滤（后端 q 参数）：列表正序分页，新审批通过的
   *  文档总在末页，只在当前页里筛会搜不到刚通过的文档。 */
  listDocuments(offset = 0, limit = 20, sort = "asc", keyword = "") {
    const q = String(keyword || "").trim();
    const suffix = q ? `&q=${encodeURIComponent(q)}` : "";
    return this.#req(`/documents?offset=${offset}&limit=${limit}&sort=${encodeURIComponent(sort)}${suffix}`);
  }

  document(docId) { return this.#req(`/documents/${docId}`); }

  inspect(docId) { return this.#req(`/documents/${docId}/inspect`); }

  recommendations(topN = 10, seed = {}) {
    const params = new URLSearchParams({ top_n: String(topN) });
    if (seed.seed_doc_id) params.set("seed_doc_id", String(seed.seed_doc_id));
    if (seed.seed_text) params.set("seed_text", seed.seed_text);
    return this.#req(`/recommendations?${params}`);
  }

  /* ================= 文档维护（双人审批，不旁路） ================= */
  /** 上传后进入草稿；发布必须走 propose → decide */
  upload(file, classification) {
    const form = new FormData();
    form.append("file", file);
    if (classification != null) form.append("classification", String(classification));
    return postForm(`${this.base}/documents`, form);
  }

  managedDocuments(limit = 100) { return this.#req(`/managed-documents?limit=${limit}`); }

  /** 提交发布/变更申请（生成工单；批准由审批员在 Web 端完成） */
  propose(docId, policy) {
    return this.#req(`/policy-requests/${docId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(policy),
    });
  }

  requests() { return this.#req("/governance/requests"); }

  decide(requestId, approve) {
    return this.#req(`/governance/requests/${requestId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve }),
    });
  }

  /* ================= 组织与审计 ================= */
  users() { return this.#req("/admin/users"); }
  departments() { return this.#req("/admin/departments"); }

  /** 安全职级列表（只读，固定 L0~L3，由 HR 维护）。
   *  前端需要它把 classification 数字译成名称——不写死在前端，
   *  免得职级调整后名称对不上。 */
  levels() { return this.#req("/admin/levels"); }

  auditEvents(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.#req(`/admin/audit-events${query ? `?${query}` : ""}`);
  }

  /* ================= 网关侧（应用 / 嵌入） ================= */
  embedConfig() { return fetchJSON(`${this.gateway}/embed/config`); }
  embedDocuments(offset = 0, limit = 20) {
    return fetchJSON(`${this.gateway}/embed/documents?offset=${offset}&limit=${limit}`);
  }

  /* ================= MCP（与 REST 同源同权，供控制台复用） ================= */
  /** 调用 MCP 工具；企业路径需带员工令牌 */
  mcpCall(name, args = {}, id = 1) {
    return fetchJSON(`${this.gateway}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18" },
      body: JSON.stringify({ jsonrpc: "2.0", id, method: "tools/call", params: { name, arguments: args } }),
    });
  }

  mcpTools() {
    return fetchJSON(`${this.gateway}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
    });
  }

  mcpMetrics() { return fetchJSON(`${this.gateway}/mcp/metrics`); }

  /* ================= 应用治理自助（对应 MCP get_app_usage） ================= */
  /** 调用方应用近期用量（MCP 工具同源实现） */
  appUsage(days = 7) { return this.mcpCall("get_app_usage", { days }); }
}

/** 默认单例（工作台/widget 直接 import 使用） */
export const kms = new KmsClient();
export { getToken, setToken, clearToken };
