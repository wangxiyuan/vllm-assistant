<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ChatPanel from './ChatPanel.vue'
import ChatIntentForm from './ChatIntentForm.vue'
import { useChatDrawerStore } from '@/stores/aiAgent'

// 可复用的 AI 助手抽屉：从各业务页的「AI 帮我建」入口打开。
// 带 intent 时先展示结构化表单（用户填字段，不接触提示词模板），
// 提交后拼好的提示词直接发送；也可「直接问 AI」跳过表单走自由对话。
// 使用独立的 chatDrawer store，会话上下文与 /ai-agent 页隔离。
const props = defineProps<{
  open: boolean
  intent?: string
}>()
const emit = defineEmits<{ (e: 'close'): void }>()

const drawerStore = useChatDrawerStore()
const panelRef = ref<InstanceType<typeof ChatPanel> | null>(null)
const showForm = ref(false)

watch(() => props.open, (val) => {
  if (val) {
    showForm.value = !!props.intent
    document.addEventListener('keydown', onKeydown)
  } else {
    document.removeEventListener('keydown', onKeydown)
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

function onFormSend(prompt: string) {
  showForm.value = false
  nextTick(() => {
    panelRef.value?.sendText(prompt)
    panelRef.value?.focusInput()
  })
}

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="chat-drawer">
      <div v-if="open" class="chat-drawer-backdrop" @click="emit('close')">
        <div class="chat-drawer" @click.stop>
          <div class="chat-drawer-header">
            <span class="chat-drawer-title">AI 助手</span>
            <button class="chat-drawer-close" @click="emit('close')" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="chat-drawer-body">
            <ChatIntentForm v-if="showForm && intent" :intent="intent"
                            @send="onFormSend" @dismiss="showForm = false" />
            <ChatPanel ref="panelRef" :store="drawerStore" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.chat-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: var(--z-top, 1000);
  display: flex;
  justify-content: flex-end;
}
.chat-drawer {
  width: min(600px, 100vw);
  height: 100%;
  background: var(--bg-elev-1, #1a1a1a);
  border-left: 1px solid var(--border, rgba(255,255,255,0.1));
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.35);
}
.chat-drawer-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--border-faint);
  flex-shrink: 0;
}
.chat-drawer-title {
  font-size: var(--text-base, 15px);
  font-weight: 600;
  color: var(--text-primary);
}
.chat-drawer-close {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: color var(--t-fast), background var(--t-fast);
}
.chat-drawer-close:hover {
  color: var(--text-primary);
  background: var(--bg-elev-2);
}
.chat-drawer-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* ChatPanel 默认为页面布局设计（sticky + 100vh 偏移），抽屉内重置为满高 */
.chat-drawer-body :deep(.agent-chat) {
  height: 100%;
  position: static;
  align-self: stretch;
}

/* 滑入/滑出过渡 */
.chat-drawer-enter-active,
.chat-drawer-leave-active {
  transition: opacity 0.18s ease;
}
.chat-drawer-enter-active .chat-drawer,
.chat-drawer-leave-active .chat-drawer {
  transition: transform 0.22s ease;
}
.chat-drawer-enter-from,
.chat-drawer-leave-to {
  opacity: 0;
}
.chat-drawer-enter-from .chat-drawer,
.chat-drawer-leave-to .chat-drawer {
  transform: translateX(40px);
}
</style>
