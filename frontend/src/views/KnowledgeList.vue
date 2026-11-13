<template>
  <div class="kl">
    <!-- 工具栏：筛选 / 刷新 / 计数 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <input
          v-model.trim="q"
          class="input kl-search"
          type="search"
          placeholder="按文件名筛选…"
          aria-label="按文件名筛选"
        />
        <button class="btn" :disabled="loading" @click="load">
          {{ loading ? "加载中…" : "刷新" }}
        </button>
      </div>
      <div class="toolbar-right">
        <span class="badge badge--neutral">共 {{ filtered.length }} 篇</span>
      </div>
    </div>

    <!-- 状态：错误 / 空 / 加载中（复用主站 state-box，图形由 CSS 绘制） -->
    <div v-if="error" class="state-box state-box--error">
      <span class="state-icon" aria-hidden="true"></span>
      <span class="state-title">加载失败</span>
      <span class="state-desc">{{ error }}</span>
      <button class="btn" @click="load">重试</button>
    </div>
    <div v-else-if="loading && !docs.length" class="state-box">
      <span class="state-icon" aria-hidden="true"></span>
      <span class="state-title">正在加载…</span>
    </div>
    <div v-else-if="!docs.length" class="state-box">
      <span class="state-icon" aria-hidden="true"></span>
      <span class="state-title">暂无可见文档</span>
      <span class="state-desc">
        可见范围由服务端按 BLP 规则裁决。若你刚同步过数据，点「刷新」重试。
      </span>
    </div>
    <div v-else-if="!filtered.length" class="state-box">
      <span class="state-icon" aria-hidden="true"></span>
      <span class="state-title">没有匹配的文档</span>
      <span class="state-desc">没有文件名包含「{{ q }}」的文档。</span>
    </div>

    <!-- 数据表：table-scroll 提供粘性表头，长列表滚动时表头不丢失语义 -->
    <div v-else class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>文件名</th>
            <th>类型</th>
            <th>密级</th>
            <th>归属部门</th>
            <th>分块</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in filtered" :key="d.id">
            <td>{{ d.id }}</td>
            <td class="kl-name" :title="d.filename">{{ d.filename }}</td>
            <td>
              <span class="type-tag" :class="`type-tag-${typeKey(d.file_type)}`">
                {{ d.file_type }}
              </span>
            </td>
            <td>
              <span class="badge" :class="secBadge(d.classification ?? 0)">
                {{ levelName(d.classification ?? 0, levels) }}
              </span>
            </td>
            <td>{{ (Array.isArray(d.departments) && d.departments.length) ? d.departments.join(', ') : (d.owner_department || "-") }}</td>
            <td>{{ d.chunk_count }}</td>
            <td>{{ fmtDate(d.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="kl-note">
      只读试点视图：本页不提供任何写操作，也不在前端做权限过滤——
      可见范围由服务端按 BLP 规则裁决，前端重复裁决只会引入不一致。
    </p>
  </div>
</template>

<script setup>
/**
 * KnowledgeList · 只读知识列表（Vue 试点）
 *
 * 为什么拿它做第一个组件：
 *   1. 纯展示，不涉及操作按钮显隐（那是 js/core/policy.js 的职责，已有测试覆盖）；
 *   2. 出问题影响面小——删掉挂载点即可回退，不触碰既有 app.js 的任何视图；
 *   3. 能验证「Vue → import policy.js 纯函数 → 经 kms-client 调契约端点」整条链路。
 *
 * 刻意不做的事：
 *   - **不调用** canWriteDoc / canManageDoc。本视图没有写操作，
 *     在前端重复服务端已做过的权限裁决毫无收益，且易写出方向相反的判断
 *     （历史上就有这个 bug，见 policy.test.js 的 ★ 用例）。
 *   - 密级只用 levelName 做**名称翻译**，纯显示函数，不涉及判定。
 */
import { computed, onMounted, ref } from "vue";

import { levelName } from "@kms/core/policy.js";
import { kms } from "@kms/sdk/kms-client.js";

const docs = ref([]);
const levels = ref([]);
const loading = ref(false);
const error = ref("");
const q = ref("");

const filtered = computed(() => {
  const kw = q.value.toLowerCase();
  if (!kw) return docs.value;
  return docs.value.filter((d) => (d.filename || "").toLowerCase().includes(kw));
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [docRes, lvRes] = await Promise.all([
      kms.listDocuments(0, 200),
      kms.levels(),
    ]);
    docs.value = (docRes && docRes.items) || [];
    levels.value = (lvRes && lvRes.items) || [];
  } catch (e) {
    docs.value = [];
    error.value = (e && e.message) || String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

/** .type-tag.pdf 这类修饰类要求命中 CSS 里已定义的后缀，其余类型回落到默认样式 */
function typeKey(fileType) {
  const t = String(fileType || "").toLowerCase();
  return ["pdf", "docx", "doc", "xlsx", "txt", "md", "img"].includes(t) ? t : "other";
}

/** 密级 → 状态标签配色（L0 公开 / L1 秘密 / L2 机密 / L3 绝密）。
 *  纯展示映射：只决定徽章颜色，不构成任何权限判定——权限一律由服务端裁决。 */
function secBadge(level) {
  return ["badge--neutral", "badge--info", "badge--warn", "badge--err"][level] || "badge--neutral";
}

function fmtDate(v) {
  if (!v) return "-";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
</script>

<style scoped>
.kl {
  padding: 4px 0 8px;
}

.kl-search {
  max-width: 280px;
}

/* scoped 内覆盖全局类：Vue 会给本组件元素加 data 属性，仍能命中 */
.state-box { margin: 4px 0; }

.kl-name {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.type-tag-other {
  background: var(--surface-3);
  color: var(--ink-2);
}

.kl-note {
  margin-top: 12px;
  font-size: 11.5px;
  color: var(--ink-3);
  line-height: 1.7;
}
</style>
