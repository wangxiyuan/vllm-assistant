<script setup lang="ts">
/**
 * NPU 应用内 confirm/prompt 对话框（单例渲染组件）
 * 在各 NPU 视图中挂载一次 <NpuDialog />，配合 useNpuDialog() 使用。
 * 注意：本组件样式必须自包含（npu-shared.css 被视图 scoped 引入，作用不到子组件内部）。
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
  <div v-if="state.visible" class="npd-mask">
    <div class="npd-modal">
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
      <div class="npd-actions">
        <button class="npd-btn npd-btn-ghost" @click="cancel()">取消</button>
        <button
          class="npd-btn npd-btn-primary"
          :disabled="state.kind === 'prompt' && !state.inputValue.trim()"
          @click="accept()"
        >确定</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.npd-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 120;
  display: flex; align-items: center; justify-content: center;
}
.npd-modal {
  background: var(--bg-panel, #12161e); border: 1px solid var(--border-faint);
  border-radius: var(--radius-md); padding: var(--space-5); width: min(520px, 92vw);
  max-height: 88vh; overflow-y: auto;
}
.npd-modal h3 { margin: 0; font-size: var(--text-lg); }
.npd-msg {
  margin: var(--space-3) 0; font-size: var(--text-md);
  color: var(--text-secondary); line-height: 1.7; word-break: break-all;
}
.npd-input {
  width: 100%; box-sizing: border-box; padding: var(--space-3); border-radius: var(--radius-md);
  border: 1px solid var(--border-faint); background: var(--bg-elev-2);
  color: var(--text-primary); font-size: var(--text-md);
}
.npd-input:focus { outline: none; border-color: var(--amber); }
.npd-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-4); }
.npd-btn {
  border: none; cursor: pointer; border-radius: var(--radius-md);
  font-size: var(--text-sm); padding: var(--space-2) var(--space-4);
}
.npd-btn-ghost { background: transparent; color: var(--text-secondary); border: 1px solid var(--border-faint); }
.npd-btn-primary { background: var(--accent); color: #fff; }
.npd-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
