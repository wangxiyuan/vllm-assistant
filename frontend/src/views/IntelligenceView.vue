<script setup lang="ts">
import { onMounted } from 'vue'
import { useIntelStore } from '@/stores/intel'

const intelStore = useIntelStore()

onMounted(() => {
  intelStore.loadReports()
  intelStore.loadIntelTasks()
})
</script>

<template>
  <div class="view-container">
    <div class="view-header">
      <h2 class="view-title">洞察面板</h2>
      <div class="view-actions">
        <button class="btn btn-primary btn-sm" @click="intelStore.showModal = true; intelStore.loadIntelTasks()">
          + 生成报告
        </button>
      </div>
    </div>

    <div class="report-list">
      <div v-for="report in intelStore.reports" :key="report.id" class="report-card" @click="intelStore.viewReport(report)">
        <div class="report-header">
          <h3 class="report-title">{{ report.title || '无标题' }}</h3>
          <span class="badge" :class="'status-' + report.status">
            {{ report.status === 'completed' ? '已完成' : report.status === 'generating' ? '生成中' : '失败' }}
          </span>
        </div>
        <div class="report-meta">
          <span>{{ report.word_count }} 字</span>
          <span>{{ new Date(report.created_at).toLocaleDateString('zh-CN') }}</span>
        </div>
        <div class="report-sources">
          <span v-for="s in report.sources" :key="s" class="source-tag">{{ intelStore.intelSourceLabel(s) }}</span>
        </div>
      </div>
      <div v-if="intelStore.reports.length === 0 && !intelStore.loading" class="empty-state">
        <p>暂无报告</p>
        <button class="btn btn-primary btn-sm" @click="intelStore.showModal = true">生成第一份报告</button>
      </div>
    </div>

    <!-- Generate Report Modal -->
    <Teleport to="body">
      <div v-if="intelStore.showModal" class="modal-backdrop" @click="intelStore.showModal = false">
        <div class="modal modal-lg" @click.stop>
          <h3 class="modal-title">生成洞察报告</h3>
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
              <label v-for="opt in [
                { value: 'vllm', label: 'vLLM 社区' },
                { value: 'vllm-ascend', label: 'vLLM-Ascend' },
                { value: 'sglang', label: 'sglang' },
                { value: 'academic', label: '学术动态' },
                { value: 'news', label: '新闻动态' },
              ]" :key="opt.value" class="checkbox-label">
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
          <div class="modal-actions">
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
            <h3 class="modal-title">{{ intelStore.selectedReport.title || '报告详情' }}</h3>
            <div class="modal-actions">
              <button class="btn btn-sm" @click="intelStore.copyReportMarkdown()">复制 Markdown</button>
              <button class="btn btn-sm btn-ghost" @click="intelStore.closeReport()">&times;</button>
            </div>
          </div>
          <div v-if="intelStore.reportModalLoading" class="modal-body" style="text-align:center;padding:var(--space-9);">
            加载中…
          </div>
          <div v-else class="modal-body report-content">
            <pre>{{ intelStore.reportDetails?.content || '(无内容)' }}</pre>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
