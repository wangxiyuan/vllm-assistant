<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

const icons = {
  success: 'M9 12l2 2 4-4',
  error: 'M18 6L6 18M6 6l12 12',
  info: 'M12 8v4M12 16h.01',
  warning: 'M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z',
  undo: 'M3 7v6h6M3 13a9 9 0 1 0 3-7.7L3 8',
}

function iconPath(type: string): string {
  return (icons as any)[type] || icons.info
}

function dismiss(id: number) {
  appStore.toasts = appStore.toasts.filter(t => t.id !== id)
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div v-for="toast in appStore.toasts" :key="toast.id"
             class="toast" :class="'toast-' + toast.type">
          <svg class="toast-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path :d="iconPath(toast.type)" />
          </svg>
          <div class="toast-body">
            <span class="toast-title">{{ toast.title }}</span>
            <span v-if="toast.msg" class="toast-msg">{{ toast.msg }}</span>
          </div>
          <button v-if="toast.undo" class="toast-undo" @click="appStore.executeUndo(toast.id)">撤销</button>
          <button class="toast-close" @click="dismiss(toast.id)" title="关闭">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
          <div class="toast-progress" :class="'toast-progress-' + toast.type"></div>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  bottom: var(--space-6);
  right: var(--space-6);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 360px;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-4);
  background: var(--bg-elev-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  position: relative;
  overflow: hidden;
}

/* Type accent via icon color */
.toast-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  padding: 1px;
}
.toast-success .toast-icon { color: var(--signal-green); background: var(--signal-green-glow); }
.toast-error .toast-icon { color: var(--signal-red); background: var(--signal-red-glow); }
.toast-info .toast-icon { color: var(--signal-blue); background: var(--signal-blue-glow); }
.toast-warning .toast-icon { color: var(--signal-yellow); background: var(--signal-yellow-glow); }
.toast-undo .toast-icon { color: var(--amber); background: var(--amber-glow-soft); }

.toast-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.toast-title {
  font-weight: 600;
  font-size: var(--text-sm);
  line-height: 1.3;
}
.toast-msg {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.4;
  font-family: var(--font-mono);
}

.toast-undo {
  flex-shrink: 0;
  background: transparent;
  border: 1px solid var(--amber-dim);
  color: var(--amber);
  border-radius: var(--radius-sm);
  padding: 3px var(--space-3);
  font-size: var(--text-xs);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--t-fast);
}
.toast-undo:hover {
  background: var(--amber-glow-soft);
  border-color: var(--amber);
}

.toast-close {
  flex-shrink: 0;
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-xs);
  transition: all var(--t-fast);
}
.toast-close:hover {
  color: var(--text-primary);
  background: var(--bg-elev-3);
}

/* Bottom progress bar */
.toast-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  opacity: 0.5;
}
.toast-progress-success { background: var(--signal-green); }
.toast-progress-error { background: var(--signal-red); }
.toast-progress-info { background: var(--signal-blue); }
.toast-progress-warning { background: var(--signal-yellow); }
.toast-progress-undo { background: var(--amber); }

/* Transition */
.toast-enter-active {
  transition: all 0.35s var(--ease-out);
}
.toast-leave-active {
  transition: all 0.25s var(--ease-out);
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(40px) scale(0.95);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(40px) scale(0.95);
}
.toast-move {
  transition: transform 0.3s var(--ease-out);
}
</style>
