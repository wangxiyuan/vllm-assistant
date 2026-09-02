<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import ChatDrawer from '@/components/ai/ChatDrawer.vue'
import { useRoute } from 'vue-router'
import { useIntelStore } from '@/stores/intel'
import { useReposStore } from '@/stores/repos'
import { renderMarkdown } from '@/composables/useMarkdown'
import { api } from '@/api/client'
import DailyReportRenderer from '@/components/common/DailyReportRenderer.vue'
import CommentSection from '@/components/common/CommentSection.vue'
import Icon from '@/components/common/Icon.vue'

const route = useRoute()
const intelStore = useIntelStore()
const reposStore = useReposStore()

const activeTab = ref<'daily' | 'manual'>('daily')
const hasSlackCred = ref(false)

const filteredReports = computed(() => {
  return intelStore.reports.filter(r => (r.category || 'manual') === activeTab.value)
})

const intelSourceOptions = computed(() => {
  const repoOptions = reposStore.repos.map(r => ({
    value: r.repo,
    label: r.repo + ' 社区',
  }))
  const options = [
    ...repoOptions,
    { value: 'academic', label: '学术动态' },
    { value: 'news', label: '新闻动态' },
  ]
  if (hasSlackCred.value) {
    options.push({ value: 'slack', label: 'Slack 社群讨论' })
  }
  return options
})

onMounted(async () => {
  await intelStore.loadReports()
  // 检查 Slack 是否有凭证
  try {
    const slackStatus: any = await api('/api/slack/status')
    hasSlackCred.value = slackStatus.cred_exists === true
  } catch (_) {}
  // 如果 URL 中有 report_id 参数，自动打开报告
  const reportId = route.query.report_id
  if (reportId) {
    const id = parseInt(reportId as string, 10)
    if (!isNaN(id)) {
      const found = intelStore.reports.find(r => r.id === id)
      if (found) {
        intelStore.viewReport(found)
        activeTab.value = (found.category || 'manual') as 'daily' | 'manual'
      } else {
        intelStore.viewReport({ id } as any)
      }
    }
  }
})

function isDailyReport(report: any): boolean {
  return (report.category || 'manual') === 'daily'
}

function reportProgressOf(report: any): any {
  return intelStore.reportProgress[report.id]
}

function isGeneratingNow(report: any): boolean {
  return report?.status === 'generating'
}

function reportStageLabel(report: any): string {
  const p = reportProgressOf(report)
  if (!p) return ''
  if (p.stage_label) return p.stage_label
  const idx = p.stage_index
  if (Array.isArray(p.stages) && idx != null && p.stages[idx]) return p.stages[idx]
  return p.stage || ''
}

function progressPercent(report: any): number {
  const p = reportProgressOf(report)
  if (!p || typeof p.progress !== 'number') return 0
  return Math.min(Math.round(p.progress * 100), 99)
}

const showTraceModal = ref(false)
const traceLoaded = ref(false)

function traceOf(report: any): any {
  return report && intelStore.reportTrace[report.id]
}

function stageLabel(key: string): string {
  const map: Record<string, string> = { search: '搜索情报', detail: '深入分析', report: '撰写报告', fallback: '单次回退' }
  return map[key] || key
}

function fmtDuration(ms: number): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function fmtArgs(args: string): string {
  if (!args) return '(无)'
  try {
    return JSON.stringify(JSON.parse(args))
  } catch {
    return args
  }
}

function failedCount(toolCalls: any[]): number {
  return (toolCalls || []).filter(tc => tc.status === 'error').length
}

async function openTraceModal(reportId: number) {
  showTraceModal.value = true
  traceLoaded.value = false
  await intelStore.fetchReportTrace(reportId)
  traceLoaded.value = true
}

function closeTraceModal() {
  showTraceModal.value = false
}

