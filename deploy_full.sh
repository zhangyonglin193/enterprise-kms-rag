#!/usr/bin/env bash
# 兼容旧命令：仅执行非破坏安装，不再清库、停进程、覆盖配置或删除索引。
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
printf '%s\n' '原重置式部署已停用；现转入安全安装。数据迁移须按 DEPLOY.md 单独审批执行。'
exec bash "$ROOT/deploy.sh" "$@"
