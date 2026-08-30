<script setup lang="ts">
/**
 * Playground：对运行中的 vLLM 服务实例直接对话测试
 * 走统一推理网关 /api/npu/services/{id}/proxy/v1（SSE 流式）
 */
import { ref, nextTick, computed } from 'vue'
import { useNpuOpsStore } from '@/stores/npuOps'

const ops = useNpuOpsStore()
const input = ref('')
const listBox = ref<HTMLElement | null>(null)

const service = computed(() =>
  ops.pgServiceId ? ops.serviceById(ops.pgServiceId) : null)

function renderMd(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

async function send() {
  const text = input.value.trim()
  if (!text || ops.pgStreaming || !ops.pgServiceId) return
  input.value = ''
  await ops.pgSend(text)
  await nextTick()
  if (listBox.value) listBox.value.scrollTop = listBox.value.scrollHeight
}

async function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    await send()
  }
}
</script>

<template>
  <div class="playground">
    <div v-if="!service" class="pg-empty">先选择一个运行中的服务实例</div>
    <template v-else>
      <div ref="listBox" class="pg-list">
        <div v-if="ops.pgMessages.length === 0" class="pg-empty">
          直接与 <b>{{ service.model_name || service.name }}</b> 对话测试（OpenAI 兼容，流式输出）
        </div>
        <div v-for="(m, i) in ops.pgMessages" :key="i" class="pg-msg" :class="m.role">
          <div class="pg-bubble" :class="{ error: m.error }">
            <span v-html="renderMd(m.content)"></span>
            <span v-if="!m.done && m.role === 'assistant'" class="pg-cursor">▋</span>
          </div>
        </div>
      </div>
      <div class="pg-input-row">
        <textarea
          v-model="input"
          class="pg-input"
          rows="2"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          @keydown="onKeydown"
          :disabled="ops.pgStreaming"
        ></textarea>
        <button class="pg-send" :disabled="ops.pgStreaming || !input.trim()" @click="send">发送</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.playground { display: flex; flex-direction: column; height: 100%; min-height: 320px; gap: var(--space-2); }
.pg-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-tertiary); font-size: var(--text-sm); }
.pg-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-2); }
.pg-msg { display: flex; }
.pg-msg.user { justify-content: flex-end; }
.pg-msg.assistant { justify-content: flex-start; }
.pg-bubble {
  max-width: 78%; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  font-size: var(--text-sm); line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}
.pg-msg.user .pg-bubble { background: var(--accent); color: #fff; }
.pg-msg.assistant .pg-bubble { background: var(--surface-faint, rgba(255,255,255,0.04)); border: 1px solid var(--border-faint); }
.pg-bubble.error { border-color: var(--amber); color: var(--amber); }
.pg-cursor { opacity: 0.6; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0; } }
.pg-input-row { display: flex; gap: var(--space-2); align-items: flex-end; }
.pg-input {
  flex: 1; resize: none; padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md); border: 1px solid var(--border-faint);
  background: var(--surface-faint, transparent); color: inherit; font-size: var(--text-sm);
  font-family: inherit;
}
.pg-input:focus { outline: none; border-color: var(--accent); }
.pg-send {
  padding: var(--space-2) var(--space-4); border-radius: var(--radius-md);
  border: none; background: var(--accent); color: #fff; cursor: pointer; font-size: var(--text-sm);
}
.pg-send:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
