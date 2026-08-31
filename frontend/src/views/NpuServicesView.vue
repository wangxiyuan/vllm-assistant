<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useNpuOpsStore, type NpuService, type ProfileSession } from '@/stores/npuOps'
import { useNpuStore, type MachineModelDir, type MachineImage } from '@/stores/npu'
import Playground from '@/components/npu/Playground.vue'
import LogViewer from '@/components/npu/LogViewer.vue'
import NpuDialog from '@/components/npu/NpuDialog.vue'
import NpuCardPicker from '@/components/npu/NpuCardPicker.vue'
import NpuFilterSelect from '@/components/npu/NpuFilterSelect.vue'
import { useNpuDialog } from '@/composables/useNpuDialog'
import { useAuthStore } from '@/stores/auth'

const ops = useNpuOpsStore()
const npu = useNpuStore()
const dialog = useNpuDialog()
const authStore = useAuthStore()

const showDeploy = ref(false)
const deploying = ref(false)
const deployPreview = ref('')
const copied = ref('')
const showPg = ref(false)

const detail = ref<NpuService | null>(null)
const svcJobId = ref<number | null>(null)
const debugInfo = ref<any>(null)
const currentSession = ref<ProfileSession | null>(null)

// 部署表单
const form = ref<any>(emptyDeploy())
const machineModels = ref<MachineModelDir[]>([])
const machineImages = ref<MachineImage[]>([])

function emptyDeploy() {
  return {
    machine_id: null as number | null, name: '', model_dir: '', model_name: '',
    image: '', port: 8000, network: 'host' as 'host' | 'bridge',
    device_ids: null as number[] | null,
    // 并行策略
    tp: 1, dp: null as number | null, pp: null as number | null,
    pcp: null as number | null, dcp: null as number | null,
    enable_ep: false, distributed_backend: 'auto',
    // 内存与缓存
    max_model_len: null as number | null, gpu_memory_utilization: null as number | null,
    max_num_seqs: null as number | null, max_num_batched_tokens: null as number | null,
    swap_space: null as number | null, block_size: null as number | null, kv_cache_dtype: '',
    // 精度与加载
    dtype: 'auto', quantization: '', load_format: 'auto', trust_remote_code: true,
    // 性能
    enforce_eager: false, seed: null as number | null,
    // JSON 配置（字符串形式，提交时 parse）
    speculative_config: '', compilation_config: '', additional_config: '',
    // 额外参数
    serve_args: '',
    // 调试与 Profiling
    debug_mode: false, debugpy_port: 5678, wait_for_client: false,
    profiling_enabled: false, profiler_with_stack: false,
  }
}

function parseJsonField(text: string): Record<string, any> | null | 'INVALID' {
  const t = text.trim()
  if (!t) return null
  try { return JSON.parse(t) } catch { return 'INVALID' }
}

async function onMachineChange() {
  machineModels.value = []
  machineImages.value = []
  const mid = form.value.machine_id
  if (!mid) return
  const [m, i] = await Promise.allSettled([npu.fetchMachineModels(mid), npu.fetchMachineImages(mid)])
  if (m.status === 'fulfilled') machineModels.value = m.value
  if (i.status === 'fulfilled') machineImages.value = i.value
}

async function doDeployPreview() {
  const f = form.value
  if (!f.machine_id) return
  try {
    const r = await npu.previewCommand({
      machine_id: f.machine_id, mode: 'persistent', image: f.image,
      device_ids: f.device_ids,
      mounts: [f.model_dir].filter(Boolean), env: {}, network: f.network,
      ports: f.network === 'bridge' ? [`${f.port}:${f.port}`] : [], command: '（vllm serve 命令自动生成）',
    })
    deployPreview.value = r.docker_cmd.replace("bash -c '（vllm serve 命令自动生成）'", 'bash -c "<自动生成的 vllm serve 命令>"')
  } catch (e: any) { deployPreview.value = e.message || String(e) }
}

