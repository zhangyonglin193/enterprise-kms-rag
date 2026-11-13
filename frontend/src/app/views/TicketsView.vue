<script setup>
/* 工单中心（两段式：申请 → 审批，审批通过即系统自动执行，无执行人角色）。
 *
 * 三个 tab 的职责：
 * - mine      我的申请：我发起过的全部单据（含已办结，进行中优先）——
 *             提交过的每一次都能在这里跟踪到底，不会「提完就消失」
 * - approval  待我审批：待我处理的两类单据（tickets 工单 + governance 发布申请），
 *             用户无需感知后端体系差异，统一在此审批
 * - done      已完成：两个体系的全部终态记录（含我发起与我审批的）
 *
 * 详情弹窗对齐旧版 renderTicketFull / renderTicketBlind 的完整口径：
 * 关联文档快照表（含 BLP 可读性判定与内容预览）、待审附件下载、
 * 原始/审批双哈希、审批意见、执行结果、驳回原因、核验清单；
 * payload 为 null 且带核验清单时进入盲视图（不展示申请内容）。 */
import { ref, computed, onMounted, watch } from "vue";
import { api } from "../api.js";
import { me, state, toast, withBusy } from "../store.js";
import DocDetailModal from "../components/DocDetailModal.vue";

const tabs = [
  { key: "mine", label: "我的申请", load: loadMine },
  // 待我审批 = 两体系合并：tickets 工单 + governance 发布申请（用户不感知体系差异）
  { key: "approval", label: "待我审批", load: loadApproval },
  // 已完成 = tickets 终态工单 + governance 已决策发布申请，统一为办结历史
  { key: "done", label: "已完成", load: loadDone },
];
const tab = ref("mine");
const rows = ref([]);
const loading = ref(false);
const busy = ref(false);

/** 详情弹窗：ticket 为 GET /tickets/{id} 的完整对象 */
const dlg = ref(null);
/** 文档详情子弹窗：{ id, classification } */
const docDlg = ref(null);

/** 工单模块 → 中文短标签（后端 label 是「批量删除文档」这类冗长名，
 *  表格里只需要看得出「这是一次删除」）。 */
const TICKET_TYPE_LABEL = {
  doc_batch_delete: "删除文档",
  doc_restore: "恢复文档",
  doc_upload: "上传文档",
  doc_update: "更新文档",
};

/** 发布类申请的动作类型 → 中文标签。
 *  没有这层映射，上传、换版本、改属性、回滚在列表里全是「发布审批」，
 *  用户根本看不出自己那条记录到底是哪一次操作。 */
const ACTION_LABEL = {
  upload: "上传入库",
  update_version: "更新版本",
  update_policy: "变更属性",
  rollback: "版本回滚",
};

/** tickets 体系的行 → 统一展示结构（与 governance 行同构，便于「已完成」合并渲染） */
function ticketRow(x) {
  return {
    kind: "ticket", raw: x, id: x.id,
    no: x.ticket_no || `#${x.id}`,
    type: TICKET_TYPE_LABEL[x.module] || x.module_label || x.module,
    applicant: x.applicant?.name || x.applicant?.employee_no || "—",
    approver: x.approver?.name || x.approver?.employee_no || "—",
    status: x.status, label: x.status_label || STATUS[x.status] || x.status,
    closed_at: x.executed_at || x.created_at,
  };
}

/** governance 行 → 统一展示结构（与 tickets 行同构，便于各 tab 混排渲染） */
function govRow(r) {
  const p = policyOf(r);
  const note = String(p.reason || "");
  // action 是后加的字段：老记录里没有，退回从申请理由推断（否则历史上传
  // 全部显示为「发布审批」，用户会以为它们和换版本、改属性是同一种操作）。
  const action = r.action || p.action
    || (note.includes("回滚") ? "rollback"
      : note.includes("上传入库") ? "upload" : "");
  // 回滚与上传/换版本同属内容变更，同样走真实审批：审批人列显示实际操作人，
  // 不再有「无需审批」特例（那套特例来自旧的「回滚直接生效 + 事后补录」）。
  return {
    kind: "gov", raw: r, id: r.id,
    no: r.title || r.filename || `#${r.document_id}`,
    type: ACTION_LABEL[action] || "发布审批",
    action,
    reason: note,
    applicant: r.requester_name || r.requester_no || "—",
    approver: r.approver_name || r.approver_no || "—",
    status: r.status, label: PSTATUS[r.status] || r.status,
    closed_at: r.created_at,
  };
}

