"""文档加载与分块。

支持：PDF / DOCX / DOC / MD / TXT / XLSX / 图片(走 OCR)。
分块器为中文优化的递归字符切分。
注意：加载器只读取原始文件，绝不写入或覆盖；临时文件统一放系统 temp 目录。
"""
from __future__ import annotations

import io
import re
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.logger import get_logger
from config import settings

logger = get_logger("document")


# 结构化 OCR prompt：保留表格、参数、UI 元素细节，避免通用 prompt 丢失结构
_OCR_STRUCTURED_PROMPT = (
    "请识别图片中的全部文字，严格遵守以下规则：\n"
    "1. 保持原有段落结构和层级关系\n"
    "2. 表格内容用制表符分隔各列，每行独立一行\n"
    "3. 完整保留所有数字、参数值、配置项（如 '参数值 0=58mm' 不可省略）\n"
    "4. 按钮、菜单项、对话框文字用【】标记\n"
    "5. 不要总结或省略任何内容，逐字识别\n"
)

# 整页扫描页 OCR prompt：扫描页主体可能是表格（如 MCC 码表）或正文，
# 明确指示"若是表格保行列结构"，提升代码行的识别率（doc104 类）。
_OCR_SCAN_PROMPT = (
    "请识别图片中的全部文字，严格遵守以下规则：\n"
    "1. 若图片主体是表格，用制表符分隔各列、每行独立一行，完整保留每行的代码与名称\n"
    "2. 若是普通文档页，保持原有段落结构和层级关系\n"
    "3. 完整保留所有数字、代码、参数值，不可省略或改写\n"
    "4. 不要总结或省略任何内容，逐字识别\n"
)

# 条带分解 OCR prompt：只给正向指令。实测否定祈使句（"不要重复/不要省略"）会被 VLM
# 回显成复读循环（"不要在表格中添加…"×31），故禁用否定句式。
_OCR_STRIP_PROMPT = (
    "逐字转录图片中的全部文字。每行文字单独一行，"
    "表格行内的多列内容用竖线 | 分隔。完整保留四位数字代码及其对应的名称和描述。"
)

# 条带重试 prompt：更短、约束更少，降低回显风险。
_OCR_STRIP_RETRY_PROMPT = "逐字转录图片中的全部文字，保持阅读顺序。"


# 归一化时保留的字符集：CJK + 字母 + 数字，其余（空白/标点/全半角符号）全部剔除，
# 使 pdfplumber 文本与 OCR 文本可在“去噪后”做字面比对（OCR 与文本层几乎不可能逐字相同）。
_NORM_KEEP_RE = re.compile(r'[^\u4e00-\u9fff0-9a-zA-Z]+')


def _norm_compact(s: str) -> str:
    """归一化：仅保留 CJK/字母/数字并小写化，去掉空格、标点、版面符号。"""
    return _NORM_KEEP_RE.sub('', s or '').lower()


def _char_bigrams(s: str) -> set:
    """字符 bigram 集合，用于模糊包含度判定（比精确子串对 OCR 字面差异更鲁棒）。"""
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _ocr_line_quality_ok(line: str) -> bool:
    """OCR 行质量门（与去重正交）：拦截乱码/符号汤，避免其作为“独有内容”混入库。

    判定分两类（长度门按字符密度自适应，避免误杀界面/表格短标签）：
    - CJK 主导（≥2 个汉字）：汉字信息密度高，“商户编号/私有化部署/在线API”这类界面标签
      虽短却有义，只要有效字符占比达标即保留，不再套用统一长度门；
    - 非 CJK 主导（拉丁/数字/符号）：短行更易是碎片噪声，保留 len≥6 的长度门。
    两类均要求有效字符（CJK/字母/数字）占非空白字符比例 ≥0.5（拦符号汤/乱码）。
    """
    s = line.strip()
    nonspace = re.sub(r'\s', '', s)
    if not nonspace:
        return False
    cjk = len(re.findall(r'[\u4e00-\u9fff]', nonspace))
    meaningful = len(re.findall(r'[\u4e00-\u9fff0-9a-zA-Z]', nonspace))
    ratio = meaningful / len(nonspace)
    # CJK 密度高：≥2 个汉字即为有意义短标签，不因短被误杀
    if cjk >= 2:
        return ratio >= 0.5
    # 非 CJK 主导：短行更可能是碎片噪声，保留原长度门
    if len(nonspace) < 6:
        return False
    return ratio >= 0.5


