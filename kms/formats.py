"""文档格式白名单与目录收集（单一事实源）。

改造前同一套「支持哪些格式」有 **5 份互相矛盾的拷贝**：

    gateway/routes_kms.py:129    上传入口只认 5 种（pdf/docx/txt/md/xlsx）
    scripts/ingest.py:17         18 种（含图片）
    scripts/ingest_batch.py:27   17 种
    scripts/reingest_all.py:24   17 种
    scripts/seed_kms_demo.py:27  11 种（去掉图片）

后果：**同一份文档，走入库脚本能收、走上传入口却 422 拒绝**——策略边界取决于
走哪条路，而不是文档本身是否受支持。`collect()` 函数体也因此抄了 4 遍。

此处收敛为一份定义 + 一个 helper，上传入口与入库脚本共用同一判据。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

# 可直接解析出文本的格式（与 DocumentLoader.load() 的分发一一对应）
TEXT_EXTS = frozenset({
    ".pdf", ".docx", ".doc", ".md", ".markdown",
    ".txt", ".text", ".csv", ".json", ".xml", ".html", ".htm", ".xlsx",
})

# 需走 OCR 的图片格式
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"})

# 入库/检索链路支持的完整集合
ALLOWED_EXTS = TEXT_EXTS | IMAGE_EXTS


def normalize_ext(filename: str | Path) -> str:
    """规范化扩展名（小写、含前导点）；无扩展名返回空串。"""
    return Path(str(filename)).suffix.lower()


def is_allowed(filename: str | Path,
               allowed: Iterable[str] = ALLOWED_EXTS) -> bool:
    """判断文件是否属于受支持格式。"""
    return normalize_ext(filename) in frozenset(allowed)


def collect_files(root: str | Path,
                  allowed: Iterable[str] = ALLOWED_EXTS) -> List[Path]:
    """递归收集受支持的文件。

    目录：按 `allowed` 过滤后**排序**返回（保证入库顺序稳定可复现）；
    单文件：直接返回——调用方显式指定单个文件时信任其意图，不再二次过滤。

    原 4 份 `collect()` 实现在此统一；排序行为与 reingest_all.py 一致。
    """
    path = Path(root)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(str(root))
    allowed_set = frozenset(allowed)
    return sorted(f for f in path.rglob("*")
                  if f.is_file() and f.suffix.lower() in allowed_set)
