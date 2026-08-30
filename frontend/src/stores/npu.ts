/**
 * NPU 算力管理 - 机器与任务中心
 *
 * 机器纳管/巡检、远程任务（提交/列表/日志增量轮询/停止）、容器模板。
 * 日志轮询模式仿 stores/intel.ts 的 setTimeout 递归轮询。
 */
import { defineStore } from 'pinia'
import { api } from '@/api/client'

export interface NpuMachine {
  id: number
  name: string
  host: string
  port: number
  username: string
  auth_type: 'key' | 'password'
  key_path: string | null
  has_password: boolean
  machine_type: string
  workdir: string
  model_root: string | null
  tags: string[]
  status: 'online' | 'offline' | 'unknown'
  status_message: string | null
  last_check_at: string | null
  npu_count: number | null
  npu_chip: string | null
  driver_version: string | null
  enabled: boolean
}

export interface NpuJob {
  id: number
  machine_id: number
  type: string
  mode: 'persistent' | 'oneshot'
  name: string
  payload: { docker_cmd?: string; command?: string; image?: string; [k: string]: any }
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  exit_code: number | null
  container_name: string | null
  log_file: string | null
  log_size: number
  error_message: string | null
  source: 'ui' | 'agent'
  service_id: number | null
  test_case_id: number | null
  benchmark_id: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface NpuContainerTemplate {
  id: number
  name: string
  mode: 'persistent' | 'oneshot'
  machine_type: string | null
  image: string | null
  devices: number[] | null
  mounts: string[] | null
  env: Record<string, string> | null
  network: string
  ports: string[] | null
  command: string | null
  shm_size: string | null
  notes: string | null
}

export interface MachineMetric {
  ts: string
  npu_util: number[]
  npu_mem_used: number[]
  npu_mem_total: number[]
  temperature: number[]
  power: number[]
  cpu: number | null
  mem: number | null
  disk: number | null
}

export interface MachineModelDir { id: number; path: string; note: string | null; source: string }
export interface MachineImage { id: number; full_name: string; source: string }

export interface JobSpecDraft {
  machine_id: number | null
  mode: 'persistent' | 'oneshot'
  name: string
  image: string
  device_ids: number[] | null
  mounts: string[]
  env: Record<string, string>
  network: 'host' | 'bridge'
  ports: string[]
  command: string
  shm_size: string
  extra_devices: string[]
  timeout: number | null
}

export const useNpuStore = defineStore('npu', {
  state: () => ({
    machines: [] as NpuMachine[],
    profileOptions: [] as { value: string; label: string; npu_count: number | null; notes: string; default_image: string }[],
    jobs: [] as NpuJob[],
    templates: [] as NpuContainerTemplate[],
    loading: false,
  }),

  getters: {
    onlineCount: (s) => s.machines.filter(m => m.status === 'online').length,
    machineName: (s) => (id: number) => s.machines.find(m => m.id === id)?.name || `#${id}`,
    runningJobs: (s) => s.jobs.filter(j => j.status === 'running' || j.status === 'pending'),
  },

  actions: {
    async fetchMachines() {
      this.machines = await api<NpuMachine[]>('/api/npu/machines')
    },
    async fetchProfileOptions() {
      this.profileOptions = await api('/api/npu/machines/profile-options')
    },
    async saveMachine(payload: Record<string, any>) {
      if (payload.id) {
        await api(`/api/npu/machines/${payload.id}`, { method: 'PUT', body: JSON.stringify(payload) })
      } else {
        await api('/api/npu/machines', { method: 'POST', body: JSON.stringify(payload) })
      }
      await this.fetchMachines()
    },
    async deleteMachine(id: number) {
      await api(`/api/npu/machines/${id}`, { method: 'DELETE' })
      await this.fetchMachines()
    },
    async testMachine(id: number) {
      return api(`/api/npu/machines/${id}/test`, { method: 'POST' }, 180000) as Promise<{ ok: boolean; message: string }>
    },
    async refreshMachine(id: number) {
      return api(`/api/npu/machines/${id}/refresh`, { method: 'POST' }, 180000) as Promise<{ ok: boolean }>
    },
    async fetchMachineMetrics(id: number, hours = 24): Promise<MachineMetric[]> {
      return api(`/api/npu/machines/${id}/metrics?hours=${hours}`)
    },
    async fetchMachineImages(id: number): Promise<MachineImage[]> {
      return api(`/api/npu/machines/${id}/images`)
    },
    async fetchMachineModels(id: number): Promise<MachineModelDir[]> {
      return api(`/api/npu/machines/${id}/models`)
    },
    async fetchMachineNpus(id: number): Promise<{ machine_id: number; total: number; occupied: Record<string, string> }> {
      return api(`/api/npu/machines/${id}/npus`)
    },
    async addMachineModel(id: number, path: string, note = '') {
      await api(`/api/npu/machines/${id}/models`, { method: 'POST', body: JSON.stringify({ path, note }) })
      return this.fetchMachineModels(id)
    },
    async deleteMachineModel(machineId: number, modelDirId: number) {
      await api(`/api/npu/machines/${machineId}/models/${modelDirId}`, { method: 'DELETE' })
      return this.fetchMachineModels(machineId)
    },
    async fetchSshInfo(id: number): Promise<{ ssh_cmd: string; ssh_config: string; exec_hint: string }> {
      return api(`/api/npu/machines/${id}/ssh-info`)
    },

    // ---- 任务 ----
    async fetchJobs(filters: Record<string, any> = {}) {
      const qs = new URLSearchParams()
      Object.entries(filters).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '') qs.set(k, String(v)) })
      this.jobs = await api(`/api/npu/jobs?${qs.toString()}`)
    },
    async previewCommand(spec: Record<string, any>): Promise<{ docker_cmd: string; image: string }> {
      return api('/api/npu/jobs/preview', { method: 'POST', body: JSON.stringify(spec) }, 30000)
    },
    async createJob(spec: Record<string, any>): Promise<NpuJob> {
      const job = await api<NpuJob>('/api/npu/jobs', { method: 'POST', body: JSON.stringify(spec) })
      await this.fetchJobs()
      return job
    },
    async stopJob(id: number) {
      await api(`/api/npu/jobs/${id}/stop`, { method: 'POST' })
      await this.fetchJobs()
    },
    async fetchTemplates() {
      this.templates = await api<NpuContainerTemplate[]>('/api/npu/jobs/templates')
    },
    async createTemplate(payload: Record<string, any>) {
      await api('/api/npu/jobs/templates', { method: 'POST', body: JSON.stringify(payload) })
      await this.fetchTemplates()
    },
    async deleteTemplate(id: number) {
      await api(`/api/npu/jobs/templates/${id}`, { method: 'DELETE' })
      await this.fetchTemplates()
    },
  },
})
