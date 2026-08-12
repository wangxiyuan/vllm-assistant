<script setup lang="ts">
import { ref, computed } from 'vue'
import { renderMarkdown } from '@/composables/useMarkdown'

const props = defineProps<{
  content: string
}>()

const activeTab = ref('yesterday')
const copyToast = ref(false)

const tabs = [
  { key: 'yesterday', label: '昨日数据' },
  { key: 'quality', label: '质量与架构' },
  { key: 'competitive', label: '竞品动态与对比' },
  { key: 'academic', label: '学术动态' },
  { key: 'news', label: '新闻动态' },
  { key: 'slack', label: 'Slack信息' },
  { key: 'contribution', label: '贡献机会' },
  { key: 'other', label: '其他' },
]

const tabHeadings: Record<string, string[]> = {
  yesterday: ['昨日概览', '昨日新增 Issue 明细', '昨日新增 PR 明细', '版本发布'],
  quality: ['质量与架构'],
  competitive: ['竞品动态与对比'],
  academic: ['学术动态'],
  news: ['新闻动态'],
  slack: ['Slack 信息'],
  contribution: ['贡献机会'],
  other: ['其他'],
}

function extractSection(content: string, key: string): string {
  const headings = tabHeadings[key]
  if (!headings || !content) return ''
  const lines = content.split('\n')
  const result: string[] = []
  let capturing = false
  for (const line of lines) {
    const trimmed = line.trim()
    const m = trimmed.match(/^##\s+(.+)$/)
    if (m) {
      const title = m[1]
      if (headings.some(h => title.includes(h) || h.includes(title))) {
        capturing = true
        continue
      }
      if (capturing) {
        capturing = false
        continue
      }
    }
    if (capturing) result.push(line)
  }
  return result.join('\n').trim()
}

const sections = computed(() =>
  tabs.map(t => ({ key: t.key, raw: extractSection(props.content, t.key) }))
)

const activeSection = computed(() =>
  sections.value.find(s => s.key === activeTab.value)
)

function makeLinksClickable(html: string): string {
  return html.replace(
    /#(\d{3,})/g,
    '<a class="issue-link" href="https://github.com/vllm-project/vllm/issues/$1" target="_blank" rel="noopener">#$1</a>'
  )
}

const renderedHtml = computed(() => {
  const sec = activeSection.value
  if (!sec || !sec.raw) return ''
  const raw = sec.raw
  switch (activeTab.value) {
    case 'yesterday': {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
        .replace(/<table>/g, '<table class="daily-overview-table">')
        .replace(/<code>([^<]+)<\/code>/g, '<span class="tag tag-$1">$1</span>')
        .replace(/\bmerged\b/g, '<span class="pr-status pr-merged">merged</span>')
        .replace(/\bWIP\b/g, '<span class="pr-status pr-wip">WIP</span>')
    }
    case 'quality': {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
        .replace(/<code>高<\/code>/g, '<span class="rlvl rlvl-high">高</span>')
        .replace(/<code>中<\/code>/g, '<span class="rlvl rlvl-mid">中</span>')
        .replace(/<code>低<\/code>/g, '<span class="rlvl rlvl-low">低</span>')
        .replace(/<blockquote>/g, '<blockquote class="qa-summary">')
    }
    case 'competitive': {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
        .replace(/<table>/g, '<table class="daily-sglang-table">')
        .replace(/\b已支持\b/g, '<span class="cmp cmp-yes">已支持</span>')
        .replace(/\b未支持\b/g, '<span class="cmp cmp-no">未支持</span>')
        .replace(/→\s*持平/g, '<span class="trend trend-flat">→ 持平</span>')
        .replace(/↑\s*追赶中/g, '<span class="trend trend-up">↑ 追赶中</span>')
        .replace(/↓\s*领先/g, '<span class="trend trend-down">↓ 领先</span>')
        .replace(/\[建议优先级:\s*([^\]]+)\]/g, '<span class="cmp-prio cmp-prio-$1">建议优先级: $1</span>')
    }
    case 'academic': {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
        .replace(/\[相关性:\s*([^\]]+)\]/g, '<span class="rel rel-$1">[相关性: $1]</span>')
    }
    case 'slack': {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
        .replace(/\*\*#(\w+)\*\*/g, '<span class="slack-channel">#$1</span>')
    }
    case 'contribution': {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
        .replace(/<code>good first issue<\/code>/g, '<span class="tag tag-good-first-issue">good first issue</span>')
        .replace(/<code>help wanted<\/code>/g, '<span class="tag tag-help-wanted">help wanted</span>')
        .replace(/<code>bug<\/code>/g, '<span class="tag tag-bug">bug</span>')
        .replace(/<code>feature<\/code>/g, '<span class="tag tag-feature">feature</span>')
        .replace(/<code>docs<\/code>/g, '<span class="tag tag-docs">docs</span>')
        .replace(/<code>performance<\/code>/g, '<span class="tag tag-performance">performance</span>')
        .replace(/来源:\s*([^\n]+)/g, '<span class="source-tag">来源: $1</span>')
        .replace(/\[预估:\s*([^\]]+)\]/g, '<span class="est">[预估: $1]</span>')
    }
    default: {
      const html = renderMarkdown(raw)
      return makeLinksClickable(html)
    }
  }
})

