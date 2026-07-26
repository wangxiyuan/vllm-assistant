<script setup lang="ts">
import { onMounted } from 'vue'
import { useWatchlistStore } from '@/stores/watchlist'
import { usePRCenterStore } from '@/stores/prCenter'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { renderMarkdown, renderSummary, renderReview } from '@/composables/useMarkdown'
import { timeAgo } from '@/utils/helpers'

const watchlistStore = useWatchlistStore()
const prStore = usePRCenterStore()
const appStore = useAppStore()
const usersStore = useUsersStore()

onMounted(() => {
  watchlistStore.loadWatchlist()
})

function openWatchlistItem(w: any) {
  if (w.item_type === 'pr') {
    prStore.openPR({ pr_number: w.number, title: w.title, url: w.url, state: w.state || 'open', watchlist_note: w.note || '', watchlist_assignee_id: w.assignee_id || null })
  } else {
    prStore.openIssue({ number: w.number, title: w.title, url: w.url, state: w.state || 'open', watchlist_note: w.note || '', watchlist_assignee_id: w.assignee_id || null })
  }
}

function toggleWatchlist(number: number, type: string, title: string, url: string) {
  watchlistStore.toggleWatch(number, type, title, url)
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">特别关注</h2>
      <div class="view-actions">
        <span class="count" style="margin-right:12px;">{{ watchlistStore.watchlist.length }} 项</span>
        <button class="btn btn-primary btn-sm" @click="watchlistStore.openAddModal()">+ 添加关注</button>
      </div>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'pr' }"
              @click="watchlistStore.watchlistTab = 'pr'">PR <span class="badge">{{ watchlistStore.watchlist.filter(w => w.item_type === 'pr').length }}</span></button>
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'issue' }"
              @click="watchlistStore.watchlistTab = 'issue'">Issue <span class="badge">{{ watchlistStore.watchlist.filter(w => w.item_type === 'issue').length }}</span></button>
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'all' }"
              @click="watchlistStore.watchlistTab = 'all'">全部</button>
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
        <div v-if="w.linked_tasks && w.linked_tasks.length > 0" class="item-meta" style="margin-top:4px;">
          <span style="font-size:10px;color:var(--text-tertiary);">关联任务：</span>
          <span v-for="lt in w.linked_tasks" :key="lt.id" class="ref-badge" style="font-size:10px;">
            <span>#{{ lt.id }}</span>
            <span>{{ lt.title?.length > 20 ? lt.title.slice(0, 20) + '…' : lt.title }}</span>
          </span>
        </div>
        <div class="item-actions">
          <button class="btn btn-sm" @click.stop="watchlistStore.openEditModal(w)">编辑</button>
          <button class="btn btn-sm btn-ghost" @click.stop="watchlistStore.toggleWatch(w.number, w.item_type, w.title, w.url)">移除</button>
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
          <h3 class="modal-title">添加特别关注</h3>
          <div class="form-group">
            <label class="form-label">Issue/PR 编号</label>
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
          <div class="modal-actions">
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
          <h3 class="modal-title">编辑关注</h3>
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
          <div class="modal-actions">
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
              <button class="btn btn-sm" :class="{ 'btn-starred': watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr') }"
                      @click.stop="toggleWatchlist(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr', prStore.selectedPR.title, 'https://github.com/vllm-project/vllm/pull/' + (prStore.selectedPR.pr_number || prStore.selectedPR.number))"
                      :title="watchlistStore.findWatchlistItem(prStore.selectedPR.pr_number || prStore.selectedPR.number, 'pr') ? '取消关注' : '添加到特别关注'">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              <a :href="'https://github.com/vllm-project/vllm/pull/' + (prStore.selectedPR.pr_number || prStore.selectedPR.number)" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closePR()">&times;</button>
            </div>
          </div>
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
            <template v-if="prStore.prDetailTab === 'details'">
              <div v-if="prStore.loadingDetails" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.prLoadError" class="detail-loading" style="color:var(--signal-red)">{{ prStore.prLoadError }}</div>
              <div v-else-if="prStore.prDetails">
                <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)">
                  <template v-if="prStore.prTranslatedBody">
                    <button class="btn btn-sm" :class="{ 'btn-active': !prStore.prShowChinese }" @click="prStore.prShowChinese = false">EN</button>
                    <button class="btn btn-sm" :class="{ 'btn-active': prStore.prShowChinese }" @click="prStore.prShowChinese = true">中文</button>
                  </template>
                  <template v-else>
                    <button class="btn btn-sm" @click="prStore.translateBody('pr')" :disabled="prStore.translateLoading">
                      {{ prStore.translateLoading ? '翻译中…' : 'AI 翻译' }}
                    </button>
                  </template>
                </div>
                <div v-if="prStore.prShowChinese && prStore.prTranslatedBody" class="pr-body" v-html="renderMarkdown(prStore.prTranslatedBody)"></div>
                <div v-else-if="prStore.prDetails.pr?.body" class="pr-body" v-html="renderMarkdown(prStore.prDetails.pr.body)"></div>
                <div v-else class="empty-state" style="padding:var(--space-5)"><p>无详细描述</p></div>
              </div>
            </template>
            <template v-if="prStore.prDetailTab === 'summary'">
              <div v-if="prStore.aiSummaryLoading" class="detail-loading">AI 总结生成中…</div>
              <div v-else-if="prStore.aiSummary" class="ai-section-body" v-html="renderSummary(prStore.aiSummary)"></div>
              <div v-else class="empty-state" style="padding:var(--space-5)">
                <p>尚未生成 AI 总结</p>
                <button class="btn btn-sm btn-primary" @click="prStore.generateSummary('pr')">生成 AI 总结</button>
              </div>
            </template>
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
                      @click.stop="toggleWatchlist(prStore.selectedIssue.number, 'issue', prStore.selectedIssue.title, 'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number)"
                      :title="watchlistStore.findWatchlistItem(prStore.selectedIssue.number, 'issue') ? '取消关注' : '添加到特别关注'">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
              </button>
              <a :href="'https://github.com/vllm-project/vllm/issues/' + prStore.selectedIssue.number" target="_blank" class="btn btn-sm">在 GitHub 打开</a>
              <button class="btn btn-sm btn-ghost" @click="prStore.closeIssue()">&times;</button>
            </div>
          </div>
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
            <template v-if="prStore.issueDetailTab === 'details'">
              <div v-if="prStore.loadingIssue" class="detail-loading">加载中…</div>
              <div v-else-if="prStore.issueLoadError" class="detail-loading" style="color:var(--signal-red)">{{ prStore.issueLoadError }}</div>
              <div v-else>
                <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)">
                  <template v-if="prStore.issueTranslatedBody">
                    <button class="btn btn-sm" :class="{ 'btn-active': !prStore.issueShowChinese }" @click="prStore.issueShowChinese = false">EN</button>
                    <button class="btn btn-sm" :class="{ 'btn-active': prStore.issueShowChinese }" @click="prStore.issueShowChinese = true">中文</button>
                  </template>
                  <template v-else>
                    <button class="btn btn-sm" @click="prStore.translateBody('issue')" :disabled="prStore.translateLoading">
                      {{ prStore.translateLoading ? '翻译中…' : 'AI 翻译' }}
                    </button>
                  </template>
                </div>
                <div v-if="prStore.issueShowChinese && prStore.issueTranslatedBody" class="pr-body" v-html="renderMarkdown(prStore.issueTranslatedBody)"></div>
                <div v-else-if="prStore.issueDetails?.body" class="pr-body" v-html="renderMarkdown(prStore.issueDetails.body)"></div>
                <div v-else class="empty-state" style="padding:var(--space-5)"><p>无详细描述</p></div>
              </div>
            </template>
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