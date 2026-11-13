/* ===== core/dom.js · DOM 原语（零依赖）=====
 * 工作台、嵌入组件、MCP 控制台共用的最小 DOM 层。
 * 只做选择器、转义、事件委托三类事，不引入任何框架。
 */

/** 单选择器 */
export function $(sel, ctx = document) { return ctx.querySelector(sel); }

/** 多选择器（返回数组，便于 map/filter） */
export function $$(sel, ctx = document) { return [...ctx.querySelectorAll(sel)]; }

/** HTML 转义：所有插入 innerHTML 的用户/资料内容必须先过这里 */
export function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 事件委托：容器内匹配 selector 的点击统一走 handler(event, matchedEl) */
export function on(root, selector, eventName, handler) {
  root.addEventListener(eventName, (event) => {
    const matched = event.target.closest(selector);
    if (matched && root.contains(matched)) handler(event, matched);
  });
}

/** 创建元素（属性/子节点一次性设置） */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const child of children) node.append(child);
  return node;
}

/** 显示/隐藏 */
export function show(node, visible = true) { node.hidden = !visible; }

/* 注意：此处原先有一行 `export { $, $$ };`，与第 7/10 行的 `export function`
 * 构成重复导出——ES Module 中这是**硬 SyntaxError**，不是警告。
 * 后果是整个 dom.js 加载失败，连带 js/app.js 的 import 链断裂：
 * window.KMS 永不挂载 → loadLegacyWorkbench() 不执行 → 工作台完全不渲染。
 * （`node --test tests/frontend/md.test.js` 报 "Duplicate export of '$$'" 即此因。）
 * `export function` 已足够导出，无需再写 export {}。
 */
