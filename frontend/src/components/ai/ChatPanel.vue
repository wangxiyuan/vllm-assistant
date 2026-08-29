<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, nextTick, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import type { AIAgentStore } from '@/stores/aiAgent'
import { useAppStore } from '@/stores/app'
import { renderMarkdown } from '@/composables/useMarkdown'
import { api } from '@/api/client'
import Icon from '@/components/common/Icon.vue'

// 可复用的聊天面板：消息流 + 过程步骤渲染 + 输入框。
// 被 /ai-agent 页与各业务页的 ChatDrawer 共用。
// store 由父组件注入：AI 页传 aiAgent store，抽屉传独立的 chatDrawer store（会话上下文隔离）。
const props = defineProps<{ store: AIAgentStore }>()
const agentStore = props.store
const appStore = useAppStore()
const router = useRouter()
const inputText = ref('')
const chatContainer = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)

// 过程步骤展示：只显示最近 N 条，太长时折叠更早的，避免页面被刷屏
const MAX_VISIBLE_STEPS = 12
const visibleSteps = computed(() => {
  const steps = agentStore.streamingSteps
  if (steps.length <= MAX_VISIBLE_STEPS) return steps
  return steps.slice(-MAX_VISIBLE_STEPS)
})
const hiddenStepCount = computed(() => {
  const total = agentStore.streamingSteps.length
  return Math.max(0, total - MAX_VISIBLE_STEPS)
})
// 单独拆分 thinking / tool 步，便于分别渲染与美化，同时保持顺序（filter 保序）
const visibleThinkingSteps = computed(() => streamingStepsByType('thinking').slice(-MAX_VISIBLE_STEPS))
const visibleToolSteps = computed(() => streamingStepsByType('tool_call').slice(-MAX_VISIBLE_STEPS))
function streamingStepsByType(type: string) {
  return agentStore.streamingSteps.filter(s => s.type === type)
}
const stepCountSummary = computed(() => {
  const steps = agentStore.streamingSteps
  const tools = steps.filter(s => s.type === 'tool_call').length
  const rounds = new Set(steps.filter(s => s.round != null).map(s => s.round)).size
  const maxRound = steps.reduce((m, s) => Math.max(m, s.round || 0), 0)
  const currentRound = maxRound || 1
  if (tools === 0) return `${steps.length} 步`
  return `第 ${currentRound} 轮 / ${tools} 次工具`
})
// 当前 session 是不是正在被生成中那个：用于决定流式气泡 / 停止按钮 / 输入框禁用状态
const isStreamingHere = computed(() =>
  agentStore.streaming &&
  agentStore.currentSessionId === agentStore.activeStreamingSessionId
)

const isComposing = ref(false)

interface QuickPromptItem {
  id: number
  text: string
  sort_order: number
}

const quickPrompts = ref<QuickPromptItem[]>([])
const quickPromptsLoading = ref(false)
const editingPromptIdx = ref<number | null>(null)
const editingPromptText = ref('')
const showAddPrompt = ref(false)
const newPromptText = ref('')

async function loadQuickPrompts() {
  quickPromptsLoading.value = true
  try {
    const data: any = await api('/api/ai-agent/quick-prompts')
    quickPrompts.value = data || []
  } catch (_) {
  } finally {
    quickPromptsLoading.value = false
  }
}

function usePrompt(text: string) {
  inputText.value = text
  inputEl.value?.focus()
}

function startEditPrompt(idx: number) {
  editingPromptIdx.value = idx
  editingPromptText.value = quickPrompts.value[idx].text
}

async function saveEditPrompt() {
  const prompt = quickPrompts.value[editingPromptIdx.value!]
  if (editingPromptIdx.value !== null && editingPromptText.value.trim() && prompt) {
    try {
      const data: any = await api(`/api/ai-agent/quick-prompts/${prompt.id}`, {
        method: 'PUT', body: JSON.stringify({ text: editingPromptText.value.trim() }),
      })
      quickPrompts.value[editingPromptIdx.value] = data
    } catch (_) {}
  }
  editingPromptIdx.value = null
  editingPromptText.value = ''
}

function cancelEditPrompt() {
  editingPromptIdx.value = null
  editingPromptText.value = ''
}

async function deletePrompt(idx: number) {
  const prompt = quickPrompts.value[idx]
  try {
    await api(`/api/ai-agent/quick-prompts/${prompt.id}`, { method: 'DELETE' })
    quickPrompts.value.splice(idx, 1)
  } catch (_) {}
}

async function addPrompt() {
  if (newPromptText.value.trim()) {
    try {
      const data: any = await api('/api/ai-agent/quick-prompts', {
        method: 'POST', body: JSON.stringify({ text: newPromptText.value.trim() }),
      })
      quickPrompts.value.push(data)
    } catch (_) {}
  }
  newPromptText.value = ''
  showAddPrompt.value = false
}

