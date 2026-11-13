# -*- coding: utf-8 -*-
"""知识库回滚（通用工具）：从 backup_db.py 生成的备份目录恢复 FAISS + MySQL。

用法（须停服务后执行）：
    python scripts/restore_db.py data/pre_reingest_backup_<ts>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.service import ROOT, apply_environment, load_values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("backup_dir", help="backup_db.py 输出的备份目录")
    args = ap.parse_args()

    backup = Path(args.backup_dir)
    if not (backup / "mysql_dump.json").exists():
        ap.error(f"备份目录不完整（缺 mysql_dump.json）: {backup}")

    apply_environment(str(ROOT / ".env"), load_values(str(ROOT / ".env")))

    from app.logger import get_logger
    from app.store import MySQLStore
    from config import settings

    logger = get_logger("restore")

    dump = json.loads((backup / "mysql_dump.json").read_text(encoding="utf-8"))
    docs, chunks = dump["documents"], dump["chunks"]
    logger.info(f"备份内容：{len(docs)} 文档 / {len(chunks)} 块")

    # 1. 恢复 MySQL（清空后按原 id 插回）
    mysql = MySQLStore()
    with mysql._conn() as cur:
        cur.execute("DELETE FROM chunks")
        cur.execute("DELETE FROM documents")
        for d in docs:
            cols = ", ".join(f"`{k}`" for k in d.keys())
            ph = ", ".join(["%s"] * len(d))
            cur.execute(f"INSERT INTO documents ({cols}) VALUES ({ph})", list(d.values()))
        for c in chunks:
            cols = ", ".join(f"`{k}`" for k in c.keys())
            ph = ", ".join(["%s"] * len(c))
            cur.execute(f"INSERT INTO chunks ({cols}) VALUES ({ph})", list(c.values()))
    logger.info("MySQL 已恢复")

    # 2. 恢复 FAISS 索引
    index_file = Path(str(settings.faiss_index_path) + ".index")
    bak_index = backup / index_file.name
    if bak_index.exists():
        shutil.copy2(bak_index, index_file)
        logger.info(f"FAISS 索引已恢复: {index_file}")
    else:
        logger.warning("备份中无 FAISS 索引，跳过（需自行重建）")

    logger.info("回滚完成，可重启服务")


if __name__ == "__main__":
    main()
