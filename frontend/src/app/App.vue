<script setup>
/* 工作台根组件。
 *
 * 与既有前端一致的两条硬约束：
 *   1. 视图切换是纯状态切换（store.state.view），URL 不带状态——现有
 *      kms/web/app.js 就是这么做的，引入 vue-router 会改变刷新/后退行为；
 *   2. 复用主站 CSS 变量与类名，不自带主题，亮/暗自动跟随。
 *
 * 登录后一次性拉齐「字典型」数据（安全职级、部门、未读数），避免每个视图
 * 各自去请求一遍 /admin/levels —— 那正是既有代码里反复出现的问题。
 */
import { computed, onErrorCaptured, onMounted, onUnmounted, ref, watch } from "vue";

import { getToken } from "@kms/core/http.js";
import { api } from "./api.js";
import { isLoggedIn, me, navItems, resetSession, state, toast, toasts, withBusy } from "./store.js";

import DashboardView from "./views/DashboardView.vue";
import DocumentsView from "./views/DocumentsView.vue";
import ChatView from "./views/ChatView.vue";
import PersonalView from "./views/PersonalView.vue";
import SystemView from "./views/SystemView.vue";
import TicketsView from "./views/TicketsView.vue";
import AdminView from "./views/AdminView.vue";

const VIEWS = {
  dashboard: DashboardView,
  documents: DocumentsView,
  chat: ChatView,
  personal: PersonalView,
  system: SystemView,
  tickets: TicketsView,
  admin: AdminView,
};

const TITLES = {
  dashboard: "仪表盘", documents: "文档库", chat: "智能问答",
  personal: "个人中心", system: "系统状态", tickets: "工单中心", admin: "管理视图",
};

const current = computed(() => VIEWS[state.view] || DocumentsView);

/* 组件级错误边界：视图渲染/生命周期抛错在此截停（return false 阻止冒泡到
 * 全局 handler 重复 toast），渲染局部错误面板并保留错误详情供重试判断。 */
const viewError = ref(null);
onErrorCaptured((err) => {
  console.error("[kms-app] view error", err);
  viewError.value = String((err && err.message) || err);
  return false;
});

/** 顶栏身份标识：**层级 + 部门**（如 "L3 · 风险控制部"）。
 *  层级走 levelTag（L0-L3），不是 levelName（那是文档密级名）。
 *  部门未登记时只显示层级，避免留下孤零零的 "L3 · "。 */
const roleTag = computed(() => {
  const lv = me.levelTag(me.level());
  const dep = state.user?.department;
  return dep ? `${lv} · ${dep}` : lv;
});
const title = computed(() => TITLES[state.view] || "知识服务平台");

/* ---------- 登录 ---------- */
const empNo = ref("");
const pwd = ref("");
const loginErr = ref("");
const logging = ref(false);

async function doLogin() {
  loginErr.value = "";
  if (!empNo.value.trim() || !pwd.value) { loginErr.value = "请输入工号与密码"; return; }
  logging.value = true;
  try {
    await api.login(empNo.value.trim(), pwd.value);
    await bootstrap();
    pwd.value = "";
  } catch (e) {
    loginErr.value = String(e.message || e);
  } finally { logging.value = false; }
}

async function doLogout() {
  try { await api.logoutApi(); } catch { /* 本地无论如何都要清 */ }
  resetSession();
  state.view = "documents";
}

/* ---------- 登录后初始化 ---------- */
async function bootstrap() {
  try {
    state.user = await withBusy(() => api.me());
  } catch {
    resetSession();
    return;
  }
  // 字典并行拉取：密级（数字→名称）与部门（上传归属下拉）
  const [lv, dp] = await Promise.all([
    api.levels().catch(() => ({ items: [] })),
    api.departments().catch(() => ({ items: [] })),
  ]);
  state.levels = Array.isArray(lv) ? lv : lv.items || [];
  state.departments = Array.isArray(dp) ? dp : dp.items || [];
  refreshUnread();

  // 仪表盘是运营审计专属；普通员工落到这里会看到空面板，故直接改落文档库
  if (state.view === "dashboard" && !state.user?.is_auditor) state.view = "documents";
}