function formatDepartments(departments, fallback) {
  let list = departments;
  if (typeof list === "string") {
    try { list = JSON.parse(list); } catch { list = []; }
  }
  if (Array.isArray(list) && list.length) return list.join(", ");
  if (fallback && fallback !== "*") return fallback;
  if (fallback === "*") return "不限部门";
  return "—";
}

function formatPolicyDepartments(policy) {
  if (!policy) return "—";
  return formatDepartments(policy.departments, policy.owner_department);
}

async function mapTicketRows(p) {
  return { items: (p?.items ?? []).map(ticketRow) };
}

/** 我的申请 = 我发起过的全部单据（含已办结），进行中排前面。
 *
 * 不能只留 pending：单据一旦被审批，就从列表里彻底消失，用户回头想看
 * 「我提过什么、结果如何」无处可查（只能去「已完成」里翻全量历史）。
 * tickets 侧后端本就按 applicant_id 返回全部；governance 侧需显式过滤掉
 * 「指派我审批」的单子——那类归「待我审批」，不重复占位。 */
async function loadMine() {
  const [t, g] = await Promise.all([
    api.ticketsMine().catch(() => ({ items: [] })),
    api.governanceRequests().catch(() => ({ items: [] })),
  ]);
  const ticketRows = (t?.items ?? []).map(ticketRow);
  const govRows = (g?.items ?? [])
    .filter((r) => Number(r.requested_by) === Number(state.user?.id))
    .map(govRow);
  // 进行中优先，其余按时间倒序，便于一眼看出哪些还没走完
  const rank = (x) => (x.status === "pending" ? 0 : 1);
  const items = [...ticketRows, ...govRows].sort((a, b) =>
    rank(a) - rank(b)
    || String(b.closed_at || "").localeCompare(String(a.closed_at || "")));
  return { items };
}

/** 待我审批 = 两体系合并：tickets 待我审批的工单 + governance 待我审批的发布申请 */
async function loadApproval() {
  const [t, g] = await Promise.all([
    api.ticketsPendingApproval().catch(() => ({ items: [] })),
    api.governanceRequests("pending").catch(() => ({ items: [] })),
  ]);
  const ticketRows = (t?.items ?? []).map(ticketRow);
  // governance 返回「我发起的 OR 指派我的」：这里只留指派我审批的
  const govRows = (g?.items ?? [])
    .filter((r) => r.status === "pending"
      && Number(r.approver_id) === Number(state.user?.id))
    .map(govRow);
  return { items: [...ticketRows, ...govRows] };
}

/** 「已完成」：并行拉两个体系的办结记录，统一行结构后合并 */
async function loadDone() {
  const [t, g] = await Promise.all([
    api.ticketsDone().catch(() => ({ items: [] })),
    api.governanceRequests("approved,rejected").catch(() => ({ items: [] })),
  ]);
  const govRows = (g?.items ?? []).map(govRow);
  return { items: [...(await mapTicketRows(t)).items, ...govRows] };
}

/** 工单状态 → 中文标签（与后端 TICKET_STATUS_* 对齐，无执行人状态） */
const STATUS = {
  pending: "待审批", approved: "已批准", rejected: "已驳回",
  executed: "已执行", cancelled: "已撤销", timeout: "已超时", tampered: "已篡改",
};
/** 工单状态 → 徽章配色（BEM 命名，对齐旧版 ticketStatusBadge 的色阶） */
const STATUS_BADGE = {
  pending: "badge--warn", approved: "badge--info", executed: "badge--ok",
  rejected: "badge--err", timeout: "badge--err", tampered: "badge--err",
  cancelled: "badge--neutral",
};
/** 发布审批（governance request）状态 → 中文标签 */
const PSTATUS = { pending: "待审批", approved: "已通过", rejected: "已驳回" };
/** 发布审批状态 → 徽章配色 */
const PSTATUS_BADGE = { pending: "badge--warn", approved: "badge--ok", rejected: "badge--err" };

