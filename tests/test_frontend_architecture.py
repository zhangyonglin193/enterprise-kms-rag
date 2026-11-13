"""前端架构约束回归（离线，无 JS 运行时依赖）。

本机无 node 运行时（Windows 开发机仅 cscript/JScript），因此行为级测试
（tests/frontend/*.test.js）在 CI 的 node 环境执行；本文件守住**架构红线**，
这些约束用静态检查即可验证，且一旦破坏即意味着企业级部署属性失效：

  1. 零运行期外链：kms/web 下禁止引用公网 CDN/外部脚本（内网部署红线）；
  2. Vue 工作台结构：根入口挂载 dist-app 构建产物，源码树（frontend/）完整；
  3. SDK 能力面：与后端 REST 及 MCP 工具面对应的关键方法必须存在（复用契约）；
  4. 安全约束在位：同源校验、令牌不得外转、Markdown 先转义后渲染；
  5. 发布完整性：共享层、构建产物与 Vue 源码必须进入发布白名单。
"""
from __future__ import annotations

import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "kms" / "web"
JS = WEB / "js"
FRONTEND = ROOT / "frontend"

REQUIRED_MODULES = [
    "index.html",
    "style.css",
    "knowledge-widget.js",
    "js/core/dom.js",      # widget 与 md.js 的 escapeHtml 依赖
    "js/core/http.js",
    "js/core/policy.js",
    "js/ui/md.js",
    "js/sdk/kms-client.js",
    "dist-app/kms-app.js",  # Vue 工作台构建产物（vite.app.config.js）
    "dist-app/kms-app.css",
]

# SDK 必须提供的能力面（与 gateway/mcp/schemas.py 工具面及 /kms/api 路由对应）
SDK_REQUIRED_METHODS = [
    "login", "logout", "me", "ask", "askStream", "feedback",
    "search", "listDocuments", "document", "recommendations",
    "upload", "propose", "decide", "auditEvents",
    "mcpCall", "mcpTools", "mcpMetrics",
]


def read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


class ZeroExternalDependencyTests(unittest.TestCase):
    """内网部署红线：运行期不得引用任何外部资源。"""

    def test_no_external_script_or_link(self):
        offenders = []
        for path in WEB.rglob("*"):
            if not path.is_file() or path.suffix not in {".html", ".js", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)["\']', text):
                offenders.append(f"{path.relative_to(ROOT)} -> {match.group(1)}")
        self.assertEqual(offenders, [], "发现运行期外链，内网部署不可接受：" + "; ".join(offenders))

    def test_no_cdn_import_inside_modules(self):
        for path in JS.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"""import\s+.*["']https?://""", f"{path.name} 不得从外网 import")

    def test_markdown_is_self_contained(self):
        text = read("js/ui/md.js")
        self.assertIn("escapeHtml", text)      # 先转义再渲染
        self.assertNotIn("window.marked", text)  # 不再依赖 CDN 版 marked


class ModuleLayoutTests(unittest.TestCase):
    def test_required_modules_exist(self):
        missing = [rel for rel in REQUIRED_MODULES if not (WEB / rel).is_file()]
        self.assertEqual(missing, [], f"缺少模块: {missing}")

    def test_entry_mounts_vue_bundle(self):
        """根路径入口必须挂载 Vue 构建产物（经典脚本前端已退役删除）。"""
        html = read("index.html")
        self.assertRegex(html, r'<script type="module">')
        self.assertIn('"/static/dist-app/kms-app.js"', html)
        self.assertIn("kms-app-root", html)
        # 不得再引用已退役的经典脚本装配链
        self.assertNotIn("/static/js/app.js", html)
        self.assertNotIn("/static/app.js", html)

    def test_vue_sources_exist(self):
        """Vue 工作台源码结构完整（frontend/ 为构建输入）。"""
        for rel in ("package.json", "vite.app.config.js",
                    "src/app/main.js", "src/app/App.vue", "src/app/api.js",
                    "src/app/store.js"):
            self.assertTrue((FRONTEND / rel).is_file(), f"缺少 frontend/{rel}")

    def test_sdk_is_single_client_for_all_channels(self):
        """工作台（Vue 源码）与嵌入组件必须共用同一客户端。"""
        widget = read("knowledge-widget.js")
        vue_api = (FRONTEND / "src" / "app" / "api.js").read_text(encoding="utf-8")
        for text in (widget, vue_api):
            self.assertIn("KmsClient", text, "工作台与嵌入组件必须共用同一客户端")
        self.assertRegex(vue_api, r"extends\s+KmsClient",
                         "Vue 工作台 api.js 必须继承 KmsClient，不得重写客户端")


