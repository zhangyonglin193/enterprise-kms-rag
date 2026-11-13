/* ESLint flat config（eslint 9）：只守**错误级**红线，不搞风格洁癖。
 *
 * 规则集 vue3-essential（编译/运行期会真出错的模式：v-model 双绑冲突、
 * 重复 key、无效指令等）。风格问题（引号/分号/缩进）不拦——现有代码
 * 风格已统一，引入格式化工具只会制造无谓 diff。
 *
 * 检查范围：src/ 的 .js 与 .vue；dist* 产物不查。
 * 运行：npx eslint src （CI 门禁可直接挂这条命令的退出码）。 */
import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";

export default [
  { ignores: ["dist/**", "dist-app/**", "node_modules/**"] },
  js.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        // 浏览器宿主：库模式挂载在既有页面里，全局只有 BOM/DOM
        window: "readonly", document: "readonly", console: "readonly",
        navigator: "readonly", URL: "readonly", URLSearchParams: "readonly",
        Blob: "readonly",
        File: "readonly", FormData: "readonly", fetch: "readonly",
        setTimeout: "readonly", setInterval: "readonly",
        clearTimeout: "readonly", clearInterval: "readonly",
        performance: "readonly", location: "readonly", localStorage: "readonly",
        sessionStorage: "readonly", HTMLElement: "readonly",
        DOMParser: "readonly", CustomEvent: "readonly",
      },
    },
    rules: {
      // 生产级收紧：未用变量往往是改漏的死代码，但下划线前缀的
      // 形参（如 errorHandler 的 _instance）是刻意忽略，放行。
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      // console 允许：兜底日志（errorHandler）必须留 console.error
      "no-console": "off",
    },
  },
];
