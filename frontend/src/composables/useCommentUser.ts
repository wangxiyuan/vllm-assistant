import { ref, watch } from 'vue'
import { useUsersStore } from '@/stores/users'

const STORAGE_KEY = 'comment_user_id'

const selectedUserId = ref<number | null>(null)

let initialized = false

function ensureInit() {
  if (initialized) return
  initialized = true
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) selectedUserId.value = parseInt(saved, 10)
  watch(selectedUserId, (val) => {
    if (val !== null) {
      localStorage.setItem(STORAGE_KEY, String(val))
    }
  })
}

export function useCommentUser() {
  ensureInit()
  const usersStore = useUsersStore()

  function pickUser() {
    usersStore.loadUsers()
  }

  function setUser(id: number) {
    selectedUserId.value = id
  }

  function resetUser() {
    selectedUserId.value = null
  }

  return {
    selectedUserId,
    pickUser,
    setUser,
    resetUser,
  }
}