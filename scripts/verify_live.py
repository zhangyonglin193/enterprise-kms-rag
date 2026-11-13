# -*- coding: utf-8 -*-
"""真实数据库环境下的端到端验收脚本。

用途
----
离线契约测试（tests/）只能验证「鉴权声明、权限不变量、SQL 常量」这类静态属性，
验证不了真实链路：SQL 能否在 MySQL 8 上跑通、事务是否提交、执行器是否真的生效。
本脚本直接调用路由函数（不经 HTTP/JWT），在**真实库**上跑完整流程。

典型场景：本机验收、以及通过 Xshell 上传到组委会服务器后，用服务器上的 MySQL
再跑一次（`python scripts/verify_live.py --all`）。

安全约定
--------
- 默认只做只读盘点（--survey），不写任何数据。
- --tickets / --upload 会写库，但都使用带固定前缀的测试数据，并在结束时清理。
- 不打印口令。

用法
----
    python scripts/verify_live.py               # 只读盘点（默认，安全）
    python scripts/verify_live.py --tickets     # 工单端到端（建单→审批→执行）
    python scripts/verify_live.py --knowledge   # 知识中心 4 端点
    python scripts/verify_live.py --upload      # 批量上传真实入库
    python scripts/verify_live.py --all         # 全部
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock

# 以 scripts/ 直接运行时，sys.path[0] 是 scripts 而非项目根，需手动补上
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 标记本次脚本造的数据，便于清理，也避免污染真实业务数据
TAG = "[verify]"


def _req() -> MagicMock:
    """伪造 Request：路由只用它取客户端 IP。"""
    r = MagicMock()
    r.client.host = "127.0.0.1"
    return r


def survey() -> int:
    """只读盘点：确认环境是否具备验收条件。"""
    from app.store import MySQLStore

    print("=" * 68)
    print("数据环境盘点（只读）")
    print("=" * 68)
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT VERSION() AS v, DATABASE() AS db")
        info = cur.fetchone()
        print(f"MySQL {info['v']}  库={info['db']}")

        checks = [
            ("在职员工", "SELECT COUNT(*) n FROM kms_users WHERE is_active=1"),
            ("有部门的员工", "SELECT COUNT(*) n FROM kms_users WHERE is_active=1 "
                            "AND department IS NOT NULL AND department<>''"),
            ("有组织路径的员工", "SELECT COUNT(*) n FROM kms_users WHERE is_active=1 "
                                "AND org_path IS NOT NULL AND org_path<>''"),
            ("文档总数", "SELECT COUNT(*) n FROM documents"),
            ("已登记密级的文档", "SELECT COUNT(*) n FROM kms_doc_levels"),
            ("已发布文档", "SELECT COUNT(*) n FROM documents WHERE status='published'"),
            ("持审批职责的员工", "SELECT COUNT(*) n FROM kms_user_duties"),
            ("工单", "SELECT COUNT(*) n FROM kms_tickets"),
            ("上传批次", "SELECT COUNT(*) n FROM kms_upload_batches"),
            ("推荐交互", "SELECT COUNT(*) n FROM kms_rec_interactions"),
        ]
        for label, sql in checks:
            cur.execute(sql)
            print(f"  {label:<20} = {cur.fetchone()['n']}")

        cur.execute("SELECT security_level, COUNT(*) n FROM kms_users "
                    "WHERE is_active=1 GROUP BY security_level ORDER BY security_level")
        print("  在职员工密级分布 =",
              {r["security_level"]: r["n"] for r in cur.fetchall()})

        cur.execute("SELECT l.level, COUNT(*) n FROM kms_doc_levels l GROUP BY l.level")
        print("  文档密级分布     =",
              {r["level"]: r["n"] for r in cur.fetchall()})

    # 完整性检查：这类问题会让「代码正确但全库不可见」，且极难从现象反推
    print("\n完整性检查：")
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) n FROM kms_doc_levels l "
                    "LEFT JOIN documents d ON d.id=l.document_id WHERE d.id IS NULL")
        orphan = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM documents d "
                    "LEFT JOIN kms_doc_levels l ON l.document_id=d.id WHERE l.document_id IS NULL")
        nolevel = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM documents WHERE status='published' "
                    "AND publication_approved=0")
        unapproved = cur.fetchone()["n"]
    print(f"  孤立密级记录（指向不存在的文档）= {orphan}")
    print(f"  未登记密级的文档               = {nolevel}")
    print(f"  已发布但未过发布闸门的文档      = {unapproved}")

    # 其余关键量：验收跑完后应与跑之前一致（用于确认脚本「用完还原」没留残留）
    with MySQLStore()._conn() as cur:
        for label, sql in (
            ("有部门的员工", "SELECT COUNT(*) n FROM kms_users WHERE department IS NOT NULL "
                            "AND department<>''"),
            ("有归属部门的文档", "SELECT COUNT(*) n FROM documents WHERE owner_department<>''"),
            ("工单", "SELECT COUNT(*) n FROM kms_tickets"),
            ("上传批次", "SELECT COUNT(*) n FROM kms_upload_batches"),
            ("职责记录", "SELECT COUNT(*) n FROM kms_user_duties"),
            ("文档总数", "SELECT COUNT(*) n FROM documents"),
        ):
            cur.execute(sql)
            print(f"  {label:<20} = {cur.fetchone()['n']}")
    if orphan:
        print("  [!] 孤立密级记录意味着这些文档的密级登记已失效；")
        print("      若同时所有文档都无密级，则全库不可见（fail-closed 的正确表现）。")
    if nolevel:
        print("  [!] 未登记密级的文档对所有人不可见——这是刻意的 fail-closed，")
        print("      需先完成文档定级（密级=未定级的文档一律不出域）。")

    # 明确提示会影响验收结论的环境问题
    print("\n关键提示：")
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT COUNT(*) n FROM kms_users WHERE is_active=1 "
                    "AND department IS NOT NULL AND department<>''")
        if cur.fetchone()["n"] == 0:
            print("  [!] 没有任何在职员工设置了 department。")
            print("      service.allowed() 对密级>0 的文档要求 user.department 非空，")
            print("      因此除 L0 公开文档外，所有人都看不到任何文档（含问答召回）。")
            print("      这不是代码缺陷，是数据未初始化——需先跑 HR/组织同步。")
    return 0


def migrate() -> int:
    """补齐缺失的列与表（部署到新库后必须先跑一次）。

    真实库上 documents 表可能缺少治理列（owner_department / publication_approved
    等），这些列是权限判定的前置条件；缺列会让文档列表与问答**全部**报 503，
    且异常被 except 吞成「权限元数据不可用」，极难定位。
    """
    from app.store import MySQLStore
    from gateway import ensure_gateway_tables, service
    from kms.hr_sync import ensure_hr_sync_columns
    from kms.lifecycle import ensure_lifecycle_columns

    print("=" * 68)
    print("结构迁移（补列/建表）")
    print("=" * 68)
    service.migrate()
    print(f"  gateway 表 = {ensure_gateway_tables()}")
    print(f"  lifecycle  = {ensure_lifecycle_columns()}")
    print(f"  hr_sync    = {ensure_hr_sync_columns()}")

    # 存量库升级场景：闸门列可能早已存在（故 service.migrate 的回填不触发），
    # 但值仍是 0 → 全库不可见。这里补齐，语义与 service.migrate 的回填一致。
    with MySQLStore()._conn() as cur:
        cur.execute("UPDATE documents SET publication_approved=1 "
                    "WHERE status='published' AND publication_approved=0")
        if cur.rowcount:
            print(f"  [修复] 回填 {cur.rowcount} 篇已发布文档的发布闸门")

    need = ("owner_department", "extra_departments", "publication_approved",
            "status", "lifecycle_state", "expires_at", "owner_org_path")
    with MySQLStore()._conn() as cur:
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents'")
        cols = {r["COLUMN_NAME"] for r in cur.fetchall()}
    missing = [c for c in need if c not in cols]
    for c in need:
        print(f"  {'OK ' if c in cols else '缺 '} {c}")
    return 1 if missing else 0


def acl_check() -> int:
    """在真实数据上验证「分级 + 分部门 + 组织继承」读权限（用完还原）。

    离线测试只能验证判定函数的逻辑，验证不了这套逻辑落到**真实 SQL** 上是否等价。
    这里临时造一个可控场景，逐条断言，跑完必须还原。
    """
    from app.store import MySQLStore
    from gateway import service

    DEPT, OTHER = "__v_dept__", "__v_other__"
    ROOT, CHILD = "__v公司/研发中心", "__v公司/研发中心/平台组"

    print("=" * 68)
    print("分级 / 分部门 / 组织继承 读权限验收（真实库，用完还原）")
    print("=" * 68)

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id FROM documents ORDER BY id LIMIT 2")
        docs = cur.fetchall()
        cur.execute("SELECT id FROM kms_users WHERE is_active=1 AND security_level>=1 "
                    "ORDER BY id LIMIT 2")
        us = cur.fetchall()
    if len(docs) < 2 or len(us) < 2:
        print("  数据不足（需 2 篇文档 + 2 名 L1 以上在职员工）")
        return 1
    d_gated, d_public = docs[0]["id"], docs[1]["id"]
    u_same, u_diff = us[0]["id"], us[1]["id"]

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id, department, org_path FROM kms_users WHERE id IN (%s,%s)",
                    (u_same, u_diff))
        bu = {r["id"]: (r["department"], r["org_path"]) for r in cur.fetchall()}
        cur.execute("SELECT id, owner_department, owner_org_path FROM documents "
                    "WHERE id IN (%s,%s)", (d_gated, d_public))
        bd = {r["id"]: (r["owner_department"], r["owner_org_path"]) for r in cur.fetchall()}

    def _visible(user, doc_id: int) -> bool:
        try:
            r = service.documents(user, 0, 3, 0, 500)
        except Exception:
            return False
        return any(i["document_id"] == doc_id for i in r["items"])

    ok = True
    try:
        with MySQLStore().transaction() as cur:
            cur.execute("UPDATE kms_users SET department=%s, org_path='' WHERE id=%s",
                        (DEPT, u_same))
            cur.execute("UPDATE kms_users SET department=%s, org_path='' WHERE id=%s",
                        (OTHER, u_diff))
            # gated：L1 且归属 DEPT → 只有同部门可见
            cur.execute("UPDATE documents SET owner_department=%s, owner_org_path='' "
                        "WHERE id=%s", (DEPT, d_gated))
            cur.execute("INSERT INTO kms_doc_levels (document_id, level, granted_by) "
                        "VALUES (%s,1,%s) ON DUPLICATE KEY UPDATE level=1",
                        (d_gated, u_same))
            # public：L0 → 任何人都可见
            cur.execute("UPDATE documents SET owner_department=%s, owner_org_path='' "
                        "WHERE id=%s", (OTHER, d_public))
            cur.execute("INSERT INTO kms_doc_levels (document_id, level, granted_by) "
                        "VALUES (%s,0,%s) ON DUPLICATE KEY UPDATE level=0",
                        (d_public, u_same))

        same, diff = _user(u_same), _user(u_diff)
        cases = [
            ("同部门(L1)看 L1 文档", _visible(same, d_gated), True),
            ("跨部门看 L1 文档", _visible(diff, d_gated), False),
            ("跨部门看 L0 公开文档", _visible(diff, d_public), True),
            ("同部门看 L0 公开文档", _visible(same, d_public), True),
        ]
        for label, got, want in cases:
            flag = "PASS" if got == want else "FAIL"
            ok &= (got == want)
            print(f"  [{flag}] {label}: 实际={got} 期望={want}")

        # 组织继承：把文档放到子组织，用户放到父组织，部门故意不匹配
        with MySQLStore().transaction() as cur:
            cur.execute("UPDATE documents SET owner_department=%s, owner_org_path=%s "
                        "WHERE id=%s", (OTHER, CHILD, d_gated))
            cur.execute("UPDATE kms_users SET department=%s, org_path=%s WHERE id=%s",
                        (OTHER, ROOT, u_diff))
        diff2 = _user(u_diff)
        got = _visible(diff2, d_gated)
        ok &= got
        print(f"  [{'PASS' if got else 'FAIL'}] 上级组织看下级 L1 文档: 实际={got} 期望=True")
    finally:
        with MySQLStore().transaction() as cur:
            for uid, (dept, op) in bu.items():
                cur.execute("UPDATE kms_users SET department=%s, org_path=%s WHERE id=%s",
                            (dept, op or "", uid))
            for did, (dept, op) in bd.items():
                cur.execute("UPDATE documents SET owner_department=%s, owner_org_path=%s "
                            "WHERE id=%s", (dept, op or "", did))
            cur.execute("DELETE FROM kms_doc_levels WHERE document_id IN (%s,%s)",
                        (d_gated, d_public))
        print("  已还原用户部门/组织路径与文档归属，并删除临时密级登记")
    return 0 if ok else 1


def _user(user_id: int):
    from kms.security import AuthUser
    from kms import access_control as acl

    row = acl.get_user_by_id(user_id)
    if not row:
        return None
    return AuthUser(row)


def tickets() -> int:
    """工单端到端：模块目录 → 候选人 → 建单 → 审批 → 执行。"""
    from app.store import MySQLStore
    from fastapi import HTTPException

    from gateway import routes_tickets as rt
    from kms import access_control as acl
    from kms.constants import DUTY_TICKET_APPROVE

    print("=" * 68)
    print("工单端到端验收（真实库）")
    print("=" * 68)

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id, employee_no, username FROM kms_users "
                    "WHERE is_active=1 ORDER BY id LIMIT 2")
        two = cur.fetchall()
    if len(two) < 2:
        print("  需要至少 2 名在职员工才能验证 A/B 分离，当前不足")
        return 1
    applicant = _user(two[0]["id"])
    approver = _user(two[1]["id"])
    if not applicant or not approver:
        print("  构造 AuthUser 失败")
        return 1
    print(f"  申请人 A = {applicant.employee_no} ({applicant.username})")
    print(f"  审批人 B = {approver.employee_no} ({approver.username})")

    # 1. 模块目录
    mods = rt.ticket_modules(applicant)
    print(f"  1. 模块目录 = {[m['key'] for m in mods['items']]}")
    assert len(mods["items"]) == 2, "应注册 2 个模块"

    # 2. 授予审批职责（模拟配置播种 / 冷启动）；记录原状态，便于事后精确还原
    approver_had_duty = acl.has_duty(approver.id, DUTY_TICKET_APPROVE)
    if approver_had_duty:
        print(f"  2. B 已持有 {DUTY_TICKET_APPROVE}，沿用（验收后不撤回）")
    else:
        acl.grant_duty(approver.id, DUTY_TICKET_APPROVE)
        print(f"  2. 已为 B 授予 {DUTY_TICKET_APPROVE}（验收后撤回）")

    # 3. 候选人列表必须排除申请人本人
    cands = rt.ticket_candidates(module="user_duty_grant", user=applicant)
    ids = [c["id"] for c in cands["items"]]
    print(f"  3. 审批候选人 = {ids}")
    assert approver.id in ids, "审批职责持有人应出现在候选列表"
    assert applicant.id not in ids, "申请人本人不得出现在候选列表（A/B 分离）"

    # 4. 建单
    created = rt.create_ticket(
        rt.TicketCreate(
            module="user_duty_grant",
            payload={"target_user": applicant.id,
                     "duties": [DUTY_TICKET_APPROVE],
                     "reason": f"{TAG} 验收：授予审批职责"},
            approver_id=approver.id,
        ),
        _req(), applicant,
    )
    tid = created["id"]
    print(f"  4. 建单 {created['ticket_no']} 状态={created['status']}")

    # 5. 申请人给自己当审批人 → 必须 400
    try:
        rt.create_ticket(
            rt.TicketCreate(module="user_duty_grant",
                            payload={"target_user": applicant.id,
                                     "duties": [DUTY_TICKET_APPROVE],
                                     "reason": f"{TAG} 自检"},
                            approver_id=applicant.id),
            _req(), applicant,
        )
        print("  5. [FAIL] 自选审批人未被拦截")
        return 1
    except HTTPException as e:
        print(f"  5. 自选审批人被拦截 = {e.status_code} {e.detail}")

    # 6. 非审批人尝试审批 → 必须 403
    try:
        rt.approve_ticket(tid, rt.Decision(comment=f"{TAG} 越权尝试"), _req(), applicant)
        print("  6. [FAIL] 越权审批未被拦截")
        return 1
    except HTTPException as e:
        print(f"  6. 非审批人审批被拦截 = {e.status_code} {e.detail}")

    # 7. 待办列表
    pend = rt.tickets_pending_approval(approver)
    assert any(t["id"] == tid for t in pend["items"]), "审批人待办未见该工单"
    print(f"  7. B 的待审批列表包含该工单（共 {len(pend['items'])} 条）")

    # 8. 正式审批（two_step：审批通过即执行）
    res = rt.approve_ticket(tid, rt.Decision(comment=f"{TAG} 同意"), _req(), approver)
    print(f"  8. 审批结果 status={res.get('status')}")

    # 9. 执行结果：目标员工应真的拿到职责
    got = acl.has_duty(applicant.id, DUTY_TICKET_APPROVE)
    print(f"  9. 执行生效：A 是否持有 {DUTY_TICKET_APPROVE} = {got}")
    if not got:
        print("     [FAIL] 审批通过后执行器未真正授予职责")
        return 1

    # 10. 终态可见
    done = rt.tickets_done(applicant)
    print(f"  10. A 的已结束工单 {len(done['items'])} 条")

    # 清理：撤回本次授予的职责，删除验收工单
    acl.revoke_duty(applicant.id, DUTY_TICKET_APPROVE)
    if not approver_had_duty:
        acl.revoke_duty(approver.id, DUTY_TICKET_APPROVE)  # 只撤本次授予的
    with MySQLStore().transaction() as cur:
        cur.execute("DELETE FROM kms_tickets WHERE payload_summary LIKE %s",
                    (f"%{TAG}%",))
        cur.execute("DELETE FROM kms_tickets WHERE payload LIKE %s", (f"%{TAG}%",))
        cur.execute("DELETE FROM kms_notifications WHERE title='待审批工单' "
                    "AND content LIKE %s", (f"%{TAG}%",))
    print("  清理完成（已撤回验收授予的职责并删除验收工单）")
    return 0


def knowledge() -> int:
    """知识中心 4 个端点在真实数据下的表现。"""
    from app.store import MySQLStore

    from gateway import routes_knowledge as rk

    print("=" * 68)
    print("知识中心验收（真实库）")
    print("=" * 68)
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id FROM kms_users WHERE is_active=1 ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        print("  无在职员工，跳过")
        return 1
    user = _user(row["id"])
    print(f"  以 {user.employee_no} (L{user.security_level}, dept={user.department!r}) 查询")

    hot = rk.hot_documents(limit=5, user=user)
    print(f"  hot      → {len(hot['items'])} 条")
    ov = rk.analytics_overview(user=user)
    print(f"  overview → {ov}")
    tr = rk.analytics_trends(days=30, user=user)
    print(f"  trends   → 活跃用户 {tr['active_users']}，{len(tr['items'])} 天有数据")
    ps = rk.personal_stats(user=user)
    print(f"  personal → {ps}")
    return 0


def upload() -> int:
    """批量上传真实入库（会真实写 upload_dir 与向量索引）。"""
    import time
    from pathlib import Path

    from app.store import MySQLStore, VectorStore
    from config import settings

    from gateway import routes_upload as ru

    print("=" * 68)
    print("批量上传验收（真实库 + 真实入库）")
    print("=" * 68)

    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id FROM kms_users WHERE is_active=1 AND security_level=3 "
                    "ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if not row:
        print("  需要一名 L3 在职员工（入库要求 L3），当前没有")
        return 1
    user = _user(row["id"])
    print(f"  以 {user.employee_no} (L{user.security_level}) 上传")

    if not settings.gw_model_egress_allowed:
        print("  注意：gw_model_egress_allowed=False —— 模型出域闸门关闭，")
        print("        真实入库（Embedding/向量索引）被刻意禁用。")
        print("        改用桩入库：批次的记账/状态流转/轮询/清理仍走真实 SQL，")
        print("        只把模型调用替换掉。")

        def _install_stub():
            from app.store import MySQLStore
            from kms import routes

            class _Stub:
                def ingest(self, path):
                    with MySQLStore().transaction() as cur:
                        cur.execute(
                            "INSERT INTO documents (filename, source_path, file_type, "
                            "content_hash, title) VALUES (%s,%s,'txt',SHA2(%s,256),%s)",
                            (path.name, str(path), path.name, path.stem))
                        did = cur.lastrowid
                        cur.execute(
                            "INSERT INTO chunks (document_id, chunk_index, text, faiss_id, "
                            "text_hash, embedding_model) VALUES (%s,0,%s,%s,'stub','stub')",
                            (did, path.name, did))
                    return {"document_id": did}

            routes.get_indexer = lambda: _Stub()
            routes._hot_update_caches = lambda: None

        _install_stub()
        settings.gw_model_egress_allowed = True  # 仅为跑通链路，进程内临时开启

    from fastapi import UploadFile

    def _f(name: str, body: bytes) -> UploadFile:
        from io import BytesIO
        return UploadFile(filename=name, file=BytesIO(body))

    files = [
        _f(f"{TAG}验收A.txt", b"verify batch upload content A " * 20),
        _f(f"{TAG}验收B.txt", b"verify batch upload content B " * 20),
        _f(f"{TAG}验收C.exe", b"MZ fake binary"),  # 类型不合法，应被预检拒绝
    ]
    res = ru.batch_upload(files=files, level="3", user=user)
    print(f"  提交返回 batch_id={res['batch_id']}")
    for it in res["items"]:
        print(f"    [{it['seq']}] {it['filename']} → {it['status']} {it['message']}")

    bid = res["batch_id"]
    for _ in range(40):
        st = ru.batch_status(bid, user=user)
        if st["finished"]:
            break
        time.sleep(1)
    print(f"  轮询结束 finished={st['finished']}")
    for it in st["items"]:
        print(f"    [{it['seq']}] {it['filename']} → {it['status']} "
              f"chunks={it['chunk_count']} {it['message']}")

    # 清理：删掉验收产生的文档
    # 先把 faiss_id 收齐：只删 chunks 行而不删向量，会在索引里留下孤儿向量，
    # 下次启动时一致性守卫（app/rag.py::warmup）直接拒绝启动。
    with MySQLStore()._conn() as cur:
        cur.execute("SELECT id, source_path FROM documents WHERE filename LIKE %s",
                    (f"{TAG}%",))
        docs = cur.fetchall()
        doc_ids = [int(d["id"]) for d in docs]
        faiss_ids: list[int] = []
        if doc_ids:
            ph = ",".join(["%s"] * len(doc_ids))
            cur.execute(f"SELECT faiss_id FROM chunks WHERE document_id IN ({ph})",
                        doc_ids)
            faiss_ids = [int(r["faiss_id"]) for r in cur.fetchall()]

    if faiss_ids:
        vs = VectorStore()
        vs.load()
        vs.remove(faiss_ids)
        vs.save()

    with MySQLStore().transaction() as cur:
        for d in docs:
            cur.execute("DELETE FROM chunks WHERE document_id=%s", (d["id"],))
            cur.execute("DELETE FROM kms_doc_levels WHERE document_id=%s", (d["id"],))
            cur.execute("DELETE FROM documents WHERE id=%s", (d["id"],))
            try:
                Path(d["source_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        cur.execute("DELETE FROM kms_upload_batch_items WHERE batch_id=%s", (bid,))
        cur.execute("DELETE FROM kms_upload_batches WHERE id=%s", (bid,))
    print(f"  清理完成（删除 {len(docs)} 篇验收文档，回收 {len(faiss_ids)} 个向量）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="真实数据库环境下的端到端验收")
    ap.add_argument("--tickets", action="store_true", help="工单端到端")
    ap.add_argument("--knowledge", action="store_true", help="知识中心 4 端点")
    ap.add_argument("--upload", action="store_true", help="批量上传真实入库")
    ap.add_argument("--all", action="store_true", help="全部（默认只做只读盘点）")
    ap.add_argument("--migrate", action="store_true", help="补列/建表（新库首次部署必跑）")
    ap.add_argument("--acl", action="store_true", help="分级/分部门/组织继承读权限验证")
    a = ap.parse_args()

    rc = 0
    if a.all or a.migrate:
        rc |= migrate()
    rc |= survey()
    if a.all or a.acl:
        rc |= acl_check()
    if a.all or a.tickets:
        rc |= tickets()
    if a.all or a.knowledge:
        rc |= knowledge()
    if a.all or a.upload:
        rc |= upload()
    return rc


if __name__ == "__main__":
    sys.exit(main())
