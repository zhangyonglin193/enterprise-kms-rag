"""白名单打包代码：默认不包含数据、原始知识、凭据、虚拟环境或历史文档。"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
TOP = {"config.py", "run_kms.py", "api.py", "requirements.txt", "DEPLOY.md", ".env.example", ".env.kms.example",
       "deploy.sh", "deploy_full.sh", "start.sh", "stop.sh", "start_local.bat", "rag.service", "kms.service", ".gitignore"}
DOCS = {"gateway_architecture.md", "gateway_api_reference.md", "enterprise_delivery.md",
        "mcp_engineering.md", "frontend_architecture.md"}
SCRIPTS = {"service.py", "manage.py", "bootstrap_employee.py", "package_release.py", "check_port.sh", "ingest_batch.py", "reingest_all.py", "eval_accuracy.py", "eval_on_server.sh"}


def release_files():
    result = []
    candidates = [ROOT / name for name in TOP]
    for directory in ("app", "kms", "gateway", "examples", "tests", "docs", "scripts", "frontend"):
        candidates.extend((ROOT / directory).rglob("*"))
    for path in candidates:
        rel = path.relative_to(ROOT)
        if path.is_symlink() or not path.is_file() or any((ROOT.joinpath(*rel.parts[:n])).is_symlink() for n in range(1, len(rel.parts))):
            continue
        if "__pycache__" in rel.parts or "node_modules" in rel.parts or path.suffix in (".pyc", ".tmp"):
            continue
        include = (len(rel.parts) == 1 and path.name in TOP
                   or rel.parts[0] in {"app", "kms", "gateway", "examples", "tests"} and path.suffix in {".py", ".html", ".js", ".css"}
                   or rel.parts[0] == "frontend" and path.suffix in {".js", ".mjs", ".cjs", ".vue", ".json", ".html", ".css"}
                   or rel.parts[0] == "docs" and len(rel.parts) == 2 and path.name in DOCS
                   or rel.parts[0] == "scripts" and len(rel.parts) == 2 and path.name in SCRIPTS)
        if include:
            result.append(path)
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅校验清单，不创建压缩包")
    args = parser.parse_args()
    files = release_files()
    if args.check:
        print(f"白名单包含 {len(files)} 个代码/模板/当前文档文件；数据与真实配置不在清单内。")
        return
    output = ROOT / "dist" / ("enterprise-rag-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".tar.gz")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    print(f"已生成代码包：{output}；请独立备份并经审批传输数据。")


if __name__ == "__main__":
    main()
