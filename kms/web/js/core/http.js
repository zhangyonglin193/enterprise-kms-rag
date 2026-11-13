/* ===== core/http.js · HTTP 客户端（零依赖）=====
 * 所有渠道（工作台 / 嵌入组件 / MCP 控制台）共用的请求层：
 *   - 统一注入 Bearer 令牌
 *   - 解析网关统一错误信封 { code, message, request_id, data }
 *   - 401 时按策略降级（可注入 onUnauthorized，由宿主决定回退逻辑）
 *   - 禁止把令牌发往非同源地址（嵌入场景硬约束）
 */

const TOKEN_KEY = "kms-token";

export function getToken() { return localStorage.getItem(TOKEN_KEY); }
export function setToken(token) { localStorage.setItem(TOKEN_KEY, token); }
export function clearToken() { localStorage.removeItem(TOKEN_KEY); }

export function authHeaders(extra = {}) {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}`, ...extra } : { ...extra };
}

/** 同源校验：嵌入组件不得把令牌转发到外部站点 */
export function assertSameOrigin(url) {
  const parsed = new URL(url, location.origin);
  if (parsed.origin !== location.origin) {
    throw new Error("仅允许同源请求，禁止转发令牌到外部站点");
  }
  return parsed;
}

/** 从网关信封提取可读错误信息 */
export function errorMessage(payload, status, requestId = "") {
  const base = payload?.detail || payload?.message || `请求失败 (${status})`;
  const rid = payload?.request_id || requestId;
  return rid ? `${base}（请求ID ${rid}）` : base;
}

/**
 * JSON 请求。opts.onUnauthorized 可覆盖默认 401 行为（默认清理令牌）。
 * 返回解析后的 JSON；HTTP 失败抛 Error(message)。
 */
export async function fetchJSON(url, opts = {}) {
  const { onUnauthorized, headers = {}, ...rest } = opts;
  assertSameOrigin(url);
  const response = await fetch(url, {
    ...rest,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...authHeaders(headers) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      if (typeof onUnauthorized === "function") await onUnauthorized(response, payload);
      else { clearToken(); }
    }
    throw new Error(errorMessage(payload, response.status, response.headers.get("X-Request-ID")));
  }
  return payload;
}

/** 表单/文件上传（multipart，不设置 Content-Type） */
export async function postForm(url, formData, opts = {}) {
  assertSameOrigin(url);
  const response = await fetch(url, { method: "POST", body: formData, headers: authHeaders(opts.headers || {}) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(payload, response.status, response.headers.get("X-Request-ID")));
  return payload;
}

/** SSE 流式读取（问答流式输出）；onEvent 收到单条 JSON 事件 */
export async function streamSSE(url, body, onEvent, opts = {}) {
  assertSameOrigin(url);
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    headers: authHeaders({ "Content-Type": "application/json", ...(opts.headers || {}) }),
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(errorMessage(payload, response.status, response.headers.get("X-Request-ID")));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try { onEvent(JSON.parse(line.slice(5).trim())); } catch { /* 忽略非 JSON 帧 */ }
    }
  }
}

export { TOKEN_KEY };
