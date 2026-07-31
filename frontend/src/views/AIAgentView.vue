<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, nextTick, watch, computed } from 'vue'
import { useAIAgentStore, KNOWLEDGE_TYPE_LABELS, KNOWLEDGE_TYPE_ORDER } from '@/stores/aiAgent'
import { useAppStore } from '@/stores/app'
import { renderMarkdown } from '@/composables/useMarkdown'
import { api } from '@/api/client'
import Icon from '@/components/common/Icon.vue'

const agentStore = useAIAgentStore()
const appStore = useAppStore()
const inputText = ref('')
const chatContainer = ref<HTMLElement | null>(null)

// Sidebar tab: 'sessions' | 'knowledge'
const sidebarTab = ref<'sessions' | 'knowledge'>('sessions')

// Knowledge detail modal
const showKbModal = ref(false)
const modalType = ref('')
const modalSearchInput = ref('')
const modalLoading = ref(false)
const modalEntries = ref<any[]>([])
const modalTotal = ref(0)
const modalOffset = ref(0)
const modalHasMore = ref(false)
const MODAL_PAGE_SIZE = 50

// Export
const exportMenuOpen = ref(false)
const exportBtnRef = ref<HTMLElement | null>(null)
const exportMenuStyle = ref<Record<string, string>>({})

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

// Add knowledge modal
const showAddModal = ref(false)
const addForm = ref({ content: '', source_ref: '', tags: '' })
const addSubmitting = ref(false)
const addError = ref('')

function openAddModal() {
  addForm.value = { content: '', source_ref: '', tags: '' }
  addError.value = ''
  showAddModal.value = true
}

function closeAddModal() {
  showAddModal.value = false
}

async function handleAddKnowledge() {
  const content = addForm.value.content.trim()
  if (!content) {
    addError.value = '请输入知识内容'
    return
  }
  addSubmitting.value = true
  addError.value = ''
  try {
    const tags = addForm.value.tags
      .split(/[,，]/)
      .map(t => t.trim())
      .filter(Boolean)
    await api('/api/ai-agent/memories', {
      method: 'POST',
      body: JSON.stringify({
        content,
        source_type: 'manual',
        source_ref: addForm.value.source_ref.trim() || undefined,
        tags: tags.length ? tags : undefined,
      }),
    })
    appStore.showToast('知识已添加', '', 'success')
    showAddModal.value = false
    agentStore.loadKbStats()
  } catch (e: any) {
    addError.value = e.message
  } finally {
    addSubmitting.value = false
  }
}

function toggleExportMenu() {
  if (exportMenuOpen.value) {
    exportMenuOpen.value = false
    return
  }
  if (exportBtnRef.value) {
    const rect = exportBtnRef.value.getBoundingClientRect()
    exportMenuStyle.value = {
      position: 'fixed',
      bottom: `${window.innerHeight - rect.top + 4}px`,
      left: `${rect.right - 180}px`,
    }
  }
  exportMenuOpen.value = true
}

function closeExportMenu() {
  exportMenuOpen.value = false
}

function handleOutsideClick(e: MouseEvent) {
  if (!exportMenuOpen.value) return
  const target = e.target as HTMLElement
  if (exportBtnRef.value?.contains(target)) return
  if (target?.closest?.('.export-dropdown')) return
  closeExportMenu()
}

onMounted(() => {
  agentStore.loadSessions()
  loadQuickPrompts()
  document.addEventListener('click', handleOutsideClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleOutsideClick)
})

