# -*- coding: utf-8 -*-
"""共享 helper 契约测试：kms/formats.py 与 kms/pagination.py。

锁死「单一事实源」的收益：
  - 格式白名单：上传入口与入库脚本共用同一判据，不再出现「能入库却传不上来」；
  - 分页归一化：外部入口（MCP）必须受上限约束，避免 limit=999999 全表扫描。
"""
from __future__ import annotations

import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from scripts.service import apply_environment

RUN = ROOT / "data" / "test-runs" / uuid.uuid4().hex
apply_environment(RUN / "absent.env", {
    "MYSQL_DATABASE": "offline_test_only",
    "KMS_SECRET_KEY": "offline-test-key-not-for-production-0123456789",
    "KMS_APPROVER_EMPLOYEES": "approver",
    "KMS_ADMIN_EMPLOYEES": "admin", "KMS_AUDITOR_EMPLOYEES": "auditor",
    "FAISS_INDEX_PATH": str(RUN / "faiss" / "index"),
    "UPLOAD_DIR": str(RUN / "uploads"),
    "DOCS_DIR": str(RUN / "docs"),
    "GW_AUDIT_DIR": str(RUN / "audit"),
    "GW_STATE_PATH": str(RUN / "state.sqlite3"),
})

from kms.formats import (ALLOWED_EXTS, IMAGE_EXTS, TEXT_EXTS,  # noqa: E402
                         collect_files, is_allowed, normalize_ext)
from kms.pagination import (DEFAULT_LIMIT, MAX_LIMIT,  # noqa: E402
                            clamp_pagination)


class FormatsTests(unittest.TestCase):
    """格式白名单：单一判据 + 目录收集。"""

    def test_upload_and_ingest_share_one_source(self):
        """上传入口与入库脚本必须判同一套格式（原来 5 份拷贝互相矛盾）。"""
        self.assertIn(".csv", ALLOWED_EXTS)     # 入库脚本一直收
        self.assertIn(".png", ALLOWED_EXTS)     # 图片也走 OCR
        self.assertTrue(is_allowed("a.PDF"))    # 大小写不敏感

    def test_text_and_image_layers_are_explicit(self):
        """演示等场景可显式只要文本层，而不必再抄一份白名单。"""
        self.assertTrue(TEXT_EXTS.isdisjoint(IMAGE_EXTS))
        self.assertEqual(ALLOWED_EXTS, TEXT_EXTS | IMAGE_EXTS)
        self.assertTrue(is_allowed("x.md", TEXT_EXTS))
        self.assertFalse(is_allowed("x.png", TEXT_EXTS))

    def test_normalize_ext_handles_no_suffix(self):
        self.assertEqual(normalize_ext("README"), "")
        self.assertEqual(normalize_ext("a/b/c.tar.gz"), ".gz")

    def test_unsupported_rejected(self):
        for bad in ("a.exe", "a.sh", "a.zip", "noext"):
            self.assertFalse(is_allowed(bad), bad)

    def test_collect_files_directory_is_sorted_and_filtered(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "b.pdf").write_bytes(b"x")
            (d / "a.txt").write_bytes(b"x")
            (d / "c.exe").write_bytes(b"x")
            (d / "sub").mkdir()
            (d / "sub" / "d.md").write_bytes(b"x")
            got = [p.name for p in collect_files(d)]
            self.assertEqual(got, ["a.txt", "b.pdf", "d.md"])  # 过滤+排序稳定

    def test_collect_files_single_file_passes_through(self):
        """显式指定单文件时信任调用方意图，不再二次过滤。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "only.dat"
            f.write_bytes(b"x")
            self.assertEqual(collect_files(f), [f])

    def test_collect_files_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            collect_files("/nonexistent/path/xyz")


class PaginationTests(unittest.TestCase):
    """分页归一化：外部入口必须有上限。"""

    def test_huge_limit_is_clamped(self):
        """MCP 原写法无上限，外部可传 limit=999999 触发全表扫描。"""
        _, limit = clamp_pagination(0, 999999)
        self.assertEqual(limit, MAX_LIMIT)

    def test_defaults_and_floors(self):
        self.assertEqual(clamp_pagination(), (0, DEFAULT_LIMIT))
        self.assertEqual(clamp_pagination(-5, 0), (0, 1))     # offset 不为负、limit 至少 1
        self.assertEqual(clamp_pagination(None, None), (0, DEFAULT_LIMIT))

    def test_non_numeric_falls_back_to_default(self):
        """分页参数不该成为请求失败的原因。"""
        self.assertEqual(clamp_pagination("abc", "xyz"), (0, DEFAULT_LIMIT))
        self.assertEqual(clamp_pagination("10", "30"), (10, 30))

    def test_custom_max_limit(self):
        self.assertEqual(clamp_pagination(0, 500, max_limit=50)[1], 50)

    def test_within_range_passes_through(self):
        self.assertEqual(clamp_pagination(20, 20), (20, 20))


if __name__ == "__main__":
    unittest.main()
