# -*- coding: utf-8 -*-
"""离线单测：EmbeddingClient 磁盘缓存（不连数据库/真实模型 API）。

覆盖：
1. 未命中 → 批量请求 → 向量落缓存；二次调用直接命中、不再发请求
2. 缓存命中不触发任何网络调用
3. 脏缓存文件（损坏 JSON）按未命中处理并自动修复
4. 空文本返回零向量且不写缓存
5. 缓存键含模型名，切换模型不串缓存
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.clients import EmbeddingClient
from config import settings

DIM = settings.embedding_dim


class TestEmbeddingCache(unittest.TestCase):
    def _make_client(self, tmp: Path) -> EmbeddingClient:
        client = EmbeddingClient()
        client._cache_dir = tmp  # 隔离到临时目录，不污染 data/.emb_cache
        return client

    def test_miss_then_hit(self):
        with tempfile.TemporaryDirectory() as td:
            client = self._make_client(Path(td))
            calls: list = []

            def fake_batch(texts):
                calls.extend(texts)
                return [[0.1 * (i + 1)] * DIM for i in range(len(texts))]

            with mock.patch.object(client, "_embed_batch", side_effect=fake_batch):
                out1 = client.embed(["同一条文本", "另一条文本"])
            self.assertEqual(len(calls), 2)  # 两条都发请求
            self.assertEqual(out1[0][0], 0.1)
            self.assertEqual(len(list(client._cache_dir.glob("*.json"))), 2)

            # 二次调用：全部命中缓存，含同文本重复位置
            with mock.patch.object(
                client, "_embed_batch",
                side_effect=AssertionError("缓存命中不应再发请求"),
            ):
                out2 = client.embed(["同一条文本", "另一条文本", "同一条文本"])
            self.assertEqual(out2[0], out1[0])
            self.assertEqual(out2[1], out1[1])
            self.assertEqual(out2[2], out1[0])

    def test_cache_hit_no_network(self):
        with tempfile.TemporaryDirectory() as td:
            client = self._make_client(Path(td))
            vec = [0.5] * DIM
            client._emb_cache_put("已缓存文本", vec)
            with mock.patch.object(client, "_embed_batch") as m:
                out = client.embed(["已缓存文本"])
            m.assert_not_called()
            self.assertEqual(out[0], vec)

    def test_corrupt_cache_treated_as_miss(self):
        with tempfile.TemporaryDirectory() as td:
            client = self._make_client(Path(td))
            client._emb_cache_put("损坏缓存", [0.7] * DIM)
            f = next(client._cache_dir.glob("*.json"))
            f.write_text("{broken json", encoding="utf-8")

            with mock.patch.object(
                client, "_embed_batch", return_value=[[0.9] * DIM]
            ) as m:
                out = client.embed(["损坏缓存"])
            m.assert_called_once_with(["损坏缓存"])
            self.assertEqual(out[0][0], 0.9)
            # 修复后重新写入为合法缓存
            self.assertEqual(client._emb_cache_get("损坏缓存"), [0.9] * DIM)

    def test_empty_text_zero_vec_not_cached(self):
        with tempfile.TemporaryDirectory() as td:
            client = self._make_client(Path(td))
            with mock.patch.object(client, "_embed_batch") as m:
                out = client.embed(["", "   "])
            m.assert_not_called()
            self.assertEqual(out[0], [0.0] * DIM)
            self.assertEqual(out[1], [0.0] * DIM)
            self.assertEqual(list(client._cache_dir.glob("*.json")), [])

    def test_cache_key_includes_model(self):
        with tempfile.TemporaryDirectory() as td:
            client = self._make_client(Path(td))
            client.model = "model-A"
            client._emb_cache_put("文本", [0.1] * DIM)
            self.assertIsNotNone(client._emb_cache_get("文本"))
            client.model = "model-B"
            self.assertIsNone(client._emb_cache_get("文本"))  # 模型不同不串缓存


if __name__ == "__main__":
    unittest.main()
