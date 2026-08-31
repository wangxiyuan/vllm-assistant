<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useNpuStore, type NpuMachine, type MachineMetric, type MachineModelDir, type MachineImage } from '@/stores/npu'
import LogViewer from '@/components/npu/LogViewer.vue'
import NpuDialog from '@/components/npu/NpuDialog.vue'
import { useNpuDialog } from '@/composables/useNpuDialog'

const npu = useNpuStore()
const dialog = useNpuDialog()

const showForm = ref(false)
const editing = ref<NpuMachine | null>(null)
const form = ref<any>(emptyForm())
const saving = ref(false)
const testing = ref<number | null>(null)
const testResult = ref<{ id: number; ok: boolean; message: string } | null>(null)

const detail = ref<NpuMachine | null>(null)
const metrics = ref<MachineMetric[]>([])
const modelDirs = ref<MachineModelDir[]>([])
const images = ref<MachineImage[]>([])
const sshInfo = ref<any>(null)
const newModelPath = ref('')
const quickCmd = ref('')
const quickJobId = ref<number | null>(null)
const copied = ref('')
const imageFilter = ref('')
const modelFilter = ref('')
const activeTab = ref<'overview' | 'models' | 'images' | 'quick'>('overview')

const filteredImages = computed(() => {
  const kw = imageFilter.value.trim().toLowerCase()
  if (!kw) return images.value
  return images.value.filter(i => i.full_name.toLowerCase().includes(kw))
})

const filteredModels = computed(() => {
  const kw = modelFilter.value.trim().toLowerCase()
  if (!kw) return modelDirs.value
  return modelDirs.value.filter(d => d.path.toLowerCase().includes(kw))
})

/** 最近一次巡检点（概览指标来源） */
const latestMetric = computed(() => metrics.value.length ? metrics.value[metrics.value.length - 1] : null)

function maxOf(arr: number[] | null | undefined): number | null {
  const nums = (arr || []).filter((v): v is number => typeof v === 'number')
  return nums.length ? Math.max(...nums) : null
}
function sumOf(arr: number[] | null | undefined): number {
  return (arr || []).filter((v): v is number => typeof v === 'number').reduce((a, b) => a + b, 0)
}
function fmt1(v: number | null, unit = ''): string {
  return v === null ? '—' : `${v.toFixed(1)}${unit}`
}
/** 显存：SUM(used)/SUM(total) → GB */
const memStat = computed(() => {
  const m = latestMetric.value
  if (!m) return null
  const used = sumOf(m.npu_mem_used), total = sumOf(m.npu_mem_total)
  if (!total) return null
  return { used: (used / 1024).toFixed(0), total: (total / 1024).toFixed(0), pct: (used * 100 / total) }
})

const statChips = computed(() => {
  const m = latestMetric.value
  const mem = memStat.value
  return [
    { k: '显存', v: mem ? `${mem.used} / ${mem.total} GB` : '—' },
    { k: '最高温度', v: m ? fmt1(maxOf(m.temperature), '℃') : '—' },
    { k: '总功耗', v: m ? fmt1(sumOf(m.power), ' W') : '—' },
    { k: 'CPU', v: m && m.cpu !== null ? fmt1(m.cpu, '%') : '—' },
    { k: '内存', v: m && m.mem !== null ? fmt1(m.mem, '%') : '—' },
    { k: '磁盘', v: m && m.disk !== null ? fmt1(m.disk, '%') : '—' },
  ]
})

function emptyForm() {
  return {
    id: 0, name: '', host: '', port: 22, username: 'root', auth_type: 'key',
    key_content: '', key_path: '', password: '', machine_type: 'a2',
    workdir: '~/npu-workspace', model_root: '', tags: '',
  }
}

const keyFileEl = ref<HTMLInputElement | null>(null)

/** 从本地文件读取私钥内容（浏览器 File API，不上传原始文件） */
function onKeyFileChange(e: Event) {
  const input = e.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => { form.value.key_content = String(reader.result || '').trim() }
  reader.readAsText(file)
  input!.value = ''
}

const typeLabel = computed(() => {
  const m: Record<string, string> = { a2: 'Atlas A2', a3: 'Atlas A3', '310p': '300I DUO', other: '自定义' }
  return (t: string) => m[t] || t
})

function openCreate() { editing.value = null; form.value = emptyForm(); showForm.value = true }
function openEdit(m: NpuMachine) {
  editing.value = m
  form.value = { ...emptyForm(), ...m, key_content: '', password: '', tags: (m.tags || []).join(',') }
  showForm.value = true
}

