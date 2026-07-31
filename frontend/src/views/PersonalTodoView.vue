<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useTodoStore } from '@/stores/todo'
import { useUsersStore } from '@/stores/users'
import { useReposStore } from '@/stores/repos'
import { useRouter } from 'vue-router'
import { statusLabel, sourceLabel, priorityClass, statusClass } from '@/utils/helpers'
import type { TodoTask } from '@/utils/types'
import { renderMarkdown } from '@/composables/useMarkdown'
import Icon from '@/components/common/Icon.vue'

const todoStore = useTodoStore()
const usersStore = useUsersStore()
const reposStore = useReposStore()
const router = useRouter()

const insightSourceOptions = computed(() => {
  const repoOptions = reposStore.repos.map(r => ({
    value: r.repo,
    label: r.repo + ' 社区',
  }))
  return [
    ...repoOptions,
    { value: 'academic', label: '学术动态' },
    { value: 'news', label: '新闻动态' },
  ]
})

// Edit form ref input
const editRefInput = ref('')
const resolveRefLoading = ref(false)

// Drag-and-drop state
const draggedTaskId = ref<number | null>(null)
const dragOverPriority = ref<string | null>(null)

function onCardDragStart(e: DragEvent, task: any) {
  draggedTaskId.value = task.id
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(task.id))
  }
  // 拖拽时卡片半透明
  const el = e.target as HTMLElement
  const card = el.closest('.kanban-card') as HTMLElement | null
  if (card) {
    setTimeout(() => card.classList.add('dragging'), 0)
  }
}

function onCardDragEnd(e: DragEvent) {
  const el = e.target as HTMLElement
  const card = el.closest('.kanban-card') as HTMLElement | null
  if (card) {
    card.classList.remove('dragging')
  }
  draggedTaskId.value = null
  dragOverPriority.value = null
}

function onColumnDragOver(e: DragEvent) {
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'move'
  }
  e.preventDefault()
}

function onColumnDragEnter(e: DragEvent, priority: string) {
  // Accept enter from child elements too (dragenter bubbles)
  e.preventDefault()
  dragOverPriority.value = priority
}

function onColumnDragLeave(e: DragEvent) {
  // Only clear when the pointer truly leaves the column (relatedTarget is outside)
  const related = e.relatedTarget as Node | null
  if (related && e.currentTarget && (e.currentTarget as HTMLElement).contains(related)) {
    return
  }
  dragOverPriority.value = null
}

function onColumnDrop(e: DragEvent, targetPriority: TodoTask['priority']) {
  e.preventDefault()
  const taskId = draggedTaskId.value
  draggedTaskId.value = null
  dragOverPriority.value = null

  if (taskId === null) return

  // 找到被拖拽的任务
  const task = todoStore.tasks.find(t => t.id === taskId)
  if (!task || task.priority === targetPriority) return

  todoStore.moveTaskPriority(taskId, targetPriority)
}

async function addEditRef() {
  if (!editRefInput.value.trim()) return
  resolveRefLoading.value = true
  try {
    const r = await todoStore.resolveRef(editRefInput.value)
    if (r) {
      if (!todoStore.editTaskForm.related_refs) {
        todoStore.editTaskForm.related_refs = []
      }
      todoStore.addRef(todoStore.editTaskForm.related_refs, r)
      editRefInput.value = ''
    }
  } finally {
    resolveRefLoading.value = false
  }
}

// Subtask edit ref input
const editSubtaskRefInput = ref('')
const subtaskRefLoading = ref(false)

async function addEditSubtaskRef() {
  if (!editSubtaskRefInput.value.trim()) return
  subtaskRefLoading.value = true
  try {
    const r = await todoStore.resolveRef(editSubtaskRefInput.value)
    if (r) {
      if (!todoStore.editSubtaskForm.related_refs) {
        todoStore.editSubtaskForm.related_refs = []
      }
      todoStore.addRef(todoStore.editSubtaskForm.related_refs, r)
      editSubtaskRefInput.value = ''
    }
  } finally {
    subtaskRefLoading.value = false
  }
}

onMounted(() => {
  todoStore.loadTasks()
})

const statusFilters = ['todo', 'in_progress', 'done', 'all']
const priorityFilters = ['all', 'P0', 'P1', 'P2', 'P3']

const sources = [
  { value: 'self', label: '主动规划' },
  { value: 'team', label: '产品反馈' },
  { value: 'community', label: '社区反馈' },
]

function openUrl(url: string) {
  window.open(url, '_blank')
}

async function openInsight(task: any) {
  const reportId = await todoStore.openTaskInsight(task)
  if (reportId) {
    router.push({ name: 'intelligence' })
  }
}

