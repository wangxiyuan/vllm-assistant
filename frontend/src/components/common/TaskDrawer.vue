<script setup lang="ts">
import { useTodoStore } from '@/stores/todo'
import { useUsersStore } from '@/stores/users'
import { statusLabel, sourceLabel, priorityClass, statusClass } from '@/utils/helpers'

const todoStore = useTodoStore()
const usersStore = useUsersStore()

function openUrl(url: string) {
  window.open(url, '_blank')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="todoStore.selectedTask" class="drawer-backdrop" @click="todoStore.closeTask()">
      <div class="drawer" @click.stop>
        <div class="drawer-header">
          <div class="drawer-title">
            <div class="pr-id">
              <span>#{{ todoStore.selectedTask.id }}</span>
              <span style="margin-left:8px;"><span class="status-badge" :class="statusClass(todoStore.selectedTask.status)" v-text="statusLabel(todoStore.selectedTask.status)"></span></span>
            </div>
            <h2>{{ todoStore.selectedTask.title }}</h2>
          </div>
          <button class="drawer-close" @click="todoStore.closeTask()" title="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="drawer-body">
          <div v-if="todoStore.taskDrawerLoading" class="detail-loading">加载中…</div>
          <template v-else-if="todoStore.selectedTaskDetails">
            <div class="detail-section item-meta" style="margin-bottom:var(--space-4);">
              <span class="priority-badge" :class="priorityClass(todoStore.selectedTaskDetails.priority)">{{ todoStore.selectedTaskDetails.priority }}</span>
              <span class="status-badge" :class="statusClass(todoStore.selectedTaskDetails.status)">{{ statusLabel(todoStore.selectedTaskDetails.status) }}</span>
              <span class="badge badge-source" :class="'source-' + todoStore.selectedTaskDetails.source">{{ sourceLabel(todoStore.selectedTaskDetails.source) }}</span>
              <span v-if="todoStore.selectedTaskDetails.assignee_id" class="badge badge-assignee">{{ usersStore.userName(todoStore.selectedTaskDetails.assignee_id) }}</span>
              <span v-if="todoStore.selectedTaskDetails.area" class="meta-item">{{ todoStore.selectedTaskDetails.area }}</span>
            </div>
            <div v-if="todoStore.selectedTaskDetails.description" class="detail-desc">
              {{ todoStore.selectedTaskDetails.description }}
            </div>
            <div v-if="todoStore.selectedTaskDetails.related_refs && todoStore.selectedTaskDetails.related_refs.length > 0" style="margin-bottom:var(--space-4);">
              <label class="form-label">关联引用</label>
              <div style="display:flex;flex-direction:column;gap:6px;">
                <div v-for="(ref, idx) in todoStore.selectedTaskDetails.related_refs" :key="idx" class="ref-row clickable" @click="openUrl(ref.url)">
                  <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                  <span class="ref-number">#{{ ref.number }}</span>
                  <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
                  <span class="ref-repo">{{ ref.repo }}</span>
                  <span class="ref-title">{{ ref.title || '' }}</span>
                </div>
              </div>
            </div>
            <div v-if="todoStore.subtasks.length > 0" style="margin-bottom:var(--space-4);">
              <label class="form-label">子任务 ({{ todoStore.subtaskProgressText }})</label>
              <div class="subtask-list">
                <div v-for="st in todoStore.subtasks" :key="st.id" class="subtask-item">
                  <label class="subtask-checkbox">
                    <input type="checkbox" :checked="st.status === 'done'" @change="todoStore.toggleSubtaskDone(st)" />
                  </label>
                  <div class="subtask-content">
                    <span class="subtask-title" :class="{ 'task-done': st.status === 'done' }">{{ st.title }}</span>
                    <div class="subtask-meta">
                      <span class="priority-badge" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                      <span v-if="st.related_refs && st.related_refs.length > 0" style="display:inline-flex;gap:3px;flex-wrap:wrap;margin-left:4px;">
                        <span v-for="(ref, idx) in st.related_refs.slice(0, 3)" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)" style="font-size:10px;padding:1px 4px;">
                          <span class="ref-type" :class="'ref-type-' + ref.type" style="font-size:9px;">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                          <span>{{ ref.repo }}#{{ ref.number }}</span>
                        </span>
                        <span v-if="st.related_refs.length > 3" class="badge badge-subtask" style="font-size:10px;">+{{ st.related_refs.length - 3 }}</span>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="detail-loading">加载中…</div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