async function deploy() {
  const f = form.value
  if (!f.machine_id || !f.name || !f.model_dir) { dialog.toastError('机器、实例名、模型目录必填'); return }
  const specCfg = parseJsonField(f.speculative_config)
  const compCfg = parseJsonField(f.compilation_config)
  const addCfg = parseJsonField(f.additional_config)
  if (specCfg === 'INVALID') { dialog.toastError('speculative-config 不是合法 JSON'); return }
  if (compCfg === 'INVALID') { dialog.toastError('compilation-config 不是合法 JSON'); return }
  if (addCfg === 'INVALID') { dialog.toastError('additional-config 不是合法 JSON'); return }
  deploying.value = true
  try {
    await ops.deployService({
      machine_id: f.machine_id, name: f.name, model_dir: f.model_dir,
      model_name: f.model_name || f.name, image: f.image, port: f.port,
      device_ids: f.device_ids,
      network: f.network,
      ports: f.network === 'bridge' ? [`${f.port}:${f.port}`] : [],
      env: {},
      trust_remote_code: f.trust_remote_code, serve_args: f.serve_args,
      tp: f.tp, dp: f.dp, pp: f.pp, pcp: f.pcp, dcp: f.dcp,
      enable_ep: f.enable_ep, distributed_backend: f.distributed_backend,
      max_model_len: f.max_model_len, gpu_memory_utilization: f.gpu_memory_utilization,
      max_num_seqs: f.max_num_seqs, max_num_batched_tokens: f.max_num_batched_tokens,
      block_size: f.block_size, kv_cache_dtype: f.kv_cache_dtype, swap_space: f.swap_space,
      dtype: f.dtype, quantization: f.quantization, load_format: f.load_format,
      enforce_eager: f.enforce_eager, seed: f.seed,
      speculative_config: specCfg, compilation_config: compCfg, additional_config: addCfg,
      debug_mode: f.debug_mode, debugpy_port: f.debugpy_port, wait_for_client: f.wait_for_client,
      profiling_enabled: f.profiling_enabled, profiler_with_stack: f.profiler_with_stack,
    })
    showDeploy.value = false
    form.value = emptyDeploy(); deployPreview.value = ''
    dialog.toastSuccess('部署已发起', `${f.name} · 健康检查进行中`)
  } catch (e: any) { dialog.toastError('部署失败', e) } finally { deploying.value = false }
}

async function copy(text: string, tag: string) {
  try { await navigator.clipboard.writeText(text); copied.value = tag; setTimeout(() => (copied.value = ''), 1500) } catch {}
}

async function openDetail(s: NpuService) {
  detail.value = s
  debugInfo.value = null
  currentSession.value = null
  svcJobId.value = null
  if (s.profiling_enabled) await ops.fetchSessions(s.id)
}

async function checkHealth(s: NpuService) {
  const r = await ops.checkHealth(s.id).catch((e: any) => ({ ok: false, error: e.message || String(e) }))
  if (r.ok) dialog.toastSuccess('健康检查通过', s.name)
  else dialog.toastError('健康检查失败', (r as any).error || '服务可能还在加载')
  await ops.fetchServices()
}

async function loadDebugInfo(s: NpuService) {
  try {
    debugInfo.value = await ops.fetchDebugInfo(s.id)
  } catch (e: any) { dialog.toastError('获取调试信息失败', e) }
}

function copyDebugLaunch(s: NpuService) {
  loadDebugInfo(s).then(() => {
    if (debugInfo.value) copy(JSON.stringify(debugInfo.value.launch_json, null, 2), `launch${s.id}`)
  })
}

// Profiling 操作
async function profStart(s: NpuService) {
  const notes = (await dialog.prompt('采集备注（可空）：', '开始采集', '', '如 复现 TTFT 抖动')) || ''
  try {
    const r = await ops.startProfile(s.id, notes)
    currentSession.value = await ops.refreshSession(r.session_id)
    await ops.fetchSessions(s.id)
  } catch (e: any) { dialog.toastError('开始采集失败', e) }
}