// 流式输出时自动滚动到底部
watch(() => agentStore.streamingFinal, () => {
  if (agentStore.streaming) {
    nextTick(() => {
      if (chatContainer.value) {
        chatContainer.value.scrollTop = chatContainer.value.scrollHeight
      }
    })
  }
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

// Knowledge base
async function openKbTab() {
  sidebarTab.value = 'knowledge'
  if (!agentStore.kbStats) {
    await agentStore.loadKbStats()
  }
}

// Knowledge detail modal
async function openKbDetail(sourceType: string) {
  modalType.value = sourceType
  modalSearchInput.value = ''
  modalEntries.value = []
  modalOffset.value = 0
  modalHasMore.value = false
  modalTotal.value = 0
  showKbModal.value = true
  await loadModalEntries()
}

async function loadModalEntries(append: boolean = false) {
  modalLoading.value = true
  try {
    const params = new URLSearchParams({
      list_by_type: modalType.value,
      offset: String(append ? modalOffset.value : 0),
      limit: String(MODAL_PAGE_SIZE),
    })
    const q = modalSearchInput.value.trim()
    if (q) params.set('q', q)

    const data: any = await api(`/api/ai-agent/memories?${params}`)

    if (append) {
      modalEntries.value.push(...(data.results || []))
    } else {
      modalEntries.value = data.results || []
    }
    modalEntries.value.forEach((e: any) => { e._expanded = false })
    modalTotal.value = data.total || 0
    modalOffset.value = append ? modalOffset.value + (data.results || []).length : (data.results || []).length
    modalHasMore.value = data.has_more || false
  } catch (e: any) {
    appStore.showToast('加载失败', e.message, 'error')
  } finally {
    modalLoading.value = false
  }
}

function onModalSearch() {
  loadModalEntries(false)
}

function loadMoreModalEntries() {
  if (modalHasMore.value && !modalLoading.value) {
    loadModalEntries(true)
  }
}

// Close modal
function closeKbModal() {
  showKbModal.value = false
}

// Copy knowledge entry content
function copyEntryContent(content: string) {
  if (!navigator.clipboard) {
    fallbackCopy(content)
    return
  }
  navigator.clipboard.writeText(content).then(() => {
    appStore.showToast('已复制', '', 'info')
  }).catch(() => {
    fallbackCopy(content)
  })
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

async function deleteEntry(entry: any) {
  const result = await appStore.showConfirm({
    title: '删除知识条目',
    message: `确定删除这条知识吗？\n\n${entry.content.slice(0, 100)}...`,
    confirmText: '删除',
    danger: true,
  })
  if (!result.confirmed) return
  try {
    await api(`/api/ai-agent/memories/${entry.id}`, { method: 'DELETE' })
    appStore.showToast('已删除', '', 'info')
    modalEntries.value = modalEntries.value.filter(e => e.id !== entry.id)
    modalTotal.value = Math.max(0, modalTotal.value - 1)
    agentStore.loadKbStats()
  } catch (e: any) {
    appStore.showToast('删除失败', e.message, 'error')
  }
}

// Export session as markdown
function doExportMarkdown() {
  try {
    const md = agentStore.exportSessionAsMarkdown()
    if (!md) {
      closeExportMenu()
      appStore.showToast('没有可导出的消息', '', 'info')
      return
    }
    const session = agentStore.sessions.find(s => s.id === agentStore.currentSessionId)
    const title = session?.title?.replace(/[\\/:*?"<>|]/g, '_') || 'ai-agent-chat'
    const filename = `${title}-${new Date().toISOString().slice(0, 10)}.md`
    agentStore.downloadAsMarkdown(md, filename)
    closeExportMenu()
    appStore.showToast('已导出', filename, 'success')
  } catch (e: any) {
    closeExportMenu()
    appStore.showToast('导出失败', e?.message || '未知错误', 'error')
  }
}

function doCopyToClipboard() {
  try {
    const md = agentStore.exportSessionAsMarkdown()
    if (!md) {
      closeExportMenu()
      appStore.showToast('没有可导出的消息', '', 'info')
      return
    }
    if (!navigator.clipboard) {
      closeExportMenu()
      fallbackCopy(md)
      return
    }
    navigator.clipboard.writeText(md).then(() => {
      closeExportMenu()
      appStore.showToast('已复制到剪贴板', '', 'info')
    }).catch(() => {
      closeExportMenu()
      fallbackCopy(md)
    })
  } catch (e: any) {
    closeExportMenu()
    appStore.showToast('复制失败', e?.message || '未知错误', 'error')
  }
}

// Sorted knowledge types
const sortedKbTypes = computed(() => {
  const stats = agentStore.kbStats?.by_type
  if (!stats) return []
  return KNOWLEDGE_TYPE_ORDER
    .filter(t => t in stats)
    .map(t => ({ key: t, label: KNOWLEDGE_TYPE_LABELS[t] || t, count: stats[t] }))
})
</script>

<template>
  <div class="view-container ai-agent-view">
    <div class="view-header">
      <h2 class="view-title">AI Agent</h2>
      <div class="view-actions">
      </div>
    </div>

    <div class="ai-agent-layout">
      <!-- Sidebar with tabs -->
      <div class="agent-sessions">
        <div class="agent-sessions-tabs">
          <button class="agent-tab" :class="{ active: sidebarTab === 'sessions' }" @click="sidebarTab = 'sessions'">会话历史</button>
          <button class="agent-tab" :class="{ active: sidebarTab === 'knowledge' }" @click="openKbTab()">知识库</button>
        </div>

        <!-- Sessions tab -->
        <div v-if="sidebarTab === 'sessions'" class="agent-tab-content">
          <div class="agent-session-list">
            <div v-for="s in agentStore.sessions" :key="s.id"
                 class="agent-session-item"
                 :class="{ active: s.id === agentStore.currentSessionId }"
                 @click="agentStore.switchSession(s.id)">
              <div class="agent-session-title">{{ s.title }}</div>
              <div class="agent-session-meta">{{ s.message_count }} 条消息</div>
              <button class="agent-session-delete" @click.stop="agentStore.deleteSession(s.id)" title="删除会话">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
            <div v-if="agentStore.sessions.length === 0" class="empty-state" style="padding:var(--space-5)">
              暂无会话
            </div>
          </div>
          <div class="agent-session-bottom">
            <button class="agent-session-bottom-btn" @click="agentStore.createSession()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              新对话
            </button>
            <div class="agent-session-bottom-sep"></div>
            <div class="tt-host" style="position:relative">
              <button ref="exportBtnRef" class="agent-session-bottom-btn" @click.stop="toggleExportMenu">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                导出
              </button>
              <div v-if="exportMenuOpen" class="export-dropdown" :style="exportMenuStyle" @click.stop>
                <div class="export-dropdown-item" @click="doExportMarkdown">
                  下载为 .md 文件
                </div>
                <div class="export-dropdown-item" @click="doCopyToClipboard">
                  复制到剪贴板
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Knowledge base tab -->
        <div v-if="sidebarTab === 'knowledge'" class="agent-tab-content">
          <div v-if="agentStore.kbLoading" class="empty-state" style="padding:var(--space-5)">加载中...</div>
          <div v-else-if="!agentStore.kbStats" class="empty-state" style="padding:var(--space-5)">暂无知识库数据</div>
          <div v-else class="kb-type-list">
            <div class="kb-stats-header">
              <span class="kb-stats-total">共 {{ agentStore.kbStats.total }} 条</span>
              <button class="btn btn-sm" @click="openAddModal()">+ 添加知识</button>
            </div>
            <div v-for="t in sortedKbTypes" :key="t.key"
                 class="kb-type-item"
                 @click="openKbDetail(t.key)">
              <div class="kb-type-label">{{ t.label }}</div>
              <div class="kb-type-count">{{ t.count }}</div>
            </div>
            <div v-if="sortedKbTypes.length === 0" class="empty-state" style="padding:var(--space-5)">
              暂无知识分类
            </div>
          </div>
        </div>
      </div>

      <!-- Chat area -->
      <div class="agent-chat">
        <div ref="chatContainer" class="chat-messages">
          <div v-for="(msg, i) in agentStore.messages" :key="i"
               class="chat-message" :class="'msg-' + msg.role">
            <div class="msg-avatar">{{ msg.role === 'user' ? 'U' : 'AI' }}</div>
            <div class="msg-body">
              <div v-if="editingMsgIdx === i" class="msg-edit-row">
                <textarea class="textarea textarea-sm w-100" v-model="editingMsgText" rows="2" @keydown.enter.ctrl="saveEditMsg()" @keydown.escape="cancelEditMsg()"></textarea>
                <div class="msg-edit-actions">
                  <button class="btn btn-xs btn-primary" @click="saveEditMsg()">保存并重新生成</button>
                  <button class="btn btn-xs" @click="cancelEditMsg()">取消</button>
                </div>
              </div>
              <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="msg.role === 'user'" class="msg-actions">
                <button class="msg-action-btn" @click="startEditMsg(i)" title="编辑">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="msg-action-btn" @click="regenerateResponse(i)" title="重新生成回复" v-if="i < agentStore.messages.length - 1 && agentStore.messages[i + 1]?.role === 'assistant'">
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
              <div v-if="agentStore.streamingSteps.length" class="agent-process" open>
                <div class="agent-process-summary">
                  <span class="agent-process-icon"><Icon name="gear" :size="12" /></span>
                  <span>处理过程 ({{ stepCountSummary }})</span>
                </div>
                <div class="agent-process-body">
                  <div v-for="(step, i) in visibleSteps" :key="step._key || i" class="agent-step" :class="'step-' + step.type">
                    <div v-if="step.type === 'thinking'" class="step-thinking">
                      <span class="step-icon"><Icon name="brain" :size="12" /></span>
                      <span class="step-text" v-html="renderMarkdown(step.thinking || '')"></span>
                    </div>
                    <div v-else-if="step.type === 'tool_call'" class="step-tool-call">
                      <span class="step-icon"><Icon name="wrench" :size="12" /></span>
                      <span class="step-text">
                        调用工具 <code>{{ step.tool?.name }}</code>
                        <span v-if="step.tool?.args && hasArgs(step.tool.args)" class="step-tool-args">({{ formatArgs(step.tool.args) }})</span>
                        <span v-if="step.tool && step.tool.result !== undefined" class="step-tool-done"><Icon name="check" :size="11" /></span>
                        <span v-else-if="agentStore.streaming" class="step-tool-pending"><Icon name="hourglass" :size="11" /></span>
                      </span>
                    </div>
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
                <span v-if="agentStore.streamingFinal" class="cursor-blink">▊</span>
                <div v-else class="agent-thinking-indicator">
                  <span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                  <span>AI 思考中</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Error -->
          <div v-if="agentStore.error" class="chat-message msg-error">
            <div class="msg-content">{{ agentStore.error }}</div>
          </div>

          <div v-if="agentStore.messages.length === 0 && !agentStore.streaming" class="quick-prompts-area">
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
<input type="text" class="input input-lg chat-input"
               v-model="inputText"
               placeholder="输入消息…"
               @keydown.enter.prevent="send()"
               @compositionstart="isComposing = true"
               @compositionend="isComposing = false"
               :disabled="isStreamingHere" />
          <button v-if="!isStreamingHere" class="btn btn-primary" @click="send()" :disabled="!inputText.trim()">
            发送
          </button>
          <button v-else class="btn btn-stop" @click="agentStore.stopGenerating()" title="停止生成">
            <Icon name="stop" :size="11" />
            停止
          </button>
        </div>
      </div>
    </div>

    <!-- Knowledge detail modal -->
    <Teleport to="body">
      <div v-if="showKbModal" class="modal-backdrop" @click="closeKbModal()">
        <div class="modal modal-wide" @click.stop>
          <div class="modal-header">
            <h3>
              {{ KNOWLEDGE_TYPE_LABELS[modalType] || modalType }}
              <span class="count">{{ modalTotal }} 条</span>
            </h3>
            <div class="drawer-actions" style="margin-left:auto;">
              <input type="text" class="input input-sm" placeholder="搜索知识…"
                     v-model="modalSearchInput"
                     @keydown.enter.prevent="onModalSearch()" style="width:200px;" />
              <button class="btn btn-sm" @click="onModalSearch()">搜索</button>
              <button class="modal-close" @click="closeKbModal()" title="关闭">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>
          <div class="modal-body">
            <div v-if="modalLoading && !modalEntries.length" class="empty-state is-compact">加载中...</div>
            <div v-else-if="!modalEntries.length" class="empty-state is-compact">暂无数据</div>
            <div v-else class="kb-entry-list">
              <div v-for="entry in modalEntries" :key="entry.id" class="kb-entry-card">
                <div class="kb-entry-header">
                  <span class="badge" :class="'kb-source-' + entry.source_type">{{ KNOWLEDGE_TYPE_LABELS[entry.source_type] || entry.source_type }}</span>
                  <span v-if="entry.tags?.length" class="kb-entry-tags">
                    <span v-for="tag in entry.tags.slice(0, 5)" :key="tag" class="badge badge-tag">{{ tag }}</span>
                  </span>
                  <button class="btn btn-xs btn-ghost" style="margin-left:auto;flex-shrink:0" @click="copyEntryContent(entry.content)" title="复制内容">复制</button>
                  <button class="btn btn-xs btn-ghost" style="flex-shrink:0;color:var(--signal-red);" @click="deleteEntry(entry)" title="删除">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  </button>
                </div>
                <div class="kb-entry-body">
                  <div class="kb-entry-body-text">{{ entry.content.slice(0, entry._expanded ? undefined : 500) }}</div>
                  <button v-if="entry.content.length > 500" class="btn btn-xs btn-ghost" style="margin-top:var(--space-2);" @click="entry._expanded = !entry._expanded">
                    {{ entry._expanded ? '收起' : '展开全部 (' + entry.content.length + ' 字)' }}
                  </button>
                </div>
                <div class="kb-entry-footer">
                  <span v-if="entry.source_ref" class="kb-entry-ref">{{ entry.source_ref }}</span>
                  <span v-if="entry.updated_at" class="kb-entry-date">{{ entry.updated_at?.slice(0, 10) }}</span>
                </div>
              </div>
            </div>
            <div v-if="modalHasMore" class="load-more-wrap">
              <button class="btn btn-sm" :disabled="modalLoading" @click="loadMoreModalEntries()">
                {{ modalLoading ? '加载中…' : '加载更多' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Add knowledge modal -->
    <Teleport to="body">
      <div v-if="showAddModal" class="modal-backdrop" @click="closeAddModal()">
        <div class="modal" @click.stop>
          <div class="modal-header">
            <h3>添加知识</h3>
            <button class="modal-close" @click="closeAddModal()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">内容 <span class="text-danger">*</span></label>
              <textarea class="textarea" v-model="addForm.content"
                        placeholder="支持 Markdown 格式…"
                        style="min-height:180px;font-family:var(--font-mono);font-size:var(--text-sm);"></textarea>
            </div>
            <div class="form-group" style="margin-top:var(--space-4);">
              <label class="form-label">来源引用</label>
              <input class="input" type="text" v-model="addForm.source_ref" placeholder="如 vllm-project/vllm#1234（可选）" />
            </div>
            <div class="form-group" style="margin-top:var(--space-4);">
              <label class="form-label">标签</label>
              <input class="input" type="text" v-model="addForm.tags" placeholder="逗号分隔，如 attention, kernel（可选）" />
            </div>
            <div v-if="addError" class="form-error" style="margin-top:var(--space-3);color:var(--signal-red);font-size:var(--text-sm);">
              {{ addError }}
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="closeAddModal()" :disabled="addSubmitting">取消</button>
            <button class="btn btn-primary" @click="handleAddKnowledge()" :disabled="addSubmitting">
              {{ addSubmitting ? '提交中…' : '提交' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.ai-agent-view {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.ai-agent-layout {
  display: flex;
  flex: 1;
  gap: var(--space-5);
  overflow: hidden;
}

/* ── Sidebar ── */
.agent-sessions {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-faint);
  padding-right: var(--space-4);
  overflow: hidden;
  height: calc(100vh - 180px);
}

/* Sidebar tabs */
.agent-sessions-tabs {
  display: flex;
  gap: 0;
  margin-bottom: var(--space-4);
  background: var(--bg-elev-2);
  border-radius: var(--radius-sm);
  padding: 2px;
  border: 1px solid var(--border-faint);
  flex-shrink: 0;
}
.agent-tab {
  flex: 1;
  padding: 5px 8px;
  background: transparent;
  border: none;
  border-radius: var(--radius-xs);
  color: var(--text-secondary);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--t-base);
  text-align: center;
}
.agent-tab:hover {
  color: var(--text-primary);
}
.agent-tab.active {
  background: var(--bg-elev-3);
  color: var(--amber-bright);
  box-shadow: var(--shadow-sm);
}

/* Tab content area */
.agent-tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Session list */
.agent-session-list {
  flex: 1;
  overflow-y: auto;
  margin-bottom: var(--space-3);
}
.agent-session-item {
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  margin-bottom: 2px;
  position: relative;
}
.agent-session-item:hover { background: var(--bg-elev-2); }
.agent-session-item.active { background: var(--bg-elev-3); border-left: 2px solid var(--amber); }
.agent-session-title { font-size: var(--text-sm); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 20px; }
.agent-session-meta { font-size: var(--text-xs); color: var(--text-tertiary); }
.agent-session-delete {
  position: absolute; top: 4px; right: 4px;
  background: none; border: none; color: var(--text-tertiary);
  cursor: pointer; font-size: 16px; display: none;
}
.agent-session-item:hover .agent-session-delete { display: block; }

/* ── Session sidebar bottom bar ── */
.agent-session-bottom {
  display: flex;
  align-items: center;
  gap: 0;
  flex-shrink: 0;
  background: var(--bg-elev-2);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius);
  overflow: hidden;
  margin-top: var(--space-3);
}
.agent-session-bottom-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3);
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--t-base);
  white-space: nowrap;
  position: relative;
}
.agent-session-bottom-btn:hover {
  background: var(--bg-elev-3);
  color: var(--text-primary);
}
.agent-session-bottom-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.agent-session-bottom-btn:disabled:hover {
  background: transparent;
  color: var(--text-secondary);
}
.agent-session-bottom-btn svg {
  flex-shrink: 0;
  opacity: 0.8;
}
.agent-session-bottom-btn:hover svg {
  opacity: 1;
}
.agent-session-bottom-sep {
  width: 1px;
  height: 20px;
  background: var(--border-faint);
  flex-shrink: 0;
}

/* ── Knowledge base type list ── */
.kb-type-list {
  flex: 1;
  overflow-y: auto;
}
.kb-stats-header {
  padding: var(--space-2) var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: var(--space-2);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.kb-stats-total {
  font-weight: 600;
}
.kb-type-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  margin-bottom: 2px;
  transition: background var(--t-base);
}
.kb-type-item:hover {
  background: var(--bg-elev-2);
}
.kb-type-label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
}
.kb-type-count {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--amber);
  font-weight: 600;
  background: var(--amber-glow-soft);
  padding: 0 8px;
  border-radius: var(--radius-pill);
  min-width: 28px;
  text-align: center;
}

/* ── Knowledge entry list in modal ── */
.kb-entry-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.kb-entry-card {
  background: var(--bg-elev-2);
  border: 1px solid var(--border-faint);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color var(--t-base);
}
.kb-entry-card:hover {
  border-color: var(--border);
}
.kb-entry-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-elev-3);
  border-bottom: 1px solid var(--border-faint);
  flex-wrap: wrap;
}
.kb-entry-tags {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.kb-entry-body {
  padding: var(--space-4);
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
.kb-entry-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--border-faint);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.kb-entry-ref {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}
.kb-entry-date {
  flex-shrink: 0;
}

.load-more-wrap {
  padding: var(--space-5);
  text-align: center;
}

/* ── Chat area ── */
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
}
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
.step-thinking { color: var(--text-tertiary); font-style: italic; }
.step-tool-call code {
  background: var(--bg-elev-2);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.9em;
  font-family: var(--font-mono, monospace);
}
.step-tool-args {
  color: var(--text-tertiary);
  font-size: 0.85em;
  font-family: var(--font-mono, monospace);
  margin-left: 4px;
}
.step-tool-done { color: var(--signal-green); }
.step-tool-pending { color: var(--text-tertiary); }
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

