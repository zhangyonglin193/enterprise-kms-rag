/* 模块可加载性测试：node --test
 *
 * 目的：抓住**硬 SyntaxError** 类缺陷，尤其是重复导出。
 *
 * 实例：core/dom.js 曾有 `export function $$` 之后又写一行 `export { $, $$ }`。
 * ES Module 中同名重复导出是 SyntaxError（不是警告），后果是整条 import 链断裂：
 *   core/dom.js 加载失败 → 下游（md.js / knowledge-widget.js）import 失败
 *   → 渲染输出空白，极难定位；而 tests/test_frontend_architecture.py 的
 *   ImportGraphTests 只静态比对「import 的名字在导出里是否存在」，抓不到这类错误。
 *
 * 因此这里在 Node 里真正 import 每个模块——能加载即通过。
 *
 * 注：Vue 工作台源码（frontend/src 下的 .vue 与 @kms 别名导入）不在此列，
 * 由 vite 构建保证可解析；本测试只覆盖 kms/web/js 共享层。
 */
import test from "node:test";
import assert from "node:assert/strict";

// ---- 最小浏览器全局桩 ----
// 只满足模块**顶层求值**，不模拟真实 DOM 行为。
globalThis.localStorage = {
  store: new Map(),
  getItem(k) { return this.store.has(k) ? this.store.get(k) : null; },
  setItem(k, v) { this.store.set(k, String(v)); },
  removeItem(k) { this.store.delete(k); },
};
// http.js 的 assertSameOrigin 用 location.origin（Node 无该全局）
globalThis.location = { origin: "http://localhost" };
globalThis.window = globalThis;
globalThis.document = {
  readyState: "loading",
  addEventListener() {},
  removeEventListener() {},
  createElement: () => ({}),
  querySelector: () => null,
  querySelectorAll: () => [],
};

// 按依赖顺序排列：被依赖方在前，报错时更容易定位。
// knowledge-widget.js 顶层注册 Custom Element，Node 无 customElements，不纳入。
const MODULES = [
  "../../kms/web/js/core/dom.js",
  "../../kms/web/js/core/http.js",
  "../../kms/web/js/core/policy.js",
  "../../kms/web/js/ui/md.js",
  "../../kms/web/js/sdk/kms-client.js",
];

test("所有 ES Module 均可加载（无硬 SyntaxError / 重复导出）", async () => {
  const failures = [];
  for (const spec of MODULES) {
    try {
      await import(spec);
    } catch (e) {
      failures.push(`${spec}: ${e.constructor.name}: ${e.message}`);
    }
  }
  assert.deepEqual(failures, [], "以下模块加载失败：\n" + failures.join("\n"));
});

test("Vue 工作台仍复用共享层客户端（kms-client 为单一真相）", async () => {
  // 前端迁移为 Vue 架构后，api.js 继承 KmsClient 而非重写——
  // 这里静态断言继承关系仍在，防止后续被改成独立实现造成双客户端漂移。
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../../frontend/src/app/api.js", import.meta.url), "utf-8");
  assert.match(src, /extends\s+KmsClient/, "frontend/src/app/api.js 必须继承 KmsClient");
  assert.match(src, /from\s+"@kms\/sdk\/kms-client\.js"/, "必须经 @kms 别名复用共享 SDK");
});
