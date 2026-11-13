#!/usr/bin/env bash
# 只停止本项目已安装的用户级 systemd 单元，不按进程名或遗留 PID 杀进程。
set -euo pipefail
case "${1:-all}" in
  qa) units=(rag.service) ;;
  kms) units=(kms.service) ;;
  all) units=(rag.service kms.service) ;;
  *) printf '%s\n' '用法：bash stop.sh [qa|kms|all]'; exit 2 ;;
esac
printf '%s\n' '仅适用于 DEPLOY.md 中安装的用户级 systemd 服务。前台 start.sh 请在原窗口 Ctrl+C。'
exec systemctl --user stop "${units[@]}"
