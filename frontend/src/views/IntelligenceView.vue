<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useIntelStore } from '@/stores/intel'
import { useReposStore } from '@/stores/repos'
import { renderMarkdown } from '@/composables/useMarkdown'

const route = useRoute()
const intelStore = useIntelStore()
const reposStore = useReposStore()

const intelSourceOptions = computed(() => {
  const repoOptions = reposStore.repos.map(r => ({
    value: r.repo,
    label: r.repo + ' 社区',
  }))
  return [
    ...repoOptions,
    { value: 'academic', label: '学术动态' },
    { value: 'news', label: '新闻动态' },
  ]
})

onMounted(async () => {
  await intelStore.loadReports()
  intelStore.loadIntelTasks()
  // 如果 URL 中有 report_id 参数，自动打开报告
  const reportId = route.query.report_id
  if (reportId) {
    const id = parseInt(reportId as string, 10)
    if (!isNaN(id)) {
      const found = intelStore.reports.find(r => r.id === id)
      if (found) {
        intelStore.viewReport(found)
      } else {
        // 报告不在当前列表（可能是刚生成还未加载），直接通过 API 获取
        intelStore.viewReport({ id } as any)
      }
    }
  }
})
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">洞察面板</h2>
      <div class="view-actions">
        <button class="btn btn-primary btn-sm" :disabled="intelStore.dailyGenLoading" @click="intelStore.triggerDailyReport()">
          <svg v-if="intelStore.dailyGenLoading" class="spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
          {{ intelStore.dailyGenLoading ? '生成中…' : '生成每日报告' }}
        </button>
        <button class="btn btn-primary btn-sm" @click="intelStore.openModal()">
          + 生成自定义报告
        </button>
      </div>
    </div>

    <div class="report-list">
      <div v-for="report in intelStore.reports" :key="report.id" class="report-card" @click="intelStore.viewReport(report)">
        <div class="report-header">
          <h3 class="report-title">{{ report.title || '无标题' }}</h3>
          <div class="report-header-badges">
            <span v-if="report.category === 'daily'" class="badge badge-daily">每日</span>
            <span class="badge" :class="'status-' + report.status">
              {{ report.status === 'completed' ? '已完成' : report.status === 'generating' ? '生成中' : '失败' }}
            </span>
          </div>
        </div>
        <div class="report-meta">
          <span v-if="report.task_title" class="meta-item" @click.stop="intelStore.viewReport(report)" title="触发任务">触发任务: <strong>{{ report.task_title }}</strong></span>
          <span v-for="s in report.sources" :key="s" class="badge badge-source" :class="intelStore.intelSourceClass(s)">{{ intelStore.intelSourceLabel(s) }}</span>
          <span>{{ report.word_count }} 字</span>
          <span>{{ new Date(report.created_at).toLocaleDateString('zh-CN') }}</span>
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
      <div v-if="intelStore.reports.length === 0 && !intelStore.loading" class="empty-state">
        <p>暂无报告</p>
        <button class="btn btn-primary btn-sm" @click="intelStore.openModal()">生成第一份报告</button>
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
              <label class="form-label">关联任务</label>
              <select class="select" v-model.number="intelStore.intelForm.task_id">
                <option value="">选择任务…</option>
                <option v-for="t in intelStore.intelTasks" :key="t.id" :value="t.id">{{ t.title }}</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">报告标题（可选）</label>
              <input type="text" class="input" v-model="intelStore.intelForm.title" placeholder="自动生成标题" />
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
          <div v-else class="modal-body report-content">
            <div class="pr-body" v-html="renderMarkdown(intelStore.reportDetails?.content || '(无内容)')"></div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>