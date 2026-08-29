import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import { useReposStore } from './repos'
import { issueType } from '@/utils/helpers'
import type { Issue, PR } from '@/utils/types'

function repoFullNameFromCloneUrl(cloneUrl: string): string {
  let url = cloneUrl.endsWith('.git') ? cloneUrl.slice(0, -4) : cloneUrl
  url = url.replace(/\/+$/, '')
  const parts = url.split('/')
  if (parts.length >= 2) return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`
  return ''
}

export const useCommunityStore = defineStore('community', () => {
  const issues = ref<Issue[]>([])
  const prs = ref<PR[]>([])
  const commits = ref<any[]>([])
  const sortBy = ref('created')
  const communityTab = ref<'commits' | 'issues' | 'prs'>('commits')
  const communityPage = ref(1)
  const communityIssueType = ref('all')
  const communityIssueArea = ref('')
  const communityPRArea = ref('')
  const communityRepo = ref('')  // 当前选中的仓库，'' 表示全部

  const trackedRepos = computed(() => {
    const reposStore = useReposStore()
    return reposStore.repos.filter(r => r.tracked)
  })

  watch(trackedRepos, (repos) => {
    if (!communityRepo.value && repos.length > 0) {
      const url = repos[0].clone_url
      communityRepo.value = repoFullNameFromCloneUrl(url)
      loadCommunityData()
    }
  }, { immediate: true })

  // Reset pagination depth when switching between PR / Issue tabs
  watch(communityTab, () => {
    communityPage.value = 1
  })

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

  const filteredCommits = computed(() => {
    const appStore = useAppStore()
    const q = (appStore.searchQuery || '').toLowerCase().trim()
    let list = commits.value
    if (q) {
      list = list.filter(c =>
        (c.subject || '').toLowerCase().includes(q) ||
        (c.short_sha || '').toLowerCase().includes(q) ||
        String(c.sha || '').toLowerCase().includes(q) ||
        (c.author || '').toLowerCase().includes(q),
      )
    }
    return list
  })

  const pagedFilteredIssues = computed(() => {
    if (communityTab.value === 'prs' || communityTab.value === 'commits') return []
    const limit = communityPage.value * 25
    return filteredIssues.value.slice(0, limit)
  })

  const pagedFilteredPRs = computed(() => {
    if (communityTab.value === 'issues' || communityTab.value === 'commits') return []
    const limit = communityPage.value * 25
    return filteredPRs.value.slice(0, limit)
  })

  const pagedFilteredCommits = computed(() => {
    if (communityTab.value !== 'commits') return []
    const limit = communityPage.value * 25
    return filteredCommits.value.slice(0, limit)
  })

  const hasMoreCommunity = computed(() => {
    if (communityTab.value === 'prs') {
      return pagedFilteredPRs.value.length < filteredPRs.value.length
    }
    if (communityTab.value === 'commits') {
      return pagedFilteredCommits.value.length < filteredCommits.value.length
    }
    return pagedFilteredIssues.value.length < filteredIssues.value.length
  })

  async function loadAreas() {
    try {
      await useAppStore().loadAreas()
    } catch (_) {}
  }

  async function loadCommunityData() {
    communityPage.value = 1
    // 没有选中仓库时，默认选中第一个 tracked repo
    if (!communityRepo.value) {
      const repos = trackedRepos.value
      if (repos.length > 0) {
        const url = repos[0].clone_url
        communityRepo.value = repoFullNameFromCloneUrl(url)
      }
    }
    try {
      const params = new URLSearchParams()
      params.set('sort_by', sortBy.value)
      params.set('limit', '200')
      if (communityRepo.value) params.set('repo', communityRepo.value)
      const [itemsData, commitsData] = await Promise.all([
        api('/api/community/items?' + params),
        api('/api/community/commits?limit=200' + (communityRepo.value ? '&repo=' + encodeURIComponent(communityRepo.value) : '')),
      ])
      const items = itemsData.items || itemsData
      issues.value = items.filter((x: any) => x.type === 'issue')
      prs.value = items.filter((x: any) => x.type === 'pr')
      commits.value = commitsData.commits || []
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

  return {
    issues, prs, commits, sortBy, communityTab, communityPage,
    communityIssueType, communityIssueArea, communityPRArea,
    communityRepo, trackedRepos,
    filteredIssues, filteredPRs, filteredCommits,
    pagedFilteredIssues, pagedFilteredPRs, pagedFilteredCommits,
    hasMoreCommunity,
    loadAreas, loadCommunityData, forceRefresh,
  }
})