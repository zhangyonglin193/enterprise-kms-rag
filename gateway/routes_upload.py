# -*- coding: utf-8 -*-
"""文档批量上传（/kms/api/documents/batch-upload + /kms/api/upload/batches/{id}）。

为什么拆成两个端点
------------------
入库要做 Embedding 与索引构建，单文件就可能数秒。若把整批挂在 HTTP 请求里
同步跑完，几十个文件必然超时。因此：

    POST /documents/batch-upload  → 预检 + 建批次 + 启动后台线程，立即返回
    GET  /upload/batches/{id}     → 前端轮询每个文件的最终状态

预检（文件类型、大小、重名）在**请求内同步完成**，所以被拒的文件会在响应里
立刻以 status=failed 返回；真正耗时的入库才交给后台。

与单文件上传的一致性（重要）
---------------------------
密级与归属部门由上传者声明，两个入口（本模块与 `POST /documents` 单文件）
**必须遵守同一条规则**，否则「哪个入口更松」就成了绕过口：

  1. BLP 不下写——文档密级不得低于本人安全职级；
  2. 部门可以是任意已登记部门（含本人部门）或「不限」（DOC_DEPT_UNLIMITED）；
  3. 两者缺省都取**更严**的一侧，漏传字段不会放宽权限。

历史上这里**忽略** level、密级恒为 3，理由是怕批量入口被用来把敏感文档登记
成 L0 公开。那条约束现在由第 1、3 点更一般地覆盖，且密级选了什么都仍要先过
发布审批才可见——真正的暴露门槛是草稿状态，不是硬编码的 3。
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.logger import get_logger
from app.store import MySQLStore
from config import settings
from gateway import doc_inflight
from gateway.routes_kms import _auto_submit_for_approval, _ingest_lock, editor
from kms.constants import DOC_DEPT_UNLIMITED, DEPARTMENTS
from kms.formats import is_allowed
from kms.security import AuthUser

logger = get_logger("gateway.upload")

router = APIRouter(prefix="/kms/api", tags=["enterprise-controlled"])

# 内存里暂存待入库字节，必须有上限：批量接口是少数能被外部放大内存的入口之一
_MAX_FILES = 20
_MAX_EACH = 10 * 1024 * 1024        # 单文件 10 MiB（与单文件上传一致）
_MAX_TOTAL = 60 * 1024 * 1024       # 整批 60 MiB

# 入库串行锁已在 routes_kms 定义，这里复用同一把，避免与单文件上传并发 ingest
_batch_seq_lock = threading.Lock()


class _DocInflightBusy(RuntimeError):
    """目标文档已有在途单：事务内判定后抛出，由外层回滚并清理临时文档。

    用异常而不是 return，是因为判定点已在 `with transaction()` 内部：return 会
    把事务正常提交，而此刻我们必须让这个事务什么都不做地结束。
    """


def _drop_orphan_doc(doc_id: int) -> None:
    """删掉 ingest 刚建出、尚未被采纳的临时文档（行 + chunks + 向量）。

    新版本流程是「先 ingest 成一篇新文档，再把它的 chunks 搬到目标 doc_id 上」。
    中途被在途互斥拦下时，那篇临时文档就成了无人认领的孤儿（主列表会多出一
    篇重复文档），必须连同向量一并清掉。
    """
    faiss_ids: list[int] = []
    try:
        with MySQLStore().transaction() as cur:
            cur.execute("SELECT faiss_id FROM chunks WHERE document_id=%s", (doc_id,))
            faiss_ids = [int(r["faiss_id"]) for r in cur.fetchall()]
            cur.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))
            cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"临时文档 {doc_id} 清理失败: {e}")
        return
    if faiss_ids:
        try:
            from gateway.routes_tickets import _post_commit_cleanup_faiss
            _post_commit_cleanup_faiss(faiss_ids)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"临时文档 {doc_id} 向量清理失败: {e}")


def _new_batch(cur, user_id: int, department: str, total: int) -> int:
    cur.execute(
        "INSERT INTO kms_upload_batches (user_id, department, total) VALUES (%s, %s, %s)",
        (user_id, department, total))
    return int(cur.lastrowid)


def _parse_departments(value: str) -> list[str]:
    """解析前端表单中的归属部门 JSON 数组字符串。"""
    if not value or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, str):
        return [parsed]
    if isinstance(parsed, list):
        return [str(x) for x in parsed if x is not None]
    return []


def _insert_items(cur, batch_id: int, rows: list[dict]) -> None:
    cur.executemany(
        "INSERT INTO kms_upload_batch_items (batch_id, seq, filename, status, message) "
        "VALUES (%s, %s, %s, %s, %s)",
        [(batch_id, r["seq"], r["filename"][:512], r["status"], r["message"][:512])
         for r in rows])


def _set_item(batch_id: int, seq: int, status: str, message: str = "",
              chunk_count: int = 0, document_id: int | None = None) -> None:
    with MySQLStore().transaction() as cur:
        cur.execute(
            "UPDATE kms_upload_batch_items SET status=%s, message=%s, chunk_count=%s, "
            "document_id=%s WHERE batch_id=%s AND seq=%s",
            (status, message[:512], chunk_count, document_id, batch_id, seq))


def _finish_batch(batch_id: int) -> None:
    with MySQLStore().transaction() as cur:
        cur.execute("UPDATE kms_upload_batches SET finished=1 WHERE id=%s", (batch_id,))


def _approval_message(approval: dict) -> str:
    """把自动审批结果转成前端可读的短消息。"""
    if not approval:
        return "审批状态未知"
    if approval.get("auto_submitted"):
        a = approval.get("approver") or {}
        name = a.get("username") or a.get("employee_no") or "未知"
        return f"已自动提交发布审批（审批人：{name}）"
    return f"未自动提交审批：{approval.get('reason', '原因未知')}"


def _ingest_one(name: str, data: bytes, user: AuthUser, level: int,
                departments: list[str], specified_approver_id: int | None = None,
                ip: str = "", target_document_id: int | None = None,
                update_reason: str | None = None) -> dict:
    """入库单个文件，返回 {status, message, chunk_count, document_id}。

    两种语义（版本绑定 doc_id，不绑文件名）：
      · target_document_id 为空 → 一律创建**新文档**（新 doc_id）。同名文件
        不再隐式归并为新版本——避免「恰好同名」的不同文档被系统擅自归并；
        同内容仍由 ingest 内部 content_hash 查重拦截（skipped）。
      · target_document_id 非空 → 为该已有文档上传**新版本**（任意文件名均可），
        走 _ingest_new_version 版本归档替换。目标文档的存在性/管理权/生命周期
        校验在路由层（routes_kms.upload_document）完成，本函数是纯执行层。

    逻辑与 routes_kms.upload_document 保持一致（含重内容拦截与草稿登记），
    唯一区别是失败时清理已落盘文件，避免批量失败在 upload_dir 留下孤儿文件。

    level / departments **由上传者声明**（原实现写死 L3 + 上传者部门，"选密级"
    这件事从来不存在）。二者进来前已在入口完成校验：
      · level 过 BLP 不下写（level >= 本人安全职级）
      · departments 为已登记部门数组或含 DOC_DEPT_UNLIMITED（不限）
    """
    if target_document_id:
        return _ingest_new_version(int(target_document_id), name, data, user, level,
                                   departments, specified_approver_id, ip,
                                   update_reason=update_reason)

    suffix = Path(name).suffix.lower()
    path = settings.upload_dir / (uuid.uuid4().hex + suffix)
    try:
        with path.open("xb") as output:
            output.write(data)
        from kms.routes import get_indexer
        result = get_indexer().ingest(path)
        if result.get("skipped"):
            return {"status": "skipped",
                    "message": f"库中已存在相同内容的文档（ID {result.get('document_id')}），无需重复上传",
                    "chunk_count": 0, "document_id": None}
        doc_id = int(result["document_id"])
        with MySQLStore().transaction() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM chunks WHERE document_id=%s", (doc_id,))
            chunk_count = int(cur.fetchone()["n"])
            # 读取 content_hash（提取文本哈希，由 ingest 写入）
            cur.execute("SELECT content_hash FROM documents WHERE id=%s", (doc_id,))
            real_hash = cur.fetchone()["content_hash"]
            cur.execute(
                "UPDATE documents SET filename=%s,title=%s,departments=%s,"
                "status='draft',lifecycle_state='draft',"
                "current_version_no=1 WHERE id=%s",
                (name, Path(name).stem, json.dumps(departments, ensure_ascii=False), doc_id))
            # 落库上传者声明的密级（原写死 L3）。仍登记为草稿，发布另走审批。
            cur.execute(
                "INSERT INTO kms_doc_levels(document_id,level,granted_by) VALUES(%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE level=VALUES(level), granted_by=VALUES(granted_by)",
                (doc_id, level, user.id))
            # 为新文档登记初始版本（v1），content_hash 与 documents 表一致
            from kms.versioning import record_version
            record_version(cur, doc_id, real_hash, chunk_count, str(path),
                           user.id, user.employee_no, summary="初始版本")
            # 上传入库后自动提交发布审批：审批人按文档归属部门 + 密级指派
            approval = _auto_submit_for_approval(cur, doc_id, user, level, departments,
                                                 ip=ip,
                                                 specified_approver_id=specified_approver_id,
                                                 action="upload")
        # 把审批结果拼进 message，前端轮询批量状态时可见
        approval_msg = _approval_message(approval)
        return {"status": "success", "message": approval_msg, "chunk_count": chunk_count,
                "document_id": doc_id, "auto_approval": approval}
    except Exception as e:
        # 入库失败：清掉刚写的原文，不留孤儿文件
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"status": "failed", "message": str(e)[:500], "chunk_count": 0,
                "document_id": None}


def _same_content_as_current(doc_id: int, other_id: int) -> bool:
    """命中的文档与目标文档当前版本是否同内容。

    ingest 的查重是全库 content_hash（提取文本哈希），命中时返回的 document_id
    可能是目标文档自身，也可能是库里另一篇同内容文档（甚至可能与目标当前版本
    同哈希——同一内容存在多行时 LIMIT 1 命中哪行不确定）。
    """
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM documents a JOIN documents b ON b.id=%s "
            "WHERE a.id=%s AND a.content_hash=b.content_hash", (other_id, doc_id))
        return int(cur.fetchone()["n"]) > 0


def _ingest_new_version(doc_id: int, name: str, data: bytes, user: AuthUser,
                        level: int, departments: list[str],
                        specified_approver_id: int | None = None, ip: str = "",
                        update_reason: str | None = None) -> dict:
    """为已有文档创建新版本（保持 document_id 不变）。

    流程：落盘新文件 → ingest 新建临时 doc → 迁移 chunks 到旧 doc_id →
    覆盖 documents 行 → record_version → 递增版本号 → 清理旧 FAISS 向量。
    """
    from kms.routes import get_indexer
    from kms.versioning import record_version

    suffix = Path(name).suffix.lower()
    path = settings.upload_dir / (uuid.uuid4().hex + suffix)
    try:
        with path.open("xb") as output:
            output.write(data)
    except OSError as e:
        return {"status": "failed", "message": f"落盘失败: {e}", "chunk_count": 0,
                "document_id": None}

    old_faiss_ids: list[int] = []
    try:
        # ingest 按「提取文本哈希」全库查重：命中时 result["document_id"] 是命中行的 id。
        result = get_indexer().ingest(path)
        if result.get("skipped"):
            existing_id = result.get("document_id")
            if existing_id is not None and _same_content_as_current(doc_id, int(existing_id)):
                # 与目标文档当前版本一字不差——这才是真正意义上的「内容未变化」
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return {"status": "skipped",
                        "message": "新版本内容与当前版本完全一致，未产生新版本",
                        "chunk_count": 0, "document_id": doc_id}
            # 命中的是「库里其它文档」：版本更新是用户对 doc_id 的显式意图，
            # 不能被全库查重拦住（否则把 A 的内容改到 B 上永远做不成）。
            # 强制入库仅跳过查重，新行在下方事务里被覆写并删除，不会留下重复行。
            result = get_indexer().ingest(path, force=True)
            if result.get("skipped"):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return {"status": "skipped", "message": "内容未变化", "chunk_count": 0,
                        "document_id": doc_id}
        new_doc_id = int(result["document_id"])
        new_chunk_count = int(result.get("chunk_count", 0))

        with MySQLStore().transaction() as cur:
            # 在途互斥（并发防线）：路由层对「上传新版本」已前置校验过一次，
            # 这里在同一事务内、写任何内容之前再判定一次——否则「检查后、写内容前」
            # 的窗口里别人建了单，本次仍会把正文改掉却不产生审批单（绕过审批）。
            # 必须排在删旧 chunks / 覆盖 documents 之前。
            conflict = doc_inflight.find_inflight_conflict(cur, [doc_id])
            if conflict:
                raise _DocInflightBusy(conflict + doc_inflight.CONFLICT_TAIL)
            # 读取新文档的 content_hash（提取文本的哈希，与 documents 表一致）
            cur.execute("SELECT content_hash FROM documents WHERE id=%s", (new_doc_id,))
            new_content_hash = cur.fetchone()["content_hash"]

            # 1. 收集旧 chunks 的 faiss_id（事务提交后清理 FAISS）
            cur.execute("SELECT faiss_id FROM chunks WHERE document_id=%s", (doc_id,))
            old_faiss_ids = [int(r["faiss_id"]) for r in cur.fetchall()]

            # 2. 删除旧 chunks
            cur.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))

            # 3. 把新 doc 的 chunks 迁移到旧 document_id
            cur.execute(
                "UPDATE chunks SET document_id=%s WHERE document_id=%s",
                (doc_id, new_doc_id),
            )

            # 4. 用新行数据覆盖旧 documents 行
            cur.execute(
                "UPDATE documents d JOIN documents nd ON nd.id=%s SET "
                " d.content_hash=nd.content_hash, d.source_path=nd.source_path, "
                " d.file_type=nd.file_type, d.chunk_count=nd.chunk_count, "
                " d.title=nd.title, d.author=nd.author, d.language=nd.language "
                "WHERE d.id=%s",
                (new_doc_id, doc_id),
            )

            # 5. 删除新建的 documents 行（其 chunks 已迁移走）
            cur.execute("DELETE FROM documents WHERE id=%s", (new_doc_id,))

            # 6. 更新密级、部门、状态（新版本重置为草稿待审批）
            cur.execute(
                "UPDATE documents SET departments=%s,"
                "status='draft',lifecycle_state='draft' WHERE id=%s",
                (json.dumps(departments, ensure_ascii=False), doc_id))
            # 6.1 持久化新上传文件名/标题。上面的 JOIN 覆盖不含 filename，且 title
            #     复制的是临时 doc 的值——若不补此句，换文件名更新后主列表仍显示
            #     旧文件名，与版本表记录的新文件名前后不一致（最容易漏的一行）。
            cur.execute(
                "UPDATE documents SET filename=%s, title=%s WHERE id=%s",
                (name, Path(name).stem, doc_id))
            cur.execute(
                "INSERT INTO kms_doc_levels(document_id,level,granted_by) VALUES(%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE level=VALUES(level), granted_by=VALUES(granted_by)",
                (doc_id, level, user.id))

            # 7. 留痕新版本并递增版本号（content_hash 用提取文本哈希，与 documents 表一致）
            reason = (update_reason or "").strip()[:200]
            new_no = record_version(
                cur, doc_id, new_content_hash, new_chunk_count, str(path),
                user.id, user.employee_no, summary=reason or "内容更新",
            )
            cur.execute(
                "UPDATE documents SET current_version_no=%s WHERE id=%s",
                (new_no, doc_id),
            )
            # 新版本入库后自动提交发布审批：审批人按文档归属部门 + 密级指派。
            # action 标为 update_version，工单中心才能把「换了一版内容」与
            # 「新上传一篇」区分开（两者走同一套审批与可见性）。
            approval = _auto_submit_for_approval(cur, doc_id, user, level, departments,
                                                 ip=ip,
                                                 specified_approver_id=specified_approver_id,
                                                 action="update_version")

        # 事务提交后清理旧 FAISS 向量
        if old_faiss_ids:
            try:
                from gateway.routes_tickets import _post_commit_cleanup_faiss
                _post_commit_cleanup_faiss(old_faiss_ids)
            except Exception as e:
                logger.warning(f"新版本上传后 FAISS 清理失败: {e}")

        logger.info(f"文档 {doc_id} 新版本 v{new_no} 已创建")
        approval_msg = _approval_message(approval)
        return {"status": "success", "message": f"已更新为版本 v{new_no}；{approval_msg}",
                "chunk_count": new_chunk_count, "document_id": doc_id,
                "auto_approval": approval}
    except _DocInflightBusy as e:
        # 事务已回滚（目标文档一个字都没动），但 ingest 出的临时文档是上一次
        # 事务提交的产物，得单独清掉。
        _drop_orphan_doc(new_doc_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"status": "conflict", "message": str(e)[:500], "chunk_count": 0,
                "document_id": doc_id}
    except Exception as e:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"status": "failed", "message": str(e)[:500], "chunk_count": 0,
                "document_id": None}


def _run_batch(batch_id: int, payloads: list[tuple[int, str, bytes]], user: AuthUser,
               level: int, departments: list[str],
               specified_approver_id: int | None = None) -> None:
    """后台线程：串行入库整批。

    用阻塞式 acquire（而非单文件上传的 try_acquire）：这是后台线程，等待是
    合理的；单文件上传接口才需要「忙则立刻 409」来保护 HTTP 响应时间。
    """
    try:
        for seq, name, data in payloads:
            _set_item(batch_id, seq, "processing")
            with _ingest_lock:
                outcome = _ingest_one(name, data, user, level, departments,
                                      specified_approver_id=specified_approver_id)
            # 把自动审批结果拼进 message，前端轮询时可见
            approval = outcome.get("auto_approval") or {}
            if approval.get("auto_submitted"):
                approver = approval.get("approver", {})
                msg = f"已入库，已自动提交发布审批（审批人：{approver.get('username', approver.get('employee_no', '?'))}）"
            elif approval.get("reason"):
                msg = f"已入库（草稿），{approval['reason']}"
            else:
                msg = outcome["message"]
            _set_item(batch_id, seq, outcome["status"], msg,
                      outcome["chunk_count"], outcome["document_id"])
        from kms.routes import _hot_update_caches
        _hot_update_caches()
    except Exception as e:
        logger.warning(f"批量入库批次 {batch_id} 异常: {e}")
    finally:
        _finish_batch(batch_id)


@router.post("/documents/batch-upload", status_code=202)
def batch_upload(files: list[UploadFile] = File(...), level: str = Form(""),
                 departments: str = Form(""),  # JSON 数组字符串
                 approver_id: int | None = Form(None),
                 user: AuthUser = Depends(editor)):
    """批量入库：预检后交后台线程，返回 batch_id 供前端轮询。

    密级与归属部门**由上传者声明**（原实现两者都写死：密级一律 L3、部门取上传者
    部门——"选密级"这件事从来不存在，且要求 security_level==3 等于只有 L3 能入库）。

      · BLP 不下写：文档密级不得低于本人安全职级；
      · 归属部门必须显式声明（已登记部门或 DOC_DEPT_UNLIMITED），不回落本人部门；
      · 密级缺省取本人职级（最严的一侧），漏传不会放宽权限。

    其余鉴权与单文件上传一致（部门知识维护授权 + 模型出域授权），
    避免批量入口成为权限洼地。
    """
    if not settings.gw_model_egress_allowed:
        raise HTTPException(403, "入库需模型出域授权")
    if not files:
        raise HTTPException(422, "未选择文件")
    if len(files) > _MAX_FILES:
        raise HTTPException(413, f"单次最多 {_MAX_FILES} 个文件")

    # 密级：缺省取本人职级（满足「不下写」的最严取值），显式传入则须 >= 本人职级
    if level in ("", None):
        lv = int(user.security_level)
    elif level in ("0", "1", "2", "3"):
        lv = int(level)
    else:
        raise HTTPException(422, "密级参数非法")
    if lv < int(user.security_level):
        raise HTTPException(403, f"不能登记低于本人安全职级 L{user.security_level} 的文档")

    # 解析 JSON 数组。department 可能为 NULL，用 or 兜底成 '' 再判空
    # （test_department_is_never_written_as_null 的静态契约）。
    # **不回落本人部门**：归属部门决定「谁能读 + 谁来审」，系统替用户猜一次
    # 就是一次错授权（选了财务部，单据上却是产品管理部）。缺了就 422。
    raw_depts = _parse_departments(departments)
    seen = set()
    dept_list: list[str] = []
    for d in raw_depts:
        d = (d or "").strip()[:128]
        if not d or d in seen:
            continue
        seen.add(d)
        if d != DOC_DEPT_UNLIMITED and d not in DEPARTMENTS:
            raise HTTPException(422, f"归属部门无效：{d}")
        dept_list.append(d)
    if DOC_DEPT_UNLIMITED in dept_list and len(dept_list) > 1:
        dept_list = [DOC_DEPT_UNLIMITED]
    if not dept_list:
        raise HTTPException(422, "请选择归属部门（它决定谁能看到、由谁审批）")

    rows: list[dict] = []
    payloads: list[tuple[int, str, bytes]] = []
    total = 0
    for seq, f in enumerate(files):
        name = Path((f.filename or "").replace("\\", "/")).name
        if not is_allowed(name):
            rows.append({"seq": seq, "filename": name, "status": "failed",
                         "message": "不支持的文件类型"})
            continue
        data = f.file.read(_MAX_EACH + 1)
        if not data or len(data) > _MAX_EACH:
            rows.append({"seq": seq, "filename": name, "status": "failed",
                         "message": "文件为空或超过 10 MiB"})
            continue
        total += len(data)
        if total > _MAX_TOTAL:
            rows.append({"seq": seq, "filename": name, "status": "failed",
                         "message": "整批总量超过上限"})
            continue
        rows.append({"seq": seq, "filename": name, "status": "pending", "message": ""})
        payloads.append((seq, name, data))

    with MySQLStore().transaction() as cur:
        # department 列为 NOT NULL：员工的 department 可能是 NULL（未做组织同步），
        # 显式传 NULL 会被 MySQL 拒绝（DEFAULT 只在省略该列时生效），故在此兜底。
        batch_id = _new_batch(cur, user.id, dept_list[0] if dept_list else "", len(payloads))
        _insert_items(cur, batch_id, rows)

    if payloads:
        threading.Thread(target=_run_batch, args=(batch_id, payloads, user, lv, dept_list, approver_id),
                         name=f"kms-batch-{batch_id}", daemon=True).start()

    return {
        "batch_id": batch_id,
        "message": f"已接收 {len(payloads)} 个文件，入库中",
        "items": [{"seq": r["seq"], "filename": r["filename"], "status": r["status"],
                   "message": r["message"]} for r in rows],
    }


@router.get("/upload/batches/{batch_id}")
def batch_status(batch_id: int, user: AuthUser = Depends(editor)):
    """查询批量入库进度（前端轮询）。

    只能查自己的批次——批次里含文件名，泄露他人上传行为属于信息越权。
    """
    with MySQLStore().transaction() as cur:
        cur.execute("SELECT user_id, finished FROM kms_upload_batches WHERE id=%s", (batch_id,))
        batch = cur.fetchone()
        if not batch or batch["user_id"] != user.id:
            raise HTTPException(404, "批次不存在")
        cur.execute(
            "SELECT seq, filename, status, message, chunk_count, document_id "
            "FROM kms_upload_batch_items WHERE batch_id=%s ORDER BY seq", (batch_id,))
        items = cur.fetchall()
    return {
        "batch_id": batch_id,
        "finished": bool(batch["finished"]),
        "items": [{"seq": i["seq"], "filename": i["filename"], "status": i["status"],
                   "message": i["message"], "chunk_count": i["chunk_count"],
                   "document_id": i["document_id"]} for i in items],
    }
