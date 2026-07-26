import { esc } from '@/utils/helpers'

export function renderInlineMarkdown(text: string): string {
  if (!text) return ''

  let s = text
  const preserved: string[] = []

  s = s.replace(/<img\s+[^>]*src\s*=\s*"([^"]+)"[^>]*\/?>/gi, (match) => {
    const safe = match.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    const idx = preserved.length
    preserved.push(safe)
    return `\x00IMG${idx}\x00`
  })

  s = s.replace(/<a\s+[^>]*>.*?<\/a>/gi, (match) => {
    let safe = match.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    safe = safe.replace(/\bhref\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')/gi, 'href="#"')
    const idx = preserved.length
    preserved.push(safe)
    return `\x00HTML${idx}\x00`
  })

  s = esc(s)

  s = s.replace(/\x00IMG(\d+)\x00/g, (_, idx) => preserved[parseInt(idx)])
  s = s.replace(/\x00HTML(\d+)\x00/g, (_, idx) => preserved[parseInt(idx)])

  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>')
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')

  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
    if (/^(https?:|data:)/i.test(url)) {
      return `<img src="${url}" alt="${alt}" style="max-width:100%;border-radius:var(--radius);" />`
    }
    return match
  })

  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
    if (/^(https?:|mailto:)/i.test(url)) {
      return `<a href="${url}" target="_blank" rel="noopener">${text}</a>`
    }
    return text
  })

  s = s.replace(/(^|[^"\'>=])(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')

  s = s.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
  s = s.replace(/\bhref\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*'|javascript:[^\s>]+)/gi, 'href="#"')
  s = s.replace(/\bsrc\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*'|javascript:[^\s>]+)/gi, 'src="#"')

  return s
}

export function renderMarkdown(text: string): string {
  if (!text) return ''
  let normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const lines = normalized.split('\n')
  const out: string[] = []
  let inList: string | null = null
  let inCode = false
  let codeLines: string[] = []
  let inTable = false
  let tableLines: string[] = []
  let blockquoteLines: string[] = []
  let inDetails = false
  let detailsSummary = ''
  let detailsBody: string[] = []

  const flushList = () => {
    if (inList) { out.push(`</${inList}>`); inList = null }
  }
  const flushBlockquote = () => {
    if (blockquoteLines.length) {
      out.push(`<blockquote>${renderInlineMarkdown(blockquoteLines.join(' '))}</blockquote>`)
      blockquoteLines = []
    }
  }
  const flushTable = () => {
    if (tableLines.length >= 2) {
      const headers = parseTableRow(tableLines[0])
      const rows = tableLines.slice(2).map(l => parseTableRow(l))
      let h = '<table><thead><tr>'
      headers.forEach(c => h += `<th>${renderInlineMarkdown(c)}</th>`)
      h += '</tr></thead><tbody>'
      rows.forEach(r => {
        h += '<tr>'
        r.forEach(c => h += `<td>${renderInlineMarkdown(c)}</td>`)
        h += '</tr>'
      })
      h += '</tbody></table>'
      out.push(h)
    }
    tableLines = []
    inTable = false
  }
  const flushDetails = () => {
    if (inDetails) {
      const renderedBody = renderMarkdown(detailsBody.join('\n'))
      out.push(`<details><summary>${renderInlineMarkdown(esc(detailsSummary))}</summary>${renderedBody}</details>`)
      inDetails = false
      detailsSummary = ''
      detailsBody = []
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    const imgMatch = line.match(/^\s*<img\s+[^>]*src\s*=\s*"([^"]+)"[^>]*\/?>\s*$/i)
    if (imgMatch) {
      flushList(); flushBlockquote(); flushTable()
      const safeLine = line.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      const alt = safeLine.match(/alt\s*=\s*"([^"]+)"/i)
      const altText = alt ? alt[1] : ''
      out.push(`<img src="${esc(imgMatch[1])}" alt="${esc(altText)}" style="max-width:100%;border-radius:var(--radius);margin:var(--space-3) 0;" />`)
      continue
    }

    const detailsMatch = line.match(/^\s*<details>/i)
    const detailsCloseMatch = line.match(/^\s*<\/details>/i)
    if (detailsMatch) {
      flushList(); flushBlockquote(); flushTable()
      inDetails = true
      detailsSummary = ''
      detailsBody = []
      const summaryMatch = line.match(/<summary>([^<]*)<\/summary>/i)
      if (summaryMatch) detailsSummary = summaryMatch[1]
      continue
    }
    if (inDetails) {
      if (detailsCloseMatch) { flushDetails(); continue }
      const summaryMatch = line.match(/^\s*<summary>([^<]*)<\/summary>\s*$/i)
      if (summaryMatch) { detailsSummary = summaryMatch[1]; continue }
      detailsBody.push(line)
      continue
    }

    if (line.trim().startsWith('```')) {
      flushList(); flushBlockquote(); flushTable()
      if (!inCode) {
        inCode = true
        codeLines = []
      } else {
        out.push(`<pre><code>${esc(codeLines.join('\n'))}</code></pre>`)
        inCode = false
      }
      continue
    }
    if (inCode) { codeLines.push(line); continue }

    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      flushList(); flushBlockquote()
      if (!inTable) inTable = true
      tableLines.push(line.trim())
      continue
    } else if (inTable) { flushTable() }

    const hMatch = line.match(/^(#{1,6})\s+(.*)$/)
    if (hMatch) {
      flushList(); flushBlockquote()
      const level = hMatch[1].length
      out.push(`<h${level}>${renderInlineMarkdown(hMatch[2])}</h${level}>`)
      continue
    }

    if (line.startsWith('>')) {
      flushList()
      blockquoteLines.push(line.replace(/^>\s?/, ''))
      continue
    } else if (blockquoteLines.length) { flushBlockquote() }

    if (/^[-*_]{3,}$/.test(line.trim())) {
      flushList()
      out.push('<hr>')
      continue
    }

    const ulMatch = line.match(/^[\s]*[-*+]\s+(.*)$/)
    const olMatch = line.match(/^[\s]*\d+\.\s+(.*)$/)
    if (ulMatch || olMatch) {
      const tag = olMatch ? 'ol' : 'ul'
      const raw = (olMatch || ulMatch)![1]
      const taskMatch = raw.match(/^\[([ xX])\]\s+(.*)$/)
      if (taskMatch) {
        const checked = taskMatch[1].toLowerCase() === 'x'
        const text = renderInlineMarkdown(taskMatch[2])
        if (inList && inList !== tag) flushList()
        if (!inList) { out.push(`<${tag}>`); inList = tag }
        out.push(`<li><input type="checkbox" disabled${checked ? ' checked' : ''}> ${text}</li>`)
      } else {
        if (inList && inList !== tag) flushList()
        if (!inList) { out.push(`<${tag}>`); inList = tag }
        out.push(`<li>${renderInlineMarkdown(raw)}</li>`)
      }
      continue
    } else { flushList() }

    if (!line.trim()) continue
    out.push(`<p>${renderInlineMarkdown(line)}</p>`)
  }
  flushList(); flushBlockquote(); flushTable()
  if (inCode) out.push(`<pre><code>${esc(codeLines.join('\n'))}</code></pre>`)
  return out.join('\n')
}

function parseTableRow(line: string): string[] {
  return line.split('|').slice(1, -1).map(c => c.trim())
}

export function renderDiff(diffText: string): string {
  if (!diffText) return ''
  const lines = diffText.split('\n')
  const out: string[] = []
  let lineNum = 0
  for (const line of lines) {
    if (line.startsWith('@@')) {
      const m = line.match(/@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
      if (m) lineNum = parseInt(m[1], 10)
      out.push(`<div class="diff-hunk-header">${esc(line)}</div>`)
      continue
    }
    if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++')) {
      out.push(`<div class="diff-meta">${esc(line)}</div>`)
      continue
    }
    if (line.startsWith('+')) {
      out.push(`<div class="diff-line diff-add"><span class="diff-line-num">${lineNum}</span><span>${esc(line)}</span></div>`)
      lineNum++
    } else if (line.startsWith('-')) {
      out.push(`<div class="diff-line diff-del"><span class="diff-line-num">${lineNum}</span><span>${esc(line)}</span></div>`)
    } else if (line.startsWith('\\')) {
      out.push(`<div class="diff-line diff-no-newline"><span>${esc(line)}</span></div>`)
    } else {
      out.push(`<div class="diff-line diff-ctx"><span class="diff-line-num">${lineNum}</span><span>${esc(line)}</span></div>`)
      lineNum++
    }
  }
  return out.join('\n')
}

export function renderSummary(summaryData: any): string {
  if (!summaryData) return ''
  try {
    let data = summaryData
    if (typeof summaryData === 'string') {
      let s = summaryData.trim()
      if (s.startsWith('```')) s = s.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '')
      data = JSON.parse(s)
    }
    let html = ''
    if (data.core_problem) {
      html += `<p><strong>核心问题：</strong> ${esc(String(data.core_problem))}</p>`
    }
    if (Array.isArray(data.key_points) && data.key_points.length > 0) {
      html += `<h4>关键要点</h4><ul>`
      for (const p of data.key_points) {
        html += `<li>${esc(String(p))}</li>`
      }
      html += `</ul>`
    }
    if (data.impact) {
      html += `<p><strong>影响范围：</strong> ${esc(String(data.impact))}</p>`
    }
    if (data.risk && data.risk !== '暂无') {
      html += `<p><strong>潜在风险：</strong> <span class="severity-important">${esc(String(data.risk))}</span></p>`
    } else if (data.risk === '暂无') {
      html += `<p><strong>潜在风险：</strong> <span style="color: var(--text-tertiary);">暂无</span></p>`
    }
    return html || `<p>${esc(String(summaryData))}</p>`
  } catch {
    return `<p>${esc(String(summaryData))}</p>`
  }
}

export function renderReview(review: any): string {
  if (!review) return ''
  try {
    const hasStructuredData = Array.isArray(review.code_quality) || Array.isArray(review.tests)
    if (!hasStructuredData) {
      return renderAIJSON(review)
    }

    let html = ''
    if (review.summary) {
      html += `<p><strong>总体评价：</strong> ${esc(String(review.summary))}</p>`
    }

    const renderSection = (title: string, items: any, icon = '') => {
      try {
        if (typeof items === 'string' && items.trim()) {
          return `<h4>${icon} ${esc(title)}</h4><p>${esc(items)}</p>`
        }
        if (!Array.isArray(items) || items.length === 0) return ''
        let h = `<h4>${icon} ${esc(title)}</h4><ul>`
        for (const item of items) {
          if (typeof item === 'string') {
            h += `<li>${esc(item)}</li>`
          } else if (item && typeof item === 'object') {
            const severity = item.severity || item.level || ''
            const sevClass = severity ? ` class="severity-${String(severity).toLowerCase()}"` : ''
            const sevTag = severity ? `<span${sevClass}>[${esc(severityLabel(severity))}]</span> ` : ''
            const desc = item.description || item.comment || item.message || item.explanation || ''
            const itemTitle = item.title || item.name || item.concern || ''
            if (itemTitle) {
              h += `<li>${sevTag}<strong>${esc(String(itemTitle))}</strong>`
              if (desc) h += ` - ${esc(String(desc))}`
              h += `</li>`
            } else {
              h += `<li>${sevTag}${esc(String(desc || ''))}</li>`
            }
          }
        }
        h += `</ul>`
        return h
      } catch { return '' }
    }

    html += renderSection('代码质量', review.code_quality, '◆')
    html += renderSection('性能', review.performance, '⚡')
    html += renderSection('测试', review.tests, '✓')
    html += renderSection('文档', review.docs, '📄')

    if (review.raw_response) {
      html += `<details style="margin-top: 12px;"><summary style="cursor: pointer; font-size: 12px; color: var(--text-tertiary);">查看 AI 原始返回</summary><pre class="ai-raw" style="margin-top: 8px;">${esc(String(review.raw_response))}</pre></details>`
    }

    return html || '<p class="text-tertiary">未返回结构化反馈</p>'
  } catch (e: any) {
    return `<p style="color: var(--signal-red);">渲染失败：${esc(e.message)}</p>`
  }
}

function renderAIJSON(obj: any): string {
  if (!obj) return ''
  if (obj.error) {
    return `<p><strong class="severity-critical">错误：</strong> ${esc(obj.error)}</p>` +
      (obj.raw_response ? `<pre class="ai-raw">${esc(obj.raw_response)}</pre>` : '')
  }
  if (obj.raw_response && Object.keys(obj).length <= 2) {
    return `<pre class="ai-raw">${esc(obj.raw_response)}</pre>`
  }
  return ''
}

function severityLabel(sev: string): string {
  return { critical: '严重', important: '重要', minor: '次要', high: '高', medium: '中', low: '低' }[sev.toLowerCase()] || sev
}