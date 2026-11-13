<script setup>
/* 系统状态：业务统计 + 存活探测 + 入库健康度。
 *   /stats         业务口径（documents/chunks/file_types），全体员工可见
 *   /health        网关存活探测
 *   /audit/ingest-status  入库流程状态，**仅运营审计**（含 FAISS/MySQL 一致性）
 * 第三个端点对员工返回 403，故按需渲染、失败不阻塞整页。
 */
import { onMounted, ref } from "vue";

import { api } from "../api.js";
import { state, withBusy } from "../store.js";
import StateBox from "../components/StateBox.vue";

const stats = ref(null);
const health = ref(null);
const ingest = ref(null);
const ingestErr = ref("");
const error = ref("");

async function load() {
  error.value = "";
  ingestErr.value = "";
  try {
    const [s, h] = await withBusy(() => Promise.all([api.stats(), api.health()]));
    stats.value = s;
    health.value = h;
  } catch (e) { error.value = String(e.message || e); }

  // 入库状态只对运营审计开放；员工拿到 403 属预期，单独记录不污染主错误区
  if (state.user?.is_auditor) {
    try { ingest.value = await api.ingestStatus(); }
    catch (e) { ingestErr.value = String(e.message || e); }
  }
}

onMounted(load);
defineExpose({ load });
</script>

<template>
  <div>
    <StateBox v-if="error" kind="error" title="加载失败" :desc="error" />

    <div class="panel">
      <div class="panel-head"><h3>运行概况</h3></div>
      <ul v-if="stats" class="kv-list">
        <li><span>状态</span><b>{{ stats.status }}</b></li>
        <li><span>数据库</span><b>{{ stats.mysql }}</b></li>
        <li><span>文档数</span><b>{{ stats.documents }}</b></li>
        <li><span>分块数</span><b>{{ stats.chunks }}</b></li>
      </ul>
      <StateBox v-else kind="loading" title="加载中…" />
    </div>

    <div class="panel">
      <div class="panel-head"><h3>存活探测</h3></div>
      <pre v-if="health" class="code-block">{{ JSON.stringify(health, null, 2) }}</pre>
      <StateBox v-else kind="loading" title="加载中…" />
    </div>

    <div v-if="state.user?.is_auditor" class="panel">
      <div class="panel-head"><h3>入库流程状态</h3></div>
      <StateBox v-if="ingestErr" kind="error" title="不可读" :desc="ingestErr" />
      <ul v-else-if="ingest" class="kv-list">
        <li><span>文档总数</span><b>{{ ingest.documents_total }}</b></li>
        <li><span>分块总数</span><b>{{ ingest.chunks_total }}</b></li>
        <li><span>FAISS 向量</span><b>{{ ingest.faiss_total ?? "—" }}</b></li>
        <li>
          <span>索引一致性</span>
          <b :style="{ color: ingest.faiss_mysql_consistent ? 'var(--c-ok)' : 'var(--c-err)' }">
            {{ ingest.faiss_mysql_consistent ? "一致" : "不一致（脏数据）" }}
          </b>
        </li>
      </ul>
      <StateBox v-else kind="loading" title="加载中…" />
    </div>
  </div>
</template>
