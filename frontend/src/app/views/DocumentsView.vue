<script setup>
/* 文档库。
 *
 * 三个联动下拉框的设计意图（与后端契约严格对齐）：
 *   ① 密级 —— 可写区间来自 policy.js writableRange()（BLP「不下写」：
 *      可写区间为 [本人职级, 系统最高密级]），不是前端自己枚举 L0~L3；
 *   ② 部门 —— 只能选本人所属部门或「*」（不限部门哨兵）。
 *      注意：**空串不是「不限」**，空串表示未登记归属，会让审批人候选池为空
 *      并最终 409（后端 DOC_DEPT_UNLIMITED = "*"）。
 *      **默认不预选任何部门**：默认帮用户勾上本人部门，会让「加选另一个部门」
 *      变成并集，审批人池里冒出本人部门的人——用户会认为系统没按他选的部门匹配。
 *   ③ 审批人 —— 只从「所选的归属部门 ∩ 职级≥密级 − 本人」里出，前后端同一判据
 *      （acl.approver_candidates）。不发部门就不发候选，后端不再回落本人部门。
 *
 * 删除为什么不是直删：后端**没有** DELETE /documents/{id} 路由（同路径只有
 * GET），历史上那个按钮一直是 404/405。删除改为提交 doc_batch_delete 工单，
 * 审批通过后由系统执行——破坏性动作走审批，治理强度反而比假直删更高。
 */
import { computed, onMounted, ref, watch } from "vue";

import { api } from "../api.js";
import { me, state, toast, withBusy } from "../store.js";
import StateBox from "../components/StateBox.vue";
import DocDetailModal from "../components/DocDetailModal.vue";

const PAGE_SIZE = 20;

const docs = ref([]);
const total = ref(0);
const offset = ref(0);
const keyword = ref("");
const error = ref("");
const selected = ref(new Set());

/* ---------- 上传区：三个联动下拉框 ---------- */
const files = ref([]);
const upLevel = ref(null);
// 归属部门：**默认不预选**。曾默认勾上本人部门，用户再点「财务管理部」时看到
// 的是两个高亮胶囊，以为是替换——实际是并集，于是审批人池里冒出了产品管理部的人，
// 用户只会认为「系统没按我选的部门匹配」。空数组不是「不限」，哨兵是 "*"。
const upDepts = ref([]);
const upApprover = ref(null);
const approvers = ref([]);
const approverHint = ref("");
const uploading = ref(false);

/* ---------- 逐文件入库进度（对齐旧版 uploadQueue 面板） ----------
 * 条目按提交顺序与服务端 batch.items 一一对应（后端保证有序返回，
 * 含类型不合法被拒的文件），状态机：pending → uploading → success/error。
 * 终态条目 8s 后自动清出队列，面板随之收起。 */
const uploadQueue = ref([]);
let uploadCleanTimer = null;

/** 可写密级区间；不可写（未登录/职级超上限）时为 null */
const writeRange = computed(() => me.writableRange());
const levelOptions = computed(() => {
  const r = writeRange.value;
  if (!r) return [];
  const [min, max] = r;
  const out = [];
  for (let lv = min; lv <= max; lv += 1) out.push(lv);
  return out;
});

/** 可选归属部门：取 /admin/departments 的完整列表（App.vue 启动时已加载，
 *  实测 9 项，且「*」不限部门哨兵**本就在列表里**，无需前端自己造）。
 *  曾只给「本人部门 + 自造 *」，结果列表里看不到其余 8 个部门——把文档
 *  归属到别的部门（进而由该部门审批）根本选不出来。
 *  字典未就绪时兜底为本人部门 + *，至少不让下拉框变空。 */
const deptOptions = computed(() => {
  const list = state.departments || [];
  if (list.length) {
    return list.map((d) => ({
      value: d.name,
      label: d.name === "*" ? "不限部门（全员可见）" : d.name,
    }));
  }
  const mine = state.user?.department || "";
  const out = mine ? [{ value: mine, label: mine }] : [];
  out.push({ value: "*", label: "不限部门（全员可见）" });
  return out;
});

/** 将文档行的归属部门归一化为数组（兼容新 departments JSON / 旧 owner_department）。*/
function resolveDepts(d) {
  let list = d?.departments;
  if (typeof list === "string") {
    try { list = JSON.parse(list); } catch { list = []; }
  }
  if (Array.isArray(list) && list.length) return list;
  const old = d?.owner_department;
  return old ? [old] : [];
}

/** 列表展示：多个部门逗号拼接，"*" 显为不限部门。*/
function fmtDepts(d) {
  const list = resolveDepts(d);
  if (!list.length) return "—";
  if (list.includes("*")) return "不限部门";
  return list.join(", ");
}

