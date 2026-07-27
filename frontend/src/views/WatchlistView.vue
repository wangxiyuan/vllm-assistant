<script setup lang="ts">
import { onMounted } from 'vue'
import { useWatchlistStore } from '@/stores/watchlist'
import { usePRCenterStore } from '@/stores/prCenter'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { useTodoStore } from '@/stores/todo'
import { renderMarkdown, renderSummary, renderReview, renderDiff } from '@/composables/useMarkdown'
import { timeAgo, statusLabel, sourceLabel, priorityClass, statusClass } from '@/utils/helpers'

const watchlistStore = useWatchlistStore()
const prStore = usePRCenterStore()
const appStore = useAppStore()
const usersStore = useUsersStore()
const todoStore = useTodoStore()

onMounted(() => {
  watchlistStore.loadWatchlist()
})

function openWatchlistItem(w: any) {
  if (w.item_type === 'pr') {
    prStore.openPR({ pr_number: w.number, title: w.title, url: w.url, state: w.state || 'open', watchlist_note: w.note || '', watchlist_assignee_id: w.assignee_id || null, linked_tasks: w.linked_tasks || [] })
  } else {
    prStore.openIssue({ number: w.number, title: w.title, url: w.url, state: w.state || 'open', watchlist_note: w.note || '', watchlist_assignee_id: w.assignee_id || null, linked_tasks: w.linked_tasks || [] })
  }
}

function openTaskDrawer(task: any) {
  // linked_tasks 只包含部分字段，构造一个最小 TodoTask 对象传给 openTask
  todoStore.openTask({ id: task.id, title: task.title, status: task.status || 'todo', priority: task.priority || 'P2', source: 'self', created_at: '', updated_at: '' })
}

function openUrl(url: string) {
  window.open(url, '_blank')
}

