import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAppStore } from './app'

export interface AIRule {
  id: number
  name: string
  prompt: string
  item_type: 'pr' | 'issue' | 'both' | 'commit'
  include_commits: boolean
  repos: string[]
  areas: string[]
  enabled: boolean
  sort_order: number
  last_triage_at: string | null
  last_run_at: string | null
  last_error: string | null
  match_count?: number
}

/** 表单三开关 → 后端 item_type + include_commits */
export function deriveItemTypes(t: { pr: boolean; issue: boolean; commit: boolean }):
  { item_type: 'pr' | 'issue' | 'both' | 'commit'; include_commits: boolean } {
  if (!t.pr && !t.issue) {
    // PR/Issue 都不选 = 仅 Commit 规则
    return { item_type: 'commit', include_commits: true }
  }
  const item_type = t.pr && t.issue ? 'both' : t.pr ? 'pr' : 'issue'
  return { item_type, include_commits: t.commit }
}

/** 已存规则 → 类型徽章文案（PR / Issue / Commit 的启用组合） */
export function ruleTypeLabel(rule: Pick<AIRule, 'item_type' | 'include_commits'>): string {
  const parts: string[] = []
  if (rule.item_type === 'pr' || rule.item_type === 'both') parts.push('PR')
  if (rule.item_type === 'issue' || rule.item_type === 'both') parts.push('Issue')
  if (rule.item_type === 'commit' || rule.include_commits !== false) parts.push('Commit')
  return parts.join('+') || 'PR+Issue'
}

