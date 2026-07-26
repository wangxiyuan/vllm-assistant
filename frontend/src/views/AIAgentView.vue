<script setup lang="ts">
import { onMounted, ref, nextTick, watchEffect } from 'vue'
import { useAIAgentStore } from '@/stores/aiAgent'
import { useAppStore } from '@/stores/app'

const agentStore = useAIAgentStore()
const appStore = useAppStore()
const inputText = ref('')
const chatContainer = ref<HTMLElement | null>(null)

onMounted(() => {
  agentStore.loadSessions()
})

watchEffect(() => {
  if (agentStore.streamingContent || agentStore.messages.length) {
    nextTick(() => {
      if (chatContainer.value) {
        chatContainer.value.scrollTop = chatContainer.value.scrollHeight
      }
    })
  }
})

async function send() {
  const text = inputText.value.trim()
  if (!text) return
  inputText.value = ''
  await agentStore.sendMessage(text)
}
</script>

<template>
  <div class="view-container ai-agent-view">
    <div class="view-header">
      <h2 class="view-title">AI Agent</h2>
      <div class="view-actions">
        <button class="btn btn-sm" @click="agentStore.createSession()">新对话</button>
      </div>
    </div>

    <div class="ai-agent-layout">
      <!-- Session sidebar -->
      <div class="agent-sessions">
        <h3 class="agent-sessions-title">会话历史</h3>
        <div v-for="s in agentStore.sessions" :key="s.id"
             class="agent-session-item"
             :class="{ active: s.id === agentStore.currentSessionId }"
             @click="agentStore.switchSession(s.id)">
          <div class="agent-session-title">{{ s.title }}</div>
          <div class="agent-session-meta">{{ s.message_count }} 条消息</div>
          <button class="agent-session-delete" @click.stop="agentStore.deleteSession(s.id)" title="删除">&times;</button>
        </div>
        <div v-if="agentStore.sessions.length === 0" class="empty-state" style="padding:var(--space-5)">
          暂无会话
        </div>
      </div>

      <!-- Chat area -->
      <div class="agent-chat">
        <div ref="chatContainer" class="chat-messages">
          <div v-for="(msg, i) in agentStore.messages" :key="i"
               class="chat-message" :class="'msg-' + msg.role">
            <div class="msg-avatar">{{ msg.role === 'user' ? 'U' : 'AI' }}</div>
            <div class="msg-content">{{ msg.content }}</div>
          </div>

          <!-- Streaming message -->
          <div v-if="agentStore.streaming" class="chat-message msg-assistant">
            <div class="msg-avatar">AI</div>
            <div class="msg-content">{{ agentStore.streamingContent }}<span class="cursor-blink">▊</span></div>
          </div>

          <!-- Error -->
          <div v-if="agentStore.error" class="chat-message msg-error">
            <div class="msg-content">{{ agentStore.error }}</div>
          </div>

          <div v-if="agentStore.messages.length === 0 && !agentStore.streaming" class="empty-state" style="padding:var(--space-9);text-align:center;color:var(--text-tertiary);">
            <p>开始与 AI Agent 对话</p>
            <p style="font-size:var(--text-sm);">支持 GitHub 查询、代码分析、知识库检索等</p>
          </div>
        </div>

        <div class="chat-input-bar">
          <input type="text" class="input input-lg chat-input"
                 v-model="inputText"
                 placeholder="输入消息…"
                 @keydown.enter.prevent="send()"
                 :disabled="agentStore.streaming" />
          <button class="btn btn-primary" @click="send()" :disabled="agentStore.streaming || !inputText.trim()">
            {{ agentStore.streaming ? '发送中…' : '发送' }}
          </button>
        </div>
      </div>
    </div>
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
.agent-sessions {
  width: 240px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid var(--border-faint);
  padding-right: var(--space-4);
}
.agent-sessions-title {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--text-tertiary);
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
.agent-session-title { font-size: var(--text-sm); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-session-meta { font-size: var(--text-xs); color: var(--text-tertiary); }
.agent-session-delete {
  position: absolute; top: 4px; right: 4px;
  background: none; border: none; color: var(--text-tertiary);
  cursor: pointer; font-size: 16px; display: none;
}
.agent-session-item:hover .agent-session-delete { display: block; }

.agent-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) 0;
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
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-error .msg-content { color: var(--signal-red); }

.cursor-blink {
  animation: blink 1s step-end infinite;
  color: var(--text-secondary);
}
@keyframes blink {
  50% { opacity: 0; }
}

.chat-input-bar {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--border-faint);
}
.chat-input { flex: 1; }
</style>