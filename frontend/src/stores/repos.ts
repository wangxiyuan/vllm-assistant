import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { RepoConfig } from '@/utils/types'

export const useReposStore = defineStore('repos', () => {
  const repos = ref<RepoConfig[]>([])
  const showRepoManager = ref(false)
  const repoForm = ref({ repo: '', clone_url: '', branch: 'main' })
  const repoFormMode = ref<'create' | 'edit'>('create')
  const editingRepo = ref<RepoConfig | null>(null)
  const repoSaving = ref(false)

  async function loadRepos() {
    try {
      const data: any = await api('/api/repos')
      repos.value = data.repos || []
    } catch (e: any) {
      useAppStore().showToast('加载仓库失败', e.message, 'error')
    }
  }

  function openManager() {
    showRepoManager.value = true
    resetForm()
    loadRepos()
  }

  function closeManager() {
    showRepoManager.value = false
    resetForm()
  }

  function resetForm() {
    repoForm.value = { repo: '', clone_url: '', branch: 'main' }
    repoFormMode.value = 'create'
    editingRepo.value = null
  }

  function openEditRepo(repo: RepoConfig) {
    repoFormMode.value = 'edit'
    editingRepo.value = repo
    repoForm.value = {
      repo: repo.repo,
      clone_url: repo.clone_url,
      branch: repo.branch || 'main',
    }
  }

  async function saveRepo() {
    const repoName = repoForm.value.repo.trim()
    const cloneUrl = repoForm.value.clone_url.trim()
    const branch = repoForm.value.branch.trim() || 'main'

    if (!repoName) {
      useAppStore().showToast('仓库名称不能为空', '', 'error')
      return
    }
    if (!cloneUrl) {
      useAppStore().showToast('克隆地址不能为空', '', 'error')
      return
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(repoName)) {
      useAppStore().showToast('仓库名称格式不正确', '只能包含字母、数字、短横线和下划线', 'error')
      return
    }
    if (!cloneUrl.startsWith('https://') && !cloneUrl.startsWith('git@')) {
      useAppStore().showToast('克隆地址格式不正确', '请输入 https:// 或 git@ 开头的 Git 地址', 'error')
      return
    }

    if (repoSaving.value) return
    repoSaving.value = true

    const payload = { repo: repoName, clone_url: cloneUrl, branch }

    try {
      if (repoFormMode.value === 'create') {
        const repo: any = await api('/api/repos', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        repos.value.push(repo)
        useAppStore().showToast('仓库已创建', `${repoName}（正在后台 clone...）`, 'success')
      } else if (editingRepo.value) {
        const repo: any = await api(`/api/repos/${editingRepo.value.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
        const idx = repos.value.findIndex(r => r.id === repo.id)
        if (idx >= 0) repos.value[idx] = repo
        useAppStore().showToast('仓库已更新', repoName, 'success')
      }
      resetForm()
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    } finally {
      repoSaving.value = false
    }
  }

  async function deleteRepo(repo: RepoConfig) {
    if (!confirm(
      `确认删除仓库「${repo.repo}」？\n\n` +
      `删除后将清理：\n` +
      `• 该仓库的代码缓存（LocalCodeCache）\n` +
      `• 文件变更历史记录\n` +
      `• 文章中的代码引用（标记为无效）\n` +
      `• 知识库中相关内容（标记为过期）\n` +
      `• 本地克隆目录\n\n` +
      `此操作不可撤销，确认删除？`
    )) return

    try {
      await api(`/api/repos/${repo.id}`, { method: 'DELETE' })
      repos.value = repos.value.filter(r => r.id !== repo.id)
      if (editingRepo.value?.id === repo.id) resetForm()
      useAppStore().showToast('已删除', `仓库「${repo.repo}」已删除`, 'info')
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  return {
    repos,
    showRepoManager,
    repoForm,
    repoFormMode,
    editingRepo,
    repoSaving,
    loadRepos,
    openManager,
    closeManager,
    resetForm,
    openEditRepo,
    saveRepo,
    deleteRepo,
  }
})