async function refreshUnread() {
  try {
    const d = await api.unreadCount();
    state.unread = Number(d.unread ?? d.count ?? 0) || 0;
  } catch { state.unread = 0; }
}

/* ---------- 通知中心 ---------- */
const notifOpen = ref(false);
const notifItems = ref([]);
const notifLoading = ref(false);

async function openNotifications() {
  notifOpen.value = true;
  notifLoading.value = true;
  try {
    const d = await api.notifications();
    notifItems.value = d.items || [];
  } catch (e) {
    notifItems.value = [];
    toast("通知加载失败：" + (e?.message || e), "error");
  } finally { notifLoading.value = false; }
}

/** 点击通知：标记已读；带 ticket_id 的跳工单详情（经 store.jumpTicketId） */
async function clickNotification(n) {
  if (!n.is_read) {
    try { await api.markRead(n.id); n.is_read = true; } catch { /* 已读失败不阻断跳转 */ }
    refreshUnread();
  }
  if (n.ticket_id) {
    notifOpen.value = false;
    state.view = "tickets";
    state.jumpTicketId = Number(n.ticket_id);
  }
}

async function markAllRead() {
  try {
    await api.markAllRead();
    notifItems.value.forEach((n) => { n.is_read = true; });
    refreshUnread();
    toast("已全部标记为已读", "ok");
  } catch (e) { toast("操作失败：" + (e?.message || e), "error"); }
}

/* ---------- 侧栏健康状态轮询 ---------- */
async function pollStatus() {
  // /health 需要用户令牌，未登录不探测，避免误导性「服务离线」
  if (!state.user) return;
  try {
    const h = await api.health();
    state.systemOk = h?.mysql === "ok";
  } catch { state.systemOk = false; }
}

const statusText = computed(() =>
  state.systemOk === null ? "检测中…" : (state.systemOk ? "运行正常" : "服务异常")
);

/* ---------- 登录期轮询（未读 30s / 健康 10s，与旧版口径一致） ---------- */
let unreadTimer = null;
let statusTimer = null;

function startPolling() {
  stopPolling();
  refreshUnread();
  pollStatus();
  unreadTimer = setInterval(refreshUnread, 30000);
  statusTimer = setInterval(pollStatus, 10000);
}

function stopPolling() {
  if (unreadTimer) { clearInterval(unreadTimer); unreadTimer = null; }
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
}

// 登录/登出切换轮询；登出同时清健康态，避免下个账号看到上次的陈旧结论
watch(isLoggedIn, (on) => {
  if (on) startPolling();
  else { stopPolling(); state.systemOk = null; state.unread = 0; notifOpen.value = false; }
});

/* ---------- 顶栏刷新：重载当前视图（各视图 defineExpose({ load })） ---------- */
const viewRef = ref(null);

function refreshView() {
  const fn = viewRef.value?.load;
  if (typeof fn === "function") fn();
  refreshUnread();
  pollStatus();
}

// 权限收敛：身份变化后若当前视图已不可见，退回文档库
watch(
  () => navItems.value.map((i) => i.view),
  (views) => { if (!views.includes(state.view)) state.view = "documents"; }
);

// 有本地令牌就尝试恢复会话；令牌失效时 /auth/me 会 401，
// 由 api.onUnauthorized → resetSession() 统一踢回登录态。
// 会话恢复成功后 isLoggedIn 变 true → watch 触发 startPolling。
onMounted(() => { if (isLoggedIn.value || getToken()) bootstrap(); });

// 单测环境/组件卸载时清掉轮询句柄，避免定时器悬挂
onUnmounted(stopPolling);
</script>

