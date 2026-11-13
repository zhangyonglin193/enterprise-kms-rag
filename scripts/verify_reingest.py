# -*- coding: utf-8 -*-
"""重灌后通用验收（可复用）：双存储一致性 + 残余垃圾块审计 + 关键短语存在性。

用法（服务停止时或运行时均可，只读）：
    python scripts/verify_reingest.py
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.service import apply_environment, load_values
apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))
from app.store import MySQLStore
from app.rag import _chunk_is_garbage

OUT = ROOT / "data" / "verify_reingest.txt"
L = []
mysql = MySQLStore()

# 1. 双存储一致性
with mysql._conn() as cur:
    cur.execute("SELECT COUNT(*) n FROM chunks")
    mysql_n = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(DISTINCT document_id) n FROM chunks")
    docs_with_chunks = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) n FROM documents")
    docs_total = cur.fetchone()["n"]
    cur.execute("SELECT c.document_id FROM chunks c LEFT JOIN documents d ON d.id=c.document_id WHERE d.id IS NULL LIMIT 5")
    orphan = cur.fetchall()
    cur.execute("SELECT c.faiss_id, LEFT(MIN(c.text),60) t FROM chunks c GROUP BY c.faiss_id HAVING COUNT(*)>1 LIMIT 3")
    dup_faiss = cur.fetchall()

from app.rag import Retriever
retriever = Retriever()
retriever.warmup()  # warmup 内部有一致性校验日志
faiss_n = retriever.vector_store.total
L.append("=== 1. 双存储一致性 ===")
L.append(f"FAISS ntotal={faiss_n}  MySQL chunks={mysql_n}  -> {'PASS' if faiss_n == mysql_n else 'FAIL'}")
L.append(f"documents={docs_total} 有块的文档={docs_with_chunks} 孤儿块={len(orphan)} 重复faiss_id组={len(dup_faiss)}")
if orphan:
    L.append(f"  孤儿块样例: {orphan[:3]}")
if dup_faiss:
    L.append(f"  重复faiss样例: {dup_faiss}")

# 2. 残余垃圾块审计（全库）
with mysql._conn() as cur:
    cur.execute("SELECT text FROM chunks")
    rows = cur.fetchall()
garbage = [r["text"] for r in rows if _chunk_is_garbage(r["text"])]
L.append("\n=== 2. 残余垃圾审计 ===")
L.append(f"全库 {len(rows)} 块，仍命中垃圾签名 {len(garbage)} 块 ({len(garbage)/max(len(rows),1):.2%})")
for g in garbage[:5]:
    L.append(f"  样例: {g[:70]!r}")

# 3. 关键短语存在性（覆盖历史未命中题的源内容）
CHECKS = [
    ("doc102 Q44 牌照表格", "预付卡受理（全国）"),
    ("doc102 Q44 牌照表格", "广州银联网络支付"),
    ("doc120 Q91/94 参数表", "打印宽度"),
    ("doc120 Q91/94 参数表", "58mm"),
    ("doc104 MCC 码", "8398"),
    ("doc109 SN 示例", "95534"),
    ("doc084 898公式", "898"),
    ("doc087 898公式", "商户编号设置为"),
    ("doc107 Q19 原则句", "谁的商户谁负责"),
]
L.append("\n=== 3. 关键短语存在性 ===")
with mysql._conn() as cur:
    for label, phrase in CHECKS:
        cur.execute("SELECT COUNT(*) n FROM chunks WHERE text LIKE %s", (f"%{phrase}%",))
        n = cur.fetchone()["n"]
        L.append(f"[{'PASS' if n > 0 else 'MISS'}] {label}: '{phrase}' 命中 {n} 块")

OUT.write_text("\n".join(L), encoding="utf-8")
print("done")
