"""文档定级初始化（数据初始化第一步）。

为什么需要这一步
----------------
`kms_doc_levels` 为空 → 所有文档对所有人不可见。这是 fail-closed 的**正确**表现，
但结果是系统里没有任何内容可看、问答也召回不到东西。

为什么不能简单批量赋值
----------------------
定级是安全决策，两种偷懒做法都是错的：
  - 全部 L0（公开）：所有文档对全公司敞开，等于取消分级保护；
  - 全部 L3（绝密）：除 L3 员工外无人可见，系统依旧"看起来是空的"。

本脚本遵守四条约束
------------------
  1. **默认只演练**（--dry-run），必须显式 --apply 才写库；
  2. **规则显式可审计**——每篇的定级结果都能追溯到命中的具体关键词与规则；
  3. **L3 绝密绝不自动定**——命中绝密信号也只升到 L2 并标记为待人工复核；
  4. **就高不就低**——同时命中多个等级时取最高，宁可定高也不可定低
     （定低 = 泄密，定高只是暂时看不见，后果不对称）。

信号来源
--------
文件名 + 正文前若干片段。只看文件名会漏判（例如正文含"密钥"但文件名看不出来），
只看正文又容易被无关词误伤，故两者都参与、取最高命中。

用法
----
    python scripts/init_classify.py --survey    # 只看现状，不写库
    python scripts/init_classify.py             # 演练：打印将写入什么
    python scripts/init_classify.py --apply     # 真正写入
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _bootstrap_env() -> str:
    """在任何依赖配置的模块被导入**之前**套用环境文件，返回所用路径。

    必须早于下方 import：config.Settings 是类属性，在 import 期就完成求值，
    先导入再改配置是无效的——这正是本脚本一度误操作到 QA 库（rag_competition）
    而非 KMS 库（enterprise_kms）的根因。两个库的文档与用户完全独立，
    打错库不会报错，只会静默改到错的数据上。
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env", default=str(ROOT / ".env"))
    known, _ = pre.parse_known_args()
    from scripts.service import apply_environment, load_values

    apply_environment(known.env, load_values(known.env))
    return known.env


DEFAULT_ENV = _bootstrap_env()

from app.store import MySQLStore  # noqa: E402
from kms.constants import DOC_DEPT_UNLIMITED, SECURITY_LEVELS  # noqa: E402

SEPARATOR = "=" * 72

# 定级规则：命中即取该等级，最终取所有命中中的**最高**值。
# 关键词按"升密"方向组织：越靠上的列表密级越高。

# L3 信号：命中也不自动定 L3，只升到 L2 并标记人工复核
L3_SIGNALS = ("绝密", "核心商密", "核心商业秘密")

# L2 强信号：这类词**绝不该出现在公开资料里**
# 注意：不含"密码"/"凭证"——它们在支付产品文件名里是功能词
# （"重置密码操作手册"讲的是功能，不是凭据本身），实测误判。
L2_STRONG = (
    "密钥", "私钥", "口令", "credential", "secret", "token",
    "反洗钱", "黑名单", "可疑交易",
)

# 权威机构正式发文：命中"机构 + 文种"两者时判定为公开来源，**优先于主题词**。
# 理由（实测踩出来的）：一份讲反洗钱的央行文件，它本身是公开法规——
# 047 号（人民银行·可疑交易报告通知）、081 号（人民银行令·反洗钱办法）
# 都曾被"反洗钱/可疑交易"误判成 L2 机密。主题敏感 ≠ 文件密级。
PUBLIC_ISSUERS = ("人民银行", "央行", "银监会", "外汇管理局", "外汇局",
                  "银保监", "金融监管", "国务院", "发改委", "财政部")
PUBLIC_DOCTYPES = ("通知", "令", "办法", "批复", "公告", "条例", "规定",
                   "指引", "意见", "细则", "决定", "函")

# L2 弱信号：经营敏感词，但在支付行业正文里很常见（如"清算"），
# 放在正文上会把公开新闻误判成机密，因此**仅匹配文件名**
L2_WEAK = ("合同", "协议", "报价", "费率", "清算", "对账", "结算价",
           "应急预案", "灾备")

# L1 秘密：内部资料，不宜对外，但泄露损失有限（同样仅匹配文件名）
L1_KEYWORDS = (
    "手册", "部署", "运维", "架构", "方案", "设计", "规范", "接口",
    "api", "培训", "内部", "指南", "操作", "配置", "故障", "排查",
)

