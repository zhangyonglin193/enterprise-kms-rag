#!/usr/bin/env bash
# 前台启动；Ctrl+C 退出。后台生产托管使用 systemd，不保存不可信 PID 文件。
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/venv/bin/python" "$ROOT/scripts/manage.py" "${1:-all}"