/** 阶段：把两套体系的一堆状态收敛成用户只需要看懂的三档。
 *
 *   pending + 指派我批 → 待我审批
 *   pending            → 进行中（在别人手上）
 *   其余终态           → 已完成
 *
 * 具体结果（已通过 / 已驳回 / 已执行 / 已超时…）仍保留在 title 提示里：
 * 只给三档时看不出「已完成」到底是成了还是被驳了，必须留一条退路。 */
function stageOf(t) {
  if (t.status === "pending") {
    return canDecide(t.raw)
      ? { text: "待我审批", cls: "badge--warn" }
      : { text: "进行中", cls: "badge--info" };
  }
  const bad = ["rejected", "timeout", "tampered"];
  return { text: "已完成", cls: bad.includes(t.status) ? "badge--err" : "badge--ok" };
}

/** 当前 tab 的阶段统计（均基于已加载的行，不做额外请求） */
const summary = computed(() => {
  const out = { running: 0, mine: 0, done: 0 };
  for (const t of rows.value) {
    const { text } = stageOf(t);
    if (text === "待我审批") out.mine += 1;
    else if (text === "进行中") out.running += 1;
    else out.done += 1;
  }
  return out;
});

/** 空态文案：按 tab 区分 */
const emptyText = computed(() =>
  tab.value === "done" ? "暂无已办结记录"
    : tab.value === "approval" ? "暂无待我审批的单据"
      : "暂无申请记录");

async function load() {
  loading.value = true;
  try {
    const fn = tabs.find(t => t.key === tab.value)?.load;
    if (fn) rows.value = (await fn())?.items ?? [];
  } catch (e) {
    rows.value = [];
    toast("加载失败：" + (e?.message || e), "error");
  } finally { loading.value = false; }
}

/** governance request 的 policy 是 JSON 字符串，解析出目标密级/部门/理由 */
function policyOf(r) {
  try { return typeof r.policy === "string" ? JSON.parse(r.policy) : (r.policy || {}); }
  catch { return {}; }
}

/** 发布申请详情弹窗：raw 为列表行（字段已够展示，无需再拉接口） */
const govDlg = ref(null);
function openGov(r) { govDlg.value = r; }

/** 发布申请详情弹窗：下载文档原文（后端对审批人/上传者放行，含未发布草稿） */
async function downloadGovDoc() {
  try {
    await api.download(Number(govDlg.value.document_id),
      govDlg.value.title || govDlg.value.filename || "");
  } catch (e) { toast("下载失败：" + (e?.message || e), "error"); }
}

/** 发布审批行：当前用户是否为被指派审批人且尚未处理 */
function canDecide(r) {
  return tab.value === "approval" && r.status === "pending"
    && Number(r.approver_id) === Number(state.user?.id);
}

async function decidePublish(r, approve) {
  if (busy.value) return;
  busy.value = true;
  try {
    await api.decideRequest(r.id, approve);
    toast(approve ? "已通过" : "已驳回", approve ? "ok" : "info");
    govDlg.value = null;
    await load();
  } catch (e) { toast((approve ? "通过" : "驳回") + "失败：" + (e?.message || e), "error"); }
  finally { busy.value = false; }
}

/* ================= 详情弹窗 ================= */

/** 打开详情：先以列表行占位（标题即时反馈），再拉完整对象。
 *  view=true 只读（详情按钮）；false 进入决策态（审批/撤销）。
 *
 *  这里**必须**总是拉详情：列表行只保证 ticket_no / status 等摘要字段，
 *  can_approve / can_cancel 由详情按当前用户判定，缺了它弹窗只剩
 *  「当前身份无待办操作」，审批人点「审批」进来却看不到通过按钮。 */