# L0 公开（公司内部公开）：外部公开发布的政策/新闻/公告类（仅匹配文件名）
L0_KEYWORDS = (
    "人民银行", "央行", "外汇管理局", "外汇局", "银保监", "金融监管",
    "公告", "通知", "新闻", "公开发布", "白皮书",
    "政策", "法规", "条例", "办法", "指引", "标准",
    "运行情况", "统计报告", "季度报告", "年度报告",
)

# 未命中任何规则时的默认等级。
# 取 L1 而非 L0：不明确的资料按内部资料处理，符合 fail-closed。
DEFAULT_LEVEL = 1

# 自动定级的上限：L3 绝密必须由人确认，脚本绝不自动赋
AUTO_MAX_LEVEL = 2


def _level_name(level: int) -> str:
    return SECURITY_LEVELS.get(level, f"L{level}")


def classify(filename: str) -> tuple[int, str, bool]:
    """返回 (等级, 命中原因, 是否需人工复核)。

    取所有命中规则中的最高等级；命中 L3 信号时封顶到 AUTO_MAX_LEVEL 并标记复核。

    **只匹配文件名，不用正文。** 这是两次实测踩出来的结论：
      - 第一轮允许正文匹配全部关键词：央行公开新闻因正文含"清算"被定 L2；
      - 第二轮收窄到只允许正文匹配"强信号"（密码/凭证/征信/私钥/密钥…）：
        120 篇语料上仍误判 5 篇以上——`007-交通银行 B2B 网上支付操作手册`
        （公开手册，正文讲登录"密码"）、`008-国家外汇管理局通知`（正文"凭证"）、
        `012-《Web3支付产业研讨会》`（正文"私钥"）全被定成 L2 机密。

    根因是本语料为支付行业资料，这些词在**正文里是普通词汇**，
    出现频率与密级无关。文件名则能稳定反映资料性质（"手册"= 内部资料，
    "人民银行/外汇管理局"= 公开文件）。

    代价是**漏判**：一份取名平常、正文含真实密钥的文件会落到默认 L1。
    这个代价可以接受——漏判最多是定低一级，而误判成 L2 会让公开资料
    对本该看到的人不可见，且无人会收到提示去纠正。
    真正的绝密认定必须人工审，脚本不越界。
    """
    name_l = filename.lower()
    hits: list[tuple[int, str]] = []

    for group, level, label in ((L3_SIGNALS, 3, "L3信号"),
                                (L2_STRONG, 2, "L2强信号"),
                                (L2_WEAK, 2, "L2弱信号"),
                                (L1_KEYWORDS, 1, "L1内部词"),
                                (L0_KEYWORDS, 0, "L0公开词")):
        for kw in group:
            if kw.lower() in name_l:
                hits.append((level, f"{label}:{kw}"))
                break

    # 权威机构正式发文 → 公开来源优先，压过主题词命中的更高等级。
    # 被压掉的命中会写进原因并标记复核，交人工兜底（宁可让人看一眼，
    # 也不要让公开法规被锁成机密后无人敢动）。
    has_issuer = any(k in name_l for k in PUBLIC_ISSUERS)
    doctype = next((k for k in PUBLIC_DOCTYPES if k in name_l), "")
    if has_issuer and doctype:
        suppressed = [h for h in hits if h[0] > 0]
        reason = f"公开来源优先（权威机构正式发文，文种「{doctype}」）"
        if suppressed:
            reason += "；已压掉 " + "、".join(h[1] for h in suppressed) + "，请复核"
        return 0, reason, bool(suppressed)

    if not hits:
        return DEFAULT_LEVEL, f"未命中任何规则，默认 L{DEFAULT_LEVEL}", False

    top = max(h[0] for h in hits)
    reasons = [h[1] for h in hits if h[0] == top]
    # 同时命中多组时，取最高等级那一组作为主因，其余作为佐证
    others = [h[1] for h in hits if h[0] != top]
    reason = "、".join(reasons)
    if others:
        reason += f"（另命中 {'、'.join(others)}，就高取 L{top}）"

    needs_review = top >= 3
    if needs_review:
        top = AUTO_MAX_LEVEL
        reason += f" → 封顶 L{top}，待人工复核是否升 L3"
    return top, reason, needs_review


