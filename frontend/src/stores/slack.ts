import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'

export interface SlackConfig {
  id: number
  token: boolean
  cookie: boolean
  cred_exists: boolean
  channels: string[]
  collect_interval: number
  collect_lookback: number
  last_collect_at: string | null
  total_messages: number
  last_refresh_at: string | null
  updated_at: string
  created_at: string
}

export interface SlackStatus {
  cred_exists: boolean
  cred_valid: boolean
  last_collect_at: string | null
  total_messages: number
  collect_interval: number
  collect_lookback: number
  last_refresh_at: string | null
}

export interface SlackChannel {
  id: string
  name: string
  display: string
  num_members: number
  topic: string
  purpose: string
}

export const useSlackStore = defineStore('slack', () => {
  const config = ref<SlackConfig | null>(null)
  const status = ref<SlackStatus | null>(null)
  const showManager = ref(false)
  const configLoading = ref(false)
  const availableChannels = ref<SlackChannel[]>([])
  const channelsLoading = ref(false)
  const tokenInput = ref('')
  const cookieInput = ref('')
  const newChannel = ref('')
  const collectInterval = ref(360)
  const collectLookback = ref(1440)
  const saving = ref(false)
  const collecting = ref(false)
  const testing = ref(false)
  const refreshing = ref(false)

  async function loadConfig() {
    configLoading.value = true
    try {
      const data: any = await api('/api/slack/config')
      config.value = data as SlackConfig
      collectInterval.value = data.collect_interval || 360
      collectLookback.value = data.collect_lookback || 1440
      if (data.token) tokenInput.value = data.token
      if (data.cookie) cookieInput.value = data.cookie
    } catch (e: any) {
      useAppStore().showToast('加载 Slack 配置失败，尝试自动刷新凭证...', e.message, 'error')
      await refreshToken()
    } finally {
      configLoading.value = false
    }
  }

  async function loadStatus() {
    try {
      const data: any = await api('/api/slack/status')
      status.value = data as SlackStatus
    } catch (e: any) {
      // silent
    }
  }

  async function loadAvailableChannels() {
    if (channelsLoading.value) return
    channelsLoading.value = true
    try {
      const data: any = await api('/api/slack/channels')
      availableChannels.value = (data.channels || []) as SlackChannel[]
    } catch (e: any) {
      useAppStore().showToast('加载频道列表失败', e.message, 'error')
    } finally {
      channelsLoading.value = false
    }
  }

  async function testAuth() {
    const token = tokenInput.value.trim()
    const cookie = cookieInput.value.trim()
    if (!token || !cookie) {
      useAppStore().showToast('请先填写 token 和 cookie', '', 'error')
      return
    }
    testing.value = true
    try {
      const data: any = await api('/api/slack/test-auth', {
        method: 'POST',
        body: JSON.stringify({ token, cookie }),
      })
      if (data.ok) {
        useAppStore().showToast('凭证有效', `用户: ${data.user}，团队: ${data.team}`, 'success')
        await loadStatus()
      } else {
        useAppStore().showToast('凭证无效', data.error || 'unknown', 'error')
      }
    } catch (e: any) {
      useAppStore().showToast('测试失败', e.message, 'error')
    } finally {
      testing.value = false
    }
  }

  async function saveConfig() {
    if (saving.value) return
    saving.value = true
    try {
      const payload: any = {
        channels: config.value?.channels || [],
        collect_interval: collectInterval.value,
        collect_lookback: collectLookback.value,
      }
      if (tokenInput.value.trim()) payload.token = tokenInput.value.trim()
      if (cookieInput.value.trim()) payload.cookie = cookieInput.value.trim()

      const data: any = await api('/api/slack/config', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      config.value = data as SlackConfig
      if (data.token) tokenInput.value = data.token
      if (data.cookie) cookieInput.value = data.cookie
      useAppStore().showToast('Slack 配置已保存', '', 'success')
    } catch (e: any) {
      useAppStore().showToast('保存 Slack 配置失败', e.message, 'error')
    } finally {
      saving.value = false
    }
  }

  async function addChannel() {
    const channel = newChannel.value.trim()
    if (!channel) {
      useAppStore().showToast('请选择或输入频道', '', 'error')
      return
    }
    if (!channel.startsWith('#')) {
      useAppStore().showToast('频道名称必须以 # 开头', '', 'error')
      return
    }
    if (config.value?.channels?.includes(channel)) {
      useAppStore().showToast('频道已存在', channel, 'warning')
      return
    }
    try {
      const data: any = await api('/api/slack/config/channels', {
        method: 'POST',
        body: JSON.stringify({ channel }),
      })
      config.value = data as SlackConfig
      newChannel.value = ''
      useAppStore().showToast('频道已添加', channel, 'success')
    } catch (e: any) {
      useAppStore().showToast('添加频道失败', e.message, 'error')
    }
  }

  async function removeChannel(channel: string) {
    const result = await useAppStore().showConfirm({
      title: '移除频道',
      message: `确认移除频道 ${channel}？`,
      confirmText: '移除',
      danger: true,
    })
    if (!result.confirmed) return
    try {
      const data: any = await api(`/api/slack/config/channels/${encodeURIComponent(channel)}`, {
        method: 'DELETE',
      })
      config.value = data as SlackConfig
      useAppStore().showToast('频道已移除', channel, 'info')
    } catch (e: any) {
      useAppStore().showToast('移除频道失败', e.message, 'error')
    }
  }

  async function triggerCollect() {
    if (collecting.value) return
    collecting.value = true
    try {
      const data: any = await api('/api/slack/collect', { method: 'POST' })
      useAppStore().showToast('Slack 采集完成', `获取 ${data.total_fetched || 0} 条，新增 ${data.total_stored || 0} 条`, 'success')
      await loadStatus()
      await loadConfig()
    } catch (e: any) {
      useAppStore().showToast('Slack 采集失败', e.message, 'error')
    } finally {
      collecting.value = false
    }
  }

  async function clearData() {
    const result = await useAppStore().showConfirm({
      title: '清除 Slack 数据',
      message: '确认清除所有 Slack 采集数据？此操作不可恢复。',
      confirmText: '清除',
      danger: true,
    })
    if (!result.confirmed) return
    try {
      const data: any = await api('/api/slack/data', { method: 'DELETE' })
      useAppStore().showToast('Slack 数据已清除', `删除了 ${data.deleted} 条记录`, 'info')
      await loadStatus()
    } catch (e: any) {
      useAppStore().showToast('清除失败', e.message, 'error')
    }
  }

  async function refreshToken() {
    refreshing.value = true
    try {
      const data: any = await api('/api/slack/refresh-token', { method: 'POST' })
      if (data.ok) {
        config.value = data as SlackConfig
        if (data.token) tokenInput.value = data.token
        if (data.cookie) cookieInput.value = data.cookie
        useAppStore().showToast('凭证已刷新', '', 'success')
        await loadStatus()
      } else {
        useAppStore().showToast('刷新失败', data.error || '请检查 .env 中 SLACK_EMAIL / SLACK_PASSWORD', 'error')
      }
    } catch (e: any) {
      useAppStore().showToast('刷新失败', e.message, 'error')
    } finally {
      refreshing.value = false
    }
  }

  function getAvailableNotConfigured(): SlackChannel[] {
    const configured = config.value?.channels || []
    return availableChannels.value.filter(ch => !configured.includes(`#${ch.name}`))
  }

  function openManager() {
    showManager.value = true
    loadConfig()
    loadStatus()
    loadAvailableChannels()
  }

  function closeManager() {
    showManager.value = false
  }

  return {
    config, status, showManager, configLoading, availableChannels, channelsLoading,
    tokenInput, cookieInput, newChannel, collectInterval, collectLookback, saving, collecting, testing, refreshing,
    loadConfig, loadStatus, loadAvailableChannels,
    testAuth, saveConfig, addChannel, removeChannel,
    triggerCollect, clearData, refreshToken, getAvailableNotConfigured,
    openManager, closeManager,
  }
})