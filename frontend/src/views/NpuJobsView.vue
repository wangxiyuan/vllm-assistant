<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useNpuStore, type NpuJob, type NpuContainerTemplate } from '@/stores/npu'
import LogViewer from '@/components/npu/LogViewer.vue'
import NpuCardPicker from '@/components/npu/NpuCardPicker.vue'
import NpuDialog from '@/components/npu/NpuDialog.vue'
import { useNpuDialog } from '@/composables/useNpuDialog'

const npu = useNpuStore()
const dialog = useNpuDialog()

const showForm = ref(false)
const submitting = ref(false)
const preview = ref('')
const activeJob = ref<NpuJob | null>(null)
const filterStatus = ref('')
const filterMachine = ref<number | ''>('')
const copiedTag = ref('')

async function copy(text: string, tag: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedTag.value = tag
    setTimeout(() => (copiedTag.value = ''), 1500)
  } catch {}
}

const draft = ref<any>(emptyDraft())
const preset = ref('bash')
const envText = ref('')

function emptyDraft() {
  return {
    machine_id: null as number | null, mode: 'persistent' as 'persistent' | 'oneshot',
    name: '', image: '', device_ids: null as number[] | null, mountsText: '',
    network: 'host' as 'host' | 'bridge', portsText: '', command: '',
    shm_size: '', extraDevicesText: '', timeout: null as number | null,
  }
}

const presets: Record<string, { label: string; apply: (d: any) => void }> = {
  bash: { label: 'bash 常驻（exec 进去开发）', apply: (d) => { d.mode = 'persistent'; d.command = '' } },
  serve: { label: 'vllm serve', apply: (d) => { d.mode = 'persistent'; d.command = 'vllm serve /models/your-model --host 0.0.0.0 --port 9001' } },
  bench: { label: '压测客户端', apply: (d) => { d.mode = 'oneshot'; d.command = 'vllm bench serve --backend vllm --model <name> --endpoint /v1/completions --dataset-name random --num-prompts 32' } },
  empty: { label: '空白', apply: (d) => { d.command = '' } },
}

function applyPreset() {
  const p = presets[preset.value]
  if (p) p.apply(draft.value)
}

function parseLines(t: string): string[] {
  return t.split('\n').map(s => s.trim()).filter(Boolean)
}
function parseEnv(t: string): Record<string, string> {
  const env: Record<string, string> = {}
  parseLines(t).forEach(l => {
    const i = l.indexOf('=')
    if (i > 0) env[l.slice(0, i).trim()] = l.slice(i + 1).trim()
  })
  return env
}
function buildSpec() {
  return {
    machine_id: draft.value.machine_id,
    mode: draft.value.mode,
    name: draft.value.name,
    image: draft.value.image,
    device_ids: draft.value.device_ids,
    mounts: parseLines(draft.value.mountsText),
    env: parseEnv(envText.value),
    network: draft.value.network,
    ports: parseLines(draft.value.portsText),
    command: draft.value.command,
    shm_size: draft.value.shm_size,
    extra_devices: parseLines(draft.value.extraDevicesText),
    timeout: draft.value.timeout,
  }
}

async function doPreview() {
  try {
    const r = await npu.previewCommand(buildSpec())
    preview.value = r.docker_cmd
  } catch (e: any) { dialog.toastError('预览失败', e) }
}

async function submit() {
  if (!draft.value.machine_id) { dialog.toastError('请先选择机器'); return }
  submitting.value = true
  try {
    const job = await npu.createJob(buildSpec())
    showForm.value = false
    activeJob.value = job
    draft.value = emptyDraft(); envText.value = ''; preview.value = ''
  } catch (e: any) { dialog.toastError('提交失败', e) } finally { submitting.value = false }
}

async function applyTemplate(t: NpuContainerTemplate) {
  draft.value = {
    ...emptyDraft(),
    machine_id: draft.value.machine_id,
    mode: t.mode, image: t.image || '',
    device_ids: t.devices || null, mountsText: (t.mounts || []).join('\n'),
    network: (t.network as any) || 'host', portsText: (t.ports || []).join('\n'),
    command: t.command || '', shm_size: t.shm_size || '',
  }
  envText.value = Object.entries(t.env || {}).map(([k, v]) => `${k}=${v}`).join('\n')
  showForm.value = true
}

