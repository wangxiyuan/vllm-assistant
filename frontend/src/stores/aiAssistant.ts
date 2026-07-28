import { ref } from 'vue'
import { defineStore } from 'pinia'
import { useAppStore } from './app'
import { generateSummary, generateReview, translateText, getAICache, clearAICache } from '@/api/ai'

/**
 * AI 辅助功能 Store
 *
 * 管理 PR/Issue 的 AI review、摘要、翻译状态。
 * 从 prCenter.ts 中分离出来，专注 AI 功能。
 */
export const useAIAssistantStore = defineStore('aiAssistant', () => {
  // Review
  const aiReview = ref<any>(null)
  const aiReviewLoading = ref(false)
  const aiReviewElapsed = ref(0)
  const aiReviewTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const aiReviewCollapsed = ref(false)
  const pendingReviews = ref<Record<number, boolean>>({})

  // Summary
  const aiSummary = ref<any>(null)
  const aiSummaryLoading = ref(false)
  const aiSummaryCollapsed = ref(false)
  const pendingSummaries = ref<Record<string, boolean>>({})

  // Translate
  const translateLoading = ref(false)
  const prTranslatedBody = ref<string | null>(null)
  const issueTranslatedBody = ref<string | null>(null)
  const prShowChinese = ref(false)
  const issueShowChinese = ref(false)

  function resetReview() {
    aiReview.value = null
    aiReviewLoading.value = false
    aiReviewElapsed.value = 0
    aiReviewCollapsed.value = false
    if (aiReviewTimer.value) {
      clearInterval(aiReviewTimer.value)
      aiReviewTimer.value = null
    }
  }

  function resetSummary() {
    aiSummary.value = null
    aiSummaryLoading.value = false
    aiSummaryCollapsed.value = false
  }

  function resetTranslate() {
    translateLoading.value = false
    prTranslatedBody.value = null
    issueTranslatedBody.value = null
    prShowChinese.value = false
    issueShowChinese.value = false
  }

  function resetAll() {
    resetReview()
    resetSummary()
    resetTranslate()
  }

  /** 加载缓存的 AI 结果 */
  async function loadCachedAI(itemType: string, number: number) {
    try {
      const cachedSummary: any = await getAICache(itemType, number, 'summary')
      if (cachedSummary && !cachedSummary.empty) {
        aiSummary.value = cachedSummary
      }
      if (itemType === 'pr') {
        const cachedReview: any = await getAICache(itemType, number, 'review')
        if (cachedReview && !cachedReview.empty) {
          aiReview.value = cachedReview
        }
      }
    } catch (_) {}
  }

  /** 加载缓存的翻译 */
  async function loadCachedTranslate(itemType: string, number: number) {
    try {
      const cached: any = await getAICache(itemType, number, 'translate')
      if (cached && cached.translated) {
        if (itemType === 'pr') prTranslatedBody.value = cached.translated
        else issueTranslatedBody.value = cached.translated
      }
    } catch (_) {}
  }

  /** 生成 AI 摘要 */
  async function generate(itemType: string, number: number, title: string, body: string) {
    const pendingKey = itemType + ':' + number
    if (aiSummaryLoading.value) return

    aiSummary.value = null
    aiSummaryLoading.value = true
    aiSummaryCollapsed.value = false
    pendingSummaries.value[pendingKey] = true

    try {
      await clearAICache(itemType, number, 'summary')
    } catch (_) {}

    try {
      const res = await generateSummary(itemType, number, title, body)
      aiSummary.value = res
    } catch (e: any) {
      aiSummary.value = { error: e.message }
    } finally {
      delete pendingSummaries.value[pendingKey]
      aiSummaryLoading.value = false
    }
  }

  /** 生成 AI Review */
  async function review(prNumber: number) {
    if (aiReviewLoading.value) return

    aiReview.value = null
    aiReviewLoading.value = true
    aiReviewElapsed.value = 0
    aiReviewCollapsed.value = false
    pendingReviews.value[prNumber] = true

    if (aiReviewTimer.value) clearInterval(aiReviewTimer.value)
    aiReviewTimer.value = setInterval(() => { aiReviewElapsed.value++ }, 1000)

    try {
      await clearAICache('pr', prNumber, 'review')
    } catch (_) {}

    try {
      const review = await generateReview(prNumber, true)
      aiReview.value = review
      if (review.error) {
        useAppStore().showToast('AI Review 异常', review.error, 'error')
      }
    } catch (e: any) {
      aiReview.value = { error: e.message }
      useAppStore().showToast('AI Review 失败', e.message, 'error')
    } finally {
      delete pendingReviews.value[prNumber]
      if (aiReviewTimer.value) {
        clearInterval(aiReviewTimer.value)
        aiReviewTimer.value = null
      }
      aiReviewLoading.value = false
    }
  }

  /** 翻译正文 */
  async function translate(itemType: string, number: number, body: string) {
    if (translateLoading.value) return
    if (!body) {
      useAppStore().showToast('无内容可翻译', '', 'info')
      return
    }

    translateLoading.value = true
    try {
      const result: any = await translateText(itemType, number, body)
      if (itemType === 'pr') {
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

  return {
    // Review
    aiReview, aiReviewLoading, aiReviewElapsed, aiReviewTimer,
    aiReviewCollapsed, pendingReviews,
    // Summary
    aiSummary, aiSummaryLoading, aiSummaryCollapsed, pendingSummaries,
    // Translate
    translateLoading, prTranslatedBody, issueTranslatedBody,
    prShowChinese, issueShowChinese,
    // Methods
    resetAll, resetReview, resetSummary, resetTranslate,
    loadCachedAI, loadCachedTranslate,
    generate, review, translate,
 ​}
})