import { fileURLToPath } from "node:url";
import path from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");

export default defineConfig({
  plugins: [vue()],

  // 同 vite.config.js：lib 模式下 Vite 不会替浏览器消除 process.env.NODE_ENV，
  // 而 Vue esm-bundler 遍布 `process.env.NODE_ENV !== "production"` 的 dev 分支，
  // 浏览器没有 process 全局 → 首帧即抛 "process is not defined"。
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },

  resolve: {
    alias: {
      // 复用既有分层，不另起炉灶：权限判定走 js/core/policy.js（有 node --test
      // 覆盖的纯函数），请求走 js/sdk/kms-client.js（单一客户端）。
      "@kms": path.resolve(repo, "kms/web/js"),
    },
  },

  server: { fs: { allow: [repo] } },

  build: {
    // 产物落在 kms/web/dist-app/：**刻意不复用 dist/**。
    // dist/ 是知识浏览试点（knowledge-list.js）的产物，emptyOutDir 会把它一起
    // 清掉。完整应用先独立构建、独立验证，确认与现有前端等价后再统一切换。
    outDir: path.resolve(repo, "kms/web/dist-app"),
    emptyOutDir: true,

    // 必须自包含：内网零运行期外链，Vue 运行时打进产物。这是部署红线。
    lib: {
      entry: path.resolve(here, "src/app/main.js"),
      formats: ["es"],
      fileName: () => "kms-app.js",
      cssFileName: "kms-app",
    },

    // hidden：生成 .map 供生产排障（拿到产物 + map 即可还原源码栈），
    // 但产物本身不引用——浏览器 DevTools 默认不可见，不向使用者暴露源码。
    sourcemap: "hidden",
  },
});