async function saveAsTemplate() {
  const name = await dialog.prompt('模板名称：', '存为模板')
  if (!name) return
  try {
    const spec = buildSpec()
    await npu.createTemplate({
      name, mode: spec.mode, machine_type: npu.machines.find(m => m.id === spec.machine_id)?.machine_type || '',
      image: spec.image, device_ids: spec.device_ids, mounts: spec.mounts, env: spec.env,
      network: spec.network, ports: spec.ports, command: spec.command, shm_size: spec.shm_size,
      notes: '',
    })
    dialog.toastSuccess('模板已保存', name)
  } catch (e: any) { dialog.toastError('保存失败', e) }
}

async function removeTemplate(id: number) {
  if (!(await dialog.confirm('删除该模板？', '删除确认'))) return
  await npu.deleteTemplate(id)
}

function statusClass(s: string) {
  return s === 'running' ? 'job-st-running' : s === 'completed' ? 'job-st-completed'
    : (s === 'failed' || s === 'cancelled') ? 'job-st-failed' : 'job-st-pending'
}

function fmtTime(ts: string | null) { return ts ? new Date(ts).toLocaleString() : '—' }

async function refreshJobs() {
  const f: Record<string, any> = {}
  if (filterStatus.value) f.status = filterStatus.value
  if (filterMachine.value) f.machine_id = filterMachine.value
  await npu.fetchJobs(f)
}

watch([filterStatus, filterMachine], refreshJobs)

onMounted(async () => {
  await Promise.all([npu.fetchMachines(), npu.fetchJobs(), npu.fetchTemplates()])
  // 常驻任务列表每 10s 自动刷新（运行状态变化）
  setInterval(() => { if (!activeJob.value) refreshJobs() }, 10000)
})
</script>

