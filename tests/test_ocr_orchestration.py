# -*- coding: utf-8 -*-
"""离线单测：入库管线编排层启发式规则（不连数据库/模型/OCR）。

覆盖范围：
1. `_ocr_vs_pdfplumber_similar` — "大差不差"判定（混合页跳过条带的依据）
2. `_ocr_degenerate` — 整页 OCR 七签名退化检测（含 doc104 正常表格不误判回归）
3. `_ocr_strip_attempt` / `_ocr_strip_with_retry` — 条带预算只扣真实网络调用、
   prompt 重试阶梯、细分递归到深度 2 丢弃
4. `_chunk_is_garbage` — 块级垃圾七签名（含 MCC 裸码块不误杀回归）

背景：2026-10-18 实测，`_page_ocr_with_upgrade` 的"大差不差"分支一度 return None
导致 OCR 独有内容整页丢失、adv100 回归 8 题；此类编排层分支此前无任何测试，
只能靠"重灌 10 分钟 + 100 题评测 2 分钟"兜底。本文件把其中可离线验证的纯函数
部分钉死，改规则 5 秒内见结论。页面级编排（`_page_ocr_with_upgrade`）依赖
pdfplumber page 对象与真实 OCR，不在离线范围。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.document as document_mod
from app.document import (
    _OCR_STRIP_PROMPT,
    _OCR_STRIP_RETRY_PROMPT,
    _ocr_degenerate,
    _ocr_strip_attempt,
    _ocr_strip_with_retry,
    _ocr_vs_pdfplumber_similar,
)
from app.rag import _chunk_is_garbage


class TestOcrVsPdfplumberSimilar(unittest.TestCase):
    def test_empty_pdf_returns_false(self):
        """pdfplumber 为空（纯扫描页）无法比较 → 不判大差不差。"""
        self.assertFalse(_ocr_vs_pdfplumber_similar("识别出一段文字", ""))

    def test_empty_ocr_returns_true(self):
        """OCR 无汉字 → 视为没有新信息。"""
        self.assertTrue(_ocr_vs_pdfplumber_similar("12345", "正文内容若干"))

    def test_high_overlap_true(self):
        """pdf 已覆盖 OCR 全部汉字 → 大差不差。"""
        self.assertTrue(
            _ocr_vs_pdfplumber_similar(
                "非银行支付机构监督管理条例施行", "非银行支付机构监督管理条例"
            )
        )

    def test_novel_content_false(self):
        """OCR 含大量 pdf 没有的汉字 → 有实质新信息，不判大差不差。"""
        self.assertFalse(_ocr_vs_pdfplumber_similar("上海安信汇支付有限公司", "北京市朝阳区"))


class TestOcrDegenerate(unittest.TestCase):
    def test_empty_or_normal_false(self):
        self.assertFalse(_ocr_degenerate(""))
        self.assertFalse(_ocr_degenerate("这是正常的一句话。"))
        self.assertFalse(_ocr_degenerate("2024 年支付体系运行总体情况\n各项指标稳步增长"))

    def test_layout_token_true(self):
        self.assertTrue(_ocr_degenerate("内容 <|LOC_151|> 继续 <|LOC_152|> 结尾"))

    def test_single_line_burst_true(self):
        self.assertTrue(_ocr_degenerate("A" * 600))

    def test_repeated_line_true(self):
        text = "\n".join(["相同的行"] * 5 + [f"不同行{i}" for i in range(3)])
        self.assertTrue(_ocr_degenerate(text))

    def test_word_dominates_lines_true(self):
        text = "\n".join(f"{i} 批发业务 {i}" for i in range(15))
        self.assertTrue(_ocr_degenerate(text))

    def test_low_dedup_ratio_true(self):
        text = "\n".join(("x1\nx2\nx3\n") * 5).strip()
        self.assertTrue(_ocr_degenerate(text))

    def test_latex_concentration_true(self):
        lines = ["行内数学幻觉 \\(\\frac{1}{2}\\)"] * 4 + [f"正常行{i}" for i in range(6)]
        self.assertTrue(_ocr_degenerate("\n".join(lines)))

    def test_long_line_internal_loop_true(self):
        self.assertTrue(_ocr_degenerate("影响和" * 100))

    def test_dense_mcc_table_not_degenerate(self):
        """回归：doc104 条带产物（不同编码的行）绝不能误判退化。"""
        text = "\n".join(f"{code} 批发业务" for code in (4458, 5039, 5045, 5074, 5111, 9312, 9400))
        self.assertFalse(_ocr_degenerate(text))


class TestStripBudget(unittest.TestCase):
    class FakeOcr:
        def __init__(self, ret: str):
            self.ret = ret
            self.calls = 0

        def ocr(self, image_path, prompt):
            self.calls += 1
            return self.ret

    def test_budget_exhausted_no_call(self):
        client = self.FakeOcr("内容")
        out = _ocr_strip_attempt(client, Path("fake.png"), "prompt", budget=[0])
        self.assertEqual(out, "")
        self.assertEqual(client.calls, 0)

    def test_slow_call_charges_budget(self):
        with mock.patch.object(document_mod, "_OCR_NETWORK_CALL_S", 0.0):
            client = self.FakeOcr("内容")
            budget = [3]
            out = _ocr_strip_attempt(client, Path("fake.png"), "prompt", budget)
        self.assertEqual(out, "内容")
        self.assertEqual(budget, [2])

    def test_fast_cache_hit_free(self):
        with mock.patch.object(document_mod, "_OCR_NETWORK_CALL_S", 1e9):
            client = self.FakeOcr("内容")
            budget = [3]
            out = _ocr_strip_attempt(client, Path("fake.png"), "prompt", budget)
        self.assertEqual(out, "内容")
        self.assertEqual(budget, [3])


class TestStripRetryLadder(unittest.TestCase):
    class FakeOcr:
        """按 prompt 内容决定返回什么；记录调用顺序。"""

        def __init__(self):
            self.prompts = []
            self.ret = ""

        def ocr(self, image_path, prompt):
            self.prompts.append(prompt)
            return self.ret

    def test_first_attempt_clean(self):
        client = self.FakeOcr()
        client.ret = "清晰文字"
        out = _ocr_strip_with_retry(Path("fake.png"), client)
        self.assertEqual(out, "清晰文字")
        self.assertEqual(client.prompts, [_OCR_STRIP_PROMPT])

    def test_retry_prompt_rescues(self):
        """首试退化 → 极简 prompt 重试成功 → 不再细分。"""
        client = self.FakeOcr()
        client.ret = "复读循环" * 100  # 退化输出
        calls = []

        def fake_ocr(image_path, prompt):
            calls.append(prompt)
            if prompt == _OCR_STRIP_RETRY_PROMPT:
                return "干净结果"
            return "复读循环" * 100

        client.ocr = fake_ocr
        out = _ocr_strip_with_retry(Path("fake.png"), client)
        self.assertEqual(out, "干净结果")
        self.assertEqual(calls, [_OCR_STRIP_PROMPT, _OCR_STRIP_RETRY_PROMPT])

    def test_all_degenerate_dropped(self):
        """全退化 → 细分到深度 2 → 丢弃返回空串（真实 PNG 走裁剪路径）。"""
        client = self.FakeOcr()
        client.ret = "复读循环" * 100
        with tempfile.TemporaryDirectory() as td:
            from PIL import Image
            png = Path(td) / "strip.png"
            Image.new("RGB", (100, 200), "white").save(png)
            out = _ocr_strip_with_retry(png, client, budget=[99])
        self.assertEqual(out, "")
        self.assertGreater(len(client.prompts), 2)


class TestChunkIsGarbage(unittest.TestCase):
    def test_clean_text_ok(self):
        self.assertFalse(_chunk_is_garbage("非银行支付机构设立后无正当理由连续停业，人民银行可注销其许可。"))

    def test_layout_token_garbage(self):
        self.assertTrue(_chunk_is_garbage("内容 <|LOC_292|> 继续"))

    def test_foreign_hallucination_garbage(self):
        self.assertTrue(_chunk_is_garbage("текст Свой текст 한글"))

    def test_year_loop_garbage(self):
        self.assertTrue(_chunk_is_garbage("\n".join("2024 年" for _ in range(8))))

    def test_duplicate_lines_garbage(self):
        text = "\n".join(["同一行"] * 6 + ["结尾行"])
        self.assertTrue(_chunk_is_garbage(text))

    def test_symbol_soup_garbage(self):
        self.assertTrue(_chunk_is_garbage("。" * 70))

    def test_repeat_run_garbage(self):
        self.assertTrue(_chunk_is_garbage("你好" * 30))

    def test_periodic_cycle_garbage(self):
        self.assertTrue(_chunk_is_garbage("abc" * 20))

    def test_bare_mcc_codes_ok(self):
        """回归：doc104 的裸码列（纯数字行）是合法内容，不得误杀。"""
        self.assertFalse(_chunk_is_garbage("9312\n4458\n5074\n5111\n9400"))


if __name__ == "__main__":
    unittest.main()
