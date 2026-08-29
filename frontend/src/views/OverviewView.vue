<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import ChatDrawer from '@/components/ai/ChatDrawer.vue'
import { useCommunityStore } from '@/stores/community'
import { useAppStore } from '@/stores/app'
import { usePRCenterStore } from '@/stores/prCenter'
import { useWatchlistStore } from '@/stores/watchlist'
import { useRulesStore } from '@/stores/rules'
import { useUsersStore } from '@/stores/users'
import { useReposStore } from '@/stores/repos'
import { useTodoStore } from '@/stores/todo'
import { issueType, issueTypeLabel, issueStateLabel, prStateLabel, timeAgo, exactTime, ghUrl, ghCommitUrl, ciLabel, ciBadgeClass } from '@/utils/helpers'
import type { Issue, PR } from '@/utils/types'
import Icon from '@/components/common/Icon.vue'
import FilterRow from '@/components/common/FilterRow.vue'
import PRDrawer from '@/components/common/PRDrawer.vue'
import IssueDrawer from '@/components/common/IssueDrawer.vue'
import TaskDrawer from '@/components/common/TaskDrawer.vue'
import WatchlistModals from '@/components/common/WatchlistModals.vue'
import { useCommentUser } from '@/composables/useCommentUser'

const communityStore = useCommunityStore()
const appStore = useAppStore()
const prStore = usePRCenterStore()
const watchlistStore = useWatchlistStore()
const rulesStore = useRulesStore()
const usersStore = useUsersStore()
const reposStore = useReposStore()
const todoStore = useTodoStore()
const { selectedUserId, setUser } = useCommentUser()

// ================= 左列：tab（AI 规则 + 社区动态） =================
const activeTab = ref<string>('')
const matchesLoaded = ref<Set<number>>(new Set())
const userSelectedTab = ref(false)

const ruleTabs = computed(() => rulesStore.enabledRules)

watch(ruleTabs, (tabs) => {
  const currentIsRule = activeTab.value.startsWith('rule:')
  const currentValid = currentIsRule && tabs.some(t => 'rule:' + t.id === activeTab.value)
  if (currentValid) return
  // 初始默认、规则首次到达、或选中的规则被删除/停用时：优先第一条规则
  if (!activeTab.value || !userSelectedTab.value || currentIsRule) {
    activeTab.value = tabs.length > 0 ? 'rule:' + tabs[0].id : 'community'
  }
}, { immediate: true })

watch(activeTab, (tab) => {
  if (tab.startsWith('rule:')) {
    const ruleId = parseInt(tab.slice(5), 10)
    markRuleViewed(ruleId)
    if (!matchesLoaded.value.has(ruleId)) {
      matchesLoaded.value.add(ruleId)
      rulesStore.loadMatches(ruleId)
    }
  }
})

function selectTab(key: string) {
  userSelectedTab.value = true
  activeTab.value = key
}

onMounted(() => {
  communityStore.loadAreas()
  rulesStore.loadRules()
})

const activeMatches = computed(() => {
  if (!activeTab.value.startsWith('rule:')) return []
  const ruleId = parseInt(activeTab.value.slice(5), 10)
  return rulesStore.matches[ruleId] || []
})

// 规则命中子 tab（全部/PR/Issue/Commit），切换规则时重置
const ruleMatchFilter = ref<'all' | 'pr' | 'issue' | 'commit'>('all')

watch(activeTab, () => {
  ruleMatchFilter.value = 'all'
})

const activeMatchCounts = computed(() => {
  const counts = { all: activeMatches.value.length, pr: 0, issue: 0, commit: 0 }
  for (const m of activeMatches.value) {
    const t = m.type as 'pr' | 'issue' | 'commit'
    if (t === 'pr' || t === 'issue' || t === 'commit') counts[t]++
  }
  return counts
})

const activeMatchesFiltered = computed(() => {
  if (ruleMatchFilter.value === 'all') return activeMatches.value
  return activeMatches.value.filter(m => m.type === ruleMatchFilter.value)
})

// ================= 规则命中"已读"标记（localStorage 记录每规则上次查看时间） =================
const RULE_LASTSEEN_KEY = 'rule-match-lastseen'
// 本轮渲染使用的"上次查看时间"快照：打开 tab 时先取旧值再写入当前时间，
// 这样本次浏览期间命中以旧值为准，下次打开才显示新的
const prevSeenAt = ref<Record<string, number>>({})

function loadLastSeenMap(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(RULE_LASTSEEN_KEY) || '{}')
  } catch (_) {
    return {}
  }
}

