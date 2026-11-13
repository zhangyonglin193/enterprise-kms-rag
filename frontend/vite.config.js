import { fileURLToPath } from "node:url";
import path from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..");

export default defineConfig({
  plugins: [vue()],

  // Vite 在 **lib 模式**下不会像 app 模式那样替浏览器消除 process.env.NODE_ENV
  // —— 它假设产物会由下游打包器再处理，于是把这处判定留给对方。
  // 但本项目 dist/ 是直接挂到浏览器跑的，而 Vue 的 esm-bundler 版本里遍布
  // `process.env.NODE_ENV !== "production"` 的 dev-only 分支，浏览器没有
  // process 全局，结果模块一执行就抛 "process is not defined"（首帧即炸）。
  //
  // 显式替换成字面量后有两个收益：
  //   1. 浏览器不再缺 process 变量；
  //   2. 那些 !== "production" 的分支恒为 false，会被摇掉，产物体积反而更小。
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },

  // 试用 TS 之前先不做转换；这里只是预留的别名，方便组件按逻辑层引用源码。
  resolve: {
    alias: {
      // Vue 组件复用既有分层（core / sdk），不另起炉灶：
      // 权限显示走 js/core/policy.js（有 node --test 覆盖的纯函数），
      // 数据请求走 js/sdk/kms-client.js（三处消费方共用的单一客户端）。
      "@kms": path.resolve(repo, "kms/web/js"),
    },
  },

  // dev server 需要读仓库根才能解析 @kms 别名（构建期 rollup 直接读磁盘，不受限）
  server: { fs: { allow: [repo] } },

  build: {
    // 产物落在 kms/web/dist/：/static 挂载 kms/web（run_kms.py:311），
    // 故组件可用 /static/dist/knowledge-list.js 引用到自身产物，无需任何外链。
    outDir: path.resolve(repo, "kms/web/dist"),
    emptyOutDir: true,

    // **必须自包含**：内网零运行期外链，Vue 运行时要打进产物，
    // 不能设为 external 去 CDN 取。这是本项目部署红线。
    lib: {
      entry: path.resolve(here, "src/main.js"),
      formats: ["es"],
      fileName: () => "knowledge-list.js",
      cssFileName: "knowledge-list",
    },

    sourcemap: false,
  },
});
