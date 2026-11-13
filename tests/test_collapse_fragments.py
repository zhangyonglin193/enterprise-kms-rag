"""离线单测：句子级残片塌缩（Retriever._collapse_fragments 及辅助纯函数）。

覆盖三规则与边界：截断残片删除 / 粘连完整句删除 / 截尾截断 / 表格行保留 /
排比句保留 / 尾部关键数字保留 / 完全重复句去重 / 无变化时原样返回。
不连接数据库/模型/检索，仅测纯函数逻辑。

注意：必须先 apply_environment 再 import app.rag——config.Settings 的类属性默认值
在模块首次导入时求值，导入顺序错误会把 KMS_*_EMPLOYEES 冻结为空，污染其他离线测试。
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
})

from app.rag import Retriever


class TestNormAndLcs(unittest.TestCase):
    def test_norm_keeps_cjk_alnum_and_positions(self):
        norm, pos = Retriever._norm_with_pos("3.5万元 A/B")
        self.assertEqual(norm, "35万元ab")
        idx = norm.index("万")
        self.assertEqual("3.5万元 A/B"[pos[idx]], "万")

    def test_lcs_len(self):
        self.assertEqual(Retriever._lcs_len("abcde", "xbcdey"), 4)
        self.assertEqual(Retriever._lcs_len("", "abc"), 0)
        self.assertEqual(Retriever._lcs_len("abc", "xyz"), 0)


class TestCollapseFragments(unittest.TestCase):
    def test_fragment_before_complete_sentence_dropped(self):
        """规则2：截断残片（无句末标点）与后文完整句高重合 → 删残片、保留完整句。"""
        text = (
            "车耐用品属性更强、居民购买会更加审慎，并不会因为有补贴政策就轻易多买汽车，当期刺\n"
            "车耐用品属性更强、居民购买会更加审慎，并不会因为有补贴政策就轻易多买汽车，"
            "当期刺激的汽车消费基本上是从未来几年腾挪过来的。"
        )
        result = Retriever._collapse_fragments(text)
        self.assertNotIn("当期刺\n", result)
        self.assertIn("当期刺激的汽车消费基本上是从未来几年腾挪过来的。", result)
        self.assertEqual(result, text.split("\n")[1])

    def test_glued_fragment_dropped(self):
        """规则2b：残片的长前缀被后文完整句覆盖、且尾部在前文出现过 → 删残片。

        样本必须是**残片**（句末无标点）。原因见下方 test_complete_sentence_is_kept：
        实现有意只删残片、绝不删完整句。
        """
        text = (
            "弹性相对小一些。\n"
            "年高，除了当时可能受疫情影响以外，供给侧创新带来了电动车渗透率的快速爬升，"
            "也是政性相对小一些\n"
            "年高，除了当时可能受疫情影响以外，供给侧创新带来了电动车渗透率的快速爬升，"
            "也是政策效果更好的一个重要原因。"
        )
        result = Retriever._collapse_fragments(text)
        self.assertNotIn("也是政性相对小一些", result)
        self.assertIn("弹性相对小一些。", result)
        self.assertIn("也是政策效果更好的一个重要原因。", result)

    def test_complete_sentence_is_kept(self):
        """回归锁：规则2b **只删残片**，完整句（有句末标点）必须保留。

        这是有意的保护，不是缺陷：表格行/列表项常「同模板 + 异取值」，
        前缀高度重合且尾部重复是常态，若删完整句会丢掉唯一的数据行。
        若将来有人放宽此条件，本用例会失败——请先确认不会误删表格数据。
        """
        text = (
            "弹性相对小一些。\n"
            "年高，除了当时可能受疫情影响以外，供给侧创新带来了电动车渗透率的快速爬升，"
            "也是政性相对小一些。\n"
            "年高，除了当时可能受疫情影响以外，供给侧创新带来了电动车渗透率的快速爬升，"
            "也是政策效果更好的一个重要原因。"
        )
        result = Retriever._collapse_fragments(text)
        self.assertIn("也是政性相对小一些。", result)
        self.assertIn("弹性相对小一些。", result)
        self.assertIn("也是政策效果更好的一个重要原因。", result)

    def test_normal_sentences_unchanged(self):
        """正常叙述的两句无重复 → 原样返回。"""
        text = "财政补贴当期乘数较高，对相关消费拉动力强。后续由于透支效应，累积乘数会逐渐降到1以下。"
        self.assertEqual(Retriever._collapse_fragments(text), text)

    def test_parallel_sentences_kept(self):
        """排比句（前缀相同度低）不误删。"""
        text = (
            "今年汽车政策乘数比2022年高，除了当时可能受疫情影响以外，也是政策效果更好的一个重要原因。"
            "今年家电政策乘数比2022年低，除了当时可能受疫情影响以外，也是政策效果一般的重要原因。"
        )
        self.assertEqual(Retriever._collapse_fragments(text), text)

    def test_tail_truncated(self):
        """规则3：残片尾部与后文句头部重叠 → 截掉尾部，保留残片头部独特内容。
        （头部截后 <6 个有效字符时整句删，属预期行为）"""
        text = (
            "从上面的数据来看，这能够调动更多的居民在当期购买汽车，提升当期\n"
            "这能够调动更多的居民在当期购买汽车，提升当期乘数。但单价贵是双刃剑。"
        )
        result = Retriever._collapse_fragments(text)
        self.assertIn("从上面的数据来看，", result)
        self.assertNotIn("提升当期\n", result)
        self.assertIn("提升当期乘数。但单价贵是双刃剑。", result)

    def test_tail_truncated_too_short_drops_sentence(self):
        """规则3：截尾后头部 <6 个有效字符 → 整句删（残片无独立信息量）。"""
        text = (
            "从数据看，这能够调动更多的居民在当期购买汽车，提升当期\n"
            "这能够调动更多的居民在当期购买汽车，提升当期乘数。但单价贵是双刃剑。"
        )
        result = Retriever._collapse_fragments(text)
        self.assertNotIn("从数据看", result)
        self.assertIn("提升当期乘数。但单价贵是双刃剑。", result)

    def test_table_rows_kept(self):
        """表格标题行（前缀相似但编号不同）不误删。"""
        text = "图表8：汽车和家电补贴政策乘数对比\n图表9：汽车和家电补贴政策长期乘数对比"
        self.assertEqual(Retriever._collapse_fragments(text), text)

    def test_identical_sentence_dropped(self):
        """规则1：完全重复句删前一份、留后一份。"""
        result = Retriever._collapse_fragments("同一个句子重复出现。同一个句子重复出现。")
        self.assertEqual(result, "同一个句子重复出现。")

    def test_key_number_tail_kept(self):
        """尾部含关键数字的相似句（尾部未在前文出现）不误删。"""
        text = (
            "2009年汽车补贴政策财政规模约281亿元，拉动的零售额为1952亿元，财政乘数达到7.0。"
            "2009年汽车补贴政策财政规模约281亿元，拉动的零售额为1952亿元。"
        )
        result = Retriever._collapse_fragments(text)
        self.assertIn("财政乘数达到7.0", result)

    def test_single_sentence_returns_original(self):
        text = "只有一句话的内容。"
        self.assertEqual(Retriever._collapse_fragments(text), text)


if __name__ == "__main__":
    unittest.main()
