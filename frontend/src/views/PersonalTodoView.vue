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
          <div v-for="task in items" :key="task.id" class="kanban-card" @click="todoStore.openTask(task)">
            <div class="kanban-card-header">
              <span class="badge" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
              <span class="kanban-card-source">{{ sourceLabel(task.source) }}</span>
            </div>
            <h4 class="kanban-card-title">{{ task.title }}</h4>
            <div class="kanban-card-meta">
              <span v-if="task.assignee_id">{{ usersStore.userName(task.assignee_id) }}</span>
              <span>{{ timeAgo(task.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- List view -->
    <template v-else>
      <div class="task-list">
        <div v-for="task in todoStore.tasks" :key="task.id" class="task-item" @click="todoStore.openTask(task)">
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
              <span v-if="task.assignee_id">{{ usersStore.userName(task.assignee_id) }}</span>
            </div>
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
              <option value="self">主动规划</option>
              <option value="team">产品反馈</option>
              <option value="community">社区反馈</option>
            </select>
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
            <h3>{{ todoStore.selectedTask.title }}</h3>
            <button class="btn btn-sm btn-ghost" @click="todoStore.closeTask()">&times;</button>
          </div>
          <div class="drawer-body">
            <div class="detail-section">
              <span class="badge" :class="priorityClass(todoStore.selectedTask.priority)">{{ todoStore.selectedTask.priority }}</span>
              <span class="badge" :class="statusClass(todoStore.selectedTask.status)">{{ statusLabel(todoStore.selectedTask.status) }}</span>
              <span>{{ sourceLabel(todoStore.selectedTask.source) }}</span>
            </div>
            <p v-if="todoStore.selectedTask.description" class="detail-desc">{{ todoStore.selectedTask.description }}</p>
            <div class="detail-actions">
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