/** 文档状态 → 中文。
 *  draft 必须显式标出来：上传只意味着「进入草稿」，还没过发布审批、不进检索。
 *  直接显示英文 draft 时，用户会误以为上传失败了。 */
function statusLabel(s) {
  return { draft: "草稿（待审批）", published: "已发布", archived: "已归档",
           expired: "已过期" }[s] || s || "—";
}
function statusBadge(s) {
  return { draft: "badge--warn", published: "badge--ok",
           archived: "badge--neutral", expired: "badge--err" }[s] || "badge--neutral";
}

/** 点选归属部门胶囊：单击选中/再点取消；「不限」与其他部门互斥（与后端收敛一致）。*/
function toggleDept(arr, value) {
  const i = arr.indexOf(value);
  if (i >= 0) { arr.splice(i, 1); return; }              // 已选 -> 取消
  if (value === "*" || arr.includes("*")) arr.length = 0;  // 选中任一项时清空互斥项
  arr.push(value);
}

/** 审批人下拉框的占位文案：必须区分「还没选密级」「还没选部门」「选了但无候选」。
 *  早期统一写死一句「请先选定密级与部门」，用户分不清到底卡在哪一步。 */
const approverPlaceholder = computed(() => {
  if (approvers.value.length) return "请选择";
  if (upLevel.value == null) return "请先选定密级";
  if (!upDepts.value?.length) return "请先选定归属部门";
  return "该组合下无合格审批人";
});

/** 部门名归一化（与后端 normalize_department 同口径）：HR 台账里带空格的
 *  「综合 管理部」必须与「综合管理部」视为同一个部门。 */
function deptKey(v) {
  return String(v || "").replace(/[\s\u3000]+/g, "");
}

async function loadApprovers() {
  approvers.value = [];
  approverHint.value = "";
  if (upLevel.value == null || !upDepts.value?.length) return;
  try {
    const d = await api.approverCandidates(upLevel.value, upDepts.value);
    const raw = Array.isArray(d) ? d : d.items || [];
    // 候选池 = 所选归属部门 ∩ 职级≥密级 − 本人（后端 acl 单一事实源），**可以有很多人**。
    // 这里只额外做一次「部门归属」兜底：进程还是旧版、或库里有脏数据时，
    // 池子里可能混进所选部门之外的人——上传区选的是财务管理部，下拉框里就
    // 不该出现产品管理部。「不限部门」本就是全员候选，不筛。
    const wanted = new Set(upDepts.value.map(deptKey));
    const list = upDepts.value.includes("*")
      ? raw
      : raw.filter((a) => wanted.has(deptKey(a.department)));
    approvers.value = list;
    const dropped = raw.length - list.length;
    // 空池时的文案由后端给（它知道各部门在职最高职级），前端不再编一句笼统的
    // 「无合格审批人」——那句话解释不了「为何财务部的文档冒出产品部的人」。
    approverHint.value = list.length
      ? `所选部门内有 ${list.length} 位符合条件（职级≥L${upLevel.value}）：均属 `
        + `${d.departments?.length ? d.departments.join("、") : upDepts.value.join("、")}；`
        + "任选其一，留空则由系统在这个池内指派"
        + (dropped ? `；已剔除 ${dropped} 位不属于所选部门的候选` : "")
      : (d.reason || "该组合下无合格审批人");
  } catch (e) {
    approverHint.value = `审批人候选加载失败：${e.message || e}`;
  }
}

// 密级或部门一变，审批人候选立即重算；已选审批人若不在新池子里则清空，
// 避免提交一个后端必然 422 的组合。
watch([upLevel, upDepts], () => {
  upApprover.value = null;
  loadApprovers();
}, { deep: true });

function onPickFiles(e) {
  files.value = Array.from(e.target.files || []);
}