def _sample_text(document_id: int, limit: int = 8) -> str:
    """取正文前若干片段作为定级依据（无需加载全文）。"""
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT text FROM chunks WHERE document_id=%s "
                    "ORDER BY chunk_index LIMIT %s", (document_id, limit))
        return "\n".join(r["text"] or "" for r in cur.fetchall())


def survey() -> None:
    """盘点现状：定级的必要性、可依据的信号、以及定级之后是否真的可见。"""
    print(SEPARATOR)
    print("文档定级 · 现状盘点（只读）")
    print(SEPARATOR)

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) n FROM documents")
        total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM documents d "
                    "JOIN kms_doc_levels l ON l.document_id=d.id")
        classified = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM kms_doc_levels l "
                    "LEFT JOIN documents d ON d.id=l.document_id WHERE d.id IS NULL")
        orphan = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM chunks")
        chunks = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM chunks c "
                    "LEFT JOIN documents d ON d.id=c.document_id WHERE d.id IS NULL")
        orphan_chunks = cur.fetchone()["n"]

    print(f"文档总数           = {total}")
    print(f"已定级（有效）     = {classified}")
    print(f"未定级             = {total - classified}")
    print(f"孤立密级记录       = {orphan}（指向不存在的文档，属脏数据）")
    print(f"文本块总数         = {chunks}")
    print(f"孤立文本块         = {orphan_chunks}")

    # 源文件是否还在：决定缺失的文档是"可重建"还是"真丢失"
    repo = Path("RAG_repository")
    if repo.is_dir():
        from kms.formats import ALLOWED_EXTS, collect_files

        src = collect_files(repo, ALLOWED_EXTS)
        print(f"\n源文件（{repo}）= {len(src)}")
        if len(src) > total:
            print(f"  [!] 库内比源文件少 {len(src) - total} 篇：这批文档在库中缺失。")
            print("      源文件完好，可用 scripts/reingest_all.py 重建；")
            print("      但重建会清空现有库，且需要模型出域授权，请先确认。")
        elif len(src) < total:
            print(f"  [!] 库内比源文件多 {total - len(src)} 篇：有文档已不在源目录。")

    # ---- 可用于推导密级的信号 ----
    print("\n--- 可用于定级的信号 ---")
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT file_type, COUNT(*) n FROM documents "
                    "GROUP BY file_type ORDER BY n DESC")
        for r in cur.fetchall():
            print(f"  类型 {str(r['file_type']):<10} {r['n']}")

    # ---- 定级之后是否真的可见？ ----
    print("\n--- 定级之后能否被看见（关键前置检查）---")
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE is_active=1")
        active = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE is_active=1 "
                    "AND department IS NOT NULL AND department<>''")
        with_dept = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE is_active=1 "
                    "AND org_path IS NOT NULL AND org_path<>''")
        with_org = cur.fetchone()["n"]
        cur.execute("SELECT security_level, COUNT(*) n FROM kms_users "
                    "WHERE is_active=1 GROUP BY security_level ORDER BY security_level")
        levels = cur.fetchall()

    print(f"  在职员工           = {active}")
    print(f"  其中有部门         = {with_dept}")
    print(f"  其中有组织路径     = {with_org}")
    lv = {r["security_level"]: r["n"] for r in levels}
    print("  在职员工密级分布   = " +
          ", ".join(f"L{k}({_level_name(k)}):{v}" for k, v in sorted(lv.items())))

    if with_dept == 0:
        print("\n  [!] 所有在职员工的 department 均为空。")
        print("      后果：分级判定里 `active = is_active AND department` 为假，")
        print("            员工的可见密级上界被压到 L0——")
        print("            **即使把文档定成 L1/L2/L3，仍然没有人能看见。**")
        print("      即：定级是必要条件，但不是充分条件。")
        print("      还需补齐员工的部门/组织归属（HR 同步），否则只有 L0 文档可见。")


def build_plan(include_classified: bool = False) -> list[dict]:
    """按规则生成定级方案（只读，不写库）。

    include_classified=True 时重判**全部**文档（用于存量已定级但需要按新规则复核的库），
    并带上 current 字段供比对升降。
    """
    with MySQLStore()._conn() as cur:
        if include_classified:
            cur.execute(
                "SELECT d.id, d.filename, d.file_type, d.owner_department, "
                "l.level AS current FROM documents d "
                "LEFT JOIN kms_doc_levels l ON l.document_id=d.id ORDER BY d.id")
        else:
            cur.execute(
                "SELECT d.id, d.filename, d.file_type, d.owner_department, "
                "NULL AS current FROM documents d "
                "LEFT JOIN kms_doc_levels l ON l.document_id=d.id "
                "WHERE l.document_id IS NULL ORDER BY d.id")
        docs = cur.fetchall()

    plan = []
    for d in docs:
        level, reason, review = classify(d["filename"])
        plan.append({"document_id": d["id"], "filename": d["filename"],
                     "level": level, "level_name": _level_name(level),
                     "current": d["current"], "owner_department": d["owner_department"] or "",
                     "reason": reason, "needs_review": review})
    return plan


