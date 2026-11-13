"""文档版本管理（kms/versioning.py）的离线契约回归。

本机为离线环境（禁止真实 MySQL），因此不做端到端流程，只守住**设计不变量**：

1. 版本表 DDL 幂等且包含核心字段（document_id / version_no / is_current / 唯一约束）；
2. record_version 必须在事务内先置旧 is_current=0 再写新版本，保证只有一个当前版本；
3. list_versions 倒序返回；
4. rollback_to_version 必须校验源文件存在性，不允许越权读取；
5. ingest 的 force 参数默认 False（不改变既有查重行为），True 时跳过查重；
6. 上传链路 _ingest_one 的版本语义：显式 target_document_id 走新版本分支，
   普通上传一律新文档（不按文件名隐式归并），且新版本必须持久化 filename/title；
7. 文档删除时级联清理 kms_doc_versions；
8. 版本回滚与「申请更新」同一套治理：目标密级/部门由申请人声明、审批人按
   目标态派生、审批通过后才落库（回滚不得抄当前值，也不得借机降密）。
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VersioningModuleTests(unittest.TestCase):

    def _versioning_src(self) -> str:
        return (ROOT / "kms" / "versioning.py").read_text(encoding="utf-8")

    def test_ddl_contains_core_fields(self):
        src = self._versioning_src()
        for field in ("document_id", "version_no", "content_hash", "chunk_count",
                      "source_path", "is_current", "UNIQUE KEY uk_doc_version"):
            self.assertIn(field, src, f"版本表 DDL 缺少 {field}")

    def test_record_version_resets_old_current(self):
        """record_version 必须先把旧版本 is_current 置 0，再写新版本。"""
        src = self._versioning_src()
        self.assertIn("UPDATE kms_doc_versions SET is_current=0", src,
                      "record_version 必须先将旧 is_current 置 0")
        self.assertIn("VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)", src,
                      "新版本 is_current 必须为 1")

    def test_rollback_checks_source_file(self):
        """rollback 必须校验源文件存在且在受信任目录内。"""
        src = self._versioning_src()
        self.assertIn("resolve_version_source", src)
        self.assertIn("source_path", src)

    def test_rollback_uses_force_ingest(self):
        """回滚重新入库必须用 force=True（旧 content_hash 仍存在）。"""
        src = self._versioning_src()
        self.assertIn("force=True", src)

    def test_ensure_version_tables_idempotent(self):
        """建表用 IF NOT EXISTS，加列前先查 INFORMATION_SCHEMA。"""
        src = self._versioning_src()
        self.assertIn("CREATE TABLE IF NOT EXISTS", src)
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", src)


class IngestForceTests(unittest.TestCase):

    def test_ingest_force_param_default_false(self):
        """ingest 的 force 参数默认 False，不改变既有查重行为。"""
        src = (ROOT / "app" / "rag.py").read_text(encoding="utf-8")
        # 签名包含 force: bool = False
        self.assertIn("force: bool = False", src)
        # 仅在 not force 时查重
        self.assertIn("if not force:", src)


class UploadVersionFlowTests(unittest.TestCase):

    def test_ingest_one_supports_new_version(self):
        """显式 target_document_id 走 _ingest_new_version 分支；
        普通上传不再按文件名隐式归并（同名=新文档，版本绑定 doc_id 不绑文件名）。"""
        src = (ROOT / "gateway" / "routes_upload.py").read_text(encoding="utf-8")
        self.assertIn("_ingest_new_version", src)
        self.assertIn("target_document_id", src)
        self.assertNotIn("WHERE filename=%s", src,
                         "普通上传不得按文件名归并为新版本——版本更新必须走显式 target_document_id")

    def test_new_version_persists_filename_title(self):
        """新版本必须持久化 filename/title——JOIN 覆盖不含 filename，
        换文件名更新后若丢失此句，主列表仍显示旧文件名，与版本表不一致。"""
        src = (ROOT / "gateway" / "routes_upload.py").read_text(encoding="utf-8")
        self.assertIn("SET filename=%s, title=%s", src,
                      "_ingest_new_version 必须显式更新 documents.filename/title 为新上传文件名")

    def test_new_version_records_version(self):
        """新版本流程必须调用 record_version 并递增 current_version_no。"""
        src = (ROOT / "gateway" / "routes_upload.py").read_text(encoding="utf-8")
        self.assertIn("record_version", src)
        self.assertIn("current_version_no=%s", src)


class DeleteCascadeTests(unittest.TestCase):

    def test_delete_cascades_versions(self):
        """文档删除时必须级联删除 kms_doc_versions。"""
        src = (ROOT / "gateway" / "routes_tickets.py").read_text(encoding="utf-8")
        self.assertIn("DELETE FROM kms_doc_versions WHERE document_id IN", src)


class ServiceListFieldsTests(unittest.TestCase):

    def test_documents_list_includes_version(self):
        """文档列表接口必须返回 current_version_no。"""
        src = (ROOT / "gateway" / "service.py").read_text(encoding="utf-8")
        self.assertIn("current_version_no", src)


class RollbackGovernanceTests(unittest.TestCase):
    """回滚必须与「上传入库 / 申请更新」同一套治理，不得自成一套。

    历史问题：回滚接口把文档**当前行**的密级/部门原样抄进 policy，工单上
    看着像有人选过，实际是系统替申请人填的——审批人据以复核的「目标态」
    从来没人确认过。这里守住「申请人声明 → 按目标态指派 → 审批后落库」全链路。
    """

    def _kms_src(self) -> str:
        return (ROOT / "gateway" / "routes_kms.py").read_text(encoding="utf-8")

    def test_rollback_accepts_declared_target_state(self):
        """目标密级/部门必须来自申请人入参，而不是仅读文档当前值。"""
        src = self._kms_src()
        self.assertIn("declared_level", src, "回滚未解析申请人声明的密级")
        self.assertIn("declared_depts", src, "回滚未解析申请人声明的归属部门")
        self.assertIn("Policy(classification=target_level, departments=target_depts", src,
                      "回滚 policy 必须写目标态，不得回写文档当前值")

    def test_rollback_approver_matched_by_target_state(self):
        """审批人候选池按目标态派生：按当前态派生会出现「批的和改的不是一回事」。"""
        src = self._kms_src()
        self.assertIn("acl.approver_candidates(target_level, target_depts", src)
        self.assertIn("acl.pick_approver(target_level, target_depts", src)

    def test_rollback_rejects_level_downgrade(self):
        """回滚只恢复内容，不得顺带降密（降密须另走「申请更新」单独审批）。"""
        src = self._kms_src()
        self.assertIn("回滚不能顺带降低密级", src)

    def test_decide_applies_target_state_after_rollback(self):
        """审批通过后必须把目标密级/部门落库：单据写 L2、文档仍 L0 会比不批更难排查。"""
        src = self._kms_src()
        self.assertIn("int(policy.classification), list(policy.departments)", src,
                      "rollback_job 必须携带目标态")
        self.assertIn("回滚同时调整属性", src,
                      "回滚成功后必须落库密级/部门并留痕")

    def test_frontend_rollback_collects_target_state(self):
        """前端回滚弹窗必须让申请人选密级/部门，并随申请一并提交。"""
        vue = (ROOT / "frontend" / "src" / "app" / "views" / "DocumentsView.vue")\
            .read_text(encoding="utf-8")
        self.assertIn("rollbackLevels", vue)
        api = (ROOT / "frontend" / "src" / "app" / "api.js").read_text(encoding="utf-8")
        self.assertIn("classification = null, departments = null", api,
                      "api.rollback 必须能带上目标密级/部门")


if __name__ == "__main__":
    unittest.main()
