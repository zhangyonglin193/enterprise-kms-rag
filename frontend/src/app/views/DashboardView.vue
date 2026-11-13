<script setup>
/* 仪表盘（运营审计专属视图）。
 *
 * 数据全部来自 GET /stats。该端点**按身份裁剪下发**：
 *   全体员工可见：documents / chunks / file_types
 *   仅审计员可见：vectors / bm25 / models / rag_params（非审计员时这些字段
 *                 根本不在响应里——不是前端隐藏，是后端不下发）
 * 所以这里用 `k in stats` 判断能否渲染某块面板，而不是假设字段一定存在。 */
import { onMounted, ref } from "vue";

import { api } from "../api.js";
import { state, withBusy } from "../store.js";
import StateBox from "../components/StateBox.vue";

const stats = ref(null);
const error = ref("");
const recent = ref([]);

const RAG_META = [
  ["chunk_size", "分块大小"],
  ["chunk_overlap", "分块重叠"],
  ["top_k_retrieve", "召回 TopK"],
  ["top_k_rerank", "重排 TopK"],
  ["max_context_chars", "上下文上限"],
  ["enable_rerank", "启用重排"],
  ["enable_bm25", "启用 BM25"],
  ["enable_cache", "启用缓存"],
  ["llm_temperature", "温度"],
  ["llm_max_tokens", "最大 Token"],
];

async function load() {
  error.value = "";
  try {
    stats.value = await withBusy(() => api.stats());
  } catch (e) {
    error.value = String(e.message || e);
  }
  // 最近入库文档：与统计并行，失败不阻塞统计面板。
  // 必须显式 desc——列表默认口径已改为按编号从小到大，跟着默认值拿到的
  // 会是最早的 5 篇，标题写着「最近」却全是旧文档。
  try {
    const d = await api.listDocuments(0, 5, "desc");
    recent.value = (Array.isArray(d) ? d : d.items) || [];
  } catch { recent.value = []; }
}

onMounted(load);
defineExpose({ load });

const asBool = (v) => (typeof v === "boolean" ? (v ? "开" : "关") : String(v ?? "—"));
const fmt = (s) => (s || "").replace("T", " ").slice(0, 16);
/** 文件类型徽章配色（type-tag 的扩展类名） */
const tagClass = (t) => ["pdf", "docx", "doc", "xlsx", "txt", "md", "img"].includes(t) ? t : "txt";
</script>

<template>
  <div>
    <StateBox v-if="error" kind="error" title="统计加载失败" :desc="error" />
    <StateBox v-else-if="!stats" kind="loading" title="正在加载统计…" />

    <template v-else>
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-ico c-sapphire">📄</div>
          <div class="stat-body">
            <div class="stat-num">{{ stats.documents }}</div>
            <div class="stat-label">文档总数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-ico c-blue">🧩</div>
          <div class="stat-body">
            <div class="stat-num">{{ stats.chunks }}</div>
            <div class="stat-label">知识分块</div>
          </div>
        </div>
        <!-- 向量/BM25：非审计员时后端不下发这两个键，故整卡不渲染 -->
        <div v-if="'vectors' in stats" class="stat-card">
          <div class="stat-ico c-violet">🔢</div>
          <div class="stat-body">
            <div class="stat-num">{{ stats.vectors ?? "—" }}</div>
            <div class="stat-label">向量索引</div>
          </div>
        </div>
        <div v-if="'bm25' in stats" class="stat-card">
          <div class="stat-ico c-teal">🔎</div>
          <div class="stat-body">
            <div class="stat-num">{{ stats.bm25 ?? "—" }}</div>
            <div class="stat-label">BM25 索引</div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h3>文件类型分布</h3></div>
        <ul class="kv-list">
          <li v-for="(n, t) in stats.file_types || {}" :key="t">
            <span>{{ t }}</span><b>{{ n }}</b>
          </li>
          <li v-if="!Object.keys(stats.file_types || {}).length"><span>暂无数据</span></li>
        </ul>
      </div>

      <!-- 最近入库（复用主站 recent-* 类） -->
      <div class="panel">
        <div class="panel-head"><h3>最近入库</h3></div>
        <StateBox v-if="!recent.length" kind="empty" title="暂无文档，请先上传" />
        <div v-else class="recent-list">
          <div v-for="d in recent" :key="d.document_id" class="recent-item">
            <div class="recent-left">
              <div class="type-tag" :class="tagClass(String(d.file_type || '').toLowerCase())">
                {{ String(d.file_type || "?").slice(0, 3).toUpperCase() }}
              </div>
              <div>
                <div class="recent-name" :title="d.filename || d.title">{{ d.filename || d.title }}</div>
                <div class="recent-meta">{{ d.chunk_count ?? "—" }} 分块 · {{ fmt(d.created_at) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="stats.models" class="panel">
        <div class="panel-head"><h3>模型配置</h3></div>
        <ul class="kv-list">
          <li v-for="(v, k) in stats.models" :key="k"><span>{{ k }}</span><b>{{ v || "—" }}</b></li>
        </ul>
      </div>

      <div v-if="stats.rag_params" class="panel">
        <div class="panel-head"><h3>检索参数</h3></div>
        <ul class="kv-list">
          <li v-for="[k, label] in RAG_META" :key="k">
            <span>{{ label }}</span><b>{{ asBool(stats.rag_params[k]) }}</b>
          </li>
        </ul>
      </div>

      <p v-if="!state.user?.is_auditor" class="hint">
        模型配置与检索参数属运维敏感信息，仅运营审计可见。
      </p>
    </template>
  </div>
</template>
