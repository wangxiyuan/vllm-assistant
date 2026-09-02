<script setup lang="ts">
import { usePRCenterStore } from '@/stores/prCenter'
import { useWatchlistStore } from '@/stores/watchlist'
import { renderMarkdown } from '@/composables/useMarkdown'
import { ghUrl } from '@/utils/helpers'
import Icon from '@/components/common/Icon.vue'

const prStore = usePRCenterStore()
const watchlistStore = useWatchlistStore()

function toggleWatchlist(number: number, type: string, title: string, url: string, extra?: any) {
  watchlistStore.toggleWatch(number, type, title, url, extra)
}

</script>

<template>
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
            <button class="btn btn-sm btn-icon" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.repo) }"
                    @click.stop="toggleWatchlist(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.title, ghUrl(prStore.selectedIssue.repo, prStore.selectedIssue.number, 'issue'), { repo: prStore.selectedIssue.repo })"
                    :title="watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.repo) ? '取消关注' : '添加到特别关注'">
              <svg width="14" height="14" viewBox="0 0 24 24" :fill="watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.repo) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </button>
            <a :href="ghUrl(prStore.selectedIssue.repo, prStore.selectedIssue.number, 'issue')" target="_blank" class="btn btn-sm">
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
                <span class="watchlist-note-text">{{ prStore.selectedIssue.watchlist_note }}</span>
              </div>
              <div class="drawer-toolbar">
                <template v-if="prStore.issueTranslatedBody">
                  <button class="btn btn-sm" :class="{ 'btn-active': !prStore.issueShowChinese }" @click="prStore.issueShowChinese = false">EN</button>
                  <button class="btn btn-sm" :class="{ 'btn-active': prStore.issueShowChinese }" @click="prStore.issueShowChinese = true">中文</button>
                </template>
                <template v-else>
                  <button class="btn btn-sm btn-primary" @click="prStore.translateBody('issue')" :disabled="prStore.translateLoading">
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
</template>