const meta = computed(() => {
  const text = props.content || ''
  const dateMatch = text.match(/(\d{4}-\d{2}-\d{2})/)
  const date = dateMatch ? dateMatch[1] : ''
  return { date }
})

function copyCurrentTab() {
  const sec = activeSection.value
  if (!sec || !sec.raw) return
  navigator.clipboard.writeText(sec.raw).then(() => {
    copyToast.value = true
    setTimeout(() => { copyToast.value = false }, 2000)
  }).catch(() => {})
}
</script>

<template>
  <div class="daily-report-render">
    <!-- 报告头部摘要 -->
    <div class="daily-header">
      <div class="daily-header-left">
        <span class="daily-header-title">vLLM 社区报告</span>
        <span v-if="meta.date" class="daily-header-date">{{ meta.date }}</span>
      </div>
      <div class="daily-header-right">
        <button class="daily-header-btn" title="复制当前 Tab 内容" @click="copyCurrentTab">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          复制
        </button>
        <span v-if="copyToast" class="daily-copy-toast">已复制</span>
      </div>
    </div>

    <!-- Tab 栏 -->
    <div class="daily-tab-bar">
      <button
        v-for="t in tabs"
        :key="t.key"
        :class="['daily-tab', { active: activeTab === t.key }]"
        @click="activeTab = t.key"
      >{{ t.label }}</button>
    </div>

    <!-- Tab 内容 -->
    <div class="daily-tab-content">
      <div v-if="!renderedHtml" class="daily-tab-empty">暂无数据</div>
      <div v-else class="daily-tab-body" v-html="renderedHtml"></div>
    </div>
  </div>
</template>