async function doUpload() {
  if (!files.value.length) { toast("请先选择文件", "error"); return; }
  if (upLevel.value == null) { toast("请选择密级", "error"); return; }
  if (!upDepts.value?.length) { toast("请选择归属部门", "error"); return; }
  uploading.value = true;
  // 先占位渲染（每文件一行），再整批提交——用户立即看到反馈，而非空白等待。
  // 注意：push 后必须从 uploadQueue.value 重新取引用——那是 reactive 代理，
  // 直接改原始对象（entries 里的裸引用）不会触发视图更新。
  const picked = [...files.value];
  const entries = picked.map((f) => ({
    name: f.name, status: "pending", statusText: "提交中", progress: 8,
  }));
  uploadQueue.value.push(...entries);
  const tracked = uploadQueue.value.slice(-entries.length);
  try {
    // 三项声明全部随表单提交：密级（level）/ 归属（departments JSON 数组）/
    // 审批人（approver_id）——省略任何一项都会让对应下拉框失效，
    // 后端将静默回落本人职级/部门并随机指派审批人。
    const res = await withBusy(() => api.batchUpload(picked, upLevel.value, upDepts.value, upApprover.value));
    toast(`已提交 ${picked.length} 个文件，入库进行中`, "ok");
    // 按提交顺序对齐服务端 items（含类型不合法被拒的文件）
    (res?.items || []).forEach((it, i) => {
      const t = tracked[i];
      if (!t) return;
      if (it.status === "failed") {
        t.status = "error";
        t.statusText = "✗ " + (it.message || "被拒绝");
        t.progress = 0;
      } else {
        t.status = "uploading";
        t.statusText = "排队中";
        t.progress = 25;
      }
    });
    files.value = [];
    upApprover.value = null;
    // 列表按 id 正序：新文档在末页，直接跳过去
    await gotoLast();
    // 入库是 202+后台线程：不轮询批次的话，用户立即刷新看不到新文档会误判失败
    if (res && res.batch_id != null) pollBatch(res.batch_id, tracked);
    else scheduleQueueCleanup();
  } catch (e) {
    tracked.forEach((t) => {
      if (t.status === "pending") { t.status = "error"; t.statusText = "✗ " + (e.message || e); }
    });
    toast(String(e.message || e), "error");
    scheduleQueueCleanup();
  } finally {
    uploading.value = false;
  }
}

/* ---------- 列表 ---------- */
/** 轮询后台入库进度：finished 由后端在整批处理完后置位；
 *  逐文件条目随轮询更新状态，列表在停止轮询时刷新一次。最长等约 4 分钟。 */
async function pollBatch(batchId, entries) {
  for (let i = 0; i < 160; i += 1) {
    await new Promise((r) => setTimeout(r, 1500));
    let b;
    try { b = await api.uploadBatch(batchId); } catch {
      entries.forEach((t) => {
        if (t.status === "uploading") { t.status = "error"; t.statusText = "✗ 状态查询失败"; }
      });
      break;
    }
    const items = Array.isArray(b && b.items) ? b.items : [];
    items.forEach((it, idx) => {
      const t = entries[idx];
      if (!t) return;
      if (it.status === "success") {
        t.status = "success";
        t.statusText = `✓ ${it.chunk_count} 分块${it.message ? `｜${it.message}` : ""}`;
        t.progress = 100;
      } else if (it.status === "skipped") {
        t.status = "success";
        t.statusText = "重复，已跳过";
        t.progress = 100;
      } else if (it.status === "failed") {
        t.status = "error";
        t.statusText = "✗ " + (it.message || "入库失败");
        t.progress = 0;
      } else if (it.status === "processing") {
        t.status = "uploading";
        t.statusText = "入库中（Embedding/索引构建）…";
        t.progress = Math.max(t.progress, 60);
      } else {
        t.status = "pending";
        t.statusText = "排队中";
      }
    });
    if (b && b.finished) {
      const failed = items.filter((x) => x.status === "failed");
      const okN = items.length - failed.length;
      toast(`入库完成：成功 ${okN}${failed.length ? `，失败 ${failed.length}` : ""}`, failed.length ? "error" : "ok");
      if (failed.length) toast(`${failed[0].filename}：${failed[0].message || "入库失败"}`, "error");
      await load();
      scheduleQueueCleanup();
      return;
    }
  }
  scheduleQueueCleanup();
}

/** 终态条目延迟 8s 清出（给用户看完结果的时间），面板随之收起 */
function scheduleQueueCleanup() {
  if (uploadCleanTimer) clearTimeout(uploadCleanTimer);
  uploadCleanTimer = setTimeout(() => {
    uploadQueue.value = uploadQueue.value.filter((t) => !["success", "error"].includes(t.status));
  }, 8000);
}

async function load() {
  error.value = "";
  try {
    const d = await withBusy(() => api.listDocuments(offset.value, PAGE_SIZE, "asc", keyword.value));
    docs.value = (Array.isArray(d) ? d : d.items) || [];
    total.value = Number(d.total ?? docs.value.length) || docs.value.length;
  } catch (e) {
    error.value = String(e.message || e);
  }
}

function goto(p) {
  offset.value = Math.max(0, p);
  load();
}

/** 列表按 id 正序（从小到大），新上传的文档落在最后一页。
 *  上传成功后必须跳末页，否则用户停在第一页看现状，会以为「传了却没进库」。 */
async function gotoLast() {
  await load();                       // 先拿最新 total
  const last = Math.max(0, Math.floor(Math.max(total.value - 1, 0) / PAGE_SIZE) * PAGE_SIZE);
  if (last !== offset.value) { offset.value = last; await load(); }
}