<template>
  <!-- 未登录：只渲染登录弹窗。照主站 modal 结构——.modal 默认 display:none，
       必须带 active；内容在 .modal-dialog 里，遮罩只是纯背景层。 -->
  <div v-if="!state.user" class="modal active">
    <div class="modal-mask" />
    <div class="modal-dialog" style="max-width:420px">
      <div class="modal-head"><h3>企业知识服务平台</h3></div>
      <div class="modal-body">
        <form @submit.prevent="doLogin">
          <div class="form-item">
            <label>工号</label>
            <input v-model="empNo" class="input" autocomplete="username" placeholder="如 20260019" />
          </div>
          <div class="form-item">
            <label>密码</label>
            <input v-model="pwd" class="input" type="password" autocomplete="current-password" />
          </div>
          <div v-if="loginErr" class="form-error">{{ loginErr }}</div>
          <button class="btn btn-primary btn-block" :disabled="logging">
            {{ logging ? "登录中…" : "登 录" }}
          </button>
          <p class="login-tip">使用员工工号和密码登录。首次登录后请及时修改密码。</p>
        </form>
      </div>
    </div>
  </div>

  <!-- 已登录：完整布局 -->
  <div v-else class="app">
    <aside class="sidebar">
      <div class="brand">知识服务平台</div>
      <nav class="nav">
        <button
          v-for="it in navItems"
          :key="it.view"
          class="nav-item"
          :class="{ active: state.view === it.view }"
          @click="state.view = it.view"
        >
          <span class="nav-icon">{{ it.icon }}</span>{{ it.label }}
        </button>
      </nav>
      <!-- 侧栏底部健康胶囊：10s 轮询 /health（仅登录态探测） -->
      <div class="sidebar-status">
        <span class="status-pill" :class="state.systemOk === null ? 'txt' : (state.systemOk ? 'ok' : 'fail')">
          <span class="dot" />{{ statusText }}
        </span>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <h1 class="view-title">{{ title }}</h1>
        <div class="topbar-right">
          <button class="btn btn-ghost" title="刷新当前视图" @click="refreshView">↻</button>
          <!-- 通知铃铛：badge 复用主站 .notif-badge（绝对定位于 .bell-btn 内） -->
          <button class="btn btn-ghost bell-btn" title="通知" @click="openNotifications">
            🔔
            <span v-if="state.unread > 0" class="notif-badge">{{ state.unread > 99 ? "99+" : state.unread }}</span>
          </button>
          <div class="user-chip">
            <span class="user-avatar">👤</span>
            <div class="user-meta">
              <span class="user-name">{{ state.user?.username }}</span>
              <span class="user-role">{{ roleTag }}</span>
            </div>
          </div>
          <button class="btn btn-ghost" title="退出登录" @click="doLogout">⏻</button>
        </div>
      </header>

      <!-- .view 必须只出现在**这一层**：它自带 display:none/block 切换与
           overflow/padding。若视图根元素也挂 .view.active，其 display 会在
           同一元素上与本层冲突——问答视图的 .chat-layout（display:grid，
           特异性 0,1,0）会被 .view.active（display:block，0,2,0）覆盖，
           三栏布局塌成一栏。故视图根元素一律不挂 view 类。 -->
      <div class="view active" :key="state.view">
        <!-- 组件级错误边界：单个视图渲染抛错 → 局部错误面板 + 重试，
             侧栏/顶栏/其余状态全部存活（生产级最小影响面） -->
        <template v-if="viewError">
          <div class="state-box state-box--error">
            <span class="state-title">视图加载异常</span>
            <span class="state-desc">侧栏与其他功能不受影响，可重试或切换其他栏目。</span>
            <span class="state-desc" style="font-family:var(--mono);font-size:11.5px">{{ viewError }}</span>
            <button class="btn" style="margin-top:10px" @click="viewError = null">重试</button>
          </div>
        </template>
        <component v-else :is="current" ref="viewRef" />
      </div>
    </main>

    <!-- 通知面板：复用主站 notif-* 类；点击条目标记已读并跳关联工单 -->
    <div v-if="notifOpen" class="modal active">
      <div class="modal-mask" @click="notifOpen = false" />
      <div class="modal-dialog">
        <div class="modal-head">
          <h3>通知</h3>
          <button class="modal-close" @click="notifOpen = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="notif-toolbar">
            <button class="btn btn-link" @click="markAllRead">全部标记为已读</button>
          </div>
          <div v-if="notifLoading" class="empty">加载中…</div>
          <div v-else-if="!notifItems.length" class="empty">暂无通知</div>
          <div v-else class="notif-list">
            <div
              v-for="n in notifItems"
              :key="n.id"
              class="notif-item"
              :class="{ unread: !n.is_read }"
              style="cursor:pointer"
              @click="clickNotification(n)"
            >
              <div class="notif-title">{{ n.title }}</div>
              <div class="notif-content">{{ n.content || "" }}</div>
              <div class="notif-meta">
                {{ (n.created_at || "").replace("T", " ").slice(0, 19) }} · {{ n.ntype || "" }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 主站 .toast 是**单元素**固定定位（top/right 22px），同时来多条会互相
         重叠。队列化后用 inline style 逐条下移，无需新增 CSS 类。 -->
    <div
      v-for="(t, i) in toasts"
      :key="t.id"
      class="toast show"
      :class="t.kind === 'ok' ? 'success' : t.kind === 'error' ? 'error' : ''"
      :style="{ top: `${22 + i * 52}px` }"
    >{{ t.text }}</div>
  </div>
</template>

<style>
/* ============================================================
   补充样式：只定义主站 style.css **没有** 的类。
   刻意不重复定义任何主站已有的类（view / panel / panel-body / table / btn /
   modal / msg / conv / source / stat 等一律复用），避免同一视觉元素在两处
   各写一份、日后必然漂移。本块随 dist-app/kms-app.css 输出。
   ============================================================ */

/* 键值列表：主站无对应类，面板内容多由 app.js 动态拼装 */
.kv-list { list-style: none; margin: 0; padding: 0; }
.kv-list > li {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 7px 0; font-size: 12.5px;
  border-bottom: 1px dashed var(--line);
}
.kv-list > li:last-child { border-bottom: none; }
.kv-list > li > span { color: var(--ink-2); }
.kv-list > li > b { font-weight: 600; color: var(--ink); }

/* 排行榜（知识中心热门文档） */
.rank-list { list-style: none; margin: 0; padding: 0; }
.rank-list > li {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 0; border-bottom: 1px dashed var(--line); font-size: 12.5px;
}
.rank-list > li:last-child { border-bottom: none; }
.rank-no {
  flex: 0 0 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--surface-2); color: var(--ink-2);
  font-size: 11.5px; font-variant-numeric: tabular-nums;
}
.rank-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-meta { color: var(--ink-3); font-size: 11.5px; font-variant-numeric: tabular-nums; }