function toggleWatchlist(number: number, type: string, title: string, url: string) {
  watchlistStore.toggleWatch(number, type, title, url)
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">
        特别关注
        <span class="count" style="font-family:var(--font-mono);font-size:var(--text-sm);color:var(--text-tertiary);font-weight:400;margin-left:12px;">{{ watchlistStore.watchlist.length }} 项</span>
      </h2>
      <div class="view-actions">
        <button class="btn btn-primary btn-sm" @click="watchlistStore.openAddModal()">+ 添加关注</button>
      </div>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'pr' }"
              @click="watchlistStore.watchlistTab = 'pr'">PR <span class="badge">{{ watchlistStore.watchlist.filter(w => w.item_type === 'pr').length }}</span></button>
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'issue' }"
              @click="watchlistStore.watchlistTab = 'issue'">Issue <span class="badge">{{ watchlistStore.watchlist.filter(w => w.item_type === 'issue').length }}</span></button>
    </div>

    <div class="community-filters" style="margin-bottom:var(--space-4)">
      <select class="select select-sm" v-model.number="watchlistStore.watchlistAssigneeFilter">
        <option :value="null">全部责任人</option>
        <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
      </select>
    </div>

    <div class="watchlist-list">
      <div v-for="w in watchlistStore.filteredWatchlist" :key="w.item_type + '-' + w.number" class="watchlist-item" @click="openWatchlistItem(w)">
        <div class="item-header">
          <span class="item-type-badge" :class="w.item_type === 'pr' ? 'badge-pr' : 'badge-issue'">
            {{ w.item_type === 'pr' ? 'PR' : 'ISSUE' }}
          </span>
          <span class="item-number">#{{ w.number }}</span>
          <span v-if="w.state" class="item-state" :class="'state-' + w.state">
            {{ w.state === 'merged' ? '已合并' : w.state === 'open' ? '开放' : '已关闭' }}
          </span>
          <span v-if="w.item_type === 'issue' && w.issue_type && w.issue_type !== 'other'" class="badge badge-issue-type">{{ w.issue_type }}</span>
          <span v-if="w.area" class="badge badge-area">{{ w.area }}</span>
        </div>
        <h3 class="item-title">{{ w.title }}</h3>
        <div class="item-meta">
          <span v-if="w.assignee_id" class="badge badge-assignee">{{ usersStore.userName(w.assignee_id) }}</span>
          <span>{{ timeAgo(w.added_at) }} 加入</span>
          <span v-if="w.note" class="watchlist-note">📝 {{ w.note }}</span>
        </div>
        <div v-if="w.linked_tasks && w.linked_tasks.length > 0" class="item-meta linked-tasks-row" style="margin-top:4px;">
          <span class="linked-tasks-label">关联任务：</span>
          <span v-for="lt in w.linked_tasks" :key="lt.id" class="ref-badge ref-badge-sm">
            <span>#{{ lt.id }}</span>
            <span>{{ lt.title?.length > 20 ? lt.title.slice(0, 20) + '…' : lt.title }}</span>
          </span>
        </div>
        <div class="item-actions">
          <button class="card-action-btn" @click.stop="watchlistStore.openEditModal(w)" title="编辑备注/责任人">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            编辑
          </button>
          <button class="card-action-btn is-danger" @click.stop="watchlistStore.toggleWatch(w.number, w.item_type, w.title, w.url)" title="移除关注">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            移除
          </button>
        </div>
      </div>
      <div v-if="watchlistStore.filteredWatchlist.length === 0" class="empty-state">
        <p>暂无关注项</p>
        <button class="btn btn-primary btn-sm" @click="watchlistStore.openAddModal()">添加第一个关注</button>
      </div>
    </div>

    <!-- Add Watchlist Modal -->
    <Teleport to="body">
      <div v-if="watchlistStore.showAddModal" class="modal-backdrop" @click="watchlistStore.closeAddModal()">
        <div class="modal" @click.stop>
          <div class="modal-header">
            <h3>添加特别关注</h3>
            <button class="modal-close" @click="watchlistStore.closeAddModal()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label form-label-required">Issue/PR 编号</label>
              <input type="number" class="input" v-model.number="watchlistStore.manualAddNumber"
                     placeholder="输入 GitHub issue/PR 编号" />
            </div>
            <div class="form-group">
              <label class="form-label">备注</label>
              <input type="text" class="input" v-model="watchlistStore.manualAddNote" placeholder="可选备注" />
            </div>
            <div class="form-group">
              <label class="form-label">责任人</label>
              <select class="select" v-model.number="watchlistStore.manualAddAssigneeId">
                <option :value="null">无</option>
                <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
              </select>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="watchlistStore.closeAddModal()">取消</button>
            <button class="btn btn-primary" :disabled="watchlistStore.manualAddLoading"
                    @click="watchlistStore.addWatchlistByNumber()">
              {{ watchlistStore.manualAddLoading ? '添加中…' : '添加' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Watchlist Modal -->
    <Teleport to="body">
      <div v-if="watchlistStore.showEditModal" class="modal-backdrop" @click="watchlistStore.closeEditModal()">
        <div class="modal" @click.stop>
          <div class="modal-header">
            <h3>编辑关注</h3>
            <button class="modal-close" @click="watchlistStore.closeEditModal()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">备注</label>
              <textarea class="textarea" v-model="watchlistStore.watchlistEditNote" rows="2"></textarea>
            </div>
            <div class="form-group">
              <label class="form-label">责任人</label>
              <select class="select" v-model.number="watchlistStore.watchlistEditAssigneeId">
                <option :value="null">无</option>
                <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
              </select>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="watchlistStore.closeEditModal()">取消</button>
            <button class="btn btn-primary" :disabled="watchlistStore.watchlistEditSaving"
                    @click="watchlistStore.saveWatchlistItem()">
              {{ watchlistStore.watchlistEditSaving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

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
          <div class="tab-bar tab-bar-drawer">
            <button class="tab" :class="{ active: prStore.prDetailTab === 'details' }"
                    @click="prStore.prDetailTab = 'details'">详情</button>
            <button class="tab" :class="{ active: prStore.prDetailTab === 'summary' }"
                    @click="prStore.prDetailTab = 'summary'">
              AI 总结
              <span v-if="prStore.aiSummaryLoading" class="badge badge-loading">…</span>
              <span v-else-if="prStore.aiSummary" class="badge badge-done">✓</span>
            </button>
            <button class="tab" :class="{ active: prStore.prDetailTab === 'review' }"
                    @click="prStore.prDetailTab = 'review'">
              AI Review
              <span v-if="prStore.aiReviewLoading" class="badge badge-loading">…</span>
              <span v-else-if="prStore.aiReview" class="badge badge-done">✓</span>
            </button>
          </div>
          <div class="drawer-body">
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
            <template v-if="prStore.prDetailTab === 'summary'">
              <div v-if="prStore.aiSummaryLoading" class="detail-loading">AI 总结生成中…</div>
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderSummary(prStore.aiSummary)"></div>
              <div v-else class="empty-state is-compact">
                <p>尚未生成 AI 总结</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateSummary('pr')">生成 AI 总结</button>
              </div>
            </template>
            <template v-if="prStore.prDetailTab === 'review'">
              <div v-if="prStore.aiReviewLoading" class="detail-loading">AI Review 生成中… ({{ prStore.aiReviewElapsed }}s)</div>
              <div v-else-if="prStore.aiReview" class="ai-section-body" v-html="renderReview(prStore.aiReview)"></div>
              <div v-else class="empty-state is-compact">
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
          <div class="tab-bar tab-bar-drawer">
            <button class="tab" :class="{ active: prStore.issueDetailTab === 'details' }"
                    @click="prStore.issueDetailTab = 'details'">详情</button>
            <button class="tab" :class="{ active: prStore.issueDetailTab === 'summary' }"
                    @click="prStore.issueDetailTab = 'summary'">
              AI 总结
              <span v-if="prStore.aiSummaryLoading" class="badge badge-loading">…</span>
              <span v-else-if="prStore.aiSummary" class="badge badge-done">✓</span>
            </button>
          </div>
          <div class="drawer-body">
            <template v-if="prStore.issueDetailTab === 'details'">
              <div v-if="prStore.loadingIssue" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.issueLoadError" class="detail-loading is-error">{{ prStore.issueLoadError }}</div>
              <div v-else>
                <!-- Watchlist note -->
                <div v-if="prStore.selectedIssue?.watchlist_note" class="watchlist-note-detail">
                  <span class="watchlist-note-label">备注</span>
                  <span class="watchlist-note-text">{{ prStore.selectedIssue.watchlist_note }}</span>
                </div>
                <!-- Linked tasks -->
                <div v-if="prStore.selectedIssue?.linked_tasks && prStore.selectedIssue.linked_tasks.length > 0" class="linked-tasks-detail">
                  <span class="linked-tasks-label">关联任务</span>
                  <div class="linked-tasks-list">
                    <span v-for="lt in prStore.selectedIssue.linked_tasks" :key="lt.id" class="ref-badge ref-badge-sm clickable" @click.stop="openTaskDrawer(lt)">
                      <span>#{{ lt.id }}</span>
                      <span>{{ lt.title }}</span>
                    </span>
                  </div>
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
            <template v-if="prStore.issueDetailTab === 'summary'">
              <div v-if="prStore.aiSummaryLoading" class="detail-loading">AI 总结生成中…</div>
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderSummary(prStore.aiSummary)"></div>
              <div v-else class="empty-state is-compact">
                <p>尚未生成 AI 总结</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateSummary('issue')">生成 AI 总结</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Task Drawer (from linked tasks) -->
    <Teleport to="body">
      <div v-if="todoStore.selectedTask" class="drawer-backdrop" @click="todoStore.closeTask()">
        <div class="drawer" @click.stop>
          <div class="drawer-header">
            <div class="drawer-title">
              <div class="pr-id">
                <span>#{{ todoStore.selectedTask.id }}</span>
                <span style="margin-left:8px;"><span class="status-badge" :class="statusClass(todoStore.selectedTask.status)" v-text="statusLabel(todoStore.selectedTask.status)"></span></span>
              </div>
              <h2>{{ todoStore.selectedTask.title }}</h2>
            </div>
            <button class="drawer-close" @click="todoStore.closeTask()" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="drawer-body">
            <div v-if="todoStore.taskDrawerLoading" class="detail-loading">加载中…</div>
            <template v-else-if="todoStore.selectedTaskDetails">
              <div class="detail-section item-meta" style="margin-bottom:var(--space-4);">
                <span class="priority-badge" :class="priorityClass(todoStore.selectedTaskDetails.priority)">{{ todoStore.selectedTaskDetails.priority }}</span>
                <span class="status-badge" :class="statusClass(todoStore.selectedTaskDetails.status)">{{ statusLabel(todoStore.selectedTaskDetails.status) }}</span>
                <span class="badge badge-source" :class="'source-' + todoStore.selectedTaskDetails.source">{{ sourceLabel(todoStore.selectedTaskDetails.source) }}</span>
                <span v-if="todoStore.selectedTaskDetails.assignee_id" class="badge badge-assignee">{{ usersStore.userName(todoStore.selectedTaskDetails.assignee_id) }}</span>
                <span v-if="todoStore.selectedTaskDetails.area" class="meta-item">{{ todoStore.selectedTaskDetails.area }}</span>
              </div>
              <div v-if="todoStore.selectedTaskDetails.description" class="detail-desc">
                {{ todoStore.selectedTaskDetails.description }}
              </div>
              <div v-if="todoStore.selectedTaskDetails.related_refs && todoStore.selectedTaskDetails.related_refs.length > 0" style="margin-bottom:var(--space-4);">
                <label class="form-label">关联引用</label>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                  <span v-for="(ref, idx) in todoStore.selectedTaskDetails.related_refs" :key="idx" class="ref-badge clickable" @click="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)">
                    <span class="ref-type" :class="'ref-type-' + ref.type">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                    <span>{{ ref.repo }}#{{ ref.number }}</span>
                  </span>
                </div>
              </div>
              <div v-if="todoStore.subtasks.length > 0" style="margin-bottom:var(--space-4);">
                <label class="form-label">子任务 ({{ todoStore.subtaskProgressText }})</label>
                <div class="subtask-list">
                  <div v-for="st in todoStore.subtasks" :key="st.id" class="subtask-item">
                    <label class="subtask-checkbox">
                      <input type="checkbox" :checked="st.status === 'done'" @change="todoStore.toggleSubtaskDone(st)" />
                    </label>
                    <div class="subtask-content">
                      <span class="subtask-title" :class="{ 'task-done': st.status === 'done' }">{{ st.title }}</span>
                      <div class="subtask-meta">
                        <span class="priority-badge" :class="priorityClass(st.priority)">{{ st.priority }}</span>
                        <span v-if="st.related_refs && st.related_refs.length > 0" style="display:inline-flex;gap:3px;flex-wrap:wrap;margin-left:4px;">
                          <span v-for="(ref, idx) in st.related_refs.slice(0, 3)" :key="idx" class="ref-badge clickable" @click.stop="openUrl(ref.url)" :title="ref.title || (ref.repo + '#' + ref.number)" style="font-size:10px;padding:1px 4px;">
                            <span class="ref-type" :class="'ref-type-' + ref.type" style="font-size:9px;">{{ ref.type === 'pr' ? 'PR' : 'I' }}</span>
                            <span>{{ ref.repo }}#{{ ref.number }}</span>
                          </span>
                          <span v-if="st.related_refs.length > 3" class="badge badge-subtask" style="font-size:10px;">+{{ st.related_refs.length - 3 }}</span>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            <div v-else class="detail-loading">加载中…</div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>