const editingMsgIdx = ref<number | null>(null)
const editingMsgText = ref('')
// 已完成 assistant 消息「处理过程」折叠展开状态（按消息下标）
const showMsgProcess = ref<Set<string>>(new Set())
// 已完成消息里每个工具返回结果的折叠状态（key: "msgId:toolIdx"）
const openMsgTools = ref<Set<string>>(new Set())
// 错误消息的重试状态（按 session 标识，避免重试时状态残留）
const retrying = ref(false)

function toggleMsgProcess(msgId: string) {
  const s = new Set(showMsgProcess.value)
  if (s.has(msgId)) s.delete(msgId)
  else s.add(msgId)
  showMsgProcess.value = s
}

function toggleMsgTool(msgId: string, si: number) {
  const key = `${msgId}:${si}`
  const s = new Set(openMsgTools.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  openMsgTools.value = s
}

function openMsgTool(msgId: string, si: number): boolean {
  return openMsgTools.value.has(`${msgId}:${si}`)
}

const copiedMsgId = ref<string | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | null = null

function copyMessageContent(msgId: string | undefined, content: string) {
  const text = content || ''
  const id = msgId ?? ''
  const done = () => {
    copiedMsgId.value = id
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copiedMsgId.value = null }, 2000)
  }
  if (!navigator.clipboard) {
    fallbackCopy(text); done(); return
  }
  navigator.clipboard.writeText(text).then(done).catch(() => {
    fallbackCopy(text); done()
  })
}

async function retrySend() {
  if (!agentStore.messages.length || retrying.value) return
  const lastIndex = agentStore.messages.length - 1
  if (agentStore.messages[lastIndex].role !== 'user') return
  retrying.value = true
  await agentStore.retriggerFrom(lastIndex)
  retrying.value = false
}

function processSummary(steps: any[]): string {
  if (!steps || !steps.length) return ''
  const tools = steps.filter(s => s?.type === 'tool_call').length
  if (tools === 0) return `${steps.length} 步`
  return `${steps.length} 步 / ${tools} 次工具`
}

function startEditMsg(idx: number) {
  editingMsgIdx.value = idx
  editingMsgText.value = agentStore.messages[idx].content
}

function saveEditMsg() {
  if (editingMsgIdx.value !== null && editingMsgText.value.trim()) {
    agentStore.editUserMessage(editingMsgIdx.value, editingMsgText.value.trim())
  }
  editingMsgIdx.value = null
  editingMsgText.value = ''
}

function cancelEditMsg() {
  editingMsgIdx.value = null
  editingMsgText.value = ''
}

function regenerateResponse(userMsgIdx: number) {
  agentStore.retriggerFrom(userMsgIdx)
}

function hasArgs(args: any): boolean {
  return args && typeof args === 'object' && Object.keys(args).length > 0
}

function formatArgs(args: any): string {
  if (!args || typeof args !== 'object') return ''
  // 常见字段优先 + 截断长字符串
  const PRIORITY = ['query', 'keyword', 'file_path', 'repo', 'file_pattern', 'q']
  const parts: string[] = []
  const used = new Set<string>()
  for (const k of PRIORITY) {
    if (k in args) {
      parts.push(formatArgPair(k, args[k]))
      used.add(k)
    }
  }
  for (const [k, v] of Object.entries(args)) {
    if (used.has(k)) continue
    if (parts.length >= 3) break
    parts.push(formatArgPair(k, v))
  }
  return parts.join(', ')
}

function formatArgPair(k: string, v: any): string {
  let s = String(v ?? '')
  if (s.length > 40) s = s.slice(0, 38) + '…'
  return `${k}=${s}`
}

function formatTokens(n: number | undefined): string {
  if (n == null) return ''
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return `${n}`
}

function toolResultText(result: any): string {
  if (result == null) return ''
  try {
    const obj = typeof result === 'string' ? JSON.parse(result) : result
    if (typeof obj === 'string') return obj
    const s = JSON.stringify(obj, null, 2)
    return s.length > 2000 ? s.slice(0, 2000) + '…[已截断]' : s
  } catch {
    return String(result)
  }
}

