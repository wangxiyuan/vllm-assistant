import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { Comment } from '@/utils/types'

export const useCommentsStore = defineStore('comments', () => {
  const comments = ref<Comment[]>([])
  const loading = ref(false)
  const submitting = ref(false)

  async function loadComments(targetType: string, targetId: number) {
    loading.value = true
    try {
      const data: any = await api(`/api/comments?target_type=${targetType}&target_id=${targetId}`)
      comments.value = data.comments || []
    } catch (e: any) {
      useAppStore().showToast('加载评论失败', e.message, 'error')
    } finally {
      loading.value = false
    }
  }

  async function addComment(targetType: string, targetId: number, content: string, userId: number | null) {
    submitting.value = true
    try {
      const comment: any = await api('/api/comments', {
        method: 'POST',
        body: JSON.stringify({ target_type: targetType, target_id: targetId, content, user_id: userId }),
      })
      comments.value.push(comment)
      return comment
    } catch (e: any) {
      useAppStore().showToast('评论失败', e.message, 'error')
      throw e
    } finally {
      submitting.value = false
    }
  }

  async function editComment(id: number, content: string) {
    try {
      const updated: any = await api(`/api/comments/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
      })
      const idx = comments.value.findIndex(c => c.id === id)
      if (idx >= 0) comments.value[idx] = updated
      return updated
    } catch (e: any) {
      useAppStore().showToast('编辑评论失败', e.message, 'error')
      throw e
    }
  }

  async function removeComment(id: number) {
    const appStore = useAppStore()
    const result = await appStore.showConfirm({
      title: '删除评论',
      message: '确定删除这条评论？',
      confirmText: '删除',
      danger: true,
    })
    if (!result.confirmed) return
    try {
      await api(`/api/comments/${id}`, { method: 'DELETE' })
      comments.value = comments.value.filter(c => c.id !== id)
      appStore.showToast('评论已删除', '', 'info')
    } catch (e: any) {
      appStore.showToast('删除失败', e.message, 'error')
    }
  }

  function clearComments() {
    comments.value = []
  }

  return {
    comments, loading, submitting,
    loadComments, addComment, editComment, removeComment, clearComments,
  }
})