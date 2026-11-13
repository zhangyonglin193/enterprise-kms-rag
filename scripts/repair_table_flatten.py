# -*- coding: utf-8 -*-
"""通用「表格摊平块」重排修复器（可复用工具）。

背景：扫描件整页 OCR 会把财务报表摊平成「科目名+数字」行串，词项被稀释、
      语义漂移，导致检索双通道都召回不了 gold 块（实测 union100 Q34）。
方法：结构签名检测命中块 → LLM(temperature=0) 重排成行列对齐表格 →
      数字不变性校验（不过则整块拒绝）→ 备份后 UPDATE MySQL。

用法：
    python scripts/repair_table_flatten.py                # 全库检测 + 干跑（只打印 diff，不改库）
    python scripts/repair_table_flatten.py --doc 16       # 仅指定文档
    python scripts/repair_table_flatten.py --apply        # 落笔：备份 → UPDATE（text+text_hash）
    python scripts/repair_table_flatten.py --apply --doc 16

安全红线：
    1. 数字不变性校验：重排后整体数字字符流（去分隔符）与原文一致，
       且负号/百分号/小数点总数一致，否则整块拒绝、保持原文。
    2. 落笔前自动备份原块到 data/backup_doc{id}_chunks_{ts}.json，可完整回滚。
    3. LLM 只做结构重排，不改数字。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.store import MySQLStore

# 财报数字形态：千分位 + 两位小数（如 1,407,546,234.93）
NUM_RE = re.compile(r"\d[\d,]{2,}\.\d{2}")
HEAD_WORDS = ["总资产", "营业收入", "净利润", "所有者权益", "合计", "（元）", "（%）",
              "本报告期", "上年同期", "年初至报告期末", "期末余额", "本期发生额"]
# 数字段（含负号/百分号），用于不变性校验
NUM_SEG_RE = re.compile(r"-?\d[\d,]*\.?\d*[%％]?")

SYSTEM_PROMPT = "你是财务报表文本结构修复器，负责把 OCR 提取的摊平文本重排为行列对齐的表格。"
USER_PROMPT = """下面是扫描件 OCR 提取的财务报表文本，表格行列结构丢失（科目名称与数字粘连成行串），个别句子还被重复提取。请修复为行列对齐的纯文本表格。

修复规则：
1. 把「科目名称 + 数字」的粘连串拆成行：科目名放在行首，其后的数字按列对齐（用空格或制表符分列）。
2. 重复出现的句子只保留一次（重复段落必须至少保留一份，不得整段删除）。
3. 数字逐字原样保留：千分位逗号、小数点、负号、百分号的位置都保持原样，数字只做换行和列对齐。
4. 非表格的叙述性文字（如「三季度，扣非后归母净利润同比减少…」）也必须保留：重复多遍的保留一遍，单次出现的不能删除。
5. 只输出修复后的表格文本，不要任何解释。

