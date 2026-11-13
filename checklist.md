# Checklist：OIDC/LDAP 适配器 + 权限隔离定向推荐（KMS 增量）

> 验收核对清单，逐项对照 `spec.md` 与 `tasks.md`。全部勾选后交付。

- [x] 配置项与校验齐全且默认零配置可跑
  （`config.py` 新增目录源/LDAP/OIDC/推荐全部 env + `validate_ports()` 枚举/必填/权重校验；默认 `seed`+`builtin` 启动成功）
- [x] 目录适配器可插拔（seed/ldap/ad）且缺 `ldap3` 明确报错
  （`kms/directory.py`：`build_directory_adapter` 分发；`LdapDirectoryAdapter._connect` 惰性 import，缺失抛 `RuntimeError`）
- [x] 统一登录可插拔（builtin/external）且 `/sso/exchange` 仅 external 生效
  （`kms/oidc_provider.py` + `kms/oidc.py` L328 `/exchange`；builtin 下实测返回 400）
- [x] 推荐四路策略融合且逐条经 `service.allowed()` 硬过滤
  （`kms/recommend.py` L350 `service.allowed(row, user, 0, user.security_level)`）
- [x] 业务埋点（chat_source/view/feedback）落库且失败不影响主业务
  （`gateway/routes_kms.py` `_recommend_call` 容错包装；实测推荐含 `collaborative` 命中，证明交互已落库）
- [x] 启动装配（`run_kms.py`）加载目录/推荐表与推荐路由
  （日志输出 `adapter=simulated-seed 节点=19`）
- [x] 离线回归全绿（`tests/test_enterprise.py` 37 + `tests/test_directory_recommend.py` 15）
  （`unittest discover -s tests` → `Ran 52 tests ... OK`）
- [x] 端到端冒烟（仅 6342）：readyz/login/me(组织字段)/documents/chat/document/recommendations 均正常
  （readyz 200；me 含 `org_path/org_node_id/manager_employee_no`；chat 200 带 `message_id`；document 200；recommendations 200 带 `reasons`）
- [x] 越权校验：低职级账号推荐不返回无权文档
  （20260001 level=1 → `/recommendations` 返回 `items: []`）
- [x] SSO 回归：`authorize` 302、`exchange`（builtin）400
- [x] `6341` 赛题问答服务代码（`app/`）零改动
- [x] 文档与示例凭据更新，凭据仅经 `.env` 注入
  （`docs/gateway_architecture.md`、`docs/enterprise_delivery.md`、`.env.kms.example`；口令/密钥仅留空占位）
