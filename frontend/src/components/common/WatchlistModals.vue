<script setup lang="ts">
import { useWatchlistStore } from '@/stores/watchlist'
import { useUsersStore } from '@/stores/users'
import { useReposStore } from '@/stores/repos'

const watchlistStore = useWatchlistStore()
const usersStore = useUsersStore()
const reposStore = useReposStore()
</script>

<template>
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
            <label class="form-label form-label-required">项目</label>
            <select class="select" v-model="watchlistStore.manualAddRepo">
              <option value="" disabled>请选择项目</option>
              <option v-for="r in reposStore.repos" :key="r.id" :value="r.repo">{{ r.repo }}</option>
            </select>
          </div>
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
</template>