async function generateInsight(task: any) {
  await todoStore.openInsightSourceModal(task)
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">任务面板</h2>
      <div class="view-actions">
        <button class="btn btn-primary btn-sm" @click="todoStore.showAddModal = true">+ 新建任务</button>
      </div>
    </div>

    <!-- Stats overview -->
    <div class="stat-grid" style="margin-bottom:var(--space-5)">
      <div class="stat-card" style="--accent-color: var(--signal-blue)">
        <div class="stat-label">待处理</div>
        <div class="stat-value">{{ todoStore.todoCount }}</div>
      </div>
      <div class="stat-card" style="--accent-color: var(--amber)">
        <div class="stat-label">进行中</div>
        <div class="stat-value">{{ todoStore.inProgressCount }}</div>
      </div>
      <div class="stat-card" style="--accent-color: var(--signal-green)">
        <div class="stat-label">已完成</div>
        <div class="stat-value">{{ todoStore.doneCount }}</div>
      </div>
    </div>

    <div class="todo-filters">
      <div class="tab-bar">
        <button v-for="s in statusFilters" :key="s" class="tab"
                :class="{ active: todoStore.filterStatus === s }"
                @click="todoStore.switchStatusFilter(s)">
          {{ s === 'all' ? '全部' : statusLabel(s) }}
        </button>
      </div>
      <select class="select select-sm" v-model="todoStore.filterPriority"
              @change="todoStore.switchPriorityFilter(todoStore.filterPriority)">
        <option value="all">全部优先级</option>
        <option v-for="p in priorityFilters.slice(1)" :key="p" :value="p">{{ p }}</option>
      </select>
    </div>

    <!-- Kanban view -->
    <template v-if="todoStore.useKanban">
      <div class="kanban-board">
        <div v-for="(items, priority) in todoStore.tasksByPriority" :key="priority" class="kanban-column"
             :class="{ 'drag-over': dragOverPriority === priority }"
              @dragover="onColumnDragOver"
              @dragenter="onColumnDragEnter($event, priority)"
              @dragleave="onColumnDragLeave($event)"
              @drop="onColumnDrop($event, priority as TodoTask['priority'])">
          <h3 class="kanban-column-title" :class="priorityClass(priority)">{{ priority }}</h3>
          <div v-for="task in items" :key="task.id" class="kanban-card"
               draggable="true"
               :class="{ 'overdue': task.due_date && task.due_date < todoStore.todayISO && task.status !== 'done' }"
               @dragstart="onCardDragStart($event, task)"
               @dragend="onCardDragEnd"
               @click="todoStore.openTask(task)">
            <div class="kanban-card-header">
              <span class="badge" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
              <span class="kanban-card-source">{{ sourceLabel(task.source) }}</span>
            </div>
            <h4 class="kanban-card-title">{{ task.title }}</h4>
            <div class="kanban-card-footer">
              <span v-if="task.assignee_id" class="badge badge-assignee">{{ usersStore.userName(task.assignee_id) }}</span>
              <span v-if="task.area" class="kanban-tag">{{ task.area }}</span>
              <span v-if="task.due_date" class="kanban-tag kanban-tag-icon" :class="{ 'overdue': task.due_date < todoStore.todayISO && task.status !== 'done' }"><Icon name="calendar" :size="11" /> {{ task.due_date }}</span>
              <span v-if="task.subtask_count && task.subtask_count > 0" class="kanban-tag kanban-tag-icon">{{ task.subtask_done_count || 0 }}/{{ task.subtask_count }} <Icon name="checklist" :size="11" /></span>
              <span v-for="(ref, idx) in (task.related_refs || []).slice(0, 2)" :key="idx" class="ref-badge ref-badge-sm" :title="ref.title || (ref.repo + '#' + ref.number)">
                <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                <span>{{ ref.repo }}#{{ ref.number }}</span>
                <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
              </span>
              <span v-if="(task.related_refs || []).length > 2" class="kanban-tag">+{{ (task.related_refs || []).length - 2 }}</span>
              <span v-if="task.has_dedup_check && task.dedup_check_result?.matches?.length > 0" class="kanban-tag is-warning">{{ task.dedup_check_result.matches.length }} 重复</span>
              <span v-if="task.has_dedup_check && (!task.dedup_check_result || !task.dedup_check_result.matches || task.dedup_check_result.matches.length === 0)" class="kanban-tag is-success kanban-tag-icon"><Icon name="check" :size="11" /> 无重复</span>
              <span v-if="task.has_ai_insight" class="kanban-tag is-info kanban-tag-icon"><Icon name="search" :size="11" /> 有洞察</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- List view -->
    <template v-else>
      <div class="task-list">
        <div v-for="task in todoStore.tasks" :key="task.id" class="task-item" :class="{ 'overdue': task.due_date && task.due_date < todoStore.todayISO && task.status !== 'done' }" @click="todoStore.openTask(task)">
          <div class="task-check">
            <input type="checkbox" :checked="task.status === 'done'"
                   @click.stop @change="todoStore.toggleTaskDone(task)" />
          </div>
          <div class="task-body">
            <h4 class="task-title" :class="{ 'task-done': task.status === 'done' }">{{ task.title }}</h4>
            <div class="task-meta">
              <span class="badge" :class="priorityClass(task.priority)">{{ task.priority }}</span>
              <span class="badge" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
              <span>{{ sourceLabel(task.source) }}</span>
              <span v-if="task.assignee_id" class="badge badge-assignee">{{ usersStore.userName(task.assignee_id) }}</span>
              <span v-if="task.area" class="kanban-tag">{{ task.area }}</span>
              <span v-if="task.due_date" class="kanban-tag kanban-tag-icon" :class="{ 'overdue': task.due_date < todoStore.todayISO && task.status !== 'done' }"><Icon name="calendar" :size="11" /> {{ task.due_date }}</span>
              <span v-if="task.subtask_count && task.subtask_count > 0" class="kanban-tag kanban-tag-icon">{{ task.subtask_done_count || 0 }}/{{ task.subtask_count }} <Icon name="checklist" :size="11" /></span>
              <span v-for="(ref, idx) in (task.related_refs || []).slice(0, 3)" :key="idx" class="ref-badge" :title="ref.title || (ref.repo + '#' + ref.number)">
                <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                <span>{{ ref.repo }}#{{ ref.number }}</span>
                <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
              </span>
              <span v-if="(task.related_refs || []).length > 3" class="kanban-tag">+{{ (task.related_refs || []).length - 3 }}</span>
              <span v-if="task.has_dedup_check && task.dedup_check_result?.matches?.length > 0" class="kanban-tag is-warning">{{ task.dedup_check_result.matches.length }} 重复</span>
              <span v-if="task.has_dedup_check && (!task.dedup_check_result || !task.dedup_check_result.matches || task.dedup_check_result.matches.length === 0)" class="kanban-tag is-success kanban-tag-icon"><Icon name="check" :size="11" /> 无重复</span>
              <span v-if="task.has_ai_insight" class="kanban-tag is-info kanban-tag-icon"><Icon name="search" :size="11" /> 有洞察</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Add Task Modal -->
    <Teleport to="body">
      <div v-if="todoStore.showAddModal" class="modal-backdrop" @click="todoStore.showAddModal = false">
        <div class="modal" @click.stop>
          <div class="modal-header">
            <h3>新建任务</h3>
            <button class="modal-close" @click="todoStore.showAddModal = false" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label form-label-required">标题</label>
              <input type="text" class="input input-lg" v-model="todoStore.newTask.title" placeholder="任务标题" />
            </div>
            <div class="form-group">
              <label class="form-label">描述</label>
              <textarea class="textarea" v-model="todoStore.newTask.description" placeholder="描述（可选）" rows="3"></textarea>
            </div>
            <div class="form-row" style="align-items:flex-end;">
              <div class="field">
                <label class="form-label">优先级</label>
                <select class="select" v-model="todoStore.newTask.priority">
                  <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
                </select>
              </div>
              <div class="field">
                <label class="form-label">来源</label>
                <select class="select" v-model="todoStore.newTask.source">
                  <option v-for="s in sources" :key="s.value" :value="s.value">{{ s.label }}</option>
                </select>
              </div>
              <div class="field">
                <label class="form-label">责任人</label>
                <select class="select" v-model="todoStore.newTask.assignee_id">
                  <option :value="null">无</option>
                  <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                </select>
              </div>
            </div>
            <div class="form-row" style="align-items:flex-end;margin-top:var(--space-4);">
              <div class="field">
                <label class="form-label">领域</label>
                <input class="input" type="text" placeholder="如 engine" v-model="todoStore.newTask.area" />
              </div>
              <div class="field">
                <label class="form-label">截止日期</label>
                <input class="input" type="date" v-model="todoStore.newTask.due_date" />
              </div>
            </div>
            <div class="form-group">
              <label class="form-label">关联 PR/Issue</label>
              <div class="ref-input-row">
                <input class="input input-sm" type="text" v-model="todoStore.newTask.refInput"
                       placeholder="如 vllm#123 或纯数字" @keyup.enter="async () => { const r = await todoStore.resolveRef(todoStore.newTask.refInput); if (r) { todoStore.addRef(todoStore.newTask.related_refs, r); todoStore.newTask.refInput = '' } }" />
                <button class="btn btn-sm" @click="async () => { const r = await todoStore.resolveRef(todoStore.newTask.refInput); if (r) { todoStore.addRef(todoStore.newTask.related_refs, r); todoStore.newTask.refInput = '' } }" :disabled="todoStore.resolveRefLoading || !todoStore.newTask.refInput.trim()">
                  {{ todoStore.resolveRefLoading ? '解析中…' : '添加' }}
                </button>
              </div>
              <div v-if="todoStore.newTask.related_refs.length > 0" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:var(--space-1);">
                <span v-for="(ref, idx) in todoStore.newTask.related_refs" :key="idx" class="ref-badge" :title="ref.title">
                  <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                  <span>{{ ref.repo }}#{{ ref.number }}</span>
                  <span class="ref-remove" @click="todoStore.removeRef(todoStore.newTask.related_refs, idx)" style="cursor:pointer;margin-left:3px;opacity:0.6;">&times;</span>
                </span>
              </div>
            </div>
            <div class="form-group">
              <label class="toggle-label">
                <input type="checkbox" v-model="todoStore.newTask.trigger_dedup_check" />
                添加后自动去重检查
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="todoStore.showAddModal = false">取消</button>
            <button class="btn btn-primary" :disabled="todoStore.newTaskLoading"
                    @click="todoStore.createTask()">{{ todoStore.newTaskLoading ? '创建中…' : '创建任务' }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Task Drawer -->
    <Teleport to="body">
      <div v-if="todoStore.selectedTask" class="drawer-backdrop" @click="todoStore.editingTask ? null : todoStore.closeTask()">
        <div class="drawer" @click.stop>
          <div class="drawer-header">
            <!-- View mode: display title -->
            <template v-if="!todoStore.editingTask">
              <div class="drawer-title">
                <div class="pr-id">
                  <span>#{{ todoStore.selectedTask.id }}</span>
                  <span style="margin-left:8px;"><span class="status-badge" :class="statusClass(todoStore.selectedTask.status)" v-text="statusLabel(todoStore.selectedTask.status)"></span></span>
                </div>
                <h2>{{ todoStore.selectedTask.title }}</h2>
              </div>
            </template>
            <!-- Edit mode: compact header -->
            <template v-else>
              <div class="drawer-title">
                <div class="pr-id">
                  <span>#{{ todoStore.selectedTask.id }}</span>
                  <span style="margin-left:8px;font-size:var(--text-sm);color:var(--text-tertiary);">编辑任务</span>
                </div>
              </div>
            </template>
            <button class="drawer-close" @click="todoStore.closeTask()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="drawer-body">
            <!-- ============ VIEW MODE ============ -->
            <template v-if="!todoStore.editingTask">
              <!-- Meta tags -->
              <div class="detail-section item-meta" style="margin-bottom:var(--space-3);">
                <span class="priority-badge" :class="priorityClass(todoStore.selectedTask.priority)">{{ todoStore.selectedTask.priority }}</span>
                <span class="status-badge" :class="statusClass(todoStore.selectedTask.status)">{{ statusLabel(todoStore.selectedTask.status) }}</span>
                <span class="badge badge-source" :class="'source-' + todoStore.selectedTask.source">{{ sourceLabel(todoStore.selectedTask.source) }}</span>
                <span v-if="todoStore.selectedTask.assignee_id" class="badge badge-assignee">{{ usersStore.userName(todoStore.selectedTask.assignee_id) }}</span>
                <span v-if="todoStore.selectedTask.area" class="meta-item">{{ todoStore.selectedTask.area }}</span>
                <span v-if="todoStore.selectedTask.due_date" class="meta-item" :class="{ 'overdue': todoStore.selectedTask.due_date < todoStore.todayISO && todoStore.selectedTask.status !== 'done' }">截止 {{ todoStore.selectedTask.due_date }}</span>
              </div>

              <!-- Action buttons -->
              <div class="detail-action-bar" style="margin-bottom:var(--space-4);">
                <div class="action-bar-secondary">
                  <button class="btn btn-sm" @click="todoStore.startEditTask()">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    编辑
                  </button>
                  <button class="btn btn-sm" @click="todoStore.runDedupCheck(todoStore.selectedTask!)" :disabled="todoStore.dedupLoading">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
                    {{ todoStore.dedupLoading ? '检查中…' : '去重检查' }}
                  </button>
                  <button class="btn btn-sm" @click="generateInsight(todoStore.selectedTask!)" :disabled="todoStore.insightGenLoading">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/></svg>
                    {{ todoStore.insightGenLoading ? '生成中…' : '生成洞察' }}
                  </button>
                  <button class="btn btn-sm" @click="todoStore.showSubtaskForm = !todoStore.showSubtaskForm" :disabled="!todoStore.selectedTask">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    {{ todoStore.showSubtaskForm ? '收起' : '添加子任务' }}
                  </button>
                </div>
                <div class="action-bar-primary">
                  <button class="btn btn-sm btn-success" :class="{ 'is-done': todoStore.selectedTask.status === 'done' }" @click="todoStore.toggleTaskDone(todoStore.selectedTask!)">
                    <svg v-if="todoStore.selectedTask.status !== 'done'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                    <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                    {{ todoStore.selectedTask.status === 'done' ? '恢复未完成' : '标记完成' }}
                  </button>
                  <span class="action-bar-divider"></span>
                  <button class="btn btn-sm btn-danger" @click="todoStore.deleteTask(todoStore.selectedTask!)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    删除
                  </button>
                </div>
              </div>

              <!-- Description -->
              <div v-if="todoStore.selectedTask.description" class="detail-desc" style="margin-bottom:var(--space-4);">
                <div v-html="renderMarkdown(todoStore.selectedTask.description)"></div>
              </div>

              <!-- Related refs -->
              <div v-if="todoStore.selectedTask.related_refs && todoStore.selectedTask.related_refs.length > 0" style="margin-bottom:var(--space-4);">
                <label class="form-label">关联引用</label>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                  <span v-for="(ref, idx) in todoStore.selectedTask.related_refs" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)">
                    <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                    <span>{{ ref.repo }}#{{ ref.number }}</span>
                    <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
                  </span>
                </div>
              </div>
            </template>

            <!-- ============ EDIT MODE ============ -->
            <template v-else>
              <!-- Title -->
              <div class="field" style="margin-bottom:var(--space-3);">
                <input type="text" class="input input-lg" v-model="todoStore.editTaskForm.title" placeholder="任务标题" />
              </div>

              <!-- Description -->
              <div class="field" style="margin-bottom:var(--space-3);">
                <label class="field-label-sm">描述</label>
                <textarea class="textarea" rows="24" v-model="todoStore.editTaskForm.description" placeholder="描述（可选，支持 Markdown）"></textarea>
              </div>

              <!-- Meta fields -->
              <div class="form-row" style="margin-bottom:var(--space-3);flex-wrap:wrap;">
                <div class="field" style="flex:1;min-width:100px;margin-top:0;">
                  <label class="field-label-sm">优先级</label>
                  <select class="select" v-model="todoStore.editTaskForm.priority">
                    <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
                  </select>
                </div>
                <div class="field" style="flex:1;min-width:100px;margin-top:0;">
                  <label class="field-label-sm">状态</label>
                  <select class="select" v-model="todoStore.editTaskForm.status">
                    <option value="todo">待处理</option>
                    <option value="in_progress">进行中</option>
                    <option value="done">已完成</option>
                    <option value="cancelled">已取消</option>
                  </select>
                </div>
                <div class="field" style="flex:1;min-width:100px;margin-top:0;">
                  <label class="field-label-sm">来源</label>
                  <select class="select" v-model="todoStore.editTaskForm.source">
                    <option v-for="s in sources" :key="s.value" :value="s.value">{{ s.label }}</option>
                  </select>
                </div>
                <div class="field" style="flex:1;min-width:120px;margin-top:0;">
                  <label class="field-label-sm">责任人</label>
                  <select class="select" v-model.number="todoStore.editTaskForm.assignee_id">
                    <option :value="null">无</option>
                    <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                  </select>
                </div>
                <div class="field" style="flex:0 0 100px;margin-top:0;">
                  <label class="field-label-sm">领域</label>
                  <input class="input" type="text" v-model="todoStore.editTaskForm.area" placeholder="如 engine" />
                </div>
                <div class="field" style="flex:0 0 140px;margin-top:0;">
                  <label class="field-label-sm">截止日期</label>
                  <input class="input" type="date" v-model="todoStore.editTaskForm.due_date" />
                </div>
              </div>

              <!-- Related refs (editable) -->
              <div class="field" style="margin-bottom:var(--space-3);">
                <label class="field-label-sm">关联 PR/Issue</label>
                <div class="ref-input-row" style="margin-bottom:var(--space-2);">
                  <input class="input" type="text" v-model="editRefInput"
                         placeholder="如 vllm#123 或纯数字" @keyup.enter="addEditRef()" />
                  <button class="btn" @click="addEditRef()" :disabled="resolveRefLoading || !editRefInput.trim()">
                    {{ resolveRefLoading ? '解析中…' : '添加' }}
                  </button>
                </div>
                <div v-if="todoStore.editTaskForm.related_refs && todoStore.editTaskForm.related_refs.length > 0" style="display:flex;flex-direction:column;gap:4px;">
                  <span v-for="(ref, idx) in todoStore.editTaskForm.related_refs" :key="idx" class="ref-badge" :title="ref.title" style="display:inline-flex;align-items:center;justify-content:space-between;">
                    <span>
                      <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                      <span>{{ ref.repo }}#{{ ref.number }}</span>
                    </span>
                    <span class="ref-remove" @click="todoStore.editTaskForm.related_refs.splice(idx, 1)" style="margin-left:6px;cursor:pointer;">&times;</span>
                  </span>
                </div>
                <div v-else style="color:var(--text-tertiary);font-size:var(--text-xs);padding:var(--space-3);text-align:center;border:1px dashed var(--border-faint);border-radius:var(--radius-sm);">
                  暂无关联引用，在上方输入 vllm#编号 添加
                </div>
              </div>

              <!-- Save / Cancel -->
              <div class="edit-task-actions">
                <button class="btn" @click="todoStore.cancelEditTask()">取消</button>
                <button class="btn btn-primary" @click="todoStore.saveTask()" :disabled="!todoStore.editTaskForm.title?.trim()">
                  {{ todoStore.taskSaving ? '保存中…' : '保存' }}
                </button>
              </div>
            </template>

            <!-- Dedup result -->
            <div v-if="!todoStore.editingTask && todoStore.dedupResult" style="margin-bottom:var(--space-4);">
              <label class="form-label">去重结果</label>
              <div v-if="todoStore.dedupResult.matches && todoStore.dedupResult.matches.length > 0" class="ai-result">
                <div class="ai-result-body">
                  <p>发现 <strong>{{ todoStore.dedupResult.matches.length }}</strong> 个可能重复的项：</p>
                  <div v-for="m in todoStore.dedupResult.matches" :key="m.id || m.number" class="dedup-item">
                    <a :href="m.url" target="_blank" class="dedup-item-link">{{ m.title }}</a>
                    <span v-if="m.repo" class="badge">{{ m.repo }}#{{ m.number }}</span>
                  </div>
                </div>
              </div>
              <div v-else>
                <span class="badge badge-success">未发现重复</span>
              </div>
            </div>

            <!-- AI Insight -->
            <div v-if="!todoStore.editingTask && (todoStore.selectedTask as any).latest_insight_report_id" style="margin-bottom:var(--space-4);">
              <label class="form-label">AI 洞察</label>
              <button class="btn btn-sm btn-subtle" @click="openInsight(todoStore.selectedTask!)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                查看洞察报告
              </button>
            </div>

            <!-- Subtasks -->
            <div v-if="todoStore.subtasks.length > 0" class="subtask-module">
              <label class="form-label subtask-module-label">子任务 ({{ todoStore.subtaskProgressText }})</label>
              <div class="subtask-list">
                <div v-for="st in todoStore.subtasks" :key="st.id" class="subtask-item">
                  <!-- Individual subtask full edit mode -->
                  <template v-if="todoStore.editingSubtaskId === st.id">
                    <div class="subtask-edit-form" style="flex:1;display:flex;flex-direction:column;gap:var(--space-1);">
                      <input class="input input-sm" type="text" v-model="todoStore.editSubtaskForm.title" placeholder="子任务标题" @keyup.enter="todoStore.saveSubtask()" />
                      <textarea class="textarea textarea-sm" v-model="todoStore.editSubtaskForm.description" placeholder="描述（可选，支持 Markdown）" rows="2"></textarea>
                      <div style="display:flex;gap:var(--space-2);align-items:center;flex-wrap:wrap;">
                        <select class="select select-sm" style="width:80px;" v-model="todoStore.editSubtaskForm.priority">
                          <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
                        </select>
                        <select class="select select-sm" style="flex:1;min-width:80px;" v-model.number="todoStore.editSubtaskForm.assignee_id">
                          <option :value="null">无责任人</option>
                          <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                        </select>
                        <select class="select select-sm" style="width:90px;" v-model="todoStore.editSubtaskForm.status">
                          <option value="todo">待处理</option>
                          <option value="in_progress">进行中</option>
                          <option value="done">已完成</option>
                          <option value="cancelled">已取消</option>
                        </select>
                      </div>
                      <div v-if="todoStore.editingSubtaskId === st.id">
                        <div class="ref-input-row">
                          <input class="input input-sm" type="text" v-model="editSubtaskRefInput"
                                 placeholder="关联 PR/Issue，如 vllm#123" @keyup.enter="addEditSubtaskRef()" />
                          <button class="btn btn-sm" @click="addEditSubtaskRef()" :disabled="subtaskRefLoading || !editSubtaskRefInput.trim()">
                            {{ subtaskRefLoading ? '解析中…' : '添加' }}
                          </button>
                        </div>
                        <div v-if="todoStore.editSubtaskForm.related_refs && todoStore.editSubtaskForm.related_refs.length > 0" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:var(--space-1);">
                          <span v-for="(ref, idx) in todoStore.editSubtaskForm.related_refs" :key="idx" class="ref-badge" :title="ref.title">
                            <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                            <span>{{ ref.repo }}#{{ ref.number }}</span>
                            <span class="ref-remove" @click="todoStore.editSubtaskForm.related_refs.splice(idx, 1)" style="cursor:pointer;margin-left:3px;opacity:0.6;">&times;</span>
                          </span>
                        </div>
                      </div>
                      <div class="subtask-edit-actions">
                        <button class="btn btn-sm btn-ghost" @click="todoStore.cancelEditSubtask()">取消</button>
                        <button class="btn btn-sm btn-primary" @click="todoStore.saveSubtask()">保存</button>
                      </div>
                    </div>
                  </template>
                  <!-- Display mode (view mode) -->
                  <template v-else-if="!todoStore.editingTask">
                    <div class="subtask-checkbox">
                      <input type="checkbox" :checked="st.status === 'done'" @change="todoStore.toggleSubtaskDone(st)" />
                    </div>
                    <div class="subtask-content">
                      <div class="subtask-content-row">
                        <span class="subtask-title" :class="{ 'task-done': st.status === 'done' }">{{ st.title }}</span>
                        <div class="subtask-actions">
                          <button class="card-action-btn" @click.stop="todoStore.startEditSubtask(st)" title="编辑子任务">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                          </button>
                          <button class="card-action-btn is-danger" @click.stop="todoStore.deleteSubtask(st)" title="删除子任务">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                          </button>
                        </div>
                      </div>
                      <div v-if="st.description" class="subtask-desc" :class="{ 'task-done': st.status === 'done' }">
                        <div v-html="renderMarkdown(st.description)"></div>
                      </div>
                      <div class="subtask-meta">
                        <span class="priority-badge" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                        <span class="status-badge" :class="statusClass(st.status)">{{ statusLabel(st.status) }}</span>
                        <span v-if="st.assignee_id" class="badge badge-assignee badge-subtask-assignee">{{ usersStore.userName(st.assignee_id) }}</span>
                        <span v-if="st.related_refs && st.related_refs.length > 0" style="display:inline-flex;gap:3px;flex-wrap:wrap;margin-left:4px;">
                          <span v-for="(ref, idx) in st.related_refs.slice(0, 3)" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)" style="font-size:10px;padding:1px 4px;">
                            <span class="ref-type" :class="'ref-type-' + ref.type" style="font-size:9px;">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                            <span>{{ ref.repo }}#{{ ref.number }}</span>
                            <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state" style="font-size:8px;padding:0 3px;">{{ ref.state }}</span>
                          </span>
                          <span v-if="st.related_refs.length > 3" class="badge badge-subtask" style="font-size:10px;">+{{ st.related_refs.length - 3 }}</span>
                        </span>
                      </div>
                    </div>
                  </template>
                  <!-- Subtask inline edit mode (when main task is being edited) -->
                  <template v-else>
                    <div class="subtask-checkbox">
                      <input type="checkbox" :checked="st.status === 'done'" @change="todoStore.toggleSubtaskDone(st)" />
                    </div>
                    <div class="subtask-content">
                      <div class="subtask-content-row">
                        <span class="subtask-title" :class="{ 'task-done': st.status === 'done' }">{{ st.title }}</span>
                        <div class="subtask-actions">
                          <button class="card-action-btn" @click.stop="todoStore.startEditSubtask(st)" title="编辑子任务">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                          </button>
                          <button class="card-action-btn is-danger" @click.stop="todoStore.deleteSubtask(st)" title="删除子任务">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                          </button>
                        </div>
                      </div>
                      <div v-if="st.description" class="subtask-desc" :class="{ 'task-done': st.status === 'done' }">
                        <div v-html="renderMarkdown(st.description)"></div>
                      </div>
                      <div class="subtask-meta">
                        <span class="priority-badge" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                        <span class="status-badge" :class="statusClass(st.status)">{{ statusLabel(st.status) }}</span>
                        <span v-if="st.assignee_id" class="badge badge-assignee badge-subtask-assignee">{{ usersStore.userName(st.assignee_id) }}</span>
                        <span v-if="st.related_refs && st.related_refs.length > 0" style="display:inline-flex;gap:3px;flex-wrap:wrap;margin-left:4px;">
                          <span v-for="(ref, idx) in st.related_refs.slice(0, 3)" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)" style="font-size:10px;padding:1px 4px;">
                            <span class="ref-type" :class="'ref-type-' + ref.type" style="font-size:9px;">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                            <span>{{ ref.repo }}#{{ ref.number }}</span>
                            <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state" style="font-size:8px;padding:0 3px;">{{ ref.state }}</span>
                          </span>
                          <span v-if="st.related_refs.length > 3" class="badge badge-subtask" style="font-size:10px;">+{{ st.related_refs.length - 3 }}</span>
                        </span>
                      </div>
                    </div>
                  </template>
                </div>
              </div>
            </div>

            <!-- Add Subtask Form -->
            <div v-if="todoStore.showSubtaskForm" style="margin-bottom:var(--space-4);padding:var(--space-3);background:var(--surface-faint);border-radius:var(--radius-md);">
              <label class="form-label">新建子任务</label>
              <div class="form-group" style="margin-bottom:var(--space-2);">
                <input class="input input-sm" type="text" v-model="todoStore.newSubtask.title" placeholder="子任务标题" @keyup.enter="todoStore.createSubtask()" />
              </div>
              <div class="form-group" style="margin-bottom:var(--space-2);">
                <textarea class="textarea textarea-sm" v-model="todoStore.newSubtask.description" placeholder="描述（可选，支持 Markdown）" rows="2"></textarea>
              </div>
              <div class="form-row" style="gap:var(--space-2);">
                <div class="field" style="flex:1;margin-top:0;">
                  <select class="select select-sm" v-model="todoStore.newSubtask.priority">
                    <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
                  </select>
                </div>
                <div class="field" style="flex:1;margin-top:0;">
                  <select class="select select-sm" v-model="todoStore.newSubtask.assignee_id">
                    <option :value="null">无责任人</option>
                    <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                  </select>
                </div>
              </div>
              <div class="form-group" style="margin-top:var(--space-2);">
                <div class="ref-input-row">
                  <input class="input input-sm" type="text" v-model="todoStore.newSubtask.refInput"
                         placeholder="关联 PR/Issue，如 vllm#123" @keyup.enter="async () => { const r = await todoStore.resolveRef(todoStore.newSubtask.refInput); if (r) { todoStore.addRef(todoStore.newSubtask.related_refs, r); todoStore.newSubtask.refInput = '' } }" />
                  <button class="btn btn-sm" @click="async () => { const r = await todoStore.resolveRef(todoStore.newSubtask.refInput); if (r) { todoStore.addRef(todoStore.newSubtask.related_refs, r); todoStore.newSubtask.refInput = '' } }" :disabled="todoStore.resolveRefLoading || !todoStore.newSubtask.refInput.trim()">
                    {{ todoStore.resolveRefLoading ? '解析中…' : '添加' }}
                  </button>
                </div>
                <div v-if="todoStore.newSubtask.related_refs.length > 0" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:var(--space-1);">
                  <span v-for="(ref, idx) in todoStore.newSubtask.related_refs" :key="idx" class="ref-badge" :title="ref.title">
                    <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                    <span>{{ ref.repo }}#{{ ref.number }}</span>
                    <span class="ref-remove" @click="todoStore.newSubtask.related_refs.splice(idx, 1)" style="cursor:pointer;margin-left:3px;opacity:0.6;">&times;</span>
                  </span>
                </div>
              </div>
              <div style="display:flex;gap:var(--space-2);margin-top:var(--space-2);">
                <button class="btn btn-sm btn-primary" @click="todoStore.createSubtask()" :disabled="!todoStore.newSubtask.title.trim()">添加</button>
                <button class="btn btn-sm" @click="todoStore.showSubtaskForm = false; todoStore.newSubtask = { title: '', description: '', priority: 'P2', assignee_id: null, related_refs: [], refInput: '' }">取消</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>

  <!-- Insight Source Selection Modal -->
  <Teleport to="body">
    <div v-if="todoStore.showInsightSourceModal" class="modal-backdrop" @click="todoStore.showInsightSourceModal = false">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3>选择数据来源</h3>
          <button class="modal-close" @click="todoStore.showInsightSourceModal = false" title="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">生成洞察报告的数据来源</label>
            <div class="checkbox-group">
              <label v-for="opt in insightSourceOptions" :key="opt.value" class="checkbox-label">
                <input type="checkbox" :checked="todoStore.isInsightSourceSelected(opt.value)"
                       @change="todoStore.toggleInsightSource(opt.value)" />
                {{ opt.label }}
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="todoStore.showInsightSourceModal = false">取消</button>
          <button class="btn btn-primary" :disabled="todoStore.insightSourceSaving"
                  @click="todoStore.confirmGenerateInsight()">
            {{ todoStore.insightSourceSaving ? '生成中…' : '确认生成' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.subtask-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-faint);
  margin-top: var(--space-1);
}
.edit-task-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-faint);
  margin-bottom: var(--space-4);
}
</style>