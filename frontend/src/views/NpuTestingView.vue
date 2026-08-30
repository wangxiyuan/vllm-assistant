<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useNpuOpsStore, type NpuTestCase, type NpuBenchmarkRun } from '@/stores/npuOps'
import { useNpuStore } from '@/stores/npu'
import NpuDialog from '@/components/npu/NpuDialog.vue'
import { useNpuDialog } from '@/composables/useNpuDialog'

const ops = useNpuOpsStore()
const npu = useNpuStore()
const dialog = useNpuDialog()

const tab = ref<'cases' | 'bench'>('cases')

// 用例表单
const showCaseForm = ref(false)
const caseForm = ref<any>(emptyCase())
function emptyCase() {
  return {
    id: 0, name: '', description: '', kind: 'openai_chat' as 'openai_chat' | 'container_cmd',
    message: 'Hello, reply with one word.', expect_keyword: '', max_tokens: 64,
    command: 'python -c "print(1)"', image: '', target: 'service' as 'service' | 'machine',
    timeout_seconds: 600,
  }
}

async function saveCase() {
  if (!caseForm.value.name) { dialog.toastError('用例名必填'); return }
  const f = caseForm.value
  const payload = f.kind === 'openai_chat'
    ? { message: f.message, expect_keyword: f.expect_keyword, max_tokens: f.max_tokens }
    : { command: f.command, image: f.image }
  try {
    await ops.saveTestCase({
      id: f.id || undefined, name: f.name, description: f.description, kind: f.kind,
      payload, target: f.kind === 'openai_chat' ? 'service' : 'machine',
      timeout_seconds: f.timeout_seconds, enabled: true,
    })
    showCaseForm.value = false
    dialog.toastSuccess('用例已保存', f.name)
  } catch (e: any) { dialog.toastError('保存失败', e) }
}

function editCase(c: NpuTestCase) {
  caseForm.value = {
    ...emptyCase(), id: c.id, name: c.name, description: c.description || '', kind: c.kind,
    message: c.payload?.message || 'Hello', expect_keyword: c.payload?.expect_keyword || '',
    max_tokens: c.payload?.max_tokens || 64, command: c.payload?.command || '', image: c.payload?.image || '',
    target: c.target, timeout_seconds: c.timeout_seconds,
  }
  showCaseForm.value = true
}

async function runCase(c: NpuTestCase) {
  try {
    await ops.runTestCase(c.id)
    dialog.toastSuccess('用例已发起', c.name)
    await ops.fetchTestRuns()
  } catch (e: any) { dialog.toastError('运行失败', e) }
}

async function toggleCase(c: NpuTestCase) {
  await ops.saveTestCase({
    id: c.id, name: c.name, description: c.description || '', kind: c.kind,
    payload: c.payload, target: c.target, timeout_seconds: c.timeout_seconds, enabled: !c.enabled,
  })
}

async function deleteCase(c: NpuTestCase) {
  await ops.deleteTestCase(c.id)
  await ops.fetchTestRuns()
}

// benchmark 表单
const benchForm = ref<any>(emptyBench())
const benchRunning = ref(false)
function emptyBench() {
  return {
    service_id: null as number | null, dataset_name: 'random', dataset_path: '',
    num_prompts: 32, request_rate: null as number | null, max_concurrency: null as number | null,
    endpoint: '/v1/completions',
  }
}

async function startBench() {
  if (!benchForm.value.service_id) { dialog.toastError('请先选择服务实例'); return }
  benchRunning.value = true
  try {
    const r = await ops.startBenchmark({
      service_id: benchForm.value.service_id,
      dataset_name: benchForm.value.dataset_name,
      dataset_path: benchForm.value.dataset_path,
      num_prompts: benchForm.value.num_prompts,
      request_rate: benchForm.value.request_rate || undefined,
      max_concurrency: benchForm.value.max_concurrency || undefined,
      endpoint: benchForm.value.endpoint,
    })
    dialog.toastSuccess('压测已发起', `#${r.benchmark_id} · 结果将自动解析落库`)
    // 轮询结果（前端提示进行中，结果列表自动刷新可见）
    const poll = setInterval(async () => {
      const run = await ops.pollBenchmark(r.benchmark_id)
      if (run.status !== 'running') { clearInterval(poll); benchRunning.value = false; await ops.fetchBenchmarks() }
    }, 8000)
    await ops.fetchBenchmarks()
  } catch (e: any) { dialog.toastError('发起压测失败', e); benchRunning.value = false }
}

