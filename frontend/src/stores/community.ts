import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import { issueType } from '@/utils/helpers'
import type { Issue, PR } from '@/utils/types'

export const useCommunityStore = defineStore('community', () => {
  const issues = ref<Issue[]>([])
  const prs = ref<PR[]>([])
  const stats = ref({ totalIssues: 0, totalPRs: 0 })
  const sortBy = ref('created')
  const communityTab = ref<'issues' | 'prs'>('prs')
  const communityPage = ref(1)
  const pageSize = ref(25)
  const communityLoadingMore = ref(false)
  const communityIssueType = ref('all')
  const communityIssueArea = ref('')
  const communityPRArea = ref('')
  const labelLoading = ref<number | null>(null)
  const labelResult = ref<Record<number, string[]>>({})

  const filteredIssues = computed(() => {
    const appStore = useAppStore()
    const q = (appStore.searchQuery || '').toLowerCase().trim()
    let list = issues.value
    if (communityIssueType.value !== 'all') {
      list = list.filter(i => issueType(i) === communityIssueType.value)
    }
    if (communityIssueArea.value) {
      list = list.filter(i => i.area === communityIssueArea.value)
    }
    if (q) {
      list = list.filter(i =>
        (i.title || '').toLowerCase().includes(q) ||
        String(i.number).includes(q) ||
        (i.author || '').toLowerCase().includes(q) ||
        (i.area || '').toLowerCase().includes(q),
      )
    }
    return list
  })

  const filteredPRs = computed(() => {
    const appStore = useAppStore()
    const q = (appStore.searchQuery || '').toLowerCase().trim()
    let list = prs.value
    if (communityPRArea.value) {
      list = list.filter(p => p.area === communityPRArea.value)
    }
    if (q) {
      list = list.filter(p =>
        (p.title || '').toLowerCase().includes(q) ||
        String(p.number).includes(q) ||
        (p.author || '').toLowerCase().includes(q) ||
        (p.area || '').toLowerCase().includes(q),
      )
    }
    return list
  })

  const pagedFilteredIssues = computed(() => {
    if (communityTab.value === 'prs') return []
    const limit = communityPage.value * pageSize.value
    return filteredIssues.value.slice(0, limit)
  })

  const pagedFilteredPRs = computed(() => {
    if (communityTab.value === 'issues') return []
    const limit = communityPage.value * pageSize.value
    return filteredPRs.value.slice(0, limit)
  })

  const hasMoreCommunity = computed(() => {
    const shown = pagedFilteredIssues.value.length + pagedFilteredPRs.value.length
    const total = filteredIssues.value.length + filteredPRs.value.length
    return shown < total
  })

  const filteredListEmpty = computed(() => {
    if (communityTab.value === 'prs') return filteredPRs.value.length === 0
    return filteredIssues.value.length === 0
  })

  const newIssuesCount = computed(() => issues.value.filter(i => i.is_new).length)
  const newPRsCount = computed(() => prs.value.filter(p => p.is_new).length)

  async function loadAreas() {
    try {
      await useAppStore().loadAreas()
    } catch (_) {}
  }

  async function loadCommunityData() {
    communityPage.value = 1
    communityLoadingMore.value = false
    try {
      const params = new URLSearchParams()
      params.set('sort_by', sortBy.value)
      params.set('limit', '200')
      const data: any = await api('/api/community/items?' + params)
      const items = data.items || data
      issues.value = items.filter((x: any) => x.type === 'issue')
      prs.value = items.filter((x: any) => x.type === 'pr')
      stats.value = {
        totalIssues: issues.value.length,
        totalPRs: prs.value.length,
      }
    } catch (e: any) {
      useAppStore().showToast('加载社区动态失败', e.message, 'error')
    }
  }

  async function forceRefresh() {
    try {
      const params = new URLSearchParams({ force_refresh: 'true' })
      await api('/api/community/items?' + params)
      useAppStore().showToast('已触发同步', '后台同步已启动，几秒后刷新查看最新数据', 'success')
    } catch (e: any) {
      useAppStore().showToast('触发刷新失败', e.message, 'error')
    }
  }

  async function toggleLabelPopover(issue: Issue) {
    if (labelResult.value[issue.number]) {
      delete labelResult.value[issue.number]
      return
    }
    labelResult.value = {}
    labelLoading.value = issue.number
    try {
      const result: any = await api('/api/ai-assistant/suggest-labels', {
        method: 'POST',
        body: JSON.stringify({
          issue_title: issue.title,
          issue_body: (issue.body || '').slice(0, 2000),
        }),
      })
      labelResult.value[issue.number] = result.suggested_labels || []
      if (labelResult.value[issue.number].length === 0) {
        useAppStore().showToast('无标签建议', 'AI 未给出建议（检查 OPENAI_API_KEY 配置）', 'info')
      }
    } catch (e: any) {
      useAppStore().showToast('标签推荐失败', e.message, 'error')
      labelResult.value[issue.number] = []
    } finally {
      labelLoading.value = null
    }
  }

  return {
    issues, prs, stats, sortBy, communityTab, communityPage, pageSize,
    communityLoadingMore, communityIssueType, communityIssueArea, communityPRArea,
    labelLoading, labelResult,
    filteredIssues, filteredPRs, pagedFilteredIssues, pagedFilteredPRs,
    hasMoreCommunity, filteredListEmpty, newIssuesCount, newPRsCount,
    loadAreas, loadCommunityData, forceRefresh, toggleLabelPopover,
  }
})