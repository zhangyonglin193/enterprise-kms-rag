"""离线单测：混合页 OCR 合并去重（app.document._merge_text_and_ocr 及辅助纯函数）。

覆盖逐行三分类的四条边界：重复剔除 / 独有保留 / 乱码拦截 / OCR 行自去重，以及全空退化。
不连接数据库/模型/OCR，仅测纯函数逻辑。
"""
from __future__ import annotations

import unittest

from app.document import (
    _char_bigrams,
    _merge_text_and_ocr,
    _norm_compact,
    _ocr_line_quality_ok,
)


class TestMergeTextAndOcr(unittest.TestCase):
    def test_empty_ocr_returns_pdf(self):
        """OCR 为空 → 原样返回 pdf 文本（不因新逻辑丢内容）。"""
        self.assertEqual(_merge_text_and_ocr("正文内容若干字", ""), "正文内容若干字")

    def test_empty_pdf_returns_ocr(self):
        """pdf 文本为空 → 原样返回 OCR（纯扫描页无参照可比）。"""
        self.assertEqual(_merge_text_and_ocr("   ", "整页 OCR 独有内容"), "整页 OCR 独有内容")

    def test_duplicate_line_dropped_despite_char_diff(self):
        """OCR 与 pdf 内容相同但字面有别（0↔O、空格、标点）→ 仍判重复丢弃，结果==pdf。"""
        pdf = "请在设置界面中配置打印机的参数值0=58毫米"
        ocr = "请在设置界面 中配置打印机的参数值O=58毫米"  # 多空格 + 0→O
        self.assertEqual(_merge_text_and_ocr(pdf, ocr), pdf)

    def test_novel_line_appended(self):
        """OCR 独有内容（图片区）→ 保留并追加到 pdf 文本之后。"""
        pdf = "本文介绍产品背景与适用范围。"
        ocr = "【确认】按钮位于弹窗右下角区域"
        merged = _merge_text_and_ocr(pdf, ocr)
        self.assertTrue(merged.startswith(pdf.rstrip()))
        self.assertIn("【确认】按钮位于弹窗右下角区域", merged)

    def test_garbled_line_filtered(self):
        """乱码/符号汤即使“独有”也被质量门拦截 → 结果==pdf。"""
        pdf = "正常文本内容若干字"
        ocr = "|||---<<<>>>===~~~"
        self.assertEqual(_merge_text_and_ocr(pdf, ocr), pdf)

    def test_mixed_lines(self):
        """重复行丢、独有行留、乱码行拦：三类行同现时各归各位。"""
        pdf = "第一步登录系统第二步进入商户管理界面"
        ocr = "第一步登录系统 第二步进入商户管理\n【提交】按钮在右下角\n|||--->>>\t\t"
        merged = _merge_text_and_ocr(pdf, ocr)
        self.assertNotIn("第二步进入商户管理\n", merged)  # 重复行已剔除
        self.assertIn("【提交】按钮在右下角", merged)         # 独有行保留
        self.assertNotIn("|||", merged)                       # 乱码行拦截

    def test_ocr_internal_dedup(self):
        """OCR 自身重复的两行 → 只保留一份。"""
        pdf = "无关的正文内容"
        ocr = "这是独有的一行说明文字\n这是独有的一行说明文字"
        merged = _merge_text_and_ocr(pdf, ocr)
        self.assertEqual(merged.count("这是独有的一行说明文字"), 1)


class TestHelpers(unittest.TestCase):
    def test_norm_compact(self):
        """归一化剔除空格/标点/符号并小写化，仅留 CJK/字母/数字。"""
        self.assertEqual(_norm_compact("参数 值A-b！C"), "参数值abc")

    def test_char_bigrams(self):
        self.assertEqual(_char_bigrams("abcd"), {"ab", "bc", "cd"})
        self.assertEqual(_char_bigrams("a"), {"a"})
        self.assertEqual(_char_bigrams(""), set())

    def test_quality_gate_accepts_meaningful(self):
        self.assertTrue(_ocr_line_quality_ok("打印参数值0=58毫米"))

    def test_quality_gate_rejects_soup_and_short(self):
        self.assertFalse(_ocr_line_quality_ok("|||---<<<>>>"))
        self.assertFalse(_ocr_line_quality_ok("短"))


if __name__ == "__main__":
    unittest.main()