export const useRulesStore = defineStore('rules', () => {
  const rules = ref<AIRule[]>([])
  const loading = ref(false)

  // Manager modal
  const showRulesManager = ref(false)
  const editingMode = ref<'list' | 'edit'>('list')
  const editingRuleId = ref<number | null>(null) // null = 新建
  const ruleForm = ref({
    name: '',
    prompt: '',
    // 条目类型三开关；保存时推导为后端的 item_type + include_commits
    types: { pr: true, issue: true, commit: true },
    repos: [] as string[],
    areas: [] as string[],
    enabled: true,
  })
  const ruleSaving = ref(false)

  // 命中结果缓存（ruleId -> items）
  const matches = ref<Record<number, any[]>>({})
  const matchesLoading = ref<Record<number, boolean>>({})
  // 正在分诊中的规则（触发后轮询直到 last_run_at 变化）
  const runningRuleIds = ref<Set<number>>(new Set())

  const enabledRules = computed(() =>
    rules.value.filter(r => r.enabled).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
  )

  async function loadRules() {
    loading.value = true
    try {
      const data: any = await api('/api/rules')
      rules.value = data.rules || []
    } catch (e: any) {
      useAppStore().showToast('加载筛选规则失败', e.message, 'error')
    } finally {
      loading.value = false
    }
  }

  async function loadMatches(ruleId: number) {
    matchesLoading.value[ruleId] = true
    try {
      const data: any = await api(`/api/rules/${ruleId}/matches?limit=100`)
      matches.value[ruleId] = data.items || []
    } catch (e: any) {
      useAppStore().showToast('加载筛选结果失败', e.message, 'error')
    } finally {
      matchesLoading.value[ruleId] = false
    }
  }

  /**
   * 触发一次分诊。后端是后台线程执行，这里轮询 last_run_at 变化作为完成信号，
   * 完成后自动刷新命中列表。
   */
  async function runRule(ruleId: number, rerun = false) {
    try {
      const resp: any = await api(`/api/rules/${ruleId}/run?rerun=${rerun}`, { method: 'POST' })
      if (!resp.triggered) {
        useAppStore().showToast('已在运行中', '请稍候', 'info')
        return
      }
    } catch (e: any) {
      useAppStore().showToast('触发失败', e.message, 'error')
      return
    }
    const before = rules.value.find(r => r.id === ruleId)?.last_run_at
    runningRuleIds.value.add(ruleId)
    useAppStore().showToast(rerun ? '已开始重新筛选' : '已开始筛选', 'AI 正在分析社区条目，完成后自动刷新', 'info')
    let tries = 0
    const timer = setInterval(async () => {
      tries++
      try {
        const data: any = await api('/api/rules')
        const updated = (data.rules || []).find((r: AIRule) => r.id === ruleId)
        if (updated) {
          const idx = rules.value.findIndex(r => r.id === ruleId)
          if (idx !== -1) rules.value[idx] = { ...rules.value[idx], ...updated }
          if (updated.last_run_at && updated.last_run_at !== before) {
            clearInterval(timer)
            runningRuleIds.value.delete(ruleId)
            await loadMatches(ruleId)
            useAppStore().showToast('筛选完成', `命中 ${updated.match_count ?? 0} 条`, 'success')
            return
          }
        }
      } catch (_) {}
      if (tries >= 60) {
        clearInterval(timer)
        runningRuleIds.value.delete(ruleId)
      }
    }, 3000)
  }

  async function toggleEnabled(rule: AIRule) {
    try {
      await api(`/api/rules/${rule.id}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !rule.enabled }),
      })
      rule.enabled = !rule.enabled
    } catch (e: any) {
      useAppStore().showToast('更新失败', e.message, 'error')
    }
  }

  async function saveRule() {
    if (ruleSaving.value) return
    if (!ruleForm.value.name.trim() || !ruleForm.value.prompt.trim()) {
      useAppStore().showToast('请填写完整', '规则名称和筛选要求不能为空', 'error')
      return
    }
    ruleSaving.value = true
    try {
      const { types, ...rest } = ruleForm.value
      const payload = JSON.stringify({ ...rest, ...deriveItemTypes(types) })
      if (editingRuleId.value !== null) {
        await api(`/api/rules/${editingRuleId.value}`, { method: 'PUT', body: payload })
      } else {
        const created: any = await api('/api/rules', { method: 'POST', body: payload })
        await loadRules()
        // 新建后立即跑一轮，让 tab 尽快有内容
        if (created?.id && created.enabled) runRule(created.id)
      }
      await loadRules()
      useAppStore().showToast('规则已保存', '', 'success')
      backToList()
    } catch (e: any) {
      useAppStore().showToast('保存失败', e.message, 'error')
    } finally {
      ruleSaving.value = false
    }
  }

  async function deleteRule(rule: AIRule) {
    const result = await useAppStore().showConfirm({
      title: '删除规则',
      message: `确认删除规则「${rule.name}」？其命中结果将一并删除。`,
      confirmText: '确认删除',
      danger: true,
    })
    if (!result.confirmed) return
    try {
      await api(`/api/rules/${rule.id}`, { method: 'DELETE' })
      delete matches.value[rule.id]
      await loadRules()
      useAppStore().showToast('规则已删除', '', 'success')
    } catch (e: any) {
      useAppStore().showToast('删除失败', e.message, 'error')
    }
  }

  function openManager() {
    showRulesManager.value = true
    editingMode.value = 'list'
    loadRules()
  }

  function closeManager() {
    showRulesManager.value = false
    backToList()
  }

  function openCreate() {
    editingMode.value = 'edit'
    editingRuleId.value = null
    ruleForm.value = { name: '', prompt: '', types: { pr: true, issue: true, commit: true }, repos: [], areas: [], enabled: true }
  }

  function openEdit(rule: AIRule) {
    editingMode.value = 'edit'
    editingRuleId.value = rule.id
    ruleForm.value = {
      name: rule.name,
      prompt: rule.prompt,
      types: {
        pr: rule.item_type === 'pr' || rule.item_type === 'both',
        issue: rule.item_type === 'issue' || rule.item_type === 'both',
        commit: rule.item_type === 'commit' || rule.include_commits !== false,
      },
      repos: [...(rule.repos || [])],
      areas: [...(rule.areas || [])],
      enabled: rule.enabled,
    }
  }

  function backToList() {
    editingMode.value = 'list'
    editingRuleId.value = null
  }

  return {
    rules, loading, enabledRules,
    showRulesManager, editingMode, editingRuleId, ruleForm, ruleSaving,
    matches, matchesLoading, runningRuleIds,
    loadRules, loadMatches, runRule, toggleEnabled, saveRule, deleteRule,
    openManager, closeManager, openCreate, openEdit, backToList,
  }
})
