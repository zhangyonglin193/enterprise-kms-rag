/* ===== ui/md.js · 自包含 Markdown 渲染（零依赖、零外链）=====
 * 原实现依赖 jsdelivr CDN 的 marked，内网不可达且构成运行期外联。
 * 现改为自有最小渲染器：先整体转义，再应用受限白名单变换，
 * 因此输出中的 HTML/脚本一律不可执行（防 XSS）。
 * 支持：标题 / 粗体 / 斜体 / 行内代码 / 代码块 / 列表 / 引用 / 链接 / 分割线 / 换行
 */

import { escapeHtml } from "../core/dom.js";

const SAFE_LINK = /^(https?:|mailto:|\/|#)/i;

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) =>
      SAFE_LINK.test(href) ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>` : label);
}

/** 渲染为安全 HTML 字符串 */
export function renderMarkdown(src) {
  const text = String(src ?? "");
  const escaped = escapeHtml(text);
  const lines = escaped.split("\n");
  const out = [];
  let listType = null;
  let inCode = false;
  let codeBuf = [];

  const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (/^```/.test(line)) {
      if (inCode) { out.push(`<pre><code>${codeBuf.join("\n")}</code></pre>`); codeBuf = []; inCode = false; }
      else { closeList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(raw); continue; }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) { closeList(); out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); continue; }

    const quote = /^&gt;\s?(.*)$/.exec(line);
    if (quote) { closeList(); out.push(`<blockquote>${inline(quote[1])}</blockquote>`); continue; }

    if (/^---+$/.test(line.trim())) { closeList(); out.push("<hr>"); continue; }

    const ul = /^\s*[-*]\s+(.*)$/.exec(line);
    if (ul) { if (listType !== "ul") { closeList(); out.push("<ul>"); listType = "ul"; } out.push(`<li>${inline(ul[1])}</li>`); continue; }

    const ol = /^\s*\d+[.、]\s*(.*)$/.exec(line);
    if (ol) { if (listType !== "ol") { closeList(); out.push("<ol>"); listType = "ol"; } out.push(`<li>${inline(ol[1])}</li>`); continue; }

    if (!line.trim()) { closeList(); continue; }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
  }
  if (inCode && codeBuf.length) out.push(`<pre><code>${codeBuf.join("\n")}</code></pre>`);
  closeList();
  return out.join("\n");
}

/** 纯文本降级（无 HTML 场景：日志、剪贴板、测试） */
export function markdownToText(src) {
  return String(src ?? "")
    .replace(/```[\s\S]*?```/g, (m) => m.replace(/```/g, ""))
    .replace(/^\s*[-*]\s+/gm, "· ")
    .replace(/^\s*#{1,4}\s+/gm, "")
    .replace(/\*\*|__|`|\[|\]|\(([^)]+)\)/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export { inline as _inlineForTest };
