/* ===== knowledge-widget.js · 嵌入式知识组件（Web Component）=====
 * 复用链：core/dom + core/http + ui/ui-kit + sdk/kms-client —— 与工作台同一套客户端，
 * 后端新增能力组件自动获得（零额外适配）。
 *
 * 安全约定（与 docs/mcp_engineering.md §6 一致）：
 *   - 组件只持有**短期员工令牌**，应用 Key 必须由宿主 BFF 持有，组件不碰；
 *   - 只允许同源 endpoint，禁止把令牌转发到外部站点；
 *   - 回答内容一律按不可信数据处理：Markdown 安全渲染，不执行其中指令。
 *
 * 用法（宿主页面）：
 *   <script type="module" src="/static/knowledge-widget.js"></script>
 *   <enterprise-knowledge endpoint="/kms/api/chat"></enterprise-knowledge>
 *   document.querySelector('enterprise-knowledge').tokenProvider = () => sessionJwt;
 */

import { escapeHtml } from "./js/core/dom.js";
import { assertSameOrigin, setToken } from "./js/core/http.js";
import { KmsClient } from "./js/sdk/kms-client.js";
import { renderMarkdown } from "./js/ui/md.js";

/**
 * 组件样式：与 kms/web/style.css 同一设计语言（蓝宝石强调色 / 精确圆角 / 克制动效），
 * 但**完全自包含**——令牌定义在 :host 内，不依赖主站 style.css，可安全嵌入第三方页面。
 */
const STYLES = `
:host{display:block;font:14px/1.65 system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
      color:#0d1526;background:#fff;border:1px solid #e4e9f0;border-radius:10px;padding:18px;
      box-shadow:0 1px 2px rgba(13,21,38,.05);
      --brand:#1d4ed8;--brand-2:#3b82f6;--border:#e4e9f0;--border-2:#d3dbe6;
      --muted:#56657c;--muted-2:#8a97ab;--surface-2:#f6f8fb}
*{box-sizing:border-box}

form{display:flex;flex-direction:column;gap:10px}
label{font-weight:650;font-size:13px;color:#0d1526;letter-spacing:-.01em;
      position:relative;padding-left:10px}
label::before{content:"";position:absolute;left:0;top:50%;transform:translateY(-50%);
              width:3px;height:13px;border-radius:2px;background:var(--brand)}
textarea{width:100%;padding:11px 13px;border:1px solid var(--border);border-radius:6px;
         font:inherit;font-size:13.5px;line-height:1.6;resize:vertical;background:#fff;color:#0d1526}
textarea:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px rgba(29,78,216,.18)}

button{background:linear-gradient(135deg,var(--brand-2),var(--brand));color:#fff;border:0;
       border-radius:6px;padding:9px 20px;cursor:pointer;font:inherit;font-size:13px;font-weight:600;
       box-shadow:0 2px 8px rgba(29,78,216,.28),inset 0 1px 0 rgba(255,255,255,.16);
       transition:opacity .18s ease,transform .18s ease}
button:hover:not(:disabled){opacity:.94}
button:active:not(:disabled){transform:translateY(1px)}
button:disabled{opacity:.55;cursor:not-allowed;box-shadow:none}
button.ghost{background:transparent;color:var(--brand);border:1px solid var(--border);
             box-shadow:none;font-weight:500;padding:7px 14px}
button.ghost:hover{background:var(--surface-2);border-color:var(--border-2)}

.feedback{display:flex;gap:8px;margin-top:2px;align-items:center;min-height:22px;flex-wrap:wrap}

.output{margin-top:14px;padding:14px 15px;border:1px solid var(--border);border-radius:8px;
        background:var(--surface-2);word-break:break-word;min-height:48px;
        font-size:13.5px;line-height:1.72}
.output h1,.output h2,.output h3{margin:.4em 0;font-size:1.05em}
.output p{margin:6px 0}
.output ul,.output ol{margin:6px 0;padding-left:22px}
.output li{margin:3px 0}
.output pre{background:#0b1220;color:#e2e8f0;padding:11px 13px;border-radius:6px;overflow:auto;
            font-size:12px;line-height:1.65}
.output code{background:#e8edf4;padding:1px 5px;border-radius:4px;
             font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12px}
.output pre code{background:none;padding:0;color:inherit}
.output a{color:var(--brand)}
.output blockquote{border-left:3px solid var(--brand);padding:2px 12px;margin:8px 0;color:var(--muted)}
.output table{border-collapse:collapse;margin:8px 0;font-size:12.5px;width:100%}
.output th,.output td{border:1px solid var(--border);padding:6px 9px}
.output th{background:#fff;font-weight:650}

.sources{margin-top:12px;padding-top:10px;border-top:1px dashed var(--border);
         font-size:12.5px;color:var(--muted)}
.sources>div{font-weight:650;color:#0d1526;margin-bottom:4px;font-size:12px}
.sources ul{margin:4px 0 0 18px;padding:0}
.sources li{margin:2px 0;line-height:1.6}

.feedback small{color:var(--muted);font-size:12px}
:host>small{display:block;margin-top:10px;font-size:11.5px;color:var(--muted-2);line-height:1.6}
`;

