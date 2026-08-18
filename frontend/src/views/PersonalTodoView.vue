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

// Subtask edit ref input
const editSubtaskRefInput = ref('')
const subtaskRefLoading = ref(false)

// Drag-and-drop state
const draggedTaskId = ref<number | null>(null)
const dragOverPriority = ref<string | null>(null)

function onCardDragStart(e: DragEvent, task: any) {
  draggedTaskId.value = task.id
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(task.id))
  }
  const el = e.target as HTMLElement
  const card = el.closest('.kanban-card') as HTMLElement | null
  if (card) {
    setTimeout(() => card.classList.add('dragging'), 0)
  }
}

function onCardDragEnd(e: DragEvent) {
  const el = e.target as HTMLElement
  const card = el.closest('.kanban-card') as HTMLElement | null
  if (card) card.classList.remove('dragging')
  draggedTaskId.value = null
  dragOverPriority.value = null
}

function onColumnDragOver(e: DragEvent) {
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  e.preventDefault()
}

function onColumnDragEnter(e: DragEvent, priority: string) {
  e.preventDefault()
  dragOverPriority.value = priority
}

function onColumnDragLeave(e: DragEvent) {
  const related = e.relatedTarget as Node | null
  if (related && e.currentTarget && (e.currentTarget as HTMLElement).contains(related)) return
  dragOverPriority.value = null
}

function onColumnDrop(e: DragEvent, targetPriority: TodoTask['priority']) {
  e.preventDefault()
  const taskId = draggedTaskId.value
  draggedTaskId.value = null
  dragOverPriority.value = null
  if (taskId === null) return
  const task = todoStore.tasks.find(t => t.id === taskId)
  if (!task || task.priority === targetPriority) return
  todoStore.moveTaskPriority(taskId, targetPriority)
}

// Progress ring progress value 0..100
function progressPercent(task: TodoTask): number {
  if (!task.subtask_count) return 0
  return Math.round(((task.subtask_done_count || 0) / task.subtask_count) * 100)
}

// Subtasks for the currently in-place-expanded task
const expandedSubtasks = computed(() => {
  if (todoStore.expandedTaskId === null) return []
  return todoStore.subtasks
})

function cardProgressColor(p: number): string {
  if (p >= 100) return 'var(--signal-green)'
  if (p > 0) return 'var(--signal-blue)'
  return 'var(--text-tertiary)'
}

async function addEditRef() {
  if (!editRefInput.value.trim()) return
  resolveRefLoading.value = true
  try {
    const r = await todoStore.resolveRef(editRefInput.value)
    if (r) {
      if (!todoStore.editTaskForm.related_refs) todoStore.editTaskForm.related_refs = []
      todoStore.addRef(todoStore.editTaskForm.related_refs, r)
      editRefInput.value = ''
    }
  } finally {
    resolveRefLoading.value = false
  }
}