<style scoped>
.daily-report-render {
  --daily-border: var(--border-faint, #2e3848);
  --daily-accent: var(--amber, #e8964a);
  --daily-accent-light: var(--amber-glow-soft, rgba(255, 180, 84, 0.15));
  --daily-text: var(--text-primary, #e6edf3);
  --daily-text-secondary: var(--text-secondary, #9aa4b6);
  --daily-tab-bg: var(--bg-elev-1, #0f141d);
  --daily-tab-active-bg: var(--bg-elev-2, #161d28);
}

/* ── Header ── */
.daily-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 8px;
}
.daily-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.daily-header-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--daily-text);
}
.daily-header-date {
  font-size: 12px;
  font-family: var(--font-mono, monospace);
  color: var(--daily-text-secondary);
  background: var(--daily-accent-light);
  padding: 1px 8px;
  border-radius: 4px;
}
.daily-header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  position: relative;
}
.daily-header-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 1px solid var(--daily-border);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 11px;
  color: var(--daily-text-secondary);
  cursor: pointer;
  transition: all 0.12s;
}
.daily-header-btn:hover {
  color: var(--daily-accent);
  border-color: var(--daily-accent);
}
.daily-copy-toast {
  font-size: 11px;
  color: var(--signal-green);
  animation: fade-out 2s forwards;
}
@keyframes fade-out {
  0% { opacity: 1; }
  80% { opacity: 1; }
  100% { opacity: 0; }
}

/* ── Tab bar ── */
.daily-tab-bar {
  display: flex;
  gap: 2px;
  background: var(--daily-tab-bg);
  padding: 3px;
  border-radius: 8px 8px 0 0;
  border: 1px solid var(--daily-border);
  border-bottom: none;
  overflow-x: auto;
  flex-shrink: 0;
}
.daily-tab {
  padding: 7px 14px;
  background: transparent;
  border: none;
  border-radius: 6px 6px 0 0;
  color: var(--daily-text-secondary);
  font-family: var(--font-ui, inherit);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--t-base, 0.15s) var(--ease-out, ease-out);
  white-space: nowrap;
  flex-shrink: 0;
}
.daily-tab:hover {
  color: var(--daily-text);
  background: rgba(255, 255, 255, 0.04);
}
.daily-tab.active {
  color: var(--daily-accent);
  background: var(--daily-tab-active-bg);
  box-shadow: 0 -1px 0 var(--daily-accent);
  font-weight: 600;
}

/* ── Tab content ── */
.daily-tab-content {
  border: 1px solid var(--daily-border);
  border-radius: 0 0 8px 8px;
  padding: 16px 18px;
  font-size: 13px;
  line-height: 1.6;
  height: 560px;
  overflow-y: auto;
}

.daily-tab-body {
  flex: 1;
}
.daily-tab-empty {
  text-align: center;
  color: var(--daily-text-secondary);
  padding: 120px 0;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.daily-tab-body :deep(p) { margin: 6px 0; }
.daily-tab-body :deep(ul) { padding-left: 18px; margin: 6px 0; }
.daily-tab-body :deep(li) { margin: 4px 0; }
.daily-tab-body :deep(blockquote) {
  border-left: 3px solid var(--daily-accent);
  margin: 8px 0;
  padding: 6px 12px;
  background: var(--daily-accent-light);
  border-radius: 0 4px 4px 0;
  font-size: 12px;
  color: var(--daily-text-secondary);
}
.daily-tab-body :deep(a.issue-link) {
  color: var(--daily-accent);
  text-decoration: none;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
}
.daily-tab-body :deep(a.issue-link:hover) {
  text-decoration: underline;
}

/* ── Overview table ── */
.daily-overview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.daily-overview-table :deep(th) {
  background: var(--daily-accent-light);
  color: var(--daily-accent);
  font-weight: 600;
  padding: 8px 12px;
  text-align: left;
  border-bottom: 2px solid var(--daily-accent);
}
.daily-overview-table :deep(td) {
  padding: 8px 12px;
  border-bottom: 1px solid var(--daily-border);
}
.daily-overview-table :deep(tr:last-child td) { border-bottom: none; }

/* ── Tags ── */
.tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  font-family: inherit;
}
.tag-bug { background: var(--signal-red-glow); color: var(--signal-red); border: 1px solid rgba(255, 142, 133, 0.35); }
.tag-feature, .tag-enhancement { background: var(--signal-purple-glow); color: var(--signal-purple); border: 1px solid rgba(218, 178, 255, 0.35); }
.tag-performance { background: var(--signal-yellow-glow); color: var(--signal-yellow); border: 1px solid rgba(242, 204, 96, 0.35); }
.tag-good-first-issue { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }
.tag-help-wanted { background: var(--signal-cyan-glow); color: var(--signal-cyan); border: 1px solid rgba(106, 216, 223, 0.35); }
.tag-docs { background: var(--signal-blue-glow); color: var(--signal-blue); border: 1px solid rgba(132, 203, 255, 0.35); }