/* 分页器 */
.pager {
  display: flex; align-items: center; justify-content: flex-end;
  gap: 10px; margin-top: 12px; font-size: 12px; color: var(--ink-2);
}

/* JSON 预览块 */
.code-block {
  margin: 0; padding: 12px 14px;
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-family: var(--mono); font-size: 11.5px; line-height: 1.6;
  color: var(--ink); overflow-x: auto; white-space: pre-wrap; word-break: break-all;
}

/* 表单横向排列 */
.form-row { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; }
.form-row > .form-item { flex: 1; min-width: 180px; margin-bottom: 0; }
/* 需要整行宽度容纳多选项的表单项（如归属部门胶囊） */
.form-item--full { flex: 1 1 100% !important; min-width: 0; }

/* 归属部门多选：胶囊标签（取代原生 select[multiple]，避免列表框拥挤） */
.dept-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
.dept-chip {
  cursor: pointer; user-select: none; white-space: nowrap;
  padding: 4px 12px; border-radius: var(--r-pill);
  font-size: 12.5px; line-height: 1.5;
  border: 1px solid var(--line-2); background: var(--surface-2); color: var(--ink-2);
  transition: background .15s ease, border-color .15s ease, color .15s ease;
}
.dept-chip:hover { border-color: var(--accent-2); color: var(--accent); }
.dept-chip--on {
  background: var(--accent); border-color: var(--accent); color: #fff;
}
.dept-chip--on:hover { color: #fff; filter: brightness(1.06); }

/* 面板头部右侧操作区 */
.panel-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; flex-wrap: wrap; }

/* 弹窗底部按钮组 */
.modal-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }

/* 侧栏图标 */
.nav-icon { width: 18px; text-align: center; flex-shrink: 0; opacity: .85; }

/* 侧栏底部健康胶囊：.sidebar 是纵向 flex，margin-top:auto 推到底 */
.sidebar-status {
  margin-top: auto;
  padding: 14px 16px;
  border-top: 1px solid var(--rail-line);
}

/* 说明文字 */
.hint { font-size: 11.5px; color: var(--ink-3); line-height: 1.6; margin-top: 10px; }
</style>