// ── AI 助手抽屉（AI 帮我建）──
const aiChatOpen = ref(false)
const aiChatIntent = ref('')
function openAIChat(intent: string) {
  aiChatIntent.value = intent
  aiChatOpen.value = true
}
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">洞察面板</h2>
      <div class="view-header-row">
        <div class="tab-bar">
          <button :class="['tab', { active: activeTab === 'daily' }]" @click="activeTab = 'daily'">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            每日报告
          </button>
          <button :class="['tab', { active: activeTab === 'manual' }]" @click="activeTab = 'manual'">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            自定义洞察
          </button>
        </div>
        <div class="view-actions">
          <button class="btn btn-sm" @click="openAIChat('report')">✨ AI 帮我建</button>
          <button v-if="activeTab === 'daily'" class="btn btn-primary btn-sm" :disabled="intelStore.dailyGenLoading" @click="intelStore.triggerDailyReport()">
            <svg v-if="intelStore.dailyGenLoading" class="spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
            {{ intelStore.dailyGenLoading ? '生成中…' : '生成每日报告' }}
          </button>
          <button v-if="activeTab === 'manual'" class="btn btn-primary btn-sm" @click="intelStore.openModal()">
            + 生成自定义报告
          </button>
        </div>
      </div>
    </div>

    <!-- Tab content -->
    <div class="report-list">
      <div v-for="report in filteredReports" :key="report.id" class="report-card" @click="intelStore.viewReport(report)">
        <div class="report-header">
          <h3 class="report-title">{{ report.title || '无标题' }}</h3>
          <div class="report-header-badges">
            <span v-if="isDailyReport(report) && activeTab === 'manual'" class="badge badge-daily">每日</span>
            <span class="badge" :class="'status-' + report.status">
              {{ report.status === 'completed' ? '已完成' : report.status === 'generating' ? '生成中' : '失败' }}
            </span>
          </div>
        </div>
        <div class="report-meta">
          <span v-if="isDailyReport(report)" class="meta-item"><Icon name="calendar" :size="11" /> {{ new Date(report.created_at).toLocaleDateString('zh-CN') }}</span>
          <span v-for="s in report.sources" :key="s" class="badge badge-source" :class="intelStore.intelSourceClass(s)" :style="intelStore.intelSourceStyle(s)">{{ intelStore.intelSourceLabel(s) }}</span>
          <span>{{ report.word_count }} 字</span>
          <span>{{ new Date(report.created_at).toLocaleDateString('zh-CN') }}</span>
        </div>
        <!-- 生成进度 -->
        <div v-if="report.status === 'generating' && reportProgressOf(report)" class="report-progress">
          <div class="report-progress-row">
            <span class="report-progress-stage">
              <span class="spin" style="display:inline-block;width:10px;height:10px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;vertical-align:-1px;margin-right:6px;"></span>
              {{ reportProgressOf(report).stage_label || '' }}{{ reportProgressOf(report).stages?.[reportProgressOf(report).stage_index] || '' }}
            </span>
            <span class="report-progress-pct">{{ progressPercent(report) }}%</span>
          </div>
          <div class="report-progress-bar"><div class="report-progress-fill" :style="{ width: progressPercent(report) + '%' }"></div></div>
          <div v-if="reportProgressOf(report).tools && reportProgressOf(report).tools.length" class="report-progress-tools">
            <template v-for="tn in reportProgressOf(report).tools" :key="tn">
              <span class="report-progress-tool">{{ tn }}</span>
            </template>
          </div>
        </div>
        <div class="card-action-row report-actions">
          <button class="card-action-btn is-primary" @click.stop="intelStore.viewReport(report)" title="查看报告">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            查看
          </button>
          <button class="card-action-btn" @click.stop="intelStore.regenerateReport(report)" title="重新生成">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            重新生成
          </button>
          <button class="card-action-btn is-danger" @click.stop="intelStore.deleteReport(report)" title="删除报告">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            删除
          </button>
        </div>
      </div>
      <div v-if="filteredReports.length === 0 && !intelStore.loading" class="empty-state">
        <p v-if="activeTab === 'daily'">暂无每日报告</p>
        <p v-else>暂无自定义报告</p>
        <button v-if="activeTab === 'daily'" class="btn btn-primary btn-sm" @click="intelStore.triggerDailyReport()">生成每日报告</button>
        <button v-else class="btn btn-primary btn-sm" @click="intelStore.openModal()">生成第一份自定义报告</button>
      </div>
    </div>

    <!-- Generate Report Modal -->
    <Teleport to="body">
      <div v-if="intelStore.showModal" class="modal-backdrop" @click="intelStore.showModal = false">
        <div class="modal modal-lg" @click.stop>
          <div class="modal-header">
            <h3>生成洞察报告</h3>
            <button class="modal-close" @click="intelStore.showModal = false" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">报告主题 <span style="color: var(--signal-red)">*</span></label>
              <input type="text" class="input" v-model="intelStore.intelForm.title"
                     placeholder="想了解什么，如：最近两周 MoE 通信优化的进展" @keyup.enter="intelStore.generateReport()" />
            </div>
            <div class="form-group">
              <label class="form-label">数据来源</label>
              <div class="checkbox-group">
                <label v-for="opt in intelSourceOptions" :key="opt.value" class="checkbox-label">
                  <input type="checkbox" :checked="intelStore.isSourceSelected(opt.value)"
                         @change="intelStore.toggleSource(opt.value)" />
                  {{ opt.label }}
                </label>
              </div>
            </div>
            <div class="form-group">
              <label class="form-label">额外提示</label>
              <textarea class="textarea" v-model="intelStore.intelForm.extra_prompt" rows="3"
                        placeholder="可选：指定关注方向…"></textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="intelStore.showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="intelStore.genLoading"
                    @click="intelStore.generateReport()">
              {{ intelStore.genLoading ? '生成中…' : '生成报告' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- View Report Modal -->
    <Teleport to="body">
      <div v-if="intelStore.selectedReport" class="modal-backdrop" @click="intelStore.closeReport()">
        <div class="modal modal-xl" @click.stop>
          <div class="modal-header">
            <h3>{{ intelStore.selectedReport.title || '报告详情' }}</h3>
            <div class="drawer-actions" style="margin-left:auto;">
              <button class="btn btn-sm" @click="openTraceModal(intelStore.selectedReport.id)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                生成过程
              </button>
              <button class="btn btn-sm" @click="intelStore.copyReportMarkdown()">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                复制 Markdown
              </button>
              <button class="modal-close" @click="intelStore.closeReport()" title="关闭">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>
          <div v-if="intelStore.reportModalLoading" class="modal-body detail-loading">
            加载中…
          </div>
          <div v-else-if="intelStore.reportDetails" class="modal-body report-content">
            <!-- 生成中进度（详情弹窗内） -->
            <div v-if="isGeneratingNow(intelStore.selectedReport) && reportProgressOf(intelStore.selectedReport)" class="report-detail-progress">
              <div class="report-progress-row">
                <span class="report-progress-stage">
                  <span class="spin" style="display:inline-block;width:10px;height:10px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;vertical-align:-1px;margin-right:6px;"></span>
                  {{ reportStageLabel(intelStore.selectedReport) }}
                </span>
                <span class="report-progress-pct">{{ progressPercent(intelStore.selectedReport) }}%</span>
              </div>
              <div class="report-progress-bar"><div class="report-progress-fill" :style="{ width: progressPercent(intelStore.selectedReport) + '%' }"></div></div>
              <div v-if="reportProgressOf(intelStore.selectedReport).tools && reportProgressOf(intelStore.selectedReport).tools.length" class="report-progress-tools">
                <template v-for="tn in reportProgressOf(intelStore.selectedReport).tools" :key="tn">
                  <span class="report-progress-tool">{{ tn }}</span>
                </template>
              </div>
            </div>
            <DailyReportRenderer
              v-if="isDailyReport(intelStore.selectedReport)"
              :content="intelStore.reportDetails.content || ''"
            />
            <div v-else class="pr-body" v-html="renderMarkdown(intelStore.reportDetails.content || '(无内容)')"></div>
            <CommentSection target-type="report" :target-id="intelStore.selectedReport.id" />
          </div>
          <div v-else class="modal-body report-content">
            <div class="pr-body" v-html="renderMarkdown('(无内容)')"></div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Trace Modal -->
    <Teleport to="body">
      <div v-if="showTraceModal" class="modal-backdrop" @click="closeTraceModal">
        <div class="modal modal-xl" @click.stop>
          <div class="modal-header">
            <h3>生成过程追溯</h3>
            <button class="modal-close" @click="closeTraceModal" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="modal-body trace-body">
            <div v-if="!traceLoaded" class="detail-loading">加载中…</div>
            <template v-else-if="traceOf(intelStore.selectedReport)">
              <div v-if="!traceOf(intelStore.selectedReport).traces || !traceOf(intelStore.selectedReport).traces.length" class="empty-state">
                <p>本次生成无过程记录（旧报告可能不含痕迹）。</p>
              </div>
              <div v-else>
                <div class="trace-summary">
                  <span class="badge">共 {{ traceOf(intelStore.selectedReport).traces.length }} 阶段</span>
                  <span class="badge">Tokens: {{ traceOf(intelStore.selectedReport).total_usage?.total_tokens ?? 0 }}</span>
                  <span class="badge">耗时 {{ fmtDuration(traceOf(intelStore.selectedReport).total_duration_ms) }}</span>
                </div>
                <div v-for="tr in traceOf(intelStore.selectedReport).traces" :key="tr.id" class="trace-stage">
                  <div class="trace-stage-head">
                    <span class="badge badge-info">{{ stageLabel(tr.stage) }}</span>
                    <span v-if="tr.fallback" class="badge" style="background:var(--signal-yellow);color:#000;">回退</span>
                    <span class="trace-meta">
                      <span v-if="tr.turns">工具 {{ tr.turns }} 次</span>
                      <span v-if="tr.usage?.total_tokens">Tokens: {{ tr.usage.total_tokens }}</span>
                      <span v-if="tr.usage?.input_tokens || tr.usage?.output_tokens">(in {{ tr.usage.input_tokens }} / out {{ tr.usage.output_tokens }})</span>
                      <span>耗时 {{ fmtDuration(tr.duration_ms) }}</span>
                      <span v-if="tr.model" class="trace-model">{{ tr.model }}</span>
                      <span v-if="tr.temperature != null">temp {{ tr.temperature }}</span>
                      <span v-if="tr.max_turns">max_turns {{ tr.max_turns }}</span>
                      <span v-if="fmtTime(tr.created_at)" class="trace-time">{{ fmtTime(tr.created_at) }}</span>
                    </span>
                  </div>

                  <details class="trace-section" v-if="tr.system_prompt">
                    <summary>系统提示词</summary>
                    <pre class="trace-pre">{{ tr.system_prompt }}</pre>
                  </details>
                  <details class="trace-section" v-if="tr.user_input">
                    <summary>阶段输入</summary>
                    <pre class="trace-pre">{{ tr.user_input }}</pre>
                  </details>

                  <div v-if="tr.tool_calls && tr.tool_calls.length" class="trace-section">
                    <div class="trace-subhead">工具调用（{{ tr.tool_calls.length }} 次<template v-if="failedCount(tr.tool_calls)">，失败 {{ failedCount(tr.tool_calls) }} 次</template>）</div>
                    <div v-for="(tc, i) in tr.tool_calls" :key="i" class="trace-tool">
                      <div class="trace-tool-name" :class="{ 'is-error': tc.status === 'error' }">{{ tc.name }}<template v-if="tc.status === 'error'"> ⚠</template></div>
                      <details class="trace-tool-detail">
                        <summary>参数</summary>
                        <pre class="trace-pre">{{ fmtArgs(tc.arguments) }}</pre>
                      </details>
                      <details class="trace-tool-detail" v-if="tc.output">
                        <summary>结果</summary>
                        <pre class="trace-pre">{{ tc.output }}</pre>
                      </details>
                    </div>
                  </div>

                  <details class="trace-section" v-if="tr.final_output">
                    <summary>阶段输出</summary>
                    <pre class="trace-pre">{{ tr.final_output }}</pre>
                  </details>
                </div>
              </div>
            </template>
            <div v-else class="empty-state"><p>加载失败或无记录。</p></div>
          </div>
        </div>
      </div>
    </Teleport>
    <ChatDrawer :open="aiChatOpen" :intent="aiChatIntent" @close="aiChatOpen = false" />
  </div>
</template>