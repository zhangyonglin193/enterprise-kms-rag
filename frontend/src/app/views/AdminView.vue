<script setup>
/* 管理视图。
 *
 * 注意：本系统**没有「管理员」角色**，身份只有「员工」与「运营审计」两类
 * （kms/constants.py）。本视图入口由 policy.js canViewAdmin() 控制——判据是
 * **安全职级 L2 及以上**，不是 is_admin（该字段已下线，恒 false）。
 *
 * 可见内容同样按身份裁剪：
 *   /admin/users  全体员工可见（组织通讯用）
 *   /admin/levels 全体员工可见（把密级数字译成名称，不写死在前端）
 *   /audit/audit-logs  **仅运营审计**（员工访问 403）
 */
import { onMounted, ref } from "vue";

import { api } from "../api.js";
import { state, withBusy } from "../store.js";
import StateBox from "../components/StateBox.vue";

const users = ref([]);
const levels = ref([]);
const logs = ref([]);
const actions = ref([]);
const error = ref("");
const logErr = ref("");

/* 审计筛选：操作类型取自库中实际出现过的动作（/audit/audit-actions），
 * 工号取自已加载员工——两者都是可枚举值，用下拉代替手打，
 * 手打拼错不报错，只会静默筛出空结果。 */
const fAction = ref("");
const fEmployee = ref("");

async function load() {
  error.value = "";
  logErr.value = "";
  try {
    const [u, l] = await withBusy(() => Promise.all([api.users(), api.levels()]));
    users.value = Array.isArray(u) ? u : u.items || [];
    levels.value = Array.isArray(l) ? l : l.items || [];
  } catch (e) { error.value = String(e.message || e); }

  // 审计日志仅运营审计可读；员工拿 403 属预期，单独记录不污染主错误区
  if (state.user?.is_auditor) {
    try {
      const [a] = await withBusy(() =>
        Promise.all([api.auditActions(), refreshAudit()])
      );
      actions.value = Array.isArray(a) ? a : a.items || [];
    } catch (e) { logErr.value = String(e.message || e); }
  }
}

/** 按筛选条件拉审计日志（limit 200，与旧版口径一致） */
async function refreshAudit() {
  const params = { limit: 200 };
  if (fAction.value) params.action = fAction.value;
  if (fEmployee.value) params.employee_no = fEmployee.value;
  const lg = await api.auditLogs(params);
  logs.value = Array.isArray(lg) ? lg : lg.items || [];
  return lg;
}

async function applyFilter() {
  if (!state.user?.is_auditor) return;
  logErr.value = "";
  try { await withBusy(refreshAudit); }
  catch (e) { logErr.value = String(e.message || e); }
}

onMounted(load);
defineExpose({ load });
</script>

<template>
  <div>
    <StateBox v-if="error" kind="error" title="加载失败" :desc="error" />

    <div class="panel">
      <div class="panel-head"><h3>安全职级</h3></div>
      <ul class="kv-list">
        <li v-for="l in levels" :key="l.level"><span>L{{ l.level }}</span><b>{{ l.name }}</b></li>
        <li v-if="!levels.length"><span>暂无</span></li>
      </ul>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>员工（{{ users.length }}）</h3></div>
      <StateBox v-if="!users.length && !error" kind="empty" title="暂无数据" />
      <table v-else class="table">
        <thead><tr><th>工号</th><th>姓名</th><th>部门</th><th>职级</th><th>在职</th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.employee_no || u.id">
            <td>{{ u.employee_no }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.department }}</td>
            <td>L{{ u.security_level ?? u.level }}</td>
            <td>{{ u.is_active ? "是" : "否" }}</td>
          </tr>
        </tbody>
      </table>
      <p class="form-hint">人事主数据由 HR 系统维护，KMS 不可修改。</p>
    </div>

    <div v-if="state.user?.is_auditor" class="panel">
      <div class="panel-head">
        <h3>审计日志</h3>
        <div class="panel-actions">
          <select v-model="fAction" class="input" @change="applyFilter">
            <option value="">全部操作类型</option>
            <option v-for="a in actions" :key="a.action" :value="a.action">
              {{ a.action }}（{{ a.count }}）
            </option>
          </select>
          <select v-model="fEmployee" class="input" @change="applyFilter">
            <option value="">全部工号</option>
            <option v-for="u in users" :key="u.employee_no || u.id" :value="u.employee_no">
              {{ u.employee_no }} {{ u.username || "" }}
            </option>
          </select>
          <button class="btn" @click="applyFilter">刷新</button>
        </div>
      </div>
      <StateBox v-if="logErr" kind="error" title="不可读" :desc="logErr" />
      <StateBox v-else-if="!logs.length" kind="empty" title="暂无日志" />
      <table v-else class="table">
        <thead>
          <tr><th>时间</th><th>工号</th><th>操作</th><th>对象</th><th>详情</th><th>IP</th></tr>
        </thead>
        <tbody>
          <tr v-for="(l, i) in logs" :key="i">
            <td>{{ (l.created_at || "").replace("T", " ").slice(0, 19) }}</td>
            <td>{{ l.employee_no || "—" }}</td>
            <td><span class="type-tag txt">{{ l.action }}</span></td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                :title="l.target">{{ l.target || "—" }}</td>
            <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                :title="l.detail">{{ l.detail || "—" }}</td>
            <td>{{ l.ip || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
