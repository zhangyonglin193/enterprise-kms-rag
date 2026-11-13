"""失败根因分析：把每道未命中题追踪到管线具体环节。

对每道「未命中」题，结合 gold 标准答案的关键事实与「已索引进库的 chunk 文本」，判定根因：
  E) 抽取缺失：gold 关键事实在全库 chunk 文本里几乎找不到 → OCR/文本层没抽出来（不可检索恢复）
  F) 分块碎片化：关键事实都在库里，但分散在多个不同 chunk，没有单块能凑齐 → 分块把语义切散
  G) 检索/生成：某个单块几乎覆盖全部关键事实（本该能答对），却没答对 → 召回排名/LLM 生成问题

同时给出 gold 答案最可能所属的源文档（按 gold 关键事实在各文档 chunk 中的命中数排名）。

运行：
    python scripts/analyze_failures.py --report data/eval_report_100_tuned2.json
    可选：--md <测试集路径> --verdict 未命中
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFUSE_TOKENS = ("未找到", "没有检索到", "无法回答", "无权", "暂无", "没有找到", "不在我能访问", "覆盖较为有限")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
TERM_RE = re.compile(r"[「『“\"'《【]([^」』”\"'》】]{2,20})[」』”\"'》】]")


def parse_md(text: str):
    items, qnum, question = [], None, None
    for line in text.splitlines():
        m = re.match(r"\*\*Q(\d+)：(.+?)\*\*", line.strip())
        if m:
            qnum, question = int(m.group(1)), m.group(2).strip()
            continue
        a = re.match(r"A[：:](.+)", line.strip())
        if a and qnum is not None:
            items.append({"qnum": qnum, "question": question, "gold": a.group(1).strip()})
            qnum, question = None, None
    return items


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[，。、；：（）()《》「」『』“”\"'　\s*\-*—]", "", s)


def extract_facts(gold: str):
    nums = set(NUM_RE.findall(gold))
    terms = {t for t in TERM_RE.findall(gold) if len(t) >= 2}
    # 补充：gold 中较长的中文片段（去标点后≥3字）作为候选关键词
    return list(nums | terms)


def char_ngrams(s: str, n: int = 3):
    """gold 的字符 n-gram 集合（去标点空白后），用于稳健的『内容是否在库』判定。"""
    s = norm(s)
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", default="data/eval_report_100_tuned2.json")
    ap.add_argument("--md", default=r"d:/Desktop/知识库测试问题与答案100题.md")
    ap.add_argument("--verdict", default="未命中")
    args = ap.parse_args()

    # 1) 载入已索引 chunk（真相源：抽取+分块后进库的文本）
    from app.store import MySQLStore
    store = MySQLStore()
    rows = []
    with store._conn() as cur:
        cur.execute(
            "SELECT c.faiss_id, c.document_id, c.chunk_index, c.text, d.filename "
            "FROM chunks c LEFT JOIN documents d ON d.id = c.document_id"
        )
        rows = cur.fetchall()
    chunks = [(r["filename"] or "", norm(r["text"] or "")) for r in rows]
    print(f"已载入 chunk 数: {len(chunks)}")
    indexed_blob = "".join(nt for _, nt in chunks)

    # 1b) 载入原始源文件的文本层（区分『入库丢失』vs『真缺失』）
    from app.document import DocumentLoader
    loader = DocumentLoader()
    src_blob_parts = []
    n_src = 0
    for f in sorted(Path("RAG_repository").glob("*")):
        if f.name.startswith("~$") or f.suffix.lower() in loader.IMAGE_EXTS:
            continue
        try:
            t = loader.load(f)
            if t:
                src_blob_parts.append(norm(t))
                n_src += 1
        except Exception:
            pass
    source_blob = "".join(src_blob_parts)
    print(f"已载入源文件文本层: {n_src} 个\n" + "=" * 60)

    # 2) 载入测试集与报告
    items = parse_md(Path(args.md).read_text(encoding="utf-8"))
    gold_by_q = {it["qnum"]: it for it in items}
    rep = json.load(open(args.report, encoding="utf-8"))
    results = rep["results"] if isinstance(rep, dict) and "results" in rep else rep
    pred_by_q = {r["qnum"]: r for r in results}

    targets = sorted(q for q, r in pred_by_q.items() if r.get("verdict") == args.verdict)
    print(f"分析 {args.verdict} 题 {len(targets)} 道\n" + "=" * 60)

    buckets = defaultdict(list)
    detail = []
    for q in targets:
        g = gold_by_q.get(q, {})
        gold = g.get("gold", "")
        grams = char_ngrams(gold, n=3)
        grams = [gr for gr in grams if len(gr) >= 2]
        total = len(grams) or 1
        # gold 内容在『已索引库』与『原始源文件』中的覆盖率
        idx_cov = sum(1 for gr in grams if gr in indexed_blob) / total
        src_cov = sum(1 for gr in grams if gr in source_blob) / total
        # 单个 chunk 对 gold 的最佳覆盖（看答案是否能被一个完整块装下）
        best_chunk_cov = 0.0
        for _, ct in chunks:
            if not ct:
                continue
            cov = sum(1 for gr in grams if gr in ct) / total
            if cov > best_chunk_cov:
                best_chunk_cov = cov
        pred = pred_by_q[q]
        refused = any(tok in pred.get("pred", "") for tok in REFUSE_TOKENS)

        if idx_cov >= 0.5:
            cause = "G-检索/生成" if best_chunk_cov >= 0.5 else "F-分块碎片化"
        elif src_cov >= 0.5:
            cause = "X-入库丢失"
        else:
            cause = "E-真缺失(图片)"
        buckets[cause].append(q)
        detail.append((q, cause, round(idx_cov, 2), round(src_cov, 2), round(best_chunk_cov, 2), refused,
                       g.get("question", "")[:22]))

    # 3) 输出
    print("题号  根因              入库覆盖 源文件覆盖 单块最佳 拒答")
    for row in sorted(detail):
        print(f"Q{row[0]:<3} {row[1]:<15} {row[2]:>7} {row[3]:>9} {row[4]:>8} {str(row[5]):>5}  {row[6]}")
    print("\n" + "=" * 60)
    for c in ("G-检索/生成", "F-分块碎片化", "X-入库丢失", "E-真缺失(图片)"):
        print(f"{c}: {len(buckets[c])} 道 -> {buckets[c]}")


if __name__ == "__main__":
    main()