def _extract_page_text_colwise(page, min_gap: float = 24.0) -> str:
    """多栏页面按栏提取（x 投影找栏缝）；单栏页面原样退回 extract_text()。

    pdfplumber 默认横向扫描会把多栏版式逐行交错（实测 doc84 三栏互相穿插：
    「商户编号：898+地区代码（4 | 录入收单银行编制 | 898+地区代码（4」），
    问答检索到的是交错后的错误栏内容。栏缝用词块覆盖直方图找全页贯通的垂直空档
    （词中心直方图会被整行长词块制造假缝，见 doc084 p4），按空档切栏带、
    栏内按 (top, x0) 组装行并合并行尾回绕残行，恢复各栏独立阅读顺序。
    无栏缝（单栏/通栏表格）时与 extract_text 行为一致，零回归风险。
    """
    words = page.extract_words()
    if len(words) < 12:
        return page.extract_text() or ""
    # 词块覆盖直方图：真栏缝处没有任何词块横跨（覆盖=0）；
    # 词中心直方图会被长行词块（如整行一个词块 x 657-1207）制造 30pt+ 假缝。
    cov: Dict[int, int] = {}
    for w in words:
        x0b = int(float(w["x0"]) // 5) * 5
        x1b = int(float(w["x1"]) // 5) * 5
        for b in range(x0b, x1b + 5, 5):
            cov[b] = cov.get(b, 0) + 1
    xmin, xmax = min(cov), max(cov)
    gaps: List[Tuple[int, int]] = []
    start = None
    for b in range(xmin, xmax + 5, 5):
        if cov.get(b, 0) == 0 and start is None:
            start = b
        elif cov.get(b, 0) > 0 and start is not None:
            if b - start >= min_gap:
                gaps.append((start, b))
            start = None
    if start is not None and xmax - start >= min_gap:
        gaps.append((start, xmax))
    # 表格列边界：coverage 直方图只能找全页贯通的缝；多列表格的列缝会被表格
    # 上方的通栏标题行填掉（doc084 p1 三列表格实测）。find_tables 识别的大表格
    # （≥3 列且 ≥5 行，排除导航条等 1-2 行误识别表）列边界一并作为切分线，
    # 恢复表格各列独立阅读流；单栏文档无大表格 → 零影响。
    col_edges: List[int] = []
    try:
        for tb in page.find_tables():
            if len(tb.columns) >= 3 and len(tb.rows) >= 5:
                for c in tb.columns:
                    col_edges.append(int(round(c.bbox[0])))
                    col_edges.append(int(round(c.bbox[2])))
    except Exception:
        col_edges = []
    if not gaps and not col_edges:
        return page.extract_text() or ""
    edges = [xmin]
    for g0, g1 in gaps:
        edges.append(g0)
        edges.append(g1)
    edges.extend(col_edges)
    edges.append(xmax + 5)
    edges = sorted(set(edges))
    bands = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    if len(bands) <= 1:
        return page.extract_text() or ""
    col_texts: List[str] = []
    for x0b, x1b in bands:
        ws = [w for w in words if x0b <= (float(w["x0"]) + float(w["x1"])) / 2 < x1b]
        if not ws:
            continue
        ws.sort(key=lambda w: (float(w["top"]), float(w["x0"])))
        hmed = sorted(float(w["bottom"]) - float(w["top"]) for w in ws)[len(ws) // 2] or 4.0
        lines: List[List] = []
        cur = [ws[0]]
        for w in ws[1:]:
            if float(w["top"]) - float(cur[-1]["top"]) > 0.7 * hmed:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
        # 回绕残行合并：行尾 1-3 字溢出被排到下一行行首（doc084 p4「……全数字编」
        # 行尾的「制；」），拼回上一行行尾恢复被切断的短语（如「全数字编制」）。
        # 条件从严：残行极短、行首不落后于上一行、上一行行尾顶到栏右边界、
        # 垂直间隙为行距级（非段落间距），避免误吞段落短行。
        band_x1 = max(float(w["x1"]) for w in ws)
        merged: List[List] = []
        for ln in lines:
            if not merged:
                merged.append(ln)
                continue
            prev = merged[-1]
            cur_x0 = min(float(w["x0"]) for w in ln)
            prev_x0 = min(float(w["x0"]) for w in prev)
            prev_x1 = max(float(w["x1"]) for w in prev)
            cur_w = max(float(w["x1"]) for w in ln) - cur_x0
            vgap = float(ln[0]["top"]) - float(prev[-1]["top"])
            if (cur_w < 3.0 * hmed
                    and cur_x0 <= prev_x0 + 2.0
                    and prev_x1 >= band_x1 - 20.0
                    and 0.5 * hmed < vgap < 2.2 * hmed):
                merged[-1] = prev + ln
            else:
                merged.append(ln)
        lines = merged
        col_texts.append("\n".join(" ".join(w["text"] for w in ln) for ln in lines))
    return "\n\n".join(col_texts)


def _rows_to_markdown(rows: List[List]) -> str:
    """将二维单元格数据渲染为 Markdown 表格（通用：DOCX/XLSX/PDF 表格共用）。

    - 首行作表头，其后补 `| --- |` 分隔行，保留行列关系；
    - 单元格内换行/多空白压成单空格、竖线转义，避免破坏表格结构；
    - 跳过全空行；列数按最宽行对齐（不足补空单元格）。
    相较 TSV：Markdown 显式给出表头分隔，生成端 LLM 解析表格型问题更稳，
    且是 embedding 模型预训练中常见的结构（复用性优于私有分隔格式）。
    """
    clean_rows: List[List[str]] = []
    for row in rows or []:
        cells = [re.sub(r'\s+', ' ', str(c) if c is not None else '').strip().replace('|', '\\|')
                 for c in row]
        if any(cells):
            clean_rows.append(cells)
    if not clean_rows:
        return ""
    ncol = max(len(r) for r in clean_rows)
    header = clean_rows[0] + [''] * (ncol - len(clean_rows[0]))
    lines = ['| ' + ' | '.join(header) + ' |',
             '| ' + ' | '.join(['---'] * ncol) + ' |']
    for r in clean_rows[1:]:
        r = r + [''] * (ncol - len(r))
        lines.append('| ' + ' | '.join(r) + ' |')
    return '\n'.join(lines)


def _merge_text_and_ocr(pdf_text: str, ocr_text: str, dup_thresh: float = 0.7) -> str:
    """混合页面：合并 pdfplumber 文本与 OCR 文本（行粒度 + 模糊去重 + 质量门）。

    背景：旧实现按 OCR 前 30 字与 pdf 文本做“精确子串”判定，属全有或全无——
    匹配则整段 OCR 全丢（误删图片区独有内容），不匹配则整段全留（重复+乱码灌入库）；
    且 OCR 与文本层几乎不可能逐字相同，精确指纹实际几乎永不命中，行为偏向“全留”。

    新策略（逐行三分类）：
    1. 归一化后算该行字符 bigram 与 pdf 全文 bigram 的包含度；≥dup_thresh 判重复 → 丢（pdf 质量更高）；
    2. 未重复的行再过质量门 `_ocr_line_quality_ok`，乱码/符号汤 → 丢；
    3. OCR 行间按归一化指纹自去重；仅保留“独有且合格”的行追加到 pdf 文本之后。
    """
    ocr_text = (ocr_text or "").strip()
    if not ocr_text:
        return pdf_text
    if not pdf_text.strip():
        return ocr_text
    pdf_shingles = _char_bigrams(_norm_compact(pdf_text))
    kept: List[str] = []
    seen: set = set()
    for raw_line in ocr_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        ln = _norm_compact(line)
        if len(ln) < 4:
            continue
        shingles = _char_bigrams(ln)
        if not shingles:
            continue
        # 1. 模糊去重：与 pdf 文本重合度高的行视为已覆盖，丢弃
        if pdf_shingles and len(shingles & pdf_shingles) / len(shingles) >= dup_thresh:
            continue
        # 2. 质量门：乱码/符号汤即使“独有”也不保留
        if not _ocr_line_quality_ok(line):
            continue
        # 3. OCR 行间自去重
        if ln in seen:
            continue
        seen.add(ln)
        kept.append(line)
    if not kept:
        return pdf_text
    return pdf_text.rstrip() + "\n\n" + "\n".join(kept)


def _postprocess_ocr_text(text: str) -> str:
    """OCR 后处理：修复常见识别错误，合并断行。

    针对 PaddleOCR-VL 的常见错误模式：
    1. 中文行内断行过多（应合并为连续段落）
    2. 空格插入中文之间（应去除）
    3. 常见 OCR 误识别（如 0/O、1/l 混淆，但保留原始数字参数）
    """
    if not text or len(text) < 10:
        return text
    lines = text.split("\n")
    merged = []
    for line in lines:
        line = line.strip()
        if not line:
            if merged:
                merged.append("")  # 保留段落分隔
            continue
        # 去除中文之间的多余空格（但保留英文/数字之间的空格）
        line = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', line)
        merged.append(line)
    # 合并相邻中文短行（双栏/竖排 OCR 碎片，如 "最多可支持三" + "方分润合并划付，并"）：
    # 两行均不含制表符（保护表格行）、去空白后均 <20 字符、均不以句末标点结尾
    changed = True
    while changed:
        changed = False
        merged2 = []
        i = 0
        while i < len(merged):
            line = merged[i]
            s = re.sub(r"\s", "", line)
            nxt = merged[i + 1] if i + 1 < len(merged) else ""
            s2 = re.sub(r"\s", "", nxt)
            if (line and nxt and "\t" not in line and "\t" not in nxt
                    and 0 < len(s) < 20 and 0 < len(s2) < 20
                    and not s.endswith(("。", "；", "！", "？", "："))
                    and not s2.endswith(("。", "；", "！", "？", "："))):
                merged2.append(line + nxt)
                i += 2
                changed = True
            else:
                merged2.append(line)
                i += 1
        merged = merged2
    # 合并连续空行
    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(merged))
    return result.strip()


def _extract_title_from_filename(filename: str) -> str:
    """从文件名智能提取文档标题（去扩展名、时间戳后缀、工具后缀，保留序号前缀）。"""
    if not filename:
        return ""
    title = re.sub(r"\.[^.]+$", "", filename)   # 去扩展名
    title = re.sub(r"_\d{13}$", "", title)      # 去时间戳后缀（如 _1785897931988）
    # 去工具后缀（如 " - pdfview"）：要求 dash 两侧均有空白，
    # 避免误删序号前缀（如 "001-"）或标题中的连词（如 "076-EMD1"）
    title = re.sub(r"\s+-\s+\w+$", "", title)
    return title.strip()


def _clean_layout_tokens(text: str) -> str:
    """清洗 PDF 版面分析模型残留的布局 token。

    某些 PDF 解析工具（如 PP-Structure、LayoutLM）会在文本中插入
    布局坐标 token，格式如 <|LOC_88|>、<|TEXT_101|>。
    分块后还可能产生残片如 C_92|>（<|LOC_92|> 被截断）。

    清洗策略：
    1. 完整 token：<|LOC_88|> → 删除
    2. 残片（无开头）：C_92|>、LOC_88|> → 删除
    3. 残片（无结尾）：<|LOC_8 → 删除
    4. 裸分隔符：<| 和 |> → 删除
    5. 合并多余空白
    """
    if not text:
        return text
    # 1. 完整的布局 token：<|LOC_88|>, <|TEXT_101|>, <|TITLE_0|> 等
    text = re.sub(r'<\|[A-Z_]+\d+\|>', ' ', text)
    # 2. 残片：被分块截断的 token，如 C_92|> 或 LOC_88|>（缺少 <| 前缀）
    text = re.sub(r'\b[A-Z]{1,6}_\d+\|>', ' ', text)
    # 3. 残片：<|LOC_8（缺少 |> 后缀）
    text = re.sub(r'<\|[A-Z_]+\d+', ' ', text)
    # 4. 裸分隔符
    text = re.sub(r'<\|', ' ', text)
    text = re.sub(r'\|>', ' ', text)
    # 5. 合并多余空白
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _collapse_inline_repeat(line: str) -> str:
    """行内重复折叠：整行由同一片段重复>=3次构成时保留1份。

    例：'版本信息控制表 版本信息控制表 版本信息控制表' → '版本信息控制表'
    约束：片段（去空白后）长度>=4 且重复>=3 次，避免误伤正常叠词。
    """
    s = line.strip()
    if not s:
        return line
    compact = re.sub(r"\s+", "", s)
    n = len(compact)
    if n < 12:
        return line
    for m in range(3, n // 4 + 1):
        if n % m == 0:
            part = compact[: n // m]
            if compact == part * m:
                return part
    return line


# 行内局部周期折叠正则（与块级 _REPEAT_RUN 同规则，此处保留 1 份/删除而非整块丢弃）
_REPEAT_RUN_SINGLE = re.compile(r"(.)\1{11,}")
_REPEAT_RUN_PERIOD = re.compile(r"(.{2,8})\1{7,}")


def _collapse_inline_partial(line: str) -> str:
    """行内局部周期折叠：折叠长行中段的连续重复子串（整行周期折叠的补充）。

    1. 单字符连续 >=12 次（表格边框误读如 '0'x77）→ 整段删除
    2. 2~8 字周期重复 >=8 次（幻觉循环被行/块边界截断的形态，
       如 '、图表数据'x12、'88104610'x37.5）→ 保留 1 份
    最小匹配 16~24 字，正文中不存在此类长重复，零误伤风险。
    """
    s = _REPEAT_RUN_SINGLE.sub("", line)
    s = _REPEAT_RUN_PERIOD.sub(r"\1", s)
    return s


# 可选引号前缀：VLM 可能输出 "1. \"不要添加...\"" 带引号形态
_PROMPT_ECHO_HINT = re.compile(
    r"^[\"'「『]?(不要|请勿|严禁|确保|仅输出|只输出|逐字|完整保留|不要添加|不要总结|不要省略)"
)
# 编号分隔符覆盖点号/顿号/括号/冒号（半角全角），适配各类指令列表形态
_NUMBERED_LINE = re.compile(r"^\s*(\d{1,3})[.、）):：]\s*(.*)$")


def _strip_prompt_echo(text: str) -> str:
    """删除 VLM 复读 OCR prompt 指令的句子（通用去污）。

    VLM 有时会把 prompt 中的指令逐条转录进输出（编号列表、祈使句），
    同一句子主体反复出现（编号不同）。识别特征：
    1. 阿拉伯数字编号行（如 "6. 不要添加任何文字..."）
    2. 主体以 prompt 风指令词开头（不要/请勿/严禁/确保/仅输出/逐字/完整保留...）
    3. 同一主体在文档中出现 >=3 次
    正式文档的编号祈使句主体互不相同（操作步骤），或不用此类指令词
    （法规用“不得”而非“不要”），故不误伤。
    """
    lines = text.splitlines()
    bodies = []
    for ln in lines:
        m = _NUMBERED_LINE.match(ln)
        body = m.group(2).strip() if m else None
        bodies.append(body if (body and _PROMPT_ECHO_HINT.match(body)) else None)
    counter: Dict[str, int] = {}
    for b in bodies:
        if b:
            counter[b] = counter.get(b, 0) + 1
    echo = {b for b, c in counter.items() if c >= 3}
    if not echo:
        return text
    return "\n".join(
        ln for ln, b in zip(lines, bodies) if not (b and b in echo)
    )


# OCR prompt 复读句式（无编号形态）：'请识别图片中的全部文字，严格遵守以下规则：'。
# 正文不会出现"请识别图片中的全部文字"这类句式（正文 AI 功能描述形如
# '请识别图像内容，根据图像内容判断…'，无"的…文字"宾语，不命中）。
_OCR_ECHO_SENT = re.compile(
    r"请(识别|提取|转录|阅读|输出)(图片|图像|截图)(中|内|里)?的"
    r"(全部|所有|每[一-]?处)?(文字|文本)"
)
# 句式后可能紧跟 prompt 残片（"严格遵守以下规则"被行拼接截断为"严格"）
_OCR_ECHO_STRIP = re.compile(
    r"请(识别|提取|转录|阅读|输出)(图片|图像|截图)(中|内|里)?的"
    r"(全部|所有|每[一-]?处)?(文字|文本)[，,]?"
    r"(严格遵守以下规则|遵守以下规则|严格)?[：:。.]?"
)


def _strip_ocr_echo(text: str) -> str:
    """剥离 VLM 复读 OCR prompt 句（无编号形态，_strip_prompt_echo 的补充）。

    prompt 中的引导句"请识别图片中的全部文字，严格遵守以下规则："有时被
    无编号地转录进输出（或与正文行内拼接），编号规则无法覆盖。特征：
    1. 行内含 OCR prompt 引导句式（请识别/提取/转录+图片+的+全部文字）
    2. 同一文档中该类行 >=2 次才触发（单次出现视为正文，防误伤）
    剥离时仅删除句式及其 prompt 残片，保留行内剩余正文。
    """
    lines = text.splitlines()
    if sum(1 for ln in lines if _OCR_ECHO_SENT.search(ln)) < 2:
        return text
    out = []
    for ln in lines:
        if _OCR_ECHO_SENT.search(ln):
            rest = _OCR_ECHO_STRIP.sub("", ln, count=1).strip()
            if rest:
                out.append(rest)
        else:
            out.append(ln)
    return "\n".join(out)


def _compress_repeated_text(text: str) -> str:
    """文档级重复文本压缩（通用去污，保守只折叠严格相等的重复）。

    面向源文件常见的多类重复污染（会稀释 embedding 权重、抬升 chunk 体积、
    拖累 rerank 相关性，doc084/doc087/doc108 实证）：
    0. 行内局部周期折叠（'0'x77 删除、'、图表数据'x12 保留 1 份）
    0.5. prompt 复读句删除（VLM 转录指令列表）
    1. 行内单一片段重复（'版本信息控制表'×4）
    2. 相邻完全相同的行（文字层叠加最常见形态）
    3. 连续行块重复（2~6 行块紧邻重复，段落被粘贴两遍的形态）
    只做严格相等折叠，不做模糊相似合并，避免误删合法重复内容。
    """
    if not text:
        return text
    # 0) 行内局部周期折叠
    lines = [_collapse_inline_partial(ln) for ln in text.splitlines()]
    text = "\n".join(lines)
    # 0.5) prompt 复读句删除（编号形态）
    text = _strip_prompt_echo(text)
    # 0.55) OCR prompt 引导句剥离（无编号形态，与正文行内拼接）
    text = _strip_ocr_echo(text)
    lines = [_collapse_inline_repeat(ln) for ln in text.splitlines()]
    # 2) 相邻相同行折叠
    deduped: List[str] = []
    for ln in lines:
        if deduped and ln == deduped[-1] and ln.strip():
            continue
        deduped.append(ln)
    lines = deduped
    # 2.5) 全局行块重复折叠：>=3 行且去空白后>=30 字的连续行块全文重复出现时
    #      仅保留首次出现（源文档整段/整表粘贴两遍的形态）。严格相等，
    #      不误伤相似但不同的表格行（如 MCC 表各行代码不同）。
    if len(lines) > 6:
        block_first: dict = {}
        out2: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            matched = False
            for k in range(min(8, n - i), 2, -1):
                block = tuple(lines[i:i + k])
                if len("".join(b.strip() for b in block)) < 30:
                    continue
                if block in block_first:
                    i += k
                    matched = True
                    break
                block_first[block] = i
            if not matched:
                out2.append(lines[i])
                i += 1
        lines = out2
    # 3) 连续行块重复折叠（k 从大到小，迭代直至无变化）
    changed = True
    while changed:
        changed = False
        out: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            collapsed = False
            for k in range(min(6, (n - i) // 2), 1, -1):
                block = lines[i:i + k]
                if not any(b.strip() for b in block):
                    continue
                if lines[i + k:i + 2 * k] == block:
                    out.extend(block)
                    i += 2 * k
                    collapsed = True
                    changed = True
                    break
            if not collapsed:
                out.append(lines[i])
                i += 1
        lines = out
    return "\n".join(lines)


# ===== 扫描页 OCR 退化升级：条带分解（通用阶梯，判定条件为输出结构特征） =====
# 密集表格扫描页整页 OCR 时 VLM 会退化成复读循环（实测签名："3.1.N 批发业务"×373、
# 单行"1. 1. 1."撞顶、prompt 指令回显、短码 4458/4940/9399 循环）；此时 prompt 级修正
# 无效（要求 Markdown/制表符输出仍 0 个竖线）。解法：渲染图按水平条带切分（有栅格线处
# numpy 投影精切，无栅格处盲切+overlap），逐条 OCR 后按 y 坐标拼回，行级精确去重。
# 正常扫描页（叙述型）整页 OCR 不退化 → 快路径零影响。


def _ocr_vs_pdfplumber_similar(ocr_text: str, pdf_text: str) -> bool:
    """比较 OCR 结果与 pdfplumber 提取是否"大差不差"。

    大差不差定义：pdfplumber 已捕获 OCR 输出的大部分汉字（≥60% 重合），
    说明 pdfplumber 提取已足够，OCR 没有带来实质性新信息。
    用于混合页场景：避免对 PPT 模板/水印页触发昂贵的条带分解管线。
    """
    if not pdf_text.strip():
        return False  # pdfplumber 为空（纯扫描页），无法比较
    ocr_chars = set(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', ocr_text))
    pdf_chars = set(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', pdf_text))
    if not ocr_chars:
        return True
    overlap = len(ocr_chars & pdf_chars) / len(ocr_chars)
    return overlap >= 0.8


def _ocr_degenerate(text: str) -> bool:
    """退化签名检测：OCR 输出是否为复读循环或无关幻觉。

    七类实测签名（阈值按实测样本标定）：
    1. 单行且超长（撞 max_tokens 的编号循环）
    2. 同一行复读（prompt 指令回显）
    3. 某词出现在绝大多数行（"3.1.N 批发业务" 类；纯标点 token 如目录点线"....."不参与统计）
    4. 行去重比极低（短码循环）
    5. LaTeX 数学命令（\\( \\) \\frac \\sum 等）——中文扫描件出现必为无关幻觉
    6. 布局 token（<|LOC_151|> 类引擎泄漏，与 is_garbage 同判据）
    7. 长行内子串循环（重叠 12 字滑窗 top≥10 次，即 ≥120 字连续复读）
    """
    if not text:
        return False
    # 规则6: 布局 token 泄漏（实测 doc020 p7 整页产出几十个 <|LOC_xxx|>）
    if len(re.findall(r"<\|[A-Z_]+[\d_]*\|>", text)) >= 2:
        return True
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    n = len(lines)
    if not n:
        return False
    if n == 1 and len(text) >= 600:
        return True
    # 规则7: 长行内循环（实测 doc020 p7 “贷款后被支付至他人，影响和影响，”单行循环数百次）
    for ln in lines:
        if len(ln) >= 200:
            wins = Counter(ln[i:i + 12] for i in range(len(ln) - 11))
            if wins and max(wins.values()) >= 10:
                return True
    if n >= 8:
        top_line = max(Counter(lines).values())
        if top_line >= 5 and top_line / n > 0.5:
            return True
    if n >= 15:
        # 词频统计排除纯标点 token（TOC 点线"....."等在每行出现但非复读）
        words = [w for w in text.split() if not re.fullmatch(r"[\W_]+", w)]
        if words and max(Counter(words).values()) / n > 0.6:
            return True
        if len(set(lines)) / n < 0.25:
            return True
    # 规则5: LaTeX 数学命令——OCR 幻觉页 LaTeX 几乎铺满每行；而 docx 转换残留只有零星几行
    # （实测 doc108 1094 行仅 3 行含 \downarrow）。按「命中数 + 含 LaTeX 行占比」浓度判定。
    latex_lines = [ln for ln in lines if re.search(r"\\[()\[\]a-zA-Z]", ln)]
    if len(re.findall(r"\\[()\[\]a-zA-Z]", text)) >= 3 and len(latex_lines) * 4 >= n:
        return True
    return False


def _merge_runs(idx: List[int], gap: int = 4) -> List[int]:
    """相邻坐标合并成线段中心（容差 gap px）。"""
    runs: List[List[int]] = []
    for i in idx:
        if runs and i - runs[-1][-1] <= gap:
            runs[-1].append(i)
        else:
            runs.append([i])
    return [int(sum(r) / len(r)) for r in runs]


def _scan_bands(png_path: Path, min_band: int = 200, max_band: int = 450,
                overlap: int = 40) -> List[Tuple[int, int]]:
    """numpy 行投影找水平栅格线 → 构条带。

    有栅格线处按线精切（行不切半）；无栅格处盲切并带 overlap（防行切半，
    拼回时由 _dedup_consecutive_lines 去重）。返回 [(y0, y1), ...]，按 y 升序。
    """
    import numpy as np
    from PIL import Image
    im = Image.open(png_path)
    gray = np.asarray(im.convert("L"), dtype=np.uint8)
    h, w = gray.shape
    dark = gray < 150
    prof = dark.sum(axis=1)
    lines = _merge_runs(np.where(prof > 0.35 * w)[0].tolist())
    bands: List[Tuple[int, int]] = []
    y = 0
    while y < h - min_band:
        cut = next((L for L in lines if y + min_band <= L <= y + max_band), None)
        if cut is None:
            cut = min(y + max_band, h)
            bands.append((y, min(cut + overlap, h)))  # 盲切：带 overlap
        else:
            bands.append((y, cut))  # 栅格线：精切无 overlap
        y = cut
    if y < h:
        bands.append((y, h))
    return bands


def _detect_horizontal_line_count(png_path: Path, threshold: float = 0.35) -> int:
    """正向识别表格：numpy 行投影统计水平栅格线数量。

    真实扫描表格页含 5+ 条栅格线（行行分隔）；PPT 图表/装饰线仅0-2条。
    与 _scan_bands 使用同一阀径，确保判定一致。
    """
    import numpy as np
    from PIL import Image
    im = Image.open(png_path)
    gray = np.asarray(im.convert("L"), dtype=np.uint8)
    h, w = gray.shape
    dark = gray < 150
    prof = dark.sum(axis=1)
    runs = np.where(prof > threshold * w)[0].tolist()
    return len(_merge_runs(runs))


def _dedup_consecutive_lines(text: str) -> str:
    """相邻完全重复行去重（盲切 overlap 在条带边界产生的重复行）。"""
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            out.append("")
            continue
        if out and out[-1] == s:
            continue
        out.append(s)
    return "\n".join(out)


_CYCLIC_UNIT_RE = re.compile(r"^(\d{1,4})([\u4e00-\u9fff]{1,8})$")


def _is_cyclic_line(ln: str) -> bool:
    """单行编号递增循环（实测 doc020 p7 "| 1类账户 | 2类账户 | … | 307类账户 |" 横向幻觉）。

    判定：≥15 个「数字+短中文后缀」单元、后缀众数占比>0.6、数字多数严格递增。
    真实码列（纯数字如 5013，无中文后缀）与同后缀但非递增的列表不命中。
    """
    units = []
    for t in ln.split():
        t = t.strip("| \u3000、,，;；")
        m = _CYCLIC_UNIT_RE.match(t)
        if m:
            units.append(m)
    if len(units) < 15:
        return False
    suffixes = Counter(m.group(2) for m in units)
    if suffixes.most_common(1)[0][1] / len(units) <= 0.6:
        return False
    nums = [int(m.group(1)) for m in units]
    inc = sum(1 for a, b in zip(nums, nums[1:]) if b > a)
    return inc / (len(nums) - 1) >= 0.8


def _drop_cyclic_lines(text: str) -> str:
    """条带拼回后逐行剔除编号循环幻觉行（保留其他行，比整条带丢弃更精细）。"""
    kept = [ln for ln in text.splitlines() if not _is_cyclic_line(ln)]
    dropped = len(text.splitlines()) - len(kept)
    if dropped:
        logger.info(f"剔除编号循环幻觉行 {dropped} 行")
    return "\n".join(kept)


def _truncate_inline_cycle(ln: str) -> str:
    """行内循环截断：找到首个循环单元起点，保留循环前的真实文字。

    确定性滑窗算法（非正则，无回溯爆炸）：对长行前 1/3 位置尝试 6~24 字周期，
    单元连续重复≥5 次（≥30 字）即判循环，截断至循环起点。
    实测 doc020 p7 "贷款后被支付至他人，影响和影响，"×N 单行循环。
    """
    s = ln
    n = len(s)
    if n < 40:
        return ln
    for start in range(min(80, n // 3)):
        for w in range(6, 25):
            if start + 3 * w > n:
                continue
            unit = s[start:start + w]
            reps = 1
            j = start + w
            while j + w <= n and s[j:j + w] == unit and reps < 50:
                reps += 1
                j += w
            if reps >= 5:
                return s[:start].rstrip()
    return ln


def _clean_degenerate_text(text: str) -> str:
    """退化整页文本的截断清洗（条带分解全败时的第三兜底）：
    行内循环截断（保留循环前真实文字）+ 编号循环行剔除 + 布局 token 行剔除。
    """
    kept: List[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or _is_cyclic_line(s):
            continue
        if len(re.findall(r"<\|[A-Z_]+[\d_]*\|>", s)) >= 2:
            continue
        t = _truncate_inline_cycle(s).strip()
        if len(t) >= 20:
            kept.append(t)
    return "\n".join(kept)


_LATEX_CMD_RE = re.compile(
    r"\\(?:downarrow|uparrow|rightarrow|leftarrow|frac|sum|sqrt|int|prod|lim|ldots|cdots|infty|"
    r"begin|end|left|right|mathbf|mathrm|textit|textrm|text|times|cdot|leq|geq|neq|approx|pm|"
    r"nabla|partial|alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|sigma|phi|omega|in|to|cup|cap)\b"
    r"|\\[()]|\\\[|\\\]"
)


def _unwrap_stuffed_para(text: str) -> str:
    """HTML 导出残留的「摊平表格段落」拆解：整张表被塞进单段、以 > 或 | 拼接。

    按分隔符拆成单元行，保留可检索内容（含 CJK 的词、2+ 位数字、字母数字码），
    丢弃符号碎片。实测 doc120 小U点餐手册：2437 字段（| 拼接 + 172 行空占位）与
    1216 字段（&gt; 拼接 15 列行记录）各一条。
    """
    if len(text) < 100 or (text.count(">") + text.count("|")) < 4:
        return text
    kept: List[str] = []
    for tok in re.split(r"[>|]+", text):
        t = tok.strip("<>|= \u3000、,，;；-")
        if not t or len(t) < 2:
            continue
        if re.search(r"[\u4e00-\u9fff]", t) or re.fullmatch(r"\d{2,}(?:[.,]\d+)?", t) \
                or re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9._-]{3,}", t):
            kept.append(t)
    return "\n".join(kept) if len(kept) >= 3 else text


def _normalize_docx_para(text: str) -> str:
    """docx 段落通用归一化（HTML 转换残留清洗，格式级规则，零文档特判）：

    1. HTML 实体还原（&lt;/&gt;/&amp; 等，实测 doc120 表格摊平段）；
    2. 已知 LaTeX 命令剔除（docx 原生文本出现 \downarrow 类必为转换残留，实测 doc108；
       白名单剔除避免误伤 Windows 路径如 C:\\Users）；
    3. 摊平表格段落拆解（整表塞单段、以 > 或 | 拼接）。
    """
    import html
    text = html.unescape(text).strip()
    if not text:
        return ""
    text = _LATEX_CMD_RE.sub("", text).strip()
    if not text:
        return ""
    return _unwrap_stuffed_para(text)


def _normalize_docx_cell(text: str) -> str:
    """docx 表格单元格归一化：仅 HTML 实体还原（单元格内不拆解，避免破坏行列结构）。"""
    import html
    return html.unescape(text)


# 条带 OCR 耗时低于此值视为磁盘缓存命中（不占页级预算）
_OCR_NETWORK_CALL_S = 1.5


def _ocr_strip_attempt(ocr_client, strip_path: Path, prompt: str,
                       budget: Optional[List[int]]) -> str:
    """单次条带 OCR：预算只扣减真实网络调用，磁盘缓存命中免费放行。

    预算的本意是限制复读风暴的墙钟时间；若误扣缓存调用，真表格的
    细分恢复会在半路被截断（doc104 p6 9312 码实证）。
    """
    if budget is not None and budget[0] <= 0:
        return ""
    t0 = time.perf_counter()
    txt = ocr_client.ocr(image_path=str(strip_path), prompt=prompt)
    if budget is not None and time.perf_counter() - t0 >= _OCR_NETWORK_CALL_S:
        budget[0] -= 1
    return txt


def _ocr_strip_with_retry(strip_path: Path, ocr_client, depth: int = 0,
                          budget: Optional[List[int]] = None) -> str:
    """条带 OCR：正向 prompt → 退化/幻觉则换极简 prompt 重试 → 仍失败按条带内
    栅格线细分（无栅格线才对半，深度≤2）→ 仍失败丢弃。

    复读垃圾比缺失更伤检索，宁可丢条不灌垃圾。

    budget：页级真实网络调用预算（缓存命中不扣）。真表格条带首试即中不耗预算
    （doc104 路径）；UI 截图页条带全退化，预算耗尽即弃，防复读风暴
    （doc110 p20 实测约 84 调用/页，预算后 ≤9）。
    """
    txt = _ocr_strip_attempt(ocr_client, strip_path, _OCR_STRIP_PROMPT, budget)
    if not _ocr_degenerate(txt):
        return txt
    txt = _ocr_strip_attempt(ocr_client, strip_path, _OCR_STRIP_RETRY_PROMPT, budget)
    if not _ocr_degenerate(txt):
        return txt
    if depth >= 2:
        logger.warning(f"条带 OCR 持续退化，丢弃 len={len(txt)}")
        return ""
    from PIL import Image
    im = Image.open(strip_path)
    w, h = im.size
    # 优先按条带内栅格线细分（行级不切半）；无栅格线才对半
    sub = _scan_bands(strip_path, min_band=60, max_band=160, overlap=15)
    if len(sub) <= 1:
        sub = [(0, h // 2), (h // 2, h)]
    parts: List[str] = []
    for hi, (y0, y1) in enumerate(sub):
        hp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=f"_h{hi}.png", delete=False) as tf:
                hp = Path(tf.name)
            im.crop((0, y0, w, y1)).save(str(hp), format="png")
            part = _ocr_strip_with_retry(hp, ocr_client, depth=depth + 1, budget=budget)
            if part:
                parts.append(part)
        finally:
            if hp is not None:
                hp.unlink(missing_ok=True)
    return "\n".join(parts)


def _ocr_page_decomposed(png_path: Path, ocr_client) -> str:
    """整页 OCR 退化时的升级路径：条带分解逐条 OCR，按 y 序拼回。

    页级预算限制真实网络调用数（磁盘缓存命中不扣），UI 截图页全退化时
    快速弃页，不逐条带全量放大（doc110 复读风暴实证）。
    """
    bands = _scan_bands(png_path)
    from PIL import Image
    im = Image.open(png_path)
    parts: List[str] = []
    consec_fail = 0
    budget = [8]  # 每页真实网络调用上限（缓存命中的细分恢复不受影响）
    for bi, (y0, y1) in enumerate(bands):
        strip_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=f"_s{bi}.png", delete=False) as tf:
                strip_path = Path(tf.name)
            im.crop((0, y0, im.width, y1)).save(str(strip_path), format="png")
            txt = _ocr_strip_with_retry(strip_path, ocr_client, budget=budget)
            if txt:
                parts.append(txt)
                consec_fail = 0
            else:
                consec_fail += 1
                # 熔断：同页连续 3 条带全败（引擎进入持续循环状态），
                # 剩余条带大概率同样失败，跳过省调用（doc020 PPT 页实证）。
                if consec_fail >= 3:
                    logger.warning(
                        f"条带连续 {consec_fail} 次失败，熔断剩余 {len(bands) - bi - 1} 条带"
                    )
                    break
        except Exception as e:
            # 400/超时等调用异常与退化同罪：计入熔断，防异常条带拖延整页
            logger.warning(f"条带分解 s{bi} y={y0}-{y1} 失败: {e}")
            consec_fail += 1
            if consec_fail >= 3:
                logger.warning(
                    f"条带连续 {consec_fail} 次失败，熔断剩余 {len(bands) - bi - 1} 条带"
                )
                break
        finally:
            if strip_path is not None:
                strip_path.unlink(missing_ok=True)
    return _drop_cyclic_lines(_dedup_consecutive_lines("\n".join(parts)))


class DocumentLoader:
    """按扩展名分发到不同加载器。图片类走 OCR。"""

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

    def __init__(self, ocr_client=None):
        # 懒加载 OCR 客户端，避免未使用时也初始化
        self._ocr = ocr_client

    @property
    def ocr(self):
        if self._ocr is None:
            from app.clients import OCRClient
            self._ocr = OCRClient()
        return self._ocr

    def load(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._load_pdf(path)
        if ext == ".docx":
            return self._load_docx(path)
        if ext == ".doc":
            return self._load_doc(path)
        if ext == ".xlsx":
            return self._load_xlsx(path)
        if ext in {".md", ".markdown"}:
            return self._load_md(path)
        if ext in {".txt", ".text", ".csv", ".json", ".xml", ".html", ".htm"}:
            return self._load_text(path)
        if ext in self.IMAGE_EXTS:
            raw_ocr = self.ocr.ocr(image_path=path, prompt=_OCR_STRUCTURED_PROMPT)
            return _postprocess_ocr_text(raw_ocr)
        raise ValueError(f"不支持的文件类型: {ext}")

    def load_structured(self, file_path: str | Path) -> Tuple[str, Dict]:
        """加载文档并返回 (全文文本, 元数据)。

        元数据包含：
        - title: 文档标题（优先从文档属性读取，兜底从文件名提取）
        - author: 作者/机构（从文档属性读取）
        - language: 语言（默认 zh）
        - sections: List[(start_offset, end_offset, section_title)]，章节偏移量映射
        - pages: List[(start_offset, end_offset, page_num)]，页码偏移量映射
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        ext = path.suffix.lower()
        if ext == ".pdf":
            text, meta = self._load_pdf_structured(path)
        elif ext == ".docx":
            text, meta = self._load_docx_structured(path)
        elif ext == ".doc":
            text, meta = self._load_doc_structured(path)
        elif ext == ".xlsx":
            text, meta = self._load_xlsx_structured(path)
        elif ext in {".md", ".markdown"}:
            text, meta = self._load_md_structured(path)
        elif ext in {".txt", ".text", ".csv", ".json", ".xml", ".html", ".htm"}:
            text, meta = self._load_text_structured(path)
        elif ext in self.IMAGE_EXTS:
            raw_ocr = self.ocr.ocr(image_path=path, prompt=_OCR_STRUCTURED_PROMPT)
            text = _postprocess_ocr_text(raw_ocr)
            meta = self._default_meta(path)
        else:
            text, meta = self._load_text_structured(path)

        # 清洗版面分析模型残留的布局 token（如 <|LOC_88|>）
        text = _clean_layout_tokens(text)
        # Fix5: 文档级重复文本压缩（通用去污：文字层叠加/段落重复会稀释检索质量）
        text = _compress_repeated_text(text)
        return text, meta

    def _default_meta(self, path: Path) -> Dict:
        """构造默认元数据（从文件名提取标题，无页码/章节信息）。"""
        return {
            "title": _extract_title_from_filename(path.name),
            "author": "",
            "language": "zh",
            "sections": [],
            "pages": [],
        }

    def _lookup_meta(self, offset: int, mapping: List[Tuple[int, int, object]]) -> object:
        """根据偏移量在映射表中查找所属的页码/章节。"""
        for start, end, value in mapping:
            if start <= offset < end:
                return value
        # 偏移量超出范围，返回最后一个
        return mapping[-1][2] if mapping else 0

    def _page_ocr_with_upgrade(self, page, path: Path):
        """单页 OCR 升级管线（_load_pdf 与 _load_pdf_structured 共用，避免逻辑漂移）。
    
        混合页检测 → 300 DPI 渲染 → 整页 OCR → 退化签名检测 → 条带分解 →
        竞争兆底（文档级复读压缩）。页面无需 OCR 时返回 None。
        """
        text = _extract_page_text_colwise(page)
        page_blank = not text.strip()
        needs_ocr = page_blank
        ocr_prompt = _OCR_SCAN_PROMPT if page_blank else _OCR_STRUCTURED_PROMPT
        # Fix4: 混合页先 OCR 一次再比较——嵌入图占比>15% 即触发整页 OCR，
        # 与 pdfplumber 文本对比：大差不差则跳过（doc017 PPT模板场景），
        # OCR 多出实质内容且退化才走条带分解（doc102 全宽表格场景）。
        if not needs_ocr and hasattr(page, "images") and page.images:
            page_area = float(page.width * page.height)
            if page_area > 0:
                max_img_ratio = max(
                    (float(im.get("width", 0) * im.get("height", 0))
                     for im in page.images if isinstance(im, dict)),
                    default=0.0,
                ) / page_area
                if max_img_ratio > 0.15:
                    needs_ocr = True
                    logger.info(
                        f"混合页面触发 OCR {path.name} p{page.page_number}: "
                        f"文本={len(text.strip())}字, 最大图占比={max_img_ratio:.0%}"
                    )
        if not needs_ocr:
            return None
        try:
            # 分辨率 300 DPI，提高小字/密集参数识别率
            img = page.to_image(resolution=300)
            with tempfile.NamedTemporaryFile(
                suffix=f"_{path.stem}_p{page.page_number}.png", delete=False
            ) as tf:
                tmp = Path(tf.name)
            try:
                img.save(str(tmp), format="png")
                ocr_text = self.ocr.ocr(
                    image_path=tmp,
                    prompt=ocr_prompt,
                )
                # Fix4: OCR 结果与 pdfplumber 对比——大差不差则不升级条带分解。
                # 注意：仍返回 OCR 文本参合并（昂贵的是条带阶梯，整页 OCR 已经调完），
                # 若这里 return None 会把 OCR 独有的新实体（公司名/参数句）连同
                #  pdfplumber 缺失部分一起丢弃（adv100 实测回归 8 题：doc102/110）。
                if (not page_blank and not _ocr_degenerate(ocr_text)
                        and _ocr_vs_pdfplumber_similar(ocr_text, text)):
                    logger.info(
                        f"OCR 与 pdfplumber 大差不差，跳过条带分解 {path.name} p{page.page_number}"
                    )
                    return ocr_text
                # 整页 OCR 退化（复读循环）→ 正向识别表格：仅当含 5+ 条水平栅格线
                # （真实扫描表格特征）且 OCR 输出量极大（撞顶 max_tokens）且比
                # pdfplumber 多出实质内容时才走条带分解。PPT 图表/截图无栅格线→跳过
                if (_ocr_degenerate(ocr_text)
                        and len(ocr_text.strip()) > 300
                        and len(ocr_text.strip()) > len(text.strip()) * 1.5
                        and _detect_horizontal_line_count(tmp) >= 8):
                    logger.info(
                        f"整页 OCR 退化，升级条带分解 {path.name} p{page.page_number}"
                    )
                    decomposed = _ocr_page_decomposed(tmp, self.ocr)
                    # 竞争兆底（三选一）：块级严格重复的复读形态（如落款块循环）文档级
                    # 压缩即可还原（doc107 p12 实证）；分解全败时退回截断清洗版，
                    # 保住循环前真实文字（doc020 p7 实证）；两者自身都必须干净——
                    # 词级复读（doc104 p6 "3.1.N 批发业务"）压缩后仍退化，不可选用。
                    compressed = _compress_repeated_text(ocr_text)
                    truncated = _clean_degenerate_text(ocr_text)
                    candidates = []
                    for name, t in (("compressed", compressed), ("truncated", truncated)):
                        if t and not _ocr_degenerate(t):
                            candidates.append((name, t))
                    if _ocr_degenerate(decomposed) or len(decomposed) < 100:
                        # 分解不可用：取候选中最长（信息保留优先）
                        ocr_text = (max(candidates, key=lambda x: len(x[1]))[1]
                                    if candidates else decomposed)
                    else:
                        # 分解可用：候选仅在压缩率显著且信息更全时替换分解
                        ocr_text = decomposed
                        for name, t in candidates:
                            if len(t) < len(ocr_text) * 0.6 and len(t) > len(decomposed):
                                ocr_text = t
                                break
                elif _ocr_degenerate(ocr_text):
                    # OCR 退化但不比 pdfplumber 多→OCR 无价值，用压缩/截断兆底
                    compressed = _compress_repeated_text(ocr_text)
                    truncated = _clean_degenerate_text(ocr_text)
                    for t in (compressed, truncated):
                        if t and not _ocr_degenerate(t):
                            ocr_text = t
                            break
                    else:
                        ocr_text = ""  # 全败→丢弃 OCR，用 pdfplumber
                return ocr_text
            finally:
                tmp.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"PDF 页面 OCR 失败 {path.name} p{page.page_number}: {e}")
            return ""

    def _load_pdf(self, path: Path) -> str:
        import pdfplumber
        parts: List[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = _extract_page_text_colwise(page)
                ocr_text = self._page_ocr_with_upgrade(page, path)
                if ocr_text is not None:
                    # 混合页面时，合并 pdfplumber 文本和 OCR 文本（去重）
                    if text.strip() and ocr_text:
                        text = _merge_text_and_ocr(text, ocr_text)
                    elif ocr_text:
                        text = ocr_text
                if text:
                    text = _postprocess_ocr_text(text)
                if text:
                    parts.append(text)
        return "\n\n".join(parts)

    def _load_docx(self, path: Path) -> str:
        from docx import Document
        from docx.oxml.ns import qn
        doc = Document(str(path))

        # 图片 OCR 已停用：仅提取正文段落与表格文字，保证文本型文档的检索质量

        parts: List[str] = []
        body = doc.element.body
        para_idx = 0
        table_idx = 0
        paragraphs = doc.paragraphs
        tables = doc.tables

        for child in body:
            tag = child.tag
            if tag == qn("w:p"):
                if para_idx < len(paragraphs):
                    p = paragraphs[para_idx]
                    para_idx += 1
                    text = _normalize_docx_para(p.text)
                    if text:
                        parts.append(text)
            elif tag == qn("w:tbl"):
                if table_idx < len(tables):
                    table = tables[table_idx]
                    table_idx += 1
                    md = self._table_to_markdown(table)
                    if md:
                        parts.append(md)

        return "\n".join(parts)

    def _load_doc(self, path: Path) -> str:
        """旧版 .doc（Word OLE 二进制）。跨平台纯 Python，不依赖 Microsoft Office/pywin32。

        优先级（无任何硬性系统依赖，逐级降级）：
        1) 若系统已装 antiword / catdoc / soffice(libreoffice)，调用其转文本（质量更高，可选）
        2) 纯 Python：用 olefile 读取 WordDocument 流，提取 UTF-16LE 文本
        3) 兜底：对整文件做可打印字符扫描
        所有外部转换器输出均写入系统 temp 目录，绝不触碰原始文件。
        """
        # 策略1：可选外部转换器（不强依赖）
        for cmd in ("antiword", "catdoc"):
            text = self._doc_via_subprocess(cmd, [str(path)])
            if text:
                return text
        text = self._doc_via_libreoffice(path)
        if text:
            return text

        # 策略2/3：纯 Python
        logger.info(f".doc 纯 Python 提取（可能含少量噪声）: {path.name}")
        return self._doc_extract_pure(path)

    def _doc_via_subprocess(self, cmd: str, args: list) -> str:
        import subprocess
        try:
            r = subprocess.run([cmd, *args], capture_output=True, timeout=60)
        except FileNotFoundError:
            return ""
        except Exception as e:
            logger.warning(f"调用 {cmd} 失败: {e}")
            return ""
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", errors="ignore")
        return ""

    def _doc_via_libreoffice(self, path: Path) -> str:
        import subprocess
        import tempfile
        for bin_name in ("soffice", "libreoffice"):
            try:
                with tempfile.TemporaryDirectory() as td:
                    r = subprocess.run(
                        [bin_name, "--headless", "--convert-to", "txt:Text",
                         "--outdir", td, str(path)],
                        capture_output=True, timeout=180,
                    )
                    if r.returncode == 0:
                        out = Path(td) / (path.stem + ".txt")
                        if out.exists() and out.stat().st_size > 0:
                            return out.read_text(encoding="utf-8", errors="ignore")
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.warning(f"调用 {bin_name} 失败: {e}")
                continue
        return ""

    def _doc_extract_pure(self, path: Path) -> str:
        import re
        raw = path.read_bytes()
        stream = None
        try:
            import olefile  # type: ignore
            ole = olefile.OleFileIO(path)
            if ole.exists("WordDocument"):
                stream = ole.openstream("WordDocument").read()
            ole.close()
        except ImportError:
            logger.warning("未安装 olefile，退化为整文件字节扫描")
        except Exception as e:
            logger.warning(f"olefile 解析失败，退化为整文件扫描: {e}")
        if stream is None:
            stream = raw

        # Word 正文主要按 UTF-16LE 存储
        text = stream.decode("utf-16-le", errors="ignore")
        text = "".join(ch for ch in text if ch in "\n\t\r " or ch.isprintable())
        if not text.strip():
            text = raw.decode("latin-1", errors="ignore")
            text = "".join(ch for ch in text if ch in "\n\t " or ch.isprintable())

        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _load_xlsx(self, path: Path) -> str:
        from openpyxl import load_workbook
        wb = load_workbook(filename=str(path), read_only=True, data_only=True)
        parts: List[str] = []
        for ws in wb.worksheets:
            # 保留列位（None 作空单元格），交由 _rows_to_markdown 对齐并渲染表头
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
            md = _rows_to_markdown(rows)
            if md:
                parts.append(md)
        wb.close()
        return "\n\n".join(parts)

    def _load_md(self, path: Path) -> str:
        """加载 Markdown 文件并去除格式标记，提取纯文本。"""
        import re
        text = path.read_text(encoding="utf-8")

        # 去除代码块 ```...```
        text = re.sub(r'```[\s\S]*?```', '', text)
        # 去除行内代码 `...`
        text = re.sub(r'`[^`]*`', '', text)
        # 去除图片语法 ![alt](url)
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        # 转换链接语法 [text](url) 为 text
        text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
        # 去除标题标记 # ######
        text = re.sub(r'#{1,6}\s*', '', text)
        # 去除加粗标记 **...** 或 __...__
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        # 去除斜体标记 *...* 或 _..._
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        # 去除列表标记 -, *, +, 1.
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        # 去除引用标记 >
        text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)
        # 去除水平线
        text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
        # 去除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        # 合并多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def _load_text(self, path: Path) -> str:
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                return path.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")

    # ===== 结构化加载（带元数据） =====

    def _load_pdf_structured(self, path: Path) -> Tuple[str, Dict]:
        """PDF 结构化加载：逐页提取文本，记录页码偏移量映射。

        OCR 升级管线（混合页检测/退化检测/条带分解/竞争兜底）与 _load_pdf
        共用 _page_ocr_with_upgrade，保证两路径行为一致。
        """
        import pdfplumber
        parts: List[str] = []
        pages: List[Tuple[int, int, int]] = []  # (start, end, page_num)
        offset = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = _extract_page_text_colwise(page)
                ocr_text = self._page_ocr_with_upgrade(page, path)
                if ocr_text is not None:
                    if text.strip() and ocr_text:
                        text = _merge_text_and_ocr(text, ocr_text)
                    elif ocr_text:
                        text = ocr_text
                # OCR 后处理
                if text:
                    text = _postprocess_ocr_text(text)
                if text:
                    start = offset
                    parts.append(text)
                    offset += len(text) + 2
                    end = offset
                    pages.append((start, end, page.page_number))
        full_text = "\n\n".join(parts)
        meta = self._default_meta(path)
        meta["pages"] = pages
        return full_text, meta

    _DOCX_IMG_MIN = 150  # Fix3 Triage：最短边低于此像素的图片（logo/装饰图）不 OCR

    def _ocr_docx_image(self, image_part) -> str:
        """DOCX 嵌入图片 OCR（Triage + 退化检测 + 摊平串拆解 + 行级质量门）。

        仅转录最短边>=150px 的图片；OCR 行再过 _ocr_line_quality_ok，
        跨语种幻觉/符号汤行不入正文。temperature=0 由 OCRClient 保证。
        与 PDF 页级路径同构：整图输出退化（复读循环/长行循环）时先清理再判——
        VLM 常把图片表格输出成 >/| 分隔摊平串带 HTML 实体（doc120 53 图实测），
        摊平拆解后是有效表格内容；清理后仍退化才丢弃整图。
        """
        try:
            from PIL import Image as PILImage
            im = PILImage.open(io.BytesIO(image_part.blob))
            if min(im.size) < self._DOCX_IMG_MIN:
                return ""
            ext = Path(image_part.partname).suffix or ".png"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                tmp = Path(tf.name)
            try:
                tmp.write_bytes(image_part.blob)
                raw = self.ocr.ocr(image_path=tmp, prompt=_OCR_STRUCTURED_PROMPT)
            finally:
                tmp.unlink(missing_ok=True)
            raw = _postprocess_ocr_text(raw or "")
            if _ocr_degenerate(raw):
                cleaned = _drop_cyclic_lines(raw)
                cleaned = "\n".join(
                    _normalize_docx_para(ln) if len(ln) >= 100 else ln
                    for ln in cleaned.splitlines() if ln.strip()
                )
                if not cleaned or _ocr_degenerate(cleaned):
                    return ""
                raw = cleaned
            kept = [ln.strip() for ln in raw.splitlines()
                    if ln.strip() and _ocr_line_quality_ok(ln)]
            kept = [_normalize_docx_para(ln) if len(ln) >= 100 else ln for ln in kept]
            return "\n".join(kept)
        except Exception as e:
            logger.warning(f"DOCX 图片 OCR 失败: {e}")
            return ""

    def _load_docx_structured(self, path: Path) -> Tuple[str, Dict]:
        """DOCX 结构化加载：读文档属性（标题/作者），提取 heading 章节信息，解析表格，
        并对嵌入图片做 OCR（解决截图型操作手册内容不入库问题）。"""
        from docx import Document
        from docx.oxml.ns import qn
        doc = Document(str(path))

        # 提取文档属性
        cp = doc.core_properties
        title = (cp.title or "").strip() if cp.title else ""
        author = (cp.author or "").strip() if cp.author else ""
        if not title:
            title = _extract_title_from_filename(path.name)

        # 图片 OCR（Fix3 恢复）：只对尺寸达标（最短边>=150px）的图片转录，行级质量门过滤，
        # 避免装饰性小图/logo 与跨语种幻觉行进入正文。

        # 提取章节信息（通过 Heading 样式）+ 表格内容 + 图片 OCR
        parts: List[str] = []
        sections: List[Tuple[int, int, str]] = []
        offset = 0
        current_section = ""
        section_start = 0

        # 遍历文档 body 元素（段落 + 表格 + 图片按原文档顺序）
        body = doc.element.body
        para_idx = 0
        table_idx = 0
        paragraphs = doc.paragraphs
        tables = doc.tables
        img_ocr_count = 0
        seen_rids: set = set()  # 同一嵌入图片只 OCR 一次（docx 常多处引用同一 rId）

        for child in body:
            tag = child.tag
            if tag == qn("w:p"):
                # 段落
                if para_idx < len(paragraphs):
                    p = paragraphs[para_idx]
                    para_idx += 1
                    # Fix3: 段落内嵌图片 OCR（按文档顺序插入，同一图片只 OCR 一次）
                    blips = p._p.findall('.//' + qn('a:blip'))
                    for blip in blips:
                        rid = blip.get(qn('r:embed'))
                        if not rid or rid in seen_rids:
                            continue
                        seen_rids.add(rid)
                        try:
                            image_part = p.part.rels[rid].target_part
                        except KeyError:
                            continue
                        ocr_txt = self._ocr_docx_image(image_part)
                        if ocr_txt:
                            img_ocr_count += 1
                            for ln in ocr_txt.splitlines():
                                parts.append(ln)
                                offset += len(ln) + 1
                    text = _normalize_docx_para(p.text)
                    if text:
                        # 检测 Heading 样式
                        style_name = (p.style.name or "").lower() if p.style else ""
                        if "heading" in style_name or "title" in style_name:
                            if current_section and offset > section_start:
                                sections.append((section_start, offset, current_section))
                            current_section = text.splitlines()[0]
                            section_start = offset
                        parts.append(text)
                        offset += len(text) + 1
            elif tag == qn("w:tbl"):
                # 表格：格式化为 Markdown（保留行列结构）
                if table_idx < len(tables):
                    table = tables[table_idx]
                    table_idx += 1
                    md = self._table_to_markdown(table)
                    if md:
                        parts.append(md)
                        offset += len(md) + 1

        # 最后一个 section
        if current_section and offset > section_start:
            sections.append((section_start, offset, current_section))

        full_text = "\n".join(parts)
        meta = {
            "title": title,
            "author": author,
            "language": "zh",
            "sections": sections,
            "pages": [],  # DOCX 无可靠页码
        }
        return full_text, meta

    @staticmethod
    def _table_to_markdown(table) -> str:
        """将 docx 表格转为 Markdown（复用通用 _rows_to_markdown）。

        按文档行/列顺序采集单元格，表头与分隔行由助手统一生成，保留行列关系。
        """
        rows = [[_normalize_docx_cell(cell.text) for cell in row.cells] for row in table.rows]
        return _rows_to_markdown(rows)

    def _load_doc_structured(self, path: Path) -> Tuple[str, Dict]:
        """DOC 结构化加载：复用纯文本加载，元数据从文件名提取。"""
        text = self._load_doc(path)
        return text, self._default_meta(path)

    def _load_xlsx_structured(self, path: Path) -> Tuple[str, Dict]:
        """XLSX 结构化加载：复用纯文本加载，元数据从文件名提取。"""
        text = self._load_xlsx(path)
        return text, self._default_meta(path)

    def _load_md_structured(self, path: Path) -> Tuple[str, Dict]:
        """MD 结构化加载：通过 # 标题提取章节信息。"""
        raw = path.read_text(encoding="utf-8")
        text = self._load_md(path)  # 复用已有的 markdown 清洗逻辑

        # 从原始 markdown 提取章节标题
        sections: List[Tuple[int, int, str]] = []
        current_section = ""
        section_start = 0
        offset = 0
        for line in raw.split("\n"):
            stripped = line.strip()
            # 匹配 markdown 标题
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                if current_section and offset > section_start:
                    sections.append((section_start, offset, current_section))
                current_section = heading_match.group(2).strip()
                section_start = offset
            offset += len(line) + 1
        if current_section and offset > section_start:
            sections.append((section_start, offset, current_section))

        meta = self._default_meta(path)
        meta["sections"] = sections
        return text, meta

    def _load_text_structured(self, path: Path) -> Tuple[str, Dict]:
        """TXT 结构化加载：元数据从文件名提取，无页码/章节。"""
        text = self._load_text(path)
        return text, self._default_meta(path)


class Chunker:
    """递归字符切分，优先在中文/英文句末标点处断开。"""

    SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", ".", " ", ""]

    def __init__(self, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def split(self, text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]
        # 修复：merge_with_overlap 只在顶层调用一次；
        # 递归内层不再各自 merge，避免 overlap 前文被双重拼接成块内 [Z][Z][W] 重复。
        chunks = self._recursive_split(text, self.SEPARATORS)
        return self._merge_with_overlap(chunks)

    def split_with_positions(self, text: str) -> List[Tuple[str, int]]:
        """分块并返回每个 chunk 在原文中的起始偏移量。

        返回 [(chunk_text, start_offset), ...]
        用于通过偏移量查找 chunk 所属的页码/章节。
        """
        chunks = self.split(text)
        if not chunks:
            return []
        result: List[Tuple[str, int]] = []
        search_from = 0
        for chunk in chunks:
            # 取 chunk 的前 30 个字符作为搜索锚点（避免 overlap 导致的重复匹配）
            anchor = chunk[:30].strip()
            if anchor:
                pos = text.find(anchor, search_from)
                if pos == -1:
                    # 兜底：从头搜索
                    pos = text.find(anchor)
                if pos == -1:
                    pos = search_from  # 最终兜底
            else:
                pos = search_from
            result.append((chunk, pos))
            # 下次搜索从当前位置 + chunk 长度的 80% 开始（考虑 overlap）
            search_from = pos + max(1, int(len(chunk) * 0.8))
        return result

    def _recursive_split(self, text: str, separators: List[str]) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        sep = separators[0]
        if sep == "":
            # 兜底：按字符硬切
            return self._hard_split(text)

        pieces = text.split(sep) if sep else [text]
        next_seps = separators[1:]

        chunks: List[str] = []
        buf = ""
        for piece in pieces:
            piece_with_sep = piece + sep if sep else piece
            candidate = buf + piece_with_sep
            if len(candidate) <= self.chunk_size:
                buf = candidate
            else:
                if buf.strip():
                    chunks.append(buf)
                # 当前 piece 自身超长，递归用更细的分隔符
                if len(piece_with_sep) > self.chunk_size:
                    chunks.extend(self._recursive_split(piece, next_seps))
                    buf = ""
                else:
                    buf = piece_with_sep
        if buf.strip():
            chunks.append(buf)

        return chunks  # 顶层 split 统一 merge，避免双重 overlap

    def _hard_split(self, text: str) -> List[str]:
        chunks = [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]
        return chunks  # 顶层 split 统一 merge，避免双重 overlap

    def _merge_with_overlap(self, chunks: List[str]) -> List[str]:
        result: List[str] = []
        for c in chunks:
            c = c.strip()
            if not c:
                continue
            if self.chunk_overlap > 0 and result:
                prev_tail = result[-1][-self.chunk_overlap :]
                c = prev_tail + c
            # 硬截断：防止超长 chunk 导致向量化超 token 上限
            if len(c) > self.chunk_size * 2:
                for i in range(0, len(c), self.chunk_size):
                    piece = c[i : i + self.chunk_size]
                    if piece.strip():
                        result.append(piece)
            else:
                result.append(c)
        return [c for c in result if c.strip()]