async function open(row, view = false) {
  dlg.value = {
    ticket: row.raw || row, view, loading: true,
    comment: "", reason: "",
  };
  await fetchDetail(row.id);
}

async function openTicketById(id) {
  dlg.value = { ticket: { id }, view: false, loading: true, comment: "", reason: "" };
  await fetchDetail(id);
}

async function fetchDetail(id) {
  try {
    const t = await withBusy(() => api.ticket(id));
    if (dlg.value) dlg.value.ticket = t;
  } catch (e) {
    toast("工单详情加载失败：" + (e?.message || e), "error");
    dlg.value = null;
  } finally {
    if (dlg.value) dlg.value.loading = false;
  }
}

/** 盲视图判据：payload 为 null 且带核验清单（审批人不应看到申请内容） */
const isBlind = computed(() =>
  dlg.value?.ticket?.payload == null && !!dlg.value?.ticket?.qualification_checklist
);
const isDeleteTicket = computed(() => dlg.value?.ticket?.module === "doc_batch_delete");
const refs = computed(() => dlg.value?.ticket?.doc_references || []);
/** 快照机制上线前的老工单：doc_references 为实时查询结果而非冻结快照 */
const liveOnly = computed(() => refs.value.some((r) => r.snapshot === false));

/** 人名（工号）——与旧版 ticketPerson 同构 */
function person(p) {
  return p ? `${p.name || p.username || ""}（${p.no || p.employee_no || ""}）` : "—";
}
const fmt = (s) => (s || "").replace("T", " ").slice(0, 19);

/** 审批决策：approve 走 comment，reject 走 reason（必填 ≥2 字） */
async function decide(action) {
  const t = dlg.value?.ticket;
  if (!t || busy.value) return;
  if (action === "reject" && (dlg.value.reason || "").trim().length < 2) {
    toast("请填写驳回原因（至少 2 个字）", "error");
    return;
  }
  busy.value = true;
  try {
    if (action === "approve") await api.approveTicket(t.id, dlg.value.comment.trim());
    else if (action === "reject") await api.rejectTicket(t.id, dlg.value.reason.trim());
    else if (action === "cancel") await api.cancelTicket(t.id);
    toast(action === "approve" ? "已审批通过" : action === "reject" ? "已驳回" : "已撤回", "ok");
    dlg.value = null;
    await load();
  } catch (e) {
    toast("操作失败：" + (e?.message || e), "error");
  } finally { busy.value = false; }
}

/** 待审附件下载（Blob 流，文件名取 content-disposition） */
async function downloadFile(ticketId, index) {
  try { await api.ticketFile(ticketId, index); }
  catch (e) { toast("下载失败：" + (e?.message || e), "error"); }
}

/* 通知跳转：App.vue 通知面板点击带 ticket_id 的通知 →
 * 切到工单视图并直接打开对应工单详情（清空标记防重复触发） */
watch(
  () => state.jumpTicketId,
  (id) => {
    if (id == null) return;
    state.jumpTicketId = null;
    tab.value = "mine";
    openTicketById(id);
  }
);

onMounted(load);
defineExpose({ load });
</script>