function formatDuration(s: number | null | undefined): string {
  if (s == null) return ''
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}m${sec}s`
}

function formatTimeShort(isoStr: string): string {
  const d = new Date(isoStr)
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (d.toDateString() === now.toDateString()) return hhmm
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return `昨天 ${hhmm}`
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}/${d.getDate()} ${hhmm}`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${hhmm}`
}

// 实时最终回答：末尾加光标，避免整段闪烁
function renderMarkdownPlusCursor(t: string): string {
  return renderMarkdown(t)
}

function fallbackCopy(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
    appStore.showToast('已复制', '', 'info')
  } catch {
    appStore.showToast('复制失败', '请手动选择复制', 'error')
  }
  document.body.removeChild(textarea)
}

onMounted(() => {
  loadQuickPrompts()
})

// 滚动到底部（nearest 保留用户可能的中间位置不会强跳）
function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

// 用户是否"贴底"：距底部 < 80px 视为贴底（用于流式中自动跟随）
function isNearBottom(): boolean {
  const el = chatContainer.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

// 底部固定指示器：流式中若用户滚离底部，提示可一键回底
const showScrollHint = ref(false)
let scrollHintTimer: ReturnType<typeof setTimeout> | null = null
function onChatScroll() {
  if (!agentStore.streaming) return
  if (isNearBottom()) {
    showScrollHint.value = false
  } else {
    showScrollHint.value = true
    if (scrollHintTimer) clearTimeout(scrollHintTimer)
    scrollHintTimer = setTimeout(() => { showScrollHint.value = false }, 4000)
  }
}

// 流式中：内容增长时，若用户贴底则自动跟随滚动（工具结果/思考/回答都覆盖）
watch(() => [
  agentStore.streamingFinal,
  agentStore.liveThinking,
  agentStore.liveAnswer,
  agentStore.streamingSteps?.length,
], () => {
  if (agentStore.streaming && isNearBottom()) {
    scrollToBottom()
  }
}, { deep: true })

// 切会话 / 首次加载完成后滚动到底部
watch(() => agentStore.currentSessionId, () => {
  scrollToBottom()
})
watch(() => agentStore.loadingSession, (val) => {
  if (!val) scrollToBottom()
})

async function send() {
  if (isComposing.value) return
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''
  await agentStore.sendMessage(text)
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

// Enter 发送 / Shift+Enter 换行；输入法组合中的 Enter 不拦截（避免打断选词）
function onInputEnter(e: KeyboardEvent) {
  if (isComposing.value || e.shiftKey) return
  e.preventDefault()
  send()
}

// textarea 自适应高度（1 行起步，最高 160px 后内部滚动）
function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}
watch(inputText, () => nextTick(autoGrow))

// 供外部（表单 / 抽屉）直接发送一条消息
function sendText(text: string) {
  if (!text || !text.trim() || isStreamingHere.value) return
  agentStore.sendMessage(text.trim())
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

// AI 回复里的站内链接（如 /personal-todo）用路由跳转，不整页刷新
function onMessagesClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest?.('a')
  if (!a) return
  const href = a.getAttribute('href') || ''
  if (href.startsWith('/')) {
    e.preventDefault()
    router.push(href)
  }
}

// 供外部（ChatDrawer / 页面入口）预填输入框
function setInput(text: string) {
  inputText.value = text || ''
}

function focusInput() {
  inputEl.value?.focus()
}

defineExpose({ setInput, focusInput, sendText })
</script>

<template>
  <div class="agent-chat">
    <div ref="chatContainer" class="chat-messages" @scroll="onChatScroll" @click="onMessagesClick">
      <button v-if="showScrollHint" class="scroll-hint-btn" @click="scrollToBottom">
        <Icon name="chevronRight" :size="12" />
        回到底部
      </button>
      <div v-for="(msg, i) in agentStore.messages" :key="msg.id || i"
           class="chat-message" :class="'msg-' + msg.role">
        <div class="msg-avatar">{{ msg.role === 'user' ? 'U' : 'AI' }}</div>
        <div class="msg-body">
          <div v-if="editingMsgIdx === i" class="msg-edit-row">
            <textarea class="textarea msg-edit-textarea w-100" v-model="editingMsgText" rows="4" @keydown.enter.ctrl="saveEditMsg()" @keydown.escape="cancelEditMsg()"></textarea>
            <div class="msg-edit-actions">
              <button class="btn btn-xs btn-primary" @click="saveEditMsg()">保存并重新生成</button>
              <button class="btn btn-xs" @click="cancelEditMsg()">取消</button>
            </div>
          </div>
          <div v-if="msg.role === 'assistant' && msg.steps?.length" class="msg-process-compact">
            <button class="tool-result-toggle" @click="toggleMsgProcess(msg.id!)">
              <span class="tool-result-arrow" :class="{ open: showMsgProcess.has(msg.id!) }">▸</span>
              <Icon name="gear" :size="11" />
              <span>查看处理过程 ({{ processSummary(msg.steps) }})</span>
            </button>
            <div v-if="showMsgProcess.has(msg.id!)" class="msg-process-panel">
              <div v-for="(step, si) in msg.steps" :key="si"
                   class="agent-tool-block" :class="{ 'step-panel-thinking': step.type === 'thinking' }">
                <div v-if="step.type === 'thinking'" class="agent-step step-thinking">
                  <span class="step-pill step-pill-think"><Icon name="brain" :size="12" /></span>
                  <span class="step-text" v-html="renderMarkdown(step.thinking || '')"></span>
                </div>
                <template v-else-if="step.type === 'tool_call'">
                  <div class="agent-tool-head">
                    <span class="step-pill step-pill-tool"><Icon name="wrench" :size="12" /></span>
                    <code class="tool-name">{{ step.tool?.name }}</code>
                    <span v-if="step.tool?.args && hasArgs(step.tool.args)" class="step-tool-args">{{ formatArgs(step.tool.args) }}</span>
                    <span v-if="step.tool?.result !== undefined" class="tool-status"><span class="step-tool-done"><Icon name="check" :size="12" /><span>完成</span></span></span>
                  </div>
                  <div class="agent-tool-result">
                    <button class="tool-result-toggle" @click="toggleMsgTool(msg.id!, si)" style="padding:2px 10px 8px;">
                      <span class="tool-result-arrow" :class="{ open: openMsgTool(msg.id!, si) }">▸</span>
                      <span>查看返回结果</span>
                    </button>
                    <div v-if="openMsgTool(msg.id!, si)" class="tool-result-body" style="margin:0 10px 8px;" v-html="renderMarkdown(toolResultText(step.tool?.result))"></div>
                  </div>
                </template>
              </div>
            </div>
          </div>
          <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
          <div v-if="msg.role === 'assistant' || msg.usage || msg.duration_s != null" class="msg-meta-line">
            <button v-if="msg.role === 'assistant'" class="msg-copy-btn" @click="copyMessageContent(msg.id, msg.content)" title="复制回答">
              <svg v-if="copiedMsgId !== msg.id" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <Icon v-else :size="12" name="check" />
            </button>
            <template v-if="msg.role === 'assistant' && (msg.usage || msg.duration_s != null)">
              <span class="msg-meta-sep"></span>
              <Icon name="zap" :size="11" />
              <span v-if="msg.usage">≈{{ formatTokens(msg.usage.output_tokens) }} tokens</span>
              <span v-if="msg.duration_s != null">· {{ formatDuration(msg.duration_s) }}</span>
            </template>
            <span v-if="msg.role === 'assistant' && msg.created_at" class="msg-meta-time">{{ formatTimeShort(msg.created_at) }}</span>
          </div>
          <div v-if="msg.role === 'user'" class="msg-user-actions">
            <span v-if="msg.created_at" class="msg-time">{{ formatTimeShort(msg.created_at) }}</span>
            <span class="msg-meta-sep"></span>
            <button class="msg-action-btn" @click="startEditMsg(i)" title="编辑" :disabled="isStreamingHere">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="msg-action-btn" @click="regenerateResponse(i)" title="重新生成回复" v-if="i < agentStore.messages.length - 1 && agentStore.messages[i + 1]?.role === 'assistant'" :disabled="isStreamingHere">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            </button>
          </div>
        </div>
      </div>

      <!-- Streaming message: 思考过程 + 最终回答 -->
      <!-- 只在「当前 session 就是正在生成的那个」时显示，避免串台到别的 session -->
      <div v-if="isStreamingHere" class="chat-message msg-assistant msg-streaming">
        <div class="msg-avatar">AI</div>
        <div class="msg-content">
          <div v-if="agentStore.streamingSteps.length || agentStore.liveThinking" class="agent-process" open>
            <div class="agent-process-summary">
              <span class="agent-process-icon"><Icon name="gear" :size="12" /></span>
              <span>处理过程 <em class="summary-count">({{ stepCountSummary }})</em></span>
            </div>
            <div class="agent-process-body">
              <!-- 思考 -->
              <div v-for="(step, i) in visibleThinkingSteps" :key="step._key || i" class="agent-step step-thinking">
                <span class="step-pill step-pill-think"><Icon name="brain" :size="12" /></span>
                <span class="step-text" v-html="renderMarkdown(step.thinking || '')"></span>
              </div>
              <!-- 工具调用 -->
              <div v-for="(step, i) in visibleToolSteps" :key="step._key || i" class="agent-tool-block">
                <div class="agent-tool-head">
                  <span class="step-pill step-pill-tool"><Icon name="wrench" :size="12" /></span>
                  <code class="tool-name">{{ step.tool?.name }}</code>
                  <span v-if="step.tool?.args && hasArgs(step.tool.args)" class="step-tool-args">{{ formatArgs(step.tool.args) }}</span>
                  <span class="tool-status">
                    <span v-if="step.tool && step.tool.result !== undefined" class="step-tool-done"><Icon name="check" :size="12" /><span>完成</span></span>
                    <span v-else-if="agentStore.streaming" class="step-tool-pending"><span class="tool-spinner"></span><span>执行中</span></span>
                  </span>
                </div>
                <div v-if="step.tool && step.tool.result !== undefined" class="agent-tool-result">
                  <button class="tool-result-toggle" @click="step._open = !step._open">
                    <span class="tool-result-arrow" :class="{ open: step._open }">▸</span>
                    <span>查看返回结果</span>
                  </button>
                  <div v-if="step._open" class="tool-result-body" v-html="renderMarkdown(toolResultText(step.tool?.result))"></div>
                </div>
              </div>
              <!-- 实时思考打字（未提交为步骤前） -->
              <div v-if="agentStore.liveThinking" class="agent-step step-thinking step-thinking-live">
                <span class="step-pill step-pill-think"><Icon name="brain" :size="12" /></span>
                <span class="step-text" v-html="renderMarkdown(agentStore.liveThinking)"></span><span class="cursor-blink">▊</span>
              </div>
              <div v-if="hiddenStepCount > 0" class="agent-step step-hidden">
                <span class="step-text step-hidden-hint">
                  ⋯ 之前还有 {{ hiddenStepCount }} 步（向上滚动查看）
                </span>
              </div>
            </div>
          </div>

          <div class="agent-final">
            <div v-if="agentStore.streamingFinal" class="agent-final-text" v-html="renderMarkdown(agentStore.streamingFinal)"></div>
            <!-- 实时最终回答打字（未提交为最终前） -->
            <div v-else-if="agentStore.liveAnswer" class="agent-final-text" v-html="renderMarkdownPlusCursor(agentStore.liveAnswer)"></div>
            <span v-if="agentStore.streamingFinal || agentStore.liveAnswer" class="cursor-blink">▊</span>
            <div v-if="!agentStore.streamingFinal && !agentStore.liveAnswer" class="agent-thinking-indicator">
              <span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
              <span>AI 思考中</span>
            </div>
            <!-- 用量/耗时脚注 -->
            <div v-if="agentStore.lastUsage || agentStore.lastDuration != null" class="agent-usage">
              <Icon name="zap" :size="11" />
              <span v-if="agentStore.lastUsage">
                ≈{{ formatTokens(agentStore.lastUsage.output_tokens) }} tokens
              </span>
              <span v-if="agentStore.lastDuration != null">· {{ formatDuration(agentStore.lastDuration) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Error -->
      <div v-if="agentStore.error" class="chat-message msg-error">
        <div class="msg-avatar">!</div>
        <div class="msg-content">
          <div class="msg-content">{{ agentStore.error }}</div>
          <button class="btn btn-sm" style="margin-top:var(--space-2)" @click="retrySend" :disabled="retrying">
            {{ retrying ? '重试中…' : '重新生成' }}
          </button>
        </div>
      </div>

      <div v-if="agentStore.messages.length === 0 && !agentStore.streaming && !agentStore.loadingSession" class="quick-prompts-area">
        <div class="quick-prompts-header">
          <span class="quick-prompts-header-icon"><Icon name="zap" :size="18" /></span>
          <span class="quick-prompts-header-text">试试这样问我</span>
          <span class="quick-prompts-header-hint">点击直接提问</span>
        </div>
        <div v-if="quickPromptsLoading" class="empty-state" style="padding:var(--space-4);">加载中...</div>
        <div class="quick-prompts-list" v-else>
          <template v-for="(prompt, idx) in quickPrompts" :key="prompt.id">
            <div v-if="editingPromptIdx === idx" class="quick-prompt-card editing">
              <input class="input input-sm w-100" v-model="editingPromptText" @keydown.enter.prevent="saveEditPrompt()" @keydown.escape="cancelEditPrompt()" />
              <div class="quick-prompt-actions">
                <button class="btn btn-xs btn-primary" @click="saveEditPrompt()">保存</button>
                <button class="btn btn-xs" @click="cancelEditPrompt()">取消</button>
              </div>
            </div>
            <div v-else class="quick-prompt-card" @click="usePrompt(prompt.text)" role="button" tabindex="0">
              <span class="quick-prompt-icon"><Icon name="messageSquare" :size="15" /></span>
              <span class="quick-prompt-text">{{ prompt.text }}</span>
              <div class="quick-prompt-hover-actions">
                <button class="quick-prompt-edit" @click.stop="startEditPrompt(idx)" title="编辑">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="quick-prompt-delete" @click.stop="deletePrompt(idx)" title="删除">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
            </div>
          </template>
          <button v-if="showAddPrompt" class="quick-prompt-card editing">
            <input class="input input-sm w-100" v-model="newPromptText" placeholder="输入新的常用问题…" @keydown.enter.prevent="addPrompt()" @keydown.escape="showAddPrompt = false; newPromptText = ''" />
            <div class="quick-prompt-actions">
              <button class="btn btn-xs btn-primary" @click="addPrompt()">添加</button>
              <button class="btn btn-xs" @click="showAddPrompt = false; newPromptText = ''">取消</button>
            </div>
          </button>
          <button v-else class="quick-prompt-card add-card" @click="showAddPrompt = true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            <span>添加常用问题</span>
          </button>
        </div>
      </div>
    </div>

    <div class="chat-input-bar">
      <textarea ref="inputEl" class="textarea chat-input" rows="1"
             v-model="inputText"
             placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
             @keydown.enter="onInputEnter"
             @compositionstart="isComposing = true"
             @compositionend="isComposing = false"
             :disabled="isStreamingHere"></textarea>
      <button v-if="!isStreamingHere" class="btn btn-primary" @click="send()" :disabled="!inputText.trim()">
        发送
      </button>
      <button v-else class="btn btn-stop" @click="agentStore.stopGenerating()" title="停止生成">
        <Icon name="stop" :size="11" />
        停止
      </button>
    </div>
  </div>
</template>

<style scoped>
.agent-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: calc(100vh - 180px);
  align-self: flex-start;
  position: sticky;
  top: 0;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) 0;
  min-height: 0;
  position: relative;
}
/* 底部固定提示按钮：固定在聊天区底部居中浮动 */
.scroll-hint-btn {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: calc(var(--space-5) + 72px);
  z-index: var(--z-drop, 50);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--bg-elev-3);
  color: var(--text-secondary);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  cursor: pointer;
  box-shadow: var(--shadow-md, 0 2px 10px rgba(0,0,0,.2));
  opacity: 0;
  animation: scroll-hint-in .18s ease forwards;
}
.scroll-hint-btn:hover { color: var(--text-primary); }
.scroll-hint-btn svg { transform: rotate(-90deg); }
@keyframes scroll-hint-in { from { opacity: 0; transform: translateX(-50%) translateY(6px);} to { opacity: 1; transform: translateX(-50%) translateY(0);} }
.chat-message {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
  padding: 0 var(--space-5);
}
.msg-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: var(--text-xs); font-weight: 700;
  flex-shrink: 0;
}
.msg-user .msg-avatar { background: var(--amber-glow); color: var(--amber); }
.msg-assistant .msg-avatar { background: var(--signal-blue-glow); color: var(--signal-blue); }
/* 用户消息右对齐 + 气泡，与 AI 消息区分 */
.msg-user {
  flex-direction: row-reverse;
}
.msg-user .msg-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.msg-user .msg-content {
  background: var(--amber-glow-soft);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius) var(--radius-xs) var(--radius) var(--radius);
  padding: var(--space-3) var(--space-4);
  max-width: max(70%, 340px);
}
.msg-user .msg-footer {
  justify-content: flex-end;
}
.msg-user .msg-content :deep(code) { background: var(--bg-elev-2); }
/* 编辑时：编辑框占满宽度，方便改写长消息 */
.msg-user .msg-edit-row {
  align-self: stretch;
  width: 100%;
}
.msg-edit-textarea {
  font-family: var(--font-ui);
  resize: vertical;
  min-height: 96px;
}
.msg-content {
  flex: 1;
  font-size: var(--text-base);
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-word;
}
/* Markdown 渲染后的内联元素 */
.msg-content :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.9em;
  background: var(--bg-elev-2);
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  color: var(--amber-bright);
}
.msg-content :deep(pre) {
  background: var(--bg-elev-2);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  padding: var(--space-3) var(--space-4);
  overflow-x: auto;
  margin: 0 0 var(--space-4);
}
.msg-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.msg-content :deep(strong) { font-weight: 600; color: var(--text-primary); }
.msg-content :deep(em) { font-style: italic; }
.msg-content :deep(a) {
  color: var(--signal-blue);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.msg-content :deep(h1), .msg-content :deep(h2), .msg-content :deep(h3),
.msg-content :deep(h4), .msg-content :deep(h5), .msg-content :deep(h6) {
  margin: var(--space-5) 0 var(--space-3);
  color: var(--text-primary);
  font-weight: 600;
  line-height: 1.4;
}
.msg-content :deep(h1) { font-size: var(--text-2xl); border-bottom: 1px solid var(--border-faint); padding-bottom: var(--space-2); }
.msg-content :deep(h2) { font-size: var(--text-xl); }
.msg-content :deep(h3) { font-size: var(--text-lg); }
.msg-content :deep(h4) { font-size: var(--text-base); }
.msg-content :deep(ul),
.msg-content :deep(ol) { margin: 0 0 var(--space-4); padding-left: var(--space-6); }
.msg-content :deep(li) { margin-bottom: var(--space-1); }
.msg-content :deep(p) { margin: 0 0 var(--space-3); }
.msg-content :deep(p:last-child) { margin-bottom: 0; }
.msg-content :deep(blockquote) {
  margin: 0 0 var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-left: 4px solid var(--border);
  color: var(--text-secondary);
  background: var(--bg-elev-1);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.msg-content :deep(hr) {
  margin: var(--space-5) 0;
  border: none;
  border-top: 1px solid var(--border-faint);
}
.msg-content :deep(table) {
  width: 100%;
  margin: 0 0 var(--space-4);
  border-collapse: collapse;
  font-size: var(--text-sm);
}
.msg-content :deep(th), .msg-content :deep(td) {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-faint);
  text-align: left;
}
.msg-content :deep(th) {
  background: var(--bg-elev-2);
  font-weight: 600;
}
.msg-content :deep(h1),
.msg-content :deep(h2),
.msg-content :deep(h3),
.msg-content :deep(h4) { margin: var(--space-3) 0 var(--space-1); font-weight: 600; }
.msg-content :deep(blockquote) {
  border-left: 3px solid var(--border);
  padding-left: var(--space-3);
  color: var(--text-secondary);
  margin: var(--space-2) 0;
}
.msg-error .msg-content { color: var(--signal-red); }

.cursor-blink {
  animation: blink 1s step-end infinite;
  color: var(--text-secondary);
}
@keyframes blink {
  50% { opacity: 0; }
}

/* ── Agent 过程步骤 + 思考中指示器 ── */
.msg-streaming .msg-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.agent-process {
  background: var(--bg-elev-1);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  overflow: hidden;
}
.agent-process-summary {
  cursor: pointer;
  user-select: none;
  padding: 6px 10px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  gap: 6px;
  list-style: none;
}
.agent-process-summary::-webkit-details-marker { display: none; }
.agent-process-summary:hover { color: var(--text-secondary); }
.agent-process-icon { opacity: 0.7; }
.agent-process-body {
  padding: 4px 10px 8px;
  border-top: 1px solid var(--border-faint);
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 220px;
  overflow-y: auto;
}
.agent-step {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.step-icon { flex-shrink: 0; opacity: 0.85; }
.step-text { flex: 1; word-break: break-word; }
.step-thinking {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.6;
}

/* 思考 / 工具 徽标区分 */
.step-pill {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}
.step-pill-think {
  color: var(--signal-blue);
  background: var(--signal-blue-glow);
}
.step-pill-tool {
  color: var(--amber-bright);
  background: var(--amber-glow-soft);
}

/* 工具调用块 */
.agent-tool-block {
  margin: 2px 0;
  border: 1px solid var(--border-faint);
  border-left: 2px solid var(--amber);
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-elev-2);
}
.agent-tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  flex-wrap: wrap;
}
.agent-tool-head .tool-name {
  font-family: var(--font-mono, monospace);
  font-size: 0.92em;
  font-weight: 600;
  color: var(--amber-bright);
  background: var(--bg-elev-3);
  padding: 1px 6px;
  border-radius: 4px;
}
.step-tool-args {
  color: var(--text-tertiary);
  font-size: 0.85em;
  font-family: var(--font-mono, monospace);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}
.tool-status {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.85em;
  flex-shrink: 0;
}
.step-tool-done { color: var(--signal-green); display: inline-flex; align-items: center; gap: 3px; }
.step-tool-pending { color: var(--text-tertiary); display: inline-flex; align-items: center; gap: 5px; }
.tool-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 2px solid var(--text-tertiary);
  border-top-color: transparent;
  border-radius: 50%;
  vertical-align: -1px;
  animation: tool-spin 0.8s linear infinite;
}
@keyframes tool-spin {
  to { transform: rotate(360deg); }
}

/* 工具返回结果（可折叠） */
.tool-result-toggle {
  background: none;
  border: none;
  color: var(--text-tertiary);
  font-family: var(--font-ui);
  font-size: 0.85em;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px 5px;
}
.tool-result-toggle:hover { color: var(--text-secondary); }
.tool-result-arrow {
  display: inline-block;
  transition: transform var(--t-base);
  color: var(--amber);
  font-size: 0.7em;
}
.tool-result-arrow.open { transform: rotate(90deg); }

/* 已完成消息：折叠的处理过程 */
.msg-process-compact {
  margin-top: 6px;
  padding: 6px 10px;
  border: 1px solid var(--border-faint);
  border-radius: 6px;
  background: var(--bg-elev-1);
}
.msg-process-compact .tool-result-toggle {
  padding: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-tertiary);
}
.msg-process-compact .tool-result-toggle:hover { color: var(--text-secondary); }
.msg-process-panel {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 340px;
  overflow-y: auto;
  padding-right: 2px;
}
/* 滚动条美化 */
.msg-process-panel::-webkit-scrollbar { width: 6px; }
.msg-process-panel::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}
.msg-process-panel::-webkit-scrollbar-track { background: transparent; }
.msg-process-panel .agent-tool-block { margin: 0; flex-shrink: 0; }
.step-panel-thinking {
  border-left-color: var(--signal-blue) !important;
  border-color: var(--border-faint);
  margin-bottom: 2px;
}
.step-panel-thinking .step-thinking { padding: 6px 10px; }
/* 相邻 thinking 之间加分隔，避免粘连成一大块 */
.msg-process-panel .step-thinking + .agent-step,
.msg-process-panel .step-panel-thinking + .step-panel-thinking {
  border-top: 1px dashed var(--border-faint);
  padding-top: 6px;
  margin-top: 2px;
}
/* 工具返回结果区也独立滚动，超长内容看得清 */
.msg-process-panel .tool-result-body {
  max-height: 200px;
  overflow-y: auto;
}
.tool-result-body {
  margin: 0 10px 8px;
  padding: 6px 10px;
  border: 1px solid var(--border-faint);
  border-radius: 6px;
  background: var(--bg-elev-1);
  font-size: 0.9em;
  max-height: 220px;
  overflow-y: auto;
  color: var(--text-secondary);
}
.tool-result-body :deep(code) {
  font-family: var(--font-mono, monospace);
  font-size: 0.9em;
  background: var(--bg-elev-2);
  padding: 0 4px;
  border-radius: 3px;
}
.tool-result-body :deep(pre) {
  background: var(--bg-elev-2);
  border: 1px solid var(--border-faint);
  border-radius: 6px;
  padding: 8px 10px;
  overflow-x: auto;
  margin: 0;
}
.tool-result-body :deep(pre code) {
  background: transparent;
  padding: 0;
}

.step-thinking-live {
  opacity: 0.75;
}
/* 流式中相邻 thinking 分隔 */
.agent-process-body .step-thinking + .step-thinking {
  border-top: 1px dashed var(--border-faint);
  padding-top: 8px;
  margin-top: 4px;
}
.agent-usage,
.msg-usage {
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  opacity: 0.85;
}
.step-hidden-hint {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  font-style: italic;
}

.agent-thinking-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  font-style: italic;
}
.thinking-dots span {
  display: inline-block;
  animation: thinking-bounce 1.4s infinite ease-in-out;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes thinking-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-3px); opacity: 1; }
}

.chat-input-bar {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--border-faint);
  align-items: flex-end;
}
.chat-input {
  flex: 1;
  resize: none;
  min-height: 42px;
  max-height: 160px;
  line-height: 1.5;
  overflow-y: auto;
  font-family: var(--font-ui);
}
.btn-stop {
  background: var(--signal-red-glow, rgba(255,107,107,0.15));
  color: var(--signal-red, #ff6b6b);
  border: 1px solid var(--signal-red, #ff6b6b);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-stop:hover {
  background: var(--signal-red, #ff6b6b);
  color: white;
}
.stop-icon {
  font-size: 0.7em;
  line-height: 1;
}

/* Quick prompts */
.quick-prompts-area {
  padding: var(--space-6) var(--space-6) var(--space-4);
  text-align: center;
}
.quick-prompts-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  margin-bottom: var(--space-4);
}
.quick-prompts-header-icon {
  color: var(--accent);
  display: flex;
  margin-bottom: var(--space-1);
}
.quick-prompts-header-text {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.quick-prompts-header-hint {
  font-size: 12px;
  color: var(--text-tertiary);
}
.quick-prompts-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 560px;
  margin: 0 auto;
}
.quick-prompt-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-elev-2);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius-md);
  box-shadow: inset 3px 0 0 var(--accent);
  cursor: pointer;
  transition: all var(--t-fast);
  text-align: left;
}
.quick-prompt-card:hover {
  border-color: var(--accent);
  background: var(--bg-elev-3);
  box-shadow: var(--shadow-sm);
}
.quick-prompt-card.editing {
  cursor: default;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
  padding: var(--space-3);
  border-color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}
.quick-prompt-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  margin-top: 1px;
  color: var(--accent);
  opacity: 0.7;
}
.quick-prompt-card:hover .quick-prompt-icon {
  opacity: 1;
}
.quick-prompt-text {
  flex: 1;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.5;
  white-space: normal;
  word-break: break-word;
}
.quick-prompt-hover-actions {
  flex-shrink: 0;
  display: flex;
  gap: 1px;
  opacity: 0;
  transition: opacity var(--t-fast);
  margin-top: 1px;
}
.quick-prompt-card:hover .quick-prompt-hover-actions {
  opacity: 1;
}
.quick-prompt-edit,
.quick-prompt-delete {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: color var(--t-fast), background var(--t-fast);
}
.quick-prompt-edit:hover {
  color: var(--accent);
  background: var(--bg-elev-3);
}
.quick-prompt-delete:hover {
  color: var(--signal-red, #ff6b6b);
  background: var(--bg-elev-3);
}
.quick-prompt-actions {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
}
.quick-prompt-card.add-card {
  justify-content: center;
  align-items: center;
  color: var(--text-tertiary);
  border: 1px dashed var(--border-faint);
  border-radius: var(--radius-md);
  font-size: 13px;
  min-height: 44px;
}
.quick-prompt-card.add-card:hover {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--bg-elev-2);
  box-shadow: none;
}

/* Message actions */
.msg-body {
  flex: 1;
  min-width: 0;
}
.msg-actions {
  display: flex;
  gap: 2px;
  margin-top: var(--space-2);
  opacity: 0;
  transition: opacity var(--t-fast);
}
.chat-message:hover .msg-actions {
  opacity: 1;
}
.msg-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: color var(--t-fast), background var(--t-fast);
}
.msg-action-btn:hover {
  color: var(--accent);
  background: var(--bg-elev-2);
}
/* 用户消息操作行：时间 + 编辑/重试 右对齐，与 AI 回复的 meta 行对齐风格一致 */
.msg-user-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 2px;
  min-height: 20px;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.msg-user-actions .msg-time {
  font-size: var(--text-xs);
  color: var(--text-quaternary);
}
.msg-user-actions .msg-action-btn {
  width: 22px;
  height: 22px;
}
.msg-user-actions .msg-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.msg-edit-row {
  margin-bottom: var(--space-2);
}
/* 复制/用量/时间：同在一行，紧贴内容下方 */
.msg-meta-line {
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 20px;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.msg-copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--text-quaternary);
  padding: 3px 5px;
  margin-left: -5px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: color var(--t-fast), background var(--t-fast);
}
.msg-copy-btn:hover {
  color: var(--text-secondary);
  background: var(--bg-elev-2);
}
.msg-copy-btn svg { opacity: .85; }
.msg-meta-sep {
  width: 1px;
  height: 12px;
  background: var(--border-faint);
  flex-shrink: 0;
}
.msg-meta-time {
  font-size: var(--text-xs);
  color: var(--text-quaternary);
  flex-shrink: 0;
}
.msg-edit-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-1);
  justify-content: flex-end;
}
.msg-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-2);
  min-height: 20px;
}
.msg-time {
  font-size: var(--text-xs);
  color: var(--text-quaternary);
}
</style>
