# Spec：企业级文档版本管理（KMS 增量）

> 目标读者：实现者与评审人。
> 本文为「决策完备」规格：每项改动给出确切文件、接口签名、验证方式与审批点。

## 1. 目标

参照 IBM/Confluence 等企业 KMS 做法，在现有 KMS（`kms/` + `gateway/`，端口 6342）上补齐**文档版本管理**，解决当前"上传同名文件被拒、内容更新无历史、无法回滚"的核心痛点：

1. **版本元数据留痕**：每次内容变更写入 `kms_doc_versions`，记录 content_hash / chunk_count / 上传人 / 时间 / 变更摘要 / 是否当前版本。
2. **上传即新版本**：同文件名再次上传时，不再返回「已存在」跳过，而是创建新版本——归档旧分块与 FAISS 向量，入库新内容，更新文档行并递增版本号。
3. **版本历史 API**：`GET /kms/api/documents/{id}/versions` 返回该文档全部版本（倒序）。
4. **版本回滚**：`POST /kms/api/documents/{id}/versions/{no}/rollback` 将指定历史版本重新设为当前版本（复用旧 source_path 重新分词向量化），同时把被替换的当前版本也留痕。
5. **前端展示**：文档列表展示当前版本号；文档详情/操作区提供「版本历史」入口与回滚按钮。

## 2. 非目标（明确不做）

- 不做分块级 diff（不提供段落对比视图）；回滚是整文档粒度。
- 不做并发乐观锁（同文档同时上传新版本由最后写入者胜出，依赖 BLP 审批闸门间接控制）。
- 不改动赛题问答服务 `app.api`（6341）。
- 不做版本物理删除（历史版本永久保留以满足审计合规；仅在文档整体删除时级联清理）。
- 不引入新的工单模块（`doc_update` 常量已存在但本次不启用；版本上传走既有「上传 → 草稿 → 审批发布」链路）。

## 3. 硬约束（工程化标准）

- 版本表与 documents 表的写入必须在**同一事务**内；FAISS 向量删除在事务提交后执行（沿用 `routes_tickets._post_commit_cleanup_faiss` 的模式）。
- 回滚操作必须校验操作者对该文档有管理权限（`access_control.can_manage_document` 派生规则：同部门且职级 ≥ 文档密级）。
- 所有版本变更（新版本、回滚）落审计日志（`kms.access_control.add_audit`）。
- 现有离线回归 `tests/test_enterprise.py` 必须保持全绿；新增 `tests/test_versioning.py` 离线覆盖核心路径。
- 版本号从 1 开始单调递增，`(document_id, version_no)` 唯一。

## 4. 数据模型

### 4.1 新建 `kms_doc_versions` 表

```sql
CREATE TABLE IF NOT EXISTS kms_doc_versions (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  document_id   BIGINT       NOT NULL,
  version_no    INT          NOT NULL,
  content_hash  CHAR(64)     NOT NULL,
  chunk_count   INT          NOT NULL DEFAULT 0,
  source_path   VARCHAR(1024) NOT NULL,
  uploaded_by   BIGINT       NULL,
  uploader_no   VARCHAR(64)  NULL,
  summary       VARCHAR(512) NOT NULL DEFAULT '',
  is_current    TINYINT(1)   NOT NULL DEFAULT 0,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_doc_version (document_id, version_no),
  KEY idx_doc (document_id),
  KEY idx_current (document_id, is_current)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='KMS 文档历史版本';
```

### 4.2 `documents` 表新增列

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `current_version_no` | INT NOT NULL | 1 | 当前版本号（回填存量文档为 1） |

回填策略：新建列时 `UPDATE documents SET current_version_no=1 WHERE current_version_no IS NULL`（仅本次新建列时执行）。

## 5. 模块设计

### 5.1 新建 `kms/versioning.py`（版本管理核心）

