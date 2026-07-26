import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import type { User } from '@/utils/types'

export const useUsersStore = defineStore('users', () => {
  const users = ref<User[]>([])
  const showUserManager = ref(false)
  const userForm = ref({ name: '', github_id: '' })
  const userFormMode = ref<'create' | 'edit'>('create')
  const editingUser = ref<User | null>(null)
  const userSaving = ref(false)

  async function loadUsers() {
    try {
      const data: any = await api('/api/users')
      users.value = data.users || []
    } catch (e: any) {
      useAppStore().showToast('加载用户失败', e.message, 'error')
    }
  }

  function openManager() {
    showUserManager.value = true
    resetForm()
    loadUsers()
  }

  function closeManager() {
    showUserManager.value = false
    resetForm()
  }

  function resetForm() {
    userForm.value = { name: '', github_id: '' }
    userFormMode.value = 'create'
    editingUser.value = null
  }

  function openEditUser(user: User) {
    userFormMode.value = 'edit'
    editingUser.value = user
    userForm.value = { name: user.name, github_id: user.github_id || '' }
  }

  async function saveUser() {
    const name = userForm.value.name.trim()
    if (!name) { useAppStore().showToast('显示名称不能为空', '', 'error'); return }
    let githubId = (userForm.value.github_id || '').trim().replace(/^@+/, '')
    githubId = githubId.replace(/^https?:\/\/github\.com\//i, '').replace(/\/.*$/, '')
    if (githubId && !/^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$/.test(githubId)) {
      useAppStore().showToast('GitHub 登录名格式不正确', '请填写 GitHub 用户名（如 octocat），不要带 @ 或网址', 'error')
      return
    }
    if (userSaving.value) return
    userSaving.value = true
    const payload = { name, github_id: githubId }
    try {
      if (userFormMode.value === 'create') {
        const user: any = await api('/api/users', { method: 'POST', body: JSON.stringify(payload) })
        users.value.push(user)
        useAppStore().showToast('用户已创建', name, 'success')
      } else if (editingUser.value) {
        const user: any = await api(`/api/users/${editingUser.value.id}`, {
          method: 'PUT', body: JSON.stringify(payload),
        })
        const idx = users.value.findIndex(u => u.id === user.id)
        if (idx >= 0) users.value[idx] = user
        useAppStore().showToast('用户已更新', name, 'success')
      }
      resetForm()
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    } finally {
      userSaving.value = false
    }
  }

  async function deleteUser(user: User) {
    if (!confirm(`确认删除用户「${user.name}」？\n删除后，已关联该用户为责任人的任务/算子/模型将显示为「未知用户」。`)) return
    try {
      await api(`/api/users/${user.id}`, { method: 'DELETE' })
      users.value = users.value.filter(u => u.id !== user.id)
      if (editingUser.value?.id === user.id) resetForm()
      useAppStore().showToast('已删除', `用户「${user.name}」已删除`, 'info')
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  function userName(userId: number | null | undefined): string {
    if (!userId) return ''
    const user = users.value.find(u => u.id === userId)
    return user ? user.name : '(未知用户)'
  }

  return {
    users, showUserManager, userForm, userFormMode, editingUser, userSaving,
    loadUsers, openManager, closeManager, resetForm, openEditUser,
    saveUser, deleteUser, userName,
  }
})