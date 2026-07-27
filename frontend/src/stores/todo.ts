import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { TodoTask } from '@/utils/types'

export const useTodoStore = defineStore('todo', () => {
  const tasks = ref<TodoTask[]>([])
  const todoStats = ref({ by_status: { todo: 0, in_progress: 0, done: 0 }, by_priority: { P0: 0, P1: 0, P2: 0, P3: 0 } })
  const loading = ref(false)
  const filterStatus = ref('all')
  const filterPriority = ref('all')
  const sortBy = ref('created')
  const sortOrder = ref('desc')
  const useKanban = ref(true)

  // Add modal
  const showAddModal = ref(false)
  const newTask = ref({
    title: '', description: '', source: 'self', priority: 'P2',
    area: '', assignee_id: null, due_date: '', related_refs: [] as any[],
    refInput: '', trigger_dedup_check: false,
  })
  const newTaskLoading = ref(false)

  // Task drawer
  const selectedTask = ref<TodoTask | null>(null)
  const selectedTaskDetails = ref<any>(null)
  const taskDrawerLoading = ref(false)
  const editingTask = ref(false)
  const editTaskForm = ref<any>({})

  // Dedup
  const dedupLoading = ref(false)
  const dedupResult = ref<any>(null)

  // Insight
  const insightGenLoading = ref(false)

  // Subtasks
  const subtasks = ref<TodoTask[]>([])
  const subtasksLoading = ref(false)
  const showSubtaskForm = ref(false)
  const newSubtask = ref({ title: '', priority: 'P2', assignee_id: null, related_refs: [] as any[], refInput: '' })
  const editingSubtaskId = ref<number | null>(null)
  const editSubtaskForm = ref<any>({})

  // Computed
  const tasksByPriority = computed(() => {
    const groups: Record<string, TodoTask[]> = { P0: [], P1: [], P2: [], P3: [] }
    for (const t of tasks.value) {
      if (t.status === 'done' || t.status === 'cancelled') continue
      if (groups[t.priority]) groups[t.priority].push(t)
    }
    return groups
  })

  const todoCount = computed(() => todoStats.value.by_status?.todo || 0)
  const inProgressCount = computed(() => todoStats.value.by_status?.in_progress || 0)
  const doneCount = computed(() => todoStats.value.by_status?.done || 0)
  const subtaskProgress = computed(() => subtasks.value.filter(s => s.status === 'done').length)
  const subtaskProgressText = computed(() => `${subtaskProgress.value}/${subtasks.value.length}`)

  // Today ISO
  let _todayCacheDate: string | null = null
  let _todayCache = ''
  const todayISO = computed(() => {
    void useAppStore().nowTick
    const d = new Date()
    const todayKey = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    if (_todayCacheDate !== todayKey) {
      const y = d.getFullYear()
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      _todayCache = `${y}-${m}-${day}`
      _todayCacheDate = todayKey
    }
    return _todayCache
  })

  // Actions
  async function loadTasks() {
    loading.value = true
    try {
      const params = new URLSearchParams()
      params.set('status', filterStatus.value)
      if (filterPriority.value !== 'all') params.set('priority', filterPriority.value)
      params.set('sort_by', sortBy.value)
      params.set('sort_order', sortOrder.value)
      params.set('per_page', '50')
      const data: any = await api('/api/personal-todo/tasks?' + params)
      tasks.value = data.tasks || []
      todoStats.value = data.stats || todoStats.value
    } catch (e: any) {
      useAppStore().showToast('加载任务失败', e.message, 'error')
    } finally {
      loading.value = false
    }
  }

  async function createTask() {
    if (!newTask.value.title.trim()) {
      useAppStore().showToast('标题不能为空', '请输入任务标题', 'error')
      return
    }
    if (newTaskLoading.value) return
    newTaskLoading.value = true
    try {
      const { trigger_dedup_check, refInput, ...payload } = newTask.value as any
      if (!payload.due_date) delete payload.due_date
      if (!payload.area) delete payload.area
      if (!payload.related_refs || payload.related_refs.length === 0) delete payload.related_refs
      const result: any = await api('/api/personal-todo/tasks', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, { timeout: 120000 })
      tasks.value.unshift(result)
      if (todoStats.value.by_status) todoStats.value.by_status.todo = (todoStats.value.by_status.todo || 0) + 1
      if (todoStats.value.by_priority) {
        (todoStats.value.by_priority as any)[result.priority] = ((todoStats.value.by_priority as any)[result.priority] || 0) + 1
      }
      useAppStore().showToast('任务已创建', `#${result.id} ${result.title}`, 'success')
      newTask.value = { title: '', description: '', source: 'self', priority: 'P2', area: '', assignee_id: null, due_date: '', related_refs: [], refInput: '', trigger_dedup_check: false }
      showAddModal.value = false
      if (result.dedup_check_result?.matches?.length > 0) {
        useAppStore().showToast('发现可能重复', `${result.dedup_check_result.matches.length} 个相似 issue/PR`, 'info', 6000)
      }
    } catch (e: any) {
      useAppStore().showToast('创建失败', e.message, 'error')
    } finally {
      newTaskLoading.value = false
    }
  }

  // Task drawer
  async function openTask(task: TodoTask) {
    selectedTask.value = task
    selectedTaskDetails.value = null
    taskDrawerLoading.value = false
    editingTask.value = false
    dedupResult.value = (task as any).dedup_check_result || null
    subtasks.value = []
    showSubtaskForm.value = false
    loadTaskDetails(task.id)
    loadSubtasks(task.id)
  }

  function closeTask() {
    selectedTask.value = null
    selectedTaskDetails.value = null
    editingTask.value = false
    dedupResult.value = null
    subtasks.value = []
    showSubtaskForm.value = false
    newSubtask.value = { title: '', priority: 'P2', assignee_id: null, related_refs: [], refInput: '' }
  }

  async function loadTaskDetails(taskId: number) {
    if (!taskId) return
    taskDrawerLoading.value = true
    try {
      const details = await api(`/api/personal-todo/tasks/${taskId}`)
      selectedTaskDetails.value = details
      dedupResult.value = details.dedup_check_result || null
    } catch (e: any) {
      useAppStore().showToast('加载详情失败', e.message, 'error')
    } finally {
      taskDrawerLoading.value = false
    }
  }

  // Edit task
  function startEditTask() {
    if (!selectedTaskDetails.value) return
    const details = selectedTaskDetails.value
    editTaskForm.value = {
      ...details,
      related_refs: details.related_refs ? JSON.parse(JSON.stringify(details.related_refs)) : [],
      tags: details.tags ? [...details.tags] : [],
    }
    editingTask.value = true
  }

  function cancelEditTask() {
    editingTask.value = false
    editTaskForm.value = {}
  }

  async function saveTask() {
    if (!selectedTaskDetails.value) return
    if (!editTaskForm.value.title?.trim()) {
      useAppStore().showToast('标题不能为空', '', 'error')
      return
    }
    try {
      const updates: Record<string, any> = {}
      const fields = ['title', 'description', 'source', 'priority', 'status', 'area', 'assignee_id', 'due_date', 'related_refs']
      for (const f of fields) {
        let oldVal = selectedTaskDetails.value[f]
        let newVal = editTaskForm.value[f]
        if (newVal === '') newVal = null
        const isEqual = Array.isArray(oldVal) && Array.isArray(newVal)
          ? JSON.stringify(oldVal) === JSON.stringify(newVal)
          : oldVal === newVal
        if (!isEqual) updates[f] = newVal
      }
      if (Object.keys(updates).length === 0) {
        editingTask.value = false
        return
      }
      const result = await api(`/api/personal-todo/tasks/${selectedTaskDetails.value.id}`, {
        method: 'PUT',
        body: JSON.stringify(updates),
      })
      selectedTaskDetails.value = result
      const idx = tasks.value.findIndex(t => t.id === result.id)
      if (idx >= 0) tasks.value[idx] = { ...tasks.value[idx], ...result }
      editingTask.value = false
      useAppStore().showToast('已保存', '任务已更新', 'success')
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    }
  }

  // Delete
  async function deleteTask(task: TodoTask) {
    if (!confirm(`确认删除任务 #${task.id} "${task.title}"？`)) return
    const backup = { ...task }
    try {
      await api(`/api/personal-todo/tasks/${task.id}`, { method: 'DELETE' })
      tasks.value = tasks.value.filter(t => t.id !== task.id)
      if (selectedTaskDetails.value?.id === task.id) closeTask()
      useAppStore().showUndoToast('已删除', `#${task.id} ${task.title}`, async () => {
        try {
          const result: any = await api('/api/personal-todo/tasks', {
            method: 'POST',
            body: JSON.stringify({
              title: backup.title, description: backup.description,
              source: backup.source || 'self', priority: backup.priority || 'P2',
              area: backup.area || '', assignee_id: backup.assignee_id || null,
              due_date: backup.due_date || '', related_refs: backup.related_refs || [],
              status: backup.status || 'todo',
            }),
          })
          tasks.value.unshift(result)
          useAppStore().showToast('已恢复', `#${result.id} ${result.title}`, 'success')
          loadTasks()
        } catch (e: any) {
          useAppStore().showToast('恢复失败', e.message, 'error')
        }
      }, 10000)
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  // Toggle done
  async function toggleTaskDone(task: TodoTask) {
    let newStatus = task.status === 'done' ? 'todo' : 'done'
    if (task.status === 'cancelled') newStatus = 'todo'
    try {
      const result = await api(`/api/personal-todo/tasks/${task.id}`, {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus }),
      })
      const idx = tasks.value.findIndex(t => t.id === task.id)
      if (idx >= 0) tasks.value[idx] = { ...tasks.value[idx], ...result }
      if (selectedTaskDetails.value?.id === task.id) selectedTaskDetails.value = result
      useAppStore().showToast(newStatus === 'done' ? '已完成' : '已恢复', '', 'success')
    } catch (e: any) {
      useAppStore().showToast('操作失败', e.message, 'error')
    }
  }

  // Dedup
  async function runDedupCheck(task: TodoTask) {
    if (dedupLoading.value) return
    dedupLoading.value = true
    try {
      const result: any = await api(`/api/personal-todo/tasks/${task.id}/dedup-check`, {
        method: 'POST',
        body: JSON.stringify({ repos: [], check_type: 'hybrid' }),
      }, { timeout: 120000 })
      dedupResult.value = { checked: true, matches: result.results || [] }
      const idx = tasks.value.findIndex(t => t.id === task.id)
      if (idx >= 0) {
        tasks.value[idx].dedup_check_result = dedupResult.value
        tasks.value[idx].has_dedup_check = true
      }
      if (selectedTaskDetails.value?.id === task.id) {
        selectedTaskDetails.value.dedup_check_result = dedupResult.value
        selectedTaskDetails.value.has_dedup_check = true
      }
      const matchCount = (result.results || []).length
      if (matchCount > 0) {
        useAppStore().showToast('发现可能重复', `${matchCount} 个相似 issue/PR`, 'info', 6000)
      } else {
        useAppStore().showToast('无重复', '未发现相似 issue/PR', 'success')
      }
    } catch (e: any) {
      useAppStore().showToast('去重检查失败', e.message, 'error')
    } finally {
      dedupLoading.value = false
    }
  }

  // Subtasks
  async function loadSubtasks(taskId: number) {
    if (!taskId) return
    subtasksLoading.value = true
    try {
      const data: any = await api(`/api/personal-todo/tasks/${taskId}/subtasks`)
      subtasks.value = data.subtasks || []
    } catch (e: any) {
      useAppStore().showToast('加载子任务失败', e.message, 'error')
      subtasks.value = []
    } finally {
      subtasksLoading.value = false
    }
  }

  async function createSubtask() {
    if (!newSubtask.value.title.trim() || !selectedTask.value) return
    try {
      const result: any = await api('/api/personal-todo/tasks', {
        method: 'POST',
        body: JSON.stringify({
          title: newSubtask.value.title.trim(),
          priority: newSubtask.value.priority,
          assignee_id: newSubtask.value.assignee_id,
          related_refs: newSubtask.value.related_refs || [],
          parent_id: selectedTask.value.id,
          source: 'self',
        }),
      })
      subtasks.value.push(result)
      newSubtask.value = { title: '', priority: 'P2', assignee_id: null, related_refs: [], refInput: '' }
      showSubtaskForm.value = false
      loadTasks()
      useAppStore().showToast('子任务已创建', result.title, 'success')
    } catch (e: any) {
      useAppStore().showToast('创建子任务失败', e.message, 'error')
    }
  }

  async function toggleSubtaskDone(subtask: TodoTask) {
    let newStatus = subtask.status === 'done' ? 'todo' : 'done'
    if (subtask.status === 'cancelled') newStatus = 'todo'
    try {
      const result = await api(`/api/personal-todo/tasks/${subtask.id}`, {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus }),
      })
      const idx = subtasks.value.findIndex(s => s.id === subtask.id)
      if (idx >= 0) subtasks.value[idx] = result
      loadTasks()
      useAppStore().showToast(newStatus === 'done' ? '子任务已完成' : '子任务已恢复', result.title, 'success')
    } catch (e: any) {
      useAppStore().showToast('操作失败', e.message, 'error')
    }
  }

  async function deleteSubtask(subtask: TodoTask) {
    if (!confirm(`确认删除子任务「${subtask.title}」？`)) return
    try {
      await api(`/api/personal-todo/tasks/${subtask.id}`, { method: 'DELETE' })
      subtasks.value = subtasks.value.filter(s => s.id !== subtask.id)
      loadTasks()
      useAppStore().showToast('子任务已删除', '', 'info')
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  // Subtask edit
  function startEditSubtask(subtask: TodoTask) {
    editingSubtaskId.value = subtask.id
    editSubtaskForm.value = {
      ...subtask,
      related_refs: subtask.related_refs ? JSON.parse(JSON.stringify(subtask.related_refs)) : [],
    }
  }

  function cancelEditSubtask() {
    editingSubtaskId.value = null
    editSubtaskForm.value = {}
  }

  async function saveSubtask() {
    if (!editingSubtaskId.value) return
    const subtask = subtasks.value.find(s => s.id === editingSubtaskId.value)
    if (!subtask) return
    if (!editSubtaskForm.value.title?.trim()) {
      useAppStore().showToast('标题不能为空', '', 'error')
      return
    }
    try {
      const updates: Record<string, any> = {}
      const fields = ['title', 'priority', 'source', 'assignee_id', 'status', 'related_refs', 'area']
      for (const f of fields) {
        let oldVal = (subtask as any)[f]
        let newVal = editSubtaskForm.value[f]
        if (newVal === '') newVal = null
        const isEqual = Array.isArray(oldVal) && Array.isArray(newVal)
          ? JSON.stringify(oldVal) === JSON.stringify(newVal)
          : oldVal === newVal
        if (!isEqual) updates[f] = newVal
      }
      if (Object.keys(updates).length === 0) {
        editingSubtaskId.value = null
        return
      }
      const result = await api(`/api/personal-todo/tasks/${subtask.id}`, {
        method: 'PUT',
        body: JSON.stringify(updates),
      })
      const idx = subtasks.value.findIndex(s => s.id === subtask.id)
      if (idx >= 0) subtasks.value[idx] = result
      editingSubtaskId.value = null
      editSubtaskForm.value = {}
      useAppStore().showToast('子任务已更新', result.title, 'success')
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    }
  }

  // Resolve ref
  const resolveRefLoading = ref(false)

  async function resolveRef(input: string): Promise<any | null> {
    if (!input.trim()) return null
    resolveRefLoading.value = true
    try {
      const result: any = await api('/api/personal-todo/resolve-ref', {
        method: 'POST',
        body: JSON.stringify({ input: input.trim() }),
      })
      return result
    } catch (e: any) {
      useAppStore().showToast('解析失败', e.message, 'error')
      return null
    } finally {
      resolveRefLoading.value = false
    }
  }

  function addRef(refs: any[], ref: any) {
    if (refs.some(r => r.type === ref.type && r.number === ref.number)) {
      useAppStore().showToast('已存在', '该引用已添加', 'info')
      return
    }
    refs.push(ref)
  }

  function removeRef(refs: any[], idx: number) {
    refs.splice(idx, 1)
  }

  // Filters
  function switchStatusFilter(status: string) {
    filterStatus.value = status
    loadTasks()
  }

  function switchPriorityFilter(priority: string) {
    filterPriority.value = priority
    loadTasks()
  }

  // Insight
  async function openTaskInsight(task: TodoTask) {
    const reportId = (task as any).latest_insight_report_id
    if (!reportId) {
      useAppStore().showToast('暂无报告', '该任务还没有已完成的洞察报告', 'info')
      return
    }
    // Navigate to intelligence view - will be handled by router
    return reportId
  }

  async function generateInsightFromTask(task: TodoTask) {
    if (insightGenLoading.value) return
    insightGenLoading.value = true
    try {
      const result: any = await api('/api/intelligence/generate', {
        method: 'POST',
        body: JSON.stringify({
          task_id: task.id,
          sources: ['vllm', 'vllm-ascend', 'sglang', 'academic', 'news'],
        }),
      }, { timeout: 30000 })
      useAppStore().showToast('报告生成中', result.message || '请稍后在洞察面板查看', 'success', 6000)
      closeTask()
      return result.report_id
    } catch (e: any) {
      useAppStore().showToast('生成失败', e.message, 'error')
    } finally {
      insightGenLoading.value = false
    }
    return null
  }

  return {
    tasks, todoStats, loading, filterStatus, filterPriority, sortBy, sortOrder,
    useKanban, showAddModal, newTask, newTaskLoading,
    selectedTask, selectedTaskDetails, taskDrawerLoading, editingTask, editTaskForm,
    dedupLoading, dedupResult, insightGenLoading,
    subtasks, subtasksLoading, showSubtaskForm, newSubtask,
    editingSubtaskId, editSubtaskForm,
    tasksByPriority, todoCount, inProgressCount, doneCount,
    subtaskProgress, subtaskProgressText, todayISO,
    loadTasks, createTask, deleteTask, toggleTaskDone,
    openTask, closeTask, loadTaskDetails,
    startEditTask, cancelEditTask, saveTask,
    runDedupCheck, openTaskInsight, generateInsightFromTask,
    loadSubtasks, createSubtask, toggleSubtaskDone, deleteSubtask,
    startEditSubtask, cancelEditSubtask, saveSubtask,
    resolveRefLoading, resolveRef, addRef, removeRef,
    switchStatusFilter, switchPriorityFilter,
  }
})