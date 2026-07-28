/**
 * AI 相关 API 统一调用入口
 *
 * 集中管理所有 AI 功能的 API 调用路径和参数。
 * 当后端 API 路径变更时，只需修改此文件。
 */
import { api } from '@/api/client'

/** 生成 AI 摘要（PR/Issue） */
export function generateSummary(itemType: string, number: number, title: string, body: string) {
  return api('/api/ai-assistant/summarize', {
    method: 'POST',
    body: JSON.stringify({ item_type: itemType, number, title, body }),
  }, { timeout: 120000 })
}

/** 生成 AI Review（PR） */
export function generateReview(prNumber: number, includeDiff: boolean = true) {
  return api('/api/ai-assistant/generate-review', {
    method: 'POST',
    body: JSON.stringify({ pr_number: prNumber, include_diff: includeDiff }),
  }, { timeout: 150000 })
}

/** 翻译文本 */
export function translateText(itemType: string, number: number, text: string) {
  return api('/api/ai-assistant/translate', {
    method: 'POST',
    body: JSON.stringify({ item_type: itemType, number, text }),
  }, { timeout: 120000 })
}

/** 读取 AI 缓存 */
export function getAICache(itemType: string, number: number, action: string) {
  return api('/api/ai-assistant/get-cache', {
    method: 'POST',
    body: JSON.stringify({ item_type: itemType, number, action }),
  }, { timeout: 5000 })
}

/** 清除 AI 缓存 */
export function clearAICache(itemType: string, number: number, action: string) {
  return api('/api/ai-assistant/clear-cache', {
    method: 'POST',
    body: JSON.stringify({ item_type: itemType, number, action }),
  }, { timeout: 5000 })
}

/** 推荐标签 */
export function suggestLabels(issueTitle: string, issueBody: string) {
  return api('/api/ai-assistant/suggest-labels', {
    method: 'POST',
    body: JSON.stringify({ issue_title: issueTitle, issue_body: issueBody }),
  })
}

/** 分析影响范围 */
export function analyzeImpact(changedFiles: string[]) {
  return api('/api/ai-assistant/analyze-impact', {
    method: 'POST',
    body: JSON.stringify({ changed_files: changedFiles }),
  })
}

/** 生成洞察报告 */
export function generateIntelReport(payload: any) {
  return api('/api/ai-agent/reports/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, { timeout: 30000 })
}