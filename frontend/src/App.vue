<script setup lang="ts">
import { onMounted, watch, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { useWatchlistStore } from '@/stores/watchlist'
import { useKeyboard } from '@/composables/useKeyboard'
import AuthScreen from '@/components/auth/AuthScreen.vue'
import AppShell from '@/components/layout/AppShell.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import LoadingBar from '@/components/common/LoadingBar.vue'

const authStore = useAuthStore()
const appStore = useAppStore()
const usersStore = useUsersStore()
const watchlistStore = useWatchlistStore()
const router = useRouter()

useKeyboard()

const initialized = ref(false)

onMounted(async () => {
  await authStore.init()
  if (authStore.authenticated) {
    await startApp()
  }
  initialized.value = true

  // Sync tick: every 30s refresh sync status, every 5min silent refresh
  let tickCount = 0
  setInterval(() => {
    tickCount++
    appStore.nowTick = Date.now()
    appStore.loadSyncStatus()
    if (tickCount % 10 === 0) {
      appStore.silentRefresh()
    }
  }, 30000)
  setInterval(() => {
    appStore.nowTick = Date.now()
  }, 1000)
})

async function startApp() {
  try {
    await Promise.all([
      appStore.loadAreas(),
      appStore.loadSyncStatus(),
      watchlistStore.loadWatchlist(),
      usersStore.loadUsers(),
    ])
    appStore.lastSync = new Date().toISOString()
  } catch (e: any) {
    appStore.showToast('初始化失败', e.message || String(e), 'error')
  } finally {
    appStore.hideLoading()
  }
}

// Watch for auth state changes
watch(() => authStore.authenticated, async (val) => {
  if (val) {
    await startApp()
    if (router.currentRoute.value.path === '/' || router.currentRoute.value.path === '/login') {
      router.push({ name: 'community' })
    }
  }
})
</script>

<template>
  <!-- Loading bar -->
  <LoadingBar :visible="appStore.loading" />

  <!-- Auth screen (not authenticated) -->
  <AuthScreen v-if="initialized && !authStore.authenticated" />

  <!-- Main app (authenticated) -->
  <AppShell v-if="authStore.authenticated" />

  <!-- Toast container -->
  <ToastContainer />

  <!-- Confirm dialog -->
  <ConfirmDialog />

  <!-- User Manager Modal -->
  <Teleport to="body">
    <div v-if="usersStore.showUserManager" class="modal-backdrop" @click="usersStore.closeManager()">
      <div class="modal modal-lg" @click.stop>
        <div class="modal-header">
          <h3>用户管理</h3>
          <button class="btn btn-sm btn-ghost" @click="usersStore.closeManager()">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-row" style="margin-bottom:var(--space-5)">
            <div class="field" style="flex:1">
              <label class="form-label">显示名称</label>
              <input type="text" class="input" v-model="usersStore.userForm.name" placeholder="姓名" />
            </div>
            <div class="field" style="flex:1">
              <label class="form-label">GitHub 登录名</label>
              <input type="text" class="input input-mono" v-model="usersStore.userForm.github_id" placeholder="GitHub 用户名" />
            </div>
            <div class="field" style="flex:0 0 auto;align-self:flex-end">
              <button class="btn btn-primary" :disabled="usersStore.userSaving || !usersStore.userForm.name.trim()"
                      @click="usersStore.saveUser()">
                {{ usersStore.userFormMode === 'create' ? '添加' : '保存' }}
              </button>
            </div>
          </div>
          <div class="list">
            <div v-for="user in usersStore.users" :key="user.id" class="list-item">
              <div class="item-main">
                <span class="item-title">{{ user.name }}</span>
                <div class="item-meta">
                  <span v-if="user.github_id">@{{ user.github_id }}</span>
                </div>
              </div>
              <div class="item-side">
                <button class="btn btn-sm" @click="usersStore.openEditUser(user)">编辑</button>
                <button class="btn btn-sm btn-ghost" @click="usersStore.deleteUser(user)">删除</button>
              </div>
            </div>
            <div v-if="usersStore.users.length === 0" class="empty-state">
              <p>暂无用户</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>