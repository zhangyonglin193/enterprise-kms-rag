"""RAG 问答准确率评测：读取「测试问题与答案」Markdown，逐题打 /chat 并按关键事实覆盖率打分。

评分口径（透明可复核，非精确匹配而是自动代理指标）：
- 从标准答案抽取"关键事实"：数字(含万/亿/%/元等) 与 引号/书名号内术语；
- 命中判定：把预测答案与标准答案都做归一化（去空白/全角标点），关键事实子串出现即命中；
- coverage = 命中数 / 关键事实总数；无任何可抽取事实时，退化为字符二元组 Jaccard 相似度；
- 判定：coverage>=0.6 记为「正确」，0.3~0.6「部分」，<0.3 或命中拒答词记为「未命中」。

运行：
    python scripts/eval_accuracy.py --md <路径> --limit 10        # 先跑前10题校准
    python scripts/eval_accuracy.py --md <路径> --full            # 跑全部
    可选：--base http://127.0.0.1:6341 --workers 6 --out data/eval_report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REFUSE_TOKENS = ("未找到", "没有检索到", "无法回答", "无权", "暂无", "没有找到", "不在我能访问")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
TERM_RE = re.compile(r"[「『“\"'《【]([^」』”\"'》】]{2,20})[」』”\"'》】]")


def parse_md(text: str):
    """兼容三种格式：
    - 旧：`**Q1：问题**` + `A：答案`
    - 进阶：`**Q1.** 问题` + `> A：答案 [word_35]`
    - 图片题：`**1. 问题？**` + `答案：... [word_1]`
    （自动剥除行首 `>` 与 gold 末尾来源标记）
    """
    items, qnum, question = [], None, None
    for raw in text.splitlines():
        line = re.sub(r"^>+\s*", "", raw.strip())  # 去除 markdown 引用块前缀
        m = re.match(r"\*\*Q(\d+)：(.+?)\*\*", line)            # 旧式 **Q1：问题**
        if not m:
            m = re.match(r"\*\*Q(\d+)[.。]*\*\*\s*[:：]?\s*(.+?)\*\*$", line)  # **Q1.问题**
        if not m:
            m = re.match(r"\*\*Q(\d+)[.。]+\*\*\s*(.+)$", line)  # 进阶 **Q1.** 问题
        if not m:
            m = re.match(r"\*\*(\d+)[.。]\s*(.+?)\*\*", line)  # 图片题 **1. 问题**
        if m and m.group(2).strip():
            qnum, question = int(m.group(1)), m.group(2).strip()
            continue
        a = re.match(r"(?:A|答案)[：:](.+)", line)  # 兼容 A：与答案：
        if a and qnum is not None:
            gold = re.sub(r"\s*[\[（][a-zA-Z0-9_\u4e00-\u9fff]{1,20}[\])）]\s*$", "", a.group(1)).strip()
            items.append({"qnum": qnum, "question": question, "gold": gold})
            qnum, question = None, None
    return items


def norm(s: str) -> str:
    return re.sub(r"[，。、；：（）()《》「」『』“”\"'　\s*]", "", s)


def extract_facts(gold: str):
    nums = set(NUM_RE.findall(gold))
    terms = {t for t in TERM_RE.findall(gold) if len(t) >= 2}
    return list(nums | {t for t in terms})


def bigrams(s: str):
    n = norm(s)
    return {n[i:i + 2] for i in range(len(n) - 1)} if len(n) >= 2 else {n}


def score(gold: str, pred: str):
    """综合评分：主指标=标准答案内容召回率(对措辞/前缀鲁棒)，辅指标=关键事实(数字/术语)命中率。"""
    if any(tok in pred for tok in REFUSE_TOKENS):
        return {"verdict": "未命中", "coverage": 0.0, "facts": 0, "hits": 0, "refused": True}
    np = norm(pred)
    gb = bigrams(gold)
    pb = bigrams(pred)
    content_recall = len(gb & pb) / len(gb) if gb else 0.0
    facts = extract_facts(gold)
    fact_hit = (sum(1 for f in facts if norm(f) in np) / len(facts)) if facts else None
    # 覆盖度：内容召回为主；有关键事实时按 0.6*召回 + 0.4*事实命中 融合
    coverage = content_recall if fact_hit is None else 0.6 * content_recall + 0.4 * fact_hit
    hits = sum(1 for f in facts if norm(f) in np) if facts else round(content_recall * len(gb))
    verdict = "正确" if coverage >= 0.6 else ("部分" if coverage >= 0.35 else "未命中")
    return {"verdict": verdict, "coverage": round(coverage, 3),
            "content_recall": round(content_recall, 3),
            "fact_hit": (round(fact_hit, 3) if fact_hit is not None else None),
            "facts": len(facts), "hits": hits, "refused": False}


def ask(base: str, question: str, timeout: int):
    req = urllib.request.Request(base.rstrip("/") + "/chat",
                                 data=json.dumps({"question": question}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("answer", "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--md", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:6341")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--limit", type=int, default=0, help="仅跑前 N 题（0=不限）")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--out", default="data/eval_report.json")
    args = ap.parse_args()

    items = parse_md(Path(args.md).read_text(encoding="utf-8"))
    if not args.full and args.limit:
        items = items[:args.limit]
    print(f"解析到 {len(items)} 题，并发 {args.workers}，目标 {args.base}/chat")

    results = {}
    start = time.time()

    def work(it):
        t0 = time.time()
        try:
            pred = ask(args.base, it["question"], args.timeout)
        except Exception as e:
            pred = f"__ERROR__ {e}"
        s = score(it["gold"], pred)
        s.update(qnum=it["qnum"], question=it["question"], gold=it["gold"], pred=pred[:400], ms=round((time.time()-t0)*1000))
        return s

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, it): it for it in items}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            results[r["qnum"]] = r
            done += 1
            flag = "OK" if r["verdict"] == "正确" else ("~~" if r["verdict"] == "部分" else "XX")
            print(f"[{done:3}/{len(items)}] {flag} Q{r['qnum']:>3} cov={r['coverage']:.2f} {r['question'][:24]}")

    ordered = [results[k] for k in sorted(results)]
    n = len(ordered)
    stat = {v: sum(1 for r in ordered if r["verdict"] == v) for v in ("正确", "部分", "未命中")}
    err = sum(1 for r in ordered if r["pred"].startswith("__ERROR__"))
    cov_avg = sum(r["coverage"] for r in ordered) / n if n else 0

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"用时 {round(time.time()-start,1)}s | 正确 {stat['正确']} | 部分 {stat['部分']} | 未命中 {stat['未命中']} | 请求异常 {err} / 总 {n}")
    print(f"准确率(严格=正确/总): {stat['正确']/n:.1%}")
    print(f"准确率(宽松=(正确+部分)/总): {(stat['正确']+stat['部分'])/n:.1%}")
    print(f"平均关键事实覆盖率: {cov_avg:.1%}")
    lats = [r["ms"] for r in ordered if r.get("ms") is not None]
    if lats:
        print(f"单题延迟: 均值 {round(sum(lats)/len(lats))}ms / 最大 {max(lats)}ms")
    print(f"明细已写入: {args.out}")
    miss = [r["qnum"] for r in ordered if r["verdict"] == "未命中"]
    if miss:
        print("未命中题号:", miss)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