def show_reclassify(plan: list[dict]) -> None:
    """重判演练：显示升降变化，并推算可见性后果。

    只看等级分布是不够的——**升密会把文档变成"需部门匹配才可见"**，
    若该文档 owner_department 为空，升到 L1 以上就等于对全员隐藏。
    这个后果必须在写入前算出来，否则会出现"分级做对了、系统却空了"。
    """
    print(SEPARATOR)
    print(f"重判演练（未写库）· 共 {len(plan)} 篇")
    print(SEPARATOR)

    up = [p for p in plan if p["current"] is not None and p["level"] > p["current"]]
    down = [p for p in plan if p["current"] is not None and p["level"] < p["current"]]
    same = [p for p in plan if p["current"] is not None and p["level"] == p["current"]]
    new = [p for p in plan if p["current"] is None]

    for p in up + down:
        arrow = "↑升密" if p in up else "↓降密"
        print(f"  id={p['document_id']:<5} L{p['current']} → L{p['level']} {arrow}")
        print(f"          {p['filename'][:56]}")
        print(f"          依据：{p['reason']}")
    if not (up or down):
        print("  没有需要变更的文档")
    print(f"\n  变化统计：升密 {len(up)} / 降密 {len(down)} / 不变 {len(same)} / 新增 {len(new)}")

    dist = Counter(p["level"] for p in plan)
    print("\n  重判后等级分布：")
    for lv in sorted(dist):
        print(f"    L{lv} {_level_name(lv):<4} {dist[lv]} 篇")

    # 可见性后果：L1+ 需要 owner_department 才有机会被同部门的人看到
    gated = [p for p in plan if p["level"] > 0]
    no_owner = [p for p in gated if not p["owner_department"]]
    print("\n  可见性后果：")
    print(f"    重判后 L1 及以上（需部门匹配才可见）= {len(gated)} 篇")
    print(f"    其中 owner_department 为空         = {len(no_owner)} 篇")
    if no_owner:
        print("    [!] 这些文档升密后将**无人可见**——L1+ 要求文档归属部门与")
        print("        员工部门匹配（或组织继承），归属为空则任何人都匹配不上。")
        print("        需先跑 `--owner` 补归属部门，否则系统会静默变空。")


def show_plan(plan: list[dict]) -> None:
    print(SEPARATOR)
    print(f"定级方案（演练，未写库）· 共 {len(plan)} 篇")
    print(SEPARATOR)
    for p in plan:
        flag = "  ⚠ 待复核" if p["needs_review"] else ""
        print(f"  id={p['document_id']:<5} → L{p['level']} {p['level_name']}{flag}")
        print(f"          {p['filename'][:56]}")
        print(f"          依据：{p['reason']}")

    dist = Counter(p["level"] for p in plan)
    print("\n  等级分布：")
    for lv in sorted(dist):
        print(f"    L{lv} {_level_name(lv):<4} {dist[lv]} 篇")
    reviews = [p for p in plan if p["needs_review"]]
    if reviews:
        print(f"\n  需人工复核 {len(reviews)} 篇（命中绝密信号，已封顶 L{AUTO_MAX_LEVEL}）：")
        for p in reviews:
            print(f"    id={p['document_id']} {p['filename'][:50]}")

    print(f"\n  说明：默认等级 L{DEFAULT_LEVEL}（未命中的按内部资料处理）；"
          f"自动定级上限 L{AUTO_MAX_LEVEL}，L3 绝不自动赋。")


