<script setup>
/* 文档详情 + 分块预览弹窗（文档库「详情」与工单详情「查看内容」共用）。
 *
 * 数据来自 SDK document(docId)（GET /documents/{id}）：
 *   { document: {filename,file_type,title,chunk_count,created_at,...},
 *     chunks:   [{chunk_index,page,section,text_hash,text}] }
 * 密级徽章由调用方传入——列表行对象上有 classification，详情响应里没有，
 * 传 null 时显示「—」而非猜一个 0（公开），避免把未知密级误导成公开。 */
import { ref, watch } from "vue";

import { api } from "../api.js";
import { me } from "../store.js";
import StateBox from "./StateBox.vue";

const props = defineProps({
  /** 文档 id；null 时关闭（v-if 由父组件控制或内部容错） */
  docId: { type: Number, default: null },
  /** 文档密级（数字）；缺省 null 显示 — */
  classification: { type: Number, default: null },
});
const emit = defineEmits(["close"]);

const doc = ref(null);
const chunks = ref([]);
const error = ref("");

watch(
  () => props.docId,
  async (id) => {
    doc.value = null;
    chunks.value = [];
    error.value = "";
    if (id == null) return;
    try {
      const d = await api.document(id);
      doc.value = d.document || d;
      chunks.value = d.chunks || [];
    } catch (e) {
      error.value = String(e.message || e);
    }
  },
  { immediate: true }
);

const fmt = (s) => (s || "").replace("T", " ").slice(0, 19);
</script>

<template>
  <div class="modal active">
    <div class="modal-mask" @click="emit('close')" />
    <div class="modal-dialog" style="max-width:760px">
      <div class="modal-head">
        <h3>文档详情{{ doc ? ` · ${doc.filename}` : "" }}</h3>
        <button class="modal-close" @click="emit('close')">✕</button>
      </div>
      <div class="modal-body">
        <StateBox v-if="error" kind="error" title="加载失败" :desc="error" />
        <StateBox v-else-if="!doc" kind="loading" title="加载中…" />

        <template v-else>
          <div class="info-list" style="margin-bottom:18px">
            <div class="info-item"><span class="info-key">文件名</span><span class="info-val">{{ doc.filename }}</span></div>
            <div class="info-item"><span class="info-key">类型</span><span class="info-val">{{ doc.file_type }}</span></div>
            <div class="info-item">
              <span class="info-key">密级</span>
              <span class="info-val">
                <span v-if="classification != null" class="badge badge--info">{{ me.levelName(classification) }}</span>
                <template v-else>—</template>
              </span>
            </div>
            <div class="info-item"><span class="info-key">标题</span><span class="info-val">{{ doc.title || "—" }}</span></div>
            <div class="info-item"><span class="info-key">分块数</span><span class="info-val">{{ doc.chunk_count }}</span></div>
            <div class="info-item"><span class="info-key">入库时间</span><span class="info-val">{{ fmt(doc.created_at) }}</span></div>
          </div>

          <h4 style="margin-bottom:12px;font-size:14px">分块预览（共 {{ chunks.length }} 块）</h4>
          <StateBox v-if="!chunks.length" kind="empty" title="无分块数据" />
          <template v-else>
            <div v-for="c in chunks.slice(0, 50)" :key="c.chunk_index" class="chunk-item">
              <div class="chunk-head">
                <span>Chunk #{{ c.chunk_index }}{{ c.page ? ` · 第${c.page}页` : "" }}{{ c.section ? ` · ${c.section}` : "" }}</span>
                <span>hash: {{ c.text_hash }}</span>
              </div>
              <div class="chunk-text">{{ c.text }}</div>
            </div>
            <p v-if="chunks.length > 50" class="form-hint">仅展示前 50 块，共 {{ chunks.length }} 块</p>
          </template>
        </template>

        <button class="btn btn-block" style="margin-top:12px" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>