async function save() {
  if (!form.value.name || !form.value.host) return
  saving.value = true
  try {
    const payload: any = {
      name: form.value.name, host: form.value.host, port: form.value.port,
      username: form.value.username, auth_type: form.value.auth_type,
      machine_type: form.value.machine_type,
      workdir: form.value.workdir, model_root: form.value.model_root,
      tags: form.value.tags ? form.value.tags.split(',').map((s: string) => s.trim()).filter(Boolean) : [],
    }
    if (form.value.password) payload.password = form.value.password
    if (form.value.key_content.trim()) payload.key_content = form.value.key_content
    if (editing.value) payload.id = editing.value.id
    await npu.saveMachine(payload)
    showForm.value = false
    // 从详情抽屉进入编辑时，保存后同步刷新抽屉数据
    const updated = npu.machines.find(m => m.id === payload.id)
    if (detail.value && updated && detail.value.id === updated.id) detail.value = updated
    dialog.toastSuccess('机器已保存', payload.name)
  } catch (e: any) { dialog.toastError('保存失败', e) } finally { saving.value = false }
}

async function removeMachine(m: NpuMachine) {
  if (!(await dialog.confirm(
    `确认移除机器「${m.name}」？其巡检历史、镜像/模型缓存与任务记录将一并删除，机器本身不受影响。`,
    '移除机器',
  ))) return
  try {
    await npu.deleteMachine(m.id)
    if (detail.value?.id === m.id) detail.value = null
    dialog.toastSuccess('机器已移除', m.name)
  } catch (e: any) { dialog.toastError('移除失败', e) }
}

async function runTest(m: NpuMachine) {
  testing.value = m.id
  testResult.value = null
  try {
    const r = await npu.testMachine(m.id)
    testResult.value = { id: m.id, ok: r.ok, message: r.message }
  } catch (e: any) {
    testResult.value = { id: m.id, ok: false, message: e.message || String(e) }
  } finally { testing.value = null }
}

async function copy(text: string, tag: string) {
  try { await navigator.clipboard.writeText(text); copied.value = tag; setTimeout(() => (copied.value = ''), 1500) } catch {}
}

async function openDetail(m: NpuMachine) {
  detail.value = m
  metrics.value = []
  modelDirs.value = []
  images.value = []
  sshInfo.value = null
  quickJobId.value = null
  imageFilter.value = ''
  modelFilter.value = ''
  activeTab.value = 'overview'
  const [mt, md, mi, si] = await Promise.allSettled([
    npu.fetchMachineMetrics(m.id, 24), npu.fetchMachineModels(m.id),
    npu.fetchMachineImages(m.id), npu.fetchSshInfo(m.id),
  ])
  if (mt.status === 'fulfilled') metrics.value = mt.value
  if (md.status === 'fulfilled') modelDirs.value = md.value
  if (mi.status === 'fulfilled') images.value = mi.value
  if (si.status === 'fulfilled') sshInfo.value = si.value
}

async function addModelDir() {
  if (!detail.value || !newModelPath.value.trim()) return
  modelDirs.value = await npu.addMachineModel(detail.value.id, newModelPath.value.trim())
  newModelPath.value = ''
}

async function runQuickCmd() {
  if (!detail.value || !quickCmd.value.trim()) return
  const job = await npu.createJob({
    machine_id: detail.value.id, mode: 'oneshot', exec_target: 'host',
    command: quickCmd.value, name: '快速命令', timeout: 300,
  })
  quickJobId.value = job.id
}

/** 真正触发一次巡检（同步 SSH 采集），完成后刷新详情与列表 */
const refreshing = ref(false)
async function runRefresh() {
  if (!detail.value || refreshing.value) return
  refreshing.value = true
  try {
    const r = await npu.refreshMachine(detail.value.id)
    if (!r.ok) dialog.toastError('巡检失败', r.message || '')
    await Promise.all([
      npu.fetchMachines(),
      npu.fetchMachineMetrics(detail.value.id, 24),
      npu.fetchMachineModels(detail.value.id),
      npu.fetchMachineImages(detail.value.id),
    ]).then(([_, mt, md, mi]) => {
      metrics.value = mt as any
      modelDirs.value = md as any
      images.value = mi as any
      if (r.ok) {
        const updated = npu.machines.find(m => m.id === detail.value!.id)
        if (updated) detail.value = updated
      }
    })
  } catch (e: any) {
    dialog.toastError('巡检失败', e)
  } finally { refreshing.value = false }
}

function fmtTime(ts: string | null) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

function statusClass(s: string) {
  return s === 'online' ? 'st-online' : s === 'offline' ? 'st-offline' : 'st-unknown'
}

