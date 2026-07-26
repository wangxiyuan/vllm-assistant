<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { usePRCenterStore } from '@/stores/prCenter'
import { useUsersStore } from '@/stores/users'
import { useAppStore } from '@/stores/app'
import { timeAgo } from '@/utils/helpers'
import { useWatchlistStore } from '@/stores/watchlist'
import { useRouter } from 'vue-router'
import { renderMarkdown, renderDiff, renderSummary, renderReview } from '@/composables/useMarkdown'
import { ciLabel, ciBadgeClass, prStateLabel, issueStateLabel, issueType, issueTypeLabel } from '@/utils/helpers'

const prStore = usePRCenterStore()
const usersStore = useUsersStore()
const appStore = useAppStore()
const watchlistStore = useWatchlistStore()
const router = useRouter()

onMounted(() => {
  prStore.loadAllContribData()
})

// When contributor changes
function onContributorChange() {
  const val = prStore.selectedContributorGithubId
  if (val) {
    const user = usersStore.users.find(u => u.github_id === val)
    if (user) prStore.selectedContributor = user as any
  } else {
    prStore.selectedContributor = null
  }
  prStore.loadAllContribData()
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">贡献面板</h2>
      <div class="view-actions">
        <select class="select select-sm" v-model="prStore.selectedContributorGithubId" @change="onContributorChange">
          <option value="">全部贡献者</option>
          <option v-for="u in usersStore.users" :key="u.id" :value="u.github_id">{{ u.name }}</option>
        </select>
      </div>
    </div>

    <!-- Stats overview -->
    <div v-if="prStore.myStats" class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ prStore.myStats.totalPRs || 0 }}</div>
        <div class="stat-label">PRs</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ prStore.myStats.totalIssues || 0 }}</div>
        <div class="stat-label">Issues</div>
      </div>
      <div v-if="prStore.myStats.monthly" class="stat-card stat-chart">
        <div class="monthly-bars">
          <div v-for="(count, month) in prStore.myStats.monthly.created" :key="month" class="month-bar-wrap">
            <div class="month-bar" :style="{ height: prStore.monthBarHeight(count, prStore.myStats.monthly.created) + '%' }"></div>
            <div class="month-label">{{ prStore.formatMonthLabel(month) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: prStore.contributionTab === 'prs' }"
              @click="prStore.switchContributionTab('prs')">PRs ({{ prStore.allPRCount }})</button>
      <button class="tab" :class="{ active: prStore.contributionTab === 'issues' }"
              @click="prStore.switchContributionTab('issues')">Issues ({{ prStore.allIssueCount }})</button>
    </div>

    <!-- PR list -->
    <template v-if="prStore.contributionTab === 'prs'">
      <div class="pr-filters">
        <div class="tab-bar tab-bar-sm">
          <button class="tab tab-sm" :class="{ active: prStore.prState === 'open' }" @click="prStore.switchPRState('open')">开放 ({{ prStore.openPRCount }})</button>
          <button class="tab tab-sm" :class="{ active: prStore.prState === 'merged' }" @click="prStore.switchPRState('merged')">已合并 ({{ prStore.mergedPRCount }})</button>
          <button class="tab tab-sm" :class="{ active: prStore.prState === 'closed' }" @click="prStore.switchPRState('closed')">已关闭 ({{ prStore.closedPRCount }})</button>
          <button class="tab tab-sm" :class="{ active: prStore.prState === 'all' }" @click="prStore.switchPRState('all')">全部 ({{ prStore.allPRCount }})</button>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="prStore.filterConflicts" /> 冲突
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="prStore.filterCIFail" /> CI 失败
        </label>
      </div>

      <div class="pr-list">
        <div v-for="pr in prStore.filteredMyPRs" :key="pr.pr_number" class="pr-item" @click="prStore.openPR(pr)">
          <div class="pr-item-header">
            <span class="pr-number">#{{ pr.pr_number }}</span>
            <span class="badge" :class="'state-' + pr.state">{{ prStateLabel(pr.state) }}</span>
            <span v-if="pr.conflict_detected" class="badge badge-conflict">冲突</span>
            <span v-if="pr.ci_status" class="badge" :class="ciBadgeClass(pr.ci_status)">{{ ciLabel(pr.ci_status) }}</span>
          </div>
          <h4 class="pr-title">{{ pr.title }}</h4>
          <div class="pr-meta">
            <span>{{ pr.author }}</span>
            <span>{{ pr.branch }}</span>
            <span>{{ timeAgo(pr.created_at) }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- Issue list -->
    <template v-if="prStore.contributionTab === 'issues'">
      <div class="pr-filters">
        <div class="tab-bar tab-bar-sm">
          <button class="tab tab-sm" :class="{ active: prStore.myIssuesState === 'open' }" @click="prStore.switchMyIssuesState('open')">开放</button>
          <button class="tab tab-sm" :class="{ active: prStore.myIssuesState === 'closed' }" @click="prStore.switchMyIssuesState('closed')">已关闭</button>
          <button class="tab tab-sm" :class="{ active: prStore.myIssuesState === 'all' }" @click="prStore.switchMyIssuesState('all')">全部</button>
        </div>
        <select class="select select-sm" v-model="prStore.myIssuesType" @change="prStore.switchMyIssuesType(prStore.myIssuesType)">
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
      </div>

      <div class="pr-list">
        <div v-for="issue in prStore.filteredMyIssues" :key="issue.number" class="pr-item" @click="prStore.openIssue(issue)">
          <div class="pr-item-header">
            <span class="pr-number">#{{ issue.number }}</span>
            <span class="badge" :class="'state-' + issue.state">{{ issueStateLabel(issue.state) }}</span>
            <span class="badge badge-issue-type">{{ issueTypeLabel(issueType(issue)) }}</span>
          </div>
          <h4 class="pr-title">{{ issue.title }}</h4>
          <div class="pr-meta">
            <span>{{ issue.author }}</span>
            <span>{{ timeAgo(issue.created_at) }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- PR Drawer -->
    <Teleport to="body">
      <div v-if="prStore.selectedPR" class="drawer-backdrop" @click="prStore.closePR()">
        <div class="drawer drawer-wide" @click.stop>
          <div class="drawer-header">
            <h3>{{ prStore.selectedPR.title }}</h3>
            <div class="drawer-actions">
              <a :href="'https://github.com/vllm-project/vllm/pull/' + prStore.selectedPR.pr_number" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closePR()">&times;</button>
            </div>
          </div>
          <div class="drawer-body">
            <!-- AI Summary -->
            <div class="ai-section" v-if="prStore.aiSummary">
              <div class="ai-section-header" @click="prStore.aiSummaryCollapsed = !prStore.aiSummaryCollapsed">
                <span>🤖 AI 总结</span>
                <span class="collapse-icon">{{ prStore.aiSummaryCollapsed ? '▶' : '▼' }}</span>
              </div>
              <div v-if="!prStore.aiSummaryCollapsed" class="ai-section-body" v-html="renderSummary(prStore.aiSummary)"></div>
            </div>
            <button v-if="!prStore.aiSummaryLoading" class="btn btn-sm" @click="prStore.generateSummary('pr')">生成 AI 总结</button>
            <span v-if="prStore.aiSummaryLoading">总结中…</span>

            <!-- AI Review -->
            <div class="ai-section" v-if="prStore.aiReview">
              <div class="ai-section-header" @click="prStore.aiReviewCollapsed = !prStore.aiReviewCollapsed">
                <span>🔍 AI Review</span>
                <span class="collapse-icon">{{ prStore.aiReviewCollapsed ? '▶' : '▼' }}</span>
              </div>
              <div v-if="!prStore.aiReviewCollapsed" class="ai-section-body" v-html="renderReview(prStore.aiReview)"></div>
            </div>
            <button v-if="!prStore.aiReviewLoading" class="btn btn-sm" @click="prStore.generateReview()">生成 AI Review</button>
            <span v-if="prStore.aiReviewLoading">Review 中… ({{ prStore.aiReviewElapsed }}s)</span>

            <!-- Translate -->
            <button class="btn btn-sm" @click="prStore.translateBody('pr')">翻译为中文</button>
            <div v-if="prStore.prTranslatedBody && prStore.prShowChinese" class="translated-body" v-html="renderMarkdown(prStore.prTranslatedBody)"></div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Issue Drawer -->
    <Teleport to="body">
      <div v-if="prStore.selectedIssue" class="drawer-backdrop" @click="prStore.closeIssue()">
        <div class="drawer drawer-wide" @click.stop>
          <div class="drawer-header">
            <h3>{{ prStore.selectedIssue.title }}</h3>
            <button class="btn btn-sm btn-ghost" @click="prStore.closeIssue()">&times;</button>
          </div>
          <div class="drawer-body">
            <div v-if="prStore.issueDetails?.body" v-html="renderMarkdown(prStore.issueDetails.body)"></div>
            <button class="btn btn-sm" @click="prStore.generateSummary('issue')">生成 AI 总结</button>
            <span v-if="prStore.aiSummaryLoading">总结中…</span>
            <div v-if="prStore.aiSummary" v-html="renderSummary(prStore.aiSummary)"></div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
