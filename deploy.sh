#!/usr/bin/env bash
# 非破坏性安装：不覆盖配置、不清库、不入库、不开放防火墙。
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,12), "请使用 Python 3.10～3.12（建议3.11）"'
if [ ! -d "$ROOT/venv" ]; then
  "$PYTHON" -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
"$ROOT/venv/bin/python" -m pip check
"$ROOT/venv/bin/python" -m pip freeze > "$ROOT/requirements.resolved.txt"
printf '%s\n' '依赖安装完成。请按 DEPLOY.md 配置独立的 .env/.env.kms 和数据库；未执行入库或启动。'
