<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { useAIAgentStore, KNOWLEDGE_TYPE_LABELS, KNOWLEDGE_TYPE_ORDER } from '@/stores/aiAgent'
import { useAppStore } from '@/stores/app'
import { api } from '@/api/client'
import ChatPanel from '@/components/ai/ChatPanel.vue'

const agentStore = useAIAgentStore()
const appStore = useAppStore()
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
  document.addEventListener('click', handleOutsideClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleOutsideClick)
})

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

// ── Session grouping by date ──

function formatTime(isoStr: string): string {
  const d = new Date(isoStr)
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  // Same day → show time only
  if (d.toDateString() === now.toDateString()) return hhmm
  // Yesterday
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return `昨天 ${hhmm}`
  // This year → show M/D
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}/${d.getDate()} ${hhmm}`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function formatRelativeTime(isoStr: string): string {
  const d = new Date(isoStr)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay === 1) return '昨天'
  if (diffDay < 7) return `${diffDay}天前`
  if (diffDay < 30) return `${Math.floor(diffDay / 7)}周前`
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}/${d.getDate()}`
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function getDateGroupLabel(isoStr: string): string {
  const d = new Date(isoStr)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return '今天'
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return '昨天'
  // This week
  const weekStart = new Date(now)
  weekStart.setDate(weekStart.getDate() - weekStart.getDay())
  if (d >= weekStart) return '本周'
  // This month
  if (d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) return '本月'
  return `${d.getFullYear()}年${d.getMonth() + 1}月`
}

const GROUP_ORDER = ['今天', '昨天', '本周', '本月']

const groupedSessions = computed(() => {
  const groups: Record<string, typeof agentStore.sessions> = {}
  const otherGroups: string[] = []
  for (const s of agentStore.sessions) {
    const label = getDateGroupLabel(s.updated_at)
    if (!groups[label]) {
      groups[label] = []
      if (!GROUP_ORDER.includes(label)) otherGroups.push(label)
    }
    groups[label].push(s)
  }
  // Build ordered list
  const result: { label: string; sessions: typeof agentStore.sessions }[] = []
  for (const key of GROUP_ORDER) {
    if (groups[key]) result.push({ label: key, sessions: groups[key] })
  }
  // Sort other groups (most recent first by the year/month numeric comparison)
  otherGroups.sort().reverse()
  for (const key of otherGroups) {
    result.push({ label: key, sessions: groups[key] })
  }
  return result
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
            <template v-for="group in groupedSessions" :key="group.label">
              <div class="agent-session-date-group">{{ group.label }}</div>
              <div v-for="s in group.sessions" :key="s.id"
                   class="agent-session-item"
                   :class="{ active: s.id === agentStore.currentSessionId }"
                   @click="agentStore.switchSession(s.id)">
                <div class="agent-session-title">{{ s.title }}</div>
                <div class="agent-session-meta">
                  <span>{{ s.message_count }} 条消息</span>
                  <span class="agent-session-time">{{ formatRelativeTime(s.updated_at) }}</span>
                </div>
                <button class="agent-session-delete" @click.stop="agentStore.deleteSession(s.id)" title="删除会话">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </div>
            </template>
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

      <ChatPanel :store="agentStore" />
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
.agent-session-meta { font-size: var(--text-xs); color: var(--text-tertiary); display: flex; gap: var(--space-2); }
.agent-session-time { color: var(--text-quaternary); }
.agent-session-date-group {
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--amber-bright);
  padding: var(--space-3) var(--space-3) var(--space-1);
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border-faint);
  margin-bottom: var(--space-1);
}
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

/* ── Knowledge source badge colors ── */
.kb-source-docs { background: var(--signal-blue-glow); color: var(--signal-blue); border-color: rgba(132,203,255,0.3); }
.kb-source-code_structure { background: var(--signal-purple-glow); color: var(--signal-purple); border-color: rgba(218,178,255,0.3); }
.kb-source-issue { background: var(--signal-green-glow); color: var(--signal-green); border-color: rgba(142,236,151,0.3); }
.kb-source-pr { background: var(--signal-cyan-glow); color: var(--signal-cyan); border-color: rgba(106,216,223,0.3); }
.kb-source-manual { background: var(--amber-glow); color: var(--amber); border-color: rgba(255,180,84,0.3); }
.kb-source-conversation { background: var(--bg-elev-3); color: var(--text-secondary); border-color: var(--border); }
.kb-source-report { background: var(--signal-red-glow); color: var(--signal-red); border-color: rgba(255,107,107,0.3); }
.kb-source-slack { background: var(--signal-cyan-glow); color: var(--signal-cyan); border-color: rgba(106,216,223,0.3); }

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

</style>