class ImportGraphTests(unittest.TestCase):
    """静态校验 ES Module 导入图：路径可解析 + 命名导出齐全（无 node 运行时）。"""

    IMPORT_RE = re.compile(
        r'import\s+(?:(\*\s+as\s+\w+)|\{([^}]+)\}|(\w+))?\s*from\s*["\'](\.[^"\']+)["\']')
    EXPORT_RE = re.compile(r'export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)')
    EXPORT_LIST_RE = re.compile(r'export\s*\{([^}]+)\}', re.S)

    @classmethod
    def _exports(cls, path: Path) -> set:
        text = path.read_text(encoding="utf-8")
        names = set(cls.EXPORT_RE.findall(text))
        for block in cls.EXPORT_LIST_RE.findall(text):
            for item in block.split(","):
                item = item.strip()
                if item:
                    names.add(item.split(" as ")[-1].strip())
        return names

    @staticmethod
    def _source_js_files() -> list:
        """源码 JS 文件，**排除构建产物 dist/**。

        Vite 一旦做代码分割，产物里会出现扁平化的相对 import（如 ./chunk-abc.js），
        按源码规则校验必然失败——产物的正确性由构建工具保证，不该用源码规则卡它。
        Vue 试点落地前必须先加上这条排除，否则第一个 dist/ 产物就会让 CI 变红。
        """
        return [f for f in sorted(WEB.rglob("*.js"))
                if "dist" not in f.relative_to(WEB).parts]

    def test_all_relative_imports_resolve(self):
        errors = []
        for f in self._source_js_files():
            text = f.read_text(encoding="utf-8")
            for m in self.IMPORT_RE.finditer(text):
                spec = m.group(4)
                if not spec.startswith("."):
                    continue
                target = (f.parent / spec).resolve()
                if not target.is_file():
                    errors.append(f"{f.relative_to(ROOT)} -> 路径解析失败: {spec}")
                    continue
                named = m.group(2)
                if not named:
                    continue
                available = self._exports(target)
                for item in named.split(","):
                    name = item.strip().split(" as ")[0].strip()
                    if name and name not in available:
                        errors.append(f"{f.relative_to(ROOT)} -> {spec} 无导出: {name}")
        self.assertEqual(errors, [], "\n".join(errors))

    def test_build_output_excluded_from_import_graph(self):
        """dist/ 是构建产物，不参与导入图校验（见 _source_js_files 注释）。

        这条测试守住排除规则本身：只做路径运算、不依赖是否已有产物，
        所以 dist/ 目录还不存在时也能验证规则生效。
        """
        fake_chunk = WEB / "dist" / "js" / "chunk-abc123.js"
        self.assertIn("dist", fake_chunk.relative_to(WEB).parts)
        self.assertNotIn(fake_chunk, self._source_js_files())

        # 反向确认：普通源码文件仍会被纳入校验，排除规则没有误伤
        real_source = WEB / "js" / "core" / "policy.js"
        self.assertIn(real_source, self._source_js_files())


class SdkSurfaceTests(unittest.TestCase):
    def test_sdk_exposes_required_capabilities(self):
        text = read("js/sdk/kms-client.js")
        missing = [m for m in SDK_REQUIRED_METHODS if not re.search(rf"\b{m}\s*\(", text)]
        self.assertEqual(missing, [], f"SDK 缺少能力: {missing}")

    def test_sdk_maps_to_mcp_tool_surface(self):
        """前端 SDK 与 MCP 工具面一一对应（docs/mcp_engineering.md §5）。"""
        sdk = read("js/sdk/kms-client.js")
        mcp = (ROOT / "gateway" / "mcp" / "schemas.py").read_text(encoding="utf-8")
        alias = {
            "ask_question": "ask",
            "search_knowledge": "search",
            "get_document": "document",
            "list_documents": "listDocuments",
            "get_recommendations": "recommendations",
            "submit_feedback": "feedback",
            "submit_knowledge_request": "propose",
            "get_app_usage": "appUsage",
        }
        for tool in re.findall(r'"name": "([a-z_]+)"', mcp):
            expected = alias.get(tool, tool)
            self.assertIn(expected, sdk, f"MCP 工具 {tool} 在 SDK 中无对应实现（期望 {expected}）")


