<script setup lang="ts">
import { usePRCenterStore } from '@/stores/prCenter'
import { useWatchlistStore } from '@/stores/watchlist'
import { useTodoStore } from '@/stores/todo'
import { useUsersStore } from '@/stores/users'
import { renderMarkdown, renderDiff } from '@/composables/useMarkdown'
import { ghUrl } from '@/utils/helpers'
import Icon from '@/components/common/Icon.vue'

const prStore = usePRCenterStore()
const watchlistStore = useWatchlistStore()
const todoStore = useTodoStore()
const usersStore = useUsersStore()

function toggleWatchlist(number: number, type: string, title: string, url: string, extra?: any) {
  watchlistStore.toggleWatch(number, type, title, url, extra)
}

function openTaskDrawer(task: any) {
  todoStore.openTask({ id: task.id, title: task.title, status: task.status || 'todo', priority: task.priority || 'P2', source: 'self', created_at: '', updated_at: '' })
}
</script>

<template>
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
            <button class="btn btn-sm btn-icon" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr', prStore.selectedPR.repo) }"
                    @click.stop="toggleWatchlist(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr', prStore.selectedPR.title, ghUrl(prStore.selectedPR.repo, prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr'), { repo: prStore.selectedPR.repo })"
                    :title="watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr', prStore.selectedPR.repo) ? '取消关注' : '添加到特别关注'">
              <svg width="14" height="14" viewBox="0 0 24 24" :fill="watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr', prStore.selectedPR.repo) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </button>
            <a :href="ghUrl(prStore.selectedPR.repo, prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr')" target="_blank" class="btn btn-sm">
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
                <span class="watchlist-note-text">{{ prStore.selectedPR.watchlist_note }}</span>
              </div>
              <!-- Linked tasks -->
              <div v-if="prStore.selectedPR?.linked_tasks && prStore.selectedPR.linked_tasks.length > 0" class="linked-tasks-detail">
                <span class="linked-tasks-label">关联任务</span>
                <div class="linked-tasks-list">
                  <span v-for="lt in prStore.selectedPR.linked_tasks" :key="lt.id" class="ref-badge ref-badge-sm clickable" @click.stop="openTaskDrawer(lt)">
                    <span>#{{ lt.id }}</span>
                    <span>{{ lt.title }}</span>
                  </span>
                </div>
              </div>
              <div class="drawer-toolbar">
                <template v-if="prStore.prTranslatedBody">
                  <button class="btn btn-sm" :class="{ 'btn-active': !prStore.prShowChinese }" @click="prStore.prShowChinese = false">EN</button>
                  <button class="btn btn-sm" :class="{ 'btn-active': prStore.prShowChinese }" @click="prStore.prShowChinese = true">中文</button>
                </template>
                <template v-else>
                  <button class="btn btn-sm btn-primary" @click="prStore.translateBody('pr')" :disabled="prStore.translateLoading">
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
</template>
