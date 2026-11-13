/* ===== app/api.js · 工作台数据访问层 =====
 *
 * 继承既有 KmsClient（js/sdk/kms-client.js），只补齐工作台专有端点。
 * 为什么继承而不是重写：SDK 是三处消费方（工作台 / 嵌入组件 / MCP 控制台）
 * 的单一客户端，重写一份就等于同一后端能力出现两套调用，日后必然漂移。
 *
 * 端点归属（与后端路由一一对应，改动前请核对）：
 *   gateway/routes_kms.py       /documents /chat /conversations /governance
 *   gateway/routes_knowledge.py /knowledge/*
 *   gateway/routes_tickets.py   /tickets/*  /notifications/*
 *   gateway/routes_upload.py    /documents/batch-upload
 *   gateway/routes_embed.py     /health
 *   kms/admin_routes.py         /stats /audit/*
 */
import { authHeaders, clearToken, fetchJSON, postForm, streamSSE } from "@kms/core/http.js";
import { KmsClient } from "@kms/sdk/kms-client.js";

export class AppClient extends KmsClient {
  /** 带查询串的 GET；空值参数不拼进 URL，避免出现 ?limit=undefined */
  _get(path, params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null && v !== "")
    ).toString();
    return fetchJSON(this.base + path + (qs ? `?${qs}` : ""), {
      onUnauthorized: this.onUnauthorized,
    });
  }

  _post(path, body = {}, method = "POST") {
    return fetchJSON(this.base + path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      onUnauthorized: this.onUnauthorized,
    });
  }

  /* ================= 系统 ================= */
  stats() { return this._get("/stats"); }
  health() { return this._get("/health"); }

  /* ================= 文档 ================= */
  /** 审批人候选：按「目标密级 + 目标归属部门数组」派生，已排除申请人本人。
   *  后端 routes_kms.py:319；前端拿到后供申请人自选，不自由填写。 */
  approverCandidates(classification, departments = []) {
    return this._get("/documents/approver-candidates", {
      classification,
      departments: JSON.stringify(departments),
    });
  }

  /** 批量上传：返回批次 id，进度另行轮询 uploadBatch()。
   *  字段名必须与后端 routes_upload.py:319 的 Form 形参一致：
   *  level / departments(JSON 数组) / approver_id——写成 classification 会被后端
   *  当成未传，密级回落本人职级、部门回落本人部门、审批人随机指派，
   *  上传区三个联动下拉框全部失效（老版 app.js:1008 即此口径）。 */
  batchUpload(files, level, departments = [], approverId = null) {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    if (level != null) form.append("level", String(level));
    if (departments && departments.length) form.append("departments", JSON.stringify(departments));
    if (approverId != null) form.append("approver_id", String(approverId));
    return postForm(`${this.base}/documents/batch-upload`, form);
  }

  uploadBatch(batchId) { return this._get(`/upload/batches/${batchId}`); }

  /** 为已有文档上传新版本（显式更新入口）：走单文件接口 POST /documents。
   *  字段名与后端 routes_kms.upload_document 的 Form 形参一致——注意单文件
   *  接口密级字段是 classification（批量接口是 level，勿混）。
   *  target_document_id 指定目标 doc_id，文件名无需与原文件相同。 */
  uploadVersion(docId, file, classification, departments = [], approverId = null, reason = "") {
    const form = new FormData();
    form.append("file", file, file.name);
    if (classification != null) form.append("classification", String(classification));
    if (departments && departments.length) form.append("departments", JSON.stringify(departments));
    if (approverId != null) form.append("approver_id", String(approverId));
    form.append("target_document_id", String(docId));
    if (reason && reason.trim()) form.append("update_reason", reason.trim());
    return postForm(`${this.base}/documents`, form);
  }

  versions(docId) { return this._get(`/documents/${docId}/versions`); }

  /** 申请回滚（走审批，不直接生效）。approverId 留空则后端随机指派；
   *  指定时后端仍会在合格候选池里比对，池外一律 422。
   *
   *  classification / departments 是**申请人声明的目标态**（与「申请更新」
   *  同口径），不再由后端默默沿用文档当前值——工单上的「目标密级」必须是
   *  申请人写下、审批人据以复核的值，而不是系统从文档行里抄的。传 null
   *  才表示沿用当前值（兼容旧调用方）。 */
  rollback(docId, versionNo, approverId = null, reason = "",
           classification = null, departments = null) {
    const body = {};
    if (approverId != null) body.approver_id = approverId;
    if (reason && reason.trim()) body.reason = reason.trim();
    if (classification != null) body.classification = Number(classification);
    if (Array.isArray(departments)) body.departments = departments;
    return this._post(`/documents/${docId}/versions/${versionNo}/rollback`, body);
  }

  /** 下载原文：端点要 Bearer 鉴权，故走 fetch 取 blob，不能用裸 <a href> */
  async download(docId, filename = "") {
    const res = await fetch(`${this.base}/documents/${docId}/download`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`下载失败 (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `document-${docId}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /* ================= 个人统计 ================= */
  /** 个人中心的问答/文档统计（原知识中心栏目已下线，仅保留个人页在用的这一个） */
  knowledgePersonalStats() { return this._get("/knowledge/personal/stats"); }

  /* ================= 会话 ================= */
  /** 带会话续接的流式问答。
   *  为什么不直接用 SDK 的 askStream()：它只发 {question}，不带 session_id，
   *  后端于是每轮都新开一个会话（uuid4），多轮上下文根本接不上。
   *  这里显式带上 session_id，让同一会话里的追问能命中历史。 */
  askStreamIn(question, sessionId, onEvent) {
    const body = { question };
    if (sessionId) body.session_id = sessionId;
    return streamSSE(`${this.base}/chat?stream=true`, body, onEvent, {});
  }

  conversations(limit = 50) { return this._get("/conversations", { limit }); }
  conversationHistory(sessionId, limit = 100) {
    return this._get(`/conversations/${encodeURIComponent(sessionId)}/history`, { limit });
  }

  /* ================= 审计（运营审计只读） ================= */
  auditActions() { return this._get("/audit/audit-actions"); }
  auditLogs(params = {}) { return this._get("/audit/audit-logs", params); }
  ingestStatus() { return this._get("/audit/ingest-status"); }
  hrSyncHistory(limit = 20) { return this._get("/audit/hr-sync/history", { limit }); }

  /* ================= 工单 ================= */
  ticketModules() { return this._get("/tickets/modules"); }
  ticketOptions() { return this._get("/tickets/options"); }
  ticketsMine() { return this._get("/tickets/mine"); }
  ticketsPendingApproval() { return this._get("/tickets/pending-approval"); }
  ticketsDone() { return this._get("/tickets/done"); }
  ticketsRecycleBin() { return this._get("/tickets/recycle-bin"); }
  ticket(id) { return this._get(`/tickets/${id}`); }

  /** 待审附件下载：GET /tickets/{id}/files/{index} 返回文件流。
   *  端点要 Bearer 鉴权，走 fetch 取 blob；文件名优先取
   *  content-disposition（后端 RFC5987 编码），兜底 ticket_{id}_file_{n}。 */
  async ticketFile(ticketId, index) {
    const res = await fetch(`${this.base}/tickets/${ticketId}/files/${index}`, {
      headers: authHeaders(),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(typeof d.detail === "string" ? d.detail : `下载失败 (${res.status})`);
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    let name = `ticket_${ticketId}_file_${index}`;
    const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i);
    if (m) { try { name = decodeURIComponent(m[1]); } catch { name = m[1]; } }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /** 发布审批（governance 体系）：所有层级上传/改属性自动触发的审批进度。
   *  返回我发起的 + 被指派给我审批的；后端 routes_kms.py:776。
   *  status 可选过滤（如 "pending" / "approved,rejected"）：
   *  「发布审批」tab 只看进行中，已决策历史归入「已完成」，避免重复展示。 */
  governanceRequests(status) {
    return this._get("/governance/requests" + (status ? `?status=${encodeURIComponent(status)}` : ""));
  }

  /** 发布审批决策：approve=true/false；仅被指派的审批人可调。 */
  decideRequest(requestId, approve) {
    return this._post(`/governance/requests/${encodeURIComponent(requestId)}/decision`,
                      { approve });
  }

  /** module 必填；approver_id 留空则由后端按「同部门 + 职级够」指派 */
  createTicket(module, payload = {}, approverId = null) {
    const body = { module, payload };
    if (approverId != null) body.approver_id = approverId;
    return this._post("/tickets", body);
  }

  approveTicket(id, comment = "") { return this._post(`/tickets/${id}/approve`, { comment }); }
  rejectTicket(id, reason = "", comment = "") {
    return this._post(`/tickets/${id}/reject`, { comment, reason });
  }
  cancelTicket(id) { return this._post(`/tickets/${id}/cancel`, {}); }
  /* 注：execute/refuse/executor-candidates 为两段式前的旧执行人接口，
   *  审批通过即系统自动执行，无执行人角色，前端不提供入口。 */

  /* ================= 通知 ================= */
  notifications() { return this._get("/notifications"); }
  unreadCount() { return this._get("/notifications/unread-count"); }
  markRead(id) { return this._post(`/notifications/${id}/read`, {}, "POST"); }
  markAllRead() { return this._post("/notifications/read-all", {}); }

  /* ================= 认证 ================= */
  /** 服务端登出（清理会话）；本地令牌无论如何都清掉 */
  async logoutApi() {
    try { await this._post("/auth/logout", {}); } catch { /* 服务端失败也要清本地 */ }
    clearToken();
  }
}

/** 默认单例 */
export const api = new AppClient();