/* ── PR status ── */
.pr-status {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
}
.pr-merged { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }
.pr-wip { background: var(--signal-yellow-glow); color: var(--signal-yellow); border: 1px solid rgba(242, 204, 96, 0.35); }

/* ── Risk level ── */
.rlvl {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 0 5px;
  border-radius: 3px;
  vertical-align: middle;
  line-height: 1.6;
}
.rlvl-high { background: var(--signal-red-glow); color: var(--signal-red); border: 1px solid rgba(255, 142, 133, 0.35); }
.rlvl-mid { background: var(--signal-yellow-glow); color: var(--signal-yellow); border: 1px solid rgba(242, 204, 96, 0.35); }
.rlvl-low { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }

/* ── Quality & Architecture ── */
.daily-tab-body :deep(.qa-summary) {
  border-left: 3px solid var(--daily-accent);
  margin: 8px 0 16px;
  padding: 10px 14px;
  background: var(--daily-accent-light);
  border-radius: 0 6px 6px 0;
  font-size: 13px;
  color: var(--daily-text);
  line-height: 1.6;
}
.daily-tab-body :deep(h3) {
  font-size: 14px;
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--daily-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.daily-tab-body :deep(h3 + ul) {
  margin-top: 0;
}
.daily-tab-body :deep(.qa-summary + h3) {
  margin-top: 0;
}

/* ── Comparison table ── */
.daily-sglang-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.daily-sglang-table :deep(th) {
  background: var(--bg-elev-2, #f1f5f9);
  color: var(--daily-text);
  font-weight: 600;
  padding: 7px 10px;
  text-align: left;
  border-bottom: 2px solid var(--daily-border);
}
.daily-sglang-table :deep(td) {
  padding: 7px 10px;
  border-bottom: 1px solid var(--daily-border);
}
.daily-sglang-table :deep(tr:last-child td) { border-bottom: none; }

.cmp {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
}
.cmp-yes { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }
.cmp-no { background: var(--signal-red-glow); color: var(--signal-red); border: 1px solid rgba(255, 142, 133, 0.35); }

.cmp-prio {
  display: inline-block;
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 3px;
}
.cmp-prio-高 { background: var(--signal-red-glow); color: var(--signal-red); border: 1px solid rgba(255, 142, 133, 0.35); }
.cmp-prio-中 { background: var(--signal-yellow-glow); color: var(--signal-yellow); border: 1px solid rgba(242, 204, 96, 0.35); }
.cmp-prio-低 { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }

/* ── Trend direction ── */
.trend {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
}
.trend-flat { background: var(--bg-elev-3); color: var(--text-secondary); border: 1px solid var(--border); }
.trend-up { background: var(--signal-yellow-glow); color: var(--signal-yellow); border: 1px solid rgba(242, 204, 96, 0.35); }
.trend-down { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }

/* ── Academic relevance ── */
.rel {
  display: inline-block;
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 3px;
}
.rel-高 { background: var(--signal-red-glow); color: var(--signal-red); border: 1px solid rgba(255, 142, 133, 0.35); }
.rel-中 { background: var(--signal-yellow-glow); color: var(--signal-yellow); border: 1px solid rgba(242, 204, 96, 0.35); }
.rel-低 { background: var(--signal-green-glow); color: var(--signal-green); border: 1px solid rgba(142, 236, 151, 0.35); }

/* ── Slack channel tag ── */
.slack-channel {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg-elev-3);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  font-family: var(--font-mono, monospace);
}

/* ── Contribution tags ── */
.source-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg-elev-3);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  font-family: var(--font-mono, monospace);
}

.est {
  display: inline-block;
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--signal-yellow-glow);
  color: var(--signal-yellow);
  border: 1px solid rgba(242, 204, 96, 0.35);
}
</style>