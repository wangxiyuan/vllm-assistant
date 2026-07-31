import { onMounted, onUnmounted } from 'vue'
import { usePRCenterStore } from '@/stores/prCenter'
import { useTodoStore } from '@/stores/todo'
import { useIntelStore } from '@/stores/intel'
import { useArticlesStore } from '@/stores/articles'
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
      searchInput?.focus()
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
    const todoStore = useTodoStore()
    const intelStore = useIntelStore()
    const articlesStore = useArticlesStore()
    const anatomyStore = useAnatomyStore()
    const watchlistStore = useWatchlistStore()
    const usersStore = useUsersStore()
    const aiAgentStore = useAIAgentStore()

    // 1. Article preview
    if (articlesStore.editorSubView === 'preview' && articlesStore.editorOpen) {
      articlesStore.closePreview()
      return
    }
    // 2. Code ref modal
    if (articlesStore.showInsertRef) {
      articlesStore.closeInsertRef()
      return
    }
    // 3. Article detail
    if (articlesStore.selectedArticle) {
      articlesStore.closeArticleView()
      return
    }
    // 4. Article editor
    if (articlesStore.editorOpen) {
      articlesStore.closeEditor()
      return
    }
    // 5. PR drawer
    if (prStore.selectedPR) {
      prStore.closePR()
      return
    }
    // 6. Issue drawer
    if (prStore.selectedIssue) {
      prStore.closeIssue()
      return
    }
    // 7. Task drawer
    if (todoStore.selectedTask) {
      todoStore.closeTask()
      return
    }
    // 8. Report modal
    if (intelStore.selectedReport) {
      intelStore.closeReport()
      return
    }
    // 9. Modals
    if (todoStore.showAddModal) { todoStore.showAddModal = false; return }
    if (intelStore.showModal) { intelStore.showModal = false; return }
    if (watchlistStore.showAddModal) { watchlistStore.closeAddModal(); return }
    if (watchlistStore.showEditModal) { watchlistStore.closeEditModal(); return }
    if (usersStore.showUserManager) { usersStore.closeManager(); return }
    if (anatomyStore.showOperatorEditor) { anatomyStore.closeOperatorEditor(); return }
    if (anatomyStore.showModelEditor) { anatomyStore.closeModelEditor(); return }
    if (anatomyStore.showCategoryManager) { anatomyStore.showCategoryManager = false; return }
    if (anatomyStore.showOperatorDetail) { anatomyStore.closeOperatorDetail(); return }
    if (anatomyStore.showModelDetail) { anatomyStore.closeModelDetail(); return }
    // 10. Mobile sidebar
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