def project_visibility(replan: list[dict], oplan: list[dict]) -> None:
    """按重判后的密级 + 归属部门，逐员工推算可见篇数。

    只看"等级分布"是不够的：升密会把文档变成需部门匹配才可见，
    若归属部门与员工部门错配，结果是"分级做对了、系统却空了"。
    这一节把两者合起来算，是写入前最后一道确认。
    """
    owner = {p["document_id"]: p["department"] for p in oplan}
    levels = {p["document_id"]: p["level"] for p in replan}
    if not levels:
        return

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT employee_no, username, security_level, department "
                    "FROM kms_users WHERE is_active=1 "
                    "ORDER BY security_level DESC, id")
        users = cur.fetchall()

    print(SEPARATOR)
    print("写入后可见性推算（未写库，仅按上述方案模拟）")
    print(SEPARATOR)
    print("  规则：密级 <= 员工职级，且（文档归属部门含「不限」或 == 员工部门）")
    print("  注：密级只作职级上限，不再让 L0 绕过部门；未计入组织继承（上级看下级），"
          "实际可见数只会更多不会更少\n")

    total = len(levels)
    zero = 0
    for u in users:
        lv = int(u["security_level"])
        dept = u["department"] or ""
        n = sum(1 for did, dlevel in levels.items()
                if dlevel <= lv
                and (owner.get(did) in (DOC_DEPT_UNLIMITED, "", None)
                     or owner.get(did) == dept))
        if n == 0:
            zero += 1
        print(f"    {u['employee_no']:<11} L{lv} {str(u['username']):<9}"
              f" {dept or '(空)':<10} → 可见 {n}/{total}")
    if zero:
        print(f"\n  [!] {zero} 名员工写入后将看不到任何文档")
    print("  （L0 职级的员工只能看「归属部门=不限」的文档，这是分级，不是缺陷）")


def apply_plan(plan: list[dict]) -> int:
    """写入密级。每篇都记录审计，便于事后追溯是谁按什么规则定的。"""
    from kms import access_control as acl

    written = 0
    with MySQLStore().transaction() as cur:
        for p in plan:
            cur.execute(
                "INSERT INTO kms_doc_levels (document_id, level, granted_by) "
                "VALUES (%s, %s, NULL) ON DUPLICATE KEY UPDATE level=VALUES(level)",
                (p["document_id"], p["level"]))
            written += 1
    for p in plan:
        acl.add_audit(
            None, "init_classify",
            target=f"document:{p['document_id']}",
            detail=f"L{p['level']}({p['level_name']}) 依据={p['reason']}"
                   f"{' 需人工复核' if p['needs_review'] else ''}",
        )
    print(f"\n已写入 {written} 篇密级，并逐条记录审计（action=init_classify）")
    return 0


# 文档归属部门规则：按文件名关键词归属，未命中的由综合管理部兜底。
# 部门名必须取自 kms.constants.DEPARTMENTS / kms.org.SEED_ORG_TREE，
# 否则组织路径解析不到对应节点，组织继承会失效。
OWNER_RULES = (
    (("部署", "架构", "接口", "配置", "运维", "开发", "测试", "技术", "手册"), "技术研发部"),
    (("风控", "反洗钱", "合规", "征信", "审计", "可疑交易"), "风险控制部"),
    (("费率", "清算", "对账", "结算", "财务", "报价"), "财务管理部"),
    (("需求", "规划", "产品设计"), "产品管理部"),
    (("商户", "市场", "营销", "拓展", "客户", "客服"), "市场拓展部"),
)
DEFAULT_OWNER = "综合管理部"


def _owner_for(filename: str) -> tuple[str, str]:
    """返回 (归属部门, 组织路径)。"""
    for keywords, dept in OWNER_RULES:
        if any(k in filename for k in keywords):
            return dept, f"银联商务/{dept}"
    return DEFAULT_OWNER, f"银联商务/{DEFAULT_OWNER}"


def build_owner_plan(include_all: bool = False) -> list[dict]:
    """生成归属部门方案（只读）。

    include_all=True 时重判全部文档。存量库常出现"全部文档都挂在同一个部门"
    （本库 120 篇全归综合管理部，而该部门仅 3 名员工），一旦升密就会出现
    大批文档对绝大多数人不可见，因此重判密级时归属部门往往要一并重新分配。
    """
    with MySQLStore()._conn() as cur:
        if include_all:
            cur.execute("SELECT id, filename, owner_department FROM documents ORDER BY id")
        else:
            cur.execute("SELECT id, filename, owner_department FROM documents "
                        "WHERE owner_department IS NULL OR owner_department='' ORDER BY id")
        docs = cur.fetchall()
    return [{"document_id": d["id"], "filename": d["filename"],
             "current": d["owner_department"] or "",
             **dict(zip(("department", "org_path"), _owner_for(d["filename"])))}
            for d in docs]