/* 关键字走服务端全库搜索（后端 q 参数），不能只在前端当页 20 条里筛：
 * 列表正序分页，新审批通过的文档总在末页——页内筛选会让用户以为
 * 「已通过却没入库」。改关键字时页码归零，否则会停在超出范围的 offset 上
 * 看到空列表。 */
let searchTimer = null;
watch(keyword, () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    offset.value = 0;
    load();
  }, 300);
});

/* 服务端已按关键字做过全库过滤（后端 q）。这里再筛一遍只是兼容兜底：
 * 前端产物先更新、后端进程还没重启时，旧进程会忽略 q 参数，若这里不过滤，
 * 搜索框会看起来完全失效。口径与后端一致（标题或文件名）。 */
const pageMatches = computed(() => {
  const k = keyword.value.trim().toLowerCase();
  if (!k) return docs.value;
  return docs.value.filter(
    (d) =>
      String(d.title || "").toLowerCase().includes(k) ||
      String(d.filename || "").toLowerCase().includes(k)
  );
});

const allChecked = computed(
  () => docs.value.length > 0 && docs.value.every((d) => selected.value.has(d.document_id))
);

function toggleAll(e) {
  if (e.target.checked) docs.value.forEach((d) => selected.value.add(d.document_id));
  else selected.value.clear();
}

onMounted(load);
defineExpose({ load });

/* ---------- 行操作 ---------- */
async function download(d) {
  try { await api.download(d.document_id, d.title); }
  catch (e) { toast(String(e.message || e), "error"); }
}

const dlg = ref(null); // { type, doc }
const docDlg = ref(null); // 文档详情子弹窗：{ id, classification }

function openVersions(d) { dlg.value = { type: "versions", doc: d, items: [], loading: true }; loadVersions(d); }

async function loadVersions(d) {
  try {
    const r = await api.versions(d.document_id);
    dlg.value.items = Array.isArray(r) ? r : r.items || [];
  } catch (e) { toast(String(e.message || e), "error"); }
  finally { if (dlg.value) dlg.value.loading = false; }
}

/** 回滚 = 用旧内容替换当前内容，和「上传新版本」一样改写了正文，所以同样要走
 *  发布审批：这里只提交申请，文档内容要等审批通过才真正回退。提示不能说
 *  「已回滚」——那会让用户以为已经生效，回头发现内容没变就会当成 bug。
 *
 *  目标密级/归属部门由申请人显式声明（与「申请更新」同构）：回填当前值只是
 *  默认值，不是「系统替你定了」。早先前端不传这两项，后端就把文档当前行的值
 *  抄进工单，审批人看到的「目标密级」根本没人确认过。
 *
 *  审批人不沿用「上次处理这篇文档的人」（那是随机指派的残留，不是语义），
 *  而是与「申请更新」同规则：从合格候选池里自选，留空则由系统指派。 */
function openRollback(doc, v) {
  dlg.value = {
    type: "rollback",
    doc,
    versionNo: v.version_no ?? v.version,
    classification: Number(doc.classification) || 0,
    departments: resolveDepts(doc),
    approvers: [],
    approverId: null,
    reason: "",
    hint: "",
  };
  loadRollbackApprovers();
}

/** 回滚可选密级：不低于文档当前密级、不高于本人职级。
 *  与后端 rollback 同一口径（降密必须走「申请更新」单独审批）；前端少列一项，
 *  用户选完就会撞上 422。 */
const rollbackLevels = computed(() => {
  if (dlg.value?.type !== "rollback") return [];
  const cur = Number(dlg.value.doc?.classification) || 0;
  const mine = me.level();
  const out = [];
  for (let lv = cur; lv <= mine; lv += 1) out.push(lv);
  return out.length ? out : [cur];
});

async function loadRollbackApprovers() {
  const v = dlg.value;
  if (!v) return;
  try {
    // 候选池按**目标态**派生：按当前态算会出现「选了 L2 却派给只够 L1 的人」
    const d = await api.approverCandidates(v.classification, v.departments);
    v.approvers = Array.isArray(d) ? d : d.items || [];
    v.hint = v.approvers.length
      ? `按目标密级/部门匹配到 ${v.approvers.length} 位可审批人；留空则由系统指派`
      : (d.reason || "该组合下无合格审批人");
    if (!v.approvers.some((a) => Number(a.id) === Number(v.approverId))) v.approverId = null;
  } catch (e) { v.hint = `候选加载失败：${e.message || e}`; }
}

