/* ===== app/main.js · 完整 Vue 工作台入口 =====
 *
 * 与试点（src/main.js）同一套路：**library 模式**对外只暴露 mount()，
 * 由宿主页面主动挂载，而不是像 SPA 那样接管整个 document。好处是：
 *   - 可以和既有工作台并存，出问题只影响挂载点内；
 *   - 回退时删掉挂载点即可，不需要回滚任何既有文件。
 *
 * 产物落在 kms/web/dist-app/kms-app.js（见 vite.app.config.js），
 * **刻意不覆盖 dist/**——后者是知识浏览试点的产物。
 */
import { createApp } from "vue";

import { api } from "./api.js";
import { resetSession, toast } from "./store.js";
import App from "./App.vue";

// 401 统一回退登录态。挂在客户端单例上，所有端点共享这一条策略，
// 避免每个视图各自判断 401。
api.onUnauthorized = () => { resetSession(); };

export function mount(target) {
  const host = typeof target === "string" ? document.querySelector(target) : target;
  if (!host) throw new Error(`[kms-app] 挂载点不存在: ${target}`);

  const app = createApp(App);

  // 生产级错误兜底：单组件异常 → toast 提示 + 控制台留痕，应用**继续存活**。
  // 绝不在此替换 host.innerHTML——那会连根拔掉 Vue 应用，一个视图的渲染
  // 异常就把整个工作台打成白屏。组件级隔离由 App.vue 的 onErrorCaptured
  // 兜底渲染（局部错误面板），两层配合保证异常影响面最小。
  app.config.errorHandler = (err, _instance, info) => {
    console.error("[kms-app]", info, err);
    toast("界面异常：" + String((err && err.message) || err), "error");
  };

  app.mount(host);
  return app;
}

export { api, toast };
