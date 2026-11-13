# -*- coding: utf-8 -*-
"""L0 清洗规则增量应用器：规则库演进后，只重写「输出确实发生变化」的存量块，免全量重灌。

背景：app/typo_clean.py 新增规则后，已入库文本不会自动受益。全量重灌代价高
      （扫描件需 OCR，外部 API 稳定性是主要瓶颈）。本脚本对 chunks.text 就地
      重跑 clean_ocr_typos —— 该函数设计为幂等，对已干净文本零副作用，故只有
      真正命中新形态的块会被改写。

安全红线（与 repair_inner_dup / db_batch_swap 同风格）：
    1. 数字段校验：清洗后数字多重集必须与原文一致（错字清洗不得改动任何数字）。
    2. 只缩短或等长：清洗串长度 > 原文的块直接拒绝（防规则写错放大文本）。
    3. 落笔前备份到 data/backup_typoclean_{ts}.json，可完整回滚。
    4. 文本变了就同步重建该块 FAISS 向量并回写 faiss_id，避免文本-向量漂移。

用法：
    python scripts/apply_typo_clean.py              # 全库干跑（只打印）
    python scripts/apply_typo_clean.py --doc 20     # 指定文档干跑
    python scripts/apply_typo_clean.py --apply      # 落笔（备份 + UPDATE + 重灌向量）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.service import apply_environment, load_values

apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))

from app.store import MySQLStore, VectorStore
from app.clients import EmbeddingClient
from app.typo_clean import clean_ocr_typos

NUM_SEG_RE = re.compile(r"-?\d[\d,]*\.?\d*[%％]?")


def verify_numbers(orig: str, new: str) -> tuple[bool, list]:
    """清洗不得增删改任何数字段（多重集必须相等）。"""
    o, n = Counter(NUM_SEG_RE.findall(orig)), Counter(NUM_SEG_RE.findall(new))
    extra = list((n - o).items())[:5] + list((o - n).items())[:5]
    return o == n, extra


def only_whitespace_growth(orig: str, new: str) -> bool:
    """允许「只新增空白/换行」的变长（章节标题粘连补 \n 属结构改善），
    其余任何变长一律拒绝（防规则写错放大文本）。"""
    return len(new) <= len(orig) or re.sub(r"\s+", "", new) == re.sub(r"\s+", "", orig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", type=int, default=None, help="只处理指定 document_id")
    ap.add_argument("--apply", action="store_true", help="落笔写库（默认只干跑）")
    args = ap.parse_args()

    store = MySQLStore()
    with store._conn() as cur:
        if args.doc is not None:
            cur.execute(
                "SELECT id, document_id, chunk_index, text, faiss_id, text_hash, embedding_model "
                "FROM chunks WHERE document_id=%s ORDER BY chunk_index", (args.doc,))
        else:
            cur.execute(
                "SELECT id, document_id, chunk_index, text, faiss_id, text_hash, embedding_model "
                "FROM chunks ORDER BY document_id, chunk_index")
        rows = cur.fetchall()

    changed, rejected = [], []
    for r in rows:
        orig = r["text"] or ""
        new = clean_ocr_typos(orig)
        if new == orig:
            continue
        ok_num, extra = verify_numbers(orig, new)
        if not ok_num or not only_whitespace_growth(orig, new):
            rejected.append((r["id"], f"数字校验={ok_num} 长度{len(orig)}->{len(new)}", extra))
            continue
        changed.append({**r, "new_text": new})

    print(f"共 {len(rows)} 块 | 命中清洗 {len(changed)} | 拒绝 {len(rejected)}")
    for c in changed:
        print(f"\n  doc{c['document_id']} chunk#{c['chunk_index']} id={c['id']} "
              f"len {len(c['text'])} -> {len(c['new_text'])}")
        for i, (a, b) in enumerate(zip(c["text"], c["new_text"])):
            if a != b:
                s = max(0, i - 12)
                print(f"    原文: ...{c['text'][s:i + 14]!r}")
                print(f"    新文: ...{c['new_text'][s:i + 14]!r}")
                break
    for rid, why, extra in rejected:
        print(f"\n  [拒绝] id={rid} {why} {extra}")

    if not args.apply:
        print("\n干跑模式：未改库。确认无误后加 --apply 落笔。")
        return
    if not changed:
        print("无命中块，不落笔。")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "data" / f"backup_typoclean_{ts}.json"
    backup.write_text(json.dumps([
        {"id": c["id"], "faiss_id": c["faiss_id"], "document_id": c["document_id"],
         "chunk_index": c["chunk_index"], "text": c["text"], "text_hash": c["text_hash"]}
        for c in changed
    ], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n备份已写: {backup.name}（{len(changed)} 块，可回滚）")

    vecs = EmbeddingClient().embed([c["new_text"] for c in changed])
    v = VectorStore()
    v.load()
    before = v.total
    with store._conn() as cur:
        for c, vec in zip(changed, vecs):
            removed = v.remove([c["faiss_id"]])
            new_fid = v.add([vec])[0]
            th = hashlib.sha256(c["new_text"].encode("utf-8")).hexdigest()[:16]
            cur.execute("UPDATE chunks SET text=%s, text_hash=%s, faiss_id=%s WHERE id=%s",
                        (c["new_text"], th, new_fid, c["id"]))
            print(f"  id={c['id']} doc{c['document_id']}#{c['chunk_index']}: "
                  f"faiss_id {c['faiss_id']} -> {new_fid} (removed={removed})")
    v.save()
    print(f"已 UPDATE {len(changed)} 块。FAISS total: {before} -> {v.total}")


if __name__ == "__main__":
    main()