function markRuleViewed(ruleId: number) {
  const map = loadLastSeenMap()
  prevSeenAt.value[String(ruleId)] = map[String(ruleId)] || 0
  map[String(ruleId)] = Date.now()
  try {
    localStorage.setItem(RULE_LASTSEEN_KEY, JSON.stringify(map))
  } catch (_) {}
}

function isNewForUser(item: any): boolean {
  const last = prevSeenAt.value[String(activeRuleId.value ?? '')] ?? 0
  if (!item.matched_at) return false
  const matchedTs = new Date(item.matched_at).getTime()
  if (!last) {
    // 从未看过该规则：退化为服务端的 24 小时新增标识，避免首访满屏"新"
    return !!item.is_new
  }
  return matchedTs > last
}
const activeRuleRunning = computed(() => {
  if (!activeTab.value.startsWith('rule:')) return false
  const ruleId = parseInt(activeTab.value.slice(5), 10)
  return rulesStore.runningRuleIds.has(ruleId)
})
const activeRule = computed(() => {
  if (!activeTab.value.startsWith('rule:')) return null
  const ruleId = parseInt(activeTab.value.slice(5), 10)
  return rulesStore.rules.find(r => r.id === ruleId) || null
})
const activeRuleId = computed(() => activeTab.value.startsWith('rule:') ? parseInt(activeTab.value.slice(5), 10) : null)

function openMatchedItem(item: any) {
  if (item.type === 'commit') {
    window.open(ghCommitUrl(item.repo, item.sha), '_blank')
  } else if (item.type === 'pr') {
    prStore.openPR({ ...item, pr_number: item.number })
  } else {
    prStore.openIssue(item)
  }
}

function openCommit(commit: any) {
  window.open(ghCommitUrl(commit.repo, commit.sha), '_blank')
}

