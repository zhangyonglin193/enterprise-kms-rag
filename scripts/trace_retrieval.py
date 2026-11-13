"""检索追踪：对失败题复刻生产 retrieve()，定位 gold 答案所在块的召回排名。

目的：把「G-检索/生成」进一步拆成两类——
  R) 检索未召回：gold 所在块存在于库中，但没进 retrieve() 返回结果（或排名在 top_k_rerank 之外）→ 排序问题
  N) 生成问题：gold 所在块已被召回且在最终上下文里，但答案仍错 → LLM/prompt 问题

做法：
  1) 用 MySQL 找出「含 gold 独特子串」的 chunk（gold_chunk_ids）；独特子串=在库中命中块数很少(<=8)的
     数字/带单位数值/书名号【】术语/或最长的稀有 6-gram，避免通用词误判；
  2) 用与线上相同的 Retriever.retrieve(query)（沿用 settings 的 top_k 与复杂题逻辑）取回结果；
  3) 报告：gold 块是否被召回、最佳排名、rerank_score、以及最终进入上下文的前 top_k_rerank 名里有无 gold。

运行：
    python scripts/trace_retrieval.py --report data/eval_report_100_tuned2.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFUSE_TOKENS = ("未找到", "没有检索到", "无法回答", "无权", "暂无", "没有找到", "不在我能访问", "覆盖较为有限")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?(?:[%％]|元|亿|万|mm|cm|px|天|个|家|年|月|日)?")
BRACKET_RE = re.compile(r"[「『“\"'《【]([^」』”\"'》】]{2,20})[」』”\"'》】]")


def norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[，。、；：（）()《》「」『』“”\"'　\s*\-*—/]", "", s)


def candidate_facts(gold: str):
    """gold 里的『候选独特子串』，按稀有度排序前用于定位 gold 块。"""
    cands = set()
    for m in NUM_RE.findall(gold):
        if len(norm(m)) >= 2:
            cands.add(m)
    for t in BRACKET_RE.findall(gold):
        if len(norm(t)) >= 3:
            cands.add(t)
    # URL / 英文串
    for m in re.findall(r"[A-Za-z][A-Za-z0-9./:_-]{4,}", gold):
        cands.add(m)
    # 中文连续段（≥4 字）作为补充候选
    for seg in re.findall(r"[\u4e00-\u9fff]{4,}", gold):
        cands.add(seg[:8])
    return list(cands)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", default="data/eval_report_100_tuned2.json")
    ap.add_argument("--md", default=r"d:/Desktop/知识库测试问题与答案100题.md")
    ap.add_argument("--verdict", default="未命中")
    args = ap.parse_args()

    from app.store import MySQLStore
    store = MySQLStore()

    # 载入 chunk（faiss_id -> (filename, raw_text)）
    rows = []
    with store._conn() as cur:
        cur.execute("SELECT c.faiss_id, c.text, d.filename FROM chunks c "
                    "LEFT JOIN documents d ON d.id=c.document_id")
        rows = cur.fetchall()
    chunk_text = {r["faiss_id"]: (r["filename"] or "", r["text"] or "") for r in rows}
    norm_by_id = {fid: norm(tx) for fid, (_, tx) in chunk_text.items()}

    # 载入测试集
    def parse_md(text):
        items, qn, qs = [], None, None
        for line in text.splitlines():
            m = re.match(r"\*\*Q(\d+)：(.+?)\*\*", line.strip())
            if m:
                qn, qs = int(m.group(1)), m.group(2).strip()
                continue
            a = re.match(r"A[：:](.+)", line.strip())
            if a and qn is not None:
                items.append({"qnum": qn, "question": qs, "gold": a.group(1).strip()})
                qn, qs = None, None
        return items
    gold_by_q = {it["qnum"]: it for it in parse_md(Path(args.md).read_text(encoding="utf-8"))}

    rep = json.load(open(args.report, encoding="utf-8"))
    results = rep["results"] if isinstance(rep, dict) and "results" in rep else rep
    pred_by_q = {r["qnum"]: r for r in results}
    targets = sorted(q for q, r in pred_by_q.items() if r.get("verdict") == args.verdict)

    # 复刻生产检索
    from app.rag import Retriever
    from config import settings
    retriever = Retriever()
    retriever.warmup()

    print(f"追踪 {args.verdict} 题 {len(targets)} 道 | top_k_rerank={settings.top_k_rerank}\n" + "=" * 60)
    buckets = {"R-检索未召回": [], "R-排名靠后": [], "N-生成问题": [], "?-未定位gold块": []}
    lines = []
    for q in targets:
        gold = gold_by_q.get(q, {}).get("gold", "")
        question = gold_by_q.get(q, {}).get("question", "")
        cands = candidate_facts(gold)
        # 选『最稀有』的候选：命中块数最少且>=1
        best_fact, best_ids = None, []
        for c in cands:
            nc = norm(c)
            if len(nc) < 2:
                continue
            hit_ids = [fid for fid, nt in norm_by_id.items() if nc in nt]
            if hit_ids and (best_fact is None or len(hit_ids) < len(best_ids)):
                best_fact, best_ids = c, hit_ids
        if not best_fact:
            buckets["?-未定位gold块"].append(q)
            lines.append(f"Q{q:<3} ?未定位gold块（gold 无独特子串可匹配）  {question[:22]}")
            continue

        retrieved = retriever.retrieve(question)  # 线上同款
        ret_ids = [r["faiss_id"] for r in retrieved]
        gold_set = set(best_ids)
        inter = [fid for fid in ret_ids if fid in gold_set]
        rank = (ret_ids.index(inter[0]) + 1) if inter else None
        final_n = settings.top_k_rerank
        in_final = rank is not None and rank <= final_n

        if rank is None:
            cause = "R-检索未召回"
        elif not in_final:
            cause = "R-排名靠后"
        else:
            cause = "N-生成问题"
        buckets[cause].append(q)
        doc = chunk_text[best_ids[0]][0][:22]
        lines.append(f"Q{q:<3} {cause:<20} gold块命中词『{best_fact[:12]}』 排名={rank} gold块数={len(best_ids)} 召回数={len(ret_ids)} | {doc}")

    for ln in lines:
        print(ln)
    print("\n" + "=" * 60)
    for k in ("R-检索未召回", "R-排名靠后", "N-生成问题", "?-未定位gold块"):
        if k in buckets:
            print(f"{k}: {len(buckets[k])} 道 -> {buckets[k]}")


if __name__ == "__main__":
    main()
