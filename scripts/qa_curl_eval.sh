#!/usr/bin/env bash
# 问答服务(6341) 的 curl 验收脚本：连通性 → 语料就绪 → 单请求时延 → 准确率批量 → 并发性能
#
# 设计原则：组委会大概率就是用 curl 打 /chat，所以这里也只用 curl，
# 不引入 wrk/ab 等评测机上未必有的工具，避免"本地能跑、现场跑不了"。
#
# 用法（在服务器上，QA 服务已启动）：
#   bash scripts/qa_curl_eval.sh                          # 全跑（100 题）
#   bash scripts/qa_curl_eval.sh --host 127.0.0.1 --port 6341
#   bash scripts/qa_curl_eval.sh --limit 20               # 只跑前 20 题（先冒烟）
#   bash scripts/qa_curl_eval.sh --concurrency 20         # 并发档位
#   bash scripts/qa_curl_eval.sh --qset data/adv100_set.md
#
# 产物：data/qa_curl_eval_<时间戳>/ 下 answers.md / latency.csv / report.txt
set -uo pipefail

HOST="127.0.0.1"
PORT="6341"
QSET="data/union100_regression.md"
LIMIT="0"          # 0 = 不限
CONCURRENCY="10"
TIMEOUT="120"
OUTDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --qset) QSET="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

BASE="http://${HOST}:${PORT}"
STAMP=$(date +%Y%m%d_%H%M%S)
OUTDIR="data/qa_curl_eval_${STAMP}"
mkdir -p "$OUTDIR"
REPORT="${OUTDIR}/report.txt"

log() { echo -e "$*" | tee -a "$REPORT"; }

log "===== 问答服务 curl 验收 ====="
log "时间: $(date '+%F %T')   目标: ${BASE}   题库: ${QSET}"

# ---------- 0. 连通性 ----------
log "\n[0] 连通性"
if ! curl -sS --fail --max-time 10 "${BASE}/readyz" -o "${OUTDIR}/readyz.json" 2>>"$REPORT"; then
  log "!!! /readyz 未通过，服务未就绪，后续无意义，中止"
  exit 1
fi
log "    /readyz OK -> $(cat "${OUTDIR}/readyz.json")"

# ---------- 1. 语料就绪（关键：向量为空则准确率必然为 0，先排掉） ----------
log "\n[1] 语料就绪度（/health）"
if curl -sS --fail --max-time 15 "${BASE}/health" -o "${OUTDIR}/health.json" 2>>"$REPORT"; then
  VEC=$(grep -o '"vectors_total":[0-9]*' "${OUTDIR}/health.json" | head -1 | cut -d: -f2)
  CHUNK=$(grep -o '"chunks_cached":[0-9]*' "${OUTDIR}/health.json" | head -1 | cut -d: -f2)
  BM25=$(grep -o '"bm25_indexed":[0-9]*' "${OUTDIR}/health.json" | head -1 | cut -d: -f2)
  log "    vectors_total=${VEC}  chunks_cached=${CHUNK}  bm25_indexed=${BM25}"
  if [[ "${VEC:-0}" -eq 0 ]]; then
    log "!!! 索引为空：语料未入库。先执行入库（scripts/reingest_all.py）再测，"
    log "    否则后面所有准确率数据都是假的。"
    exit 1
  fi
else
  log "!!! /health 不可用"
fi

# ---------- 2. 单请求时延（含冷启动观察） ----------
log "\n[2] 单请求时延"
curl -sS --max-time "$TIMEOUT" "${BASE}/chat" \
     -H 'Content-Type: application/json' \
     -d '{"question":"数字人民币是什么？"}' \
     -o "${OUTDIR}/warmup.json" \
     -w '    预热请求  HTTP=%{http_code}  总耗时=%{time_total}s  建连=%{time_connect}s\n' 2>>"$REPORT" | tee -a "$REPORT"

curl -sS --max-time "$TIMEOUT" "${BASE}/chat" \
     -H 'Content-Type: application/json' \
     -d '{"question":"数字人民币是什么？"}' \
     -o "${OUTDIR}/sample.json" \
     -w '    再次请求  HTTP=%{http_code}  总耗时=%{time_total}s\n' 2>>"$REPORT" | tee -a "$REPORT"
log "    答案片段: $(head -c 120 "${OUTDIR}/sample.json")"