/** 从 commit 标题尾缀 "(#1234)" 解析关联 PR 号（GitHub merge commit 约定） */
function commitPrNumber(item: any): number | null {
  const m = /\(#(\d+)\)\s*$/.exec(item.title || item.subject || '')
  return m ? parseInt(m[1], 10) : null
}

function rerunActiveRule() {
  if (activeRule.value) rulesStore.runRule(activeRule.value.id, true)
}

// ================= 左列：社区动态 tab（原社区动态页能力） =================
const displayedItems = computed(() => {
  if (communityStore.communityTab === 'prs') return communityStore.pagedFilteredPRs
  if (communityStore.communityTab === 'commits') return communityStore.pagedFilteredCommits
  return communityStore.pagedFilteredIssues
})

function loadMore() {
  communityStore.communityPage++
}

function openPR(pr: PR) {
  prStore.openPR({ ...pr, pr_number: pr.number, repo: pr.repo })
}

function openIssue(issue: Issue) {
  prStore.openIssue(issue)
}

function toggleWatchlist(number: number, type: string, title: string, url: string, extra?: any) {
  watchlistStore.toggleWatch(number, type, title, url, extra)
}

function repoFullName(cloneUrl: string): string {
  let url = cloneUrl.endsWith('.git') ? cloneUrl.slice(0, -4) : cloneUrl
  url = url.replace(/\/+$/, '')
  const parts = url.split('/')
  if (parts.length >= 2) return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`
  return ''
}

function switchRepo(repo: string) {
  communityStore.communityRepo = repo
  communityStore.loadCommunityData()
}

// ================= 右栏：需要处理卡片 =================
const prCardMode = ref<'pending' | 'all'>('pending')

const pendingPRs = computed(() =>
  prStore.myPrs.filter(p =>
    p.state === 'open' &&
    (p.conflict_detected || p.ci_status === 'fail'),
  ),
)

function onContributorChange() {
  const val = prStore.selectedContributorGithubId
  if (val) {
    const user = usersStore.users.find(u => u.github_id === val)
    if (user) {
      prStore.selectedContributor = user as any
      setUser(user.id)
    }
  } else {
    prStore.selectedContributor = null
  }
  prStore.loadAllContribData()
}

onMounted(() => {
  if (selectedUserId.value !== null) {
    const user = usersStore.users.find(u => u.id === selectedUserId.value)
    if (user && user.github_id) {
      prStore.selectedContributorGithubId = user.github_id
      onContributorChange()
    }
  }
})

watch(selectedUserId, (id) => {
  if (id === null) {
    prStore.selectedContributorGithubId = ''
    onContributorChange()
    return
  }
  const user = usersStore.users.find(u => u.id === id)
  if (user && user.github_id && user.github_id !== prStore.selectedContributorGithubId) {
    prStore.selectedContributorGithubId = user.github_id
    onContributorChange()
  }
})

// ================= 右栏：我的关注卡片 =================
function openWatchlistItem(w: any) {
  if (w.item_type === 'pr') {
    prStore.openPR({ pr_number: w.number, title: w.title, url: w.url, state: w.state || 'open', repo: w.repo, watchlist_note: w.note || '', watchlist_assignee_id: w.assignee_id || null, linked_tasks: w.linked_tasks || [] })
  } else {
    prStore.openIssue({ number: w.number, title: w.title, url: w.url, state: w.state || 'open', repo: w.repo, watchlist_note: w.note || '', watchlist_assignee_id: w.assignee_id || null, linked_tasks: w.linked_tasks || [] })
  }
}

function openTaskDrawer(task: any) {
  todoStore.openTask({ id: task.id, title: task.title, status: task.status || 'todo', priority: task.priority || 'P2', source: 'self', created_at: '', updated_at: '' })
}

function watchlistChangeHint(w: any): string {
  if (!w.last_state_change_at) return ''
  const changed = new Date(w.last_state_change_at).getTime()
  return Date.now() - changed < 48 * 3600 * 1000 ? '变化' : ''
}

// ── AI 助手抽屉（AI 帮我建）──
const aiChatOpen = ref(false)
const aiChatIntent = ref('')
function openAIChat(intent: string) {
  aiChatIntent.value = intent
  aiChatOpen.value = true
}
</script>

<template>
  <div class="view-container overview-container">
    <div class="overview-layout">
      <!-- ============ 左主列 ============ -->
      <div class="overview-main">
        <!-- Tab 栏：AI 规则 + 社区动态 -->
        <div class="overview-tabbar">
          <button v-for="rule in ruleTabs" :key="rule.id" class="tab overview-tab"
                  :class="{ active: activeTab === 'rule:' + rule.id }"
                  @click="selectTab('rule:' + rule.id)">
            ⚡ {{ rule.name }}
            <span v-if="rulesStore.runningRuleIds.has(rule.id)" class="badge badge-loading">…</span>
            <span v-else class="badge">{{ rule.match_count ?? 0 }}</span>
          </button>
          <button class="tab overview-tab" :class="{ active: activeTab === 'community' }"
                  @click="selectTab('community')">
            社区动态
          </button>
          <button class="tab overview-tab" @click="openAIChat('rule')" title="AI 帮我建规则">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.4L22 18l-2.1.6L19 21l-.9-2.4L16 18l2.1-.6z"/></svg>
            AI 建规则
          </button>
          <button class="tab overview-tab overview-tab-gear" @click="rulesStore.openManager()" title="管理筛选规则">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </div>

        <!-- 引导：还没有规则 -->
        <div v-if="ruleTabs.length === 0" class="overview-hint">
          <span>💡 创建 AI 筛选规则，让 AI 按你的要求从社区 issue/PR/commit 流中筛出值得关注的条目</span>
          <button class="btn btn-primary btn-sm" @click="rulesStore.openManager()">创建规则</button>
        </div>

        <!-- AI 规则 tab 内容 -->
        <div v-if="activeTab.startsWith('rule:')" class="community-list">
          <div class="rule-toolbar" v-if="activeRule">
            <span class="rule-prompt-label" :title="activeRule.prompt">筛选要求：{{ activeRule.prompt }}</span>
            <button class="btn btn-sm" :disabled="activeRuleRunning" @click="rerunActiveRule" title="清空现有命中并重新评估最近 7 天条目">
              {{ activeRuleRunning ? 'AI 筛选中…' : '⟲ 重新评估' }}
            </button>
          </div>
          <FilterRow label="类型">
            <div class="tab-bar">
              <button class="tab" :class="{ active: ruleMatchFilter === 'all' }" @click="ruleMatchFilter = 'all'">
                全部 <span class="badge">{{ activeMatchCounts.all }}</span>
              </button>
              <button class="tab" :class="{ active: ruleMatchFilter === 'commit' }" @click="ruleMatchFilter = 'commit'">
                Commits <span class="badge">{{ activeMatchCounts.commit }}</span>
              </button>
              <button class="tab" :class="{ active: ruleMatchFilter === 'pr' }" @click="ruleMatchFilter = 'pr'">
                PRs <span class="badge">{{ activeMatchCounts.pr }}</span>
              </button>
              <button class="tab" :class="{ active: ruleMatchFilter === 'issue' }" @click="ruleMatchFilter = 'issue'">
                Issues <span class="badge">{{ activeMatchCounts.issue }}</span>
              </button>
            </div>
          </FilterRow>
          <template v-for="item in activeMatchesFiltered" :key="item.type + '-' + (item.number || item.sha || '')">
            <!-- commit 命中项 -->
            <div v-if="item.type === 'commit'" class="community-item" :class="{ 'is-new': item.is_new }" @click="openMatchedItem(item)">
              <div class="item-header">
                <span class="item-type-badge badge-commit">COMMIT</span>
                <span class="item-number">{{ item.short_sha || item.sha?.slice(0, 7) }}</span>
                <span v-if="commitPrNumber(item)" class="item-state">关联 #{{ commitPrNumber(item) }}</span>
                <span v-if="isNewForUser(item)" class="badge badge-new" title="上次查看该规则后新增的命中">新</span>
              </div>
              <div class="item-title-row">
                <h3 class="item-title">{{ item.title }}</h3>
              </div>
              <div v-if="item.reason" class="match-reason">⚡ {{ item.reason }}</div>
              <div class="item-meta">
                <span class="meta-item">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
                  {{ item.author }}
                </span>
                <span v-if="item.repo" class="badge badge-area" style="font-size:9px;">{{ item.repo.split('/').pop() }}</span>
                <span class="meta-item tt-host">
                  {{ timeAgo(item.committed_at) }}
                  <span class="tt">{{ exactTime(item.committed_at) }}</span>
                </span>
              </div>
            </div>
            <!-- PR / Issue 命中项 -->
            <div v-else class="community-item" :class="{ 'is-new': item.is_new }" @click="openMatchedItem(item)">
              <div class="item-header">
                <span class="item-type-badge" :class="item.type === 'pr' ? 'badge-pr' : 'badge-issue'">
                  {{ item.type === 'pr' ? 'PR' : 'ISSUE' }}
                </span>
                <span class="item-number">#{{ item.number }}</span>
                <span class="item-state" :class="'state-' + item.state">
                  {{ item.type === 'pr' ? prStateLabel(item.state) : issueStateLabel(item.state) }}
                </span>
                <span v-if="item.type === 'issue'" class="item-issue-type">{{ issueTypeLabel(issueType(item)) }}</span>
                <span v-if="isNewForUser(item)" class="badge badge-new" title="上次查看该规则后新增的命中">新</span>
              </div>
              <div class="item-title-row">
                <h3 class="item-title">{{ item.title }}</h3>
                <button class="btn btn-xs watchlist-star-btn"
                        :class="watchlistStore.findWatchlistItem(item.number, item.type, item.repo) ? 'btn-starred' : 'btn-ghost'"
                        @click.stop="toggleWatchlist(item.number, item.type, item.title, ghUrl(item.repo, item.number, item.type), { repo: item.repo })"
                        :title="watchlistStore.findWatchlistItem(item.number, item.type, item.repo) ? '取消特别关注' : '加入特别关注'">
                  <svg width="14" height="14" viewBox="0 0 24 24" :fill="watchlistStore.findWatchlistItem(item.number, item.type, item.repo) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
                    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                  </svg>
                </button>
              </div>
              <div v-if="item.reason" class="match-reason">⚡ {{ item.reason }}</div>
              <div class="item-meta">
                <span class="meta-item">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
                  {{ item.author }}
                </span>
                <span v-if="item.repo" class="badge badge-area" style="font-size:9px;">{{ item.repo.split('/').pop() }}</span>
                <span v-if="item.area" class="badge badge-area">{{ appStore.areaName(item.area) }}</span>
                <span class="meta-item tt-host">
                  {{ timeAgo(item.created_at) }}
                  <span class="tt">{{ exactTime(item.created_at) }}</span>
                </span>
                <span v-if="item.comments > 0" class="meta-item">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  {{ item.comments }}
                </span>
              </div>
            </div>
          </template>
          <div v-if="rulesStore.matchesLoading[parseInt(activeTab.slice(5))] " class="detail-loading">加载中…</div>
          <div v-else-if="activeMatchesFiltered.length === 0" class="empty-state">
            <div class="empty-icon">∅</div>
            <div class="empty-title">{{ activeRuleRunning ? 'AI 筛选中，完成后自动刷新' : '暂无命中条目' }}</div>
            <div class="empty-desc">规则定时自动运行（约每 30 分钟），也可点击右上角「重新评估」立即执行</div>
          </div>
        </div>

        <!-- 社区动态 tab 内容 -->
        <template v-if="activeTab === 'community'">
          <FilterRow v-if="communityStore.trackedRepos.length > 0" label="仓库">
            <div class="tab-bar" style="flex-wrap:wrap;">
              <button v-for="r in communityStore.trackedRepos" :key="r.id"
                      class="tab tab-sm" :class="{ active: communityStore.communityRepo === repoFullName(r.clone_url) }"
                      @click="switchRepo(repoFullName(r.clone_url))">
                {{ r.repo }}
              </button>
            </div>
          </FilterRow>

          <FilterRow label="类型">
            <div class="tab-bar">
              <button class="tab" :class="{ active: communityStore.communityTab === 'commits' }"
                      @click="communityStore.communityTab = 'commits'">
                Commits <span class="badge">{{ communityStore.commits.length }}</span>
              </button>
              <button class="tab" :class="{ active: communityStore.communityTab === 'prs' }"
                      @click="communityStore.communityTab = 'prs'">
                PRs <span class="badge">{{ communityStore.prs.length }}</span>
              </button>
              <button class="tab" :class="{ active: communityStore.communityTab === 'issues' }"
                      @click="communityStore.communityTab = 'issues'">
                Issues <span class="badge">{{ communityStore.issues.length }}</span>
              </button>
            </div>
          </FilterRow>

          <FilterRow v-if="communityStore.communityTab !== 'commits'" label="筛选">
            <template v-if="communityStore.communityTab === 'issues'">
              <select class="select select-sm" v-model="communityStore.communityIssueType">
                <option value="all">全部类型</option>
                <option value="bug">Bug</option>
                <option value="rfc">RFC</option>
                <option value="feature">功能</option>
                <option value="usage">使用</option>
                <option value="installation">安装</option>
                <option value="performance">性能</option>
                <option value="doc">文档</option>
                <option value="ci">CI</option>
                <option value="refactor">重构</option>
              </select>
              <select class="select select-sm" v-model="communityStore.communityIssueArea">
                <option value="">全部领域</option>
                <option v-for="area in appStore.areas" :key="area.id" :value="area.id">{{ area.name }}</option>
              </select>
            </template>
            <template v-else>
              <select class="select select-sm" v-model="communityStore.communityPRArea">
                <option value="">全部领域</option>
                <option v-for="area in appStore.areas" :key="area.id" :value="area.id">{{ area.name }}</option>
              </select>
            </template>
          </FilterRow>

          <div class="community-list">
            <template v-for="item in displayedItems" :key="item.type + '-' + (item.number || item.pr_number || item.sha || '')">
              <!-- commit 项 -->
              <div v-if="item.type === 'commit' || item.sha" class="community-item" :class="{ 'is-new': item.is_new }" @click="openCommit(item)">
                <div class="item-header">
                  <span class="item-type-badge badge-commit">COMMIT</span>
                  <span class="item-number">{{ item.short_sha || item.sha?.slice(0, 7) }}</span>
                  <span v-if="commitPrNumber(item)" class="item-state">关联 #{{ commitPrNumber(item) }}</span>
                  <span v-if="item.is_new" class="badge badge-new">新</span>
                </div>
                <div class="item-title-row">
                  <h3 class="item-title">{{ item.subject || item.title }}</h3>
                </div>
                <div class="item-meta">
                  <span class="meta-item">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
                    {{ item.author }}
                  </span>
                  <span v-if="!communityStore.communityRepo && item.repo" class="badge badge-area" style="font-size:9px;">{{ item.repo.split('/').pop() }}</span>
                  <span class="meta-item tt-host">
                    {{ timeAgo(item.committed_at) }}
                    <span class="tt">{{ exactTime(item.committed_at) }}</span>
                  </span>
                </div>
              </div>
              <!-- PR / Issue 项 -->
              <div v-else class="community-item" :class="{ 'is-new': item.is_new }" @click="item.type === 'pr' ? openPR(item) : openIssue(item as Issue)">
                <div class="item-header">
                  <span class="item-type-badge" :class="item.type === 'pr' ? 'badge-pr' : 'badge-issue'">
                    {{ item.type === 'pr' ? 'PR' : 'ISSUE' }}
                  </span>
                  <span class="item-number">#{{ item.number || item.pr_number }}</span>
                  <span class="item-state" :class="'state-' + item.state">
                    {{ item.type === 'pr' ? prStateLabel(item.state) : issueStateLabel(item.state) }}
                  </span>
                  <span v-if="item.type === 'issue'" class="item-issue-type">{{ issueTypeLabel(issueType(item)) }}</span>
                  <span v-if="item.is_new" class="badge badge-new">新</span>
                </div>
                <div class="item-title-row">
                  <h3 class="item-title">{{ item.title }}</h3>
                  <button class="btn btn-xs watchlist-star-btn" :class="(item.type === 'pr' ? watchlistStore.findWatchlistItem(item.number || item.pr_number, 'pr', item.repo) : watchlistStore.findWatchlistItem(item.number, 'issue', item.repo)) ? 'btn-starred' : 'btn-ghost'"
                          @click.stop="item.type === 'pr'
                            ? toggleWatchlist(item.number || item.pr_number, 'pr', item.title, ghUrl(item.repo, item.number || item.pr_number, 'pr'), { repo: item.repo })
                            : toggleWatchlist(item.number, 'issue', item.title, ghUrl(item.repo, item.number, 'issue'), { repo: item.repo })"
                          :title="(item.type === 'pr' ? watchlistStore.findWatchlistItem(item.number || item.pr_number, 'pr', item.repo) : watchlistStore.findWatchlistItem(item.number, 'issue', item.repo)) ? '取消特别关注' : '加入特别关注'">
                    <svg width="14" height="14" viewBox="0 0 24 24" :fill="(item.type === 'pr' ? watchlistStore.findWatchlistItem(item.number || item.pr_number, 'pr', item.repo) : watchlistStore.findWatchlistItem(item.number, 'issue', item.repo)) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                    </svg>
                  </button>
                </div>
                <div class="item-meta">
                  <span class="meta-item">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
                    {{ item.author }}
                  </span>
                  <span v-if="!communityStore.communityRepo && item.repo" class="badge badge-area" style="font-size:9px;">{{ item.repo.split('/').pop() }}</span>
                  <span v-if="item.area" class="badge badge-area">{{ appStore.areaName(item.area) }}</span>
                  <span class="meta-item tt-host">
                    {{ timeAgo(item.created_at) }}
                    <span class="tt">{{ exactTime(item.created_at) }}</span>
                  </span>
                  <span v-if="item.comments > 0" class="meta-item">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                    {{ item.comments }}
                  </span>
                  <span v-if="item.type === 'pr' && (item.additions || item.deletions)" class="diffstat">
                    <span class="add">+{{ item.additions || 0 }}</span>
                    <span class="del">-{{ item.deletions || 0 }}</span>
                  </span>
                </div>
              </div>
            </template>
            <div v-if="displayedItems.length === 0" class="empty-state">
              <div class="empty-icon">∅</div>
              <div class="empty-title">{{ appStore.searchQuery.trim() ? '无匹配结果' : '暂无动态' }}</div>
              <div class="empty-desc" v-if="appStore.searchQuery.trim()">未找到与「{{ appStore.searchQuery }}」匹配的项，试试其他关键词</div>
            </div>
            <button v-if="communityStore.hasMoreCommunity" class="btn btn-sm load-more" @click="loadMore">
              加载更多
            </button>
          </div>
        </template>
      </div>

      <!-- ============ 右栏 ============ -->
      <div class="overview-aside">
        <!-- 需要处理 -->
        <div class="aside-card">
          <div class="aside-card-header">
            <h3 class="aside-card-title">
              {{ prCardMode === 'pending' ? '需要处理' : '我的 PR / Issue' }}
              <span v-if="prCardMode === 'pending'" class="badge" :class="pendingPRs.length > 0 ? 'badge-danger' : ''">{{ pendingPRs.length }}</span>
            </h3>
            <div class="aside-card-actions">
              <select class="select select-sm" v-model="prStore.selectedContributorGithubId" @change="onContributorChange" style="max-width:110px;">
                <option value="">全部贡献者</option>
                <option v-for="u in usersStore.users" :key="u.id" :value="u.github_id">{{ u.name }}</option>
              </select>
              <button class="tab tab-sm" :class="{ active: prCardMode === 'pending' }" @click="prCardMode = 'pending'">待处理</button>
              <button class="tab tab-sm" :class="{ active: prCardMode === 'all' }" @click="prCardMode = 'all'">全部</button>
            </div>
          </div>

          <!-- 待处理视图：冲突 / CI 失败 / 落后 main -->
          <div v-if="prCardMode === 'pending'" class="aside-card-body">
            <div v-for="pr in pendingPRs" :key="(pr.repo || '') + '-' + pr.pr_number" class="aside-item" @click="prStore.openPR(pr)">
              <div class="aside-item-header">
                <span class="pr-number">#{{ pr.pr_number }}</span>
                <span v-if="pr.conflict_detected" class="badge badge-conflict">冲突</span>
                <span v-if="pr.ci_status === 'fail'" class="badge" :class="ciBadgeClass(pr.ci_status)">{{ ciLabel(pr.ci_status) }}</span>
              </div>
              <div class="aside-item-title">{{ pr.title }}</div>
              <div class="aside-item-meta">
                <span>{{ pr.author }}</span>
                <span v-if="pr.repo" class="badge badge-area" style="font-size:9px;">{{ pr.repo.split('/').pop() }}</span>
                <span>{{ timeAgo(pr.created_at) }}</span>
              </div>
            </div>
          <div v-if="pendingPRs.length === 0" class="empty-state is-compact">
              <p>✓ 没有待处理的 PR</p>
            </div>
          </div>

          <!-- 全部视图：原贡献面板完整能力 -->
          <div v-else class="aside-card-body">
            <div class="tab-bar tab-bar-sm" style="margin-bottom:8px;">
              <button class="tab tab-sm" :class="{ active: prStore.contributionTab === 'prs' }"
                      @click="prStore.switchContributionTab('prs')">PRs ({{ prStore.openPRCount }})</button>
              <button class="tab tab-sm" :class="{ active: prStore.contributionTab === 'issues' }"
                      @click="prStore.switchContributionTab('issues')">Issues ({{ prStore.openIssueCount }})</button>
            </div>
            <template v-if="prStore.contributionTab === 'prs'">
              <div class="tab-bar tab-bar-sm" style="margin-bottom:8px;flex-wrap:wrap;">
                <button class="tab tab-sm" :class="{ active: prStore.prState === 'open' }" @click="prStore.switchPRState('open')">开放</button>
                <button class="tab tab-sm" :class="{ active: prStore.prState === 'merged' }" @click="prStore.switchPRState('merged')">已合并</button>
                <button class="tab tab-sm" :class="{ active: prStore.prState === 'closed' }" @click="prStore.switchPRState('closed')">已关闭</button>
                <button class="tab tab-sm" :class="{ active: prStore.prState === 'all' }" @click="prStore.switchPRState('all')">全部</button>
              </div>
              <div class="aside-filters">
                <label class="checkbox-label">
                  <input type="checkbox" v-model="prStore.filterConflicts" /> 冲突
                </label>
                <label class="checkbox-label">
                  <input type="checkbox" v-model="prStore.filterCIFail" /> CI 失败
                </label>
              </div>
              <div v-for="pr in prStore.filteredMyPRs" :key="(pr.repo || '') + '-' + pr.pr_number" class="aside-item" @click="prStore.openPR(pr)">
                <div class="aside-item-header">
                  <span class="pr-number">#{{ pr.pr_number }}</span>
                  <span class="badge" :class="'state-' + pr.state">{{ prStateLabel(pr.state) }}</span>
                  <span v-if="pr.conflict_detected" class="badge badge-conflict">冲突</span>
                  <span v-if="pr.ci_status" class="badge" :class="ciBadgeClass(pr.ci_status)">{{ ciLabel(pr.ci_status) }}</span>
                </div>
                <div class="aside-item-title">{{ pr.title }}</div>
                <div class="aside-item-meta">
                  <span>{{ pr.author }}</span>
                  <span>{{ pr.branch }}</span>
                  <span>{{ timeAgo(pr.created_at) }}</span>
                </div>
              </div>
            </template>
            <template v-else>
              <div class="aside-filters" style="margin-bottom:8px;">
                <select class="select select-sm" v-model="prStore.myIssuesState">
                  <option value="open">开放</option>
                  <option value="closed">已关闭</option>
                  <option value="all">全部</option>
                </select>
                <select class="select select-sm" v-model="prStore.myIssuesType">
                  <option value="all">全部类型</option>
                  <option value="bug">Bug</option>
                  <option value="rfc">RFC</option>
                  <option value="doc">文档</option>
                  <option value="ci">CI</option>
                </select>
              </div>
              <div v-for="issue in prStore.filteredMyIssues" :key="(issue.repo || '') + '-' + issue.number" class="aside-item" @click="prStore.openIssue(issue)">
                <div class="aside-item-header">
                  <span class="pr-number">#{{ issue.number }}</span>
                  <span class="badge" :class="'state-' + issue.state">{{ issueStateLabel(issue.state) }}</span>
                  <span class="badge badge-issue-type">{{ issueTypeLabel(issueType(issue)) }}</span>
                </div>
                <div class="aside-item-title">{{ issue.title }}</div>
                <div class="aside-item-meta">
                  <span>{{ issue.author }}</span>
                  <span>{{ timeAgo(issue.created_at) }}</span>
                </div>
              </div>
            </template>
            <div v-if="prStore.contributionTab === 'prs' && prStore.filteredMyPRs.length === 0" class="empty-state is-compact"><p>暂无 PR</p></div>
            <div v-if="prStore.contributionTab === 'issues' && prStore.filteredMyIssues.length === 0" class="empty-state is-compact"><p>暂无 Issue</p></div>
          </div>
        </div>

        <!-- 重点关注 -->
        <div class="aside-card">
          <div class="aside-card-header">
            <h3 class="aside-card-title">重点关注 <span class="badge">{{ watchlistStore.watchlist.length }}</span></h3>
            <button class="btn btn-primary btn-sm" @click="watchlistStore.openAddModal()">+ 添加</button>
          </div>
          <div class="aside-card-body">
            <div v-for="w in watchlistStore.watchlist" :key="(w.repo || '') + '-' + w.item_type + '-' + w.number" class="aside-item" @click="openWatchlistItem(w)">
              <div class="aside-item-header">
                <span class="item-type-badge" :class="w.item_type === 'pr' ? 'badge-pr' : 'badge-issue'">
                  {{ w.item_type === 'pr' ? 'PR' : 'ISSUE' }}
                </span>
                <span class="pr-number">#{{ w.number }}</span>
                <span v-if="w.state" class="item-state" :class="'state-' + w.state">
                  {{ w.state === 'merged' ? '已合并' : w.state === 'open' ? '开放' : '已关闭' }}
                </span>
                <span v-if="watchlistChangeHint(w)" class="badge badge-new">状态变化</span>
              </div>
              <div class="aside-item-title">{{ w.title }}</div>
              <div class="aside-item-meta">
                <span v-if="w.assignee_id" class="badge badge-assignee">{{ usersStore.userName(w.assignee_id) }}</span>
                <span v-if="w.note" class="watchlist-note watchlist-note-icon"><Icon name="note" :size="11" /> {{ w.note }}</span>
                <span style="flex:1;"></span>
                <span v-for="lt in (w.linked_tasks || []).slice(0, 2)" :key="lt.id" class="ref-badge ref-badge-sm clickable" @click.stop="openTaskDrawer(lt)" :title="lt.title">
                  #{{ lt.id }}
                </span>
                <button class="card-action-btn" @click.stop="watchlistStore.openEditModal(w)" title="编辑备注/责任人">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                <button class="card-action-btn is-danger" @click.stop="watchlistStore.toggleWatch(w.number, w.item_type, w.title, w.url, { repo: w.repo })" title="移除关注">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
            </div>
            <div v-if="watchlistStore.watchlist.length === 0" class="empty-state is-compact">
              <p>暂无关注项</p>
              <button class="btn btn-primary btn-sm" @click="watchlistStore.openAddModal()">添加第一个关注</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 共享抽屉与弹窗 -->
    <PRDrawer />
    <IssueDrawer />
    <TaskDrawer />
    <WatchlistModals />
    <ChatDrawer :open="aiChatOpen" :intent="aiChatIntent" @close="aiChatOpen = false" />
  </div>
</template>

<style scoped>
.overview-container {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.overview-layout {
  display: flex;
  gap: var(--space-4);
  flex: 1;
  min-height: 0;
}
.overview-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding-bottom: var(--space-6);
}
.overview-aside {
  flex: 0 0 320px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  overflow-y: auto;
  padding-bottom: var(--space-6);
}
@media (max-width: 900px) {
  .overview-layout {
    flex-direction: column-reverse;
  }
  .overview-aside {
    flex: none;
  }
}

.overview-tabbar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-faint);
  padding-bottom: 8px;
}
.overview-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.overview-tab-gear {
  margin-left: auto;
  padding: 4px 8px;
  color: var(--text-tertiary);
}
.overview-tab-gear:hover {
  color: var(--accent);
}

.overview-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: var(--space-4);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
  border-radius: 8px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.rule-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: var(--space-3);
}
.rule-prompt-label {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.match-reason {
  font-size: var(--text-sm);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  border-radius: 6px;
  padding: 4px 8px;
  margin: 4px 0;
  line-height: 1.5;
}

/* 右栏卡片 */
.aside-card {
  background: var(--bg-elev-1);
  border: 1px solid var(--border-faint);
  border-radius: 10px;
  overflow: hidden;
}
.aside-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-faint);
  flex-wrap: wrap;
}
.aside-card-title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.aside-card-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.aside-card-body {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 420px;
  overflow-y: auto;
}
.aside-item {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background var(--t-fast);
}
.aside-item:hover {
  background: var(--hover-bg);
}
.aside-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.aside-item-title {
  font-size: var(--text-sm);
  font-weight: 600;
  margin: 3px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.aside-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
  flex-wrap: wrap;
}
.aside-filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
