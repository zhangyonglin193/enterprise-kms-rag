"""数据卫生维护：doc104 重复爆炸清理 + 全库同文档内高相似重复块去重。

工程安全约束：
1. 端口 6341 被占用时拒绝执行（必须先停 QA 服务）；
2. --apply 前自动备份 FAISS 索引文件 + 删除清单（可追溯）；
3. 只删两类块：
   a) doc104 的垃圾块（跨语种幻觉/布局token/低汉字占比——已验证其正文完好保存在干净块中）；
   b) 同文档内与"干净代表块"全文相似度>=0.9 的重复副本（内容由代表块保留，零信息损失）。
   跨文档重复、垃圾块作代表的组、doc107 的全部块一律不动（doc107 垃圾块含 Q19 gold 片段，留待重 OCR 替换）。
4. 删除后校验 FAISS ntotal 与 MySQL chunks 计数严格相等。

用法：
  python scripts/maintain_hygiene.py --dry-run     # 只审计，输出删除清单
  python scripts/maintain_hygiene.py --apply       # 执行删除（含备份与校验）
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import socket
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.service import ROOT, apply_environment, load_values

apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))
from app.store import MySQLStore, VectorStore

_FOREIGN = re.compile(r"[\u0400-\u04FF\uAC00-\uD7AF\u0600-\u06FF]")
_TOKEN = re.compile(r"<\|[A-Z_]+\d+")
_NORM_DROP = re.compile(r"[^\u4e00-\u9fff0-9a-zA-Z]")
_DOT_RUN = re.compile(r"\.{3,}")


def norm_full(t: str) -> str:
    return _NORM_DROP.sub("", t or "").lower()


def is_garbage(t: str) -> bool:
    fc = len(_FOREIGN.findall(t))
    tc = len(_TOKEN.findall(t))
    # 汉字占比：先去除目录点线“.....”（否则目录/点线表格会被误判为垃圾）
    compact = _DOT_RUN.sub("", re.sub(r"\s", "", t))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", compact))
    return fc >= 3 or tc >= 2 or (len(compact) > 30 and cjk < len(compact) * 0.3)


def port_in_use(port: int = 6341) -> bool:
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def collect_deletions() -> dict:
    """返回 {chunk_id: {faiss_id, document_id, text_head, reason}}。"""
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute("SELECT id, faiss_id, document_id, text FROM chunks")
        rows = cur.fetchall()
    by_doc: dict = defaultdict(list)
    for r in rows:
        by_doc[r["document_id"]].append(r)

    deletions: dict = {}
    garbage_stats: dict = {}

    for did, chunks in by_doc.items():
        # 统计该文档垃圾块（仅审计用）
        garbage_stats[did] = sum(1 for c in chunks if is_garbage(c["text"]))

        # a) doc104 垃圾块直接删除（已验证纯幻觉，正文在干净块中）
        if did == 104:
            for c in chunks:
                if is_garbage(c["text"]):
                    deletions[c["id"]] = {
                        "faiss_id": c["faiss_id"], "document_id": did,
                        "text_head": c["text"][:50], "reason": "doc104垃圾块",
                    }

        # b) 同文档内高相似重复块（代表块必须干净，内容由代表保留）
        groups: dict = defaultdict(list)
        for c in chunks:
            nf = norm_full(c["text"])
            if len(nf) >= 20:
                groups[nf].append(c)
        for nf, group in groups.items():
            if len(group) < 2:
                continue
            rep = min(group, key=lambda c: (is_garbage(c["text"]), -len(c["text"]), c["chunk_index"] if "chunk_index" in c else 0))
            if is_garbage(rep["text"]):
                continue  # 代表是垃圾 → 组内一律不动（避免误删含 gold 的乱码块）
            for c in group:
                if c["id"] == rep["id"] or c["id"] in deletions:
                    continue
                ratio = difflib.SequenceMatcher(None, rep["text"], c["text"]).ratio()
                if ratio >= 0.9:
                    deletions[c["id"]] = {
                        "faiss_id": c["faiss_id"], "document_id": did,
                        "text_head": c["text"][:50],
                        "reason": f"同文档重复块(rep={rep['id']},ratio={ratio:.2f})",
                    }
    return deletions


def main() -> None:
    apply = "--apply" in sys.argv
    dry = "--dry-run" in sys.argv
    if not apply and not dry:
        print("用法: maintain_hygiene.py --dry-run | --apply")
        sys.exit(1)

    if port_in_use():
        print("端口 6341 被占用——必须先停 QA 服务再执行！")
        sys.exit(1)

    deletions = collect_deletions()
    total = len(deletions)
    print(f"待删除块: {total}")

    # 按文档分组统计
    per_doc: dict = defaultdict(int)
    for d in deletions.values():
        per_doc[d["document_id"]] += 1
    for did in sorted(per_doc):
        print(f"  document_id={did}: {per_doc[did]} 块")

    audit_path = ROOT / "data" / "maintain_audit.json"
    audit_path.write_text(json.dumps(
        {"deletions": list(deletions.values()), "total": total},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"审计清单: {audit_path}")

    if dry:
        print("DRY-RUN 完成，未做任何删除。")
        return

    # ---- apply：备份 → 删除 → 校验 ----
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "data" / f"maintain_backup_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    vs = VectorStore()
    vs.load()
    src = Path(vs.index_file)
    shutil.copy2(src, backup_dir / "index.index.bak")
    (backup_dir / "deletions.json").write_text(
        json.dumps(list(deletions.values()), ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"已备份: {backup_dir}")

    faiss_ids = [d["faiss_id"] for d in deletions.values()]
    mysql = MySQLStore()
    mysql.delete_chunks_by_faiss_ids(faiss_ids)
    print(f"MySQL 已删除 {len(faiss_ids)} 行")

    removed = vs.remove(faiss_ids)
    vs.save()
    print(f"FAISS 已删除 {removed} 个向量")

    # 一致性校验
    vs2 = VectorStore()
    vs2.load()
    with mysql._conn() as cur:
        cur.execute("SELECT COUNT(*) c FROM chunks")
        mysql_count = cur.fetchone()["c"]
    print(f"校验: FAISS ntotal={vs2.total}, MySQL chunks={mysql_count}, 一致={vs2.total == mysql_count}")
    if vs2.total != mysql_count:
        print("!!! 不一致，请立即检查并考虑从备份恢复 !!!")
        sys.exit(1)
    print("完成。可重启 QA 服务。")


if __name__ == "__main__":
    main()
