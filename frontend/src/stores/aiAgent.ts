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

export const useAIAgentStore = defineStore('aiAgent', () => {
  const messages = ref<ChatMessage[]>([])
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  const loading = ref(false)
  const streaming = ref(false)
  const streamingContent = ref('')
  const error = ref('')

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
      currentSessionId.value = data.session_id
      messages.value = []
      error.value = ''
      await loadSessions()
      return data.session_id
    } catch (e: any) {
      useAppStore().showToast('创建会话失败', e.message, 'error')
      return null
    }
  }

  async function switchSession(sessionId: string) {
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
    if (!content.trim() || streaming.value) return

    // Add user message
    messages.value.push({ role: 'user', content: content.trim() })
    error.value = ''

    // Create session if none
    let sessionId = currentSessionId.value
    if (!sessionId) {
      sessionId = await createSession()
      if (!sessionId) return
    }

    streaming.value = true
    streamingContent.value = ''

    try {
      const token = localStorage.getItem('vllm_auth_token') || ''
      const res = await fetch('/api/ai-agent/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          messages: [{ role: 'user', content: content.trim() }],
          session_id: sessionId,
          tools: tools || ['github', 'knowledge', 'code'],
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

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6))
              if (event.type === 'token') {
                streamingContent.value += event.data
              } else if (event.type === 'tool_call') {
                // Tool call - can display in UI if needed
              } else if (event.type === 'done') {
                // Done
              }
            } catch {}
          }
        }
      }
    } catch (e: any) {
      error.value = e.message
      useAppStore().showToast('发送失败', e.message, 'error')
    } finally {
      streaming.value = false
      if (streamingContent.value) {
        messages.value.push({ role: 'assistant', content: streamingContent.value })
      }
      streamingContent.value = ''
      await loadSessions()
    }
  }

  return {
    messages, sessions, currentSessionId, loading, streaming, streamingContent, error,
    loadSessions, createSession, switchSession, deleteSession, sendMessage,
  }
})