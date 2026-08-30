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
    dialog.toastSuccess('机器已保存', payload.name)
  } catch (e: any) { dialog.toastError('保存失败', e) } finally { saving.value = false }
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

async function removeModelDir(id: number) {
  if (!detail.value) return
  modelDirs.value = await npu.deleteMachineModel(detail.value.id, id)
}

async function runQuickCmd() {
  if (!detail.value || !quickCmd.value.trim()) return
  const job = await npu.createJob({
    machine_id: detail.value.id, mode: 'oneshot', command: quickCmd.value,
    name: '快速命令', timeout: 300,
  })
  quickJobId.value = job.id
}

/** NPU 利用率 SVG 折线（24h 曲线，取每卡均值） */
function utilPoints(): string {
  const data = metrics.value.map(m => {
    const arr = (m.npu_util || []).filter((v: any) => typeof v === 'number')
    return arr.length ? arr.reduce((a: number, b: number) => a + b, 0) / arr.length : null
  })
  const pts = data.filter((v): v is number => v !== null)
  if (pts.length < 2) return ''
  const W = 300, H = 60, max = 100
  const step = W / (pts.length - 1)
  return pts.map((v, i) => `${(i * step).toFixed(1)},${(H - (v / max) * H).toFixed(1)}`).join(' ')
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
        </div>
        <div v-if="testResult && testResult.id === m.id" class="test-result" :class="testResult.ok ? 'ok' : 'bad'">
          {{ testResult.message }}
        </div>
      </div>
    </div>

    <!-- 纳管/编辑表单 -->
    <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
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
          <h3>{{ detail.name }} <span class="card-type">{{ typeLabel(detail.machine_type) }}</span></h3>
          <button class="btn-ghost" @click="detail = null">关闭</button>
        </div>

        <section class="drawer-section">
          <h4>连接</h4>
          <div v-if="sshInfo" class="ssh-info">
            <div class="ssh-row">
              <code>{{ sshInfo.ssh_cmd }}</code>
              <button class="btn-mini" @click="copy(sshInfo.ssh_cmd, 'ssh')">{{ copied === 'ssh' ? '已复制' : '复制' }}</button>
            </div>
            <div class="ssh-row">
              <code>{{ sshInfo.exec_hint }}</code>
              <button class="btn-mini" @click="copy(sshInfo.exec_hint, 'exec')">复制模板</button>
            </div>
            <details>
              <summary>~/.ssh/config 片段（VSCode Remote-SSH 用）</summary>
              <pre>{{ sshInfo.ssh_config }}</pre>
              <button class="btn-mini" @click="copy(sshInfo.ssh_config, 'cfg')">{{ copied === 'cfg' ? '已复制' : '复制片段' }}</button>
            </details>
          </div>
        </section>

        <section class="drawer-section">
          <h4>巡检历史（24h 平均 NPU 利用率）</h4>
          <svg v-if="utilPoints()" viewBox="0 0 300 60" class="util-chart">
            <polyline :points="utilPoints()" fill="none" stroke="var(--accent)" stroke-width="1.5" />
          </svg>
          <div v-else class="muted">暂无巡检数据（等待自动巡检或点机器卡片上的「测试连接」）</div>
          <button class="btn-mini" @click="openDetail(detail)">刷新巡检</button>
        </section>

        <section class="drawer-section">
          <h4>模型目录</h4>
          <div class="model-add">
            <input v-model="newModelPath" placeholder="手动登记模型目录，如 /data/models/Qwen3-32B" @keydown.enter="addModelDir" />
            <button class="btn-mini" @click="addModelDir">登记</button>
          </div>
          <ul class="dir-list">
            <li v-for="d in modelDirs" :key="d.id">
              <code>{{ d.path }}</code>
              <span class="dir-src">{{ d.source === 'scan' ? '扫描' : '手动' }}</span>
              <button class="btn-mini" @click="removeModelDir(d.id)">删</button>
            </li>
            <li v-if="modelDirs.length === 0" class="muted">无（配置 model_root 后巡检自动扫描）</li>
          </ul>
        </section>

        <section class="drawer-section">
          <h4>容器镜像（{{ images.length }}）</h4>
          <ul class="dir-list">
            <li v-for="i in images" :key="i.id"><code>{{ i.full_name }}</code></li>
            <li v-if="images.length === 0" class="muted">无（巡检时自动扫描 docker images）</li>
          </ul>
        </section>

        <section class="drawer-section">
          <h4>快速命令（宿主机，一次性）</h4>
          <div class="model-add">
            <input v-model="quickCmd" placeholder="如 npu-smi info" @keydown.enter="runQuickCmd" />
            <button class="btn-mini" @click="runQuickCmd">执行</button>
          </div>
          <div v-if="quickJobId" class="log-inline">
            <LogViewer :job-id="quickJobId" />
          </div>
        </section>
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
  font-family: 'SF Mono', Menlo, monospace; font-size: 11px; resize: vertical;
}
.key-textarea:focus { outline: none; border-color: var(--amber); }
.key-file-row { display: flex; align-items: center; gap: var(--space-2); }
</style>
