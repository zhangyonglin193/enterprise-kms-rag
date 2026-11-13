"""CLI 入库脚本。

用法：
    python scripts/ingest.py data/docs/a.pdf
    python scripts/ingest.py data/docs/   # 批量入库目录
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让脚本能直接 import 项目根目录下的包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import Indexer  # noqa: E402
from kms.formats import ALLOWED_EXTS, collect_files  # noqa: E402


def collect(path: str) -> list[Path]:
    """收集待入库文件（实现已统一到 kms.formats.collect_files）。"""
    return collect_files(path, ALLOWED_EXTS)


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/ingest.py <文件或目录>")
        sys.exit(1)

    indexer = Indexer()
    files = collect(sys.argv[1])
    if not files:
        print("未找到可入库的文件")
        sys.exit(1)

    for f in files:
        print(f"入库中: {f}")
        try:
            result = indexer.ingest(f)
            if result.get("skipped"):
                print(f"  跳过(已存在, doc_id={result['document_id']})")
            else:
                print(f"  完成: doc_id={result['document_id']}, 分块数={result['chunk_count']}")
        except Exception as e:
            print(f"  失败: {e}")


if __name__ == "__main__":
    main()
