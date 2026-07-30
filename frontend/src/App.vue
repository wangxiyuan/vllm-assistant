<script setup lang="ts">
import { onMounted, watch, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { useReposStore } from '@/stores/repos'
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
const reposStore = useReposStore()
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
      reposStore.loadRepos(),
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
          <button class="modal-close" @click="usersStore.closeManager()" title="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-row" style="margin-bottom:var(--space-5);align-items:flex-end;">
            <div class="field" style="flex:1">
              <label class="form-label">显示名称</label>
              <input type="text" class="input" v-model="usersStore.userForm.name" placeholder="姓名" />
            </div>
            <div class="field" style="flex:1">
              <label class="form-label">GitHub 登录名</label>
              <input type="text" class="input input-mono" v-model="usersStore.userForm.github_id" placeholder="GitHub 用户名" />
            </div>
            <div class="field" style="flex:0 0 auto;justify-content:flex-end;">
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
                <button class="card-action-btn" @click="usersStore.openEditUser(user)" title="编辑">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  编辑
                </button>
                <button class="card-action-btn is-danger" @click="usersStore.deleteUser(user)" title="删除">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  删除
                </button>
              </div>
            </div>
            <div v-if="usersStore.users.length === 0" class="empty-state is-compact">
              <p>暂无用户</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Repo Manager Modal -->
  <Teleport to="body">
    <div v-if="reposStore.showRepoManager" class="modal-backdrop" @click="reposStore.closeManager()">
      <div class="modal modal-lg" @click.stop>
        <div class="modal-header">
          <h3>仓库管理</h3>
          <button class="modal-close" @click="reposStore.closeManager()" title="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-row" style="margin-bottom:var(--space-5);align-items:flex-end;">
            <div class="field" style="flex:1">
              <label class="form-label">仓库名称</label>
              <input type="text" class="input input-mono" v-model="reposStore.repoForm.repo" placeholder="如 vllm、sglang" :disabled="reposStore.repoFormMode === 'edit'" />
            </div>
            <div class="field" style="flex:2">
              <label class="form-label">克隆地址</label>
              <input type="text" class="input input-mono" v-model="reposStore.repoForm.clone_url" placeholder="https://github.com/owner/repo.git" />
            </div>
            <div class="field" style="flex:0 0 120px">
              <label class="form-label">分支</label>
              <input type="text" class="input input-mono" v-model="reposStore.repoForm.branch" placeholder="main" />
            </div>
            <div class="field" style="flex:0 0 auto;justify-content:flex-end;">
              <button class="btn btn-primary" :disabled="reposStore.repoSaving || !reposStore.repoForm.repo.trim() || !reposStore.repoForm.clone_url.trim()"
                      @click="reposStore.saveRepo()">
                {{ reposStore.repoFormMode === 'create' ? '添加' : '保存' }}
              </button>
            </div>
          </div>
          <div class="form-row" style="margin-bottom:var(--space-5);">
            <label class="checkbox-label">
              <input type="checkbox" v-model="reposStore.repoForm.tracked" />
              追踪社区动态（同步该仓库的 issue/PR 到社区动态页）
            </label>
          </div>
          <div class="list">
            <div v-for="repo in reposStore.repos" :key="repo.id" class="list-item">
              <div class="item-main">
                <span class="item-title">{{ repo.repo }}</span>
                <div class="item-meta">
                  <span class="item-meta-tag">{{ repo.clone_url }}</span>
                  <span class="item-meta-tag">分支: {{ repo.branch || 'main' }}</span>
                  <span v-if="repo.last_synced_at" class="item-meta-tag">最后同步: {{ new Date(repo.last_synced_at).toLocaleString() }}</span>
                </div>
              </div>
              <div class="item-side">
                <button class="card-action-btn" :class="{ 'is-active': repo.tracked }"
                        @click="reposStore.toggleTrack(repo, !repo.tracked)" :title="repo.tracked ? '关闭追踪' : '开启追踪'">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  {{ repo.tracked ? '追踪中' : '追踪' }}
                </button>
                <button class="card-action-btn" @click="reposStore.openEditRepo(repo)" title="编辑">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  编辑
                </button>
                <button class="card-action-btn is-danger" @click="reposStore.deleteRepo(repo)" title="删除">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  删除
                </button>
              </div>
            </div>
            <div v-if="reposStore.repos.length === 0" class="empty-state is-compact">
              <p>暂无仓库</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>