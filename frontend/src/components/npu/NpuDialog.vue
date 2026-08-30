<script setup lang="ts">
/**
 * NPU 应用内 confirm/prompt 对话框（单例渲染组件）
 * 在各 NPU 视图中挂载一次 <NpuDialog />，配合 useNpuDialog() 使用。
 */
import { nextTick, ref, watch } from 'vue'
import { useNpuDialog } from '@/composables/useNpuDialog'

const { state, accept, cancel } = useNpuDialog()
const inputEl = ref<HTMLInputElement | null>(null)

// 打开时聚焦输入框并全选，方便直接输入/修改
watch(() => state.visible, async (v) => {
  if (v && state.kind === 'prompt') {
    await nextTick()
    inputEl.value?.focus()
    inputEl.value?.select()
  }
})
</script>

<template>
  <div v-if="state.visible" class="modal-mask" @click.self="cancel()">
    <div class="modal npd-modal">
      <h3>{{ state.title }}</h3>
      <p class="npd-msg">{{ state.message }}</p>
      <input
        v-if="state.kind === 'prompt'"
        ref="inputEl"
        v-model="state.inputValue"
        class="npd-input"
        :placeholder="state.placeholder"
        @keydown.enter="accept()"
        @keydown.esc="cancel()"
      />
      <div class="form-actions">
        <button class="btn-ghost" @click="cancel()">取消</button>
        <button
          class="btn-primary"
          :disabled="state.kind === 'prompt' && !state.inputValue.trim()"
          @click="accept()"
        >确定</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.npd-modal { width: min(420px, 90vw); }
.npd-msg { margin: var(--space-2) 0 var(--space-3); font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.6; word-break: break-all; }
.npd-input {
  width: 100%; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  border: 1px solid var(--border-faint); background: var(--bg-elev-2);
  color: var(--text-primary); font-size: var(--text-sm);
}
.npd-input:focus { outline: none; border-color: var(--amber); }
</style>