/* ── Knowledge source badge colors ── */
.kb-source-docs { background: var(--signal-blue-glow); color: var(--signal-blue); border-color: rgba(132,203,255,0.3); }
.kb-source-code_structure { background: var(--signal-purple-glow); color: var(--signal-purple); border-color: rgba(218,178,255,0.3); }
.kb-source-issue { background: var(--signal-green-glow); color: var(--signal-green); border-color: rgba(142,236,151,0.3); }
.kb-source-pr { background: var(--signal-cyan-glow); color: var(--signal-cyan); border-color: rgba(106,216,223,0.3); }
.kb-source-article { background: var(--signal-yellow-glow); color: var(--signal-yellow); border-color: rgba(242,204,96,0.3); }
.kb-source-manual { background: var(--amber-glow); color: var(--amber); border-color: rgba(255,180,84,0.3); }
.kb-source-conversation { background: var(--bg-elev-3); color: var(--text-secondary); border-color: var(--border); }
.kb-source-report { background: var(--signal-red-glow); color: var(--signal-red); border-color: rgba(255,107,107,0.3); }

.chat-input-bar {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--border-faint);
}
.chat-input { flex: 1; }
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

/* ── Export dropdown ── */
.export-dropdown {
  background: var(--bg-elev-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-top);
  min-width: 180px;
  overflow: hidden;
}
.export-dropdown-item {
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  transition: background var(--t-fast);
  white-space: nowrap;
}
.export-dropdown-item:hover {
  background: var(--bg-elev-3);
  color: var(--text-primary);
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
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
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
.msg-edit-row {
  margin-bottom: var(--space-2);
}
.msg-edit-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-1);
  justify-content: flex-end;
}
</style>