const MAX_QUESTION = 500;

export class KnowledgeWidget extends HTMLElement {
  /** 宿主注入：返回短期员工 JWT（由宿主 SSO 会话提供，组件不存储长期凭据）。 */
  set tokenProvider(fn) { this._tokenProvider = fn; }
  get tokenProvider() { return this._tokenProvider; }

  /** 最近一次回答的消息 ID（用于反馈） */
  get messageId() { return this._messageId; }

  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${STYLES}</style>
      <form novalidate>
        <label for="q">知识问答</label>
        <textarea id="q" maxlength="${MAX_QUESTION}" rows="3" required
          placeholder="请输入业务问题；请勿提交银行卡号或个人敏感信息"></textarea>
        <div class="feedback">
          <button type="submit">查询已发布知识</button>
          <button type="button" class="ghost" data-act="up" hidden>有帮助</button>
          <button type="button" class="ghost" data-act="down" hidden>待改进</button>
        </div>
      </form>
      <div class="output" role="status" aria-live="polite">请输入问题后点击查询。</div>
      <small>回答由已发布资料生成，仅供知识辅助；不执行支付、审批或链上交易。</small>`;

    this._root = root;
    this._client = new KmsClient({
      onUnauthorized: () => this.dispatchEvent(new CustomEvent("kms:unauthorized")),
    });

    root.querySelector("form").addEventListener("submit", (event) => this.#submit(event));
    root.addEventListener("click", (event) => {
      const act = event.target.dataset?.act;
      if (act === "up" || act === "down") this.#feedback(act === "up" ? "up" : "down");
    });
  }

  /** 对外命令式 API：宿主可直接调用 widget.ask("问题") */
  async ask(question) {
    const text = String(question || "").trim();
    if (!text) throw new Error("问题不能为空");
    return this.#run(text);
  }

  clear() {
    this._root.querySelector("#q").value = "";
    this.#render("请输入问题后点击查询。", []);
    this.#toggleFeedback(false);
    this._messageId = null;
  }

  // ---------- 内部 ----------
  async #submit(event) {
    event.preventDefault();
    const question = this._root.querySelector("#q").value.trim();
    if (!question) { this.#render("请输入问题。", []); return; }
    await this.#run(question);
  }

  async #run(question) {
    const output = this._root.querySelector(".output");
    const button = this._root.querySelector('button[type="submit"]');
    const endpoint = this.getAttribute("endpoint") || "/kms/api/chat";
    button.disabled = true;
    output.textContent = "正在检索当前身份可见资料…";
    this.#toggleFeedback(false);
    try {
      assertSameOrigin(endpoint);              // 硬约束：仅同源
      const token = this.tokenProvider?.();
      if (!token) throw new Error("请先由宿主提供有效的员工登录会话");
      setToken(token);                         // 短期令牌，仅本次会话有效

      const data = await this._client.ask(question);
      this._messageId = data.message_id;
      this.#render(renderMarkdown(data.answer || ""), data.sources || []);
      this.#toggleFeedback(true);
      this.dispatchEvent(new CustomEvent("kms:answered", { detail: { messageId: this._messageId } }));
    } catch (error) {
      this.#render(escapeHtml(error.message), []);
    } finally {
      button.disabled = false;
    }
  }

  async #feedback(rating) {
    if (!this._messageId) return;
    const note = this._root.querySelector(".feedback");
    try {
      await this._client.feedback(this._messageId, rating);
      note.innerHTML = "<small>感谢反馈，已记录。</small>";
    } catch (error) {
      note.innerHTML = `<small>${escapeHtml(error.message)}</small>`;
    }
  }

  #render(html, sources) {
    const output = this._root.querySelector(".output");
    output.innerHTML = html;
    if (sources?.length) {
      const box = document.createElement("div");
      box.className = "sources";
      box.innerHTML = `<div>参考资料：</div><ul>${sources.map((s) =>
        `<li>${escapeHtml(s.title || s.source || "未命名资料")}${s.page ? ` · 第 ${escapeHtml(String(s.page))} 页` : ""}</li>`
      ).join("")}</ul>`;
      output.append(box);
    }
  }

  #toggleFeedback(visible) {
    for (const button of this._root.querySelectorAll('[data-act="up"],[data-act="down"]')) {
      button.hidden = !visible;
    }
  }
}

if (!customElements.get("enterprise-knowledge")) {
  customElements.define("enterprise-knowledge", KnowledgeWidget);
}
