#!/usr/bin/env bash
# 在服务器（Xshell）上对运行中的 QA 服务做端到端准确率评测。
#
# 特点：
# - 只依赖 Python 标准库，走 HTTP /chat，不碰 MySQL/FAISS，服务在线即可跑，无需停服。
# - 打的是本机已部署的那套库（服务器上是多少块就测多少块），结果直接反映线上真实水位。
# - 评分口径透明：正确率(严格/宽松) + 关键事实覆盖率 + 单题延迟，明细存 JSON 可复核。
#
# 用法（在项目根目录）:
#   bash scripts/eval_on_server.sh                          # 默认：知识库专项·全新角度 100 题
#   bash scripts/eval_on_server.sh data/adv100_set.md       # 指定测试集（进阶 100）
#   bash scripts/eval_on_server.sh data/union100_regression.md
#   WORKERS=2 bash scripts/eval_on_server.sh                # 降并发（模型限流/怕影响线上时）
#   BASE=http://127.0.0.1:6341 bash scripts/eval_on_server.sh   # 指定服务地址（默认本机 6341）
#
# 前置：需先用 Xftp 把测试集 .md 传到 data/ 下（评测脚本与 .md 都不随发布包附带数据）。
set -euo pipefail
cd "$(dirname "$0")/.."

MD="${1:-data/知识库专项测试题100道（全新角度版）.md}"
OUT="${2:-data/eval_server_$(date +%Y%m%d_%H%M%S).json}"
BASE="${BASE:-http://127.0.0.1:6341}"
WORKERS="${WORKERS:-4}"

# 未激活虚拟环境且存在 venv 则激活（服务通常跑在 venv 里，python 需在 PATH）
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

[ -f "$MD" ] || { echo "测试集不存在: $MD（请先用 Xftp 上传该 .md 到 data/ 目录）"; exit 1; }

echo "== 服务健康检查: $BASE/health =="
if ! curl -fsS "$BASE/health"; then
  echo; echo "QA 服务未响应 $BASE，请先启动服务后再评测"; exit 1
fi
echo

echo "== 开始评测 =="
echo "  测试集: $MD"
echo "  并发数: $WORKERS"
echo "  目标:   $BASE/chat"
echo "  输出:   $OUT"
echo
python scripts/eval_accuracy.py --md "$MD" --base "$BASE" --workers "$WORKERS" --full --out "$OUT"
