# -*- coding: utf-8 -*-
"""知识库全量备份（通用工具）：FAISS 索引 + MySQL documents/chunks 全表导出 JSON。

用于重灌前的可回滚备份。恢复见 scripts/restore_db.py。

用法（建议停服务后执行，避免索引文件读写竞争）：
    python scripts/backup_db.py [--out data/pre_reingest_backup_auto]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.service import ROOT, apply_environment, load_values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="备份目录（默认 data/pre_reingest_backup_<时间戳>）")
    args = ap.parse_args()

    apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))

    from app.logger import get_logger
    from app.store import MySQLStore
    from config import settings

    logger = get_logger("backup")

    out = Path(args.out) if args.out else ROOT / "data" / f"pre_reingest_backup_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)

    # 1. FAISS 索引
    index_file = Path(str(settings.faiss_index_path) + ".index")
    if index_file.exists():
        shutil.copy2(index_file, out / index_file.name)
        logger.info(f"FAISS 索引已备份: {index_file.name}")
    else:
        logger.warning(f"FAISS 索引不存在，跳过: {index_file}")

    # 2. MySQL 全表导出
    mysql = MySQLStore()
    dump = {"documents": [], "chunks": []}
    with mysql._conn() as cur:
        cur.execute("SELECT * FROM documents")
        dump["documents"] = cur.fetchall()
        cur.execute("SELECT * FROM chunks")
        dump["chunks"] = cur.fetchall()

    json_path = out / "mysql_dump.json"
    json_path.write_text(
        json.dumps(dump, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )

    # 3. 元信息
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "documents": len(dump["documents"]),
        "chunks": len(dump["chunks"]),
        "faiss_index": index_file.name if index_file.exists() else None,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"备份完成: {out}（{meta['documents']} 文档 / {meta['chunks']} 块）")
    print(out)


if __name__ == "__main__":
    main()
