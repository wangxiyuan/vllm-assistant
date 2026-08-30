<script setup lang="ts">
/**
 * 远程任务日志查看器
 * oneshot 任务按 offset 增量追加；persistent 运行中拉 docker logs（tail 替换）。
 * 任务运行中每 2s 轮询，结束后停轮询。
 */
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { api } from '@/api/client'

const props = defineProps<{ jobId: number }>()

const content = ref('')
const jobStatus = ref<string>('')
const following = ref(true)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null
let offset = 0
const logBox = ref<HTMLElement | null>(null)

function render(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

async function poll() {
  if (loading.value) return
  loading.value = true
  try {
    const res = await api<{ mode: string; content: string; status: string; offset?: number; size?: number }>(
      `/api/npu/jobs/${props.jobId}/log?offset=${offset}`)
    jobStatus.value = res.status
    if (res.mode === 'tail') {
      content.value = res.content
    } else if (res.content) {
      content.value += res.content
      offset = res.offset ?? offset
    }
    if (following.value) {
      await nextTick()
      if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
    }
    if (res.status === 'pending' || res.status === 'running') {
      timer = setTimeout(poll, 2000)
    }
  } catch (e: any) {
    content.value += `\n[日志拉取失败] ${e.message || e}\n`
  } finally {
    loading.value = false
  }
}

watch(() => props.jobId, () => {
  offset = 0
  content.value = ''
  if (timer) clearTimeout(timer)
  poll()
})

onMounted(poll)
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="log-viewer">
    <div class="log-toolbar">
      <span class="log-status">状态：<b>{{ jobStatus || '…' }}</b></span>
      <label class="follow-toggle">
        <input type="checkbox" v-model="following" /> 跟随滚动
      </label>
    </div>
    <pre ref="logBox" class="log-box" v-html="render(content)"></pre>
  </div>
</template>

<style scoped>
.log-viewer { display: flex; flex-direction: column; gap: var(--space-1); min-height: 0; }
.log-toolbar { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-xs); color: var(--text-tertiary); }
.log-status b { color: var(--accent); }
.follow-toggle { display: flex; align-items: center; gap: 4px; cursor: pointer; user-select: none; }
.log-box {
  flex: 1; min-height: 200px; max-height: 480px; overflow: auto;
  background: var(--surface-faint, #0a0e14); color: #9fb3c8;
  padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  border: 1px solid var(--border-faint); font-size: 12px; line-height: 1.5;
  font-family: 'SF Mono', Menlo, Consolas, monospace; white-space: pre-wrap;
  word-break: break-all; margin: 0;
}
</style>