async function submitRollback() {
  const v = dlg.value;
  if (!v.departments.length) {
    toast("请选择归属部门（空数组会让审批人候选池为空）", "error");
    return;
  }
  try {
    const r = await withBusy(() =>
      api.rollback(v.doc.document_id, v.versionNo, v.approverId, v.reason,
                   v.classification, v.departments));
    const who = r?.approver?.username || r?.approver?.employee_no;
    toast(who ? `已提交回滚申请，待审批通过后生效（审批人：${who}）`
              : "已提交回滚申请，待审批通过后生效", "ok");
    dlg.value = null;
    await load();
  } catch (e) { toast(String(e.message || e), "error"); }
}

/** 申请更新：改密级/归属部门/状态，走治理申请（Policy），审批人由申请人自选；
 *  选填「新版本文件」则改为内容更新——以指定 doc_id 生成新版本（任意文件名），
 *  旧版本自动归档可回滚。版本绑定 doc_id（显式意图），不按文件名隐式归并。 */
function openUpdate(d) {
  dlg.value = {
    type: "update",
    doc: d,
    newFile: null,
    // 密级选项区间与 writableRange() 一致（[本人职级, 最高密级]，含 L0 公开），
    // 文档现值直接回填，无需抬升。
    classification: Number(d.classification) || 0,
    departments: resolveDepts(d),
    status: d.status === "archived" ? "archived" : "published",
    reason: "",
    approverId: null,
    approvers: [],
    hint: "",
  };
  loadUpdateApprovers();
}

function onPickUpdateFile(e) {
  if (!dlg.value) return;
  dlg.value.newFile = (e.target.files || [])[0] || null;
}

async function loadUpdateApprovers() {
  const v = dlg.value;
  if (!v) return;
  try {
    const d = await api.approverCandidates(v.classification, v.departments);
    v.approvers = Array.isArray(d) ? d : d.items || [];
    v.hint = v.approvers.length
      ? `匹配到 ${v.approvers.length} 位可审批人`
      : (d.reason || "该组合下无合格审批人");
    if (!v.approvers.some((a) => Number(a.id) === Number(v.approverId))) v.approverId = null;
  } catch (e) { v.hint = `候选加载失败：${e.message || e}`; }
}

watch(
  () => (dlg.value ? [dlg.value.classification, JSON.stringify(dlg.value.departments)] : null),
  () => {
    // 目标密级/部门一变，审批人候选池就得重算：候选按目标态派生，沿用旧名单
    // 会出现「选了 L1 却派给只够 L0 的人」，后端直接 422。
    if (dlg.value?.type === "update") loadUpdateApprovers();
    else if (dlg.value?.type === "rollback") loadRollbackApprovers();
  }
);

async function submitUpdate() {
  const v = dlg.value;
  if ((v.reason || "").trim().length < 5) { toast("变更原因至少 5 个字", "error"); return; }
  try {
    if (v.newFile) {
      // 内容更新：显式指定 doc_id 上传新版本（任意文件名），doc_id 不变、
      // 版本号自增，旧版本自动归档；密级/部门随本次声明一并落库。
      const r = await withBusy(() =>
        api.uploadVersion(v.doc.document_id, v.newFile, v.classification,
                          v.departments, v.approverId, v.reason.trim()));
      // 上传成功 ≠ 申请已提交：该文档已有在途申请 / 无合格审批人时
      // auto_submitted=false，此时不能再报「待发布审批」，必须把原因原样透出。
      const aa = r?.auto_approval || {};
      if (aa.auto_submitted) {
        const who = aa.approver?.username || aa.approver?.employee_no || "系统指派";
        toast(`新版本已上传，已提交发布审批（审批人：${who}）`, "ok");
      } else {
        toast(`新版本已上传，但未提交审批：${aa.reason || "原因未知"}`, "error");
      }
    } else {
      const r = await withBusy(() =>
        api._post(`/governance/documents/${v.doc.document_id}/requests`, {
          classification: v.classification,
          departments: v.departments,
          status: v.status,
          reason: v.reason.trim(),
          ...(v.approverId != null ? { approver_id: Number(v.approverId) } : {}),
        })
      );
      const who = r?.approver?.username || r?.approver?.employee_no;
      toast(who ? `变更申请已提交，审批人：${who}` : "变更申请已提交，待审批", "ok");
    }
    dlg.value = null;
    // 更新不改文档在列表中的位置（doc_id 不变、正序），原地刷新即可
    await load();
  } catch (e) { toast(String(e.message || e), "error"); }
}

