import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { WatchlistItem } from '@/utils/types'

export const useWatchlistStore = defineStore('watchlist', () => {
  const watchlist = ref<WatchlistItem[]>([])
  const watchlistSet = ref<Set<string>>(new Set())
  const watchlistTab = ref<'all' | 'pr' | 'issue'>('pr')

  // Add modal
  const showAddModal = ref(false)
  const manualAddType = ref('issue')
  const manualAddNumber = ref('')
  const manualAddLoading = ref(false)
  const manualAddNote = ref('')
  const manualAddAssigneeId = ref<number | null>(null)
  const manualAddLinkTaskMode = ref<'none' | 'existing' | 'new'>('none')
  const manualAddTaskSearchQuery = ref('')
  const manualAddTaskSearchResults = ref<any[]>([])
  const manualAddTaskSearchLoading = ref(false)
  const manualAddTaskOpen = ref(false)
  const manualAddNewTaskTitle = ref('')
  const manualAddNewTaskPriority = ref('P2')
  const manualAddNewTaskSource = ref('self')
  const manualAddSelectedTaskId = ref<number | null>(null)
  const manualAddSelectedTaskTitle = ref('')

  // Edit modal
  const showEditModal = ref(false)
  const editingWatchlistItem = ref<WatchlistItem | null>(null)
  const watchlistEditNote = ref('')
  const watchlistEditAssigneeId = ref<number | null>(null)
  const watchlistEditSaving = ref(false)
  const watchlistEditTaskList = ref<any[]>([])
  const watchlistEditLinkTaskId = ref('')
  const watchlistEditSelectedTasks = ref<any[]>([])
  const watchlistEditShowCreate = ref(false)
  const watchlistEditNewTaskTitle = ref('')
  const watchlistEditNewTaskSource = ref('self')
  const watchlistEditNewTaskPriority = ref('P2')

  const watchlistAssigneeFilter = ref<number | null>(null)

  const filteredWatchlist = computed(() => {
    const appStore = useAppStore()
    const q = (appStore.searchQuery || '').toLowerCase().trim()
    let list = watchlist.value
    if (watchlistTab.value !== 'all') {
      list = list.filter(w => w.item_type === watchlistTab.value)
    }
    if (watchlistAssigneeFilter.value !== null) {
      list = list.filter(w => w.assignee_id === watchlistAssigneeFilter.value)
    }
    if (q) {
      list = list.filter(w =>
        (w.title || '').toLowerCase().includes(q) ||
        String(w.number).includes(q),
      )
    }
    return list
  })

  function _watchKey(number: number, type: string) { return type + ':' + number }

  function isWatched(number: number, type: string): boolean {
    return watchlistSet.value.has(_watchKey(number, type))
  }

  function findWatchlistItem(number: number, type: string): WatchlistItem | null {
    return watchlist.value.find(i => i.number === number && i.item_type === type) || null
  }

  async function loadWatchlist() {
    try {
      const items: WatchlistItem[] = await api('/api/watchlist')
      watchlist.value = items
      watchlistSet.value = new Set(items.map(i => _watchKey(i.number, i.item_type)))
    } catch (_) {}
  }

  async function toggleWatch(number: number, type: string, title: string, url: string, extra?: any) {
    const key = _watchKey(number, type)
    if (watchlistSet.value.has(key)) {
      const ok = await useAppStore().showConfirm({
        title: '取消关注',
        message: `确认将 #${number} 移出特别关注？`,
        confirmText: '确认移出',
        danger: true,
      })
      if (!ok) return
      try {
        await api(`/api/watchlist/${type}/${number}`, { method: 'DELETE' })
        watchlistSet.value.delete(key)
        watchlist.value = watchlist.value.filter(w => _watchKey(w.number, w.item_type) !== key)
        useAppStore().showToast('已取消关注', `#${number} 已移出特别关注`, 'info')
      } catch (e: any) {
        useAppStore().showToast('取消关注失败', e.message, 'error')
      }
    } else {
      const meta = extra || {}
      const payload: any = { number, item_type: type, title, url }
      if (meta.area) payload.area = meta.area
      if (meta.issue_type) payload.issue_type = meta.issue_type
      if (meta.state) payload.state = meta.state
      try {
        await api('/api/watchlist', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        watchlistSet.value.add(key)
        watchlist.value.unshift({ number, item_type: type, title, url, added_at: new Date().toISOString(), ...meta })
        useAppStore().showToast('已加入关注', `#${number} 已加入特别关注`, 'success')
      } catch (e: any) {
        useAppStore().showToast('加入关注失败', e.message, 'error')
      }
    }
  }

  async function addWatchlistByNumber() {
    const num = parseInt(manualAddNumber.value, 10)
    if (!num || num <= 0) {
      useAppStore().showToast('编号无效', '请输入正确的 issue/PR 编号', 'error')
      return
    }
    if (manualAddLoading.value) return
    const prKey = _watchKey(num, 'pr')
    const issueKey = _watchKey(num, 'issue')
    if (watchlistSet.value.has(prKey) || watchlistSet.value.has(issueKey)) {
      useAppStore().showToast('已在关注列表', `#${num} 已在特别关注中`, 'info')
      manualAddNumber.value = ''
      return
    }
    manualAddLoading.value = true
    try {
      const note = manualAddNote.value.trim()
      const assignee_id = manualAddAssigneeId.value
      const item: any = await api('/api/watchlist/add-by-number', {
        method: 'POST',
        body: JSON.stringify({ number: num, note, assignee_id }),
      }, { timeout: 30000 })
      const key = _watchKey(item.number, item.item_type)
      watchlistSet.value.add(key)
      watchlist.value.unshift(item)

      if (manualAddLinkTaskMode.value === 'existing' && manualAddSelectedTaskId.value) {
        await api('/api/personal-todo/link-to-watchlist', {
          method: 'POST',
          body: JSON.stringify({
            watchlist_item_type: item.item_type,
            watchlist_number: item.number,
            watchlist_title: item.title || '',
            task_id: manualAddSelectedTaskId.value,
          }),
        })
      } else if (manualAddLinkTaskMode.value === 'new' && manualAddNewTaskTitle.value.trim()) {
        await api('/api/personal-todo/link-to-watchlist', {
          method: 'POST',
          body: JSON.stringify({
            watchlist_item_type: item.item_type,
            watchlist_number: item.number,
            watchlist_title: item.title || '',
            new_task_title: manualAddNewTaskTitle.value.trim(),
            new_task_source: manualAddNewTaskSource.value || 'self',
          }),
        })
      }
      await loadWatchlist()
      useAppStore().showToast('已加入关注', `#${num} 已加入特别关注`, 'success')
      manualAddNumber.value = ''
      manualAddNote.value = ''
      manualAddAssigneeId.value = null
      manualAddLinkTaskMode.value = 'none'
      manualAddTaskSearchQuery.value = ''
      manualAddTaskSearchResults.value = []
      manualAddSelectedTaskId.value = null
      manualAddNewTaskTitle.value = ''
      manualAddNewTaskPriority.value = 'P2'
      manualAddNewTaskSource.value = 'self'
      manualAddSelectedTaskTitle.value = ''
      watchlistTab.value = item.item_type
    } catch (e: any) {
      useAppStore().showToast('添加失败', e.message, 'error')
    } finally {
      manualAddLoading.value = false
      showAddModal.value = false
    }
  }

  function openAddModal() {
    showAddModal.value = true
    loadManualAddTaskList()
  }

  function closeAddModal() {
    showAddModal.value = false
  }

  async function loadManualAddTaskList() {
    manualAddTaskSearchLoading.value = true
    try {
      const data: any = await api('/api/personal-todo/tasks?per_page=50&status=all')
      manualAddTaskSearchResults.value = data.tasks || []
    } catch (e: any) {
      useAppStore().showToast('加载任务列表失败', e.message, 'error')
    } finally {
      manualAddTaskSearchLoading.value = false
    }
  }

  function selectManualAddTask(task: any) {
    manualAddSelectedTaskId.value = task.id
    manualAddSelectedTaskTitle.value = task.title
    manualAddTaskSearchQuery.value = ''
    manualAddTaskSearchResults.value = []
  }

  // Edit modal
  function openEditModal(w: WatchlistItem) {
    editingWatchlistItem.value = w
    watchlistEditNote.value = w.note || ''
    watchlistEditAssigneeId.value = w.assignee_id || null
    watchlistEditLinkTaskId.value = ''
    watchlistEditSelectedTasks.value = []
    watchlistEditShowCreate.value = false
    watchlistEditNewTaskTitle.value = ''
    watchlistEditNewTaskSource.value = 'self'
    watchlistEditNewTaskPriority.value = 'P2'
    showEditModal.value = true
    _loadWatchlistEditTaskList()
  }

  function closeEditModal() {
    showEditModal.value = false
    editingWatchlistItem.value = null
    watchlistEditNote.value = ''
    watchlistEditAssigneeId.value = null
    watchlistEditTaskList.value = []
    watchlistEditLinkTaskId.value = ''
    watchlistEditSelectedTasks.value = []
    watchlistEditShowCreate.value = false
    watchlistEditNewTaskTitle.value = ''
  }

  function watchlistEditAddTask() {
    const id = watchlistEditLinkTaskId.value
    if (!id) return
    if (id === '__new__') {
      watchlistEditShowCreate.value = true
      watchlistEditLinkTaskId.value = ''
      return
    }
    if (watchlistEditSelectedTasks.value.some(t => t.id === parseInt(id, 10))) return
    const task = watchlistEditTaskList.value.find(t => t.id === parseInt(id, 10))
    if (task) watchlistEditSelectedTasks.value.push(task)
    watchlistEditLinkTaskId.value = ''
  }

  function watchlistEditRemoveTask(taskId: number) {
    watchlistEditSelectedTasks.value = watchlistEditSelectedTasks.value.filter(t => t.id !== taskId)
  }

  async function _loadWatchlistEditTaskList() {
    try {
      const data: any = await api('/api/personal-todo/tasks?per_page=50&status=all')
      watchlistEditTaskList.value = data.tasks || []
    } catch (_) {}
  }

  async function saveWatchlistItem() {
    if (!editingWatchlistItem.value || watchlistEditSaving.value) return
    const w = editingWatchlistItem.value
    const note = watchlistEditNote.value.trim()
    const assignee_id = watchlistEditAssigneeId.value
    watchlistEditSaving.value = true
    try {
      const updated: any = await api(`/api/watchlist/${w.item_type}/${w.number}/note`, {
        method: 'PUT',
        body: JSON.stringify({ note, assignee_id }),
      })
      w.note = updated.note
      w.assignee_id = updated.assignee_id
      const idx = watchlist.value.findIndex(i => i.number === w.number && i.item_type === w.item_type)
      if (idx !== -1) {
        watchlist.value[idx].note = updated.note
        watchlist.value[idx].assignee_id = updated.assignee_id
      }
      for (const t of watchlistEditSelectedTasks.value) {
        await api('/api/personal-todo/link-to-watchlist', {
          method: 'POST',
          body: JSON.stringify({
            watchlist_item_type: w.item_type,
            watchlist_number: w.number,
            watchlist_title: w.title || '',
            task_id: t.id,
          }),
        })
      }
      await loadWatchlist()
      useAppStore().showToast('关注信息已保存', '', 'success')
      closeEditModal()
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    } finally {
      watchlistEditSaving.value = false
    }
  }

  async function saveWatchlistItemAndCreateTask() {
    if (!editingWatchlistItem.value || !watchlistEditNewTaskTitle.value.trim() || watchlistEditSaving.value) return
    const w = editingWatchlistItem.value
    const note = watchlistEditNote.value.trim()
    const assignee_id = watchlistEditAssigneeId.value
    watchlistEditSaving.value = true
    try {
      await api(`/api/watchlist/${w.item_type}/${w.number}/note`, {
        method: 'PUT',
        body: JSON.stringify({ note, assignee_id }),
      })
      await api('/api/personal-todo/link-to-watchlist', {
        method: 'POST',
        body: JSON.stringify({
          watchlist_item_type: w.item_type,
          watchlist_number: w.number,
          watchlist_title: w.title || '',
          new_task_title: watchlistEditNewTaskTitle.value.trim(),
          new_task_source: watchlistEditNewTaskSource.value,
        }),
      })
      await loadWatchlist()
      useAppStore().showToast('已保存并创建任务', '', 'success')
      closeEditModal()
    } catch (e: any) {
      useAppStore().showToast('操作失败', e.message, 'error')
    } finally {
      watchlistEditSaving.value = false
    }
  }

  function openWatchlistPR(w: WatchlistItem) {
    // This is used from community view - will be wired up via the PRCenter store
  }

  return {
    watchlist, watchlistSet, watchlistTab, watchlistAssigneeFilter, filteredWatchlist,
    showAddModal, manualAddType, manualAddNumber, manualAddLoading,
    manualAddNote, manualAddAssigneeId, manualAddLinkTaskMode,
    manualAddTaskSearchQuery, manualAddTaskSearchResults, manualAddTaskSearchLoading,
    manualAddTaskOpen, manualAddNewTaskTitle, manualAddNewTaskPriority,
    manualAddNewTaskSource, manualAddSelectedTaskId, manualAddSelectedTaskTitle,
    showEditModal, editingWatchlistItem, watchlistEditNote, watchlistEditAssigneeId,
    watchlistEditSaving, watchlistEditTaskList, watchlistEditLinkTaskId,
    watchlistEditSelectedTasks, watchlistEditShowCreate, watchlistEditNewTaskTitle,
    watchlistEditNewTaskSource, watchlistEditNewTaskPriority,
    isWatched, findWatchlistItem, loadWatchlist, toggleWatch,
    addWatchlistByNumber, openAddModal, closeAddModal, loadManualAddTaskList,
    selectManualAddTask,
    openEditModal, closeEditModal, watchlistEditAddTask, watchlistEditRemoveTask,
    saveWatchlistItem, saveWatchlistItemAndCreateTask, openWatchlistPR,
  }
})