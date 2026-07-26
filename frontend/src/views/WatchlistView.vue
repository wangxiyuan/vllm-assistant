<script setup lang="ts">
import { onMounted } from 'vue'
import { useWatchlistStore } from '@/stores/watchlist'
import { usePRCenterStore } from '@/stores/prCenter'
import { useAppStore } from '@/stores/app'
import { timeAgo } from '@/utils/helpers'

const watchlistStore = useWatchlistStore()
const prStore = usePRCenterStore()
const appStore = useAppStore()

onMounted(() => {
  watchlistStore.loadWatchlist()
})
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">特别关注</h2>
      <div class="view-actions">
        <button class="btn btn-primary btn-sm" @click="watchlistStore.openAddModal()">+ 添加关注</button>
      </div>
    </div>

    <div class="tab-bar" style="margin-bottom:var(--space-5)">
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'pr' }"
              @click="watchlistStore.watchlistTab = 'pr'">PR</button>
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'issue' }"
              @click="watchlistStore.watchlistTab = 'issue'">Issue</button>
      <button class="tab" :class="{ active: watchlistStore.watchlistTab === 'all' }"
              @click="watchlistStore.watchlistTab = 'all'">全部</button>
    </div>

    <div class="watchlist-list">
      <div v-for="w in watchlistStore.filteredWatchlist" :key="w.item_type + '-' + w.number" class="watchlist-item">
        <div class="item-header">
          <span class="item-type-badge" :class="w.item_type === 'pr' ? 'badge-pr' : 'badge-issue'">
            {{ w.item_type === 'pr' ? 'PR' : 'ISSUE' }}
          </span>
          <span class="item-number">#{{ w.number }}</span>
          <span v-if="w.state" class="item-state" :class="'state-' + w.state">
            {{ w.state === 'merged' ? '已合并' : w.state === 'open' ? '开放' : '已关闭' }}
          </span>
        </div>
        <h3 class="item-title">{{ w.title }}</h3>
        <div class="item-meta">
          <span>{{ timeAgo(w.added_at) }} 加入</span>
          <span v-if="w.note" class="watchlist-note">📝 {{ w.note }}</span>
        </div>
        <div class="item-actions">
          <a :href="w.url" target="_blank" class="btn btn-sm">打开</a>
          <button class="btn btn-sm" @click="watchlistStore.openEditModal(w)">编辑</button>
          <button class="btn btn-sm btn-ghost" @click="watchlistStore.toggleWatch(w.number, w.item_type, w.title, w.url)">移除</button>
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
  </div>
</template>