/** 删除：提交 doc_batch_delete 工单（后端无 DELETE 路由，直删必然 404） */
async function requestDelete(ids) {
  const picked = docs.value.filter((d) => ids.includes(d.document_id));
  if (!picked.length) { toast("所选文档已失效，请刷新后重试", "error"); return; }
  dlg.value = {
    type: "delete",
    ids,
    docs: picked,
    // 审批所需职级取批次内最高密级（审批人必须能读取批次里每一篇）
    level: Math.max(...picked.map((d) => Number(d.classification) || 0)),
    reason: "",
    approverId: null,
    approvers: [],
    hint: "",
  };
  try {
    const d = await api.approverCandidates(dlg.value.level, resolveDepts(picked[0]));
    dlg.value.approvers = Array.isArray(d) ? d : d.items || [];
    dlg.value.hint = dlg.value.approvers.length
      ? `匹配到 ${dlg.value.approvers.length} 位可审批人`
      : (d.reason || "该组合下无合格审批人");
  } catch (e) { dlg.value.hint = `候选加载失败：${e.message || e}`; }
}

async function submitDelete() {
  const v = dlg.value;
  if ((v.reason || "").trim().length < 5) { toast("删除原因至少 5 个字", "error"); return; }
  try {
    await withBusy(() =>
      api.createTicket(
        "doc_batch_delete",
        { doc_ids: v.ids.map(String), reason: v.reason.trim() },
        v.approverId != null ? Number(v.approverId) : null
      )
    );
    toast("删除申请已提交，待审批", "ok");
    selected.value.clear();
    dlg.value = null;
  } catch (e) { toast(String(e.message || e), "error"); }
}
</script>