```python
def ensure_version_tables() -> None
    # 幂等建表 kms_doc_versions + documents.current_version_no 列（含回填）

def record_version(cur, document_id: int, content_hash: str, chunk_count: int,
                   source_path: str, uploaded_by: int | None, uploader_no: str | None,
                   summary: str = "") -> int
    # 在事务内写入新版本行，设 is_current=1，并把该文档其他版本的 is_current 置 0
    # 返回新版本号 version_no = COALESCE(MAX(version_no),0)+1

def list_versions(document_id: int) -> list[dict]
    # 倒序返回全部版本：{version_no, content_hash, chunk_count, source_path,
    #                   uploaded_by, uploader_no, summary, is_current, created_at}

def get_current_version(document_id: int) -> dict | None
    # 返回 is_current=1 的版本行

def rollback_to_version(document_id: int, target_version_no: int,
                        operator: AuthUser) -> tuple[bool, str, int]
    # 1) 取目标版本行（source_path）；不存在 → (False, "版本不存在", 0)
    # 2) 校验源文件仍存在于受信任目录（复用 gateway.routes_kms._resolve_source_file 逻辑）
    # 3) 归档当前版本：先把当前 is_current=1 置 0
    # 4) 调 indexer.ingest(old_source_path) 重新入库 → 得到新 doc_id
    #    （ingest 内部会查重 content_hash，若命中旧文档则需特殊处理——见 5.3）
    # 5) 将原 documents 行的 content_hash/source_path/chunk_count 更新为目标版本的值
    # 6) record_version 留痕（summary="回滚至 v{target}"）
    # 7) 返回 (True, "已回滚至版本 N", new_version_no)
```

> 注：回滚的实质是「用旧文件重新生成当前版本」，而非切换指针。这样保证 FAISS 向量与 chunks 表始终与 documents.content_hash 一致，避免数据漂移。

### 5.2 修改 `gateway/routes_upload.py` 的 `_ingest_one`

当前逻辑：`SELECT id FROM documents WHERE content_hash=%s OR filename=%s` 命中则返回 `skipped`。

改为：

```python
# 同文件名 → 判定为新版本上传（content_hash 相同仍视为重复并跳过）
cur.execute("SELECT id, content_hash FROM documents WHERE filename=%s LIMIT 1", (name,))
existing = cur.fetchone()
if existing:
    if existing["content_hash"] == digest:
        return {"status": "skipped", "message": "内容未变化", ...}
    # 内容变化 → 创建新版本
    return _ingest_new_version(existing["id"], name, data, user, level, department, digest)
# 新文件名 → 走原有 ingest 流程
```

`_ingest_new_version(doc_id, name, data, user, level, department, digest)`：

1. 事务内：读旧版本的 `source_path` 与 `content_hash`，旧 chunks 的 `faiss_id` 列表（待删）。
2. 落盘新文件（uuid 命名）。
3. `indexer.ingest(new_path)` → 得到 `new_doc_id`（ingest 内部因 content_hash 不重复会新建行）。
4. 事务内：
   - 删除旧 chunks（`DELETE FROM chunks WHERE document_id=%s`）。
   - 用新行数据覆盖旧 documents 行（content_hash / source_path / chunk_count / title / file_type），删除新建的 documents 行（`new_doc_id`），把其 chunks 的 document_id 更新为旧 `doc_id`。
   - `record_version(cur, doc_id, digest, new_chunk_count, new_path, user.id, user.employee_no, summary="内容更新")`。
   - `documents.current_version_no += 1`。
5. 事务提交后：`_post_commit_cleanup_faiss(old_faiss_ids)` 清理旧向量。

> 关键：通过「覆盖旧行 + 迁移 chunks」保持 document_id 不变，使所有外部引用（工单、审计、推荐）不受版本切换影响。

### 5.3 `app/rag.py` 的 `ingest` 调整

`ingest()` 中 `document_exists(content_hash)` 查重逻辑保留，但回滚场景下目标 content_hash 恰好等于旧版 content_hash，会命中查重返回 `skipped`。