async function addEditSubtaskRef() {
  if (!editSubtaskRefInput.value.trim()) return
  subtaskRefLoading.value = true
  try {
    const r = await todoStore.resolveRef(editSubtaskRefInput.value)
    if (r) {
      if (!todoStore.editSubtaskForm.related_refs) todoStore.editSubtaskForm.related_refs = []
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
  { value: 'meeting', label: '会议' },
]

function openUrl(url: string) {
  window.open(url, '_blank')
}

async function openInsight(task: any) {
  const reportId = await todoStore.openTaskInsight(task)
  if (reportId) router.push({ name: 'intelligence' })
}

async function generateInsight(task: any) {
  await todoStore.openInsightSourceModal(task)
}

// Expanded subtask click guard: stop propagation so card click (open detail) isn't triggered
function onSubtaskClick(e: Event) {
  e.stopPropagation()
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
      <div class="tab-bar" style="margin-left:auto;">
        <button class="tab tab-sm" :class="{ active: todoStore.useKanban }" @click="todoStore.useKanban = true">看板</button>
        <button class="tab tab-sm" :class="{ active: !todoStore.useKanban }" @click="todoStore.useKanban = false">列表</button>
      </div>
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
          <h3 class="kanban-column-title" :class="priorityClass(priority)">
            {{ priority }}
            <span class="kanban-column-count">{{ items.length }}</span>
          </h3>
          <div class="kanban-column-body">
            <div v-for="task in items" :key="task.id" class="kanban-card"
                 draggable="true"
                 :class="{ 'overdue': task.due_date && task.due_date < todoStore.todayISO && task.status !== 'done',
                           'expanded': todoStore.expandedTaskId === task.id }"
                 @dragstart="onCardDragStart($event, task)"
                 @dragend="onCardDragEnd"
                 @click.stop="todoStore.openTaskDetail(task)">
              <div class="kanban-card-header">
                <span class="badge" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
                <span class="kanban-card-source">{{ sourceLabel(task.source) }}</span>
                <button v-if="task.subtask_count && task.subtask_count > 0" class="kanban-expand-btn"
                        :title="todoStore.expandedTaskId === task.id ? '收起' : '就地展开子任务'"
                        @click.stop="todoStore.toggleTaskExpand(task)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                       :style="{ transform: todoStore.expandedTaskId === task.id ? 'rotate(90deg)' : 'none', transition: 'transform .2s' }">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                </button>
              </div>
              <h4 class="kanban-card-title">{{ task.title }}</h4>
              <div class="kanban-card-footer">
                <span class="kanban-tag kanban-tag-progress" v-if="task.subtask_count && task.subtask_count > 0">
                  <span class="progress-ring" :style="{ '--prog': progressPercent(task) + '%', '--prog-color': cardProgressColor(progressPercent(task)) }"></span>
                  {{ task.subtask_done_count || 0 }}/{{ task.subtask_count }}
                </span>
                <span v-if="task.assignee_id" class="badge badge-assignee">{{ usersStore.userName(task.assignee_id) }}</span>
                <span v-if="task.area" class="kanban-tag">{{ task.area }}</span>
                <span v-if="task.due_date" class="kanban-tag kanban-tag-icon"
                      :class="{ 'is-warning': task.due_date < todoStore.todayISO && task.status !== 'done' }">
                  <Icon name="calendar" :size="11" /> {{ task.due_date }}
                </span>
                <span v-if="task.has_ai_insight" class="kanban-tag is-info kanban-tag-icon"><Icon name="search" :size="11" /> 洞察</span>
                <span v-for="(ref, idx) in (task.related_refs || []).slice(0, 1)" :key="idx" class="ref-badge ref-badge-sm" :title="ref.title || (ref.repo + '#' + ref.number)">
                  <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                  <span>{{ ref.repo }}#{{ ref.number }}</span>
                  <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
                </span>
                <span v-if="(task.related_refs || []).length > 1" class="kanban-tag">+{{ (task.related_refs || []).length - 1 }}</span>
              </div>

              <!-- In-place expanded subtasks -->
              <div v-if="todoStore.expandedTaskId === task.id" class="kanban-card-subtasks" @click="onSubtaskClick">
                <div v-for="st in expandedSubtasks" :key="st.id" class="subtask-inline">
                  <input type="checkbox" :checked="st.status === 'done'"
                         @change="todoStore.toggleSubtaskDone(st)" />
                  <span class="subtask-inline-title" :class="{ 'task-done': st.status === 'done' }">{{ st.title }}</span>
                  <span class="badge badge-assignee" v-if="st.assignee_id">{{ usersStore.userName(st.assignee_id) }}</span>
                  <span class="priority-badge" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                </div>
                <div class="subtask-inline-empty" v-if="expandedSubtasks.length === 0">无子任务</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- List view -->
    <template v-else>
      <div class="task-list">
        <div v-for="task in todoStore.tasks" :key="task.id" class="task-item" :class="{ 'overdue': task.due_date && task.due_date < todoStore.todayISO && task.status !== 'done' }" @click="todoStore.openTaskDetail(task)">
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
              <label class="form-label">批量拆子任务（可选）</label>
              <button class="btn btn-sm btn-subtle" @click="todoStore.openBulkModal('create', null)">
                点击在此任务下粘贴清单批量导入
              </button>
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

    <!-- ============ FULL-SCREEN DETAIL OVERLAY ============ -->
    <Teleport to="body">
      <div v-if="todoStore.selectedTask" class="overlay-backdrop" @click="todoStore.editingView ? null : todoStore.closeTask()">
        <div class="overlay-panel" @click.stop>
          <!-- Header -->
          <div class="overlay-header">
            <div class="overlay-title-block">
              <div class="drawer-title">
                <div class="pr-id">
                  <span>#{{ todoStore.selectedTask.id }}</span>
                  <span v-if="!todoStore.editingView" style="margin-left:10px;display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;">
                    <span class="priority-badge" :class="priorityClass(todoStore.selectedTask.priority)">{{ todoStore.selectedTask.priority }}</span>
                    <span class="status-badge" :class="statusClass(todoStore.selectedTask.status)">{{ statusLabel(todoStore.selectedTask.status) }}</span>
                    <span class="badge badge-source" :class="'source-' + todoStore.selectedTask.source">{{ sourceLabel(todoStore.selectedTask.source) }}</span>
                    <span v-if="todoStore.selectedTask.assignee_id" class="badge badge-assignee">{{ usersStore.userName(todoStore.selectedTask.assignee_id) }}</span>
                    <span v-if="todoStore.selectedTask.due_date" class="meta-item" :class="{ 'overdue': todoStore.selectedTask.due_date < todoStore.todayISO && todoStore.selectedTask.status !== 'done' }">截止 {{ todoStore.selectedTask.due_date }}</span>
                  </span>
                </div>
                <h2>{{ todoStore.editingView ? '编辑任务' : todoStore.selectedTask.title }}</h2>
              </div>
            </div>
            <div class="overlay-actions">
              <template v-if="!todoStore.editingView">
                <button class="btn btn-sm" @click="todoStore.startEditTaskView()">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  编辑
                </button>
                <button class="btn btn-sm" @click="generateInsight(todoStore.selectedTask!)" :disabled="todoStore.insightGenLoading">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/></svg>
                  {{ todoStore.insightGenLoading ? '生成中…' : 'AI 洞察' }}
                </button>
                <button class="btn btn-sm btn-success" :class="{ 'is-done': todoStore.selectedTask.status === 'done' }"
                        @click="todoStore.toggleTaskDone(todoStore.selectedTask!)">
                  <svg v-if="todoStore.selectedTask.status !== 'done'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                  <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                  {{ todoStore.selectedTask.status === 'done' ? '恢复' : '完成' }}
                </button>
                <button class="btn btn-sm btn-danger" @click="todoStore.deleteTask(todoStore.selectedTask!)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  删除
                </button>
              </template>
              <template v-else>
                <button class="btn btn-sm" @click="todoStore.cancelEditTaskView()">取消</button>
                <button class="btn btn-sm btn-primary" :disabled="!todoStore.editTaskForm.title?.trim()"
                        @click="todoStore.saveEditTaskView()">{{ todoStore.taskSaving ? '保存中…' : '保存' }}</button>
              </template>
              <button class="drawer-close" @click="todoStore.closeTask()" title="关闭">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>

          <!-- Tab bar (view only) -->
          <div v-if="!todoStore.editingView" class="tab-bar tab-bar-drawer overlay-tabs">
            <button class="tab" :class="{ active: todoStore.taskDetailTab === 'details' }"
                    @click="todoStore.switchDetailTab('details')">详情</button>
            <button class="tab" :class="{ active: todoStore.taskDetailTab === 'subtasks' }"
                    @click="todoStore.switchDetailTab('subtasks')">
              子任务
              <span v-if="todoStore.selectedTask?.subtask_count" class="tab-count">{{ todoStore.subtaskProgressText }}</span>
            </button>
            <button class="tab" :class="{ active: todoStore.taskDetailTab === 'insight' }"
                    @click="todoStore.switchDetailTab('insight')">
              AI 洞察
              <span v-if="todoStore.selectedTask?.has_ai_insight" class="badge badge-done"><Icon name="check" :size="10" /></span>
            </button>
          </div>

          <div class="overlay-body">
            <!-- ============ EDIT VIEW ============ -->
            <template v-if="todoStore.editingView">
              <div class="field" style="margin-bottom:var(--space-3);">
                <label class="field-label-sm">标题</label>
                <input type="text" class="input input-lg" v-model="todoStore.editTaskForm.title" placeholder="任务标题" />
              </div>
              <div class="field" style="margin-bottom:var(--space-3);">
                <label class="field-label-sm">描述</label>
                <textarea class="textarea" rows="18" v-model="todoStore.editTaskForm.description" placeholder="描述（支持 Markdown）"></textarea>
              </div>
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
                <div class="field" style="flex:0 0 120px;margin-top:0;">
                  <label class="field-label-sm">领域</label>
                  <input class="input" type="text" v-model="todoStore.editTaskForm.area" placeholder="如 engine" />
                </div>
                <div class="field" style="flex:0 0 140px;margin-top:0;">
                  <label class="field-label-sm">截止日期</label>
                  <input class="input" type="date" v-model="todoStore.editTaskForm.due_date" />
                </div>
              </div>
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
              </div>
            </template>

            <!-- ============ VIEW TABS ============ -->
            <template v-else>
              <!-- DETAILS TAB -->
              <div v-if="todoStore.taskDetailTab === 'details'" class="details-layout">
                <div class="details-main">
                  <div v-if="todoStore.taskDrawerLoading && !todoStore.selectedTaskDetails" class="detail-loading">加载中…</div>
                  <template v-else>
                    <div v-if="todoStore.selectedTask?.description" class="detail-desc">
                      <div v-html="renderMarkdown(todoStore.selectedTask.description)"></div>
                    </div>
                    <div v-else class="empty-state is-compact"><p>暂无描述</p></div>
                  </template>
                </div>
                <div class="details-side">
                  <label class="form-label">关联引用</label>
                  <div v-if="todoStore.selectedTask?.related_refs && todoStore.selectedTask.related_refs.length > 0" style="display:flex;flex-direction:column;gap:6px;">
                    <div v-for="(ref, idx) in todoStore.selectedTask.related_refs" :key="idx" class="ref-row clickable" @click.stop="openUrl(ref.url)">
                      <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                      <span class="ref-number">#{{ ref.number }}</span>
                      <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
                      <span class="ref-repo">{{ ref.repo }}</span>
                      <span class="ref-title">{{ ref.title || '' }}</span>
                    </div>
                  </div>
                  <div v-else style="color:var(--text-tertiary);font-size:var(--text-xs);">无关联引用</div>
                </div>
              </div>

              <!-- SUBTASKS TAB -->
              <div v-if="todoStore.taskDetailTab === 'subtasks'">
                <div class="overlay-subtask-toolbar">
                  <button class="btn btn-sm btn-primary" @click="todoStore.showSubtaskForm = !todoStore.showSubtaskForm">
                    {{ todoStore.showSubtaskForm ? '收起' : '＋ 添加子任务' }}
                  </button>
                  <button class="btn btn-sm btn-subtle" @click="todoStore.openBulkModal('edit', todoStore.selectedTask!.id)">
                    粘贴清单批量导入
                  </button>
                </div>

                <div v-if="todoStore.showSubtaskForm" style="margin-bottom:var(--space-4);padding:var(--space-4);background:var(--surface-faint);border-radius:var(--radius-md);border:1px solid var(--border-faint);">
                  <label class="form-label">新建子任务</label>
                  <div class="field" style="margin-bottom:var(--space-2);">
                    <label class="field-label-sm">标题</label>
                    <input class="input input-sm" type="text" v-model="todoStore.newSubtask.title" placeholder="子任务标题" @keyup.enter="todoStore.createSubtask()" />
                  </div>
                  <div class="field" style="margin-bottom:var(--space-2);">
                    <label class="field-label-sm">描述</label>
                    <textarea class="textarea textarea-sm" v-model="todoStore.newSubtask.description" placeholder="描述（可选）" rows="2"></textarea>
                  </div>
                  <div class="subtask-edit-grid" style="margin-bottom:var(--space-2);">
                    <div class="field">
                      <label class="field-label-sm">优先级</label>
                      <select class="select select-sm" v-model="todoStore.newSubtask.priority">
                        <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
                      </select>
                    </div>
                    <div class="field">
                      <label class="field-label-sm">责任人</label>
                      <select class="select select-sm" v-model.number="todoStore.newSubtask.assignee_id">
                        <option :value="null">无责任人</option>
                        <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                      </select>
                    </div>
                  </div>
                  <div class="field" style="margin-bottom:var(--space-2);">
                    <label class="field-label-sm">关联 PR/Issue</label>
                    <div class="ref-input-row">
                      <input class="input input-sm" type="text" v-model="todoStore.newSubtask.refInput"
                             placeholder="如 vllm#123 或纯数字" @keyup.enter="async () => { const r = await todoStore.resolveRef(todoStore.newSubtask.refInput); if (r) { todoStore.addRef(todoStore.newSubtask.related_refs, r); todoStore.newSubtask.refInput = '' } }" />
                      <button class="btn btn-sm" @click="async () => { const r = await todoStore.resolveRef(todoStore.newSubtask.refInput); if (r) { todoStore.addRef(todoStore.newSubtask.related_refs, r); todoStore.newSubtask.refInput = '' } }" :disabled="todoStore.resolveRefLoading || !todoStore.newSubtask.refInput.trim()">
                        {{ todoStore.resolveRefLoading ? '解析中…' : '添加' }}
                      </button>
                    </div>
                    <div v-if="todoStore.newSubtask.related_refs.length > 0" style="display:flex;flex-direction:column;gap:4px;margin-top:var(--space-1);">
                      <span v-for="(ref, idx) in todoStore.newSubtask.related_refs" :key="idx" class="ref-badge" :title="ref.title" style="display:inline-flex;align-items:center;justify-content:space-between;">
                        <span>
                          <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                          <span>{{ ref.repo }}#{{ ref.number }}</span>
                        </span>
                        <span class="ref-remove" @click="todoStore.newSubtask.related_refs.splice(idx, 1)" style="margin-left:6px;cursor:pointer;">&times;</span>
                      </span>
                    </div>
                  </div>
                  <div style="display:flex;gap:var(--space-2);margin-top:var(--space-2);">
                    <button class="btn btn-sm btn-primary" @click="todoStore.createSubtask()" :disabled="!todoStore.newSubtask.title.trim()">添加</button>
                    <button class="btn btn-sm" @click="todoStore.showSubtaskForm = false">取消</button>
                  </div>
                </div>

                <div class="subtask-list">
                  <div v-for="st in todoStore.subtasks" :key="st.id"
                       class="subtask-card" :class="'subtask-card-' + st.status">
                    <div class="subtask-card-head">
                      <div class="subtask-check">
                        <input type="checkbox" :checked="st.status === 'done'" @change="todoStore.toggleSubtaskDone(st)" />
                      </div>
                      <div class="subtask-checktitle">
                        <span class="subtask-checktitle-title" :class="{ 'task-done': st.status === 'done' }">{{ st.title }}</span>
                      </div>
                      <span class="subtask-checktitle-prio" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                      <div class="subtask-card-actions">
                        <button class="card-action-btn" @click.stop="todoStore.startEditSubtask(st)" title="编辑子任务">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        </button>
                        <button class="card-action-btn is-danger" @click.stop="todoStore.deleteSubtask(st)" title="删除子任务">
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                      </div>
                    </div>
                    <div v-if="st.description || st.assignee_id || (st.related_refs && st.related_refs.length > 0)" class="subtask-card-body">
                      <div v-if="st.description" class="subtask-card-desc">
                        <div v-html="renderMarkdown(st.description)"></div>
                      </div>
                      <div class="subtask-card-tags">
                        <span v-if="st.assignee_id" class="subtask-tag"><Icon name="user" :size="10" /> {{ usersStore.userName(st.assignee_id) }}</span>
                        <span v-if="st.status !== 'todo'" class="subtask-tag" :class="'is-' + st.status">{{ statusLabel(st.status) }}</span>
                        <span v-for="(ref, idx) in (st.related_refs || []).slice(0, 3)" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)">
                          <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                          <span>{{ ref.repo }}#{{ ref.number }}</span>
                          <span v-if="ref.state" class="ref-state" :class="'ref-state-' + ref.state">{{ ref.state }}</span>
                        </span>
                        <span v-if="(st.related_refs || []).length > 3" class="subtask-tag">+{{ (st.related_refs || []).length - 3 }}</span>
                      </div>
                    </div>
                    <div v-if="todoStore.editingSubtaskId === st.id" class="subtask-edit-inline">
                      <div class="field">
                        <label class="field-label-sm">标题</label>
                        <input class="input input-sm" type="text" v-model="todoStore.editSubtaskForm.title" @keyup.enter="todoStore.saveSubtask()" />
                      </div>
                      <div class="field">
                        <label class="field-label-sm">状态</label>
                        <div class="status-picker">
                          <button v-for="s in ['todo','in_progress','done','cancelled']" :key="s"
                                  :class="['status-opt', { active: todoStore.editSubtaskForm.status === s }]"
                                  @click="todoStore.editSubtaskForm.status = s">
                            {{ statusLabel(s) }}
                          </button>
                        </div>
                      </div>
                      <div class="subtask-edit-grid" style="margin-bottom:var(--space-2);">
                        <div class="field">
                          <label class="field-label-sm">优先级</label>
                          <select class="select select-sm" v-model="todoStore.editSubtaskForm.priority">
                            <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
                          </select>
                        </div>
                        <div class="field">
                          <label class="field-label-sm">责任人</label>
                          <select class="select select-sm" v-model.number="todoStore.editSubtaskForm.assignee_id">
                            <option :value="null">无责任人</option>
                            <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
                          </select>
                        </div>
                      </div>
                      <div class="field" style="margin-bottom:var(--space-2);">
                        <label class="field-label-sm">关联 PR/Issue</label>
                        <div class="ref-input-row">
                          <input class="input input-sm" type="text" v-model="editSubtaskRefInput"
                                 placeholder="如 vllm#123 或纯数字" @keyup.enter="addEditSubtaskRef()" />
                          <button class="btn btn-sm" @click="addEditSubtaskRef()" :disabled="subtaskRefLoading || !editSubtaskRefInput.trim()">
                            {{ subtaskRefLoading ? '解析中…' : '添加' }}
                          </button>
                        </div>
                        <div v-if="todoStore.editSubtaskForm.related_refs && todoStore.editSubtaskForm.related_refs.length > 0" style="display:flex;flex-direction:column;gap:4px;margin-top:var(--space-1);">
                          <span v-for="(ref, idx) in todoStore.editSubtaskForm.related_refs" :key="idx" class="ref-badge" :title="ref.title" style="display:inline-flex;align-items:center;justify-content:space-between;">
                            <span>
                              <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                              <span>{{ ref.repo }}#{{ ref.number }}</span>
                            </span>
                            <span class="ref-remove" @click="todoStore.editSubtaskForm.related_refs.splice(idx, 1)" style="margin-left:6px;cursor:pointer;">&times;</span>
                          </span>
                        </div>
                      </div>
                      <div class="field" style="margin-bottom:var(--space-2);">
                        <label class="field-label-sm">描述</label>
                        <textarea class="textarea textarea-sm" v-model="todoStore.editSubtaskForm.description" rows="2"></textarea>
                      </div>
                      <div class="subtask-edit-actions">
                        <button class="btn btn-sm" @click="todoStore.cancelEditSubtask()">取消</button>
                        <button class="btn btn-sm btn-primary" @click="todoStore.saveSubtask()">保存</button>
                      </div>
                    </div>
                  </div>
                  <div v-if="todoStore.subtasks.length === 0" class="empty-state is-compact">
                    <p>暂无子任务</p>
                  </div>
                </div>
              </div>

              <!-- INSIGHT TAB -->
              <div v-if="todoStore.taskDetailTab === 'insight'">
                <div v-if="!(todoStore.selectedTask as any).latest_insight_report_id" class="empty-state is-compact">
                  <p>尚未生成 AI 洞察报告</p>
                  <button class="btn btn-sm btn-primary" @click="generateInsight(todoStore.selectedTask!)">生成洞察</button>
                </div>
                <div v-else class="ai-section-body">
                  <button class="btn btn-sm btn-subtle" @click="openInsight(todoStore.selectedTask!)">
                    查看洞察报告
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Bulk SubTask Import Modal -->
    <Teleport to="body">
      <div v-if="todoStore.bulkModal.open" class="modal-backdrop" @click="todoStore.closeBulkModal()">
        <div class="modal modal-bulk" @click.stop>
          <div class="modal-header">
            <h3>粘贴清单批量拆子任务</h3>
            <button class="modal-close" @click="todoStore.closeBulkModal()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">Markdown / 文本清单</label>
              <textarea class="textarea" rows="10" v-model="todoStore.bulkModal.text"
                        placeholder="每行格式：标题 → 描述 @优先级 @责任人&#10;&#10;例：&#10;- 设置环境变量 → 显式覆盖优先 @P0 @王玺源&#10;- prefill parallelism > 1 → True @P1&#10;&#10;用 @P0/P1/P2/P3 设优先级，@姓名 指派人（需匹配系统用户）&#10;&#10;也可分组：&#10;一、判定优先级&#10;- 该组下的子任务"></textarea>
            </div>
            <div style="display:flex;justify-content:flex-end;margin-bottom:var(--space-3);">
              <button class="btn btn-sm btn-primary" @click="todoStore.parseMarkdownText()"
                      :disabled="todoStore.bulkModal.loading || !todoStore.bulkModal.text.trim()">
                {{ todoStore.bulkModal.loading ? '解析中…' : '解析预览' }}
              </button>
            </div>

            <div v-if="todoStore.bulkModal.rows.length > 0" class="bulk-preview">
              <label class="form-label">预览（{{ todoStore.bulkModal.rows.length }} 条）</label>
              <div class="bulk-preview-list">
                <div v-for="(row, idx) in todoStore.bulkModal.rows" :key="idx" class="bulk-preview-row">
                  <input type="checkbox" :checked="row.checked !== false" @change="todoStore.toggleBulkRow(idx)" />
                  <span class="bulk-group" v-if="row.group">[{{ row.group }}]</span>
                  <span class="bulk-title">{{ row.title }}</span>
                  <span class="priority-badge" :class="priorityClass(row.priority)">{{ row.priority }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="todoStore.closeBulkModal()">取消</button>
            <button class="btn btn-primary" :disabled="todoStore.bulkModal.creating || todoStore.bulkModal.rows.length === 0"
                    @click="todoStore.confirmBulkCreate()">
              {{ todoStore.bulkModal.creating ? '创建中…' : '确认创建' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.subtask-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding-top: var(--space-2);
  margin-top: var(--space-1);
}
</style>