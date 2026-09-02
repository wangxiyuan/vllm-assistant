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

function issueTypePrefix(issue: { title: string }): string | null {
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

/** 从 item 的 repo 字段和 number/type 生成 GitHub URL */
export function ghUrl(repo: string | undefined, number: number, type: 'pr' | 'issue'): string {
  const full = repo || 'vllm-project/vllm'
  const seg = type === 'pr' ? 'pull' : 'issues'
  return `https://github.com/${full}/${seg}/${number}`
}

/** 从 commit 的 repo 全名和 sha 生成 GitHub commit URL */
export function ghCommitUrl(repo: string | undefined, sha: string): string {
  const full = repo || 'vllm-project/vllm'
  return `https://github.com/${full}/commit/${sha}`
}

/* ── Dynamic source badge colors ──
   Report sources come from a dynamically growing repo list (vllm, sglang,
   vllm-omni, ...). Instead of a hardcoded CSS class per repo, unknown sources
   get a deterministic hue derived from the repo name.

   Curated sources keep fixed CSS classes (vllm = blue, sglang = green, ...).
   Dynamic repos use a continuous hue so two repos practically never get the
   exact same color; saturation/lightness stay inside the theme's signal range
   to keep the badges visually consistent. If the hashed hue would land inside
   a curated source's hue family, it is rotated away so a new repo can never
   render with nearly the same color as an existing curated source. */
export const CURATED_SOURCES = new Set(['vllm', 'vllm-ascend', 'sglang', 'academic', 'news'])

export interface SourceBadgeVars {
  '--src-color': string
  '--src-glow': string
  '--src-border': string
}

/* Approximate hue of each curated source's fixed CSS color. */
const CURATED_HUES = [205, 126, 270, 47, 185]
const CURATED_HUE_MARGIN = 26
const GOLDEN_ANGLE = 137.508

function _sourceHash(name: string): number {
  // MurmurHash3-style mixer so repo names sharing prefixes (vllm-*, qwen-*)
  // spread out instead of clustering onto adjacent values.
  let h = (name.length ^ 0xdeadbeef) >>> 0
  const c1 = 0xcc9e2d51
  const c2 = 0x1b873593
  for (let i = 0; i < name.length; i++) {
    let k = name.charCodeAt(i)
    k = Math.imul(k, c1) >>> 0
    k = (k << 15) | (k >>> 17)
    k = Math.imul(k, c2) >>> 0
    h ^= k
    h = ((h << 13) | (h >>> 19)) >>> 0
    h = (Math.imul(h, 5) + 0xe6546b64) >>> 0
  }
  h ^= name.length
  h ^= h >>> 16
  h = Math.imul(h, 0x85ebca6b) >>> 0
  h ^= h >>> 13
  h = Math.imul(h, 0xc2b2ae35) >>> 0
  h ^= h >>> 16
  return h >>> 0
}

function _hueDistance(a: number, b: number): number {
  const d = Math.abs(a - b)
  return Math.min(d, 360 - d)
}

export function sourceBadgeVars(source: string): SourceBadgeVars {
  const base = _sourceHash(source) % 360
  const seed = _sourceHash(source + ':escape')
  let hue = base
  let attempts = 0
  while (attempts < 8) {
    const nearCurated = CURATED_HUES.some(r => _hueDistance(hue, r) < CURATED_HUE_MARGIN)
    if (!nearCurated) break
    // Rotate by golden angle with a per-source step so escapes spread out.
    const step = 2 + ((seed >>> attempts) % 3)
    hue = (hue + GOLDEN_ANGLE * step) % 360
    attempts++
  }
  const s = 78
  const l = 74
  return {
    '--src-color': `hsl(${hue}, ${s}%, ${l}%)`,
    '--src-glow': `hsla(${hue}, ${s}%, ${l}%, 0.16)`,
    '--src-border': `hsla(${hue}, ${s}%, ${l}%, 0.34)`,
  }
}