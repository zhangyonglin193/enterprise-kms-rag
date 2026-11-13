<script setup>
/* 空 / 加载 / 错误三态。
 * 复用主站的 state-box 类名（而非组件私有类）：这样即使组件样式没加载也能读，
 * 且亮/暗双主题自动跟随主站 CSS 变量。 */
defineProps({
  kind: { type: String, default: "empty" }, // empty | loading | error
  title: { type: String, default: "" },
  desc: { type: String, default: "" },
});

const ICON = { empty: "◌", loading: "◍", error: "⚠" };
</script>

<template>
  <div class="state-box" :class="`state-box--${kind}`">
    <span class="state-icon" aria-hidden="true">{{ ICON[kind] || "◌" }}</span>
    <span class="state-title">{{ title }}</span>
    <span v-if="desc" class="state-desc">{{ desc }}</span>
    <slot />
  </div>
</template>
