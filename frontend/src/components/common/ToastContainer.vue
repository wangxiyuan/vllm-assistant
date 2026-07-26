<script setup lang="ts">
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
</script>

<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div v-for="toast in appStore.toasts" :key="toast.id"
             class="toast" :class="'toast-' + toast.type">
          <div class="toast-content">
            <strong class="toast-title">{{ toast.title }}</strong>
            <span v-if="toast.msg" class="toast-msg">{{ toast.msg }}</span>
          </div>
          <button v-if="toast.undo" class="toast-undo" @click="appStore.executeUndo(toast.id)">撤销</button>
          <button class="toast-close" @click="appStore.toasts = appStore.toasts.filter(t => t.id !== toast.id)">&times;</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed; bottom: var(--space-7); right: var(--space-7);
  z-index: var(--z-toast); display: flex; flex-direction: column; gap: var(--space-3);
  pointer-events: none;
}
.toast {
  pointer-events: auto; display: flex; align-items: center; gap: var(--space-4);
  padding: var(--space-4) var(--space-5); border-radius: var(--radius);
  background: var(--bg-elev-3); border: 1px solid var(--border);
  box-shadow: var(--shadow-lg); min-width: 280px; max-width: 420px;
}
.toast-undo { margin-left: auto; }
.toast-close { margin-left: var(--space-2); }
.toast-enter-active, .toast-leave-active { transition: all 0.3s var(--ease-out); }
.toast-enter-from { opacity: 0; transform: translateX(30px); }
.toast-leave-to { opacity: 0; transform: translateX(30px); }
</style>
