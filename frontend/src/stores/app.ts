import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { timeAgo, exactTime } from '@/utils/helpers'
import type { Toast, ConfirmOptions, ConfirmDialogState, Area } from '@/utils/types'

export const useAppStore = defineStore('app', () => {
  // Loading
  const loading = ref(false)
  function showLoading() { loading.value = true }
  function hideLoading() { loading.value = false }

  // Sidebar
  const sidebarCollapsed = ref(false)
  const mobileMenuOpen = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    document.documentElement.style.setProperty('--sidebar-w', sidebarCollapsed.value ? '60px' : '248px')
  }

  // Sync
  const syncStatus = ref<'idle' | 'syncing' | 'error'>('idle')
  const lastSync = ref<string | null>(null)
  const nextSync = ref<string | null>(null)
  const nowTick = ref(Date.now())

  const lastSyncAgo = computed(() => {
    if (!lastSync.value) return '从未同步'
    return '同步于 ' + timeAgo(lastSync.value)
  })

  const nextSyncCountdown = computed(() => {
    void nowTick.value
    if (!nextSync.value) return ''
    const target = new Date(nextSync.value).getTime()
    if (isNaN(target)) return ''
    const diff = target - Date.now()
    if (diff <= 0) return '即将同步'
    const totalSec = Math.floor(diff / 1000)
    const min = Math.floor(totalSec / 60)
    const sec = totalSec % 60
    if (min > 0) return `${min} 分 ${sec} 秒后`
    return `${sec} 秒后`
  })

  const syncStatusText = computed(() => {
    if (loading.value) return '同步中…'
    if (syncStatus.value === 'error') return '同步失败'
    if (lastSync.value) return '同步于 ' + exactTime(lastSync.value)
    return '空闲'
  })

  const syncStatusClass = computed(() => {
    if (loading.value || syncStatus.value === 'syncing') return 'syncing'
    if (syncStatus.value === 'error') return 'error'
    return ''
  })

  async function loadSyncStatus() {
    try {
      const status: any = await api('/api/status')
      if (status && status.jobs && status.jobs.length > 0) {
        const times = status.jobs
          .map((j: any) => j.next_run_time)
          .filter(Boolean)
          .sort()
        nextSync.value = times[0] || null
      }
    } catch (_) {}

    // 每秒更新 nowTick，让 nextSyncCountdown 实时刷新
    clearInterval((window as any).__syncTickInterval)
    if (nextSync.value) {
      ;(window as any).__syncTickInterval = setInterval(() => {
        nowTick.value = Date.now()
      }, 1000)
    }
  }

  // Toast
  const toasts = ref<Toast[]>([])
  let toastId = 0

  function showToast(title: string, msg = '', type: Toast['type'] = 'info', duration = 4000) {
    const id = ++toastId
    toasts.value.push({ id, title, msg, type })
    setTimeout(() => {
      toasts.value = toasts.value.filter(t => t.id !== id)
    }, duration)
  }

  function showUndoToast(title: string, msg: string, undoCallback: () => void, duration = 8000) {
    const id = ++toastId
    const timer = setTimeout(() => {
      toasts.value = toasts.value.filter(t => t.id !== id)
    }, duration)
    toasts.value.push({ id, title, msg, type: 'undo', undo: true, undoCallback, _timer: timer })
  }

  function executeUndo(id: number) {
    const toast = toasts.value.find(t => t.id === id)
    if (!toast) return
    if (toast.undoCallback) toast.undoCallback()
    if (toast._timer) clearTimeout(toast._timer)
    toasts.value = toasts.value.filter(t => t.id !== id)
    showToast('已撤销', '', 'success', 2000)
  }

  // Confirm
  const confirmDialog = ref<ConfirmDialogState>({
    show: false,
    title: '',
    message: '',
    confirmText: '确认',
    cancelText: '取消',
    danger: false,
    resolve: null,
    showKnowledgeSyncCheckbox: false,
    knowledgeSyncChecked: true,
  })

  function showConfirm(opts: ConfirmOptions = {}): Promise<{ confirmed: boolean; syncDeleteKnowledge: boolean }> {
    return new Promise((resolve) => {
      confirmDialog.value = {
        show: true,
        title: opts.title || '确认操作',
        message: opts.message || '',
        confirmText: opts.confirmText || '确认',
        cancelText: opts.cancelText || '取消',
        danger: opts.danger || false,
        resolve,
        showKnowledgeSyncCheckbox: opts.showKnowledgeSyncCheckbox || false,
        knowledgeSyncChecked: opts.knowledgeSyncChecked !== false,
      }
    })
  }

  function confirmOk() {
    const r = confirmDialog.value.resolve
    if (r) r({ confirmed: true, syncDeleteKnowledge: confirmDialog.value.knowledgeSyncChecked })
    confirmDialog.value.show = false
  }

  function confirmCancel() {
    const r = confirmDialog.value.resolve
    if (r) r({ confirmed: false, syncDeleteKnowledge: false })
    confirmDialog.value.show = false
  }

  // Areas
  const areas = ref<Area[]>([])

  async function loadAreas() {
    try {
      const data: any = await api('/api/community/areas')
      areas.value = data
    } catch (e: any) {
      showToast('加载领域失败', e.message, 'error')
    }
  }

  function areaName(areaId: string): string {
    if (!areaId) return ''
    const area = areas.value.find(a => a.id === areaId)
    return area ? area.name : areaId
  }

  // Refresh
  const _refreshing = ref(false)

  async function refreshAll() {
    if (_refreshing.value) return
    _refreshing.value = true
    syncStatus.value = 'syncing'
    showLoading()
    try {
      await api('/api/refresh', { method: 'POST' })
      showToast('已触发同步', '后台同步已启动，数据稍后将更新', 'success')
      setTimeout(async () => {
        try {
          await silentRefresh()
          lastSync.value = new Date().toISOString()
          syncStatus.value = 'idle'
          await loadSyncStatus()
        } catch (_) {
          syncStatus.value = 'error'
        } finally {
          hideLoading()
          _refreshing.value = false
        }
      }, 3000)
    } catch (e: any) {
      showToast('同步失败', e.message, 'error')
      syncStatus.value = 'error'
      hideLoading()
      _refreshing.value = false
    }
  }

  async function silentRefresh() {
    try {
      // Community data is refreshed via the community store
      // This will be wired up through the router view
      lastSync.value = new Date().toISOString()
    } catch (_) {}
  }

  // Search query (shared across views)
  const searchQuery = ref('')

  return {
    loading, showLoading, hideLoading,
    sidebarCollapsed, mobileMenuOpen, toggleSidebar,
    syncStatus, lastSync, nextSync, nowTick,
    lastSyncAgo, nextSyncCountdown, syncStatusText, syncStatusClass,
    loadSyncStatus,
    toasts, showToast, showUndoToast, executeUndo,
    confirmDialog, showConfirm, confirmOk, confirmCancel,
    areas, loadAreas, areaName,
    refreshAll, silentRefresh,
    searchQuery,
  }
})