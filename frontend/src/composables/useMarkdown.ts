import { marked } from 'marked'
import { esc } from '@/utils/helpers'

marked.setOptions({
  gfm: true,
})

export function renderMarkdown(text: string): string {
  if (!text) return ''
  const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  return marked.parse(normalized, { async: false }) as string
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