<template>
  <div>
    <!-- 上传区 -->
    <div class="panel">
      <div class="panel-head"><h3>上传文档</h3></div>
      <div class="form-row">
        <div class="form-item">
          <label>文件（可多选）</label>
          <input class="input" type="file" multiple @change="onPickFiles" />
        </div>
        <!-- ① 密级 -->
        <div class="form-item">
          <label>密级</label>
          <select v-model="upLevel" class="input">
            <option :value="null">请选择</option>
            <option v-for="lv in levelOptions" :key="lv" :value="lv">
              {{ me.levelName(lv) }}
            </option>
          </select>
        </div>
        <!-- ② 部门 -->
        <div class="form-item form-item--full">
          <label>归属部门（点选，可多选）</label>
          <div class="dept-chips">
            <span v-for="o in deptOptions" :key="o.value" class="dept-chip"
                  :class="{ 'dept-chip--on': upDepts.includes(o.value) }"
                  @click="toggleDept(upDepts, o.value)">{{ o.label }}</span>
          </div>
          <p class="form-hint">
            归属部门即「谁能看到、由谁审」：只勾选某部门→仅该部门可读、且审批人只从该部门产生；
            选「不限部门」→全员可读、审批人也不再限部门。密级只决定可读/可审的职级下限。
          </p>
        </div>
        <!-- ③ 审批人（随前两项自动匹配） -->
        <div class="form-item">
          <label>审批人</label>
          <select v-model="upApprover" class="input" :disabled="!approvers.length">
            <option :value="null">{{ approverPlaceholder }}</option>
            <option v-for="a in approvers" :key="a.id" :value="a.id">
              {{ a.username || a.name }}（{{ a.department }} L{{ a.security_level }}）
            </option>
          </select>
          <p v-if="approverHint" class="form-hint">{{ approverHint }}</p>
        </div>
      </div>
      <button class="btn btn-primary" :disabled="uploading" @click="doUpload">
        {{ uploading ? "上传中…" : "开始上传" }}
      </button>

      <!-- 逐文件入库进度：复用主站 upload-* 类，队列清空后整块收起 -->
      <div v-if="uploadQueue.length" style="margin-top:14px">
        <div class="upload-summary" style="margin-bottom:8px">
          入库进度：{{ uploadQueue.filter((t) => ["success", "error"].includes(t.status)).length }} / {{ uploadQueue.length }}
        </div>
        <div class="upload-progress-list">
          <div v-for="(t, i) in uploadQueue" :key="i" class="upload-item">
            <div class="upload-name" :title="t.name">{{ t.name }}</div>
            <div class="upload-bar"><div class="upload-bar-fill" :style="{ width: (t.progress || 0) + '%' }" /></div>
            <div class="upload-status" :class="t.status">{{ t.statusText }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 列表 -->
    <div class="panel">
      <div class="panel-head">
        <h3>文档列表（{{ total }}{{ keyword.trim() ? "，按关键字搜索全库" : "，新文档在末页" }}）</h3>
        <div class="panel-actions">
          <input v-model="keyword" class="input" placeholder="搜索标题 / 文件名（全库）" />
          <button class="btn" @click="load">刷新</button>
          <button
            class="btn btn-danger"
            :disabled="!selected.size"
            @click="requestDelete([...selected])"
          >
            批量删除（{{ selected.size }}）
          </button>
        </div>
      </div>

      <StateBox v-if="error" kind="error" title="加载失败" :desc="error" />
      <StateBox
        v-else-if="!pageMatches.length && !state.busy"
        kind="empty"
        :title="keyword.trim() ? '没有匹配的文档' : '暂无文档'"
        :desc="keyword.trim() ? '已搜全库（标题 + 文件名），换个关键字试试' : ''"
      />

      <table v-else class="table">
        <thead>
          <tr>
            <th><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
            <th>标题</th><th>密级</th><th>归属部门</th><th>状态</th>
            <th>类型</th><th>分块</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in pageMatches" :key="d.document_id">
            <td>
              <input
                type="checkbox"
                :checked="selected.has(d.document_id)"
                @change="(e) => e.target.checked ? selected.add(d.document_id) : selected.delete(d.document_id)"
              />
            </td>
            <td>{{ d.title }}</td>
            <td>{{ me.levelName(d.classification) }}</td>
            <td>{{ fmtDepts(d) }}</td>
            <td>
              <span class="badge" :class="statusBadge(d.status)">{{ statusLabel(d.status) }}</span>
            </td>
            <td>{{ d.file_type }}</td>
            <td>{{ d.chunk_count ?? "—" }}</td>
            <td class="row-actions">
              <button class="btn" @click="docDlg = { id: d.document_id, classification: Number(d.classification) || 0 }">详情</button>
              <button class="btn" @click="download(d)">下载</button>
              <button class="btn" @click="openVersions(d)">版本历史</button>
              <button class="btn" @click="openUpdate(d)">申请更新</button>
              <button class="btn btn-danger" @click="requestDelete([d.document_id])">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="total > PAGE_SIZE" class="pager">
        <button class="btn" :disabled="offset === 0" @click="goto(offset - PAGE_SIZE)">上一页</button>
        <span>{{ offset + 1 }}–{{ Math.min(offset + PAGE_SIZE, total) }} / {{ total }}</span>
        <button
          class="btn"
          :disabled="offset + PAGE_SIZE >= total"
          @click="goto(offset + PAGE_SIZE)"
        >下一页</button>
      </div>
    </div>

    <!-- 弹窗 -->
    <!-- 主站 modal 结构：.modal（默认 display:none，须带 active）内是
         .modal-mask（纯遮罩）+ .modal-dialog（内容）。曾把遮罩当外层容器、
         内容塞进 .modal 且没加 active，弹窗等于**完全不显示**。 -->
    <div v-if="dlg" class="modal active">
      <div class="modal-mask" @click="dlg = null" />
      <div class="modal-dialog">
        <div class="modal-head">
          <h3 v-if="dlg.type === 'versions'">版本历史 · {{ dlg.doc.title }}</h3>
          <h3 v-else-if="dlg.type === 'update'">申请更新 · {{ dlg.doc.title }}</h3>
          <h3 v-else-if="dlg.type === 'rollback'">申请回滚 · {{ dlg.doc.title }}</h3>
          <h3 v-else>申请删除（{{ dlg.ids.length }} 篇）</h3>
          <button class="modal-close" @click="dlg = null">✕</button>
        </div>
        <div class="modal-body">

        <template v-if="dlg.type === 'versions'">
          <StateBox v-if="dlg.loading" kind="loading" title="加载中…" />
          <StateBox v-else-if="!dlg.items.length" kind="empty" title="暂无历史版本" />
          <ul v-else class="kv-list">
            <li v-for="v in dlg.items" :key="v.version_no ?? v.version">
              <span>#{{ v.version_no ?? v.version }} · {{ v.created_at || "" }}</span>
              <button class="btn" @click="openRollback(dlg.doc, v)">申请回滚</button>
            </li>
          </ul>
        </template>

        <template v-else-if="dlg.type === 'rollback'">
          <p class="form-hint">
            将把《{{ dlg.doc.title }}》回滚到历史版本 <b>v{{ dlg.versionNo }}</b>。
            审批通过后才生效，且不会改写历史版本本身——系统会用该版本的内容生成一个新版本。
          </p>
          <div class="form-item">
            <label>目标密级</label>
            <select v-model="dlg.classification" class="input">
              <option v-for="lv in rollbackLevels" :key="lv" :value="lv">{{ me.levelName(lv) }}</option>
            </select>
            <p class="form-hint">
              回滚只恢复内容，密级由你声明、审批人按此复核；可维持或抬高，
              降密请走「申请更新」单独审批。
            </p>
          </div>
          <div class="form-item form-item--full">
            <label>归属部门（点选，可多选）</label>
            <div class="dept-chips">
              <span v-for="o in deptOptions" :key="o.value" class="dept-chip"
                    :class="{ 'dept-chip--on': dlg.departments.includes(o.value) }"
                    @click="toggleDept(dlg.departments, o.value)">{{ o.label }}</span>
            </div>
          </div>
          <div class="form-item">
            <label>审批人</label>
            <select v-model="dlg.approverId" class="input" :disabled="!dlg.approvers.length">
              <option :value="null">{{ dlg.approvers.length ? "请选择（留空则系统指派）" : "无合格审批人" }}</option>
              <option v-for="a in dlg.approvers" :key="a.id" :value="a.id">
                {{ a.username || a.name }}（{{ a.department }} L{{ a.security_level }}）
              </option>
            </select>
            <p class="form-hint">{{ dlg.hint }}</p>
          </div>
          <div class="form-item">
            <label>回滚原因（可选）</label>
            <textarea v-model="dlg.reason" class="input" rows="3" />
          </div>
          <button class="btn btn-primary btn-block" :disabled="state.busy" @click="submitRollback">
            提交回滚申请
          </button>
        </template>

        <template v-else-if="dlg.type === 'update'">
          <div class="form-item form-item--full">
            <label>新版本文件（可选）</label>
            <input type="file" class="input" @change="onPickUpdateFile($event)" />
            <p class="form-hint">
              选择后将替换文档内容并生成新版本（doc_id 不变、版本号自增，旧版本自动归档、可在版本历史中回滚）；
              文件名无需与原文件相同。不选文件则仅提交密级/部门变更申请。
            </p>
          </div>
          <div class="form-item">
            <label>密级</label>
            <select v-model="dlg.classification" class="input">
              <option v-for="lv in levelOptions" :key="lv" :value="lv">{{ me.levelName(lv) }}</option>
            </select>
          </div>
          <div class="form-item form-item--full">
            <label>归属部门（点选，可多选）</label>
            <div class="dept-chips">
              <span v-for="o in deptOptions" :key="o.value" class="dept-chip"
                    :class="{ 'dept-chip--on': dlg.departments.includes(o.value) }"
                    @click="toggleDept(dlg.departments, o.value)">{{ o.label }}</span>
            </div>
            <p class="form-hint">
              改成某部门后，原部门将不再可读；选「不限部门」则全员可读。
            </p>
          </div>
          <div class="form-item">
            <label>审批人</label>
            <select v-model="dlg.approverId" class="input" :disabled="!dlg.approvers.length">
              <option :value="null">{{ dlg.approvers.length ? "请选择（留空则系统指派）" : "无合格审批人" }}</option>
              <option v-for="a in dlg.approvers" :key="a.id" :value="a.id">
                {{ a.username || a.name }}（{{ a.department }} L{{ a.security_level }}）
              </option>
            </select>
            <p class="form-hint">{{ dlg.hint }}</p>
          </div>
          <div class="form-item">
            <label>变更原因（≥5 字）</label>
            <textarea v-model="dlg.reason" class="input" rows="3" />
          </div>
          <button class="btn btn-primary btn-block" :disabled="state.busy" @click="submitUpdate">
            {{ dlg.newFile ? "上传新版本" : "提交申请" }}
          </button>
        </template>

        <template v-else>
          <p class="form-hint" style="color:var(--c-err)">
            ⚠️ 审批通过后系统将永久删除这些文档及其分块、密级记录与向量索引，不可撤销。
          </p>
          <ul class="kv-list">
            <li v-for="d in dlg.docs" :key="d.document_id">
              <span>#{{ d.document_id }} {{ d.title }}</span>
              <b>{{ me.levelName(d.classification) }}</b>
            </li>
          </ul>
          <div class="form-item">
            <label>审批人</label>
            <select v-model="dlg.approverId" class="input" :disabled="!dlg.approvers.length">
              <option :value="null">{{ dlg.approvers.length ? "请选择（留空则系统指派）" : "无合格审批人" }}</option>
              <option v-for="a in dlg.approvers" :key="a.id" :value="a.id">
                {{ a.username || a.name }}（{{ a.department }} L{{ a.security_level }}）
              </option>
            </select>
            <p class="form-hint">{{ dlg.hint }}</p>
          </div>
          <div class="form-item">
            <label>删除原因（≥5 字）</label>
            <textarea v-model="dlg.reason" class="input" rows="3" />
          </div>
          <button class="btn btn-danger btn-block" @click="submitDelete">提交删除申请</button>
        </template>

        <button class="btn btn-block" style="margin-top:8px" @click="dlg = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 文档详情 + 分块预览（行「详情」） -->
    <DocDetailModal v-if="docDlg" :doc-id="docDlg.id" :classification="docDlg.classification"
                    @close="docDlg = null" />
  </div>
</template>
