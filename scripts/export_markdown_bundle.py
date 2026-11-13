#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把项目「主体文档 + 核心源码」汇总导出为单一 Markdown 文档。

用法:
    python scripts/export_markdown_bundle.py                  # 输出 PROJECT_FULL_BUNDLE.md
    python scripts/export_markdown_bundle.py -o out/ALL.md    # 自定义输出路径

收录范围（与「核心链路 + 全套文档」契约一致）:
    文档  AGENTS.md / docs/*.md / 根目录规格与部署文档 / 交付文档/*.md
    代码  根目录 api.py、config.py、run_kms.py + app/ + kms/ + gateway/ + frontend/src/

刻意不收录: tests/、scripts/、data/、RAG_repository/ 语料、二进制交付物
（docx/pdf/pptx/png）、虚拟环境、node_modules 与各类缓存。清单见文末附录 B。
"""
from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# —— 文档收录顺序：先总体设计，再分域专项，最后规格与交付 ——
DOC_FILES = [
    "AGENTS.md",
    "docs/系统总体设计说明书.md",
    "docs/architecture.md",
    "docs/business_flow.md",
    "docs/database_design.md",
    "docs/module_spec.md",
    "docs/gateway_architecture.md",
    "docs/gateway_api_reference.md",
    "docs/frontend_architecture.md",
    "docs/mcp_engineering.md",
    "docs/enterprise_delivery.md",
    "docs/知识服务说明.md",
    "docs/KMS_竞赛系统设计方案.md",
    "docs/PROJECT_ANALYSIS.md",
    "docs/project_analysis_report.md",
    "docs/qa_preparation.md",
    "docs/defense_script.md",
    "DEPLOY.md",
    "HOST_DEPLOY_CHECKLIST.md",
    "spec.md",
    "spec_versioning.md",
    "tasks.md",
    "tasks_versioning.md",
    "checklist.md",
    "交付文档/系统说明文档.md",
    "交付文档/答辩演讲稿.md",
]

ROOT_CODE_FILES = ["api.py", "config.py", "run_kms.py"]

# 代码目录分组：(分组标题, 目录, 说明)
CODE_GROUPS = [
    ("app/ —— QA 赛题问答服务（端口 6341）", "app",
     "检索、生成、缓存、服务生命周期；对外仅暴露 /chat 等问答接口，无员工认证。"),
    ("kms/ —— 企业知识管理核心（端口 6342）", "kms",
     "权限矩阵、用户与组织、文档审批、推荐、版本、限流。企业数据面。"),
    ("gateway/ —— API 网关（对外入口）", "gateway",
     "嵌入 API、飞书/企微机器人、MCP 知识服务、速率限制与审计。"),
    ("frontend/src —— KMS 前端（Vue 3）", "frontend",
     "组合式 API + 视图组件；页面全部走后端鉴权，前端不承载权限判定。"),
]

CODE_EXT = {".py", ".vue", ".js", ".ts", ".css", ".html"}
SKIP_PARTS = {"__pycache__", "node_modules", "dist", ".venv", "venv", "build", ".ruff_cache"}


def _skipped(p: Path) -> bool:
    """构建产物（dist/、dist-app/）、依赖目录与字节码缓存不进文档。"""
    for part in p.parts:
        if part in SKIP_PARTS or part.startswith("dist-"):
            return True
    return p.suffix in {".map", ".min.js", ".min.css"}

LANG = {".py": "python", ".vue": "vue", ".js": "javascript", ".ts": "typescript",
        ".css": "css", ".html": "html", ".md": "markdown", ".bat": "bat", ".sh": "bash",
        ".txt": "text", ".json": "json", ".toml": "toml", ".env": "ini"}

EXCLUDE_DOC_HINTS = ("副本", "_旧版存档", "PROJECT_ANALYSIS.docx")

_used_anchors: set[str] = set()


def slugify(text: str) -> str:
    """近似 GitHub 标题锚点：小写、去标点、空白转连字符，重复则追加序号。"""
    s = text.strip().lower()
    # 与 GitHub 渲染器保持一致：标点（含 . / · 等）一律剔除，仅留字母数字下划线连字符
    s = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", s)
    s = re.sub(r"\s+-\s*", "-", s)
    s = re.sub(r"[\s]+", "-", s)
    base, i = s, 1
    while s in _used_anchors:
        s = f"{base}-{i}"
        i += 1
    _used_anchors.add(s)
    return s


def read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def fence_for(body: str) -> str:
    """围栏长度必须大于正文中最长的连续反引号，避免内容截断代码块。"""
    longest = max((len(m) for m in re.findall(r"`+", body)), default=0)
    return "`" * max(3, longest + 1)


def code_block(body: str, lang: str) -> str:
    f = fence_for(body)
    return f"{f}{lang}\n{body.rstrip()}\n{f}\n"


def collect(dir_path: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(dir_path.rglob("*")):
        if not p.is_file():
            continue
        if _skipped(p):
            continue
        if p.suffix.lower() not in CODE_EXT:
            continue
        files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="导出项目代码与文档全集为单一 Markdown")
    ap.add_argument("-o", "--output", default="PROJECT_FULL_BUNDLE.md", help="输出文件路径")
    args = ap.parse_args()

    out_path = (BASE / args.output) if not Path(args.output).is_absolute() else Path(args.output)
    today = datetime.date.today().isoformat()

    # —— 阶段一：清点文件，先算统计再决定目录结构 ——
    docs: list[tuple[str, Path, str]] = []
    for rel in DOC_FILES:
        p = BASE / rel
        if not p.is_file() or any(h in rel for h in EXCLUDE_DOC_HINTS):
            continue
        docs.append((rel, p, read_text(p)))

    root_code = [(f, BASE / f, read_text(BASE / f)) for f in ROOT_CODE_FILES if (BASE / f).is_file()]

    groups: list[tuple[str, str, str, list[tuple[str, Path, str]]]] = []
    for title, sub, desc in CODE_GROUPS:
        root = BASE / sub
        if not root.is_dir():
            continue
        items = []
        for p in collect(root):
            rel = p.relative_to(BASE).as_posix()
            if "/src/" not in "/" + rel and sub == "frontend":
                continue  # frontend 只收 src/ 下的业务源码
            items.append((rel, p, read_text(p)))
        groups.append((title, sub, desc, items))

    doc_lines = sum(b.count("\n") + 1 for _, _, b in docs)
    code_all = root_code + [x for g in groups for x in g[3]]
    code_lines = sum(b.count("\n") + 1 for _, _, b in code_all)

    buf: list[str] = []
    w = buf.append

    # —— 封面 ——
    w("# 银联商务 RAG + KMS 系统 · 代码与文档全集")
    w("")
    w("> 本文档由 `scripts/export_markdown_bundle.py` 自动生成，内容为项目源码与设计文档的逐字快照，")
    w("> 不含任何凭据、密钥或个人数据。修改代码后重新执行脚本即可刷新，不必手工维护。")
    w("")
    w("| 项目 | 值 |")
    w("|---|---|")
    w(f"| 生成时间 | {today} |")
    w(f"| 文档章节 | {len(docs)} 篇 / {doc_lines} 行 |")
    w(f"| 源码文件 | {len(code_all)} 个 / {code_lines} 行 |")
    w("| 双服务端口 | QA 问答 6341、KMS 知识管理 6342（不可互换） |")
    w("")
    w("## 阅读指引")
    w("")
    w("- **第一部分 项目总览**：一分钟看懂架构边界与不可违反的约束，适合评审开场。")
    w("- **第二部分 文档全集**：设计说明书、网关/MCP/前端专项文档、部署与规格文档。")
    w("- **第三部分 源码全集**：按 app → kms → gateway → frontend 的依赖顺序排列，可直接通读。")
    w("- **附录**：文件统计与未收录清单，便于核对完整性。")
    w("")

    # —— 目录（H2/H3 两级，带锚点） ——
    w("## 目录")
    w("")
    toc: list[str] = []
    for rel, _, _ in docs:
        title = rel
        toc.append(f"  - [{title}](#{slugify(title)})")
    # 先占位，稍后按真实生成顺序回填；这里用二级缩进与第三部分区分
    w("- 第一部分 · 项目总览")
    w("  - [系统定位与双服务边界](#系统定位与双服务边界)")
    w("  - [模块职责与不可混淆的边界](#模块职责与不可混淆的边界)")
    w("  - [五条硬约束（改代码前必读）](#五条硬约束改代码前必读)")
    w("  - [安全关键路径清单](#安全关键路径清单)")
    w("- 第二部分 · 文档全集")
    for line in toc:
        w(line)
    w("- 第三部分 · 源码全集")
    for rel, _, _ in root_code:  # 顺序与正文一致，避免同名锚点自增序号错位
        w(f"  - [{rel}](#{slugify(rel)})")
    for title, _, _, items in groups:
        # 分组标题含破折号与全角括号，各家渲染器的锚点规则不一致，故不给链接
        w(f"  - **{title}**")
        for rel, _, _ in items:
            w(f"    - [{rel}](#{slugify(rel)})")
    w("- 附录")
    w("  - [附录 A · 文件统计](#附录-a--文件统计)")
    w("  - [附录 B · 未收录内容与再生成方式](#附录-b--未收录内容与再生成方式)")
    w("")

    # —— 第一部分：总览（人工撰写的口径，与 AGENTS.md 一致） ——
    w("---")
    w("")
    w("## 第一部分 · 项目总览")
    w("")
    w("### 系统定位与双服务边界")
    w("")
    w("同一代码库内置两套服务，共用检索内核但数据面严格隔离：")
    w("")
    w("| 服务 | 端口 | 职责 | 安全级别 |")
    w("|---|---|---|---|")
    w("| QA 问答 | 6341（固定） | 赛题 `/chat` 评测接口，无员工认证，仅装载竞赛公开资料 | 低（公开评测） |")
    w("| KMS 企业知识管理 | 6342～6350 | 权限体系、文档审批、推荐、API 网关、MCP 知识服务 | 高（企业数据） |")
    w("")
    w("QA 与 KMS 必须使用**不同数据库、不同 FAISS 索引、不同数据目录**，启动器 `scripts/service.py`")
    w("在启动前完成隔离校验，路径相互包含（含父子关系）即拒绝启动。")
    w("")
    w("### 模块职责与不可混淆的边界")
    w("")
    w("| 模块 | 路径 | 职责 |")
    w("|---|---|---|")
    w("| QA 问答 | `app/` + `api.py` | 赛题 `/chat` 接口、检索与生成管线 |")
    w("| KMS 核心 | `kms/` | 权限矩阵、用户组织、文档审批、推荐、版本 |")
    w("| API 网关 | `gateway/` | 嵌入 API、飞书/企微机器人、MCP 服务、限流与审计 |")
    w("| 配置 | `config.py` | 全局配置 + 端口/角色/CORS 校验 |")
    w("| 启动器 | `scripts/service.py` | 跨平台受控启动，端口冲突即退出 |")
    w("| 测试 | `tests/` | 离线安全回归，不连接真实 DB/模型 |")
    w("")
    w("### 五条硬约束（改代码前必读）")
    w("")
    w("1. **端口不可变**：QA 固定 6341，KMS 在 6342～6350；冲突时退出，不自动换端口、不杀其他进程。")
    w("2. **数据隔离强制**：QA/KMS 的 MySQL 库、FAISS 索引、上传目录、文档目录完全独立且互不包含。")
    w("3. **权限矩阵安全**：BLP 强制访问控制叠加密级、部门、审批状态、生命周期；禁止自审批；")
    w("   管理员与审计员角色不可重叠，维护员与审批员不可重叠。")
    w("4. **CORS 收敛**：KMS 来源必须显式列出，禁止通配符 `*`（QA 因无认证是例外，不可效仿）。")
    w("5. **QA 冻结面**：`app/` 与 `api.py` 由 CI 守卫；KMS 进程不得注册 `/chat`。")
    w("")
    w("### 安全关键路径清单")
    w("")
    w("```")
    for line in (
        "config.py              → 端口/角色/CORS 校验",
        "scripts/service.py     → 启动前环境隔离 + 端口绑定",
        "gateway/middleware.py  → 网关速率限制 + 审计",
        "gateway/service.py     → 文档权限判定 allowed()",
        "gateway/crypto.py      → 飞书/企微消息加解密",
        "kms/security.py        → JWT 签发/验证 + AuthUser",
        "kms/access_control.py  → BLP 权限表 + 角色管理",
        "app/main.py            → QA 服务生命周期",
        "run_kms.py             → KMS 服务生命周期 + FAISS Unicode 补丁",
    ):
        w(line)
    w("```")
    w("")
    w("")

    # —— 第二部分：文档全集 ——
    w("---")
    w("")
    w("## 第二部分 · 文档全集")
    w("")
    w("> 以下为各文档原文逐字收录；原文按 `h2→h3` 下沉一级，避免与本文档目录层级冲突。")
    w("")
    for rel, p, body in docs:
        w(f"### {rel}")
        w("")
        w(f"*源文件：`{rel}` ｜ {len(body.encode('utf-8'))} 字节 ｜ {body.count(chr(10)) + 1} 行*")
        w("")
        w(code_block(body, "markdown"))
        w("")

    # —— 第三部分：源码全集 ——
    w("---")
    w("")
    w("## 第三部分 · 源码全集")
    w("")
    w("> 按「入口配置 → 业务内核 → 对外网关 → 前端」的依赖方向排列，便于顺序通读。")
    w("")
    w("### 根目录 · 服务入口与全局配置")
    w("")
    for rel, p, body in root_code:
        w(f"#### {rel}")
        w("")
        w(f"*`{rel}` ｜ {len(body.encode('utf-8'))} 字节 ｜ {body.count(chr(10)) + 1} 行*")
        w("")
        w(code_block(body, LANG.get(p.suffix.lower(), "")))
        w("")

    for title, _, desc, items in groups:
        w(f"### {title}")
        w("")
        w(f"> {desc}")
        w("")
        for rel, p, body in items:
            w(f"#### {rel}")
            w("")
            w(f"*`{rel}` ｜ {len(body.encode('utf-8'))} 字节 ｜ {body.count(chr(10)) + 1} 行*")
            w("")
            w(code_block(body, LANG.get(p.suffix.lower(), "")))
            w("")

    # —— 附录 ——
    w("---")
    w("")
    w("## 附录 A · 文件统计")
    w("")
    w("| 分组 | 文件数 | 行数 |")
    w("|---|---:|---:|")
    w(f"| 文档（第二部分） | {len(docs)} | {doc_lines} |")
    w(f"| 根目录入口代码 | {len(root_code)} | "
      f"{sum(b.count(chr(10)) + 1 for _, _, b in root_code)} |")
    for title, _, _, items in groups:
        w(f"| {title.split(' —— ')[0]} | {len(items)} | "
          f"{sum(b.count(chr(10)) + 1 for _, _, b in items)} |")
    w(f"| **合计** | **{len(docs) + len(code_all)}** | **{doc_lines + code_lines}** |")
    w("")
    w("### 附录 B · 未收录内容与再生成方式")
    w("")
    w("按「核心链路 + 全套文档」口径，以下内容**有意未收录**：")
    w("")
    w("| 未收录 | 原因 |")
    w("|---|---|")
    w("| `tests/`（26 个文件） | 离线安全回归用例，属验证资产而非运行链路 |")
    w("| `scripts/`（39 个文件） | 入库、评测、部署、打包等运维脚本 |")
    w("| `data/`、`RAG_repository/` | 数据库导出、FAISS 索引与 121 份赛题语料，体积大且含业务内容 |")
    w("| `frontend/dist/`、`node_modules/`、`__pycache__/` | 构建产物、第三方依赖与字节码缓存 |")
    w("| `*.docx` / `*.pdf` / `*.pptx` / `*.png` | 二进制交付物，Markdown 无法无损承载 |")
    w("| `docs/PROJECT_ANALYSIS - 副本.md`、`交付文档/_旧版存档/` | 历史副本，内容已被正本覆盖 |")
    w("")
    w("再生成：")
    w("")
    w("```bash")
    w("python scripts/export_markdown_bundle.py              # 覆盖默认输出 PROJECT_FULL_BUNDLE.md")
    w("python scripts/export_markdown_bundle.py -o docs/ALL.md  # 指定输出路径")
    w("```")
    w("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(buf)
    out_path.write_text(text, encoding="utf-8")

    size_mb = len(text.encode("utf-8")) / 1024 / 1024
    print(f"已生成: {out_path}")
    print(f"文档 {len(docs)} 篇 / 源码 {len(code_all)} 个 / 合计 {text.count(chr(10)) + 1} 行 / {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
