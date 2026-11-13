# -*- coding: utf-8 -*-
"""全量重灌模拟体检（只读，不进库）。

对 RAG_repository 全部源文件走重灌同路径（DocumentLoader.load_structured，
与 Indexer.ingest 一致），并忠实模拟 ingest 的判定：Chunker 分块 +
_chunk_is_garbage 块级过滤（真实入库唯一门控；ingest 无整篇退化硬门，
doc001 类政策新闻"责任单位"格式重复、doc002 类单行 txt 会触发 _ocr_degenerate
但块级过滤不误杀——整篇指标仅作信息性标注）。

文本缓存：load_structured 结果落盘 data/_reingest_cache/，重跑不重复 OCR。
产出：
- data/_reingest_audit.txt  每篇明细
- 控制台汇总：干净 / 有问题清单
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.service import ROOT, apply_environment, load_values

apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))
from app.document import DocumentLoader, Chunker, _ocr_degenerate, _is_cyclic_line
from app.rag import _chunk_is_garbage

_FOREIGN = re.compile(r"[\u0400-\u04FF\uAC00-\uD7AF\u0600-\u06FF]")
_TOKEN = re.compile(r"<\|[A-Z_]+\d+")
CACHE = ROOT / "data" / "_reingest_cache"


def load_cached(loader: DocumentLoader, path: Path):
    """load_structured + 磁盘缓存（重跑不重复 OCR）。"""
    key = CACHE / f"{path.name}.json"
    if key.exists():
        try:
            d = json.loads(key.read_text(encoding="utf-8"))
            if d.get("text") is not None:
                return d["text"]
        except Exception:
            pass
    text, meta = loader.load_structured(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    return text


def audit_one(loader: DocumentLoader, path: Path) -> dict:
    try:
        text = load_cached(loader, path)
    except Exception as e:
        return {"file": path.name, "ok": False, "fails": [f"加载异常: {str(e)[:80]}"]}
    fails = []
    if not text or len(text) < 500:
        fails.append(f"字数不足({len(text)})")
    # 真实 ingest 判定：Chunker 分块 + 块级垃圾过滤
    chunks = [cp[0] for cp in Chunker().split_with_positions(text)]
    garbage = sum(1 for c in chunks if _chunk_is_garbage(c))
    if chunks and garbage == len(chunks):
        fails.append("全块垃圾(不入库)")
    elif garbage > max(5, int(len(chunks) * 0.15)):
        fails.append(f"垃圾块超标({garbage}/{len(chunks)})")
    ok = not fails
    # 信息性标注（不计 fail，真实 ingest 无这些整篇门）
    notes = []
    if _ocr_degenerate(text):
        notes.append("整篇退化(块级未触发则无害)")
    if _TOKEN.search(text):
        notes.append("布局token")
    if _FOREIGN.search(text):
        notes.append("外文")
    if any(_is_cyclic_line(ln) for ln in text.splitlines()):
        notes.append("循环行")
    return {
        "file": path.name, "ok": ok, "fails": fails, "notes": notes,
        "chars": len(text), "chunks": len(chunks), "garbage": garbage,
    }


def main() -> None:
    repo = ROOT / "RAG_repository"
    files = sorted([f for f in repo.glob("*") if f.is_file()])
    loader = DocumentLoader()
    rows = []
    print(f"全量重灌模拟体检: {len(files)} 个源文件（只读，不进库；文本缓存 {CACHE.name}）...")
    for i, f in enumerate(files, 1):
        r = audit_one(loader, f)
        rows.append(r)
        tag = "OK " if r["ok"] else "BAD"
        note = f" [{','.join(r['notes'])}]" if r.get("notes") else ""
        detail = f" 字={r.get('chars', 0)} 块={r.get('chunks', 0)} 垃圾={r.get('garbage', 0)}"
        print(f"[{i:3}/{len(files)}] {tag} {f.name[:44]}{detail}{note}" + (f"  <- {r['fails']}" if not r["ok"] else ""))
        sys.stdout.flush()

    ok_n = sum(1 for r in rows if r["ok"])
    bad = [r for r in rows if not r["ok"]]
    lines = [
        f"全量重灌模拟体检 {len(files)} 篇: 干净={ok_n}, 有问题={len(bad)}",
        "---- 有问题清单 ----",
    ]
    for r in bad:
        lines.append(f"{r['file']}: {r['fails']} (字={r.get('chars', 0)} 垃圾块={r.get('garbage', 0)}/{r.get('chunks', 0)})")
    (ROOT / "data" / "_reingest_audit.txt").write_text("\n".join(lines), encoding="utf-8")
    print()
    print(f"==== 汇总: 干净 {ok_n}/{len(files)}，有问题 {len(bad)} 篇 ====")
    for r in bad:
        print("  ", r["file"][:52], r["fails"])
    print("明细落盘 data/_reingest_audit.txt")


if __name__ == "__main__":
    main()
