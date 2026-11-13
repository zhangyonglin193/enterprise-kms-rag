"""组织架构目录服务 —— 组织树 + LDAP 模拟同步 + 层级权限辅助。

新增数据模型
------------
kms_org_nodes          组织树节点表（parent_id 树结构 + org_path 路径）
kms_users 扩展         org_node_id / org_path / manager_employee_no

核心能力
--------
1. upsert_org_nodes()    通用组织节点 upsert（含 parent_id/org_path/org_level 重算）
2. seed_org_tree()       初始化银联商务完整组织树（内置种子）
3. backfill_user_orgs()  目录同步后批量回填 kms_users 组织字段
4. get_descendants_path() 祖先节点 → 所有下级路径（上级部门自动可见下级文档）

可插拔目录源
------------
真实目录同步（LDAP/AD）由 kms.directory 的适配器负责，本模块只提供组织树落库
与查询辅助。sync_from_seed_or_ldap() 保留为兼容入口，委托 directory.sync_directory()。
"""
from __future__ import annotations

from typing import List, Optional, Set, Tuple

from app.logger import get_logger
from app.store import MySQLStore

logger = get_logger("kms.org")


# ===================== DDL =====================
ORG_DDL = """CREATE TABLE IF NOT EXISTS kms_org_nodes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE COMMENT '节点唯一编码（部门简写/OU）',
    name VARCHAR(128) NOT NULL COMMENT '部门/团队全称',
    parent_id INT NULL COMMENT '父节点（根为 NULL）',
    org_path VARCHAR(512) NOT NULL DEFAULT '' COMMENT '完整路径 用 / 分隔',
    org_level TINYINT NOT NULL DEFAULT 0 COMMENT '层级深度（0 = 根）',
    manager_employee_no VARCHAR(32) NULL COMMENT '部门负责人工号',
    org_type VARCHAR(16) NOT NULL DEFAULT 'department' COMMENT 'department/team/group',
    is_active TINYINT NOT NULL DEFAULT 1,
    extra JSON NULL COMMENT '扩展属性',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_parent (parent_id),
    INDEX idx_path (org_path(191)),
    INDEX idx_level (org_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='组织架构节点树';"""

USER_ORG_COLUMNS = [
    ("org_node_id", "INT NULL COMMENT '组织节点 ID'"),
    ("org_path", "VARCHAR(512) NOT NULL DEFAULT '' COMMENT '完整组织路径'"),
    ("manager_employee_no", "VARCHAR(32) NULL COMMENT '直属上级工号'"),
]