class SecurityConstraintTests(unittest.TestCase):
    def test_widget_enforces_same_origin(self):
        widget = read("knowledge-widget.js")
        self.assertIn("assertSameOrigin", widget)
        self.assertIn("禁止转发令牌到外部站点", read("js/core/http.js"))

    def test_widget_does_not_handle_app_key(self):
        """应用 Key 必须由宿主 BFF 持有，组件不得接触。"""
        widget = read("knowledge-widget.js")
        self.assertNotIn("X-API-Key", widget)

    def test_rendered_content_is_untrusted(self):
        widget = read("knowledge-widget.js")
        self.assertIn("renderMarkdown", widget)   # 安全 Markdown 渲染（先转义后渲染）
        self.assertIn("不执行支付、审批或链上交易", widget)


class PackagingTests(unittest.TestCase):
    def test_new_modules_and_docs_are_packaged(self):
        from scripts.package_release import release_files

        names = {p.relative_to(ROOT).as_posix() for p in release_files()}
        for rel in REQUIRED_MODULES:
            self.assertIn(f"kms/web/{rel}", names, f"{rel} 未进入发布包")
        self.assertIn("docs/frontend_architecture.md", names)
        self.assertIn("docs/mcp_engineering.md", names)

    def test_vue_sources_are_packaged(self):
        """Vue 源码必须随包发布（否则产物损坏后无法重建前端）。"""
        from scripts.package_release import release_files

        names = {p.relative_to(ROOT).as_posix() for p in release_files()}
        for rel in ("frontend/package.json", "frontend/vite.app.config.js",
                    "frontend/src/app/main.js", "frontend/src/app/App.vue",
                    "frontend/src/app/api.js"):
            self.assertIn(rel, names, f"{rel} 未进入发布包")
        # node_modules 绝不能混进发布包（体积与许可风险）
        self.assertFalse(any(n.startswith("frontend/node_modules/") for n in names),
                         "node_modules 不得进入发布包")


class FrontendTestImportContractTests(unittest.TestCase):
    """tests/frontend/*.test.js 的 import 契约（窄范围：只查存在性）。

    为什么用 Python 做：开发机没有 node 运行时，`node --test tests/frontend/`
    只能在 CI 跑。本地改了测试文件、引用了一个不存在的导出，要等 CI 才报错——
    而这类错误会让**整个测试文件加载失败**，同文件其余用例全部不执行，
    表现为"测试变少"而非"测试变红"，极易被忽略。

    这里只做**静态存在性校验**：import 路径可解析、具名导出确实存在。
    不解析语法、不执行断言——那是 node --test 的职责。范围刻意收窄。
    """

    IMPORT_RE = re.compile(
        r'import\s+(?:(\*\s+as\s+\w+)|\{([^}]+)\}|(\w+))?\s*from\s+["\'](\.[^"\']+)["\']')
    # 覆盖 `const { a, b } = await import("...")`（node --test 常用写法）
    DYNAMIC_IMPORT_RE = re.compile(
        r'(?:const|let|var)\s*\{([^}]+)\}\s*=\s*await\s+import\(\s*["\'](\.[^"\']+)["\']\s*\)')
    EXPORT_RE = re.compile(
        r'export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)')
    EXPORT_LIST_RE = re.compile(r'export\s*\{([^}]+)\}', re.S)

    @classmethod
    def _exports(cls, path: Path) -> set:
        text = path.read_text(encoding="utf-8")
        names = set(cls.EXPORT_RE.findall(text))
        for block in cls.EXPORT_LIST_RE.findall(text):
            for item in block.split(","):
                item = item.strip()
                if item:
                    names.add(item.split(" as ")[-1].strip())
        return names

    def _check(self, test_file: Path, text: str) -> list:
        errors = []
        pairs = []
        for m in self.IMPORT_RE.finditer(text):
            pairs.append((m.group(2), m.group(4)))
        for m in self.DYNAMIC_IMPORT_RE.finditer(text):
            pairs.append((m.group(1), m.group(2)))
        for named, spec in pairs:
            if not named:
                continue
            target = (test_file.parent / spec).resolve()
            if not target.is_file():
                errors.append(f"{test_file.name} -> 路径解析失败: {spec}")
                continue
            available = self._exports(target)
            for item in named.split(","):
                name = item.strip().split(" as ")[0].strip()
                if name and name not in available:
                    errors.append(f"{test_file.name} -> {spec} 无导出: {name}")
        return errors

    def test_frontend_tests_import_existing_exports(self):
        errors = []
        for f in sorted((ROOT / "tests" / "frontend").glob("*.test.js")):
            errors.extend(self._check(f, f.read_text(encoding="utf-8")))
        self.assertEqual(errors, [], "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
