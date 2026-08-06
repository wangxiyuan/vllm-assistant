<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useCommentsStore } from '@/stores/comments'
import { useUsersStore } from '@/stores/users'
import { timeAgo } from '@/utils/helpers'

const props = defineProps<{
  targetType: 'article' | 'report'
  targetId: number
}>()

const commentsStore = useCommentsStore()
const usersStore = useUsersStore()

const newComment = ref('')
const selectedUserId = ref<number | null>(null)
const editingId = ref<number | null>(null)
const editingContent = ref('')

onMounted(() => {
  commentsStore.loadComments(props.targetType, props.targetId)
  usersStore.loadUsers()
  const saved = localStorage.getItem('comment_user_id')
  if (saved) selectedUserId.value = parseInt(saved, 10)
})

onUnmounted(() => {
  commentsStore.clearComments()
})

function submitComment() {
  const text = newComment.value.trim()
  if (!text || selectedUserId.value === null) return
  commentsStore.addComment(props.targetType, props.targetId, text, selectedUserId.value)
  newComment.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
  }
}

function startEdit(comment: any) {
  editingId.value = comment.id
  editingContent.value = comment.content
}

function cancelEdit() {
  editingId.value = null
  editingContent.value = ''
}

function saveEdit(comment: any) {
  const text = editingContent.value.trim()
  if (!text) return
  commentsStore.editComment(comment.id, text)
  editingId.value = null
}

function changeUser() {
  selectedUserId.value = null
}

function onUserSelected() {
  if (selectedUserId.value !== null) {
    localStorage.setItem('comment_user_id', String(selectedUserId.value))
  }
}
</script>

<template>
  <div class="comment-section">
    <h3 class="comment-section-title">评论</h3>

    <div v-if="commentsStore.loading" class="comment-loading">加载中…</div>
    <div v-else-if="commentsStore.comments.length === 0" class="comment-empty">
      还没有评论，来说点什么吧
    </div>
    <div v-else class="comment-list">
      <div v-for="comment in commentsStore.comments" :key="comment.id" class="comment-item">
        <div class="comment-header">
          <span class="comment-author">{{ comment.user_name || '匿名' }}</span>
          <span class="comment-time">{{ timeAgo(comment.updated_at) }}</span>
          <div class="comment-actions">
            <button class="card-action-btn" @click="startEdit(comment)" title="编辑">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="card-action-btn is-danger" @click="commentsStore.removeComment(comment.id)" title="删除">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </div>
        </div>
        <div v-if="editingId === comment.id" class="comment-edit-area">
          <textarea class="textarea comment-textarea" v-model="editingContent" maxlength="2000" @keydown="(e: KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(comment) } }"></textarea>
          <div class="comment-input-footer">
            <span class="comment-char-count">{{ editingContent.length }}/2000</span>
            <div>
              <button class="btn btn-sm" @click="cancelEdit">取消</button>
              <button class="btn btn-primary btn-sm" :disabled="!editingContent.trim()" @click="saveEdit(comment)">保存</button>
            </div>
          </div>
        </div>
        <div v-else class="comment-body" v-html="comment.rendered_html"></div>
      </div>
    </div>

    <div class="comment-input-divider"></div>

    <div class="comment-input-area">
      <div class="comment-user-row">
        <select v-if="selectedUserId === null" class="select select-sm" v-model.number="selectedUserId" @change="onUserSelected">
          <option :value="null" disabled>选择身份</option>
          <option v-for="u in usersStore.users" :key="u.id" :value="u.id">{{ u.name }}</option>
        </select>
        <span v-else class="comment-user-badge">
          以 <strong>{{ usersStore.userName(selectedUserId) }}</strong> 身份评论
          <button class="btn btn-ghost btn-xs" @click="changeUser">[切换]</button>
        </span>
      </div>
      <textarea
        class="textarea comment-textarea"
        v-model="newComment"
        placeholder="写下你的评论…"
        @keydown="handleKeydown"
        maxlength="2000"
      ></textarea>
      <div class="comment-input-footer">
        <span class="comment-char-count">{{ newComment.length }}/2000</span>
        <button class="btn btn-primary btn-sm" :disabled="!newComment.trim() || commentsStore.submitting" @click="submitComment">
          {{ commentsStore.submitting ? '发送中…' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.comment-section {
  margin-top: var(--space-6);
  padding-top: var(--space-6);
  border-top: 1px solid var(--border);
}

.comment-section-title {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.comment-input-divider {
  height: 1px;
  background: var(--border);
  margin: var(--space-5) 0;
}

.comment-input-area {
  margin-bottom: var(--space-5);
}

.comment-user-row {
  margin-bottom: var(--space-2);
}

.comment-user-badge {
  font-size: var(--font-xs);
  color: var(--text-tertiary);
}

.comment-textarea {
  width: 100%;
  min-height: 80px;
  resize: vertical;
}

.comment-input-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--space-2);
}

.comment-char-count {
  font-size: var(--font-xs);
  color: var(--text-tertiary);
}

.comment-loading,
.comment-empty {
  text-align: center;
  color: var(--text-tertiary);
  padding: var(--space-6) 0;
  font-size: var(--font-sm);
}

.comment-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.comment-item {
  padding: var(--space-3);
  background: var(--bg-secondary);
  border-radius: var(--radius);
}

.comment-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.comment-author {
  font-weight: 600;
  font-size: var(--font-sm);
  color: var(--text);
}

.comment-time {
  font-size: var(--font-xs);
  color: var(--text-tertiary);
}

.comment-actions {
  margin-left: auto;
  display: flex;
  gap: var(--space-1);
  opacity: 0;
  transition: opacity 0.15s;
}

.comment-item:hover .comment-actions {
  opacity: 1;
}

.comment-body {
  font-size: var(--font-sm);
  line-height: 1.6;
  color: var(--text);
}

.comment-body :deep(p) {
  margin: 0;
}

.comment-body :deep(p + p) {
  margin-top: 0.5em;
}

.comment-body :deep(code) {
  background: var(--bg-tertiary);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.9em;
}

.comment-body :deep(pre) {
  background: var(--bg-tertiary);
  padding: var(--space-2);
  border-radius: var(--radius);
  overflow-x: auto;
  margin: var(--space-2) 0;
}

.comment-body :deep(ul),
.comment-body :deep(ol) {
  padding-left: var(--space-4);
  margin: var(--space-2) 0;
}

.comment-edit-area {
  margin-top: var(--space-2);
}
</style>