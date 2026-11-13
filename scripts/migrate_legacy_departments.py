"""存量知识库文档归属部门校正：密级=公开 的种子文档统一收敛为「不限部门」。

背景
----
owner_department -> departments(JSON 数组) 的迁移按旧字段逐条回填，把
RAG_repository 里的企业知识库文档（密级=公开、全公司共享）写成了 ["综合管理部"]。
「归属部门是可见范围唯一开关」语义上线后，这批文档对其它部门全部不可见。

校正规则（保守，只放宽明确属于公开共享的知识库文档）
----------------------------------------------------
  * source_path LIKE '%RAG_repository%'   种子导入，非用户上传
  * kms_doc_levels.level = 0               密级=公开（不放宽 L1~L3）
  * departments 不含 '*'                   尚未是「不限部门」
  =>
  departments = ["*"]，owner_department = '*'

用户上传的文档一律不动（保留上传时选定的归属部门）。幂等，可重复执行。

用法
----
    python scripts/migrate_legacy_departments.py           # 预演（只打印）
    python scripts/migrate_legacy_departments.py --apply   # 实际写入
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许以 `python scripts/xxx.py` 直接执行时导入仓库根目录的包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.store import MySQLStore  # noqa: E402
from kms.constants import DOC_DEPT_UNLIMITED  # noqa: E402

SELECT_SQL = """
    SELECT d.id, d.filename, d.departments, d.owner_department
    FROM documents d
    JOIN kms_doc_levels l ON l.document_id = d.id
    WHERE d.source_path LIKE %s
      AND l.level = 0
      AND NOT JSON_CONTAINS(COALESCE(d.departments, JSON_ARRAY()), JSON_QUOTE(%s))
    ORDER BY d.id
"""

UPDATE_SQL = """
    UPDATE documents SET departments = JSON_ARRAY(%s), owner_department = %s
    WHERE id = %s
"""

VISIBLE_SQL = """
    SELECT COUNT(*) AS n FROM documents d
    JOIN kms_doc_levels l ON l.document_id = d.id
    WHERE d.status='published' AND d.lifecycle_state='published'
      AND d.publication_approved=1
      AND (d.expires_at IS NULL OR d.expires_at > NOW())
      AND (JSON_CONTAINS(COALESCE(d.departments,JSON_ARRAY()), JSON_QUOTE(%s))
           OR JSON_CONTAINS(COALESCE(d.departments,JSON_ARRAY()), JSON_QUOTE(%s)))
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="校正存量文档归属部门")
    ap.add_argument("--apply", action="store_true", help="实际写入（缺省仅预演）")
    ap.add_argument("--like", default="%RAG_repository%", help="种子来源匹配模式")
    args = ap.parse_args()

    # 连接信息一律来自 .env / settings，脚本内不保存任何库口令
    with MySQLStore().transaction() as cur:
        cur.execute(SELECT_SQL, (args.like, DOC_DEPT_UNLIMITED))
        rows = cur.fetchall()

        print(f"命中待校正文档：{len(rows)} 篇"
              f"（来源 LIKE {args.like!r}，密级=公开，归属部门不含「不限」）")
        by_dept: dict[str, int] = {}
        for r in rows:
            try:
                depts = json.loads(r["departments"] or "[]")
            except (TypeError, ValueError):
                depts = []
            key = ",".join(depts) or "(空)"
            by_dept[key] = by_dept.get(key, 0) + 1
        for key, cnt in sorted(by_dept.items(), key=lambda x: -x[1]):
            print(f"  {key} -> {cnt} 篇")

        if not args.apply:
            print("\n[预演] 未写入。加 --apply 执行。")
            return 0

        for r in rows:
            cur.execute(UPDATE_SQL,
                        (DOC_DEPT_UNLIMITED, DOC_DEPT_UNLIMITED, r["id"]))
    print(f"\n[已完成] {len(rows)} 篇文档归属部门置为「不限」，密级仍为公开。")

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT DISTINCT department FROM kms_users "
                    "WHERE is_active=1 AND department<>''")
        depts = [d["department"] for d in cur.fetchall()]
        for dept in depts:
            cur.execute(VISIBLE_SQL, (DOC_DEPT_UNLIMITED, dept))
            print(f"  {dept} 可读已发布文档：{cur.fetchone()['n']} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
