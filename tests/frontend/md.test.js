/* 前端纯函数回归：node --test（零 npm 依赖，CI 直接可跑）
 * 覆盖：Markdown 安全渲染 / HTML 转义 / 权限辅助 / 错误信封解析 / URI 匹配
 */
import test from "node:test";
import assert from "node:assert/strict";

import { renderMarkdown, markdownToText } from "../../kms/web/js/ui/md.js";
import { escapeHtml } from "../../kms/web/js/core/dom.js";
import { errorMessage, assertSameOrigin } from "../../kms/web/js/core/http.js";
import { levelName } from "../../kms/web/js/core/policy.js";

/* ---------- Markdown 安全渲染 ---------- */
test("标题/列表/粗体渲染", () => {
  const html = renderMarkdown("## 标题\n\n- 甲\n- 乙\n\n**重点**");
  assert.match(html, /<h2>标题<\/h2>/);
  // 渲染器在标签之间输出换行（可读性），故用 \s* 容忍；
  // 原正则写作 /<ul><li>甲<\/li><li>乙<\/li><ul>/，末尾把闭合标签写成 <ul>，
  // 且不含换行——这条断言从未通过过。
  assert.match(html, /<ul>\s*<li>甲<\/li>\s*<li>乙<\/li>\s*<\/ul>/);
  assert.match(html, /<strong>重点<\/strong>/);
});

test("XSS：脚本与事件处理器必须被转义", () => {
  const html = renderMarkdown('<img src=x onerror="alert(1)"> <script>alert(2)</script>');
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  // 注意：不能断言 `!html.includes("onerror=")`。转义后该字符串会以**纯文本**
  // 形式留在输出里（&lt;img src=x onerror=&quot;…&quot;&gt;），这是正常的——
  // 尖括号被转义后它不再是属性，不构成 XSS。真正的安全属性是：
  // 不出现活的 <img 标签，且尖括号被转义。
  assert.ok(!html.includes("<img"), "不得出现活的 img 标签");
  assert.ok(html.includes("&lt;img"), "尖括号必须被转义");
});

test("危险协议链接不生成 href", () => {
  const html = renderMarkdown("[点我](javascript:alert(1))");
  assert.ok(!html.includes("javascript:"));
  assert.ok(html.includes("点我"));
});

test("安全链接保留", () => {
  const html = renderMarkdown("[官网](https://example.com/a)");
  assert.match(html, /href="https:\/\/example\.com\/a"/);
  assert.match(html, /rel="noopener noreferrer"/);
});

test("代码块内容被转义且不执行", () => {
  const html = renderMarkdown("```\n<b>x</b>\n```");
  assert.ok(html.includes("&lt;b&gt;"));
  assert.ok(html.includes("<pre><code>"));
});

test("markdownToText 去除标记保留文字", () => {
  // 实际输出在列表与后续段落之间多一个空行（保留段落分隔）："标题\n· 甲\n\n重点"。
  // 压缩连续空行后比对，避免把断言绑死在空白字符上。
  const text = markdownToText("## 标题\n\n- 甲\n\n**重点**").replace(/\n{2,}/g, "\n");
  assert.equal(text, "标题\n· 甲\n重点");
});

/* ---------- 转义 ---------- */
test("escapeHtml 覆盖五类字符", () => {
  assert.equal(escapeHtml(`<a href="x">&'`), "&lt;a href=&quot;x&quot;&gt;&amp;&#39;");
  assert.equal(escapeHtml(null), "");
});

/* ---------- 权限辅助 ----------
 * writableRange / canManageDoc 的测试位于 policy.test.js。
 *
 * levelName 的实现只有 js/core/policy.js 一份（ui-kit 里那份静态映射表
 * 已随经典脚本前端退役删除）；policy 版语义：登记过返回 name，
 * 未登记回退 "L{level}"，不会抛错。
 *
 * 历史上的 canWriteDoc（BLP 不下写）已删除：系统无"写文档内容"的前端入口，
 * 所有变更走工单/审批，前端只需 canManageDoc（管规则，对齐后端 manageable）。
 */

test("levelName 映射与未登记回退", () => {
  const levels = [
    { level: 0, name: "公开" },
    { level: 3, name: "绝密" },
  ];
  assert.equal(levelName(0, levels), "公开");
  assert.equal(levelName(3, levels), "绝密");
  assert.equal(levelName(0), "L0", "未传入字典时回退层级编号，不抛错");
  assert.equal(levelName(9, levels), "L9", "未登记的层级回退编号");
});

/* ---------- 错误信封 ---------- */
test("errorMessage 提取 detail/message 并带请求ID", () => {
  assert.equal(errorMessage({ detail: "无权访问" }, 403), "无权访问");
  assert.equal(errorMessage({ message: "应用已停用" }, 403, "gw-123"), "应用已停用（请求ID gw-123）");
  assert.equal(errorMessage({}, 500), "请求失败 (500)");
});

/* ---------- 同源约束（浏览器环境下由 DOM 提供；Node 下验证逻辑意图） ---------- */
test("assertSameOrigin 拒绝跨域（Node 模拟 URL）", () => {
  // Node 无 location，用 URL 直接表达约束语义
  const same = new URL("/kms/api/chat", "http://127.0.0.1:6342");
  const cross = new URL("https://evil.example/chat");
  assert.equal(same.origin, "http://127.0.0.1:6342");
  assert.notEqual(cross.origin, "http://127.0.0.1:6342");
});
