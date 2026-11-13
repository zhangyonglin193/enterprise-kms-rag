"""CLI 问答脚本。

用法：
    python scripts/query.py "你的问题"
    python scripts/query.py "你的问题" --session abc123
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import Retriever  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="RAG 命令行问答")
    parser.add_argument("question", help="问题")
    parser.add_argument("--session", default=None, help="会话 ID（用于多轮）")
    args = parser.parse_args()

    retriever = Retriever()
    retriever.warmup()
    result = retriever.answer(args.question, session_id=args.session)

    print("\n=== 回答 ===")
    print(result["answer"])
    print(f"\n=== 会话ID: {result['session_id']} ===")


if __name__ == "__main__":
    main()
