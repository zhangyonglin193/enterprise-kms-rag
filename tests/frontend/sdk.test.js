/* SDK 契约测试：node --test
 * 用最小 fetch  stub 验证 KmsClient 的 URL/方法/体/头构造，不起真实服务。
 */
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = {
  store: new Map(),
  getItem(k) { return this.store.has(k) ? this.store.get(k) : null; },
  setItem(k, v) { this.store.set(k, String(v)); },
  removeItem(k) { this.store.delete(k); },
};

// http.js 的 assertSameOrigin 用 location.origin 做同源校验；Node 无该全局，
// 不 stub 会让 5 个用例全部以 ReferenceError: location is not defined 失败。
globalThis.location = { origin: "http://localhost" };

const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), method: init.method || "GET", body: init.body, headers: init.headers || {} });
  return {
    ok: true,
    status: 200,
    headers: { get: () => "gw-test-1" },
    json: async () => ({ ok: true, data: { answer: "答案", sources: [], message_id: "m1" } }),
  };
};

const { KmsClient } = await import("../../kms/web/js/sdk/kms-client.js");
const client = new KmsClient();

test("ask 命中企业问答端点且带令牌", async () => {
  localStorage.setItem("kms-token", "jwt-123");
  const data = await client.ask("商户如何入网");
  const call = calls.at(-1);
  assert.equal(call.url, "/kms/api/chat");
  assert.equal(call.method, "POST");
  assert.equal(call.headers.Authorization, "Bearer jwt-123");
  assert.match(call.body, /商户如何入网/);
  assert.equal(data.data.message_id, "m1");
});

test("mcpCall 构造合法 JSON-RPC 信封", async () => {
  await client.mcpCall("search_knowledge", { query: "MCC" }, 42);
  const call = calls.at(-1);
  assert.equal(call.url, "/gw/api/v1/mcp");
  assert.equal(call.headers["MCP-Protocol-Version"], "2025-06-18");
  const body = JSON.parse(call.body);
  assert.equal(body.jsonrpc, "2.0");
  assert.equal(body.id, 42);
  assert.equal(body.method, "tools/call");
  assert.deepEqual(body.params, { name: "search_knowledge", arguments: { query: "MCC" } });
});

test("listDocuments 分页参数进入查询串", async () => {
  await client.listDocuments(20, 50);
  assert.match(calls.at(-1).url, /\/kms\/api\/documents\?offset=20&limit=50/);
});

test("listDocuments 关键字走服务端 q（全库搜索，不只在当页筛）", async () => {
  await client.listDocuments(0, 20, "asc", " 快手月付 ");
  const url = calls.at(-1).url;
  assert.match(url, /[?&]q=/);
  // 空白要 trim 掉、中文要编码，否则后端拿到带空格的关键字恒不命中
  assert.match(url, /q=%E5%BF%AB%E6%89%8B%E6%9C%88%E4%BB%98$/);
  // 关键字为空时不能拼出空的 q= 参数
  await client.listDocuments(0, 20);
  assert.doesNotMatch(calls.at(-1).url, /[?&]q=/);
});

test("propose 只建工单（对应后端双人审批）", async () => {
  await client.propose(7, { classification: 2, departments: ["商户服务部"], status: "published", reason: "已复核" });
  const call = calls.at(-1);
  assert.equal(call.url, "/kms/api/policy-requests/7");
  assert.equal(call.method, "POST");
  const body = JSON.parse(call.body);
  assert.equal(body.classification, 2);
  assert.equal(body.status, "published");
});

test("login 成功后写入令牌（后端返回键为 token）", async () => {
  globalThis.fetch = async () => ({
    ok: true, status: 200, headers: { get: () => "" },
    json: async () => ({ token: "new-jwt", user: { id: 1 } }),
  });
  await client.login("20260019", "pw");
  assert.equal(localStorage.getItem("kms-token"), "new-jwt");
});

test("治理/组织端点路径与后端一致", async () => {
  // 上一个用例替换过 globalThis.fetch，这里重置为记录型 stub（带可读 body 供 SSE）
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET", body: init.body, headers: init.headers || {} });
    return { ok: true, status: 200, headers: { get: () => "" }, json: async () => ({}),
             body: { getReader: () => ({ read: async () => ({ done: true }) }) } };
  };
  await client.requests();
  assert.equal(calls.at(-1).url, "/kms/api/governance/requests");
  await client.decide(9, true);
  assert.equal(calls.at(-1).url, "/kms/api/governance/requests/9/decision");
  assert.deepEqual(JSON.parse(calls.at(-1).body), { approve: true });
  await client.users();
  assert.equal(calls.at(-1).url, "/kms/api/admin/users");
  await client.departments();
  assert.equal(calls.at(-1).url, "/kms/api/admin/departments");
  await client.changePassword("old", "new");
  assert.equal(calls.at(-1).url, "/kms/api/auth/change-password");
  await client.askStream("问", () => {});
  assert.match(calls.at(-1).url, /\/kms\/api\/chat\?stream=true/);
});
