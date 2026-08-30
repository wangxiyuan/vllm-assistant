<script setup lang="ts">
import { onMounted, watch, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { useReposStore } from '@/stores/repos'
import { useSlackStore } from '@/stores/slack'
import type { SlackChannel } from '@/stores/slack'
import { useWatchlistStore } from '@/stores/watchlist'
import { useRulesStore } from '@/stores/rules'
import { useKeyboard } from '@/composables/useKeyboard'
import AuthScreen from '@/components/auth/AuthScreen.vue'
import AppShell from '@/components/layout/AppShell.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import LoadingBar from '@/components/common/LoadingBar.vue'
import RulesManagerModal from '@/components/common/RulesManagerModal.vue'

const authStore = useAuthStore()
const appStore = useAppStore()
const usersStore = useUsersStore()
const reposStore = useReposStore()
const slackStore = useSlackStore()
const watchlistStore = useWatchlistStore()
const rulesStore = useRulesStore()
const router = useRouter()

useKeyboard()

const showSlackDropdown = ref(false)
const showCredGuide = ref(false)
const highlightedSlackIdx = ref(0)
const slackSearchInput = ref('')
const slackInputRef = ref<HTMLInputElement | null>(null)
const slackDropdownStyle = ref({})

const filteredSlackChannels = computed(() => {
  const query = slackSearchInput.value.replace(/^#/, '').toLowerCase()
  if (!query) return slackStore.getAvailableNotConfigured().slice(0, 50)
  return slackStore.getAvailableNotConfigured().filter(ch =>
    ch.name.toLowerCase().includes(query) || ch.topic.toLowerCase().includes(query)
  ).slice(0, 50)
})

function updateSlackDropdownPosition() {
  slackDropdownStyle.value = {}
}

function onSlackSearchInput() {
  slackSearchInput.value = slackStore.newChannel.replace(/^#/, '')
  showSlackDropdown.value = true
  highlightedSlackIdx.value = 0
  updateSlackDropdownPosition()
}

function onSlackSearchFocus() {
  if (slackStore.availableChannels.length) {
    slackSearchInput.value = slackStore.newChannel.replace(/^#/, '')
    showSlackDropdown.value = true
    updateSlackDropdownPosition()
  }
}

function onSlackDropdownSelect() {
  if (filteredSlackChannels.value[highlightedSlackIdx.value]) {
    selectSlackChannel(filteredSlackChannels.value[highlightedSlackIdx.value])
  }
}

function selectSlackChannel(ch: SlackChannel) {
  slackStore.newChannel = `#${ch.name}`
  showSlackDropdown.value = false
  slackStore.addChannel()
}

function onSlackSearchBlur() {
  setTimeout(() => { showSlackDropdown.value = false }, 200)
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    appStore.showToast('已复制', '', 'success')
  }).catch(() => {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    appStore.showToast('已复制', '', 'success')
  })
}

function copySubmitScript() {
  const script = `(async()=>{try{const teams=JSON.parse(localStorage.localConfig_v2||localStorage.localConfig||'{}').teams||{};const m=document.location.pathname.match(/^\\/client\\/([A-Z0-9]+)/);const teamId=m?m[1]:Object.keys(teams)[0];const token=teamId?teams[teamId]?.token||teams[teamId]:'';if(!token)return alert('no token found');copy(token);alert('xoxc token \\u5df2\\u590d\\u5236\\uff01\\n\\n\\u4e0b\\u4e00\\u6b65\\uff1a\\u624b\\u52a8\\u590d\\u5236 d cookie\\nF12 \\u2192 Application \\u2192 Cookies \\u2192 slack.com\\n\\u627e\\u5230 d \\u884c\\uff0c\\u590d\\u5236 Value \\u5217\\u7684\\u503c')}catch(e){alert('\\u5931\\u8d25:'+e.message)}})();`
  copyText(script)
}

function commitUrl(repo: any): string {
  const m = repo.clone_url.match(/github\.com[\/:]([^\/]+)\/([^\/\.]+)/)
  if (!m || !repo.commit_sha) return '#'
  return `https://github.com/${m[1]}/${m[2]}/commit/${repo.commit_sha}`
}
function openCommitUrl(repo: any) {
  window.open(commitUrl(repo), '_blank')
}

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
      // 等待初始路由解析完成：否则 currentRoute 还是初始 '/'，
      // 直接访问 /npu-services 等子路由会被误跳到总览页
      await router.isReady()
      const path = router.currentRoute.value.path
      if (path === '/' || path === '/login') {
        router.push({ name: 'overview' })
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
                <div class="item-meta-url">{{ repo.clone_url }}</div>
                <div class="item-meta">
                  <span class="item-meta-tag">分支: {{ repo.branch || 'main' }}</span>
                  <span v-if="repo.commit_sha" class="commit-link" @click="openCommitUrl(repo)">{{ repo.commit_sha.slice(0, 7) }}</span>
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

  <!-- Slack Manager Modal -->
  <Teleport to="body">
    <div v-if="slackStore.showManager" class="modal-backdrop" @click="slackStore.closeManager()">
      <div class="modal modal-xl" @click.stop style="overflow:visible;">
        <div class="modal-header">
          <h3>Slack 配置</h3>
          <button class="modal-close" @click="slackStore.closeManager()" title="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body" style="overflow:visible;padding:var(--space-5) var(--space-6);position:relative;">
          <div v-if="slackStore.configLoading || slackStore.channelsLoading" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:var(--bg-elev-1);border-radius:var(--radius-lg);z-index:10;gap:12px;">
            <div class="spinner" style="width:28px;height:28px;border:3px solid var(--border-faint);border-top-color:var(--accent);border-radius:50%;animation:spin 0.7s linear infinite;"></div>
            <span style="font-size:var(--text-sm);color:var(--text-secondary);">正在加载 Slack 配置...</span>
          </div>
          <div style="display:flex;gap:var(--space-6);">
            <!-- 左列：凭证配置 -->
            <div style="flex:1;min-width:0;">
              <!-- 凭证状态 -->
              <div style="margin-bottom:var(--space-4);">
                <label class="form-label">凭证状态</label>
                <div style="display:flex;align-items:center;gap:8px;margin-top:4px;flex-wrap:wrap;">
                  <span v-if="!slackStore.config?.cred_exists" class="badge badge-warning">未配置</span>
                  <template v-else>
                    <span v-if="slackStore.status?.cred_valid" class="badge badge-success">有效</span>
                    <span v-else class="badge badge-danger">已过期</span>
                  </template>
                </div>
              </div>

              <!-- Token / Cookie -->
              <div style="margin-bottom:var(--space-3);">
                <div class="form-row" style="gap:8px;align-items:flex-end;flex-wrap:nowrap;">
                  <div class="field" style="flex:1;">
                    <label class="form-label">xoxc token</label>
                    <input type="text" class="input input-mono" v-model="slackStore.tokenInput" placeholder="xoxc-..." />
                  </div>
                  <div class="field" style="flex:1;">
                    <label class="form-label">xoxd cookie</label>
                    <input type="text" class="input input-mono" v-model="slackStore.cookieInput" placeholder="xoxd-..." />
                  </div>
                  <div class="field" style="flex:0 0 auto;">
                    <label class="form-label" style="visibility:hidden;">测试</label>
                    <div style="display:flex;gap:6px;">
                      <button class="btn" :disabled="slackStore.testing" @click="slackStore.testAuth()">
                        {{ slackStore.testing ? '测试中...' : '测试凭证' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 获取凭证指引（默认折叠） -->
              <div class="slack-cred-guide" style="margin-bottom:var(--space-4);">
                <div @click="showCredGuide = !showCredGuide" style="display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;margin-bottom:4px;">
                  <span style="font-weight:600;font-size:var(--text-sm);">获取凭证</span>
                  <span style="font-size:11px;color:var(--text-tertiary);">（自动刷新失败时使用）</span>
                  <span style="margin-left:auto;font-size:11px;color:var(--text-tertiary);">{{ showCredGuide ? '收起' : '展开' }}</span>
                </div>
                <div v-if="showCredGuide" style="padding:10px 12px;background:var(--bg-primary);border-radius:6px;border:1px solid var(--border-faint);">
                  <div style="font-size:var(--text-sm);color:var(--text-secondary);margin-bottom:8px;line-height:1.6;">
                    <div><b>Step 1</b> - 获取 xoxc token：</div>
                    <div style="margin-left:12px;">Slack 页面 → F12 → Console → 点击下方按钮 → 粘贴到 Console 回车执行</div>
                  </div>
                  <button class="btn" @click="copySubmitScript()" style="width:100%;margin-bottom:10px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    复制提取 token 脚本 → 粘贴到 Slack Console
                  </button>
                  <div style="font-size:var(--text-sm);color:var(--text-secondary);margin-bottom:8px;line-height:1.6;">
                    <div><b>Step 2</b> - 获取 xoxd cookie：</div>
                    <div style="margin-left:12px;">F12 → Application → Cookies → slack.com → 复制 <code style="font-size:11px;padding:1px 4px;background:var(--bg-secondary);border-radius:3px;">d</code> 的 Value</div>
                  </div>
                  <div style="font-size:var(--text-sm);color:var(--text-secondary);margin-bottom:8px;line-height:1.6;">
                    <div><b>Step 3</b> - 粘贴到上方输入框，点击"测试凭证"验证</div>
                  </div>
                </div>
              </div>

              <!-- 采集间隔 + 回溯范围 -->
              <div style="margin-bottom:var(--space-4);display:flex;gap:12px;">
                <div>
                  <label class="form-label">采集间隔</label>
                  <div style="display:flex;align-items:center;gap:4px;margin-top:4px;">
                    <input type="number" class="input" v-model.number="slackStore.collectInterval" min="30" style="width:80px;" />
                    <span style="font-size:var(--text-sm);color:var(--text-tertiary);">分钟</span>
                  </div>
                </div>
                <div>
                  <label class="form-label">回溯范围</label>
                  <div style="display:flex;align-items:center;gap:4px;margin-top:4px;">
                    <input type="number" class="input" v-model.number="slackStore.collectLookback" min="30" style="width:80px;" />
                    <span style="font-size:var(--text-sm);color:var(--text-tertiary);">分钟</span>
                  </div>
                </div>
              </div>

              <!-- 状态信息 -->
              <div v-if="slackStore.status" style="margin-bottom:var(--space-4);padding:12px;background:var(--bg-secondary);border-radius:6px;">
                <div style="display:flex;gap:24px;">
                  <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:var(--text-sm);color:var(--text-tertiary);">上次采集</span>
                    <span style="font-size:var(--text-sm);">{{ slackStore.status.last_collect_at ? new Date(slackStore.status.last_collect_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '尚未采集' }}</span>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:var(--text-sm);color:var(--text-tertiary);">消息总数</span>
                    <span style="font-size:var(--text-sm);">{{ slackStore.status.total_messages }}</span>
                  </div>
                </div>
                <div v-if="slackStore.status.last_refresh_at" style="margin-top:6px;display:flex;align-items:center;gap:8px;">
                  <span style="font-size:var(--text-sm);color:var(--text-tertiary);">最近刷新</span>
                  <span style="font-size:var(--text-sm);">{{ new Date(slackStore.status.last_refresh_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}</span>
                </div>
                <div v-if="slackStore.config?.cred_exists && slackStore.status?.cred_valid === false" style="margin-top:8px;padding:6px 10px;background:var(--signal-red-glow);border-radius:4px;font-size:var(--text-sm);color:var(--signal-red);">
                  凭证已过期，采集将无法执行。请按上方指引重新获取 token 和 cookie。
                </div>
              </div>

              <!-- 操作按钮 -->
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button class="btn btn-primary" :disabled="slackStore.saving" @click="slackStore.saveConfig()">
                  {{ slackStore.saving ? '保存中...' : '保存配置' }}
                </button>
                <button class="btn" :disabled="slackStore.refreshing" @click="slackStore.refreshToken()">
                  {{ slackStore.refreshing ? '刷新中...' : '手动刷新凭证' }}
                </button>
                <button class="btn" :disabled="slackStore.collecting" @click="slackStore.triggerCollect()">
                  {{ slackStore.collecting ? '采集中...' : '手动采集' }}
                </button>
                <button class="btn btn-danger" @click="slackStore.clearData()">清除数据</button>
              </div>
            </div>

            <!-- 右列：频道管理 -->
            <div style="flex:1;min-width:0;display:flex;flex-direction:column;">
              <!-- 频道列表 -->
              <div style="margin-bottom:var(--space-3);">
                <label class="form-label">频道列表</label>
                <div class="list" style="margin-top:4px;max-height:240px;overflow-y:auto;">
                  <div v-for="ch in slackStore.config?.channels || []" :key="ch" class="list-item" style="padding:6px 8px;">
                    <div class="item-main">
                      <span class="item-title" style="font-family:var(--font-mono);font-size:var(--text-sm);">{{ ch }}</span>
                    </div>
                    <div class="item-side">
                      <button class="card-action-btn is-danger" @click="slackStore.removeChannel(ch)" title="移除">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        移除
                      </button>
                    </div>
                  </div>
                  <div v-if="(slackStore.config?.channels?.length || 0) === 0" class="empty-state is-compact" style="padding:12px;">
                    <p>暂无频道，请从下方列表选择添加</p>
                  </div>
                </div>
              </div>

              <!-- 从频道列表选择添加 -->
              <div style="flex:1;">
                <label class="form-label">从已有频道添加</label>
                <div v-if="slackStore.channelsLoading" style="margin-top:4px;font-size:var(--text-sm);color:var(--text-tertiary);">加载频道列表中...</div>
                <div v-else-if="slackStore.availableChannels.length === 0" style="margin-top:4px;font-size:var(--text-sm);color:var(--text-tertiary);">无法获取频道列表（凭证可能未配置）</div>
                <div v-else style="position:relative;margin-top:4px;">
                  <div style="display:flex;gap:8px;">
                    <input type="text" class="input input-mono"
                           ref="slackInputRef"
                           v-model="slackStore.newChannel"
                           :placeholder="`搜索 ${slackStore.getAvailableNotConfigured().length} 个可用频道...`"
                           @input="onSlackSearchInput()"
                           @focus="onSlackSearchFocus()"
                           @blur="onSlackSearchBlur()"
                           @keydown.escape="showSlackDropdown = false"
                           @keydown.enter.prevent="onSlackDropdownSelect()"
                           style="flex:1;" />
                    <button class="btn btn-primary" :disabled="!slackStore.newChannel.trim() || !slackStore.newChannel.trim().startsWith('#')" @click="slackStore.addChannel()">添加</button>
                  </div>
                  <div v-if="showSlackDropdown && filteredSlackChannels.length" class="slack-channel-dropdown" :style="slackDropdownStyle">
                    <div v-for="ch in filteredSlackChannels" :key="ch.id"
                         class="slack-channel-option"
                         :class="{ highlighted: highlightedSlackIdx === filteredSlackChannels.indexOf(ch) }"
                         @mousedown.prevent="selectSlackChannel(ch)"
                         @mouseenter="highlightedSlackIdx = filteredSlackChannels.indexOf(ch)">
                      <span class="slack-channel-name">#{{ ch.name }}</span>
                      <span class="slack-channel-meta">{{ ch.num_members }} 人</span>
                      <span v-if="ch.topic" class="slack-channel-topic">{{ ch.topic }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- AI Rules Manager Modal -->
  <RulesManagerModal />
</template>

<style>
.item-meta-url {
  font-size: var(--text-sm);
  font-family: var(--font-mono);
  color: var(--text-tertiary);
  word-break: break-all;
  margin-top: var(--space-1);
  line-height: 1.4;
}
.commit-link {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--primary);
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: var(--primary-glow);
  text-underline-offset: 2px;
  transition: opacity var(--t-fast);
}
.commit-link:hover {
  opacity: 0.75;
}

.slack-channel-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  max-height: 300px;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15);
  z-index: 100;
  min-width: 280px;
}
.slack-channel-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: var(--text-sm);
  border-bottom: 1px solid var(--border-faint);
  background: var(--bg-primary);
}
.slack-channel-option:last-child {
  border-bottom: none;
}
.slack-channel-option:hover,
.slack-channel-option.highlighted {
  background: var(--hover-bg);
}
.slack-channel-name {
  font-family: var(--font-mono);
  font-weight: 500;
  flex-shrink: 0;
}
.slack-channel-meta {
  color: var(--text-tertiary);
  font-size: 11px;
  flex-shrink: 0;
}
.slack-channel-topic {
  color: var(--text-tertiary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.slack-cred-guide {
  margin-bottom: var(--space-4);
  padding: 10px 12px;
  background: var(--bg-secondary);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>