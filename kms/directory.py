"""组织目录适配器 —— 可插拔的 LDAP / AD / 内置种子目录源。

设计目标
--------
参照 IBM 等企业 KMS，人员与组织主数据来自企业目录服务（LDAP/AD）。
本模块把「取组织节点 + 取员工」抽象为标准 DirectoryAdapter 接口：

- SimulatedDirectoryAdapter  内置种子 / 可配置 JSON（本地演示、离线评测）
- LdapDirectoryAdapter       LDAP 标准目录与微软 AD（惰性依赖 ldap3）

通过环境变量 KMS_DIRECTORY_SOURCE（seed|ldap|ad）选择实现，业务代码不感知具体目录源。
KMS 仍不维护人员主数据：同步结果先落 kms_org_nodes，再经 hr_sync.sync_employees 单向写入
kms_users（只读镜像），最后由 org.backfill_user_orgs 回填组织路径。

安全约定
--------
- 只读绑定账号，凭据仅经 .env 注入，绝不硬编码；
- 未安装 ldap3 时给出明确报错，不静默降级；
- ldap/ad 模式下配置缺失由 config.validate_ports() 在启动阶段拦截。
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import List, Optional

from app.logger import get_logger
from config import settings

logger = get_logger("kms.directory")


# ===================== 抽象接口 =====================
class DirectoryAdapter(ABC):
    """目录适配器标准接口：组织节点 + 员工条目。"""

    name: str = "adapter"
    source_type: str = "seed"

    @abstractmethod
    def fetch_org_nodes(self) -> List[dict]:
        """返回组织节点列表 [{code,name,parent_code,org_type,manager_employee_no}]。"""

    @abstractmethod
    def fetch_employees(self) -> List["object"]:
        """返回 HREmployeeData 列表（无员工数据时返回空列表）。"""

    def health(self) -> dict:
        """适配器健康信息（供启动日志 / 运维探活）。"""
        return {"ok": True, "adapter": self.name, "source_type": self.source_type, "detail": ""}


# ===================== 模拟适配器（种子 / JSON） =====================
class SimulatedDirectoryAdapter(DirectoryAdapter):
    """本地演示 / 离线评测用：组织节点取自内置种子或 KMS_LDAP_SEED_JSON。

    - 未配置 KMS_LDAP_SEED_JSON：组织节点取 kms.org.SEED_ORG_TREE，员工为空
      （员工由 scripts/seed_employees.py 负责播种）。
    - 配置了 JSON：优先取该文件的 org_nodes / employees（模拟真实目录返回）。
    """

    def __init__(self, source_type: str = "seed"):
        self.source_type = source_type
        self._json_path = settings.kms_ldap_seed_json
        self._json: Optional[dict] = None
        if self._json_path and os.path.exists(self._json_path):
            try:
                with open(self._json_path, encoding="utf-8") as f:
                    self._json = json.load(f)
                self.name = "simulated-json"
            except Exception as e:
                logger.warning(f"LDAP 模拟 JSON 解析失败，回退内置种子: {e}")
                self._json = None
                self.name = "simulated-seed"
        else:
            self.name = "simulated-seed"

    def fetch_org_nodes(self) -> List[dict]:
        if self._json and isinstance(self._json.get("org_nodes"), list):
            return [self._normalize_node(n) for n in self._json["org_nodes"]]
        from .org import SEED_ORG_TREE
        return [dict(n) for n in SEED_ORG_TREE]

    def fetch_employees(self) -> List["object"]:
        if not self._json or not isinstance(self._json.get("employees"), list):
            return []
        from .hr_sync import parse_csv_employees
        return parse_csv_employees(self._json["employees"])

    def health(self) -> dict:
        return dict(super().health(), detail=f"json={self._json_path or '(内置种子)'}")

    @staticmethod
    def _normalize_node(node: dict) -> dict:
        """兼容常见目录字段命名，统一为 code/name/parent_code/org_type/manager_employee_no。"""
        return {
            "code": node.get("code") or node.get("ou") or node.get("cn") or "",
            "name": node.get("name") or node.get("ou") or node.get("cn") or node.get("code") or "",
            "parent_code": node.get("parent_code") or node.get("parent") or None,
            "org_type": node.get("org_type") or "department",
            "manager_employee_no": node.get("manager_employee_no") or node.get("manager"),
        }


# ===================== LDAP / AD 适配器 =====================
class LdapDirectoryAdapter(DirectoryAdapter):
    """标准 LDAP 目录 / 微软 AD 适配器（惰性依赖 ldap3）。

    生产环境用只读绑定账号连接（AD 推荐 LDAPS 636）。属性映射可通过
    KMS_LDAP_*_ATTR 配置覆盖，以适配各企业目录 Schema 差异。
    """

    def __init__(self, source_type: str = "ldap"):
        if source_type not in ("ldap", "ad"):
            raise ValueError("LdapDirectoryAdapter 仅支持 ldap / ad")
        self.source_type = source_type
        self.name = source_type

    # ---- 连接与查询 ----
    def _connect(self):
        """建立只读绑定连接；未安装 ldap3 时明确报错。"""
        try:
            from ldap3 import ALL, Connection, Server
        except Exception as exc:  # pragma: no cover - 依赖缺失分支
            raise RuntimeError("LDAP 适配器需要 ldap3，请 pip install ldap3 后重试") from exc

        server = Server(settings.kms_ldap_uri, get_info=ALL, connect_timeout=settings.kms_ldap_timeout)
        conn = Connection(
            server,
            user=settings.kms_ldap_bind_dn,
            password=settings.kms_ldap_bind_password,
            auto_bind=True,
            receive_timeout=settings.kms_ldap_timeout,
        )
        return conn

    def _search(self, conn, ldap_filter: str, attributes: List[str]) -> List[dict]:
        ok = conn.search(settings.kms_ldap_base_dn, ldap_filter,
                         attributes=attributes, paged_size=500)
        if not ok:
            logger.warning(f"LDAP 查询失败: filter={ldap_filter} result={conn.result}")
            return []
        entries = []
        for entry in conn.entries:
            row, dn = {}, str(entry.entry_dn)
            for attr in attributes:
                value = entry[attr].value if attr in entry else None
                row[attr] = value[0] if isinstance(value, (list, tuple)) and value else value
            row["_dn"] = dn
            entries.append(row)
        return entries

    # ---- 组织节点 ----
    def fetch_org_nodes(self) -> List[dict]:
        conn = self._connect()
        try:
            attrs = ["ou", "name", "description"]
            entries = self._search(conn, settings.kms_ldap_org_filter, attrs)
        finally:
            try:
                conn.unbind()
            except Exception:
                pass

        nodes = []
        for row in entries:
            dn = row.get("_dn", "")
            is_root = dn.strip().lower() == settings.kms_ldap_base_dn.strip().lower()
            code = (row.get("ou") or row.get("name") or ("root" if is_root else ""))
            parent_code = None if is_root else self._parent_ou(dn)
            nodes.append({
                "code": str(code),
                "name": str(row.get("name") or row.get("ou") or code),
                "parent_code": parent_code,
                "org_type": "department",
                "manager_employee_no": None,
            })
        nodes.sort(key=lambda n: n["code"])
        return nodes

    # ---- 员工 ----
    def fetch_employees(self) -> List["object"]:
        from .hr_sync import HREmployeeData

        attrs = [settings.kms_ldap_employee_no_attr, settings.kms_ldap_name_attr,
                 settings.kms_ldap_dept_attr, settings.kms_ldap_title_attr,
                 settings.kms_ldap_level_attr]
        attrs = list(dict.fromkeys(a for a in attrs if a))
        conn = self._connect()
        try:
            entries = self._search(conn, settings.kms_ldap_employee_filter, attrs)
        finally:
            try:
                conn.unbind()
            except Exception:
                pass

        employees = []
        for row in entries:
            emp_no = row.get(settings.kms_ldap_employee_no_attr)
            if not emp_no:
                continue
            employees.append(HREmployeeData(
                employee_no=str(emp_no).strip(),
                username=str(row.get(settings.kms_ldap_name_attr) or emp_no),
                department=str(row.get(settings.kms_ldap_dept_attr) or ""),
                business_title=str(row.get(settings.kms_ldap_title_attr) or ""),
                security_level=self._parse_level(row.get(settings.kms_ldap_level_attr)),
                is_active=True,
                hr_employee_id=str(emp_no).strip(),
            ))
        employees.sort(key=lambda e: e.employee_no)
        return employees

    def health(self) -> dict:
        detail = f"uri={settings.kms_ldap_uri} base={settings.kms_ldap_base_dn}"
        try:
            conn = self._connect()
            conn.unbind()
            return {"ok": True, "adapter": self.name, "source_type": self.source_type, "detail": detail}
        except Exception as e:
            return {"ok": False, "adapter": self.name, "source_type": self.source_type, "detail": f"{detail} err={e}"}

    # ---- 辅助 ----
    @staticmethod
    def _parent_ou(dn: str) -> Optional[str]:
        """从 DN 推导父 OU 的 code（父层第一个 RDN 的 ou/cn 值）。"""
        parts = [p.strip() for p in dn.split(",")]
        if len(parts) <= 1:
            return None
        first = parts[1]
        if "=" in first:
            return first.split("=", 1)[1]
        return first or None

    @staticmethod
    def _parse_level(value) -> int:
        """将目录中的密级标记解析为 L0–L3；非法值回退 0。"""
        if value is None:
            return 0
        text = str(value).strip()
        for token in ("0", "1", "2", "3"):
            if text.endswith(token) or text == token:
                return int(token)
        return 0


# ===================== HR API 适配器（模拟外部 HR 系统） =====================
class HrApiDirectoryAdapter(DirectoryAdapter):
    """从外部 HR 系统的 HTTP API **拉取**组织与员工（只读，不推送）。

    与「客户端自报人事数据」的根本区别：KMS 是 Pull 方，凭据只来自 `.env`，
    客户端无法经业务接口写入人事主数据——尤其是安全职级。这也是
    `POST /admin/hr-sync` 始终不注册的原因。

    依赖 httpx（惰性导入，与 LdapDirectoryAdapter 的 ldap3 同策略），
    避免仅为接 HR 而给全体部署引入硬依赖。

    约定端点（KMS_HR_API_BASE 可指向任意基址）：
        GET {base}/health      → 存活探测
        GET {base}/org/nodes   → {"org_nodes": [...]}
        GET {base}/employees   → {"employees": [...]}
    均支持 Bearer Token（KMS_HR_API_TOKEN）。
    """

    def __init__(self, source_type: str = "hr_api"):
        self.source_type = source_type
        self.name = "hr-api"
        self._base = (settings.kms_hr_api_base or "").rstrip("/")
        self._token = settings.kms_hr_api_token or ""
        self._timeout = settings.kms_hr_api_timeout

    def _get(self, path: str) -> dict:
        import httpx
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self._base}{path}", headers=headers)
            resp.raise_for_status()
            return resp.json()

    def fetch_org_nodes(self) -> List[dict]:
        data = self._get("/org/nodes")
        return [self._normalize_node(n) for n in (data.get("org_nodes") or [])]

    def fetch_employees(self) -> List["object"]:
        from .hr_sync import parse_csv_employees
        data = self._get("/employees")
        return parse_csv_employees(data.get("employees") or [])

    def health(self) -> dict:
        base = super().health()
        if not self._base:
            return dict(base, ok=False, detail="未配置 KMS_HR_API_BASE")
        try:
            self._get("/health")
            return dict(base, ok=True, detail=f"base={self._base}")
        except Exception as e:
            return dict(base, ok=False, detail=f"base={self._base} err={e}")

    @staticmethod
    def _normalize_node(node: dict) -> dict:
        """与 SimulatedDirectoryAdapter 保持同一套字段兼容规则。"""
        return {
            "code": node.get("code") or node.get("ou") or node.get("cn") or "",
            "name": node.get("name") or node.get("ou") or node.get("cn")
                    or node.get("code") or "",
            "parent_code": node.get("parent_code") or node.get("parent") or None,
            "org_type": node.get("org_type") or "department",
            "manager_employee_no": node.get("manager_employee_no") or node.get("manager"),
        }


# ===================== 工厂与同步入口 =====================
def build_directory_adapter(source: Optional[str] = None) -> DirectoryAdapter:
    """依 KMS_DIRECTORY_SOURCE（或显式 source）构造目录适配器。"""
    source = (source or settings.kms_directory_source or "seed").strip().lower()
    if source == "seed":
        return SimulatedDirectoryAdapter("seed")
    if source in ("ldap", "ad"):
        return LdapDirectoryAdapter(source)
    if source in ("hr_api", "hr"):
        return HrApiDirectoryAdapter(source)
    raise ValueError(f"未知目录源: {source}（仅支持 seed/ldap/ad/hr_api）")


def sync_directory(adapter: Optional[DirectoryAdapter] = None,
                   triggered_by: Optional[int] = None) -> dict:
    """执行一次目录同步：组织节点 upsert → 员工同步 → 员工组织回填。

    Returns:
        {"adapter","source_type","org_nodes","employees","org_backfilled"}
    """
    from . import hr_sync, org

    adapter = adapter or build_directory_adapter()
    nodes = adapter.fetch_org_nodes()
    node_count = org.upsert_org_nodes(nodes) if nodes else 0

    employees = adapter.fetch_employees() or []
    emp_result = None
    if employees:
        emp_result = hr_sync.sync_employees(
            employees, source_type=adapter.source_type, sync_type="full", triggered_by=triggered_by,
        )

    backfilled = org.backfill_user_orgs()
    logger.info(
        f"目录同步完成: adapter={adapter.name} source_type={adapter.source_type} "
        f"org_nodes={node_count} employees={len(employees)} org_backfilled={backfilled}"
    )
    return {
        "adapter": adapter.name,
        "source_type": adapter.source_type,
        "org_nodes": node_count,
        "employees": emp_result,
        "org_backfilled": backfilled,
    }
