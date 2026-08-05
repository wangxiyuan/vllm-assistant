import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import { useWatchlistStore } from './watchlist'
import { useReposStore } from './repos'
import { issueType } from '@/utils/helpers'
import type { PR, Issue, PRDetails } from '@/utils/types'

function repoFullNameFromCloneUrl(cloneUrl: string): string {
  let url = cloneUrl.endsWith('.git') ? cloneUrl.slice(0, -4) : cloneUrl
  url = url.replace(/\/+$/, '')
  const parts = url.split('/')
  if (parts.length >= 2) return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`
  return ''
}

export const usePRCenterStore = defineStore('prCenter', () => {
  // PR list
  const myPrs = ref<PR[]>([])
  const myIssues = ref<Issue[]>([])
  const contributionTab = ref<'prs' | 'issues'>('prs')
  const prState = ref('open')
  const myIssuesState = ref('open')
  const myIssuesType = ref('all')
  const filterConflicts = ref(false)
  const filterCIFail = ref(false)
  const selectedContributor = ref<{ id: number; name: string; github_id: string } | null>(null)
  const selectedContributorGithubId = ref('')
  const contributionRepo = ref('')  // 当前选中的仓库，'' 表示全部

  // PR drawer
  const selectedPR = ref<any>(null)
  const prDetails = ref<PRDetails | null>(null)
  const prLoadError = ref<string | null>(null)
  const loadingDetails = ref(false)
  const aiReview = ref<any>(null)
  const aiReviewLoading = ref(false)
  const aiReviewElapsed = ref(0)
  const aiSummary = ref<any>(null)
  const aiSummaryLoading = ref(false)

  // Issue drawer
  const selectedIssue = ref<any>(null)
  const issueDetails = ref<Issue | null>(null)
  const issueLoadError = ref<string | null>(null)
  const loadingIssue = ref(false)

  // Translate
  const translateLoading = ref(false)
  const prTranslatedBody = ref<string | null>(null)
  const issueTranslatedBody = ref<string | null>(null)
  const prShowChinese = ref(false)
  const issueShowChinese = ref(false)

  // Diff
  const expandedDiffFile = ref<string | null>(null)
  const fileDiffs = ref<Record<string, string>>({})

  // Computed
  const trackedRepos = computed(() => {
    const reposStore = useReposStore()
    return reposStore.repos.filter(r => r.tracked)
  })

  watch(trackedRepos, (repos) => {
    if (!contributionRepo.value && repos.length > 0) {
      const url = repos[0].clone_url
      contributionRepo.value = repoFullNameFromCloneUrl(url)
      loadAllContribData()
    }
  }, { immediate: true })

  const filteredMyPRs = computed(() => {
    const appStore = useAppStore()
    const q = (appStore.searchQuery || '').toLowerCase().trim()
    let list = myPrs.value
    if (prState.value !== 'all') {
      list = list.filter(p => p.state === prState.value)
    }
    if (filterConflicts.value) {
      list = list.filter(p => p.conflict_detected)
    }
    if (filterCIFail.value) {
      list = list.filter(p => p.ci_status === 'fail')
    }
    if (q) {
      list = list.filter(p =>
        (p.title || '').toLowerCase().includes(q) ||
        String(p.pr_number).includes(q) ||
        (p.branch || '').toLowerCase().includes(q),
      )
    }
    return list
  })

  const filteredMyIssues = computed(() => {
    const appStore = useAppStore()
    const q = (appStore.searchQuery || '').toLowerCase().trim()
    let list = myIssues.value
    if (myIssuesState.value !== 'all') {
      list = list.filter(i => i.state === myIssuesState.value)
    }
    if (myIssuesType.value !== 'all') {
      list = list.filter(i => issueType(i) === myIssuesType.value)
    }
    if (q) {
      list = list.filter(i =>
        (i.title || '').toLowerCase().includes(q) ||
        String(i.number).includes(q),
      )
    }
    return list
  })

  const openIssueCount = computed(() => myIssues.value.filter(i => i.state === 'open').length)
  const closedIssueCount = computed(() => myIssues.value.filter(i => i.state === 'closed').length)
  const allIssueCount = computed(() => myIssues.value.length)

  // Actions
  function switchPRState(state: string) {
    prState.value = state
  }

  function switchContributionTab(tab: 'prs' | 'issues') {
    contributionTab.value = tab
    if (tab === 'issues') loadMyIssues()
  }

  function switchContributionRepo(repo: string) {
    contributionRepo.value = repo
    loadMyPRs()
    if (contributionTab.value === 'issues') loadMyIssues()
  }

  function switchMyIssuesState(state: string) {
    myIssuesState.value = state
  }

  function switchMyIssuesType(type: string) {
    myIssuesType.value = type
  }

  async function loadMyPRs() {
    // 没有选中仓库时，默认选中第一个 tracked repo
    if (!contributionRepo.value) {
      const repos = trackedRepos.value
      if (repos.length > 0) {
        const url = repos[0].clone_url
        contributionRepo.value = repoFullNameFromCloneUrl(url)
      }
    }
    try {
      const githubId = selectedContributor.value?.github_id
      const params = new URLSearchParams({ state: 'all' })
      if (githubId) params.set('github_id', githubId)
      if (contributionRepo.value) params.set('repo', contributionRepo.value)
      myPrs.value = await api(`/api/pr-center/my-prs?${params}`)
    } catch (e: any) {
      useAppStore().showToast('加载 PR 失败', e.message, 'error')
    }
  }

  async function loadMyIssues() {
    try {
      const githubId = selectedContributor.value?.github_id
      const url = githubId
        ? `/api/pr-center/my-issues?state=all&github_id=${encodeURIComponent(githubId)}`
        : '/api/pr-center/my-issues?state=all'
      myIssues.value = await api(url)
    } catch (e: any) {
      useAppStore().showToast('加载 Issue 失败', e.message, 'error')
    }
  }

  function loadAllContribData() {
    loadMyPRs()
    loadMyIssues()
  }

  // PR drawer
  async function openPR(pr: any) {
    const watchlistStore = useWatchlistStore()
    const wl = watchlistStore.findWatchlistItem(pr.pr_number || pr.number, 'pr', pr.repo)
    if (wl) {
      pr.watchlist_note = wl.note || ''
      pr.watchlist_assignee_id = wl.assignee_id || null
      pr._linked_tasks = wl.linked_tasks || []
    } else if (pr._linked_tasks) {
      pr._linked_tasks = pr._linked_tasks || []
    }
    selectedPR.value = pr
    prDetails.value = null
    prLoadError.value = null
    aiReview.value = null
    aiSummary.value = null
    aiSummaryCollapsed.value = false
    aiReviewCollapsed.value = false
    loadingDetails.value = true
    aiReviewLoading.value = !!pendingReviews.value[pr.pr_number || pr.number]
    aiSummaryLoading.value = !!pendingSummaries.value['pr:' + (pr.pr_number || pr.number)]
    try {
      const repoParam = pr.repo ? `?repo=${encodeURIComponent(pr.repo)}` : ''
      prDetails.value = await api(`/api/pr-center/my-prs/${pr.pr_number || pr.number}/details${repoParam}`)
      _loadCachedAI('pr', pr.pr_number || pr.number)
      _loadCachedTranslate('pr', pr.pr_number || pr.number)
    } catch (e: any) {
      prLoadError.value = e.message
      useAppStore().showToast('加载 PR 详情失败', e.message, 'error')
    } finally {
      loadingDetails.value = false
    }
  }

  function closePR() {
    selectedPR.value = null
    prDetails.value = null
    prLoadError.value = null
    aiReview.value = null
    aiSummary.value = null
    loadingDetails.value = false
    if (aiReviewTimer.value) { clearInterval(aiReviewTimer.value); aiReviewTimer.value = null }
    aiReviewElapsed.value = 0
    prTranslatedBody.value = null
    prShowChinese.value = false
    expandedDiffFile.value = null
    fileDiffs.value = {}
    prDiffData.value = null
  }

  // Issue drawer
  async function openIssue(issue: any) {
    const watchlistStore = useWatchlistStore()
    const wl = watchlistStore.findWatchlistItem(issue.number, 'issue', issue.repo)
    if (wl) {
      issue.watchlist_note = wl.note || ''
      issue.watchlist_assignee_id = wl.assignee_id || null
      issue._linked_tasks = wl.linked_tasks || []
    } else {
      issue._linked_tasks = issue._linked_tasks || []
    }
    selectedIssue.value = issue
    issueDetails.value = issue.body ? issue : null
    issueLoadError.value = null
    aiSummary.value = null
    aiSummaryCollapsed.value = false
    aiSummaryLoading.value = !!pendingSummaries.value['issue:' + issue.number]
    loadingIssue.value = !issue.body
    try {
      if (!issue.body) {
        const repoParam = issue.repo ? `?repo=${encodeURIComponent(issue.repo)}` : ''
        issueDetails.value = await api(`/api/pr-center/issue/${issue.number}/body${repoParam}`)
      }
      _loadCachedAI('issue', issue.number)
      _loadCachedTranslate('issue', issue.number)
    } catch (e: any) {
      issueLoadError.value = e.message
      useAppStore().showToast('加载 Issue 失败', e.message, 'error')
    } finally {
      loadingIssue.value = false
    }
  }

  function closeIssue() {
    selectedIssue.value = null
    issueDetails.value = null
    issueLoadError.value = null
    aiSummary.value = null
    loadingIssue.value = false
    issueTranslatedBody.value = null
    issueShowChinese.value = false
  }

  // AI cache
  async function _loadCachedAI(itemType: string, number: number) {
    try {
      const cachedSummary: any = await api('/api/ai-assistant/get-cache', {
        method: 'POST',
        body: JSON.stringify({ item_type: itemType, number, action: 'summary' }),
      }, { timeout: 5000 })
      const isCurrent = (itemType === 'pr' && (selectedPR.value?.pr_number === number))
        || (itemType === 'issue' && selectedIssue.value?.number === number)
      if (!isCurrent) return
      if (cachedSummary && !cachedSummary.empty) {
        aiSummary.value = cachedSummary
      }
      if (itemType === 'pr') {
        const cachedReview: any = await api('/api/ai-assistant/get-cache', {
          method: 'POST',
          body: JSON.stringify({ item_type: itemType, number, action: 'review' }),
        }, { timeout: 5000 })
        if (selectedPR.value?.pr_number !== number) return
        if (cachedReview && !cachedReview.empty) {
          aiReview.value = cachedReview
        }
      }
    } catch (_) {}
  }

  async function _loadCachedTranslate(itemType: string, number: number) {
    try {
      const cached: any = await api('/api/ai-assistant/get-cache', {
        method: 'POST',
        body: JSON.stringify({ item_type: itemType, number, action: 'translate' }),
      }, { timeout: 5000 })
      const isCurrent = (itemType === 'pr' && (selectedPR.value?.pr_number === number))
        || (itemType === 'issue' && selectedIssue.value?.number === number)
      if (!isCurrent) return
      if (cached && cached.translated) {
        if (itemType === 'pr') prTranslatedBody.value = cached.translated
        else issueTranslatedBody.value = cached.translated
      }
    } catch (_) {}
  }

  // Diff
  async function loadPRDiff() {
    if (!selectedPR.value?.pr_number || prDiffLoading.value) return
    prDiffLoading.value = true
    try {
      const repoParam = selectedPR.value.repo ? `?repo=${encodeURIComponent(selectedPR.value.repo)}` : ''
      const data: any = await api(`/api/pr-center/my-prs/${selectedPR.value.pr_number}/diff${repoParam}`, {}, { timeout: 60000 })
      prDiffData.value = data.diff || ''
      _parseDiffFiles(prDiffData.value)
    } catch (e: any) {
      useAppStore().showToast('加载 diff 失败', e.message, 'error')
    } finally {
      prDiffLoading.value = false
    }
  }

  function _parseDiffFiles(rawDiff: string | null) {
    if (!rawDiff) return
    const files: Record<string, string> = {}
    const fileBlocks = rawDiff.split(/(?=^diff --git )/m)
    for (const block of fileBlocks) {
      if (!block.trim()) continue
      const m = block.match(/^diff --git a\/(\S+) b\/(\S+)/m)
      if (m) files[m[2]] = block
    }
    fileDiffs.value = files
  }

  function toggleFileDiff(filename: string) {
    if (expandedDiffFile.value === filename) {
      expandedDiffFile.value = null
      return
    }
    expandedDiffFile.value = filename
    if (!fileDiffs.value[filename] && !prDiffLoading.value) {
      loadPRDiff()
    }
  }

  // AI summary
  async function generateSummary(itemType: string) {
    const isPR = itemType === 'pr'
    const data = isPR ? selectedPR.value : selectedIssue.value
    if (!data || aiSummaryLoading.value) return
    const number = data.number || data.pr_number
    const pendingKey = itemType + ':' + number
    aiSummary.value = null
    aiSummaryLoading.value = true
    aiSummaryCollapsed.value = false
    pendingSummaries.value[pendingKey] = true
    // 切换到总结 tab
    if (isPR) prDetailTab.value = 'summary'
    else issueDetailTab.value = 'summary'

    try {
      await api('/api/ai-assistant/clear-cache', {
        method: 'POST',
        body: JSON.stringify({ item_type: itemType, number, action: 'summary' }),
      }, { timeout: 5000 })
    } catch (_) {}

    try {
      const body = isPR ? (prDetails.value?.pr?.body || '') : (issueDetails.value?.body || '')
      const res = await api('/api/ai-assistant/summarize', {
        method: 'POST',
        body: JSON.stringify({
          item_type: itemType,
          number,
          title: data.title || '',
          body,
        }),
      }, { timeout: 120000 })
      const isCurrent = (isPR && selectedPR.value?.pr_number === number)
        || (!isPR && selectedIssue.value?.number === number)
      if (isCurrent) {
        aiSummary.value = res
      }
    } catch (e: any) {
      const isCurrent = (isPR && selectedPR.value?.pr_number === number)
        || (!isPR && selectedIssue.value?.number === number)
      if (isCurrent) {
        aiSummary.value = `**摘要生成失败**：${e.message}`
      }
    } finally {
      delete pendingSummaries.value[pendingKey]
      if (selectedPR.value?.pr_number === number || selectedIssue.value?.number === number) {
        aiSummaryLoading.value = false
      }
    }
  }

  // AI review
  async function generateReview() {
    if (!selectedPR.value || aiReviewLoading.value) return
    const prNumber = selectedPR.value.pr_number
    aiReview.value = null
    aiReviewLoading.value = true
    aiReviewElapsed.value = 0
    aiReviewCollapsed.value = false
    pendingReviews.value[prNumber] = true
    // 切换到 review tab
    prDetailTab.value = 'review'
    if (aiReviewTimer.value) clearInterval(aiReviewTimer.value)
    aiReviewTimer.value = setInterval(() => { aiReviewElapsed.value++ }, 1000)

    try {
      await api('/api/ai-assistant/clear-cache', {
        method: 'POST',
        body: JSON.stringify({ item_type: 'pr', number: prNumber, action: 'review' }),
      }, { timeout: 5000 })
    } catch (_) {}

    try {
      const review = await api('/api/ai-assistant/generate-review', {
        method: 'POST',
        body: JSON.stringify({ pr_number: prNumber, include_diff: true, repo: selectedPR.value.repo }),
      }, { timeout: 150000 })
      if (selectedPR.value?.pr_number === prNumber) {
        aiReview.value = review
      }
    } catch (e: any) {
      if (selectedPR.value?.pr_number === prNumber) {
        aiReview.value = `**Review 生成失败**：${e.message}`
        useAppStore().showToast('AI Review 失败', e.message, 'error')
      }
    } finally {
      delete pendingReviews.value[prNumber]
      if (aiReviewTimer.value) { clearInterval(aiReviewTimer.value); aiReviewTimer.value = null }
      if (selectedPR.value?.pr_number === prNumber) {
        aiReviewLoading.value = false
      }
    }
  }

  // Translate
  async function translateBody(itemType: string) {
    if (translateLoading.value) return
    const isPR = itemType === 'pr'
    const number = isPR ? (selectedPR.value?.pr_number) : (selectedIssue.value?.number)
    const body = isPR ? (prDetails.value?.pr?.body || '') : (issueDetails.value?.body || '')
    if (!body) {
      useAppStore().showToast('无内容可翻译', '', 'info')
      return
    }
    translateLoading.value = true
    try {
      const result: any = await api('/api/ai-assistant/translate', {
        method: 'POST',
        body: JSON.stringify({ item_type: itemType, number, text: body }),
      }, { timeout: 120000 })
      if (isPR) {
        prTranslatedBody.value = result.translated
        prShowChinese.value = true
      } else {
        issueTranslatedBody.value = result.translated
        issueShowChinese.value = true
      }
      useAppStore().showToast('翻译完成', '', 'success')
    } catch (e: any) {
      useAppStore().showToast('翻译失败', e.message, 'error')
    } finally {
      translateLoading.value = false
    }
  }

  // Detail tabs (no 'translate' — translation is a toggle inside details tab)
  const prDetailTab = ref<'details' | 'summary' | 'review'>('details')
  const issueDetailTab = ref<'details' | 'summary'>('details')

  return {
    myPrs, myIssues, contributionTab, prState,
    myIssuesState, myIssuesType, filterConflicts, filterCIFail,
    selectedContributor, selectedContributorGithubId,
    contributionRepo, trackedRepos,
    selectedPR, prDetails, prLoadError, loadingDetails,
    aiReview, aiReviewLoading, aiReviewElapsed,
    aiSummary, aiSummaryLoading,
    selectedIssue, issueDetails, issueLoadError, loadingIssue,
    translateLoading, prTranslatedBody, issueTranslatedBody,
    prShowChinese, issueShowChinese,
    prDetailTab, issueDetailTab,
    expandedDiffFile, fileDiffs,
    filteredMyPRs, filteredMyIssues, openIssueCount, closedIssueCount, allIssueCount,
    switchPRState, switchContributionTab, switchMyIssuesState, switchMyIssuesType,
    switchContributionRepo,
    loadMyPRs, loadMyIssues, loadAllContribData,
    openPR, closePR, openIssue, closeIssue,
    loadPRDiff, toggleFileDiff,
    generateSummary, generateReview, translateBody,
  }
})