<script setup lang="ts">
/**
 * 可过滤下拉选择（轻量 combobox）
 * 原生 datalist 的下拉项无法完整显示长文本（如模型绝对路径），这里自制列表：
 * 选项完整展示、超长悬停提示、输入即时过滤、可直接手输任意值。
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  modelValue: string
  options: string[]
  placeholder?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const open = ref(false)
const keyword = ref('')
/** 过滤 + 截断，避免几百个选项全量渲染 */
const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const list = kw ? props.options.filter(o => o.toLowerCase().includes(kw)) : props.options
  return list.slice(0, 60)
})

function onInput(e: Event) {
  keyword.value = (e.target as HTMLInputElement).value
  emit('update:modelValue', keyword.value)
  open.value = true
}

function pick(v: string) {
  emit('update:modelValue', v)
  open.value = false
}

function onFocus() {
  keyword.value = ''
  open.value = true
}

function onBlur() {
  // mousedown.prevent 保证先触发 pick，再收起列表
  setTimeout(() => (open.value = false), 120)
}
</script>

<template>
  <div class="nfs-wrap">
    <input
      class="nfs-input"
      :value="modelValue"
      :placeholder="placeholder"
      @input="onInput"
      @focus="onFocus"
      @blur="onBlur"
    />
    <ul v-if="open && filtered.length" class="nfs-list">
      <li v-for="o in filtered" :key="o" :title="o" @mousedown.prevent="pick(o)">{{ o }}</li>
      <li v-if="filtered.length === 60" class="nfs-more muted">仅显示前 60 条，继续输入缩小范围…</li>
    </ul>
    <div v-else-if="open" class="nfs-list nfs-none muted">无匹配项，可直接使用输入的值</div>
  </div>
</template>

<style scoped>
.nfs-wrap { position: relative; width: 100%; }
/* 自包含样式：视图的 scoped 样式作用不到子组件内部 */
.nfs-input {
  width: 100%; box-sizing: border-box; height: 34px; padding: 0 var(--space-2);
  border-radius: var(--radius-md); border: 1px solid var(--border-faint);
  background: var(--bg-elev-2); color: var(--text-primary); font-size: var(--text-sm);
}
.nfs-input:focus {
  outline: none; border-color: var(--amber);
  box-shadow: 0 0 0 2px var(--amber-glow-soft, rgba(255, 180, 84, 0.15));
}
.nfs-list {
  position: absolute; z-index: 20; left: 0; right: 0; top: calc(100% + 2px);
  margin: 0; padding: var(--space-1); list-style: none;
  background: var(--bg-elev-2, #1a2029); border: 1px solid var(--border-faint);
  border-radius: var(--radius-md); max-height: 240px; overflow-y: auto;
  box-shadow: var(--shadow-lg);
}
.nfs-list li {
  padding: var(--space-1) var(--space-2); border-radius: 4px;
  font-size: var(--text-xs); line-height: 1.5; cursor: pointer;
  word-break: break-all; color: var(--text-primary);
}
.nfs-list li:hover { background: var(--hover-bg, rgba(255,255,255,0.06)); }
.nfs-list li.nfs-more { cursor: default; color: var(--text-tertiary); }
.nfs-list li.nfs-more:hover { background: none; }
.nfs-none { cursor: default; }
</style>
