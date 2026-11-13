# -*- coding: utf-8 -*-
"""OCR 形近错字清洗规则单测：锚定防误杀 + 幂等 + 脏文本清洗。

与 tests/test_ocr_orchestration.py 同风格（unittest，离线纯函数，不连库/模型）。
运行：venv\\Scripts\\python.exe -m unittest tests.test_typo_clean -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.typo_clean import clean_ocr_typos


class TestTypoFixesBasic(unittest.TestCase):
    """字符串映射：典型脏文本清洗正确。"""

    CASES = [
        ("非金融机支付服务管理办法", "非金融机构支付服务管理办法"),
        ("各付佥管理存在重大问题", "备付金管理存在重大问题"),
        ("客户付金管理存在漏洞", "客户备付金管理存在漏洞"),
        ("中国支付算协会", "中国支付清算协会"),
        ("及其分文机构监管使用", "及其分支机构监管使用"),
        ("积极配行业自律管理", "积极配合行业自律管理"),
        ("消极配今行业自律管理", "消极配合行业自律管理"),
        ("涉及透法犯罪案件", "涉及违法犯罪案件"),
        ("较大迷法违规情况", "较大违法违规情况"),
        ("系计亏损超过实缴货币资本", "累计亏损超过实缴货币资本"),
        ("举报10次（全）以上", "举报10次（含）以上"),
        ("约谈其童事长或总经理", "约谈其董事长或总经理"),
        ("协会接照自律管理指标", "协会按照自律管理指标"),
        ("适时调鏊支付机构分类评级", "适时调整支付机构分类评级"),
        ("受到刑事处罚或老较重", "受到刑事处罚或者较重"),
        ("下列政策文持或实施监管", "下列政策支持或实施监管"),
        ("覆盖范图、拓宽客户", "覆盖范围、拓宽客户"),
        ("不对外技露", "不对外披露"),
        ("经公词法定代表人", "经公司法定代表人"),
        ("迟报、漏报、报、虚报", "迟报、漏报、瞒报、虚报"),
        ("确定支付机构的类别、次，于每年", "确定支付机构的类别、级次，于每年"),
        ("按照（（非银行支付机构", "按照（《非银行支付机构"),
        ("并子15个工作日内", "并于15个工作日内"),
        ("出现异带，且足以导致", "出现异常，且足以导致"),
        ("至少涵盖C类C机构。", "至少涵盖C类C级机构。"),
        ("分为A（AAAA、A）、B（BBB、B、B）", "分为A（AAA、AA、A）、B（BBB、BB、B）"),
        ("通过伪、变造、隐匿数据", "通过伪造、变造、隐匿数据"),
        ("银行卡收业务等支付业务", "银行卡收单业务等支付业务"),
        ("条付金管理规范", "备付金管理规范"),
        ("各付金银行集中存放比例", "备付金银行集中存放比例"),
        ("风险隐惠，造成恶劣", "风险隐患，造成恶劣"),
        ("适规事件或多次暴露", "合规事件或多次暴露"),
        ("会规状况好", "合规状况好"),
        ("适法犯活动办理支付业务", "违法犯活动办理支付业务"),
        ("一次3.每年视情", "一次。\n3.每年视情"),
        ("监管措施外对限期未整改", "监管措施外，对限期未整改"),
        ("公开发行股票挂牌公开转让等", "公开发行股票、挂牌公开转让等"),
        ("年利率（％）÷360", "年利率（%）÷360"),
    ]

    def test_fixes(self):
        for dirty, expected in self.CASES:
            with self.subTest(dirty=dirty):
                self.assertEqual(clean_ocr_typos(dirty), expected)


class TestPatternAnchors(unittest.TestCase):
    """正则锚定：高危短串不误杀正常文本，且对脏文本正确命中。"""

    SAFE = [
        "车道成本核算",            # 「道成」不锚定「损害/不良」→ 不变
        "通道成本分析",
        "西班牙帝国与比索时代",     # 「与比」不锚定「超过」→ 不变
        "经过再三处理后",           # 「三处理」前无逗号 → 不变
        "每手交易手续费",           # 「每手」不锚定「进行」→ 不变
        "重大事项降低评级",         # 「重大事项降」不锚定顿号 → 不变
        "造成损害赔偿责任",         # 裸「成损害」已有「造」→ 不二次替换
        "MASTER\\JCB\\DINER\\AMEX 等外卡品牌",  # 路径/品牌分隔反斜杠 → 不动
        "正则 \\[a-z\\] 匹配小写字母",   # 转义方括号内非数字 → 不动
    ]

    POSITIVE = [
        ("对客户合法权益道成损害", "对客户合法权益造成损害"),
        ("道成不良社会影响", "造成不良社会影响"),
        ("虚假商户与比超过5%等", "虚假商户占比超过5%等"),
        ("负面舆情，三处理不当", "负面舆情，且处理不当"),
        ("分类评级每手进行一次", "分类评级每年进行一次"),
        ("存在重大事项降、重大信息虚假", "存在重大事项隐瞒、重大信息虚假"),
        ("合法权益成损害", "合法权益造成损害"),  # 裸「成损害」补「造」
        ("存在下列任一形，直接评定", "存在下列任一情形，直接评定"),  # 后向断言幂等
        ("参考。四）核定风险准备金", "参考。（四）核定风险准备金"),  # 编号补左括号
        ("“支付机构反洗钱办法”\\[2012\\] 适用", "“支付机构反洗钱办法”〔2012〕 适用"),  # markdown 转义残留
    ]

    def test_no_false_positive(self):
        for text in self.SAFE:
            with self.subTest(text=text):
                self.assertEqual(clean_ocr_typos(text), text, f"误杀: {text!r}")

    def test_positive(self):
        for dirty, expected in self.POSITIVE:
            with self.subTest(dirty=dirty):
                self.assertEqual(clean_ocr_typos(dirty), expected)


class TestSectionBreak(unittest.TestCase):
    """章节标题粘连：通用正则补换行（法规文档普适）。"""

    CASES = [
        ("造成恶劣社会影响。第十二条中国人民银行", "造成恶劣社会影响。\n第十二条中国人民银行"),
        ("且性质较为恶劣。第十一条支付机构", "且性质较为恶劣。\n第十一条支付机构"),
        ("《支付业务许可证》第五章", "《支付业务许可证》\n第五章"),
        ("许可证》（五）对D类机构", "许可证》\n（五）对D类机构"),
        ("影响。\n第十二条", "影响。\n第十二条"),  # 已有换行不重复加（幂等）
    ]

    def test_section(self):
        for dirty, expected in self.CASES:
            with self.subTest(dirty=dirty):
                self.assertEqual(clean_ocr_typos(dirty), expected)


class TestIdempotentAndClean(unittest.TestCase):
    """幂等性 + 干净文本无副作用 + 空值。"""

    def test_idempotent(self):
        dirty = (
            "支付机构分为A（AAAA、A）、B（BBB、B、B），涉及透法犯罪、系计亏损超过50％，"
            "道成损害且三处理不当，虚假商户与比超过5％，每手进行一次，重大事项降、重大信息虚假，"
            "造成恶劣社会影响。第十二条中国人民银行及其分文机构，适时调鏊分类评级。"
        )
        once = clean_ocr_typos(dirty)
        twice = clean_ocr_typos(once)
        self.assertEqual(once, twice, "清洗不幂等")

    def test_clean_text_untouched(self):
        samples = [
            "商户编号设置为898加地区代码4位加MCC码4位加顺序号4位。",
            "拉卡拉支付股份有限公司第三季度报告，营业收入1407546234.93元，同比减少3.28%。",
            "同一股东不得直接或者间接持有两个及以上同一业务类型的非银行支付机构10%以上股权或者表决权。",
            "应用大类银联卡直联业务、应用小类银联卡直联、收单机构银联商务、交易受理渠道机构中国银联。",
            "https://erp.chinaums.com/omps/a/login 3.5版本 1.8节 第3条",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(clean_ocr_typos(text), text, f"干净文本被改: {text!r}")

    def test_empty_and_none(self):
        self.assertEqual(clean_ocr_typos(""), "")
        self.assertIsNone(clean_ocr_typos(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
