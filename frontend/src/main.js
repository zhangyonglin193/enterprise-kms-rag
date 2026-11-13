/* ===== main.js · Vue 试点入口 =====
 *
 * 以 **library 模式**构建，对外只暴露 mount()，由既有 index.html 主动挂载到
 * `#vue-knowledge-pilot`，而不是像普通 SPA 那样接管整个页面。
 * 这样试点可以和工作台并存：任何一个视图出问题，其余界面都不受影响。
 *
 * 挂载点是既有页面里的一个空 section，旧代码不参与它的渲染，
 * 回退时删掉挂载点 + dist/ 即可，不需要回滚任何既有文件。
 */
import { createApp } from "vue";

import KnowledgeList from "./views/KnowledgeList.vue";

/**
 * 把试点组件挂到指定容器。
 * @param {string|Element} target 选择器或元素
 */
export function mount(target) {
  const host = typeof target === "string" ? document.querySelector(target) : target;
  if (!host) {
    throw new Error(`[knowledge-list] 挂载点不存在: ${target}`);
  }

  const app = createApp(KnowledgeList);

  // 试点隔离：组件内部抛错只在试点区域内提示，
  // 绝不让它冒泡去影响既有工作台的任何一块界面。
  // 统一用主站的 state-box（而非组件私有类），这样即使组件样式没加载也能读，
  // 且亮/暗双主题自动跟随。
  app.config.errorHandler = (err) => {
    host.innerHTML = `
      <div class="state-box state-box--error">
        <span class="state-icon" aria-hidden="true"></span>
        <span class="state-title">试点视图异常</span>
        <span class="state-desc">其余功能不受影响。</span>
        <span class="state-desc" style="font-family:var(--mono);font-size:11.5px">${escapeHtml(String((err && err.message) || err))}</span>
      </div>`;
  };

  app.mount(host);
  return app;
}

function escapeHtml(s) {
  const el = document.createElement("div");
  el.textContent = s;
  return el.innerHTML;
}
