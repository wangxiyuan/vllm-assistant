<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useCommunityStore } from '@/stores/community'
import { useAppStore } from '@/stores/app'
import { usePRCenterStore } from '@/stores/prCenter'
import { useWatchlistStore } from '@/stores/watchlist'
import { issueType, issueTypeLabel, issueStateLabel, prStateLabel, timeAgo } from '@/utils/helpers'
import type { Issue, PR } from '@/utils/types'

const communityStore = useCommunityStore()
const appStore = useAppStore()
const prStore = usePRCenterStore()
const watchlistStore = useWatchlistStore()

onMounted(() => {
  communityStore.loadCommunityData()
  communityStore.loadAreas()
})

const displayedItems = computed(() => {
  if (communityStore.communityTab === 'prs') return communityStore.pagedFilteredPRs
  return communityStore.pagedFilteredIssues
})

function loadMore() {
  communityStore.communityPage++
}

function openPR(pr: PR) {
  prStore.openPR({ ...pr, pr_number: pr.number })
}

function openIssue(issue: Issue) {
  prStore.openIssue(issue)
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">社区动态</h2>
      <div class="view-actions">
        <div class="tab-bar">
          <button class="tab" :class="{ active: communityStore.communityTab === 'prs' }"
                  @click="communityStore.communityTab = 'prs'">
            PRs <span class="badge">{{ communityStore.newPRsCount > 0 ? communityStore.newPRsCount : communityStore.prs.length }}</span>
          </button>
          <button class="tab" :class="{ active: communityStore.communityTab === 'issues' }"
                  @click="communityStore.communityTab = 'issues'">
            Issues <span class="badge">{{ communityStore.newIssuesCount > 0 ? communityStore.newIssuesCount : communityStore.issues.length }}</span>
          </button>
        </div>
        <select class="select select-sm" v-model="communityStore.sortBy">
          <option value="created">按创建时间</option>
          <option value="updated">按更新时间</option>
        </select>
        <button class="btn btn-sm" @click="communityStore.forceRefresh()">刷新</button>
      </div>
    </div>

    <div class="community-filters">
      <select v-if="communityStore.communityTab === 'issues'" class="select select-sm" v-model="communityStore.communityIssueType">
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
      <select class="select select-sm" v-model="communityStore.communityPRArea">
        <option value="">全部领域</option>
        <option v-for="area in appStore.areas" :key="area.id" :value="area.id">{{ area.name }}</option>
      </select>
    </div>

    <div class="community-list">
      <div v-for="item in displayedItems" :key="item.type + '-' + (item.number || item.pr_number)"
           class="community-item" @click="item.type === 'pr' ? openPR(item) : openIssue(item as Issue)">
        <div class="item-header">
          <span class="item-type-badge" :class="item.type === 'pr' ? 'badge-pr' : 'badge-issue'">
            {{ item.type === 'pr' ? 'PR' : 'ISSUE' }}
          </span>
          <span class="item-number">#{{ item.number || item.pr_number }}</span>
          <span class="item-state" :class="'state-' + item.state">
            {{ item.type === 'pr' ? prStateLabel(item.state) : issueStateLabel(item.state) }}
          </span>
          <span v-if="item.type === 'issue'" class="item-issue-type">{{ issueTypeLabel(issueType(item)) }}</span>
        </div>
        <h3 class="item-title">{{ item.title }}</h3>
        <div class="item-meta">
          <span>{{ item.author }}</span>
          <span v-if="item.area">{{ appStore.areaName(item.area) }}</span>
          <span>{{ timeAgo(item.created_at) }}</span>
        </div>
      </div>
      <div v-if="displayedItems.length === 0" class="empty-state">
        暂无数据
      </div>
      <button v-if="communityStore.hasMoreCommunity" class="btn btn-sm load-more" @click="loadMore">
        加载更多
      </button>
    </div>

    <!-- PR Drawer -->
    <Teleport to="body">
      <div v-if="prStore.selectedPR" class="drawer-backdrop" @click="prStore.closePR()">
        <div class="drawer drawer-wide" @click.stop>
          <div class="drawer-header">
            <div class="drawer-title">
              <div class="pr-id">
                <span class="badge badge-pr">PR</span>
                #{{ prStore.selectedPR.pr_number || prStore.selectedPR.number }}
              </div>
              <h2>{{ prStore.selectedPR.title }}</h2>
            </div>
            <div class="drawer-actions">
              <a :href="'https://github.com/vllm-project/vllm/pull/' + (prStore.selectedPR.pr_number || prStore.selectedPR.number)" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closePR()">&times;</button>
            </div>
          </div>
          <div class="drawer-body">
            <div v-if="prStore.loadingDetails" class="detail-loading">加载中…</div>
            <div v-else-if="prStore.prLoadError" class="detail-loading" style="color:var(--signal-red)">{{ prStore.prLoadError }}</div>
            <div v-else-if="prStore.prDetails">
              <div v-if="prStore.prDetails.pr?.body" class="pr-body" v-html="prStore.prDetails.pr.body"></div>
              <div v-else class="empty-state" style="padding:var(--space-5)"><p>无详细描述</p></div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Issue Drawer -->
    <Teleport to="body">
      <div v-if="prStore.selectedIssue" class="drawer-backdrop" @click="prStore.closeIssue()">
        <div class="drawer drawer-wide" @click.stop>
          <div class="drawer-header">
            <div class="drawer-title">
              <div class="pr-id">
                <span class="badge badge-issue">ISSUE</span>
                #{{ prStore.selectedIssue.number }}
              </div>
              <h2>{{ prStore.selectedIssue.title }}</h2>
            </div>
            <div class="drawer-actions">
              <a :href="'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closeIssue()">&times;</button>
            </div>
          </div>
          <div class="drawer-body">
            <div v-if="prStore.loadingIssue" class="detail-loading">加载中…</div>
            <div v-else-if="prStore.issueLoadError" class="detail-loading" style="color:var(--signal-red)">{{ prStore.issueLoadError }}</div>
            <div v-else-if="prStore.issueDetails?.body" class="pr-body" v-html="prStore.issueDetails.body"></div>
            <div v-else class="empty-state" style="padding:var(--space-5)"><p>无详细描述</p></div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
