"""知识文档管理系统 (Knowledge Management System) 模块。

独立于 app/ 的 RAG 问答核心，提供文档全生命周期管理、权限治理、两段式工单。
参考 IBM/企业 KMS 最佳实践设计。

架构（精简后，活跃模块）
---------------------------
1. constants.py    公共常量定义
2. security.py     认证/授权/JWT/密码学
3. access_control.py BLP 模型 + 部门规则 + 员工管理 + 审计日志 + 工单表
4. routes.py       文档管理/检索/问答入口（被 gateway/routes_kms.py 调用）
5. admin_routes.py 管理端 API 路由（认证/用户/层级/审计）
6. apps.py         第三方应用 API Key 鉴权
7. hr_sync.py      HR 数据镜像同步

权限模型
--------
- 单一主体：员工（一人一工号）
- 权限 = 安全职级 L0-L3 + 所属部门（HR 单向同步，本系统零维护）
- BLP 强制访问控制：读=文档密级 <= 员工职级；写=文档密级 >= 员工职级
- 部门约束：文档默认仅本部门可见，可额外开放部门（不突破 BLP）

治理流程
--------
- 两段式工单：A 申请（编辑人上传草稿/发变更）→ B 审批即执行
- 审批人自动匹配：同部门、BLP 可读、在职
- 同一 doc_id 同一时刻仅一条在途工单（kms_policy_requests 表互斥）
"""

# 导出核心常量和接口
from .constants import (
    ROLE_EMPLOYEE,
    SECURITY_LEVELS,
    SECURITY_LEVEL_PUBLIC,
    SECURITY_LEVEL_SECRET,
    SECURITY_LEVEL_CONFIDENTIAL,
    SECURITY_LEVEL_TOPSECRET,
    PUBLIC_LEVEL,
    PERM_ALLOW,
    PERM_DENY,
    PERM_REQUIRE_TICKET,
)

# 显式声明再导出边界：既让 lint 识别这些名字是公共 API 而非未使用导入，
# 也防止 `from kms import *` 意外波及同名的内部符号。
__all__ = [
    "ROLE_EMPLOYEE",
    "SECURITY_LEVELS",
    "SECURITY_LEVEL_PUBLIC",
    "SECURITY_LEVEL_SECRET",
    "SECURITY_LEVEL_CONFIDENTIAL",
    "SECURITY_LEVEL_TOPSECRET",
    "PUBLIC_LEVEL",
    "PERM_ALLOW",
    "PERM_DENY",
    "PERM_REQUIRE_TICKET",
]
