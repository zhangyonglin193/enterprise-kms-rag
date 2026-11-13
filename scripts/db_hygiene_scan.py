# -*- coding: utf-8 -*-
"""全库数据体检（只读，不动库，无 API 调用）：
对每个文档的 chunks 跑通用垃圾签名检测，输出污染文档清单（按垃圾块占比排序）。

块级垃圾签名（复用 app/document.py 的结构规则，零文档特判）：
  - 退化七规则（_ocr_degenerate：撞顶/复读/词频/去重比/LaTeX/布局token/行内循环）
  - 编号循环行（_is_cyclic_line）
  - 勾选框复读（"□适用 □不适用" 单元 ≥8 次）
  - 编号+数字循环（同一 6+ 位数字串在块内重复 ≥5 次，如 "1. 1.407,546,234.93"）
"""
from __future__ import annotations

import io
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.service import ROOT, apply_environment, load_values

apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))
from app.document import _ocr_degenerate, _is_cyclic_line
from app.store import MySQLStore

OUT: list = []
def P(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    OUT.append(line)

# LaTeX 幻觉签名：只认「命令名 + 定界符」白名单（与 app/document._LATEX_CMD_RE 同源）。
# 旧写法 r"\\[()\[\]a-zA-Z]" 会把 Windows 路径与品牌分隔符误判为幻觉
#（实测假阳性：doc87「MASTER\JCB\DINER\AMEX」、doc20「\[2012\]」markdown 转义）。
LATEX = re.compile(
    r"\\(?:frac|sum|sqrt|int|prod|lim|cdot|times|alpha|beta|gamma|delta|theta|lambda|"
    r"sigma|omega|infty|approx|leq|geq|neq|partial|nabla|begin|end|left|right|text|"
    r"mathrm|mathbf|textit)\b|\\[(){\[}]"
)
TOKEN = re.compile(r"<\|[A-Z_]+\d+")
CHECKBOX_RUN = re.compile(r"□\s*适用\s*□\s*不适用")
NUM_RUN = re.compile(r"(\d{1,3}[,.]\d{3}[,.]\d{3}[,.]\d{3}(?:[.,]\d+)?)")


def is_garbage_block(text: str) -> tuple[bool, str]:
    """块级垃圾判定：返回 (是否垃圾, 命中规则)。"""
    if not text or not text.strip():
        return True, "空块"
    t = text.strip()
    if _ocr_degenerate(t):
        return True, "退化七规则"
    for ln in t.splitlines():
        if _is_cyclic_line(ln):
            return True, "编号循环行"
    if len(LATEX.findall(t)) >= 2:
        return True, "LaTeX幻觉"
    if len(TOKEN.findall(t)) >= 2:
        return True, "布局token"
    # 勾选框复读：同一页面模板单元重复铺满
    if len(CHECKBOX_RUN.findall(t)) >= 8:
        return True, "勾选框复读"
    # 编号+数字循环：同一 6 位+ 数字串重复 >=5 次（撞顶循环被分块后的形态）
    for num in NUM_RUN.findall(t):
        if t.count(num) >= 5:
            return True, f"数字循环({num})"
    return False, ""


def ngrams(text: str, n: int = 6) -> set:
    s = re.sub(r"\s+", "", text)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def main() -> None:
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute("SELECT id, title, filename FROM documents ORDER BY id")
        docs = cur.fetchall()
        cur.execute("SELECT document_id, text FROM chunks")
        chunks = cur.fetchall()

    by_doc: dict = {}
    for r in chunks:
        by_doc.setdefault(r["document_id"], []).append(r["text"] or "")

    P(f"=== 全库体检：{len(docs)} 个文档，{len(chunks)} 块 ===\n")
    rows = []
    for d in docs:
        texts = by_doc.get(d["id"], [])
        n = len(texts)
        bad = 0
        reasons: Counter = Counter()
        good_text = ""
        for t in texts:
            is_bad, why = is_garbage_block(t)
            if is_bad:
                bad += 1
                reasons[why] += 1
            else:
                good_text += t + "\n"
        ratio = bad / n if n else 0
        rows.append((d, n, bad, ratio, reasons, good_text))
    rows.sort(key=lambda r: -r[3])

    for d, n, bad, ratio, reasons, good_text in rows:
        flag = "  <== 需换血" if ratio >= 0.2 else ""
        P(f"doc{d['id']:>3} [{d['title'] or d['filename']}] 块={n} 垃圾={bad} 占比={ratio:.0%}{flag}")
        if reasons:
            P(f"       命中规则: {dict(reasons.most_common(5))}")
    P("\n=== 汇总 ===")
    dirty = [r for r in rows if r[3] >= 0.2]
    P(f"污染文档(占比>=20%): {len(dirty)} 篇，共 {sum(r[1] for r in dirty)} 块中 {sum(r[2] for r in dirty)} 块垃圾")

    (ROOT / "data" / "_hygiene_scan.txt").write_text("\n".join(OUT), encoding="utf-8")
    print("written")


if __name__ == "__main__":
    main()
