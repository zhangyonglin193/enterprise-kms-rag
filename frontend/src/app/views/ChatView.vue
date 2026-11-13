<script setup>
/* 智能问答。
 *
 * 流式走 POST /chat?stream=true（SSE，由 core/http.js streamSSE 读帧），
 * 非流式走 POST /chat。两者是同一端点的两种形态，不是两个接口。
 *
 * 参考来源可点击：sources[].document_id 是整数时渲染成链接，点击调
 * api.download() 取原文。不能用裸 <a href>——下载端点要 Bearer 鉴权，
 * href 带不上令牌。非整数 id 一律降级为不可点击，避免把用户输入拼进 DOM。
 */
import { nextTick, onMounted, ref, watch } from "vue";

import { renderMarkdown } from "@kms/ui/md.js";
import { api } from "../api.js";
import { toast, withBusy } from "../store.js";

const convs = ref([]);
const sid = ref(null);
const messages = ref([]);
const input = ref("");
const sources = ref([]);
const sending = ref(false);
const error = ref("");
const msgBox = ref(null);
/** 流式输出时逐块滚到底：不滚的话答案会跑到可视区外，看着像"没输出" */
const tick = ref(0);

async function scrollBottom() {
  await nextTick();
  const el = msgBox.value;
  if (el) el.scrollTop = el.scrollHeight;
}
watch(tick, scrollBottom);

async function loadConversations() {
  try {
    const d = await api.conversations(50);
    convs.value = Array.isArray(d) ? d : d.items || [];
  } catch (e) { error.value = String(e.message || e); }
}

async function openConversation(id) {
  sid.value = id;
  messages.value = [];
  sources.value = [];
  try {
    const d = await withBusy(() => api.conversationHistory(id, 100));
    const list = Array.isArray(d) ? d : d.items || d.messages || [];
    // 历史是**问答成对**存放的：{id, question, answer, sources, created_at}，
    // 不是 {role, content} 消息流。必须把一条展开成两条气泡——曾按
    // role/content 猜，两者都是 undefined，结果整段历史渲染成空白气泡、
    // 且全落在 assistant 一侧。
    const out = [];
    for (const it of list) {
      if (it.question) out.push({ role: "user", content: it.question, id: null });
      if (it.answer) out.push({ role: "assistant", content: it.answer, id: it.id ?? null });
    }
    messages.value = out;
    await scrollBottom();
  } catch (e) { toast(String(e.message || e), "error"); }
}

function newChat() {
  sid.value = null;
  messages.value = [];
  sources.value = [];
}

async function send() {
  const q = input.value.trim();
  if (!q || sending.value) return;
  input.value = "";
  sending.value = true;
  messages.value.push({ role: "user", content: q });
  messages.value.push({ role: "assistant", content: "", id: null });
  // **必须用索引、不能用对象引用**：messages.value 是 reactive 数组，push
  // 进去的对象会被 Vue 包成 proxy 存入，但手里这个 holder 引用仍是原始对象。
  // 直接改 holder.content **绕过 Proxy 的 set 拦截、不触发响应式更新**——
  // 流式逐字就刷不出来，只有等 done 那次 sources 变更顺带重渲染才一次性
  // 显出来。经索引 messages.value[botIdx] 访问走的是 proxy，每次累加都触发。
  const botIdx = messages.value.length - 1;
  let streamErr = "";
  try {
    // 后端帧类型（gateway/routes_kms.py:166-200），字段名必须照抄：
    //   chunk {content}                                  —— 增量文本
    //   error {message}
    //   done  {answer, sources, message_id, session_id}
    await api.askStreamIn(q, sid.value, (ev) => {
      if (ev.type === "chunk") { messages.value[botIdx].content += ev.content ?? ""; tick.value += 1; }
      else if (ev.type === "done") {
        sources.value = ev.sources || [];
        messages.value[botIdx].id = ev.message_id ?? null;
        // 记住后端下发的会话，后续追问才能续接同一会话
        if (ev.session_id) sid.value = ev.session_id;
      } else if (ev.type === "error") {
        streamErr = ev.message || "服务异常";
      }
    });
    await loadConversations();
  } catch (e) {
    streamErr = streamErr || String(e.message || e);
  } finally {
    sending.value = false;
    await nextTick();
  }
  // 错误提示放在 finally 之后：JS 语法要求 finally 必须紧跟 try/catch，
  // 插在两者之间的 if 会直接解析失败。
  if (streamErr) {
    toast(`问答失败：${streamErr}`, "error");
    if (!messages.value[botIdx].content) {
      messages.value[botIdx].content = `（生成失败：${streamErr}）`;
    }
  }
}

