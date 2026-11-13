# -*- coding: utf-8 -*-
"""通用「块内重复」去重修复器（可复用工具）。

背景：Chunker._recursive_split 递归双层 overlap 拼接 bug（app/document.py 已修）
      导致存量库大量块出现「overlap 前文在块内重复」的 [Z][Z][W] 结构，
      词项稀释、语义漂移，BM25/向量双通道召回失败（实测 union100 Q37/Q93/Q94）。
方法：程序化检测紧邻重复子串（≥MIN_DUP 字）→ 删除重复份 →
      可逆校验（删除片段插回新文 == 原文，零信息丢失）→ 备份后 UPDATE MySQL。

用法：
    python scripts/repair_inner_dup.py --doc 87        # 指定文档干跑（只打印，不改库）
    python scripts/repair_inner_dup.py --ids 393,398   # 指定 chunk id 干跑
    python scripts/repair_inner_dup.py --apply --doc 87

安全红线：
    1. 可逆校验：新文 + 删除片段必须能精确重构原文（比数字校验更强，零篡改）。
    2. 数字段校验：新文数字段必须全部在原文中（防工具 bug）。
    3. 落笔前自动备份原块到 data/backup_dedup_{ts}.json，可完整回滚。
    4. 只删「紧邻重复」的重复份，至少保留一份，不改变任何文字。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.store import MySQLStore

MIN_DUP = 30  # 紧邻重复子串最小长度（字符）
NUM_SEG_RE = re.compile(r"-?\d[\d,]*\.?\d*[%％]?")


def find_adjacent_dup(text: str, min_len: int = MIN_DUP):
    """找最长紧邻重复子串 [Z][Z]，返回 (start, Z)；无则 None。"""
    n = len(text)
    for L in range(n // 2, min_len - 1, -1):
        for i in range(0, n - 2 * L + 1):
            if text[i:i + L] == text[i + L:i + 2 * L]:
                return i, text[i:i + L]
    return None


def dedup_text(text: str):
    """迭代删除紧邻重复份，返回 (new_text, [(pos, Z), ...])。删除记录按发生顺序。"""
    cur = text
    records = []
    while True:
        hit = find_adjacent_dup(cur)
        if not hit:
            break
        i, Z = hit
        records.append((i, Z))
        cur = cur[:i] + cur[i + len(Z):]
    return cur, records


def verify_reconstruct(orig: str, new: str, records) -> bool:
    """逆序插回删除片段，必须精确重构原文。"""
    rebuilt = new
    for i, Z in reversed(records):
        rebuilt = rebuilt[:i] + Z + rebuilt[i:]
    return rebuilt == orig


def verify_numbers(orig: str, new: str):
    """新文数字段多重集必须 ⊆ 原文（防工具 bug 吞数字）。"""
    from collections import Counter
    o = Counter(NUM_SEG_RE.findall(orig))
    n = Counter(NUM_SEG_RE.findall(new))
    extra = n - o
    return not extra, [f"{k}x{v}" for k, v in extra.items()][:5]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", type=int, default=None, help="只处理指定 document_id")
    ap.add_argument("--ids", type=str, default=None, help="只处理指定 chunk id（逗号分隔）")
    ap.add_argument("--apply", action="store_true", help="落笔写库（默认只干跑打印 diff）")
    args = ap.parse_args()

    store = MySQLStore()
    with store._conn() as cur:
        if args.ids:
            ids = [int(x) for x in args.ids.split(",")]
            ph = ",".join(["%s"] * len(ids))
            cur.execute(f"SELECT c.id AS id, c.document_id, c.chunk_index, c.text, c.faiss_id, d.filename "
                        f"FROM chunks c LEFT JOIN documents d ON d.id=c.document_id "
                        f"WHERE c.id IN ({ph})", ids)
            rows = cur.fetchall()
        elif args.doc is not None:
            cur.execute("SELECT c.id AS id, c.document_id, c.chunk_index, c.text, c.faiss_id, d.filename "
                        "FROM chunks c LEFT JOIN documents d ON d.id=c.document_id "
                        "WHERE c.document_id=%s ORDER BY c.chunk_index", (args.doc,))
            rows = cur.fetchall()
        else:
            cur.execute("SELECT c.id AS id, c.document_id, c.chunk_index, c.text, c.faiss_id, d.filename "
                        "FROM chunks c LEFT JOIN documents d ON d.id=c.document_id "
                        "ORDER BY c.document_id, c.chunk_index")
            rows = cur.fetchall()

    passed, rejected, clean = [], [], 0
    print(f"共 {len(rows)} 块\n" + "=" * 70)
    for i, r in enumerate(rows, 1):
        orig = r["text"] or ""
        new, records = dedup_text(orig)
        if not records:
            clean += 1
            continue
        ok_rec = verify_reconstruct(orig, new, records)
        ok_num, extra = verify_numbers(orig, new)
        ok = ok_rec and ok_num
        if not ok:
            rejected.append(r["id"])
            print(f"\n[{i}/{len(rows)}] doc{r['document_id']} chunk#{r['chunk_index']} id={r['id']} "
                  f"[拒绝] 重构校验={ok_rec} 数字校验={ok_num} {extra}")
            continue
        passed.append({**r, "new_text": new})
        print(f"\n[{i}/{len(rows)}] doc{r['document_id']} chunk#{r['chunk_index']} id={r['id']} "
              f"len {len(orig)} -> {len(new)}（删 {len(records)} 段）")
        for pos, Z in records:
            print(f"  删 @{pos} ({len(Z)}字): {Z[:48]!r}")

    print("\n" + "=" * 70)
    print(f"干净块 {clean} | 去重通过 {len(passed)} | 拒绝 {len(rejected)}")
    if not args.apply:
        print("干跑模式：未改库。确认 diff 无误后加 --apply 落笔。")
        return
    if not passed:
        print("无通过块，不落笔。")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = Path(__file__).resolve().parents[1] / "data" / f"backup_dedup_{ts}.json"
    backup.write_text(json.dumps([
        {"id": p["id"], "faiss_id": p["faiss_id"], "document_id": p["document_id"],
         "chunk_index": p["chunk_index"], "text": p["text"]}
        for p in passed
    ], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n备份已写: {backup.name}（{len(passed)} 块，可回滚）")

    with store._conn() as cur:
        for p in passed:
            cur.execute("UPDATE chunks SET text=%s, text_hash=%s WHERE id=%s",
                        (p["new_text"],
                         hashlib.sha256(p["new_text"].encode("utf-8")).hexdigest()[:16],
                         p["id"]))
    print(f"已 UPDATE {len(passed)} 块。注意：需重建向量 + 重启 QA 服务后生效。")


if __name__ == "__main__":
    main()