解决：为 `ingest` 增加可选参数 `force: bool = False`，为 True 时跳过 `document_exists` 查重（回滚路径传 `force=True`）。新版本上传路径 content_hash 必然不同，不受影响。

### 5.4 API 端点（`gateway/routes_kms.py`）

```
GET  /kms/api/documents/{doc_id}/versions
     → require_user；校验可读权限（service.allowed）
     → 返回 {"items": [ {version_no, chunk_count, summary, is_current,
                         uploaded_by, uploader_no, created_at} ]}

POST /kms/api/documents/{doc_id}/versions/{version_no}/rollback
     → require_user；校验管理权限（can_approve_document 派生）
     → body: {reason: str}  （≤512 字）
     → 调用 versioning.rollback_to_version；事务提交后清理旧向量
     → 审计 AUDIT_DOC_UPDATE，detail=f"rollback to v{version_no}"
     → 返回 {"ok": True, "message": "...", "current_version": int}
```

### 5.5 前端（`kms/web/app.js`）

1. 文档列表 `renderDocs`：在文件名旁加版本徽标 `v{current_version_no}`（需后端列表接口返回该字段）。
2. 文档操作区：在「申请更新」旁新增「版本历史」按钮 → 打开版本历史弹窗。
3. 版本历史弹窗：倒序列出各版本（版本号、上传人、时间、分块数、变更摘要），当前版本标注「当前」；非当前版本提供「回滚到此版本」按钮（二次确认）。
4. 回滚成功后 toast 提示并刷新列表。

### 5.6 文档列表接口扩展

`gateway/service.documents()` 的 SELECT 增加 `d.current_version_no`，`fields` 元组追加 `current_version_no`。

## 6. 验证步骤（验收）

1. `python -m unittest discover tests -v` → 全绿（含新增 `test_versioning.py`）。
2. 重启 6342：`python run_kms.py`。
3. 上传一份文件 A → 文档列表显示 `v1`。
4. 修改文件 A 内容后以**相同文件名**再次上传 → 不返回 skipped，文档仍为同一 document_id，版本号变为 `v2`，`kms_doc_versions` 出现两行（v2 is_current=1，v1 is_current=0）。
5. `GET /kms/api/documents/{id}/versions` → 返回 v2、v1 两条记录。
6. 回滚到 v1：`POST /kms/api/documents/{id}/versions/1/rollback` → 成功，当前版本号变为 v3（content_hash 回到 v1 的值），FAISS 中 v2 的向量被清理。
7. 旧版本源文件缺失时回滚 → 返回明确错误「历史版本源文件不存在，无法回滚」。
8. 权限校验：非同部门/职级不足的用户回滚 → 403。

## 7. 风险与回滚

- 风险：回滚依赖旧源文件仍存在 → 若文件被人工清理则回滚失败；返回明确错误而非静默降级。
- 风险：`ingest` 增加 `force` 参数影响面 → 仅回滚路径调用，默认行为不变。
- 回滚：删除 `kms_doc_versions` 表与 `documents.current_version_no` 列即可恢复（代码改动均为新增 + 单文件小幅修改）。

## 8. 待实现文件清单

| 类型 | 文件 | 动作 |
|---|---|---|
| 新 | `kms/versioning.py` | 版本表 DDL + record_version / list_versions / rollback_to_version |
| 改 | `app/rag.py` | `ingest` 增加 `force` 参数 |
| 改 | `gateway/routes_upload.py` | `_ingest_one` 支持同名文件创建新版本 |
| 改 | `gateway/routes_kms.py` | 新增 versions / rollback 端点 |
| 改 | `gateway/service.py` | documents 列表返回 current_version_no |
| 改 | `kms/web/app.js` | 版本徽标 + 历史弹窗 + 回滚 |
| 新 | `tests/test_versioning.py` | 离线回归 |

## 9. 审批点

**需要批准后才会进入编码**。批准即表示：同意上述文件清单、接口签名、数据模型、验证步骤与行为。