<template>
  <!-- 根元素不挂 .view：该类自带 display:none/.active 切换，App.vue 外层已包一层，
       这里再挂会让整个工单中心永远 display:none（渲染空白）——见 App.vue 内注释 -->
  <div>
    <p class="form-hint" style="margin:0 0 10px">
      每一次文档操作都会在这里留痕：上传入库、更新版本、变更属性、版本回滚、删除文档、恢复文档。
      状态只有三种——「进行中」表示已提交、审批人还在处理；「待我审批」表示该你处理了；「已完成」表示已办结（具体通过还是驳回见状态列悬停提示）。
    </p>

    <nav class="tabs">
      <button v-for="t in tabs" :key="t.key" class="tab"
              :class="{ active: tab === t.key }" @click="tab = t.key; load()">
        {{ t.label }}
      </button>
    </nav>

    <!-- 阶段统计：让「还剩几条没走完」一眼可见，不必自己数表格 -->
    <p v-if="!loading && rows.length" class="form-hint" style="margin:0 0 8px">
      进行中 {{ summary.running }} 条 · 待我审批 {{ summary.mine }} 条 · 已完成 {{ summary.done }} 条
    </p>

    <div v-if="loading" class="empty">加载中…</div>

    <!-- 统一表格：三 tab 共用，tickets / governance 行同构混排 -->
    <table v-else class="table">
      <thead>
        <tr>
          <th>对象</th><th>操作类型</th><th>申请人</th><th>审批人</th><th>阶段</th>
          <th>{{ tab === "done" ? "办结时间" : "创建时间" }}</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!rows.length"><td colspan="7" class="empty">{{ emptyText }}</td></tr>
        <tr v-for="t in rows" :key="t.id">
          <td style="font-weight:500">{{ t.no }}</td>
          <td>{{ t.type }}</td>
          <td>{{ t.applicant }}</td>
          <td>{{ t.approver }}</td>
          <!-- 阶段列：三档收敛 + title 保留具体结果（已通过 / 已驳回 / 已执行） -->
          <td>
            <span class="badge" :class="stageOf(t).cls" :title="`当前状态：${t.label}`">{{ stageOf(t).text }}</span>
          </td>
          <td>{{ (t.closed_at || "").replace("T", " ").slice(0, 16) }}</td>
          <td>
            <template v-if="t.kind === 'ticket'">
              <button v-if="tab === 'approval' && t.status === 'pending'" class="btn btn-sm btn-primary"
                      @click="open(t.raw)">审批</button>
              <button v-else class="btn btn-sm" @click="open(t.raw, true)">详情</button>
              <button v-if="tab === 'mine' && t.status === 'pending'" class="btn btn-sm btn-danger"
                      @click="open(t.raw)">撤销</button>
            </template>
            <template v-else-if="canDecide(t.raw)">
              <button class="btn btn-sm" @click="openGov(t.raw)">详情</button>
              <button class="btn btn-sm btn-primary" :disabled="busy"
                      @click="decidePublish(t.raw, true)">通过</button>
              <button class="btn btn-sm btn-danger" :disabled="busy"
                      @click="decidePublish(t.raw, false)">驳回</button>
            </template>
            <!-- 发布申请：任何视角都可查看详情（内容含密级/部门/理由） -->
            <button v-else class="btn btn-sm" @click="openGov(t.raw)">详情</button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 工单详情/决策弹窗（仅 tickets 体系） -->
    <div v-if="dlg" class="modal active">
      <div class="modal-mask" @click="dlg = null" />
      <div class="modal-dialog" style="max-width:820px">
        <div class="modal-head">
          <h3>工单 {{ dlg.ticket.ticket_no || `#${dlg.ticket.id}` }}</h3>
          <button class="modal-close" @click="dlg = null">✕</button>
        </div>
        <div class="modal-body">

        <div v-if="dlg.loading" class="empty">加载中…</div>

        <template v-else>
          <!-- 盲视图：申请内容隐藏，仅按核验清单确认 -->
          <div v-if="isBlind" class="ticket-blind-hint">
            <span>🔒 盲执行视图：申请内容已隐藏，请按核验清单逐项确认后执行。</span>
          </div>

          <!-- 基本信息 -->
          <div class="info-list" style="margin-bottom:18px">
            <div class="info-item"><span class="info-key">工单号</span><span class="info-val">{{ dlg.ticket.ticket_no || `#${dlg.ticket.id}` }}</span></div>
            <div class="info-item"><span class="info-key">模块</span><span class="info-val">{{ dlg.ticket.module_label || dlg.ticket.module }}</span></div>
            <div class="info-item">
              <span class="info-key">状态</span>
              <span class="info-val"><span class="badge" :class="STATUS_BADGE[dlg.ticket.status] || 'badge--neutral'">
                {{ dlg.ticket.status_label || STATUS[dlg.ticket.status] || dlg.ticket.status }}</span></span>
            </div>
            <div class="info-item"><span class="info-key">申请人</span><span class="info-val">{{ person(dlg.ticket.applicant) }}</span></div>
            <div class="info-item"><span class="info-key">审批人</span><span class="info-val">{{ person(dlg.ticket.approver) }}</span></div>
            <div class="info-item"><span class="info-key">创建时间</span><span class="info-val">{{ fmt(dlg.ticket.created_at) }}</span></div>
            <div v-if="dlg.ticket.approved_at" class="info-item"><span class="info-key">审批时间</span><span class="info-val">{{ fmt(dlg.ticket.approved_at) }}</span></div>
            <div v-if="dlg.ticket.executed_at" class="info-item"><span class="info-key">执行时间</span><span class="info-val">{{ fmt(dlg.ticket.executed_at) }}</span></div>
          </div>

          <!-- 关联文档快照表：无论工单是否已执行删除，都能看清操作对象 -->
          <template v-if="refs.length">
            <h4 style="margin-bottom:8px;font-size:14px">关联文档（{{ refs.length }} 篇）</h4>
            <p v-if="liveOnly" class="form-hint" style="margin-bottom:6px">
              该工单建于快照机制上线前，以下为实时查询结果（非冻结快照）
            </p>
            <div class="table-wrap" style="margin-bottom:18px">
              <table class="table">
                <thead><tr><th style="width:48px">ID</th><th>文件名</th><th style="width:64px">密级</th><th style="width:110px">归属部门</th><th style="width:70px">状态</th><th style="width:110px">操作</th></tr></thead>
                <tbody>
                  <template v-for="r in refs" :key="r.id">
                    <tr>
                      <td>{{ r.id }}</td>
                      <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                          :title="r.title || r.filename">{{ r.filename || `文档 #${r.id}` }}</td>
                      <td>{{ me.levelName(r.classification ?? 0) }}</td>
                      <td style="max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ formatDepartments(r.departments, r.owner_department) }}</td>
                      <td>
                        <span class="status-pill" :class="r.exists === false ? 'txt' : (r.recycled ? 'warn' : 'ok')"
                              :title="r.exists === false ? '文档已被物理销毁' : (r.recycled ? '已移入回收站，宽限期内可发起恢复工单找回' : '文档仍存在')">
                          <span class="dot" />{{ r.exists === false ? "已销毁" : (r.recycled ? "回收站" : "在库") }}
                        </span>
                      </td>
                      <td>
                        <button v-if="r.exists !== false && r.can_view" class="btn btn-sm"
                                @click="docDlg = { id: r.id, classification: r.classification ?? 0 }">📄 查看内容</button>
                        <span v-else-if="r.exists !== false" class="form-hint" title="安全职级不足以读取该文档正文">🔒 不可读</span>
                        <span v-else class="form-hint">已物理销毁</span>
                      </td>
                    </tr>
                    <tr v-if="r.snippet">
                      <td colspan="6" style="background:var(--panel-bg);padding:6px 10px">
                        <div class="form-hint" style="margin:0;max-height:60px;overflow:hidden">{{ r.snippet }}</div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </template>

          <!-- 申请内容（盲视图隐藏） -->
          <template v-if="!isBlind">
            <h4 style="margin-bottom:8px;font-size:14px">申请内容</h4>
            <div v-if="dlg.ticket.payload_summary" class="ticket-summary" style="margin-bottom:12px">
              <strong>摘要：</strong>{{ dlg.ticket.payload_summary }}
            </div>
            <details v-if="dlg.ticket.payload" style="margin-bottom:14px">
              <summary class="form-hint">原始 payload（审计留痕，可折叠）</summary>
              <pre class="ticket-payload">{{ JSON.stringify(dlg.ticket.payload, null, 2) }}</pre>
            </details>
            <p v-if="!dlg.ticket.payload_summary && !dlg.ticket.payload" class="form-hint">（无申请内容）</p>

            <!-- 删除类工单风险提示 -->
            <div v-if="isDeleteTicket" class="form-hint" style="color:var(--c-err);font-weight:500;margin:8px 0">
              ⚠️ 审批通过后系统将立即永久删除以上文档及其分块、密级记录与向量索引，此操作不可撤销。
            </div>
          </template>

          <!-- 待审附件 -->
          <div v-if="dlg.ticket.files?.length" class="ticket-files">
            <strong>待审文件：</strong>
            <button v-for="(f, i) in dlg.ticket.files" :key="i" class="btn btn-sm"
                    @click="downloadFile(dlg.ticket.id, i)">📎 {{ f.name || `文件${i + 1}` }}</button>
          </div>

          <!-- 哈希与意见（审计留痕） -->
          <div class="info-list" style="margin-top:12px">
            <div v-if="dlg.ticket.original_hash" class="info-item">
              <span class="info-key">原始哈希</span>
              <span class="info-val" style="font-family:var(--mono);font-size:11.5px;word-break:break-all">{{ dlg.ticket.original_hash }}</span>
            </div>
            <div v-if="dlg.ticket.approved_hash" class="info-item">
              <span class="info-key">审批哈希</span>
              <span class="info-val" style="font-family:var(--mono);font-size:11.5px;word-break:break-all">{{ dlg.ticket.approved_hash }}</span>
            </div>
            <div v-if="dlg.ticket.approve_comment" class="info-item">
              <span class="info-key">审批意见</span><span class="info-val">{{ dlg.ticket.approve_comment }}</span>
            </div>
            <div v-if="dlg.ticket.exec_result" class="info-item">
              <span class="info-key">执行结果</span><span class="info-val">{{ dlg.ticket.exec_result }}</span>
            </div>
            <div v-if="dlg.ticket.reason" class="info-item">
              <span class="info-key">驳回/退回原因</span><span class="info-val">{{ dlg.ticket.reason }}</span>
            </div>
          </div>

          <!-- 核验清单 -->
          <div v-if="dlg.ticket.qualification_checklist" class="ticket-checklist">
            <h4 style="margin-bottom:8px;font-size:14px">执行核验清单</h4>
            <ul>
              <li v-for="(c, i) in dlg.ticket.qualification_checklist" :key="i">
                {{ typeof c === "string" ? c : (c.label || JSON.stringify(c)) }}
              </li>
            </ul>
          </div>

          <!-- 决策区：待我审批 → 通过/驳回；我的待审 → 撤回；否则只读 -->
          <template v-if="!dlg.view">
            <div v-if="dlg.ticket.can_approve" class="form-item" style="margin-top:14px">
              <label>审批意见（通过时选填）</label>
              <textarea v-model="dlg.comment" class="input" rows="2" placeholder="审批意见（可选）" />
            </div>
            <div v-if="dlg.ticket.can_approve" class="form-item">
              <label>驳回原因（驳回时必填）</label>
              <textarea v-model="dlg.reason" class="input" rows="2" placeholder="请说明驳回原因（将通知申请人）" />
            </div>
            <div class="modal-actions">
              <template v-if="dlg.ticket.can_approve">
                <button class="btn btn-primary" :disabled="busy" @click="decide('approve')">✅ 审批通过</button>
                <button class="btn btn-danger" :disabled="busy" @click="decide('reject')">驳回</button>
              </template>
              <button v-if="dlg.ticket.can_cancel" class="btn btn-danger" :disabled="busy" @click="decide('cancel')">撤回工单</button>
            </div>
            <p v-if="!dlg.ticket.can_approve && !dlg.ticket.can_cancel" class="form-hint">
              当前身份无待办操作，仅可查看。
            </p>
          </template>
        </template>

        <button class="btn btn-block" style="margin-top:12px" @click="dlg = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 发布申请详情弹窗（governance 体系，只读；审批人可顺带决策） -->
    <div v-if="govDlg" class="modal active">
      <div class="modal-mask" @click="govDlg = null" />
      <div class="modal-dialog" style="max-width:560px">
        <div class="modal-head">
          <h3>{{ ACTION_LABEL[govDlg.action || policyOf(govDlg).action] || "发布审批" }} · 详情</h3>
          <button class="modal-close" @click="govDlg = null">✕</button>
        </div>
        <div class="modal-body">
          <div class="info-list">
            <div class="info-item">
              <span class="info-key">文档</span>
              <span class="info-val">{{ govDlg.title || govDlg.filename || `#${govDlg.document_id}` }}</span>
            </div>
            <!-- 操作类型：没有这一行，上传 / 换版本 / 改属性 / 回滚在详情里
                 全都只写「发布申请详情」，用户根本认不出这条是哪一次操作 -->
            <div class="info-item">
              <span class="info-key">操作类型</span>
              <span class="info-val">
                {{ ACTION_LABEL[govDlg.action || policyOf(govDlg).action] || "发布审批" }}
              </span>
            </div>
            <div class="info-item">
              <span class="info-key">目标密级</span>
              <span class="info-val">{{ me.levelName(policyOf(govDlg).classification) }}</span>
            </div>
            <div class="info-item">
              <span class="info-key">归属部门</span>
              <span class="info-val">{{ formatPolicyDepartments(policyOf(govDlg)) }}</span>
            </div>
            <div class="info-item">
              <span class="info-key">操作说明</span>
              <span class="info-val">{{ policyOf(govDlg).reason || "—" }}</span>
            </div>
            <div class="info-item">
              <span class="info-key">申请人</span>
              <span class="info-val">
                {{ govDlg.requester_name ? `${govDlg.requester_name}（${govDlg.requester_no}）` : "—" }}
              </span>
            </div>
            <div class="info-item">
              <span class="info-key">审批人</span>
              <span class="info-val">
                {{ govDlg.approver_name ? `${govDlg.approver_name}（${govDlg.approver_no}）` : "未指派" }}
              </span>
            </div>
            <div class="info-item">
              <span class="info-key">状态</span>
              <span class="info-val">
                <span class="badge" :class="PSTATUS_BADGE[govDlg.status] || 'badge--neutral'">
                  {{ PSTATUS[govDlg.status] || govDlg.status }}</span>
              </span>
            </div>
            <div class="info-item">
              <span class="info-key">申请时间</span>
              <span class="info-val">{{ fmt(govDlg.created_at) }}</span>
            </div>
          </div>

          <!-- 查看正文 / 下载原文：均走后端鉴权——正文按 BLP + 草稿可见性，
               下载对审批人/上传者放行（含未发布草稿），其他人由后端拒绝 -->
          <div style="display:flex;gap:8px">
            <button class="btn" style="flex:1" @click="docDlg = {
              id: Number(govDlg.document_id),
              classification: policyOf(govDlg).classification ?? 0,
            }">📄 查看文档内容</button>
            <button class="btn" style="flex:1" @click="downloadGovDoc">⬇ 下载原文</button>
          </div>

          <!-- 被指派审批人可在详情内直接决策 -->
          <div v-if="canDecide(govDlg)" class="modal-actions">
            <button class="btn btn-primary" :disabled="busy"
                    @click="decidePublish(govDlg, true)">✅ 通过</button>
            <button class="btn btn-danger" :disabled="busy"
                    @click="decidePublish(govDlg, false)">驳回</button>
          </div>
          <p v-else-if="govDlg.status === 'pending'" class="form-hint">该申请审批中，请等待审批人处理。</p>

          <button class="btn btn-block" style="margin-top:12px" @click="govDlg = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 文档详情子弹窗（关联文档「查看内容」） -->
    <DocDetailModal v-if="docDlg" :doc-id="docDlg.id" :classification="docDlg.classification"
                    @close="docDlg = null" />
  </div>
</template>
