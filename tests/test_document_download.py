"""文档原文下载（GET /kms/api/documents/{id}/download）的安全回归。

下载端点的核心风险不是"能不能下载"，而是**能不能读到不该读的文件**：
source_path 来自数据库，若被污染成 ../../etc/passwd 或绝对路径，而解析时
没有边界校验，就会退化成任意文件读取（LFI）。

这里用伪造的 DB 返回值驱动 _resolve_source_file，验证三重防护确实生效：
  1. 相对路径按 upload_dir 解析、绝对路径原样使用；
  2. resolve() 后必须**严格位于** upload_dir 之内（等于 upload_dir 也不行）；
  3. 必须是已存在的普通文件。
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from fastapi import params as fastapi_params


def _resolve_with(raw):
    """用伪造的 source_path 驱动 _resolve_source_file（离线，不碰真实 MySQL）。"""
    from gateway.routes_kms import _resolve_source_file

    cur = MagicMock()
    cur.fetchone.return_value = {"source_path": raw}
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=cur)
    conn.__exit__ = MagicMock(return_value=False)
    store = MagicMock()
    store._conn.return_value = conn
    with patch("gateway.routes_kms.MySQLStore", return_value=store):
        return _resolve_source_file(1)


class DownloadPathGuardTests(unittest.TestCase):
    def test_rejects_relative_traversal(self):
        self.assertIsNone(_resolve_with("../../etc/passwd"))

    def test_rejects_absolute_path_outside(self):
        self.assertIsNone(_resolve_with("/etc/passwd"))

    def test_rejects_empty_source_path(self):
        self.assertIsNone(_resolve_with(""))
        self.assertIsNone(_resolve_with(None))

    def test_rejects_missing_file(self):
        """路径合法但文件不存在（入库后被清理）也必须拒绝。"""
        self.assertIsNone(_resolve_with("definitely-not-here.docx"))

    def test_upload_dir_itself_is_not_servable(self):
        """等于 upload_dir 本身不允许——那是目录，不是文档。"""
        from config import settings

        self.assertIsNone(_resolve_with(str(settings.upload_dir)))

    def test_missing_document_row(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=cur)
        conn.__exit__ = MagicMock(return_value=False)
        store = MagicMock()
        store._conn.return_value = conn
        from gateway.routes_kms import _resolve_source_file

        with patch("gateway.routes_kms.MySQLStore", return_value=store):
            self.assertIsNone(_resolve_source_file(999))


class DownloadAuthTests(unittest.TestCase):
    def test_download_route_requires_auth(self):
        from gateway.routes_kms import router
        from kms.security import require_user

        matched = [r for r in router.routes
                   if getattr(r, "path", "").endswith("/documents/{doc_id}/download")]
        self.assertTrue(matched, "下载端点未注册")
        sig = inspect.signature(matched[0].endpoint)
        self.assertTrue(
            any(isinstance(p.default, fastapi_params.Depends)
                and p.default.dependency is require_user
                for p in sig.parameters.values()),
            "下载端点缺少鉴权")


if __name__ == "__main__":
    unittest.main()
