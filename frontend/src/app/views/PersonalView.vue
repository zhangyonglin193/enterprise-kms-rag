<script setup>
/* 个人中心：本人统计 + 修改密码。
 * 统计来自 /knowledge/personal/stats；改密码走 /auth/change-password。
 * 人事主数据（姓名/部门/职级）由 HR 系统维护，KMS **不可修改**——
 * 所以这里刻意只提供改密码，不提供编辑个人资料的入口。
 */
import { onMounted, ref } from "vue";

import { api } from "../api.js";
import { me, state, toast, withBusy } from "../store.js";
import StateBox from "../components/StateBox.vue";

const stats = ref(null);
const error = ref("");
const oldPwd = ref("");
const newPwd = ref("");
const pwd2 = ref("");

async function load() {
  error.value = "";
  try { stats.value = await withBusy(() => api.knowledgePersonalStats()); }
  catch (e) { error.value = String(e.message || e); }
}

async function changePwd() {
  if (newPwd.value.length < 6) { toast("新密码至少 6 位", "error"); return; }
  if (newPwd.value !== pwd2.value) { toast("两次输入不一致", "error"); return; }
  try {
    await withBusy(() => api.changePassword(oldPwd.value, newPwd.value));
    toast("密码已修改", "ok");
    oldPwd.value = newPwd.value = pwd2.value = "";
  } catch (e) { toast(String(e.message || e), "error"); }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="panel">
      <div class="panel-head"><h3>我的信息</h3></div>
      <ul class="kv-list">
        <li><span>工号</span><b>{{ state.user?.employee_no }}</b></li>
        <li><span>姓名</span><b>{{ state.user?.username }}</b></li>
        <li><span>部门</span><b>{{ state.user?.department || "—" }}</b></li>
        <!-- 层级用 L0-L3；levelName 是文档密级名（公开/…），别混用 -->
        <li><span>安全职级</span><b>{{ me.levelTag(me.level()) }}</b></li>
        <li><span>运营审计</span><b>{{ state.user?.is_auditor ? "是" : "否" }}</b></li>
      </ul>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>我的统计</h3></div>
      <StateBox v-if="error" kind="error" title="加载失败" :desc="error" />
      <StateBox v-else-if="!stats" kind="loading" title="加载中…" />
      <ul v-else class="kv-list">
        <li v-for="(v, k) in stats" :key="k"><span>{{ k }}</span><b>{{ v }}</b></li>
      </ul>
    </div>

    <div class="panel">
      <div class="panel-head"><h3>修改密码</h3></div>
      <div class="form-row">
        <div class="form-item">
          <label>原密码</label>
          <input v-model="oldPwd" class="input" type="password" />
        </div>
        <div class="form-item">
          <label>新密码</label>
          <input v-model="newPwd" class="input" type="password" />
        </div>
        <div class="form-item">
          <label>确认新密码</label>
          <input v-model="pwd2" class="input" type="password" />
        </div>
      </div>
      <button class="btn btn-primary" @click="changePwd">确认修改</button>
    </div>
  </div>
</template>