async function sendFeedback(m, rating) {
  if (m.id == null) { toast("该回答尚无消息 ID，无法反馈", "error"); return; }
  try {
    await api.feedback(m.id, rating, "");
    toast("感谢反馈", "ok");
  } catch (e) { toast(String(e.message || e), "error"); }
}

const safeDocId = (v) => {
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : null;
};

async function openSource(s) {
  const id = safeDocId(s.document_id);
  if (!id) return;
  try { await api.download(id, s.title); }
  catch (e) { toast(String(e.message || e), "error"); }
}

onMounted(loadConversations);
</script>

<template>
  <div class="chat-layout">
    <aside class="conv-panel">
      <div class="conv-head">
        <button class="btn btn-primary btn-block" @click="newChat">新建对话</button>
      </div>
      <div class="conv-list">
        <div v-if="!convs.length" class="conv-empty">暂无历史</div>
        <div
          v-for="c in convs"
          :key="c.session_id"
          class="conv-item"
          :class="{ active: c.session_id === sid }"
          @click="openConversation(c.session_id)"
        >
          <div class="conv-title">{{ c.summary || c.session_id }}</div>
          <div class="conv-meta">
            <span>{{ c.last_time || "" }}</span>
            <span class="fb">{{ c.msg_count ?? 0 }} 条</span>
          </div>
        </div>
      </div>
    </aside>

    <section class="chat-panel">
      <div ref="msgBox" class="chat-messages">
        <div v-if="!messages.length" class="msg msg-system">
          <div class="msg-avatar">💡</div>
          <div class="msg-content">
            <div class="msg-bubble">
              👋 你好！我是基于知识库的问答助手。请输入问题，我会从已入库的文档中检索并回答，同时给出参考来源。
              <br /><small>支持多轮对话上下文、流式输出、Markdown 渲染与答案反馈。</small>
            </div>
          </div>
        </div>
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="msg"
          :class="m.role === 'user' ? 'msg-user' : 'msg-bot'"
        >
          <div class="msg-avatar">{{ m.role === "user" ? "🧑" : "🤖" }}</div>
          <div class="msg-content">
            <!-- 助手回答走 renderMarkdown：主站就是这么渲染的，
                 用纯文本插值会丢掉 Markdown 排版 -->
            <div v-if="m.role === 'user'" class="msg-bubble">{{ m.content }}</div>
            <div v-else class="msg-bubble" v-html="renderMarkdown(m.content)" />
            <div v-if="m.role === 'assistant' && m.id != null" class="msg-actions">
              <button class="msg-action" title="答案有用" @click="sendFeedback(m, 1)">👍</button>
              <button class="msg-action dislike" title="答案无用" @click="sendFeedback(m, -1)">👎</button>
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input-bar">
        <textarea
          v-model="input"
          rows="2"
          placeholder="输入问题，回车发送"
          @keydown.enter.exact.prevent="send"
        />
        <button class="btn btn-primary" :disabled="sending" @click="send">
          {{ sending ? "生成中…" : "发送" }}
        </button>
      </div>
    </section>

    <aside class="sources-panel">
      <div class="sources-head">
        <span>参考来源</span>
        <span class="sources-count">{{ sources.length }}</span>
      </div>
      <div class="sources-list">
        <div v-if="!sources.length" class="conv-empty">暂无来源</div>
        <div
          v-for="(s, i) in sources"
          :key="i"
          class="source-card"
          :class="{ 'source-card--clickable': safeDocId(s.document_id) }"
        >
          <div class="source-title">
            {{ i + 1 }}.
            <a
              v-if="safeDocId(s.document_id)"
              class="source-link"
              href="javascript:void(0)"
              @click="openSource(s)"
            >{{ s.title || "未命名文档" }}</a>
            <span v-else>{{ s.title || "未命名文档" }}</span>
          </div>
          <!-- 后端来源是 {page, title, document_id}，无 snippet 字段，故页码走 source-meta -->
          <div v-if="s.page" class="source-meta">第 {{ s.page }} 页</div>
          <div v-if="s.snippet" class="source-snippet">{{ s.snippet }}</div>
        </div>
      </div>
    </aside>
  </div>
</template>
