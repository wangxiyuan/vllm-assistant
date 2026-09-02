import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePRCenterStore } from '@/stores/prCenter'
import { useIntelStore } from '@/stores/intel'
import { useAnatomyStore } from '@/stores/anatomy'
import { useWatchlistStore } from '@/stores/watchlist'
import { useUsersStore } from '@/stores/users'
import { useAIAgentStore } from '@/stores/aiAgent'
import { useAppStore } from '@/stores/app'

export function useKeyboard() {
  function handleKeydown(e: KeyboardEvent) {
    const tag = (e.target as HTMLElement).tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
    if ((e.target as HTMLElement).closest?.('[contenteditable="true"]')) return
    if ((e.target as HTMLElement).isContentEditable) return
    if (e.metaKey || e.ctrlKey || e.altKey) return

    // / key to focus search
    if (e.key === '/') {
      e.preventDefault()
      const searchInput = document.querySelector('.search-bar input') as HTMLInputElement
      if (searchInput) {
        searchInput.focus()
      }
      return
    }

    // Number keys 1-8: navigate to views (matches sidebar kbd badges)
    const viewByKey: Record<string, string> = {
      '1': 'overview',
      '2': 'intelligence',
      '3': 'anatomy',
      '4': 'ai-agent',
      '5': 'npu-machines',
      '6': 'npu-jobs',
      '7': 'npu-services',
      '8': 'npu-testing',
    }
    const routeName = viewByKey[e.key]
    if (routeName) {
      e.preventDefault()
      useRouter().push({ name: routeName })
      return
    }

    // R key: manual refresh (matches header refresh button tooltip)
    if (e.key.toLowerCase() === 'r') {
      const appStore = useAppStore()
      if (!appStore.loading) {
        e.preventDefault()
        appStore.refreshAll()
      }
      return
    }

    // Escape key for closing panels
    if (e.key === 'Escape') {
      handleGlobalEsc()
    }
  }

  function handleGlobalEsc() {
    const appStore = useAppStore()
    const prStore = usePRCenterStore()
    const intelStore = useIntelStore()
    const anatomyStore = useAnatomyStore()
    const watchlistStore = useWatchlistStore()
    const usersStore = useUsersStore()
    const aiAgentStore = useAIAgentStore()

    // 1. PR drawer
    if (prStore.selectedPR) {
      prStore.closePR()
      return
    }
    // 2. Issue drawer
    if (prStore.selectedIssue) {
      prStore.closeIssue()
      return
    }
    // 3. Report modal
    if (intelStore.selectedReport) {
      intelStore.closeReport()
      return
    }
    // 4. Modals
    if (intelStore.showModal) { intelStore.showModal = false; return }
    if (watchlistStore.showAddModal) { watchlistStore.closeAddModal(); return }
    if (watchlistStore.showEditModal) { watchlistStore.closeEditModal(); return }
    if (usersStore.showUserManager) { usersStore.closeManager(); return }
    if (anatomyStore.showBlockEditor) { anatomyStore.closeBlockEditor(); return }
    if (anatomyStore.showAssemblyEditor) { anatomyStore.closeAssemblyEditor(); return }
    if (anatomyStore.showYAMLImport) { anatomyStore.closeYAMLImport(); return }
    if (anatomyStore.showBlockDetail) { anatomyStore.closeBlockDetail(); return }
    if (anatomyStore.showAssemblyDetail) { anatomyStore.closeAssemblyDetail(); return }
    // 5. Mobile sidebar
    if (appStore.mobileMenuOpen) { appStore.mobileMenuOpen = false }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeydown)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeydown)
  })

  return { handleGlobalEsc }
}
