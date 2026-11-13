"""清理 FAISS 中「MySQL 已无对应 chunks 行」的孤儿向量。

触发场景：绕过正常入库/删除流程直接改库——例如 E2E 脚本在 finally 里
`DELETE FROM chunks / documents` 却没同步删 FAISS 向量。后果是启动守卫
（app/rag.py::warmup）比对 set(FAISS ids) 与 set(chunks.faiss_id) 不等，
直接 RuntimeError 拒绝启动（守卫刻意禁止"自动删库修复"）。

**注意 QA 与 KMS 是两套独立环境**（不同 env 文件 / 不同 FAISS 索引 / 不同库）：
  - QA : .env      → data/faiss/index
  - KMS: .env.kms  → data/kms/faiss/index.index
默认按 KMS 修，可用 --env-file 指定。脚本会先打印「实际库名 + 索引路径」，
避免修错对象。

本脚本只删 FAISS 里多余的向量：不写 MySQL、不动仍被 chunks 引用的向量。
若反向出现「MySQL 有 chunk 但 FAISS 缺向量」，脚本只报告并返回非零
—— 那种情况必须重新入库，不能在这里伪造向量。

用法：
    python scripts/repair_faiss_orphans.py                       # KMS 预演
    python scripts/repair_faiss_orphans.py --apply               # KMS 修复
    python scripts/repair_faiss_orphans.py --env-file .env       # QA 预演
"""
from __future__ import annotations

import argparse
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.service import apply_environment, load_values  # noqa: E402


def port_in_use(port: int) -> bool:
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="只审计（默认）")
    g.add_argument("--apply", action="store_true", help="备份后执行修复")
    ap.add_argument("--env-file", default=str(ROOT / ".env.kms"),
                    help="环境文件（默认 .env.kms 即 KMS）")
    args = ap.parse_args()
    dry = not args.apply

    env_file = Path(args.env_file).resolve()
    if not env_file.is_file():
        print(f"环境文件不存在：{env_file}")
        return 2
    values = load_values(str(env_file))
    apply_environment(str(env_file), values)

    # settings 在导入时读取环境变量，必须在 apply_environment 之后导入
    from app.store import MySQLStore, VectorStore  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    print(f"环境文件：{env_file}")
    print(f"数据库：  {values.get('MYSQL_DATABASE', '(未指定)')}")
    print(f"FAISS：   {settings.faiss_index_path}")

    for key in ("QA_PORT", "KMS_PORT"):
        port = int(values.get(key, 0) or 0)
        if port and port_in_use(port):
            print(f"端口 {port}（{key}）上有服务在运行，请先停止服务再修复。")
            return 2

    vs = VectorStore()
    vs.load()
    faiss_ids = [int(x) for x in vs.ids()]
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT faiss_id FROM chunks")
        mysql_ids = {int(r["faiss_id"]) for r in cur.fetchall()}

    faiss_set = set(faiss_ids)
    orphan = sorted(faiss_set - mysql_ids)
    missing = sorted(mysql_ids - faiss_set)
    print(f"FAISS 向量={len(faiss_ids)}（去重 {len(faiss_set)}）  "
          f"MySQL chunks={len(mysql_ids)}  孤儿={len(orphan)}  缺失={len(missing)}")

    if len(faiss_set) != len(faiss_ids):
        print("FAISS 内部存在重复 id，需另行处理。")
    if missing:
        print(f"!!! MySQL 有 chunks 但 FAISS 无向量（须重新入库）：{missing[:20]}")
    if orphan:
        print(f"孤儿向量（将删除）：{orphan[:30]}{' …' if len(orphan) > 30 else ''}")
    if not orphan:
        if not missing:
            print("无需修复。")
        return 0 if not missing else 1

    if dry:
        print("\nDRY-RUN 完成，未改动任何数据。加 --apply 执行。")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "data" / f"faiss_repair_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(vs.index_file), backup_dir / "index.index.bak")
    (backup_dir / "orphans.txt").write_text(
        "\n".join(str(x) for x in orphan), encoding="utf-8")
    print(f"已备份索引与清单：{backup_dir}")

    removed = vs.remove(orphan)
    vs.save()
    print(f"FAISS 已删除 {removed} 个向量")

    vs2 = VectorStore()
    vs2.load()
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM chunks")
        mysql_count = int(cur.fetchone()["c"])
    ok = vs2.total == mysql_count
    print(f"校验：FAISS ntotal={vs2.total}  MySQL chunks={mysql_count}  一致={ok}")
    if not ok:
        print("!!! 仍不一致，请从备份恢复后排查 !!!")
        return 1
    print("完成，可重新启动服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