onMounted(async () => {
  await Promise.all([npu.fetchMachines(), npu.fetchProfileOptions()])
})
</script>

<template>
  <div class="view-container">
    <div class="page-head">
      <h2>NPU 机器</h2>
      <div class="head-actions">
        <span class="head-stat">在线 <b>{{ npu.onlineCount }}</b> / {{ npu.machines.length }}</span>
        <button class="btn-primary" @click="openCreate">+ 纳管机器</button>
      </div>
    </div>

    <div v-if="npu.machines.length === 0" class="empty">还没有纳管机器，点击右上角「纳管机器」开始</div>

    <div class="machine-grid">
      <div v-for="m in npu.machines" :key="m.id" class="machine-card" @click="openDetail(m)">
        <div class="card-top">
          <span class="status-dot" :class="statusClass(m.status)"></span>
          <b class="card-name">{{ m.name }}</b>
          <span class="card-type">{{ typeLabel(m.machine_type) }}</span>
        </div>
        <div class="card-host">{{ m.username }}@{{ m.host }}:{{ m.port }}</div>
        <div class="card-npu">
          <span>{{ m.npu_count ?? '?' }} 卡 {{ m.npu_chip || '' }}</span>
          <span class="card-driver">{{ m.driver_version || '' }}</span>
        </div>
        <div class="card-foot">
          <span class="card-check">巡检 {{ fmtTime(m.last_check_at) }}</span>
          <button class="btn-mini" :disabled="testing === m.id" @click.stop="runTest(m)">
            {{ testing === m.id ? '测试中…' : '测试连接' }}
          </button>
          <button class="btn-mini btn-danger-mini" @click.stop="openEdit(m)">编辑</button>
          <button class="btn-mini btn-danger-mini" @click.stop="removeMachine(m)">移除</button>
        </div>
        <div v-if="testResult && testResult.id === m.id" class="test-result" :class="testResult.ok ? 'ok' : 'bad'">
          {{ testResult.message }}
        </div>
      </div>
    </div>

    <!-- 纳管/编辑表单 -->
    <!-- 纳管/编辑表单（层级高于详情抽屉，从抽屉点编辑时盖在上层） -->
    <div v-if="showForm" class="modal-mask modal-mask-top">
      <div class="modal">
        <h3>{{ editing ? `编辑机器 ${editing.name}` : '纳管 NPU 机器' }}</h3>
        <div class="form-grid">
          <label>名称 *<input v-model="form.name" placeholder="如 a2-01" /></label>
          <label>机型
            <select v-model="form.machine_type">
              <option v-for="p in npu.profileOptions" :key="p.value" :value="p.value">
                {{ p.label }}（{{ p.npu_count ?? '?' }} 卡）{{ p.notes ? ' - ' + p.notes : '' }}
              </option>
            </select>
          </label>
          <label>主机 *<input v-model="form.host" placeholder="IP 或主机名" /></label>
          <label>SSH 端口<input v-model.number="form.port" type="number" /></label>
          <label>用户名<input v-model="form.username" /></label>
          <label>认证方式
            <select v-model="form.auth_type">
              <option value="key">SSH 密钥（推荐）</option>
              <option value="password">密码</option>
            </select>
          </label>
          <label v-if="form.auth_type === 'key'">私钥内容
            <div class="key-input-row">
              <textarea
                v-model="form.key_content"
                rows="4"
                class="key-textarea"
                :placeholder="editing && !form.key_content ? '留空 = 保持已有私钥不变；粘贴 PEM 私钥（-----BEGIN ... PRIVATE KEY-----）' : '粘贴 PEM 私钥（-----BEGIN ... PRIVATE KEY-----）'"
              ></textarea>
              <div class="key-file-row">
                <button class="btn-mini" type="button" @click="keyFileEl?.click()">从文件读取</button>
                <input ref="keyFileEl" type="file" accept=".pem,.key,.rsa,.ed25519,.ecdsa,id_rsa,id_ed25519,*" style="display: none" @change="onKeyFileChange" />
                <span class="muted">私钥仅存服务端（加密），不会回显</span>
              </div>
            </div>
          </label>
          <label v-if="form.auth_type === 'key'">服务端私钥路径（可选，兼容旧配置）<input v-model="form.key_path" placeholder="如 ~/.ssh/id_rsa；填写了私钥内容则优先用内容" /></label>
          <label v-if="form.auth_type === 'password'">
            密码<input v-model="form.password" type="password" :placeholder="editing ? '留空 = 不修改' : ''" />
          </label>
          <label>远程工作目录<input v-model="form.workdir" placeholder="~/npu-workspace" /></label>
          <label>模型仓库根目录<input v-model="form.model_root" placeholder="如 /data/models，用于扫描模型目录" /></label>
          <label>标签（逗号分隔）<input v-model="form.tags" placeholder="训练,推理" /></label>
        </div>
        <div class="form-actions">
          <button class="btn-ghost" @click="showForm = false">取消</button>
          <button class="btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 机器详情抽屉 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="drawer">
        <div class="drawer-head">
          <div class="drawer-title">
            <h3>{{ detail.name }} <span class="card-type">{{ typeLabel(detail.machine_type) }}</span></h3>
            <div class="drawer-sub">
              <span class="status-dot" :class="statusClass(detail.status)"></span>
              <span class="mono">{{ detail.username }}@{{ detail.host }}:{{ detail.port }}</span>
              <span class="dot-sep">·</span>
              <span>{{ detail.npu_count ?? '?' }} 卡 {{ detail.npu_chip || '' }}</span>
              <span class="dot-sep">·</span>
              <span>巡检 {{ fmtTime(detail.last_check_at) }}</span>
            </div>
          </div>
          <div class="drawer-head-actions">
            <button class="btn-ghost" :disabled="refreshing" @click="runRefresh">
              {{ refreshing ? '巡检中…' : '立即巡检' }}
            </button>
            <button class="btn-mini" @click.stop="openEdit(detail)">编辑</button>
            <button class="btn-mini btn-danger-mini" @click.stop="removeMachine(detail)">移除</button>
            <button class="btn-ghost" @click="detail = null">关闭</button>
          </div>
        </div>

        <div v-if="detail.status_message" class="status-banner bad">{{ detail.status_message }}</div>

        <div class="drawer-tabs">
          <button :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">概览</button>
          <button :class="{ active: activeTab === 'models' }" @click="activeTab = 'models'">
            模型目录 <span class="tab-count">{{ modelDirs.length }}</span>
          </button>
          <button :class="{ active: activeTab === 'images' }" @click="activeTab = 'images'">
            容器镜像 <span class="tab-count">{{ images.length }}</span>
          </button>
          <button :class="{ active: activeTab === 'quick' }" @click="activeTab = 'quick'">快速命令</button>
        </div>

        <!-- 概览 -->
        <div v-if="activeTab === 'overview'" class="tab-pane">
          <div class="stat-grid">
            <div v-for="c in statChips" :key="c.k" class="stat-chip">
              <span class="k">{{ c.k }}</span>
              <span class="v">{{ c.v }}</span>
            </div>
          </div>
          <div class="ov-block">
            <div class="ov-head"><h4>SSH 连接</h4></div>
            <div v-if="sshInfo" class="ssh-info">
              <div class="ssh-row">
                <code>{{ sshInfo.ssh_cmd }}</code>
                <button class="btn-mini" @click="copy(sshInfo.ssh_cmd, 'ssh')">{{ copied === 'ssh' ? '已复制' : '复制' }}</button>
              </div>
              <details>
                <summary>~/.ssh/config 片段（VSCode Remote-SSH 用）</summary>
                <pre>{{ sshInfo.ssh_config }}</pre>
                <button class="btn-mini" @click="copy(sshInfo.ssh_config, 'cfg')">{{ copied === 'cfg' ? '已复制' : '复制片段' }}</button>
              </details>
            </div>
            <div v-else class="muted">加载中…</div>
          </div>
        </div>

        <!-- 模型目录 -->
        <div v-else-if="activeTab === 'models'" class="tab-pane">
          <div class="pane-toolbar">
            <input v-model="modelFilter" class="pane-search" placeholder="过滤模型路径，如 qwen、deepseek…" />
            <input v-model="newModelPath" class="pane-search" placeholder="手动登记目录，如 /data/models/Qwen3-32B" @keydown.enter="addModelDir" />
            <button class="btn-mini" @click="addModelDir">登记</button>
          </div>
          <ul class="dir-list list-scroll">
            <li v-for="d in filteredModels" :key="d.id">
              <code>{{ d.path }}</code>
            </li>
            <li v-if="filteredModels.length === 0" class="muted">
              {{ modelDirs.length ? '无匹配结果' : '无（配置 model_root 后巡检自动扫描，也可手动登记）' }}
            </li>
          </ul>
        </div>

        <!-- 容器镜像 -->
        <div v-else-if="activeTab === 'images'" class="tab-pane">
          <div class="pane-toolbar">
            <input v-model="imageFilter" class="pane-search" placeholder="过滤镜像，如 vllm、cann、ubuntu…" />
          </div>
          <ul class="dir-list list-scroll">
            <li v-for="i in filteredImages" :key="i.id"><code>{{ i.full_name }}</code></li>
            <li v-if="filteredImages.length === 0" class="muted">
              {{ images.length ? '无匹配镜像' : '无（巡检时自动扫描 docker images）' }}
            </li>
          </ul>
        </div>

        <!-- 快速命令 -->
        <div v-else class="tab-pane">
          <div class="pane-toolbar">
            <input v-model="quickCmd" class="pane-search" placeholder="在宿主机执行一次性命令，如 npu-smi info" @keydown.enter="runQuickCmd" />
            <button class="btn-mini" @click="runQuickCmd">执行</button>
          </div>
          <div v-if="quickJobId" class="log-inline">
            <LogViewer :job-id="quickJobId" />
          </div>
          <div v-else class="muted ov-empty">命令直接在宿主机 shell 执行（不进容器），输出实时显示在下方</div>
        </div>
      </div>
    </div>

    <NpuDialog />
  </div>