async function profStop(session: ProfileSession) {
  try {
    await ops.stopProfile(session.id)
    currentSession.value = await ops.refreshSession(session.id)
    await ops.fetchSessions(session.service_id)
    dialog.toastSuccess('采集已停止', `${(currentSession.value?.files || []).length} 个输出文件`)
  } catch (e: any) { dialog.toastError('停止采集失败', e) }
}

async function profRefresh(session: ProfileSession) {
  try { currentSession.value = await ops.refreshSession(session.id) } catch (e: any) { dialog.toastError('刷新失败', e) }
}

function fmtSize(n: number) {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

function fmtTime(ts: string | null) { return ts ? new Date(ts).toLocaleString() : '—' }

function statusClass(s: string) {
  return s === 'running' ? 'job-st-completed' : (s === 'failed' || s === 'stopped') ? 'job-st-failed'
    : s === 'deploying' ? 'job-st-running' : 'job-st-pending'
}

const pgService = computed(() => (ops.pgServiceId ? ops.serviceById(ops.pgServiceId) : null))

function apiExample(): string {
  const s = pgService.value
  if (!s) return ''
  const base = `${location.origin}/api/npu/services/${s.id}/proxy/v1`
  const token = authStore.token || '<管理服务 API_KEY，见 .env 的 API_KEY>'
  return `curl ${base}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${token}" \\
  -d '{
    "model": "${s.model_name || s.name}",
    "messages": [{"role": "user", "content": "介绍一下你自己"}]
  }'`
}

async function copyApiExample() {
  copy(apiExample(), 'api')
}

function pyExample(): string {
  const s = pgService.value
  if (!s) return ''
  const base = `${location.origin}/api/npu/services/${s.id}/proxy/v1`
  const token = authStore.token || '<管理服务 API_KEY，见 .env 的 API_KEY>'
  return `from openai import OpenAI

# 统一推理网关：机器 IP/端口变化无感知，换服务只改 id 和 model
client = OpenAI(
    base_url="${base}",
    api_key="${token}",
)

resp = client.chat.completions.create(
    model="${s.model_name || s.name}",
    messages=[{"role": "user", "content": "介绍一下你自己"}],
    stream=True,  # 与 Playground 一致的流式输出
)
for chunk in resp:
    delta = chunk.choices[0].delta.content or ""
    print(delta, end="", flush=True)`
}

onMounted(async () => {
  await Promise.all([ops.fetchServices(), npu.fetchMachines(), npu.fetchProfileOptions()])
})
</script>

<template>
  <div class="view-container">
    <div class="page-head">
      <h2>服务部署</h2>
      <div class="head-actions">
        <button class="btn-ghost" @click="showPg = !showPg">{{ showPg ? '隐藏 Playground' : '打开 Playground' }}</button>
        <button class="btn-primary" @click="showDeploy = true">+ 部署服务</button>
      </div>
    </div>

    <!-- Playground -->
    <div v-if="showPg" class="pg-panel">
      <div class="pg-panel-head">
        <b>Playground</b>
        <select v-model.number="ops.pgServiceId" class="filter-sel">
          <option :value="null" disabled>选择服务实例</option>
          <option v-for="s in ops.runningServices" :key="s.id" :value="s.id">
            {{ s.name }}（{{ s.model_name || s.name }}）
          </option>
        </select>
        <span class="muted">统一 base_url：<code>/api/npu/services/{id}/proxy/v1</code>——外部脚本、评测程序都打这个地址，机器 IP 变化无感知</span>
      </div>
      <details v-if="pgService" class="pg-api-details">
        <summary>API 调用示例（复制到你自己的脚本 / 评测程序里直接用）</summary>
        <div class="pg-api-block">
          <div class="pg-api-head">
            <span>curl</span>
            <button class="btn-mini" @click="copyApiExample">{{ copied === 'api' ? '已复制' : '复制' }}</button>
          </div>
          <pre class="pg-api-code">{{ apiExample() }}</pre>
          <div class="pg-api-head">
            <span>Python（openai SDK，流式）</span>
            <button class="btn-mini" @click="copy(pyExample(), 'py')">{{ copied === 'py' ? '已复制' : '复制' }}</button>
          </div>
          <pre class="pg-api-code">{{ pyExample() }}</pre>
          <div class="muted">api_key 就是本系统的 API_KEY（登录令牌）。切换到别的服务实例只需改 URL 里的 id 和 model 名。</div>
        </div>
      </details>
      <Playground />
    </div>

    <div class="machine-grid">
      <div v-for="s in ops.services" :key="s.id" class="machine-card" @click="openDetail(s)">
        <div class="card-top">
          <span class="status-dot" :class="s.status === 'running' ? 'st-online' : (s.status === 'failed' || s.status === 'stopped') ? 'st-offline' : 'st-unknown'"></span>
          <b class="card-name">{{ s.name }}</b>
          <span :class="statusClass(s.status)">{{ s.status }}</span>
        </div>
        <div class="card-host">{{ s.model_name || s.name }} · TP{{ s.tp }} · {{ s.image.split(':').pop() }}</div>
        <div class="card-npu">
          <span>{{ s.devices.length }} 卡 · 端口 {{ (s.ports[0] || ':8000').split(':')[0] }}</span>
          <span class="card-driver">
            <span v-if="s.debug_mode" class="job-badge">调试</span>
            <span v-if="s.profiling_enabled" class="job-badge">Profiling</span>
          </span>
        </div>
        <div class="card-foot">
          <span class="card-check">健康 {{ s.last_health_ok === null ? '—' : s.last_health_ok ? '✓' : '✗' }} {{ fmtTime(s.last_health_at) }}</span>
          <span style="display: flex; gap: var(--space-1);" @click.stop>
            <button class="btn-mini" @click="checkHealth(s)">健康检查</button>
            <button v-if="s.status === 'running'" class="btn-mini" @click="ops.stopService(s.id)">停止</button>
            <button v-else class="btn-mini" @click="ops.startService(s.id)">启动</button>
          </span>
        </div>
      </div>
      <div v-if="ops.services.length === 0" class="empty" style="grid-column: 1/-1;">暂无服务实例，点击「部署服务」三步启动模型</div>
    </div>

    <!-- 部署表单 -->
    <div v-if="showDeploy" class="modal-mask">
      <div class="modal deploy-modal">
        <h3>部署 vLLM 服务</h3>
        <div class="gf">

          <div class="gf-label">基础</div>
          <div class="gf-row cols-2">
            <label>机器 *
              <select v-model="form.machine_id" @change="onMachineChange">
                <option :value="null" disabled>选择机器</option>
                <option v-for="m in npu.machines.filter(x => x.enabled && x.status !== 'offline')" :key="m.id" :value="m.id">
                  {{ m.name }}（{{ m.npu_count ?? '?' }} 卡 {{ m.npu_chip || '' }}{{ m.status === 'online' ? '' : '，未在线' }}）
                </option>
              </select>
            </label>
            <label>实例名 *<input v-model="form.name" placeholder="如 qwen32b" /></label>
          </div>
          <div class="gf-row cols-2">
            <label>模型目录 *
              <NpuFilterSelect
                v-model="form.model_dir"
                :options="machineModels.map(d => d.path)"
                placeholder="输入关键字过滤（如 qwen）或从下拉选择"
              />
            </label>
            <div class="gf-stack">
              <label>镜像（留空 = 机型默认，可输入关键字过滤）
                <NpuFilterSelect
                  v-model="form.image"
                  :options="machineImages.map(i => i.full_name)"
                  placeholder="从下拉选择机器上的镜像，或手输"
                />
              </label>
            </div>
          </div>
          <div class="gf-row cols-2">
            <label>服务端口<input v-model.number="form.port" type="number" /></label>
            <label>网络
              <select v-model="form.network">
                <option value="host">host（多卡/多机推荐）</option>
                <option value="bridge">bridge（端口映射）</option>
              </select>
            </label>
          </div>
          <div class="gf-row">
            <label>NPU 卡（已占用的卡不可选，不选 = 全部卡）
              <NpuCardPicker v-model="form.device_ids" :machine-id="form.machine_id" />
            </label>
          </div>

          <div class="gf-label">并行策略</div>
          <div class="gf-row cols-4">
            <label>TP（张量并行）<input v-model.number="form.tp" type="number" min="1" /></label>
            <label>DP（数据并行）<input v-model.number="form.dp" type="number" min="1" placeholder="默认 1" /></label>
            <label>PP（流水线并行）<input v-model.number="form.pp" type="number" min="1" placeholder="默认 1" /></label>
            <label>分布式后端
              <select v-model="form.distributed_backend">
                <option value="auto">auto</option>
                <option value="mp">mp</option>
                <option value="ray">ray</option>
              </select>
            </label>
          </div>
          <div class="gf-row cols-4">
            <label>PCP（Prefill CP）<input v-model.number="form.pcp" type="number" min="1" placeholder="默认 1" /></label>
            <label>DCP（Decode CP）<input v-model.number="form.dcp" type="number" min="1" placeholder="默认 1" /></label>
            <label class="gf-check"><input type="checkbox" v-model="form.enable_ep" /> EP（专家并行，MoE）</label>
            <div class="gf-note">SP（序列并行）：TP&gt;1 且 DP&gt;1（MoE + EP）时自动启用，无需单独配置</div>
          </div>

          <details class="gf-details">
            <summary>内存与缓存 / 精度 / 性能（常用高级参数）</summary>
            <div class="gf-row cols-4">
              <label>max-model-len<input v-model.number="form.max_model_len" type="number" placeholder="默认模型配置" /></label>
              <label>gpu-memory-utilization<input v-model.number="form.gpu_memory_utilization" step="0.05" placeholder="0.9" /></label>
              <label>max-num-seqs<input v-model.number="form.max_num_seqs" type="number" placeholder="默认 256" /></label>
              <label>max-num-batched-tokens<input v-model.number="form.max_num_batched_tokens" type="number" placeholder="默认 2048" /></label>
            </div>
            <div class="gf-row cols-4">
              <label>block-size
                <select v-model="form.block_size">
                  <option :value="null">默认</option>
                  <option :value="16">16</option>
                  <option :value="32">32</option>
                  <option :value="128">128（Ascend 常用）</option>
                </select>
              </label>
              <label>kv-cache-dtype
                <select v-model="form.kv_cache_dtype">
                  <option value="">auto</option>
                  <option value="fp8">fp8</option>
                  <option value="int8">int8</option>
                </select>
              </label>
              <label>swap-space（GB）<input v-model.number="form.swap_space" type="number" step="0.5" placeholder="默认 4" /></label>
              <label>seed<input v-model.number="form.seed" type="number" placeholder="随机" /></label>
            </div>
            <div class="gf-row cols-4">
              <label>dtype
                <select v-model="form.dtype">
                  <option value="auto">auto</option>
                  <option value="float16">float16</option>
                  <option value="bfloat16">bfloat16</option>
                  <option value="float32">float32</option>
                </select>
              </label>
              <label>quantization<input v-model="form.quantization" placeholder="如 ascend" /></label>
              <label>load-format
                <select v-model="form.load_format">
                  <option value="auto">auto</option>
                  <option value="sharded_state">sharded_state</option>
                  <option value="dummy">dummy</option>
                </select>
              </label>
              <label class="gf-check"><input type="checkbox" v-model="form.enforce_eager" /> enforce-eager</label>
            </div>
            <div class="gf-row cols-2">
              <label class="gf-check"><input type="checkbox" v-model="form.trust_remote_code" /> trust-remote-code（加载 HF 仓库自定义代码）</label>
            </div>
          </details>

          <details class="gf-details">
            <summary>JSON 配置（投机推理 / 编译 / Ascend additional-config）</summary>
            <label>speculative-config（MTP 投机推理，JSON）
              <textarea v-model="form.speculative_config" rows="2" class="gf-code" placeholder='{"method": "mtp", "num_speculative_tokens": 3}'></textarea>
            </label>
            <label>compilation-config（编译配置，JSON）
              <textarea v-model="form.compilation_config" rows="2" class="gf-code" placeholder='{"cudagraph_mode": "FULL_DECODE_ONLY"}'></textarea>
            </label>
            <label>additional-config（Ascend 扩展配置，JSON）
              <textarea v-model="form.additional_config" rows="2" class="gf-code" placeholder='{"ascend_scheduler_config": {"enable_balance_scheduling": true}}'></textarea>
            </label>
          </details>

          <details class="gf-details">
            <summary>调试与 Profiling</summary>
            <div class="gf-row cols-4">
              <label class="gf-check"><input type="checkbox" v-model="form.debug_mode" /> 调试模式（注入 debugpy）</label>
              <label v-if="form.debug_mode">debugpy 端口<input v-model.number="form.debugpy_port" type="number" /></label>
              <label v-if="form.debug_mode" class="gf-check"><input type="checkbox" v-model="form.wait_for_client" /> 挂起等 attach</label>
            </div>
            <div class="gf-row cols-4">
              <label class="gf-check"><input type="checkbox" v-model="form.profiling_enabled" /> Profiling 采集支持（--profiler-config）</label>
              <label v-if="form.profiling_enabled" class="gf-check"><input type="checkbox" v-model="form.profiler_with_stack" /> 采集 python stack（数据量大）</label>
            </div>
          </details>

          <div class="gf-row">
            <label>额外参数（自由文本，追加在命令末尾）
              <textarea v-model="form.serve_args" rows="2" class="gf-code" placeholder="--enable-expert-parallel --no-enable-prefix-caching ..."></textarea>
            </label>
          </div>

          <div v-if="deployPreview" class="docker-preview">{{ deployPreview }}</div>
          <div class="form-actions">
            <button class="btn-ghost" @click="showDeploy = false">取消</button>
            <button class="btn-ghost" @click="doDeployPreview">预览挂载与设备</button>
            <button class="btn-primary" :disabled="deploying" @click="deploy">{{ deploying ? '部署中…' : '部署' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 实例详情（Playground 入口 / 调试 / Profiling） -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="drawer">
        <div class="drawer-head">
          <h3>{{ detail.name }} <span :class="statusClass(detail.status)">{{ detail.status }}</span></h3>
          <button class="btn-ghost" @click="detail = null">关闭</button>
        </div>

        <section class="drawer-section">
          <h4>推理测试</h4>
          <div class="preset-row">
            <button class="btn-mini" @click="ops.pgServiceId = detail.id; showPg = true; detail = null">在 Playground 中打开</button>
            <button class="btn-mini" @click="copy(detail.health_url, 'url')">{{ copied === 'url' ? '已复制' : '复制服务地址' }}</button>
          </div>
        </section>

        <section v-if="detail.debug_mode" class="drawer-section">
          <h4>远程调试（debugpy attach）</h4>
          <div class="preset-row" style="flex-wrap: wrap;">
            <button class="btn-mini" @click="copyDebugLaunch(detail)">{{ copied === `launch${detail.id}` ? '已复制 launch.json' : '复制 VSCode launch.json' }}</button>
            <button class="btn-mini" @click="loadDebugInfo(detail); copy(debugInfo?.cli_cmd || '', 'cli')">{{ copied === 'cli' ? '已复制' : '复制命令行 attach' }}</button>
          </div>
          <div v-if="debugInfo" class="ssh-info" style="margin-top: var(--space-2);">
            <div class="muted">attach 地址：{{ debugInfo.attach_host }}:{{ debugInfo.attach_port }}（{{ debugInfo.wait_for_client ? '挂起等待连接' : '服务已启动可随时 attach' }}）</div>
            <details><pre>{{ JSON.stringify(debugInfo.launch_json, null, 2) }}</pre></details>
            <div class="muted">{{ debugInfo.hint }}</div>
          </div>
        </section>

        <section v-if="detail.profiling_enabled" class="drawer-section">
          <h4>Profiling 采集</h4>
          <div class="preset-row">
            <button class="btn-mini" :disabled="detail.status !== 'running'" @click="profStart(detail)">开始采集</button>
            <span class="muted">{{ detail.profiling_dir }}</span>
          </div>
          <div class="job-list" style="margin-top: var(--space-2);">
            <div v-for="sess in ops.sessions" :key="sess.id" class="job-row-item">
              <div class="job-item-top">
                <b>#{{ sess.id }}</b>
                <span :class="sess.status === 'collecting' ? 'job-st-running' : sess.status === 'completed' ? 'job-st-completed' : 'job-st-failed'">{{ sess.status }}</span>
                <span class="muted">{{ fmtTime(sess.started_at) }} · {{ sess.duration_s ? Math.round(sess.duration_s) + 's' : '' }} · {{ (sess.files || []).length }} 文件 {{ fmtSize(sess.total_size) }}</span>
                <span style="flex: 1"></span>
                <button v-if="sess.status === 'collecting'" class="btn-mini" @click="profStop(sess)">停止采集</button>
                <button v-if="sess.status !== 'collecting'" class="btn-mini" @click="profRefresh(sess)">刷新文件</button>
              </div>
              <ul v-if="(currentSession?.id === sess.id ? currentSession.files : sess.files)?.length" class="dir-list">
                <li v-for="f in (currentSession?.id === sess.id ? currentSession.files : sess.files)" :key="f.name">
                  <code>{{ f.name }}</code>
                  <span class="dir-src">{{ fmtSize(f.size) }}</span>
                  <button class="btn-mini" @click="ops.downloadProfileFile(sess.id, f.name)">下载</button>
                </li>
              </ul>
              <div v-if="sess.error_message" class="job-err">{{ sess.error_message }}</div>
            </div>
            <div v-if="ops.sessions.length === 0" class="muted">暂无采集会话</div>
          </div>
          <div class="muted" style="margin-top: var(--space-2);">
            性能文件（ascend_pytorch_profiler_*.db / trace）下载后用 MindStudio Insight 做算子级分析
          </div>
        </section>

        <section v-else class="drawer-section">
          <h4>Profiling</h4>
          <div class="muted">该实例未开启 Profiling 支持。以「Profiling 采集支持」重新部署后，可一键开始/停止采集。</div>
        </section>

        <section class="drawer-section">
          <h4>启动日志（最近部署任务）</h4>
          <div v-if="svcJobId" class="log-inline"><LogViewer :job-id="svcJobId" /></div>
          <div v-else class="muted">在任务中心查看该实例关联任务日志</div>
        </section>
      </div>
    </div>

    <NpuDialog />
  </div>
</template>

<style scoped src="../components/npu/npu-shared.css"></style>

<style scoped>
.pg-panel {
  border: 1px solid var(--border-faint); border-radius: var(--radius-md);
  padding: var(--space-3); margin-bottom: var(--space-4); height: 480px;
  display: flex; flex-direction: column;
}
.pg-panel-head { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2); }
.filter-sel {
  padding: var(--space-1) var(--space-2); border-radius: var(--radius-md);
  border: 1px solid var(--border-faint); background: var(--surface-faint, transparent);
  color: inherit; font-size: var(--text-sm);
}
.adv-panel summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-secondary); }
.adv-panel .chk { flex-direction: row !important; align-items: center; gap: 6px !important; }
.pg-api-details { margin-bottom: var(--space-2); }
.pg-api-details summary { cursor: pointer; font-size: var(--text-xs); color: var(--text-secondary); user-select: none; }
.pg-api-block { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); }
.pg-api-head { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-xs); color: var(--text-tertiary); }
.pg-api-code {
  background: var(--surface-faint, #0a0e14); color: #c7d4e3;
  padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  font-family: 'SF Mono', Menlo, monospace; font-size: var(--text-xs); line-height: 1.6;
  white-space: pre-wrap; word-break: break-all; margin: 4px 0 0;
}
</style>