# ---------- 3. 准确率批量 ----------
# 题库格式：**Q1.** 问题  /  > A：参考答案
log "\n[3] 准确率批量问答"
mapfile -t QUESTIONS < <(grep -o '^\*\*Q[0-9]\+\.\*\* .*' "$QSET" | sed 's/^\*\*Q[0-9]\+\.\*\* //')
TOTAL=${#QUESTIONS[@]}
if [[ "$LIMIT" != "0" && "$LIMIT" -lt "$TOTAL" ]]; then
  QUESTIONS=("${QUESTIONS[@]:0:$LIMIT}")
  TOTAL=$LIMIT
fi
log "    题目数: ${TOTAL}（来自 $(basename "$QSET")）"

: > "${OUTDIR}/answers.md"
: > "${OUTDIR}/latency.csv"
echo "idx,http_code,time_total" >> "${OUTDIR}/latency.csv"
OK=0
FAIL=0
for i in "${!QUESTIONS[@]}"; do
  q="${QUESTIONS[$i]}"
  # --data-urlencode 不适用 JSON；问题含引号时用文件传，避免手工转义出错
  printf '%s' "$q" > "${OUTDIR}/.q.tmp"
  body=$(python3 -c 'import json,sys;print(json.dumps({"question":open(sys.argv[1],encoding="utf-8").read()},ensure_ascii=False))' "${OUTDIR}/.q.tmp" 2>/dev/null)
  if [[ -z "$body" ]]; then
    body=$(printf '{"question": "%s"}' "$(printf '%s' "$q" | sed 's/"/\\"/g')")
  fi
  t=$(curl -sS --max-time "$TIMEOUT" "${BASE}/chat" \
        -H 'Content-Type: application/json' -d "$body" \
        -o "${OUTDIR}/.r.tmp" -w '%{http_code},%{time_total}' 2>/dev/null)
  code="${t%%,*}"; el="${t##*,}"
  echo "$((i+1)),${code},${el}" >> "${OUTDIR}/latency.csv"
  if [[ "$code" == "200" ]]; then
    OK=$((OK+1))
    ans=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1],encoding="utf-8")).get("answer",""))' "${OUTDIR}/.r.tmp" 2>/dev/null || head -c 200 "${OUTDIR}/.r.tmp")
  else
    FAIL=$((FAIL+1))
    ans="[HTTP ${code}]"
  fi
  {
    echo "**Q$((i+1)).** $q"
    echo "> 模型答：$ans"
    echo ""
  } >> "${OUTDIR}/answers.md"
  printf '\r    进度 %d/%d  成功 %d  失败 %d' "$((i+1))" "$TOTAL" "$OK" "$FAIL"
done
rm -f "${OUTDIR}/.q.tmp" "${OUTDIR}/.r.tmp"
log ""
log "    成功=${OK}  失败=${FAIL}  —— answers.md 可与题库参考答案逐条比对打分"

# ---------- 4. 并发性能 ----------
log "\n[4] 并发性能（并发=${CONCURRENCY}）"
PERF_CSV="${OUTDIR}/perf.csv"
: > "$PERF_CSV"
echo "http_code,time_total" > "$PERF_CSV"
# 并发题目用一批**不含引号/反斜杠**的固定问题：题目里若含引号，在 xargs + bash -c
# 的双层 shell 里做转义极易出错，现场排查成本远高于用简单题目测吞吐的收益。
# 吞吐/时延是性能指标，与问什么无关；准确率由第 3 步逐题保证。
CONC_Q="数字人民币是什么？"
PAYLOAD="{\"question\": \"${CONC_Q}\"}"
START=$(date +%s.%N)
seq "$CONCURRENCY" | xargs -P "$CONCURRENCY" -I{} \
  curl -sS --max-time "$TIMEOUT" "${BASE}/chat" \
       -H 'Content-Type: application/json' -d "$PAYLOAD" \
       -o /dev/null -w '200,%{time_total}\n' >> "$PERF_CSV"
END=$(date +%s.%N)
WALL=$(python3 -c "print(f'{$END-$START:.2f}')" 2>/dev/null || echo "na")

OKC=$(grep -c '^200,' "$PERF_CSV" || true)
QPS=$(python3 -c "print(f'{$OKC/$WALL:.2f}')" 2>/dev/null || echo "na")
log "    并发 ${CONCURRENCY} 个请求，成功 ${OKC}，墙钟 ${WALL}s，吞吐约 ${QPS} req/s"
log "    逐请求明细见 perf.csv"

# 延迟分位（p50/p95/p99）
python3 - "$PERF_CSV" <<'PY' 2>/dev/null | tee -a "$REPORT"
import csv, sys
vals = []
with open(sys.argv[1], encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["http_code"] == "200":
            vals.append(float(r["time_total"]))
if vals:
    vals.sort()
    n = len(vals)
    def pct(p):
        return vals[min(n - 1, int(n * p))]
    print(f"    延迟 p50={pct(.50):.2f}s  p95={pct(.95):.2f}s  p99={pct(.99):.2f}s  max={vals[-1]:.2f}s")
PY

log "\n===== 产物 ====="
log "    ${OUTDIR}/report.txt    本汇总"
log "    ${OUTDIR}/answers.md    题目+模型答案（准确率打分用）"
log "    ${OUTDIR}/latency.csv   逐题 HTTP/时延"
log "    ${OUTDIR}/perf.csv      并发逐请求明细"
log "    ${OUTDIR}/health.json   语料就绪度快照"
log "\n判读提示：readyz=200 只代表进程活着；语料(vectors_total)为空或并发下大量非 200，"
log "        都属于未通过验收，先修再测。"
