import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface Session {
  id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface KnowledgeStats {
  total: number
  stale: number
  by_type: Record<string, number>
}

export interface KnowledgeEntry {
  id: number
  content: string
  source_type: string
  source_ref: string
  tags: string[]
  updated_at: string
  created_at: string
}

export interface KnowledgeListResult {
  results: KnowledgeEntry[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

// Agent 过程步骤（thinking / 工具调用 / 工具结果），不持久化
export interface AgentStep {
  type: 'thinking' | 'tool_call' | 'tool_result'
  thinking?: string
  tool?: { name: string; args?: any; result?: any }
}

// Human-readable labels for knowledge source types
export const KNOWLEDGE_TYPE_LABELS: Record<string, string> = {
  docs: '文档',
  code_structure: '代码结构',
  issue: 'Issue',
  pr: 'PR',
  article: '文章',
  report: '洞察报告',
  manual: '手动添加',
  conversation: '对话',
}

export const KNOWLEDGE_TYPE_ORDER = [
  'docs', 'code_structure', 'issue', 'pr', 'article', 'report', 'manual', 'conversation',
]

export const useAIAgentStore = defineStore('aiAgent', () => {
  const messages = ref<ChatMessage[]>([])
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  const loading = ref(false)
  const streaming = ref(false)
  // 当前正在生成的是哪个 session；可能和 currentSessionId 不同
  // （用户切到别的 session 后，原 session 的生成还在背景跑）
  const activeStreamingSessionId = ref<string | null>(null)
  // 用户主动点击「停止」时置 true，区分「超时失败」与「主动取消」
  const userStopped = ref(false)
  // 拆分：过程步骤 vs 最终回答文本
  const streamingSteps = ref<AgentStep[]>([])
  const streamingFinal = ref('')
  const error = ref('')

  // 模块级 AbortController：sendMessage 写、stopGenerating 读 + abort
  let abortController: AbortController | null = null

  function stopGenerating() {
    if (!streaming.value) return
    userStopped.value = true
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  // Knowledge base state
  const kbStats = ref<KnowledgeStats | null>(null)
  const kbLoading = ref(false)
  const kbSearchQuery = ref('')
  const kbSelectedType = ref<string | null>(null)
  const kbEntries = ref<KnowledgeEntry[]>([])
  const kbTotal = ref(0)
  const kbOffset = ref(0)
  const kbLimit = 50
  const kbHasMore = ref(false)

  async function loadSessions() {
    try {
      const data: any = await api('/api/ai-agent/sessions')
      sessions.value = data.sessions || []
    } catch (e: any) {
      useAppStore().showToast('加载会话失败', e.message, 'error')
    }
  }

  async function createSession() {
    try {
      const data: any = await api('/api/ai-agent/sessions', { method: 'POST' })
      currentSessionId.value = data.id || data.session_id
      messages.value = []
      error.value = ''
      await loadSessions()
      return currentSessionId.value
    } catch (e: any) {
      useAppStore().showToast('创建会话失败', e.message, 'error')
      return null
    }
  }

  async function switchSession(sessionId: string) {
    // 注意：不要在这里 stopGenerating 或清 streaming 状态
    // AI agent 在背景继续跑，只是不在错的 session 里显示输出
    currentSessionId.value = sessionId
    messages.value = []
    error.value = ''
    try {
      const data: any = await api(`/api/ai-agent/sessions/${sessionId}/messages`)
      messages.value = (data.messages || []).map((m: any) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }))
    } catch (e: any) {
      useAppStore().showToast('加载消息失败', e.message, 'error')
    }
  }

  async function deleteSession(sessionId: string) {
    const appStore = useAppStore()
    const confirmed = await appStore.showConfirm({
      title: '删除会话',
      message: '确定删除这个会话？此操作不可撤销。',
      confirmText: '删除',
      danger: true,
    })
    if (!confirmed) return
    // 删的是当前正在流式生成的会话 → 立刻 abort，丢掉过程状态
    if (currentSessionId.value === sessionId && streaming.value) {
      stopGenerating()
    }
    try {
      await api(`/api/ai-agent/sessions/${sessionId}`, { method: 'DELETE' })
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = null
        messages.value = []
      }
      await loadSessions()
      useAppStore().showToast('会话已删除', '', 'info')
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  async function sendMessage(content: string, tools?: string[]) {
    if (!content.trim()) return
    messages.value.push({ role: 'user', content: content.trim() })
    await _doStream(messages.value)
  }

  async function retriggerFrom(userMsgIndex: number) {
    if (userMsgIndex < 0 || userMsgIndex >= messages.value.length) return
    if (messages.value[userMsgIndex].role !== 'user') return
    messages.value = messages.value.slice(0, userMsgIndex + 1)
    await _doStream(messages.value)
  }

  function editUserMessage(msgIndex: number, newContent: string) {
    if (msgIndex < 0 || msgIndex >= messages.value.length) return
    if (messages.value[msgIndex].role !== 'user') return
    messages.value[msgIndex].content = newContent.trim()
    messages.value = messages.value.slice(0, msgIndex + 1)
    _doStream(messages.value)
  }

  async function _doStream(pendingMessages: ChatMessage[]) {
    // If stuck in streaming state from a previous failed request, reset it
    if (streaming.value) {
      streaming.value = false
      streamingSteps.value = []
      streamingFinal.value = ''
      if (abortController) {
        abortController.abort()
        abortController = null
      }
    }

    error.value = ''

    let sessionId = currentSessionId.value
    if (!sessionId) {
      sessionId = await createSession()
      if (!sessionId) return
    }

    streaming.value = true
    activeStreamingSessionId.value = sessionId
    streamingSteps.value = []
    streamingFinal.value = ''

    const controller = new AbortController()
    abortController = controller
    const IDLE_TIMEOUT_MS = 90_000
    let idleTimer: ReturnType<typeof setTimeout> | null = null
    const armIdleTimer = () => {
      if (idleTimer) clearTimeout(idleTimer)
      idleTimer = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS)
    }
    armIdleTimer()

    try {
      const token = localStorage.getItem('vllm_auth_token') || ''
      const res = await fetch('/api/ai-agent/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        signal: controller.signal,
        body: JSON.stringify({
          messages: pendingMessages.map(m => ({ role: m.role, content: m.content })),
          session_id: sessionId,
          tools: ['github', 'knowledge', 'code'],
          stream: true,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || '请求失败')
      }

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response stream')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        armIdleTimer()
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event: any
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          switch (event.type) {
            case 'thinking': {
              const t = (event.data || '').trim()
              if (!t) break
              streamingSteps.value = streamingSteps.value.filter(
                s => s.type !== 'thinking'
              )
              streamingSteps.value.push({ type: 'thinking', thinking: t })
              break
            }
            case 'tool_call':
              streamingSteps.value.push({
                type: 'tool_call',
                tool: { name: event.data.name, args: event.data.args },
              })
              break
            case 'tool_result': {
              const steps = streamingSteps.value
              for (const s of steps) {
                if (s.type === 'tool_call' && s.tool.result === undefined) {
                  s.tool.result = event.data.result
                  break
                }
              }
              break
            }
            case 'token':
              streamingFinal.value += event.data
              break
            case 'error':
              throw new Error(event.data || 'AI 响应异常')
          }
        }
      }
    } catch (e: any) {
      if (e.name === 'AbortError') {
        if (userStopped.value) {
          error.value = ''
          useAppStore().showToast('已停止生成', '', 'info')
        } else {
          error.value = '请求超时，请稍后重试'
          useAppStore().showToast('发送超时', 'AI 响应超时，请检查网络或 API 配置', 'error')
        }
      } else {
        error.value = e.message
        useAppStore().showToast('发送失败', e.message, 'error')
      }
    } finally {
      if (idleTimer) clearTimeout(idleTimer)
      abortController = null
      activeStreamingSessionId.value = null
      if (currentSessionId.value === sessionId && !error.value) {
        const finalText = streamingFinal.value.trim()
        if (finalText) {
          messages.value.push({ role: 'assistant', content: finalText })
        }
      }
      userStopped.value = false
      streamingFinal.value = ''
      streamingSteps.value = []
      streaming.value = false
      await loadSessions()
    }
  }

  // ======================================================================
  // Knowledge base actions
  // ======================================================================

  async function loadKbStats() {
    kbLoading.value = true
    try {
      const data: any = await api('/api/ai-agent/memories/stats')
      kbStats.value = data as KnowledgeStats
    } catch (e: any) {
      useAppStore().showToast('加载知识库统计失败', e.message, 'error')
    } finally {
      kbLoading.value = false
    }
  }

  async function loadKbEntries(sourceType: string, append: boolean = false) {
    kbLoading.value = true
    kbSelectedType.value = sourceType
    if (!append) {
      kbOffset.value = 0
      kbEntries.value = []
    }
    try {
      const q = kbSearchQuery.value.trim()
      const params = new URLSearchParams({
        list_by_type: sourceType,
        offset: String(kbOffset.value),
        limit: String(kbLimit),
      })
      if (q) params.set('q', q)

      const data: any = await api(`/api/ai-agent/memories?${params}`)
      const result = data as KnowledgeListResult
      if (append) {
        kbEntries.value.push(...result.results)
      } else {
        kbEntries.value = result.results
      }
      kbTotal.value = result.total
      kbOffset.value = result.offset + result.results.length
      kbHasMore.value = result.has_more
    } catch (e: any) {
      useAppStore().showToast('加载知识条目失败', e.message, 'error')
    } finally {
      kbLoading.value = false
    }
  }

  async function loadMoreKbEntries() {
    if (!kbSelectedType.value || !kbHasMore.value || kbLoading.value) return
    await loadKbEntries(kbSelectedType.value, true)
  }

  async function searchKbEntries(sourceType: string) {
    kbOffset.value = 0
    await loadKbEntries(sourceType, false)
  }

  function exportSessionAsMarkdown(): string {
    const msgs = messages.value
    if (!msgs.length) return ''

    let md = `# AI Agent 对话记录\n\n`
    md += `- **日期**: ${new Date().toLocaleString('zh-CN')}\n`
    md += `- **会话ID**: ${currentSessionId.value || '-'}\n`
    md += `- **消息数**: ${msgs.length}\n\n`
    md += `---\n\n`

    for (const msg of msgs) {
      const role = msg.role === 'user' ? 'User' : 'AI'
      md += `### ${role}\n\n${msg.content}\n\n---\n\n`
    }

    return md
  }

  function downloadAsMarkdown(content: string, filename: string) {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    // Delay revoke to ensure the browser has started the download
    setTimeout(() => {
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    }, 1000)
  }

  return {
    messages, sessions, currentSessionId, loading, streaming, activeStreamingSessionId, streamingSteps, streamingFinal, error, userStopped,
    loadSessions, createSession, switchSession, deleteSession, sendMessage, retriggerFrom, editUserMessage, stopGenerating,

    // Knowledge base
    kbStats, kbLoading, kbSearchQuery, kbSelectedType,
    kbEntries, kbTotal, kbOffset, kbLimit, kbHasMore,
    loadKbStats, loadKbEntries, loadMoreKbEntries, searchKbEntries,

    // Export
    exportSessionAsMarkdown, downloadAsMarkdown,
  }
})