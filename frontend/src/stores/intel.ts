import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'
import { CURATED_SOURCES, sourceBadgeVars, type SourceBadgeVars } from '@/utils/helpers'
import type { IntelReport } from '@/utils/types'

export const useIntelStore = defineStore('intel', () => {
  const reports = ref<IntelReport[]>([])
  const loading = ref(false)
  const showModal = ref(false)
  const intelForm = ref({
    task_id: '',
    title: '',
    sources: [] as string[],
    excluded_sources: [] as string[],
    extra_prompt: '',
  })
  const genLoading = ref(false)
  const intelTasks = ref<any[]>([])
  const selectedReport = ref<IntelReport | null>(null)
  const reportDetails = ref<any>(null)
  const reportModalLoading = ref(false)
  const pollingTimer = ref<ReturnType<typeof setTimeout> | null>(null)
  const dailyGenLoading = ref(false)
  // 报告生成进度：report_id -> 进度对象
  const reportProgress = ref<Record<number, any>>({})

  async function loadReports() {
    loading.value = true
    try {
      const data: any = await api('/api/intelligence/reports')
      reports.value = data.reports || []
      // 自动接管仍在生成中的报告（含每日报告，其占位记录为 generating）
      for (const r of reports.value) {
        if (r.status === 'generating') {
          pollReportStatus(r.id)
        }
      }
    } catch (e: any) {
      useAppStore().showToast('加载报告失败', e.message, 'error')
    } finally {
      loading.value = false
    }
  }

  async function loadIntelTasks() {
    try {
      const params = new URLSearchParams()
      params.set('status', 'all')
      params.set('per_page', '50')
      const data: any = await api('/api/personal-todo/tasks?' + params)
      intelTasks.value = data.tasks || []
    } catch (_) {}
  }

  function openModal() {
    showModal.value = true
    loadIntelTasks()
    // 初始化默认来源：从仓库列表和固定来源中填充
    if (intelForm.value.sources.length === 0) {
      const defaultSources = ['academic', 'news']
      // 通过 API 获取仓库列表
      api('/api/repos').then((data: any) => {
        const repos = data.repos || []
        const repoNames = repos.map((r: any) => r.repo)
        intelForm.value.sources = [...repoNames, ...defaultSources]
      }).catch(() => {
        intelForm.value.sources = [...defaultSources]
      })
    }
  }

  function toggleSource(source: string) {
    const idx = intelForm.value.sources.indexOf(source)
    if (idx >= 0) {
      intelForm.value.sources.splice(idx, 1)
    } else {
      intelForm.value.sources.push(source)
    }
  }

  function isSourceSelected(source: string): boolean {
    return intelForm.value.sources.includes(source)
  }

  async function generateReport() {
    if (intelForm.value.sources.length === 0) {
      useAppStore().showToast('请选择来源', '至少选择一个来源', 'error')
      return
    }
    if (genLoading.value) return
    genLoading.value = true
    try {
      const payload: any = {
        sources: intelForm.value.sources,
        excluded_sources: intelForm.value.excluded_sources,
        extra_prompt: intelForm.value.extra_prompt,
      }
      // 关联任务可选，仅在没有标题时用于默认标题
      if (intelForm.value.task_id) payload.task_id = parseInt(intelForm.value.task_id, 10)
      if (intelForm.value.title.trim()) payload.title = intelForm.value.title.trim()
      const result: any = await api('/api/intelligence/reports/generate', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, { timeout: 30000 })
      useAppStore().showToast('报告生成中', result.message || '请稍后查看', 'success', 6000)
      showModal.value = false
      reports.value.unshift({
        id: result.report_id,
        title: result.title,
        task_id: result.task_id,
        sources: intelForm.value.sources,
        created_at: new Date().toISOString(),
        status: 'generating',
        word_count: 0,
      })
      intelForm.value.title = ''
      intelForm.value.extra_prompt = ''
      pollReportStatus(result.report_id)
    } catch (e: any) {
      useAppStore().showToast('生成失败', e.message, 'error')
    } finally {
      genLoading.value = false
    }
  }

  function pollReportStatus(reportId: number) {
    if (pollingTimer.value) clearTimeout(pollingTimer.value)
    const startTime = Date.now()
    const timeout = 600000
    let attempt = 0
    const poll = async () => {
      attempt++
      if (Date.now() - startTime > timeout) {
        pollingTimer.value = null
        return
      }
      try {
        const report: any = await api(`/api/intelligence/reports/${reportId}`, {}, { timeout: 10000 })
        const idx = reports.value.findIndex(r => r.id === reportId)
        if (idx >= 0) {
          reports.value[idx] = {
            ...reports.value[idx],
            status: report.status,
            word_count: report.word_count,
            error_message: report.error_message,
          }
        }
        // 并行拉取阶段进度（不阻塞状态更新）
        fetchReportProgress(reportId)
        if (selectedReport.value?.id === reportId) {
          reportDetails.value = report
        }
        if (report.status === 'completed' || report.status === 'failed') {
          pollingTimer.value = null
          // 清理进度
          delete reportProgress.value[reportId]
          if (report.status === 'completed') {
            useAppStore().showToast('报告已生成', report.title, 'success')
          } else {
            useAppStore().showToast('报告生成失败', report.error_message || '未知错误', 'error')
          }
          return
        }
      } catch (_) {}
      const delay = Math.min(3000 * Math.pow(2, attempt - 1), 30000)
      pollingTimer.value = setTimeout(poll, delay)
    }
    poll()
  }

  async function fetchReportProgress(reportId: number) {
    try {
      const prog: any = await api(`/api/intelligence/reports/${reportId}/progress`, {}, { timeout: 15000 })
      if (prog && prog.status === 'running') {
        reportProgress.value[reportId] = prog
      }
    } catch (_) {
      // 进度接口不可用/已结束则忽略
    }
  }

  async function viewReport(report: IntelReport) {
    selectedReport.value = report
    reportDetails.value = null
    reportModalLoading.value = true
    try {
      reportDetails.value = await api(`/api/intelligence/reports/${report.id}`)
      // 查看的是生成中的报告 → 拉取并持续轮询进度
      if (report.status === 'generating') {
        await fetchReportProgress(report.id)
        pollReportStatus(report.id)
      }
    } catch (e: any) {
      useAppStore().showToast('加载报告失败', e.message, 'error')
    } finally {
      reportModalLoading.value = false
    }
  }

  function closeReport() {
    selectedReport.value = null
    reportDetails.value = null
  }

  async function deleteReport(report: IntelReport) {
    const appStore = useAppStore()
    const result = await appStore.showConfirm({
      title: '删除报告',
      message: `确认删除报告 "${report.title}"？此操作不可撤销。`,
      confirmText: '删除',
      danger: true,
      showKnowledgeSyncCheckbox: true,
    })
    if (!result.confirmed) return
    const backup = { ...report }
    try {
      await api(`/api/intelligence/reports/${report.id}`, { method: 'DELETE' })
      if (result.syncDeleteKnowledge) {
        try {
          await api(`/api/ai-agent/memories/by-source?source_ref_prefix=intelligence_report::${report.id}`, { method: 'DELETE' })
        } catch (_) {}
      }
      reports.value = reports.value.filter(r => r.id !== report.id)
      if (selectedReport.value?.id === report.id) closeReport()
      appStore.showUndoToast('已删除', report.title, async () => {
        try {
          const payload: any = {
            task_id: backup.task_id,
            sources: backup.sources || [],
            excluded_sources: backup.excluded_sources || [],
            extra_prompt: backup.extra_prompt || '',
          }
          if (backup.title) payload.title = backup.title
          const result: any = await api('/api/intelligence/reports/generate', {
            method: 'POST',
            body: JSON.stringify(payload),
          }, { timeout: 30000 })
          reports.value.unshift({
            id: result.report_id, title: result.title || backup.title,
            task_id: backup.task_id, sources: payload.sources,
            created_at: new Date().toISOString(), status: 'generating' as const, word_count: 0,
          })
          pollReportStatus(result.report_id)
          appStore.showToast('已重新生成', '', 'success')
        } catch (e: any) {
          appStore.showToast('恢复失败', e.message, 'error')
        }
      }, 10000)
    } catch (e: any) {
      appStore.showToast('删除失败', e.message, 'error')
    }
  }

  async function regenerateReport(report: IntelReport) {
    const appStore = useAppStore()
    const result = await appStore.showConfirm({
      title: '重新生成报告',
      message: `确认重新生成报告 "${report.title}"？`,
      confirmText: '重新生成',
    })
    if (!result.confirmed) return
    try {
      const payload: any = {
        report_id: report.id,
        task_id: report.task_id,
        sources: report.sources || [],
        excluded_sources: report.excluded_sources || [],
        extra_prompt: report.extra_prompt || '',
      }
      const result: any = await api('/api/intelligence/reports/generate', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, { timeout: 30000 })
      appStore.showToast('重新生成中', result.message, 'success')
      // 用新 report_id 替换旧记录，保持列表位置不变
      const idx = reports.value.findIndex(r => r.id === report.id)
      if (idx >= 0) {
        reports.value[idx] = {
          id: result.report_id,
          title: result.title,
          task_id: result.task_id,
          sources: payload.sources,
          created_at: new Date().toISOString(),
          status: 'generating' as const,
          word_count: 0,
        }
      } else {
        reports.value.unshift({
          id: result.report_id, title: result.title,
          task_id: result.task_id, sources: payload.sources,
          created_at: new Date().toISOString(), status: 'generating' as const, word_count: 0,
        })
      }
      pollReportStatus(result.report_id)
    } catch (e: any) {
      appStore.showToast('重新生成失败', e.message, 'error')
    }
  }

  async function copyReportMarkdown() {
    if (!reportDetails.value || !reportDetails.value.content) {
      useAppStore().showToast('无内容', '报告内容尚未加载', 'error')
      return
    }
    try {
      if (!navigator.clipboard) {
        const textarea = document.createElement('textarea')
        textarea.value = reportDetails.value.content
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        textarea.style.pointerEvents = 'none'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
        useAppStore().showToast('已复制', 'Markdown 内容已复制到剪贴板', 'success')
        return
      }
      await navigator.clipboard.writeText(reportDetails.value.content)
      useAppStore().showToast('已复制', 'Markdown 内容已复制到剪贴板', 'success')
    } catch {
      useAppStore().showToast('复制失败', '请手动选择文本复制', 'error')
    }
  }

  async function triggerDailyReport() {
    if (dailyGenLoading.value) return
    dailyGenLoading.value = true
    try {
      const result: any = await api('/api/intelligence/reports/daily/trigger', { method: 'POST' })
      if (result.status === 'skipped') {
        useAppStore().showToast('无需生成', result.message, 'info', 5000)
      } else {
        useAppStore().showToast('每日报告生成中', result.message, 'success', 6000)
        setTimeout(() => loadReports(), 5000)
      }
    } catch (e: any) {
      useAppStore().showToast('触发失败', e.message, 'error')
    } finally {
      dailyGenLoading.value = false
    }
  }

  function intelSourceLabel(source: string): string {
    const map: Record<string, string> = { academic: '学术', news: '新闻' }
    return map[source] || source
  }

  function intelSourceClass(source: string): string {
    return CURATED_SOURCES.has(source) ? 'source-' + source : 'source-dynamic'
  }

  function intelSourceStyle(source: string): Record<string, string> {
    if (CURATED_SOURCES.has(source)) return {}
    return sourceBadgeVars(source) as unknown as Record<string, string>
  }

  return {
    reports, loading, showModal, intelForm, genLoading, intelTasks,
    selectedReport, reportDetails, reportModalLoading, pollingTimer, reportProgress,
    loadReports, loadIntelTasks, openModal, toggleSource, isSourceSelected,
    generateReport, pollReportStatus, fetchReportProgress, viewReport, closeReport,
    deleteReport, regenerateReport, copyReportMarkdown, triggerDailyReport,
    dailyGenLoading,
    intelSourceLabel, intelSourceClass, intelSourceStyle,
  }
})