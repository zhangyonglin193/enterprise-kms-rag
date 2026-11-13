# Tasks：文档版本管理

> 依赖：`spec_versioning.md` 已批准。

## 阶段 1：数据模型与核心模块

- [ ] T1. 创建 `kms/versioning.py`：`ensure_version_tables()`（建表 + 加列 + 回填）
- [ ] T2. 实现 `record_version(cur, ...)` — 事务内写新版本、置 is_current
- [ ] T3. 实现 `list_versions(doc_id)` / `get_current_version(doc_id)`
- [ ] T4. 实现 `rollback_to_version(doc_id, version_no, operator)` — 含源文件存在性校验、重新 ingest、留痕

## 阶段 2：上传链路改造

- [ ] T5. `app/rag.py`：`ingest(force=False)` 参数，force=True 跳过 content_hash 查重
- [ ] T6. `gateway/routes_upload.py`：`_ingest_one` 同文件名走 `_ingest_new_version`
- [ ] T7. `_ingest_new_version`：归档旧 chunks/向量、覆盖 documents 行、迁移 chunks、record_version、递增版本号
- [ ] T8. 事务提交后调用 `_post_commit_cleanup_faiss(old_faiss_ids)`

## 阶段 3：API 与权限

- [ ] T9. `gateway/routes_kms.py`：`GET /documents/{id}/versions`（可读权限校验）
- [ ] T10. `gateway/routes_kms.py`：`POST /documents/{id}/versions/{no}/rollback`（管理权限校验 + 审计）
- [ ] T11. `gateway/service.py`：documents 列表 SELECT 增加 `current_version_no`

## 阶段 4：前端

- [ ] T12. 文档列表显示版本徽标 `vN`
- [ ] T13. 「版本历史」按钮 + 弹窗（倒序列表、当前标记、回滚按钮）
- [ ] T14. 回滚二次确认 + 成功后刷新

## 阶段 5：测试与验证

- [ ] T15. 新增 `tests/test_versioning.py`：record_version 原子性、list_versions 倒序、rollback 校验、ingest force 参数
- [ ] T16. 全量回归 `python -m unittest discover tests -v` 全绿
- [ ] T17. 端到端冒烟（上传新版本 → 版本号递增 → 回滚 → 向量清理）