</template>

<style scoped src="../components/npu/npu-shared.css"></style>

<style scoped>
.key-input-row { display: flex; flex-direction: column; gap: 4px; }
.key-textarea {
  width: 100%; box-sizing: border-box; padding: var(--space-2);
  border-radius: var(--radius-md); border: 1px solid var(--border-faint);
  background: var(--bg-elev-2); color: var(--text-primary);
  font-family: 'SF Mono', Menlo, monospace; font-size: var(--text-xs); resize: vertical;
}
.key-textarea:focus { outline: none; border-color: var(--amber); }
.key-file-row { display: flex; align-items: center; gap: var(--space-2); }
.drawer-head-actions { display: flex; align-items: center; gap: var(--space-2); }
.btn-danger-mini { color: var(--danger, #e5484d); border-color: var(--danger, #e5484d); }

/* ── 抽屉：标题区 + 页签 + 内容面板 ── */
.drawer { display: flex; flex-direction: column; }
.drawer-title { min-width: 0; }
.drawer-sub {
  display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap;
  margin-top: 4px; font-size: var(--text-xs); color: var(--text-tertiary);
}
.drawer-sub .mono { font-family: 'SF Mono', Menlo, monospace; }
.dot-sep { opacity: 0.5; }
.status-banner {
  margin-top: var(--space-3); padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md); font-size: var(--text-xs); word-break: break-all;
}
.status-banner.bad { color: var(--amber); background: rgba(255, 170, 0, 0.08); border: 1px solid rgba(255, 170, 0, 0.25); }

.drawer-tabs {
  display: flex; gap: var(--space-1); margin-top: var(--space-3);
  border-bottom: 1px solid var(--border-faint); flex-shrink: 0;
}
.drawer-tabs button {
  background: none; border: none; cursor: pointer; padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm); color: var(--text-secondary);
  border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.drawer-tabs button:hover { color: var(--text-primary); }
.drawer-tabs button.active { color: var(--amber); border-bottom-color: var(--amber); font-weight: 600; }
.tab-count {
  font-size: var(--text-xs); background: var(--hover-bg); color: var(--text-tertiary);
  border-radius: 8px; padding: 0 6px; margin-left: 2px;
}

.tab-pane { flex: 1; min-height: 0; display: flex; flex-direction: column; padding-top: var(--space-3); }

/* 概览：指标卡网格 + 图表 + SSH */
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: var(--space-2); margin-bottom: var(--space-3);
}
.stat-chip {
  background: var(--surface-faint, rgba(255,255,255,0.03));
  border: 1px solid var(--border-faint); border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3); display: flex; flex-direction: column; gap: 2px;
}
.stat-chip .k { font-size: var(--text-xs); color: var(--text-tertiary); }
.stat-chip .v { font-size: var(--text-lg); font-weight: 600; color: var(--text-primary); }
.ov-block { margin-bottom: var(--space-3); }
.ov-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: var(--space-2); }
.ov-head h4 { margin: 0; font-size: var(--text-sm); }
.ov-empty { padding: var(--space-4); text-align: center; border: 1px dashed var(--border-faint); border-radius: var(--radius-md); }

/* 分页内容：工具行 + 可滚动列表 */
.pane-toolbar { display: flex; gap: var(--space-2); margin-bottom: var(--space-2); flex-shrink: 0; }
.pane-search {
  flex: 1; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  border: 1px solid var(--border-faint); background: var(--bg-elev-2);
  color: var(--text-primary); font-size: var(--text-sm); min-width: 0;
}
.pane-search:focus { outline: none; border-color: var(--amber); }
.list-scroll { flex: 1; min-height: 0; overflow-y: auto; max-height: calc(92vh - 250px); }
.list-scroll li { padding: 3px 0; }
</style>
