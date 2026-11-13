/* ===== app/store.js · 全局响应式状态 =====
 *
 * 刻意**不用 vue-router**：
 *   1. 现有前端（kms/web/app.js）的视图切换是纯 class 切换，URL 不带状态，
 *      引入路由反而会与既有行为不一致（刷新后落在哪、后退键行为都变了）；
 *   2. package.json 只有 vue 一个依赖，新增 vue-router 要联网安装，
 *      而这是内网零外链部署的项目，尽量不加依赖。
 * 视图切换用 reactive state 表达，与既有机制等价。
 */
import { computed, reactive } from "vue";

import { clearToken, getToken } from "@kms/core/http.js";
import {
  canManageDoc,
  canViewAdmin,
  canViewTickets,
  levelName,
  levelTag,
  maxLevel,
  securityLevelOf,
  writableRange,
} from "@kms/core/policy.js";

export const state = reactive({
  /** 登录态：null=未登录，对象=/auth/me 的返回 */
  user: null,
  /** 安全职级字典（/admin/levels），用于把数字译成 L0/L1… */
  levels: [],
  departments: [],
  /** 当前视图名 */
  view: "dashboard",
  /** 全局加载遮罩计数（>0 显示忙态） */
  busy: 0,
  /** 未读通知数 */
  unread: 0,
  /** 侧栏系统健康状态 */
  systemOk: null,
  /** 跨视图跳转：通知点击带 ticket_id 时置为工单 id，
   *  TicketsView 挂载/监听后拉取详情并弹窗，随后自行清空。 */
  jumpTicketId: null,
});

export const token = () => getToken();

// ---- 轻量提示（对应既有前端的 toast）----
export const toasts = reactive([]);
let toastSeq = 0;

export function toast(text, kind = "info") {
  const id = ++toastSeq;
  toasts.push({ id, text, kind });
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id);
    if (i >= 0) toasts.splice(i, 1);
  }, 3200);
}

export const isLoggedIn = computed(() => !!state.user);

/** 统一封装：进入忙碌态 → 执行 → 退出，异常照抛 */
export async function withBusy(fn) {
  state.busy += 1;
  try { return await fn(); } finally { state.busy -= 1; }
}

export function resetSession() {
  state.user = null;
  state.unread = 0;
  clearToken();
}

export function setView(name) { state.view = name; }

// ---- 派生：把 policy.js 的纯函数接到响应式 state 上 ----
// 这些只是薄封装，判定逻辑仍集中在 core/policy.js（有 node --test 覆盖），
// 视图组件不自己写权限判断，避免出现第二套判据。
export const me = {
  level: () => securityLevelOf(state.user),
  /** 文档密级名（公开/秘密/机密/绝密） */
  levelName: (lv) => levelName(lv, state.levels),
  /** 人的层级编号（L0-L3）——文档用 levelName，别混 */
  levelTag: (lv) => levelTag(lv),
  maxLevel: () => maxLevel(state.levels),
  writableRange: () => writableRange(state.user, state.levels),
  canViewAdmin: () => canViewAdmin(state.user),
  canViewTickets: () => canViewTickets(state.user),
  canManageDoc: (docLevel, docDept, isUploader = false) =>
    canManageDoc(docLevel, state.user, docDept, state.user?.department, isUploader),
};

/** 侧栏可见项：与后端角色模型一致——只有「员工」与「运营审计」，无管理员 */
export const navItems = computed(() => {
  const u = state.user;
  const items = [{ view: "dashboard", label: "仪表盘", icon: "◧", auditorOnly: true }];
  items.push(
    { view: "documents", label: "文档库", icon: "▤" },
    { view: "chat", label: "智能问答", icon: "◈" },
    { view: "personal", label: "个人中心", icon: "◐" },
    // 系统状态与仪表盘同为运营审计专属：/stats 的运维口径与入库健康度
    // （FAISS/MySQL 一致性）不是普通员工该看的信息面
    { view: "system", label: "系统状态", icon: "◎", auditorOnly: true },
  );
  if (canViewTickets(u)) items.push({ view: "tickets", label: "工单中心", icon: "◇" });
  if (canViewAdmin(u)) items.push({ view: "admin", label: "管理视图", icon: "◈" });
  return items.filter((it) => !it.auditorOnly || u?.is_auditor);
});
