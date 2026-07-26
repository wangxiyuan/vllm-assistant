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
            <div class="drawer-title">
              <div class="pr-id">
                <span class="badge badge-pr">PR</span>
                #{{ prStore.selectedPR.pr_number }}
              </div>
              <h2>{{ prStore.selectedPR.title }}</h2>
            </div>
            <div class="drawer-actions">
              <button class="btn btn-sm" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number, 'pr') }"
                      @click.stop="watchlistStore.toggleWatch(prStore.selectedPR.pr_number, 'pr', prStore.selectedPR.title, 'https://github.com/vllm-project/vllm/pull/' + prStore.selectedPR.pr_number)"
                      :title="watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number, 'pr') ? '取消关注' : '添加到特别关注'">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              <a :href="'https://github.com/vllm-project/vllm/pull/' + prStore.selectedPR.pr_number" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closePR()">&times;</button>
            </div>
          </div>
          <!-- Tab bar -->
          <div class="tab-bar" style="margin:var(--space-4) var(--space-7) 0">
            <button class="tab" :class="{ active: prStore.prDetailTab === 'details' }"
                    @click="prStore.prDetailTab = 'details'">详情</button>
            <button class="tab" :class="{ active: prStore.prDetailTab === 'summary' }"
                    @click="prStore.prDetailTab = 'summary'">
              AI 总结
              <span v-if="prStore.aiSummaryLoading" class="badge" style="background:var(--amber-glow);color:var(--amber)">…</span>
              <span v-else-if="prStore.aiSummary" class="badge">✓</span>
            </button>
            <button class="tab" :class="{ active: prStore.prDetailTab === 'review' }"
                    @click="prStore.prDetailTab = 'review'">
              AI Review
              <span v-if="prStore.aiReviewLoading" class="badge" style="background:var(--amber-glow);color:var(--amber)">…</span>
              <span v-else-if="prStore.aiReview" class="badge">✓</span>
            </button>
          </div>
          <div class="drawer-body">
            <!-- Details tab (with translate toggle) -->
            <template v-if="prStore.prDetailTab === 'details'">
              <div v-if="prStore.loadingDetails" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.prLoadError" class="detail-loading" style="color:var(--signal-red)">{{ prStore.prLoadError }}</div>
              <div v-else-if="prStore.prDetails">
                <!-- Translate toggle -->
                <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)">
                  <template v-if="prStore.prTranslatedBody">
                    <button class="btn btn-sm" :class="{ 'btn-active': !prStore.prShowChinese }"
                            @click="prStore.prShowChinese = false">EN</button>
                    <button class="btn btn-sm" :class="{ 'btn-active': prStore.prShowChinese }"
                            @click="prStore.prShowChinese = true">中文</button>
                  </template>
                  <template v-else>
                    <button class="btn btn-sm" @click="prStore.translateBody('pr')"
                            :disabled="prStore.translateLoading">
                      {{ prStore.translateLoading ? '翻译中…' : 'AI 翻译' }}
                    </button>
                  </template>
                </div>
                <div v-if="prStore.prShowChinese && prStore.prTranslatedBody" class="pr-body" v-html="renderMarkdown(prStore.prTranslatedBody)"></div>
                <div v-else-if="prStore.prDetails.pr?.body" class="pr-body" v-html="renderMarkdown(prStore.prDetails.pr.body)"></div>
                <div v-else class="empty-state" style="padding:var(--space-5)"><p>无详细描述</p></div>

                <!-- Changed files list -->
                <template v-if="prStore.prDetails.files && prStore.prDetails.files.length > 0">
                  <h4 class="text-mono" style="font-size:11px;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-tertiary);margin:var(--space-5) 0 var(--space-3);">
                    变更文件 ({{ prStore.prDetails.files.length }})
                  </h4>
                  <ul class="file-list">
                    <li v-for="f in prStore.prDetails.files" :key="f.filename"
                        :class="{ 'diff-expanded': prStore.expandedDiffFile === f.filename }">
                      <span class="file-stats diffstat">
                        <span class="add">+{{ f.additions || 0 }}</span>
                        <span class="del">-{{ f.deletions || 0 }}</span>
                      </span>
                      <span class="file-name" @click="prStore.toggleFileDiff(f.filename)" :title="f.filename">{{ f.filename }}</span>
                      <span class="file-status" :class="'file-status-' + (f.status || 'modified')" style="margin-left:6px;font-size:10px;">{{ f.status || 'modified' }}</span>
                      <span class="diff-toggle" @click="prStore.toggleFileDiff(f.filename)" style="cursor:pointer;font-size:10px;color:var(--text-tertiary);flex-shrink:0;">
                        {{ prStore.expandedDiffFile === f.filename ? '收起' : '展开' }}
                      </span>
                      <div v-if="prStore.expandedDiffFile === f.filename" class="file-diff">
                        <div class="diff-view" v-html="renderDiff(prStore.fileDiffs[f.filename])"></div>
                      </div>
                    </li>
                  </ul>
                </template>
              </div>
            </template>

            <!-- AI Summary tab -->
            <template v-if="prStore.prDetailTab === 'summary'">
              <div v-if="prStore.aiSummaryLoading" class="detail-loading">AI 总结生成中…</div>
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderSummary(prStore.aiSummary)"></div>
              <div v-else class="empty-state" style="padding:var(--space-5)">
                <p>尚未生成 AI 总结</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateSummary('pr')">生成 AI 总结</button>
              </div>
            </template>

            <!-- AI Review tab -->
            <template v-if="prStore.prDetailTab === 'review'">
              <div v-if="prStore.aiReviewLoading" class="detail-loading">AI Review 生成中… ({{ prStore.aiReviewElapsed }}s)</div>
              <div v-else-if="prStore.aiReview" class="ai-section-body" v-html="renderReview(prStore.aiReview)"></div>
              <div v-else class="empty-state" style="padding:var(--space-5)">
                <p>尚未生成 AI Review</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateReview()">生成 AI Review</button>
              </div>
            </template>
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
              <button class="btn btn-sm" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue') }"
                      @click.stop="watchlistStore.toggleWatch(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.title, 'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number)"
                      :title="watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue') ? '取消关注' : '添加到特别关注'">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              <a :href="'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closeIssue()">&times;</button>
            </div>
          </div>
          <!-- Tab bar -->
          <div class="tab-bar" style="margin:var(--space-4) var(--space-7) 0">
            <button class="tab" :class="{ active: prStore.issueDetailTab === 'details' }"
                    @click="prStore.issueDetailTab = 'details'">详情</button>
            <button class="tab" :class="{ active: prStore.issueDetailTab === 'summary' }"
                    @click="prStore.issueDetailTab = 'summary'">
              AI 总结
              <span v-if="prStore.aiSummaryLoading" class="badge" style="background:var(--amber-glow);color:var(--amber)">…</span>
              <span v-else-if="prStore.aiSummary" class="badge">✓</span>
            </button>
          </div>
          <div class="drawer-body">
            <!-- Details tab (with translate toggle) -->
            <template v-if="prStore.issueDetailTab === 'details'">
              <div v-if="prStore.loadingIssue" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.issueLoadError" class="detail-loading" style="color:var(--signal-red)">{{ prStore.issueLoadError }}</div>
              <div v-else>
                <!-- Translate toggle -->
                <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)">
                  <template v-if="prStore.issueTranslatedBody">
                    <button class="btn btn-sm" :class="{ 'btn-active': !prStore.issueShowChinese }"
                            @click="prStore.issueShowChinese = false">EN</button>
                    <button class="btn btn-sm" :class="{ 'btn-active': prStore.issueShowChinese }"
                            @click="prStore.issueShowChinese = true">中文</button>
                  </template>
                  <template v-else>
                    <button class="btn btn-sm" @click="prStore.translateBody('issue')"
                            :disabled="prStore.translateLoading">
                      {{ prStore.translateLoading ? '翻译中…' : 'AI 翻译' }}
                    </button>
                  </template>
                </div>
                <div v-if="prStore.issueShowChinese && prStore.issueTranslatedBody" class="pr-body" v-html="renderMarkdown(prStore.issueTranslatedBody)"></div>
                <div v-else-if="prStore.issueDetails?.body" class="pr-body" v-html="renderMarkdown(prStore.issueDetails.body)"></div>
                <div v-else class="empty-state" style="padding:var(--space-5)"><p>无详细描述</p></div>
              </div>
            </template>

            <!-- AI Summary tab -->
            <template v-if="prStore.issueDetailTab === 'summary'">
              <div v-if="prStore.aiSummaryLoading" class="detail-loading">AI 总结生成中…</div>
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderSummary(prStore.aiSummary)"></div>
              <div v-else class="empty-state" style="padding:var(--space-5)">
                <p>尚未生成 AI 总结</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateSummary('issue')">生成 AI 总结</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