# ===================== Seed 组织数据 =====================
# 银联商务组织架构（三级：公司 → 部门 → 科室/团队）
# 与 constants.DEPARTMENTS 对齐，每个部门下加 2-3 个科/组
SEED_ORG_TREE = [
    # 根
    {"code": "root", "name": "银联商务", "parent_code": None, "org_type": "company",
     "manager_employee_no": None},

    # 一级部门
    {"code": "risk", "name": "风险控制部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": "20260019"},
    {"code": "tech", "name": "技术研发部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},
    {"code": "product", "name": "产品管理部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},
    {"code": "market", "name": "市场拓展部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},
    {"code": "ops", "name": "运营支撑部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},
    {"code": "finance", "name": "财务管理部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},
    {"code": "hr", "name": "人力资源部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},
    {"code": "admin", "name": "综合管理部", "parent_code": "root", "org_type": "department",
     "manager_employee_no": None},

    # 风险控制部 —— 3 个科
    {"code": "risk_strategy", "name": "风控策略组", "parent_code": "risk", "org_type": "team",
     "manager_employee_no": "20260029"},
    {"code": "risk_data", "name": "风控数据组", "parent_code": "risk", "org_type": "team",
     "manager_employee_no": None},
    {"code": "risk_audit", "name": "风控审查组", "parent_code": "risk", "org_type": "team",
     "manager_employee_no": "20260030"},

    # 技术研发部 —— 3 个科
    {"code": "tech_backend", "name": "后端研发组", "parent_code": "tech", "org_type": "team",
     "manager_employee_no": None},
    {"code": "tech_frontend", "name": "前端研发组", "parent_code": "tech", "org_type": "team",
     "manager_employee_no": None},
    {"code": "tech_qa", "name": "测试质量组", "parent_code": "tech", "org_type": "team",
     "manager_employee_no": None},

    # 产品管理部 —— 2 个科
    {"code": "product_design", "name": "产品设计组", "parent_code": "product", "org_type": "team"},
    {"code": "product_plan", "name": "产品规划组", "parent_code": "product", "org_type": "team"},

    # 市场拓展部
    {"code": "market_mob", "name": "移动支付组", "parent_code": "market", "org_type": "team"},
    {"code": "market_b2b", "name": "商户服务组", "parent_code": "market", "org_type": "team"},
]


# ===================== 建表与扩展 =====================
def ensure_org_tables() -> bool:
    """幂等建表 + kms_users 加 org 列。"""
    mysql = MySQLStore()
    ok = True
    try:
        with mysql._conn() as cur:
            cur.execute(ORG_DDL)
    except Exception as e:
        logger.error(f"组织表建表失败: {e}")
        ok = False

    for col, dfn in USER_ORG_COLUMNS:
        try:
            with mysql._conn() as cur:
                cur.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='kms_users' AND COLUMN_NAME=%s",
                    (col,),
                )
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE kms_users ADD COLUMN {col} {dfn}")
        except Exception as e:
            logger.warning(f"kms_users 扩展列 {col} 跳过: {e}")
    return ok


# ===================== 种子数据 =====================
def compute_org_paths(nodes: list[dict]) -> dict:
    """由 nodes（含 code/parent_code/name）推导每个节点的 (org_path, org_level, parent_code)。

    纯函数，便于单测；循环父指针有 visited 保护。
    """
    names = {n["code"]: n.get("name", n["code"]) for n in nodes}
    reverse_parent = {n["code"]: n.get("parent_code") for n in nodes}
    out: dict[str, Tuple[str, int, Optional[str]]] = {}
    for n in nodes:
        code = n["code"]
        chain: List[str] = []
        cur: Optional[str] = code
        visited = set()
        while cur and cur not in visited:
            visited.add(cur)
            chain.append(names.get(cur, cur))
            cur = reverse_parent.get(cur)
        chain.reverse()
        out[code] = ("/".join(chain), len(chain) - 1, reverse_parent.get(code))
    return out


def upsert_org_nodes(nodes: list[dict]) -> int:
    """按 code upsert 组织节点，并重算 parent_id / org_path / org_level。

    nodes 每个元素形如：
        {"code", "name", "parent_code", "org_type", "manager_employee_no"}
    parent_code 为 None 表示根节点。幂等：已存在的 code 只补字段，不重复插入。
    返回参与本次 upsert 的节点数。
    """
    ensure_org_tables()
    mysql = MySQLStore()

    inserted: dict[str, int] = {}
    for node in nodes:
        with mysql._conn() as cur:
            cur.execute("SELECT id FROM kms_org_nodes WHERE code=%s", (node["code"],))
            row = cur.fetchone()
            if row:
                node_id = int(row["id"])
                inserted[node["code"]] = node_id
                # 已存在：只补写名称/负责人/类型（LDAP 增量同步时这些属性可能变化）
                cur.execute(
                    "UPDATE kms_org_nodes SET name=%s, manager_employee_no=%s, org_type=%s WHERE id=%s",
                    (node["name"], node.get("manager_employee_no"),
                     node.get("org_type", "department"), node_id),
                )
                continue

            cur.execute(
                """INSERT INTO kms_org_nodes (code, name, parent_id, org_path, org_level,
                                                manager_employee_no, org_type)
                   VALUES (%s, %s, NULL, '', 0, %s, %s)""",
                (node["code"], node["name"],
                 node.get("manager_employee_no"), node.get("org_type", "department")),
            )
            inserted[node["code"]] = cur.lastrowid

    paths = compute_org_paths(nodes)

    for code, node_id in inserted.items():
        path, level, parent_code = paths.get(code, ("", 0, None))
        parent_id = inserted.get(parent_code) if parent_code else None
        with mysql._conn() as cur:
            cur.execute(
                "UPDATE kms_org_nodes SET org_path=%s, org_level=%s, parent_id=%s WHERE id=%s",
                (path, level, parent_id, node_id),
            )

    logger.info(f"组织节点 upsert 完成，共 {len(inserted)} 个节点")
    return len(inserted)


def seed_org_tree() -> dict:
    """初始化内置组织树（幂等），返回 {nodes, codes}。"""
    count = upsert_org_nodes(SEED_ORG_TREE)
    return {"nodes": count, "codes": [n["code"] for n in SEED_ORG_TREE]}


# ===================== 查询辅助 =====================
def get_node_by_code(code: str) -> Optional[dict]:
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute("SELECT * FROM kms_org_nodes WHERE code=%s LIMIT 1", (code,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"查组织节点失败: {e}")
        return None


def get_descendants_path(org_path_prefix: str) -> Set[str]:
    """祖先路径 → 包含祖先自身在内的所有下级完整路径集合。

    例 org_path_prefix='银联商务/风险控制部'
    → {'银联商务/风险控制部', '银联商务/风险控制部/风控策略组', '银联商务/风险控制部/风控数据组', ...}
    """
    if not org_path_prefix:
        return set()
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute(
                """SELECT org_path FROM kms_org_nodes
                   WHERE org_path=%s OR org_path LIKE %s""",
                (org_path_prefix, org_path_prefix + "/%"),
            )
            return {row["org_path"] for row in cur.fetchall()}
    except Exception as e:
        logger.error(f"查下级路径失败: {e}")
        return {org_path_prefix}


def user_scope_path(org_path: str, manager_path: Optional[str] = None) -> Set[str]:
    """当前用户可见的组织范围：本级 + 所有下级。"""
    scope = get_descendants_path(org_path)
    return scope


# ===================== 部门名 ↔ org_path 解析 =====================
def org_path_for_department(department_name: str) -> str:
    """从部门名 → 匹配最精确（最短）的组织路径。

    匹配优先级：
    1. org_path = '银联商务/{department_name}'         → 部门级精确
    2. org_path LIKE '银联商务/{department_name}/%'    → 团队级最精确（最短）
    不匹配则返回 ''。
    """
    if not department_name:
        return ""
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            # (org_path = '银联商务/X') OR (org_path LIKE '银联商务/X/%')
            # ORDER BY LENGTH ASC 让精确部门级排在团队级前面
            cur.execute(
                """SELECT org_path FROM kms_org_nodes
                   WHERE org_path = CONCAT('银联商务/', %s)
                      OR org_path LIKE CONCAT('银联商务/', %s, '/%%')
                   ORDER BY LENGTH(org_path) ASC LIMIT 1""",
                (department_name, department_name),
            )
            row = cur.fetchone()
            return row["org_path"] if row else ""
    except Exception as e:
        logger.warning(f"部门→org_path 映射失败: {e}")
        return ""


def resolve_user_org(employee_no: str, department: str, manager_employee_no: str = "") -> dict:
    """把 HR 员工记录里的 department 字符串解析成组织节点 + org_path。"""
    path = org_path_for_department(department)
    node = None
    if path:
        mysql = MySQLStore()
        try:
            with mysql._conn() as cur:
                cur.execute("SELECT id, org_path, org_level, manager_employee_no FROM kms_org_nodes WHERE org_path=%s", (path,))
                row = cur.fetchone()
                if row:
                    node = dict(row)
        except Exception as e:
            logger.warning(f"查组织节点失败 {path}: {e}")

    # 自动从父节点推断 manager（如果员工没带 manager 字段）
    resolved_manager = manager_employee_no or ""
    if node and not resolved_manager:
        mysql = MySQLStore()
        try:
            with mysql._conn() as cur:
                cur.execute(
                    """SELECT n.manager_employee_no FROM kms_org_nodes n
                       WHERE n.id = (SELECT parent_id FROM kms_org_nodes WHERE id=%s)""",
                    (node["id"],),
                )
                row = cur.fetchone()
                resolved_manager = (row["manager_employee_no"] or "").strip() if row else ""
        except Exception:
            pass

    return {
        "org_node_id": node["id"] if node else None,
        "org_path": path,
        "manager_employee_no": resolved_manager,
    }


# ===================== 员工组织回填 =====================
def backfill_user_orgs() -> int:
    """遍历 kms_users，按部门解析并回填 org_node_id / org_path / manager_employee_no。

    目录同步后批量对齐使用，幂等；返回成功回填的员工数。
    """
    mysql = MySQLStore()
    try:
        with mysql._conn() as cur:
            cur.execute("SELECT id, employee_no, department, manager_employee_no FROM kms_users")
            users = cur.fetchall()
    except Exception as e:
        logger.warning(f"读取员工列表失败，跳过组织回填: {e}")
        return 0

    updated = 0
    for u in users:
        resolved = resolve_user_org(
            u["employee_no"], u.get("department") or "", u.get("manager_employee_no") or "",
        )
        if not resolved.get("org_node_id"):
            continue
        try:
            with mysql._conn() as cur:
                cur.execute(
                    "UPDATE kms_users SET org_node_id=%s, org_path=%s, manager_employee_no=%s WHERE id=%s",
                    (resolved["org_node_id"], resolved["org_path"],
                     resolved["manager_employee_no"], int(u["id"])),
                )
            updated += 1
        except Exception as e:
            logger.warning(f"回填组织信息失败 {u['employee_no']}: {e}")
    return updated


# ===================== 同步入口 =====================
def sync_from_seed_or_ldap(source: str = "") -> dict:
    """组织同步入口（向后兼容旧调用），委托 kms.directory.sync_directory()。

    source 为空时读取 settings.kms_directory_source；也可显式传 seed/ldap/ad。
    """
    from .directory import build_directory_adapter, sync_directory

    adapter = build_directory_adapter(source or None)
    result = sync_directory(adapter)
    result["message"] = "组织目录已就绪"
    return result

