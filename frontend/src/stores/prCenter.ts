import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import { useWatchlistStore } from './watchlist'
import { issueType } from '@/utils/helpers'
import type { PR, Issue, PRDetails, Stats } from '@/utils/types'

export const usePRCenterStore = defineStore('prCenter', () => {
  // PR list
  const myPrs = ref<PR[]>([])
  const myIssues = ref<Issue[]>([])
  const myStats = ref<Stats | null>(null)
  const statsLoading = ref(false)
  const contributionTab = ref<'prs' | 'issues'>('prs')
  const prState = ref('open')
  const myIssuesState = ref('open')
  const myIssuesType = ref('all')
  const filterConflicts = ref(false)
  const filterCIFail = ref(false)
  const selectedContributor = ref<{ id: number; name: string; github_id: string } | null>(null)
  const selectedContributorGithubId = ref('')

  // PR drawer
  const selectedPR = ref<any>(null)
  const prDetails = ref<PRDetails | null>(null)
  const prLoadError = ref<string | null>(null)
  const loadingDetails = ref(false)
  const aiReview = ref<any>(null)
  const aiReviewLoading = ref(false)
  const aiReviewElapsed = ref(0)
  const aiReviewTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const aiSummary = ref<any>(null)
  const aiSummaryLoading = ref(false)
  const aiSummaryCollapsed = ref(false)
  const aiReviewCollapsed = ref(false)
  const pendingReviews = ref<Record<number, boolean>>({})
  const pendingSummaries = ref<Record<string, boolean>>({})

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
  const prDiffData = ref<string | null>(null)
  const prDiffLoading = ref(false)

  // Computed
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

  const myIssueTypeCounts = computed(() => {
    const counts: Record<string, number> = { all: myIssues.value.length }
    for (const i of myIssues.value) {
      const t = issueType(i)
      counts[t] = (counts[t] || 0) + 1
    }
    return counts
  })

  const openPRCount = computed(() => myPrs.value.filter(p => p.state === 'open').length)
  const mergedPRCount = computed(() => myPrs.value.filter(p => p.state === 'merged').length)
  const closedPRCount = computed(() => myPrs.value.filter(p => p.state === 'closed').length)
  const allPRCount = computed(() => myPrs.value.length)
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

  function switchMyIssuesState(state: string) {
    myIssuesState.value = state
  }

  function switchMyIssuesType(type: string) {
    myIssuesType.value = type
  }

  async function loadMyPRs() {
    try {
      const githubId = selectedContributor.value?.github_id
      const url = githubId
        ? `/api/pr-center/my-prs?state=all&github_id=${encodeURIComponent(githubId)}`
        : '/api/pr-center/my-prs?state=all'
      myPrs.value = await api(url)
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

  async function loadMyStats() {
    statsLoading.value = true
    try {
      const githubId = selectedContributor.value?.github_id
      const url = githubId
        ? `/api/my-stats?github_id=${encodeURIComponent(githubId)}`
        : '/api/my-stats'
      myStats.value = await api(url)
    } catch (e: any) {
      useAppStore().showToast('加载数据失败', e.message, 'error')
    } finally {
      statsLoading.value = false
    }
  }

  function switchContributor(githubId: string) {
    if (githubId) {
      selectedContributor.value = useAppStore().areas.reduce((acc: any, _a) => acc, null) // Will be fixed
      // Actually use users store
      selectedContributorGithubId.value = githubId || ''
    } else {
      selectedContributor.value = null
      selectedContributorGithubId.value = ''
    }
    loadAllContribData()
  }

  function loadAllContribData() {
    loadMyStats()
    loadMyPRs()
    if (contributionTab.value === 'issues') loadMyIssues()
  }

  // PR drawer
  async function openPR(pr: any) {
    const watchlistStore = useWatchlistStore()
    const wl = watchlistStore.findWatchlistItem(pr.pr_number || pr.number, 'pr')
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
      prDetails.value = await api(`/api/pr-center/my-prs/${pr.pr_number || pr.number}/details`)
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
    const wl = watchlistStore.findWatchlistItem(issue.number, 'issue')
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
        issueDetails.value = await api(`/api/pr-center/issue/${issue.number}/body`)
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
      const data: any = await api(`/api/pr-center/my-prs/${selectedPR.value.pr_number}/diff`, {}, { timeout: 60000 })
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
        aiSummary.value = { error: e.message }
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
        body: JSON.stringify({ pr_number: prNumber, include_diff: true }),
      }, { timeout: 150000 })
      if (selectedPR.value?.pr_number === prNumber) {
        aiReview.value = review
        if (review.error) useAppStore().showToast('AI Review 异常', review.error, 'error')
      }
    } catch (e: any) {
      if (selectedPR.value?.pr_number === prNumber) {
        aiReview.value = { error: e.message }
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

  // Chart helpers
  function monthBarHeight(count: number, allMonthly: Record<string, number>) {
    const max = Math.max(...Object.values(allMonthly), 1)
    return Math.round((count / max) * 100)
  }

  function formatMonthLabel(month: string) {
    if (!month) return ''
    const [year, mon] = month.split('-')
    const all = Object.keys(myStats.value?.monthly?.created || {})
    const sameYearMonths = all.filter(m => m.startsWith(year + '-'))
    if (sameYearMonths[0] === month) {
      return year.slice(2) + '/' + mon
    }
    return mon
  }

  return {
    myPrs, myIssues, myStats, statsLoading, contributionTab, prState,
    myIssuesState, myIssuesType, filterConflicts, filterCIFail,
    selectedContributor, selectedContributorGithubId,
    selectedPR, prDetails, prLoadError, loadingDetails,
    aiReview, aiReviewLoading, aiReviewElapsed, aiReviewTimer,
    aiSummary, aiSummaryLoading, aiSummaryCollapsed, aiReviewCollapsed,
    pendingReviews, pendingSummaries,
    selectedIssue, issueDetails, issueLoadError, loadingIssue,
    translateLoading, prTranslatedBody, issueTranslatedBody,
    prShowChinese, issueShowChinese,
    expandedDiffFile, fileDiffs, prDiffData, prDiffLoading,
    filteredMyPRs, filteredMyIssues, myIssueTypeCounts,
    openPRCount, mergedPRCount, closedPRCount, allPRCount,
    openIssueCount, closedIssueCount, allIssueCount,
    switchPRState, switchContributionTab, switchMyIssuesState, switchMyIssuesType,
    loadMyPRs, loadMyIssues, loadMyStats, switchContributor, loadAllContribData,
    openPR, closePR, openIssue, closeIssue,
    loadPRDiff, toggleFileDiff,
    generateSummary, generateReview, translateBody,
    monthBarHeight, formatMonthLabel,
  }
})