待修复文本：
---
{text}
---"""


def detect_flattened(cur, doc_id=None) -> list[dict]:
    """结构签名检测：千分位数字 ≥6 且含表头词。零文档特判。"""
    if doc_id is not None:
        cur.execute(
            "SELECT c.id, c.document_id, c.chunk_index, c.text, d.filename FROM chunks c "
            "LEFT JOIN documents d ON d.id=c.document_id WHERE c.document_id=%s", (doc_id,))
        rows = cur.fetchall()
    else:
        cur.execute(
            "SELECT c.id, c.document_id, c.chunk_index, c.text, d.filename FROM chunks c "
            "LEFT JOIN documents d ON d.id=c.document_id")
        rows = cur.fetchall()
    hits = []
    for r in rows:
        t = r["text"] or ""
        nums = NUM_RE.findall(t)
        heads = sum(1 for w in HEAD_WORDS if w in t)
        if len(nums) >= 6 and heads >= 1:
            hits.append({**r, "nums": len(nums), "heads": heads})
    return hits


def digit_stream(s: str) -> str:
    """数字段拼接后的纯数字字符流（去 , . % -），挡丢失/新增/篡改。"""
    return "".join(re.sub(r"[^0-9]", "", seg) for seg in NUM_SEG_RE.findall(s))


def split_glued(seg: str) -> list[str]:
    """拆粘连数字段：OCR 常见「388.8312」=「388.83」+「12,263…」的前半段粘连。

    仅当小数位 >2 且非百分数时拆为「整数.前2位」+「剩余」。
    """
    m = re.match(r"^(-?\d[\d,]*\.)(\d{3,})$", seg)
    if m:
        return [m.group(1) + m.group(2)[:2], m.group(2)[2:]]
    return [seg]


def _seg_digits(seg: str) -> str:
    return re.sub(r"[^0-9]", "", seg)


def _seg_sign_counts(s: str):
    """数字段内的负号/小数点/百分号计数（忽略表格分隔线等非数字符号）。"""
    segs = NUM_SEG_RE.findall(s)
    return (
        sum(1 for seg in segs if seg.startswith("-")),
        sum(seg.count(".") for seg in segs),
        sum(seg.count("%") + seg.count("％") for seg in segs),
    )


def verify_numbers(orig: str, new: str):
    """数字不变性校验（容忍去重/粘连拆分/符号合并，杜绝丢行/篡改/新增）。

    1. 原文每个数字段经粘连预拆分后，≥3 位的部分其纯数字序列必须在新文流中；
       防丢行、防篡改、防截断；粘连拆分正确时拆后各段自然仍在新流中。
    2. 新文 ≥3 位的数字段反向校验：必须在原文流中；防 LLM 编造数字。
    3. 数字段内负号/小数点/百分号计数新 ≤ 原（允许去重、合并「--」→「-」）。
    返回 (ok, reason)。
    """
    o_stream = digit_stream(orig)
    n_stream = digit_stream(new)
    missing = []
    for seg in NUM_SEG_RE.findall(orig):
        for part in split_glued(seg):
            d = _seg_digits(part)
            if len(d) >= 3 and d not in n_stream:
                missing.append(part)
    if missing:
        return False, f"原文 {len(missing)} 个数字段在新文中缺失（丢行/篡改/截断）: {missing[:3]}"
    invented = [seg for seg in NUM_SEG_RE.findall(new)
                if len(_seg_digits(seg)) >= 3 and _seg_digits(seg) not in o_stream]
    if invented:
        return False, f"新文出现原文没有的数字（编造）: {invented[:3]}"
    o_m, o_d, o_p = _seg_sign_counts(orig)
    n_m, n_d, n_p = _seg_sign_counts(new)
    if n_m > o_m:
        return False, f"数字段负号增多（原 {o_m} → 新 {n_m}）"
    if n_d > o_d:
        return False, f"数字段小数点增多（原 {o_d} → 新 {n_d}）"
    if n_p > o_p:
        return False, f"数字段百分号增多（原 {o_p} → 新 {n_p}）"
    return True, "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", type=int, default=None, help="只处理指定 document_id（默认全库）")
    ap.add_argument("--ids", type=str, default=None, help="强制处理指定 chunk id（逗号分隔），绕过签名检测")
    ap.add_argument("--apply", action="store_true", help="落笔写库（默认只干跑打印 diff）")
    args = ap.parse_args()

    store = MySQLStore()
    with store._conn() as cur:
        if args.ids:
            ids = [int(x) for x in args.ids.split(",")]
            ph = ",".join(["%s"] * len(ids))
            cur.execute(
                f"SELECT c.id, c.document_id, c.chunk_index, c.text, d.filename FROM chunks c "
                f"LEFT JOIN documents d ON d.id=c.document_id WHERE c.id IN ({ph})", ids)
            rows = cur.fetchall()
            hits = []
            for r in rows:
                t = r["text"] or ""
                hits.append({**r, "nums": len(NUM_RE.findall(t)),
                             "heads": sum(1 for w in HEAD_WORDS if w in t)})
        else:
            hits = detect_flattened(cur, args.doc)
    print(f"检测命中 {len(hits)} 块\n" + "=" * 70)

    from app.clients import LLMClient
    llm = LLMClient()

    passed, rejected = [], []
    for i, h in enumerate(hits, 1):
        orig = h["text"]
        print(f"\n[{i}/{len(hits)}] doc{h['document_id']} chunk#{h['chunk_index']} "
              f"id={h['id']} nums={h['nums']} len={len(orig)} | {h['filename'][:24]}")
        new = llm.chat_with_prompt(
            USER_PROMPT.format(text=orig), system=SYSTEM_PROMPT,
            temperature=0.0, max_tokens=2048,
        )
        ok, reason = verify_numbers(orig, new)
        if not ok:
            rejected.append(h)
            print(f"  [拒绝] {reason} —— 保持原文")
            print("  --- LLM 输出前 400 字（定位原因）---")
            print("\n".join("  " + ln for ln in new[:400].splitlines()))
            continue
        passed.append({**h, "new_text": new})
        print(f"  [通过] {reason}，重排后 {len(new)} 字（原 {len(orig)} 字）")
        print("  --- 重排结果预览（前 600 字）---")
        print("\n".join("  " + ln for ln in new[:600].splitlines()))

    print("\n" + "=" * 70)
    print(f"通过 {len(passed)} / {len(hits)}，拒绝 {len(rejected)}")
    if not args.apply:
        print("干跑模式：未改库。确认 diff 无误后加 --apply 落笔。")
        return

    if not passed:
        print("无通过块，不落笔。")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    doc_tag = f"doc{args.doc}" if args.doc else "all"
    backup = Path(__file__).resolve().parents[1] / "data" / f"backup_{doc_tag}_chunks_{ts}.json"
    import hashlib
    backup.write_text(json.dumps([
        {"id": p["id"], "faiss_id": p.get("faiss_id"), "document_id": p["document_id"],
         "chunk_index": p["chunk_index"], "text": p["text"]}
        for p in passed
    ], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n备份已写: {backup.name}（{len(passed)} 块，可回滚）")

    with store._conn() as cur:
        for p in passed:
            cur.execute(
                "UPDATE chunks SET text=%s, text_hash=%s WHERE id=%s",
                (p["new_text"],
                 hashlib.sha256(p["new_text"].encode("utf-8")).hexdigest()[:16],
                 p["id"]),
            )
    print(f"已 UPDATE {len(passed)} 块。注意：需重启 QA 服务重建 FAISS/BM25 索引后生效。")


if __name__ == "__main__":
    main()
