<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useCommunityStore } from '@/stores/community'
import { useAppStore } from '@/stores/app'
import { usePRCenterStore } from '@/stores/prCenter'
import { useWatchlistStore } from '@/stores/watchlist'
import { renderMarkdown, renderDiff } from '@/composables/useMarkdown'
import { issueType, issueTypeLabel, issueStateLabel, prStateLabel, timeAgo, exactTime } from '@/utils/helpers'
import type { Issue, PR } from '@/utils/types'
import Icon from '@/components/common/Icon.vue'

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

function toggleWatchlist(number: number, type: string, title: string, url: string) {
  watchlistStore.toggleWatch(number, type, title, url)
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">社区动态</h2>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: communityStore.communityTab === 'prs' }"
              @click="communityStore.communityTab = 'prs'">
        PRs <span class="badge">{{ communityStore.prs.length }}</span>
      </button>
      <button class="tab" :class="{ active: communityStore.communityTab === 'issues' }"
              @click="communityStore.communityTab = 'issues'">
        Issues <span class="badge">{{ communityStore.issues.length }}</span>
      </button>
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
      <select v-if="communityStore.communityTab === 'issues'" class="select select-sm" v-model="communityStore.communityIssueArea">
        <option value="">全部领域</option>
        <option v-for="area in appStore.areas" :key="area.id" :value="area.id">{{ area.name }}</option>
      </select>
      <select v-if="communityStore.communityTab === 'prs'" class="select select-sm" v-model="communityStore.communityPRArea">
        <option value="">全部领域</option>
        <option v-for="area in appStore.areas" :key="area.id" :value="area.id">{{ area.name }}</option>
      </select>
    </div>

    <div class="community-list">
      <div v-for="item in displayedItems" :key="item.type + '-' + (item.number || item.pr_number)"
           class="community-item" :class="{ 'is-new': item.is_new }" @click="item.type === 'pr' ? openPR(item) : openIssue(item as Issue)">
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
          <button v-if="item.type === 'issue' && communityStore.labelLoading === item.number" class="btn btn-sm btn-ghost" disabled style="padding:2px 4px;font-size:10px;">标签建议…</button>
          <button v-if="item.type === 'issue' && communityStore.labelLoading !== item.number && !communityStore.labelResult[item.number]" class="btn btn-sm btn-ghost" @click.stop="communityStore.toggleLabelPopover(item)" title="AI 标签建议" style="padding:2px 4px;font-size:10px;">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
          </button>
          <span v-if="item.type === 'issue' && communityStore.labelResult[item.number] && communityStore.labelResult[item.number].length > 0" class="badge-group" @click.stop="communityStore.toggleLabelPopover(item)">
            <span v-for="(label, li) in communityStore.labelResult[item.number].slice(0, 3)" :key="li" class="badge badge-ai-suggest" style="cursor:pointer;font-size:9px;">{{ label }}</span>
          </span>
        </div>
        <div class="item-title-row">
          <h3 class="item-title">{{ item.title }}</h3>
          <button class="btn btn-xs watchlist-star-btn" :class="(item.type === 'pr' ? watchlistStore.findWatchlistItem(item.number || item.pr_number, 'pr') : watchlistStore.findWatchlistItem(item.number, 'issue')) ? 'btn-starred' : 'btn-ghost'"
                  @click.stop="item.type === 'pr'
                    ? toggleWatchlist(item.number || item.pr_number, 'pr', item.title, 'https://github.com/vllm-project/vllm/pull/' + (item.number || item.pr_number))
                    : toggleWatchlist(item.number, 'issue', item.title, 'https://github.com/vllm-project/vllm/issues/' + item.number)"
                  :title="(item.type === 'pr' ? watchlistStore.findWatchlistItem(item.number || item.pr_number, 'pr') : watchlistStore.findWatchlistItem(item.number, 'issue')) ? '取消特别关注' : '加入特别关注'">
            <svg width="14" height="14" viewBox="0 0 24 24" :fill="(item.type === 'pr' ? watchlistStore.findWatchlistItem(item.number || item.pr_number, 'pr') : watchlistStore.findWatchlistItem(item.number, 'issue')) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
          </button>
        </div>
        <div class="item-meta">
          <span class="meta-item">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
            {{ item.author }}
          </span>
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
      <div v-if="displayedItems.length === 0" class="empty-state">
        <div class="empty-icon">∅</div>
        <div class="empty-title">{{ appStore.searchQuery.trim() ? '无匹配结果' : '暂无动态' }}</div>
        <div class="empty-desc" v-if="appStore.searchQuery.trim()">未找到与「{{ appStore.searchQuery }}」匹配的项，试试其他关键词</div>
      </div>
      <button v-if="communityStore.hasMoreCommunity" class="btn btn-sm load-more" @click="loadMore">
        加载更多
      </button>
    </div>

    <!-- PR Drawer (tab-based: details, summary, review, translate) -->
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
              <button class="btn btn-sm btn-icon" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr') }"
                      @click.stop="toggleWatchlist(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr', prStore.selectedPR.title, 'https://github.com/vllm-project/vllm/pull/' + (prStore.selectedPR.pr_number || prStore.selectedPR.number))"
                      :title="watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr') ? '取消关注' : '添加到特别关注'">
                <svg width="14" height="14" viewBox="0 0 24 24" :fill="watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr') ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              <a :href="'https://github.com/vllm-project/vllm/pull/' + (prStore.selectedPR.pr_number || prStore.selectedPR.number)" target="_blank" class="btn btn-sm">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                GitHub
              </a>
              <button class="drawer-close" @click="prStore.closePR()" title="关闭">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>
          <!-- Tab bar -->
          <div class="tab-bar tab-bar-drawer">
            <button class="tab" :class="{ active: prStore.prDetailTab === 'details' }"
                    @click="prStore.prDetailTab = 'details'">详情</button>
            <button class="tab" :class="{ active: prStore.prDetailTab === 'summary' }"
                    @click="prStore.prDetailTab = 'summary'">
              AI 总结
              <span v-if="prStore.aiSummaryLoading" class="badge badge-loading">…</span>
              <span v-else-if="prStore.aiSummary" class="badge badge-done"><Icon name="check" :size="10" /></span>
            </button>
            <button class="tab" :class="{ active: prStore.prDetailTab === 'review' }"
                    @click="prStore.prDetailTab = 'review'">
              AI Review
              <span v-if="prStore.aiReviewLoading" class="badge badge-loading">…</span>
              <span v-else-if="prStore.aiReview" class="badge badge-done"><Icon name="check" :size="10" /></span>
            </button>
          </div>
          <div class="drawer-body">
            <!-- Details tab (with translate toggle) -->
            <template v-if="prStore.prDetailTab === 'details'">
              <div v-if="prStore.loadingDetails" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.prLoadError" class="detail-loading is-error">{{ prStore.prLoadError }}</div>
              <div v-else-if="prStore.prDetails">
                <!-- Watchlist note -->
                <div v-if="prStore.selectedPR?.watchlist_note" class="watchlist-note-detail">
                  <span class="watchlist-note-label">备注</span>
                  <span>{{ prStore.selectedPR.watchlist_note }}</span>
                </div>
                <!-- Translate toggle -->
                <div class="drawer-toolbar">
                  <template v-if="prStore.prTranslatedBody">
                    <button class="btn btn-sm" :class="{ 'btn-active': !prStore.prShowChinese }"
                            @click="prStore.prShowChinese = false">EN</button>
                    <button class="btn btn-sm" :class="{ 'btn-active': prStore.prShowChinese }"
                            @click="prStore.prShowChinese = true">中文</button>
                  </template>
                  <template v-else>
                    <button class="btn btn-sm btn-primary" @click="prStore.translateBody('pr')"
                            :disabled="prStore.translateLoading">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                      {{ prStore.translateLoading ? '翻译中…' : 'AI 翻译' }}
                    </button>
                  </template>
                </div>
                <div v-if="prStore.prShowChinese && prStore.prTranslatedBody" class="pr-body" v-html="renderMarkdown(prStore.prTranslatedBody)"></div>
                <div v-else-if="prStore.prDetails.pr?.body" class="pr-body" v-html="renderMarkdown(prStore.prDetails.pr.body)"></div>
                <div v-else class="empty-state is-compact"><p>无详细描述</p></div>

                <!-- Changed files list -->
                <template v-if="prStore.prDetails.files && prStore.prDetails.files.length > 0">
                  <h4 class="section-heading">
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
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderMarkdown(prStore.aiSummary)"></div>
              <div v-else class="empty-state is-compact">
                <p>尚未生成 AI 总结</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateSummary('pr')">生成 AI 总结</button>
              </div>
            </template>

            <!-- AI Review tab -->
            <template v-if="prStore.prDetailTab === 'review'">
              <div v-if="prStore.aiReviewLoading" class="detail-loading">AI Review 生成中… ({{ prStore.aiReviewElapsed }}s)</div>
              <div v-else-if="prStore.aiReview" class="ai-section-body" v-html="renderMarkdown(prStore.aiReview)"></div>
              <div v-else class="empty-state is-compact">
                <p>尚未生成 AI Review</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateReview()">生成 AI Review</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Issue Drawer (tab-based: details, summary, translate) -->
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
              <button class="btn btn-sm btn-icon" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue') }"
                      @click.stop="toggleWatchlist(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.title, 'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number)"
                      :title="watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue') ? '取消关注' : '添加到特别关注'">
                <svg width="14" height="14" viewBox="0 0 24 24" :fill="watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue') ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              <a :href="'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number" target="_blank" class="btn btn-sm">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                GitHub
              </a>
              <button class="drawer-close" @click="prStore.closeIssue()" title="关闭">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>
          <!-- Tab bar -->
          <div class="tab-bar tab-bar-drawer">
            <button class="tab" :class="{ active: prStore.issueDetailTab === 'details' }"
                    @click="prStore.issueDetailTab = 'details'">详情</button>
            <button class="tab" :class="{ active: prStore.issueDetailTab === 'summary' }"
                    @click="prStore.issueDetailTab = 'summary'">
              AI 总结
              <span v-if="prStore.aiSummaryLoading" class="badge badge-loading">…</span>
              <span v-else-if="prStore.aiSummary" class="badge badge-done"><Icon name="check" :size="10" /></span>
            </button>
          </div>
          <div class="drawer-body">
            <!-- Details tab (with translate toggle) -->
            <template v-if="prStore.issueDetailTab === 'details'">
              <div v-if="prStore.loadingIssue" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.issueLoadError" class="detail-loading is-error">{{ prStore.issueLoadError }}</div>
              <div v-else>
                <!-- Watchlist note -->
                <div v-if="prStore.selectedIssue?.watchlist_note" class="watchlist-note-detail">
                  <span class="watchlist-note-label">备注</span>
                  <span>{{ prStore.selectedIssue.watchlist_note }}</span>
                </div>
                <!-- Translate toggle -->
                <div class="drawer-toolbar">
                  <template v-if="prStore.issueTranslatedBody">
                    <button class="btn btn-sm" :class="{ 'btn-active': prStore.issueShowChinese }"
                            @click="prStore.issueShowChinese = true">中文</button>
                    <button class="btn btn-sm" :class="{ 'btn-active': !prStore.issueShowChinese }"
                            @click="prStore.issueShowChinese = false">EN</button>
                  </template>
                  <template v-else>
                    <button class="btn btn-sm btn-primary" @click="prStore.translateBody('issue')"
                            :disabled="prStore.translateLoading">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                      {{ prStore.translateLoading ? '翻译中…' : 'AI 翻译' }}
                    </button>
                  </template>
                </div>
                <div v-if="prStore.issueShowChinese && prStore.issueTranslatedBody" class="pr-body" v-html="renderMarkdown(prStore.issueTranslatedBody)"></div>
                <div v-else-if="prStore.issueDetails?.body" class="pr-body" v-html="renderMarkdown(prStore.issueDetails.body)"></div>
                <div v-else class="empty-state is-compact"><p>无详细描述</p></div>
              </div>
            </template>

            <!-- AI Summary tab -->
            <template v-if="prStore.issueDetailTab === 'summary'">
              <div v-if="prStore.aiSummaryLoading" class="detail-loading">AI 总结生成中…</div>
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderMarkdown(prStore.aiSummary)"></div>
              <div v-else class="empty-state is-compact">
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
