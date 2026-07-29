export function esc(s: unknown): string {
  if (s == null) return ''
  return String(s).replace(/[&<>"']/g, (c) => {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c
  })
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return ''
  const now = new Date()
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000 / 60)
  if (diff < 1) return '刚刚'
  if (diff < 60) return `${diff} 分钟前`
  if (diff < 24 * 60) return `${Math.floor(diff / 60)} 小时前`
  return `${Math.floor(diff / (24 * 60))} 天前`
}

export function exactTime(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

export function issueTypePrefix(issue: { title: string }): string | null {
  const title = (issue.title || '').trim()
  const m = title.match(/^\[([^\]]+)\]/i)
  if (m) return m[1].toLowerCase()
  return null
}

export function issueType(issue: { title: string }): string {
  const raw = issueTypePrefix(issue)
  if (!raw) return 'other'
  const t = raw.toLowerCase()
  if (['bug', 'bug报告', '缺陷'].includes(t)) return 'bug'
  if (['rfc', 'proposal', '提案'].includes(t)) return 'rfc'
  if (['feature', 'feature request', '新功能', '需求'].includes(t)) return 'feature'
  if (['usage', 'question', 'help wanted', '问答', '求助'].includes(t)) return 'usage'
  if (['installation', 'install', '安装'].includes(t)) return 'installation'
  if (['performance', 'perf'].includes(t)) return 'performance'
  if (['doc', 'docs', 'documentation', '文档'].includes(t)) return 'doc'
  if (['ci', 'build'].includes(t)) return 'ci'
  if (['refactor', 'cleanup'].includes(t)) return 'refactor'
  return t
}

export function issueTypeLabel(type: string): string {
  const map: Record<string, string> = {
    bug: 'Bug', rfc: 'RFC', feature: '功能', usage: '使用',
    installation: '安装', performance: '性能', doc: '文档',
    ci: 'CI', refactor: '重构', other: '其他',
  }
  return map[type] || type
}

export function issueStateLabel(state: string): string {
  return { open: '开放', closed: '已关闭' }[state] || '开放'
}

export function prStateLabel(state: string): string {
  return { open: '开放', merged: '已合并', closed: '已关闭' }[state] || '开放'
}

export function ciLabel(status: string): string {
  return { pass: 'CI 通过', fail: 'CI 失败', pending: 'CI 进行中', unknown: 'CI 未知' }[status] || 'CI'
}

export function ciBadgeClass(status: string): string {
  return {
    pass: 'badge-ci-pass',
    fail: 'badge-ci-fail',
    pending: 'badge-ci-pending',
    unknown: 'badge-ci-unknown',
  }[status] || 'badge-ci-unknown'
}

export function severityLabel(sev: string): string {
  return { critical: '严重', important: '重要', minor: '次要', high: '高', medium: '中', low: '低' }[sev.toLowerCase()] || sev
}

export function sourceLabel(source: string): string {
  const map: Record<string, string> = { self: '主动规划', team: '产品反馈', community: '社区反馈' }
  return map[source] || source
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = { todo: '待处理', in_progress: '进行中', done: '已完成', cancelled: '已取消' }
  return map[status] || status
}

export function priorityClass(priority: string): string {
  return 'priority-' + (priority || 'P2').toLowerCase()
}

export function statusClass(status: string): string {
  return 'status-' + (status || 'todo')
}

export const repoMap: Record<string, string> = {
  vllm: 'vllm-project/vllm',
  'vllm-ascend': 'vllm-project/vllm-ascend',
}

export const intelSourceOptions = [
  { value: 'vllm', label: 'vLLM 社区' },
  { value: 'vllm-ascend', label: 'vLLM-Ascend' },
  { value: 'sglang', label: 'sglang' },
  { value: 'academic', label: '学术动态' },
  { value: 'news', label: '新闻动态' },
]

export const priorities = ['P0', 'P1', 'P2', 'P3']

export const sources = [
  { value: 'self', label: '主动规划' },
  { value: 'team', label: '产品反馈' },
  { value: 'community', label: '社区反馈' },
]

const _categoryColorPalette = [
  'var(--signal-blue)', 'var(--signal-green)', 'var(--signal-purple)',
  'var(--signal-cyan)', 'var(--amber)', 'var(--signal-red)',
  'var(--signal-yellow)', 'var(--text-tertiary)',
]

export function categoryColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0
  }
  return _categoryColorPalette[hash % _categoryColorPalette.length]
}

export function modelCategoryLabel(value: string): string {
  const map: Record<string, string> = {
    dense: 'Dense', moe: 'MoE', hybrid: 'Hybrid',
    state_space: 'State Space', other: 'Other',
  }
  return map[value] || value
}