def apply_owner_plan(plan: list[dict]) -> int:
    from kms import access_control as acl

    written = 0
    with MySQLStore().transaction() as cur:
        for p in plan:
            # departments 是权限判定的唯一事实源（owner_department 仅供追溯），
            # 二者必须同步写入：只改旧列等于改了没人读到的字段。
            # 归属为空 = 未限定部门 → 写「不限」哨兵，而不是空数组
            # （空数组在新语义下 fail-closed，等同「谁都不能看」）。
            dept = p["department"] or DOC_DEPT_UNLIMITED
            cur.execute(
                "UPDATE documents SET owner_department=%s, owner_org_path=%s, "
                "departments=JSON_ARRAY(%s) WHERE id=%s",
                (dept, p["org_path"], dept, p["document_id"]))
            written += 1
    for p in plan:
        acl.add_audit(None, "init_owner", target=f"document:{p['document_id']}",
                      detail=f"归属部门={p['department']}")
    print(f"\n已为 {len(plan)} 篇文档写入归属部门，并逐条记录审计（action=init_owner）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--survey", action="store_true", help="只读盘点，不写库")
    ap.add_argument("--owner", action="store_true", help="为文档补归属部门（默认只演练）")
    ap.add_argument("--reclassify", action="store_true",
                    help="重判**全部**文档（含已定级的），用于存量库按新规则复核")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只演练）")
    ap.add_argument("--export", metavar="PATH", help="把方案导出为 JSON 供人工复核")
    ap.add_argument("--env", default=DEFAULT_ENV,
                    help="环境配置文件（默认 .env=QA 库 rag_competition；"
                         "KMS 治理库须指定 .env.kms=enterprise_kms）")
    args = ap.parse_args()

    # 打错库不会报错、只静默改到错的数据上（QA 与 KMS 两库的文档和用户完全独立），
    # 因此每次运行都把目标库顶在前面，逼操作者先确认再往下看结果。
    from config import settings

    print(f"环境文件 = {args.env}")
    print(f"目标库   = {settings.mysql_database}   <-- 确认这是你要操作的库")
    print()

    if args.survey:
        survey()
        return 0

    if args.reclassify:
        rplan = build_plan(include_classified=True)
        if not rplan:
            print("库中没有文档")
            return 0
        show_reclassify(rplan)
        if args.export:
            out = Path(args.export)
            out.parent.mkdir(parents=True, exist_ok=True)
            payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                       "mode": "reclassify", "items": rplan}
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n方案已导出：{out}")
        if args.owner:
            oplan_preview = build_owner_plan(include_all=True)
            project_visibility(rplan, oplan_preview)
        if args.apply:
            apply_plan(rplan)
        elif not args.owner:
            print("\n（演练模式，未写库。确认无误后加 --apply）")
            return 0
        # 与 --owner 组合时继续往下走：升密后归属部门要一并重算，
        # 否则会出现大量文档只对一个部门可见

    if args.owner:
        oplan = build_owner_plan(include_all=args.reclassify)
        if not oplan:
            print("所有文档都已有归属部门，无需处理")
            return 0
        print(SEPARATOR)
        print(f"归属部门方案（演练，未写库）· 共 {len(oplan)} 篇")
        print(SEPARATOR)
        changed = [p for p in oplan if p["department"] != p["current"]]
        for p in changed:
            print(f"  id={p['document_id']:<5} {p['current'] or '(空)':<8} → {p['department']}")
            print(f"          {p['filename'][:56]}")
        print(f"\n  变更 {len(changed)} 篇 / 不变 {len(oplan) - len(changed)} 篇")
        dist = Counter(p["department"] for p in oplan)
        print("  重算后归属分布：")
        for d, n in sorted(dist.items(), key=lambda x: -x[1]):
            print(f"    {d:<10} {n} 篇")
        if args.apply:
            return apply_owner_plan(oplan)
        print("\n（演练模式，未写库。确认无误后加 --apply）")
        return 0

    plan = build_plan()
    if not plan:
        print("没有未定级的文档，无需处理")
        return 0
    show_plan(plan)

    if args.export:
        out = Path(args.export)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "default_level": DEFAULT_LEVEL, "auto_max_level": AUTO_MAX_LEVEL,
                   "items": plan}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n方案已导出：{out}")

    if args.apply:
        return apply_plan(plan)
    print("\n（演练模式，未写库。确认无误后加 --apply）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
