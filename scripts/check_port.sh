#!/usr/bin/env bash
# 只读排查指定服务端口；不终止进程、不自动换端口。
set -euo pipefail
if ! command -v ss >/dev/null 2>&1; then
    printf '需要系统提供 ss 命令；本脚本不自动安装软件。\n' >&2
    exit 2
fi
ports=(6341 6342 6343 6344 6345 6346 6347 6348 6349 6350)
if [[ $# -gt 0 ]]; then
    if [[ ! "$1" =~ ^(634[1-9]|6350)$ ]]; then
        printf '只允许检查 6341～6350。\n' >&2
        exit 2
    fi
    ports=("$1")
fi
occupied=0
for port in "${ports[@]}"; do
    result=$(ss -H -ltn "sport = :${port}")
    if [[ -n "$result" ]]; then
        printf '%s 已占用，请核实所属服务；不要强制抢占。\n%s\n' "$port" "$result"
        occupied=1
    else
        printf '%s 当前未发现监听；最终以受控启动器的绑定结果为准。\n' "$port"
    fi
done
exit "$occupied"