function fmtVal(v: number | null, unit = '') { return v === null || v === undefined ? '—' : `${v}${unit}` }
function fmtTime(ts: string) { return ts ? new Date(ts).toLocaleString() : '—' }
function fmtDur(ms: number | null) { return ms === null ? '—' : ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms` }

onMounted(async () => {
  await Promise.all([ops.fetchTestCases(), ops.fetchTestRuns(), ops.fetchBenchmarks(),
                     ops.fetchServices(), npu.fetchMachines()])
  setInterval(async () => {
    if (ops.testRuns.some(r => r.status === 'running')) await ops.fetchTestRuns()
  }, 8000)
})
</script>

<template>
  <div class="view-container">
    <div class="page-head">
      <h2>测试与压测</h2>
      <div class="head-actions">
        <button class="btn-ghost" :class="{ active: tab === 'cases' }" @click="tab = 'cases'">用例测试</button>
        <button class="btn-ghost" :class="{ active: tab === 'bench' }" @click="tab = 'bench'">Benchmark</button>
      </div>
    </div>

    <!-- 用例测试 -->
    <template v-if="tab === 'cases'">
      <div class="page-head" style="margin-bottom: var(--space-2);">
        <h4 style="margin: 0;">测试用例</h4>
        <button class="btn-primary" @click="showCaseForm = true">+ 新建用例</button>
      </div>
      <div class="job-list">
        <div v-for="c in ops.testCases" :key="c.id" class="job-row-item">
          <div class="job-item-top">
            <b>{{ c.name }}</b>
            <span class="job-badge">{{ c.kind === 'openai_chat' ? '接口探活' : '容器命令' }}</span>
            <span class="muted">{{ c.description || (c.kind === 'openai_chat' ? c.payload?.message : c.payload?.command)?.slice(0, 60) }}</span>
            <span style="flex: 1"></span>
            <button class="btn-mini" @click="runCase(c)">运行</button>
            <button class="btn-mini" @click="editCase(c)">编辑</button>
            <button class="btn-mini" @click="toggleCase(c)">{{ c.enabled ? '禁用' : '启用' }}</button>
            <button class="btn-mini" @click="deleteCase(c)">删除</button>
          </div>
        </div>
        <div v-if="ops.testCases.length === 0" class="empty">暂无用例。openai_chat 类对运行中服务发请求断言；container_cmd 类在机器容器里跑命令。</div>
      </div>

      <h4 style="margin: var(--space-4) 0 var(--space-2);">运行历史</h4>
      <div class="job-list">
        <div v-for="r in ops.testRuns" :key="r.id" class="job-row-item">
          <div class="job-item-top">
            <b>#{{ r.id }}</b>
            <span class="job-badge">{{ ops.testCases.find(c => c.id === r.case_id)?.name || `case ${r.case_id}` }}</span>
            <span :class="r.status === 'passed' ? 'job-st-completed' : r.status === 'running' ? 'job-st-running' : 'job-st-failed'">{{ r.status }}</span>
            <span class="muted">{{ fmtDur(r.duration_ms) }} · {{ fmtTime(r.created_at) }}</span>
          </div>
          <div v-if="r.output_summary" class="job-meta" style="white-space: pre-wrap;">{{ r.output_summary.slice(0, 400) }}</div>
        </div>
        <div v-if="ops.testRuns.length === 0" class="empty">暂无运行记录</div>
      </div>
    </template>

    <!-- Benchmark -->
    <template v-if="tab === 'bench'">
      <div class="job-form">
        <div class="job-row">
          <label>服务实例
            <select v-model.number="benchForm.service_id">
              <option :value="null" disabled>选择运行中的服务</option>
              <option v-for="s in ops.runningServices" :key="s.id" :value="s.id">
                {{ s.name }}（{{ s.model_name || s.name }}）
              </option>
            </select>
          </label>
          <label>数据集
            <select v-model="benchForm.dataset_name">
              <option value="random">random（合成，无需文件）</option>
              <option value="sharegpt">sharegpt（需机器上数据集）</option>
            </select>
          </label>
          <label v-if="benchForm.dataset_name === 'sharegpt'">数据集路径（机器上）<input v-model="benchForm.dataset_path" placeholder="/data/ShareGPT_V3.json" /></label>
          <label>请求数<input v-model.number="benchForm.num_prompts" type="number" /></label>
          <label>请求速率（req/s，空 = 全并发）<input v-model.number="benchForm.request_rate" type="number" step="0.5" /></label>
          <label>最大并发<input v-model.number="benchForm.max_concurrency" type="number" /></label>
          <label>endpoint
            <select v-model="benchForm.endpoint">
              <option>/v1/completions</option>
              <option>/v1/chat/completions</option>
            </select>
          </label>
        </div>
        <div class="form-actions" style="justify-content: flex-start;">
          <button class="btn-primary" :disabled="benchRunning" @click="startBench">
            {{ benchRunning ? '压测进行中…' : '发起压测' }}
          </button>
          <span class="muted">结果自动解析落库，可历史对比</span>
        </div>
      </div>

      <h4 style="margin: var(--space-4) 0 var(--space-2);">压测结果（吞吐 / TTFT / TPOT 毫秒）</h4>
      <div style="overflow-x: auto;">
        <table class="bench-table">
          <thead>
            <tr>
              <th>#</th><th>模型</th><th>数据集</th><th>请求数</th><th>并发</th><th>状态</th>
              <th>吞吐 req/s</th><th>输出 tok/s</th><th>TTFT p50</th><th>TTFT p99</th>
              <th>TPOT p50</th><th>TPOT p99</th><th>成功率</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in ops.benchmarks" :key="b.id">
              <td>{{ b.id }}</td>
              <td>{{ b.model || '—' }}</td>
              <td>{{ b.dataset_name }}</td>
              <td>{{ b.num_prompts }}</td>
              <td>{{ b.max_concurrency ?? (b.request_rate ? `${b.request_rate}/s` : 'inf') }}</td>
              <td :class="b.status === 'completed' ? 'job-st-completed' : b.status === 'running' ? 'job-st-running' : 'job-st-failed'">{{ b.status }}</td>
              <td>{{ fmtVal(b.total_throughput) }}</td>
              <td>{{ fmtVal(b.output_throughput) }}</td>
              <td>{{ fmtVal(b.ttft_p50) }}</td>
              <td>{{ fmtVal(b.ttft_p99) }}</td>
              <td>{{ fmtVal(b.tpot_p50) }}</td>
              <td>{{ fmtVal(b.tpot_p99) }}</td>
              <td>{{ fmtVal(b.success_rate, '%') }}</td>
              <td>{{ fmtTime(b.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="ops.benchmarks.length === 0" class="empty">暂无压测记录</div>
      </div>
    </template>

    <!-- 用例表单 -->
    <div v-if="showCaseForm" class="modal-mask" @click.self="showCaseForm = false">
      <div class="modal">
        <h3>{{ caseForm.id ? '编辑用例' : '新建用例' }}</h3>
        <div class="job-form">
          <div class="job-row">
            <label>用例名 *<input v-model="caseForm.name" /></label>
            <label>类型
              <select v-model="caseForm.kind">
                <option value="openai_chat">接口探活（openai_chat）</option>
                <option value="container_cmd">容器命令（container_cmd）</option>
              </select>
            </label>
          </div>
          <label style="font-size: var(--text-xs); color: var(--text-tertiary);">描述<input v-model="caseForm.description" /></label>
          <template v-if="caseForm.kind === 'openai_chat'">
            <div class="job-row">
              <label>测试消息<input v-model="caseForm.message" /></label>
              <label>期望输出包含（可选）<input v-model="caseForm.expect_keyword" /></label>
              <label>max_tokens<input v-model.number="caseForm.max_tokens" type="number" /></label>
            </div>
          </template>
          <template v-else>
            <div class="job-row">
              <label>容器命令<textarea v-model="caseForm.command" rows="3"></textarea></label>
              <label>镜像（空 = 机型默认）<input v-model="caseForm.image" /></label>
            </div>
          </template>
          <div class="job-row">
            <label>超时（秒）<input v-model.number="caseForm.timeout_seconds" type="number" /></label>
          </div>
          <div class="form-actions">
            <button class="btn-ghost" @click="showCaseForm = false">取消</button>
            <button class="btn-primary" @click="saveCase">保存</button>
          </div>
        </div>
      </div>
    </div>

    <NpuDialog />
  </div>
</template>

<style scoped src="../components/npu/npu-shared.css"></style>

<style scoped>
.head-actions .btn-ghost.active { border-color: var(--accent); color: var(--accent); }
.bench-table { width: 100%; border-collapse: collapse; font-size: var(--text-xs); }
.bench-table th, .bench-table td { padding: var(--space-2); border-bottom: 1px solid var(--border-faint); text-align: left; white-space: nowrap; }
.bench-table th { color: var(--text-tertiary); font-weight: 600; }
</style>
