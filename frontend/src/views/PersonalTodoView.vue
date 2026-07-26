<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useTodoStore } from '@/stores/todo'
import { useAppStore } from '@/stores/app'
import { timeAgo } from '@/utils/helpers'
import { useUsersStore } from '@/stores/users'
import { useIntelStore } from '@/stores/intel'
import { useRouter } from 'vue-router'
import { statusLabel, sourceLabel, priorityClass, statusClass } from '@/utils/helpers'

const todoStore = useTodoStore()
const appStore = useAppStore()
const usersStore = useUsersStore()
const intelStore = useIntelStore()
const router = useRouter()

onMounted(() => {
  todoStore.loadTasks()
})

const statusFilters = ['all', 'todo', 'in_progress', 'done']
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
  await todoStore.generateInsightFromTask(task)
  router.push({ name: 'intelligence' })
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">任务面板</h2>
      <div class="view-actions">
        <label class="toggle-label">
          <input type="checkbox" v-model="todoStore.useKanban" /> 卡片视图
        </label>
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
        <div v-for="(items, priority) in todoStore.tasksByPriority" :key="priority" class="kanban-column">
          <h3 class="kanban-column-title" :class="priorityClass(priority)">{{ priority }}</h3>
          <div v-for="task in items" :key="task.id" class="kanban-card" :class="{ 'overdue': task.due_date && task.due_date < todoStore.todayISO && task.status !== 'done' }" @click="todoStore.openTask(task)">
            <div class="kanban-card-header">
              <span class="badge" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
              <span class="kanban-card-source">{{ sourceLabel(task.source) }}</span>
            </div>
            <h4 class="kanban-card-title">{{ task.title }}</h4>
            <div class="kanban-card-meta">
              <span v-if="task.assignee_id" class="badge badge-assignee">{{ usersStore.userName(task.assignee_id) }}</span>
              <span v-if="task.area" class="meta-item">{{ task.area }}</span>
              <span v-if="task.due_date" class="meta-item" :class="{ 'overdue': task.due_date < todoStore.todayISO && task.status !== 'done' }">截止 {{ task.due_date }}</span>
              <span v-if="task.subtask_count && task.subtask_count > 0" class="badge badge-subtask">{{ task.subtask_done_count || 0 }}/{{ task.subtask_count }}</span>
            </div>
            <div class="kanban-card-meta" v-if="task.related_refs && task.related_refs.length > 0">
              <span v-for="(ref, idx) in task.related_refs.slice(0, 3)" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)">
                <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                <span>{{ ref.repo }}#{{ ref.number }}</span>
              </span>
            </div>
            <div class="kanban-card-badges" v-if="task.has_dedup_check || task.has_ai_insight">
              <span v-if="task.has_dedup_check && task.dedup_check_result?.matches?.length > 0" class="badge badge-warning">{{ task.dedup_check_result.matches.length }} 重复</span>
              <span v-if="task.has_dedup_check && (!task.dedup_check_result || !task.dedup_check_result.matches || task.dedup_check_result.matches.length === 0)" class="badge badge-success">无重复</span>
              <span v-if="task.has_ai_insight" class="badge badge-info" style="cursor:pointer;" @click.stop="openInsight(task)" title="查看洞察报告">有洞察</span>
            </div>
            <div class="kanban-card-actions">
              <button class="btn btn-sm btn-ghost" @click.stop="generateInsight(task)" title="生成洞察报告" :disabled="todoStore.insightGenLoading">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              </button>
              <button class="btn btn-sm btn-ghost" @click.stop="todoStore.toggleTaskDone(task)" :title="task.status === 'done' ? '恢复未完成' : '标记完成'" v-if="task.status !== 'cancelled'">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              </button>
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
              <span v-if="task.area">{{ task.area }}</span>
              <span v-if="task.due_date" :class="{ 'overdue': task.due_date < todoStore.todayISO && task.status !== 'done' }">截止 {{ task.due_date }}</span>
              <span v-if="task.subtask_count && task.subtask_count > 0" class="badge badge-subtask">{{ task.subtask_done_count || 0 }}/{{ task.subtask_count }}</span>
              <span v-for="(ref, idx) in (task.related_refs || []).slice(0, 2)" :key="idx" class="ref-badge" :title="ref.title || (ref.repo + '#' + ref.number)">
                <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                <span>{{ ref.repo }}#{{ ref.number }}</span>
              </span>
            </div>
          </div>
          <div class="item-side">
            <span v-if="task.has_dedup_check && task.dedup_check_result?.matches?.length > 0" class="badge badge-warning">{{ task.dedup_check_result.matches.length }} 重复</span>
            <span v-if="task.has_ai_insight" class="badge badge-info" style="cursor:pointer;" @click.stop="openInsight(task)">有洞察</span>
          </div>
        </div>
      </div>
    </template>

    <!-- Add Task Modal -->
    <Teleport to="body">
      <div v-if="todoStore.showAddModal" class="modal-backdrop" @click="todoStore.showAddModal = false">
        <div class="modal" @click.stop>
          <h3 class="modal-title">新建任务</h3>
          <div class="form-group">
            <input type="text" class="input input-lg" v-model="todoStore.newTask.title" placeholder="任务标题" />
          </div>
          <div class="form-group">
            <textarea class="textarea" v-model="todoStore.newTask.description" placeholder="描述（可选）" rows="3"></textarea>
          </div>
          <div class="form-row">
            <select class="select" v-model="todoStore.newTask.priority">
              <option v-for="p in ['P0','P1','P2','P3']" :key="p" :value="p">{{ p }}</option>
            </select>
            <select class="select" v-model="todoStore.newTask.source">
              <option v-for="s in sources" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
            <select class="select" v-model="todoStore.newTask.assignee_id">
              <option :value="null">责任人…</option>
              <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
            </select>
          </div>
          <div class="form-row">
            <input class="input" type="text" placeholder="领域 (如 engine)" v-model="todoStore.newTask.area" />
            <input class="input" type="date" v-model="todoStore.newTask.due_date" title="截止日期" />
          </div>
          <div class="form-group">
            <label class="form-label">
              <input type="checkbox" v-model="todoStore.newTask.trigger_dedup_check" style="margin-right:6px;" />
              添加后自动去重检查
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn" @click="todoStore.showAddModal = false">取消</button>
            <button class="btn btn-primary" :disabled="todoStore.newTaskLoading"
                    @click="todoStore.createTask()">{{ todoStore.newTaskLoading ? '创建中…' : '创建' }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Task Drawer -->
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
            <button class="btn btn-sm btn-ghost" @click="todoStore.closeTask()">&times;</button>
          </div>
          <div class="drawer-body">
            <!-- Meta section -->
            <div class="detail-section" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:var(--space-4);">
              <span class="priority-badge" :class="priorityClass(todoStore.selectedTask.priority)">{{ todoStore.selectedTask.priority }}</span>
              <span class="status-badge" :class="statusClass(todoStore.selectedTask.status)">{{ statusLabel(todoStore.selectedTask.status) }}</span>
              <span class="badge badge-source" :class="'source-' + todoStore.selectedTask.source">{{ sourceLabel(todoStore.selectedTask.source) }}</span>
              <span v-if="todoStore.selectedTask.assignee_id" class="badge badge-assignee">{{ usersStore.userName(todoStore.selectedTask.assignee_id) }}</span>
              <span v-if="todoStore.selectedTask.area" class="meta-item">{{ todoStore.selectedTask.area }}</span>
              <span v-if="todoStore.selectedTask.due_date" class="meta-item" :class="{ 'overdue': todoStore.selectedTask.due_date < todoStore.todayISO && todoStore.selectedTask.status !== 'done' }">截止 {{ todoStore.selectedTask.due_date }}</span>
            </div>

            <!-- Description -->
            <p v-if="todoStore.selectedTask.description" class="detail-desc" style="margin-bottom:var(--space-4);padding:12px;background:var(--bg-secondary);border-radius:6px;line-height:1.6;">{{ todoStore.selectedTask.description }}</p>

            <!-- Related refs -->
            <div v-if="todoStore.selectedTask.related_refs && todoStore.selectedTask.related_refs.length > 0" style="margin-bottom:var(--space-4);">
              <label class="form-label">关联引用</label>
              <div style="display:flex;gap:4px;flex-wrap:wrap;">
                <span v-for="(ref, idx) in todoStore.selectedTask.related_refs" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)">
                  <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                  <span>{{ ref.repo }}#{{ ref.number }}</span>
                </span>
              </div>
            </div>

            <!-- Dedup result -->
            <div v-if="todoStore.dedupResult" style="margin-bottom:var(--space-4);">
              <label class="form-label">去重结果</label>
              <div v-if="todoStore.dedupResult.matches && todoStore.dedupResult.matches.length > 0" class="ai-result">
                <div class="ai-result-body">
                  <p>发现 <strong>{{ todoStore.dedupResult.matches.length }}</strong> 个可能重复的项：</p>
                  <div v-for="m in todoStore.dedupResult.matches" :key="m.id || m.number" class="dedup-item" style="font-size:12px;padding:4px 0;">
                    <a :href="m.url" target="_blank" style="color:var(--text-primary);">{{ m.title }}</a>
                    <span v-if="m.repo" class="badge" style="margin-left:4px;">{{ m.repo }}#{{ m.number }}</span>
                  </div>
                </div>
              </div>
              <div v-else>
                <span class="badge badge-success">未发现重复</span>
              </div>
            </div>

            <!-- AI Insight -->
            <div v-if="(todoStore.selectedTask as any).latest_insight_report_id" style="margin-bottom:var(--space-4);">
              <label class="form-label">AI 洞察</label>
              <span class="badge badge-info" style="cursor:pointer;" @click="openInsight(todoStore.selectedTask!)">查看洞察报告</span>
            </div>

            <!-- Subtasks -->
            <div v-if="todoStore.subtasks.length > 0" style="margin-bottom:var(--space-4);">
              <label class="form-label">子任务 ({{ todoStore.subtaskProgressText }})</label>
              <div v-for="st in todoStore.subtasks" :key="st.id" class="subtask-item" style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--bg-secondary);border-radius:4px;margin-bottom:4px;">
                <input type="checkbox" :checked="st.status === 'done'" @change="todoStore.toggleSubtaskDone(st)" />
                <span :class="{ 'task-done': st.status === 'done' }" style="flex:1;">{{ st.title }}</span>
                <span class="badge" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                <button class="btn btn-sm btn-ghost" @click.stop="todoStore.deleteSubtask(st)" style="color:var(--signal-red);padding:2px;">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
            </div>

            <!-- Actions -->
            <div class="detail-actions" style="display:flex;gap:6px;flex-wrap:wrap;">
              <button class="btn btn-sm" @click="todoStore.toggleTaskDone(todoStore.selectedTask!)">
                {{ todoStore.selectedTask.status === 'done' ? '恢复' : '完成' }}
              </button>
              <button class="btn btn-sm" @click="todoStore.startEditTask()">编辑</button>
              <button class="btn btn-sm" @click="todoStore.runDedupCheck(todoStore.selectedTask!)">去重检查</button>
              <button class="btn btn-sm" @click="generateInsight(todoStore.selectedTask!)">生成洞察</button>
              <button class="btn btn-sm btn-ghost" @click="todoStore.deleteTask(todoStore.selectedTask!)">删除</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>