<template>
  <div class="view-container">
    <div class="page-head">
      <h2>任务中心</h2>
      <div class="head-actions">
        <select v-model="filterMachine" class="filter-sel">
          <option :value="''">全部机器</option>
          <option v-for="m in npu.machines" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>
        <select v-model="filterStatus" class="filter-sel">
          <option value="">全部状态</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="completed">completed</option>
          <option value="failed">failed</option>
          <option value="cancelled">cancelled</option>
        </select>
        <button class="btn-primary" @click="showForm = true">+ 提交任务</button>
      </div>
    </div>

    <div class="job-list">
      <div v-for="j in npu.jobs" :key="j.id" class="job-row-item">
        <div class="job-item-top">
          <b>#{{ j.id }}</b>
          <span class="job-badge">{{ j.type }}</span>
          <span class="job-badge">{{ j.mode === 'persistent' ? '常驻' : '一次性' }}</span>
          <span :class="statusClass(j.status)">{{ j.status }}</span>
          <span class="muted">{{ j.name || j.payload?.command?.slice(0, 40) }}</span>
          <span style="flex: 1"></span>
          <button v-if="j.mode === 'persistent' && j.status === 'running'" class="btn-mini"
                  @click="copy(`docker exec -it ${j.container_name} bash`, `exec${j.id}`)">
            {{ copiedTag === `exec${j.id}` ? '已复制' : '复制 exec 命令' }}
          </button>
          <button v-if="j.status === 'pending' || j.status === 'running'" class="btn-mini" @click="npu.stopJob(j.id)">停止</button>
          <button class="btn-mini" @click="activeJob = j">日志</button>
        </div>
        <div class="job-meta">
          <span>机器：{{ npu.machineName(j.machine_id) }}</span>
          <span>容器：{{ j.container_name || '—' }}</span>
          <span v-if="j.exit_code !== null">exit={{ j.exit_code }}</span>
          <span>{{ fmtTime(j.created_at) }}</span>
          <span v-if="j.source === 'agent'" class="job-badge">Agent</span>
        </div>
        <div v-if="j.error_message" class="job-err">{{ j.error_message }}</div>
      </div>
      <div v-if="npu.jobs.length === 0" class="empty">暂无任务</div>
    </div>

    <!-- 提交表单 -->
    <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
      <div class="modal">
        <h3>提交容器任务</h3>
        <div class="job-form">
          <div class="job-row">
            <label>机器
              <select v-model="draft.machine_id">
                <option :value="null" disabled>选择机器</option>
                <option v-for="m in npu.machines.filter(x => x.enabled)" :key="m.id" :value="m.id">
                  {{ m.name }}（{{ m.npu_count ?? '?' }} 卡）
                </option>
              </select>
            </label>
            <label>模式
              <select v-model="draft.mode">
                <option value="persistent">常驻（docker run -d，exec 进去开发）</option>
                <option value="oneshot">一次性（跑完退出）</option>
              </select>
            </label>
          </div>
          <div class="preset-row">
            快捷预设：
            <select v-model="preset" @change="applyPreset">
              <option v-for="(p, k) in presets" :key="k" :value="k">{{ p.label }}</option>
            </select>
            <button class="btn-mini" @click="applyPreset">应用</button>
          </div>
          <label style="font-size: var(--text-xs); color: var(--text-tertiary); display: flex; flex-direction: column; gap: 4px;">
            容器执行命令（自定义，一等公民）
            <textarea v-model="draft.command" rows="3" placeholder="容器内 shell 命令；常驻模式留空则 sleep infinity 常住"></textarea>
          </label>
          <div class="job-row">
            <label>镜像（留空 = 机型默认）
              <input v-model="draft.image" placeholder="quay.io/ascend/vllm-ascend:v0.23.0" />
            </label>
            <label>NPU 卡（已占用的卡不可选，不选 = 全部卡）
              <NpuCardPicker v-model="draft.device_ids" :machine-id="draft.machine_id" />
            </label>
          </div>
          <div class="job-row">
            <label>挂载（每行 host:container，container 省略 = 同路径）
              <textarea v-model="draft.mountsText" rows="2" placeholder="/data/models/Qwen3-32B:/models/Qwen3-32B"></textarea>
            </label>
            <label>环境变量（每行 K=V）
              <textarea v-model="envText" rows="2" placeholder="HF_TOKEN=xxx"></textarea>
            </label>
          </div>
          <div class="job-row">
            <label>网络
              <select v-model="draft.network">
                <option value="host">host（多卡/多机推荐）</option>
                <option value="bridge">bridge（端口映射）</option>
              </select>
            </label>
            <label v-if="draft.network === 'bridge'">端口映射（每行 host:container）<input v-model="draft.portsText" placeholder="9001:9001" /></label>
            <label>shm-size（留空 = 机型默认）<input v-model="draft.shm_size" placeholder="1g" /></label>
            <label v-if="draft.mode === 'oneshot'">超时（秒，默认 3600）<input v-model.number="draft.timeout" type="number" /></label>
          </div>
          <div class="job-row">
            <label>任务名（可选）<input v-model="draft.name" placeholder="如 跑单卡用例" /></label>
          </div>
          <div v-if="preview" class="docker-preview">{{ preview }}</div>
          <div class="form-actions">
            <button class="btn-ghost" @click="saveAsTemplate">存为模板</button>
            <button class="btn-ghost" @click="doPreview">预览命令</button>
            <button class="btn-primary" :disabled="submitting" @click="submit">{{ submitting ? '提交中…' : '提交任务' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 模板管理 -->
    <div v-if="npu.templates.length" class="drawer-section" style="border: none; padding: 0;">
      <h4 style="margin-bottom: var(--space-2);">任务模板</h4>
      <div class="preset-row" style="flex-wrap: wrap; gap: var(--space-2);">
        <span v-for="t in npu.templates" :key="t.id" class="template-chip">
          <button class="btn-mini" @click="applyTemplate(t)">{{ t.name }}（{{ t.mode === 'persistent' ? '常驻' : '一次性' }}）</button>
          <button class="btn-mini" @click="removeTemplate(t.id)">×</button>
        </span>
      </div>
    </div>

    <!-- 日志弹窗 -->
    <div v-if="activeJob" class="modal-mask" @click.self="activeJob = null">
      <div class="modal">
        <h3>任务 #{{ activeJob.id }} 日志 <span :class="statusClass(activeJob.status)">{{ activeJob.status }}</span></h3>
        <div class="docker-preview" style="margin-bottom: var(--space-2);">{{ activeJob.payload?.docker_cmd }}</div>
        <LogViewer :job-id="activeJob.id" />
      </div>
    </div>

    <NpuDialog />
  </div>
</template>

<style scoped src="../components/npu/npu-shared.css"></style>

<style scoped>
.filter-sel {
  padding: var(--space-1) var(--space-2); border-radius: var(--radius-md);
  border: 1px solid var(--border-faint); background: var(--surface-faint, transparent);
  color: inherit; font-size: var(--text-sm);
}
.template-chip { display: inline-flex; gap: 2px; align-items: center; }
</style>
