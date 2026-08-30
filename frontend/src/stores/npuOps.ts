/**
 * NPU 算力管理 - 服务部署 / Playground / Profiling / 用例 / benchmark
 */
import { defineStore } from 'pinia'
import { api } from '@/api/client'

export interface NpuService {
  id: number
  machine_id: number
  name: string
  model_dir: string
  model_name: string
  image: string
  container_name: string
  mounts: string[]
  env: Record<string, string>
  network: string
  ports: string[]
  devices: number[]
  tp: number
  serve_args: string | null
  debug_mode: boolean
  debugpy_port: number | null
  wait_for_client: boolean
  profiling_enabled: boolean
  profiling_dir: string | null
  health_url: string
  status: 'deploying' | 'running' | 'stopped' | 'failed' | 'unknown'
  last_health_at: string | null
  last_health_ok: boolean | null
}

export interface ProfileSession {
  id: number
  service_id: number
  machine_id: number
  status: 'collecting' | 'completed' | 'failed'
  output_dir: string
  started_at: string | null
  stopped_at: string | null
  duration_s: number | null
  files: { name: string; size: number; mtime: number | null }[]
  total_size: number
  notes: string | null
  error_message: string | null
  analysis_hint?: string
}

export interface NpuTestCase {
  id: number
  name: string
  description: string | null
  kind: 'container_cmd' | 'openai_chat'
  payload: Record<string, any>
  target: 'machine' | 'service'
  timeout_seconds: number
  enabled: boolean
}

export interface NpuTestRun {
  id: number
  case_id: number
  machine_id: number | null
  service_id: number | null
  job_id: number | null
  status: 'running' | 'passed' | 'failed' | 'error'
  duration_ms: number | null
  output_summary: string | null
  created_at: string
}

export interface NpuBenchmarkRun {
  id: number
  machine_id: number
  service_id: number | null
  job_id: number | null
  model: string
  endpoint: string
  dataset_name: string
  dataset_path: string | null
  num_prompts: number
  request_rate: number | null
  max_concurrency: number | null
  status: 'running' | 'completed' | 'failed'
  total_throughput: number | null
  output_throughput: number | null
  ttft_p50: number | null
  ttft_p99: number | null
  tpot_p50: number | null
  tpot_p99: number | null
  itl_p50: number | null
  itl_p99: number | null
  e2el_p99: number | null
  success_rate: number | null
  raw_metrics: Record<string, any>
  error_message: string | null
  created_at: string
}

export interface PlaygroundMessage {
  role: 'user' | 'assistant'
  content: string
  done?: boolean
  error?: boolean
}

export const useNpuOpsStore = defineStore('npuOps', {
  state: () => ({
    services: [] as NpuService[],
    testCases: [] as NpuTestCase[],
    testRuns: [] as NpuTestRun[],
    benchmarks: [] as NpuBenchmarkRun[],
    sessions: [] as ProfileSession[],
    loading: false,
    // Playground
    pgServiceId: null as number | null,
    pgMessages: [] as PlaygroundMessage[],
    pgStreaming: false,
  }),

  getters: {
    runningServices: (s) => s.services.filter(x => x.status === 'running'),
    serviceById: (s) => (id: number) => s.services.find(x => x.id === id),
  },

  actions: {
    // ---- 服务实例 ----
    async fetchServices() {
      this.services = await api<NpuService[]>('/api/npu/services')
    },
    async deployService(payload: Record<string, any>) {
      const res = await api<{ instance_id: number; job_id: number }>('/api/npu/services', {
        method: 'POST', body: JSON.stringify(payload),
      }, 120000)
      await this.fetchServices()
      return res
    },
    async stopService(id: number) {
      await api(`/api/npu/services/${id}/stop`, { method: 'POST' })
      await this.fetchServices()
    },
    async startService(id: number) {
      await api(`/api/npu/services/${id}/start`, { method: 'POST' }, 120000)
      await this.fetchServices()
    },
    async restartService(id: number) {
      await api(`/api/npu/services/${id}/restart`, { method: 'POST' }, 120000)
      await this.fetchServices()
    },
    async deleteService(id: number) {
      await api(`/api/npu/services/${id}`, { method: 'DELETE' })
      await this.fetchServices()
    },
    async checkHealth(id: number) {
      return api(`/api/npu/services/${id}/health`, { method: 'GET' }, 30000) as Promise<{ ok: boolean }>
    },
    async fetchDebugInfo(id: number): Promise<{ attach_host: string; attach_port: number; launch_json: any; cli_cmd: string; hint: string }> {
      return api(`/api/npu/services/${id}/debug-info`)
    },

    // ---- Playground（统一推理网关，SSE 流式）----
    async pgSend(prompt: string) {
      if (!this.pgServiceId || this.pgStreaming) return
      this.pgMessages.push({ role: 'user', content: prompt })
      const assistant: PlaygroundMessage = { role: 'assistant', content: '', done: false }
      this.pgMessages.push(assistant)
      this.pgStreaming = true
      const authStore = (await import('@/stores/auth')).useAuthStore()
      try {
        const res = await fetch(`/api/npu/services/${this.pgServiceId}/proxy/v1/chat/completions`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
          },
          body: JSON.stringify({
            model: this.serviceById(this.pgServiceId)?.model_name || 'default',
            messages: this.pgMessages.filter(m => m.done !== false || m === assistant ? true : true)
              .filter(m => m.content || m.role === 'user')
              .map(m => ({ role: m.role, content: m.content })),
            stream: true,
            max_tokens: 2048,
          }),
        })
        if (!res.ok || !res.body) {
          const detail = await res.text()
          throw new Error(detail.slice(0, 300) || `HTTP ${res.status}`)
        }
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() || ''
          for (const line of lines) {
            const t = line.trim()
            if (!t.startsWith('data:')) continue
            const data = t.slice(5).trim()
            if (data === '[DONE]') continue
            try {
              const obj = JSON.parse(data)
              const delta = obj.choices?.[0]?.delta?.content
              if (delta) assistant.content += delta
            } catch { /* 忽略半包 */ }
          }
        }
        assistant.done = true
      } catch (e: any) {
        assistant.error = true
        assistant.content += `\n[错误] ${e.message || e}`
        assistant.done = true
      } finally {
        this.pgStreaming = false
      }
    },

    // ---- Profiling ----
    async startProfile(instanceId: number, notes = '') {
      return api(`/api/npu/services/${instanceId}/profile/start`, {
        method: 'POST', body: JSON.stringify({ notes }),
      }, 120000) as Promise<{ session_id: number }>
    },
    async fetchSessions(serviceId?: number) {
      const qs = serviceId ? `?service_id=${serviceId}` : ''
      this.sessions = await api<ProfileSession[]>(`/api/npu/profiles${qs}`)
    },
    async refreshSession(id: number): Promise<ProfileSession> {
      return api(`/api/npu/profiles/${id}?refresh=true`, { method: 'GET' }, 60000)
    },
    async stopProfile(sessionId: number) {
      return api(`/api/npu/profiles/${sessionId}/stop`, { method: 'POST' }, 180000)
    },
    downloadProfileFile: async (sessionId: number, path: string) => {
      // 二进制流不走 api()（JSON 封装），单独 fetch 带 token 后转 blob 下载
      const authStore = (await import('@/stores/auth')).useAuthStore()
      const res = await fetch(`/api/npu/profiles/${sessionId}/download?path=${encodeURIComponent(path)}`, {
        headers: authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {},
      })
      if (!res.ok) throw new Error('下载失败')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = path.split('/').pop() || 'profile.bin'
      a.click()
      URL.revokeObjectURL(url)
    },

    // ---- 用例 ----
    async fetchTestCases() {
      this.testCases = await api<NpuTestCase[]>('/api/npu/test-cases')
    },
    async saveTestCase(payload: Record<string, any>) {
      if (payload.id) {
        await api(`/api/npu/test-cases/${payload.id}`, { method: 'PUT', body: JSON.stringify(payload) })
      } else {
        await api('/api/npu/test-cases', { method: 'POST', body: JSON.stringify(payload) })
      }
      await this.fetchTestCases()
    },
    async deleteTestCase(id: number) {
      await api(`/api/npu/test-cases/${id}`, { method: 'DELETE' })
      await this.fetchTestCases()
    },
    async runTestCase(id: number, machineId?: number, serviceId?: number) {
      return api(`/api/npu/test-cases/${id}/run`, {
        method: 'POST', body: JSON.stringify({ machine_id: machineId, service_id: serviceId }),
      }) as Promise<{ run_id: number }>
    },
    async fetchTestRuns(caseId?: number) {
      const qs = caseId ? `?case_id=${caseId}` : ''
      this.testRuns = await api<NpuTestRun[]>(`/api/npu/test-cases/runs${qs}`)
    },

    // ---- benchmark ----
    async fetchBenchmarks(serviceId?: number) {
      const qs = serviceId ? `?service_id=${serviceId}` : ''
      this.benchmarks = await api<NpuBenchmarkRun[]>(`/api/npu/benchmarks${qs}`)
    },
    async startBenchmark(payload: Record<string, any>) {
      return api('/api/npu/benchmarks', { method: 'POST', body: JSON.stringify(payload) }, 120000) as Promise<{ benchmark_id: number; job_id: number }>
    },
    async pollBenchmark(id: number): Promise<NpuBenchmarkRun> {
      return api(`/api/npu/benchmarks/${id}`, { method: 'GET' }, 30000)
    },
  },
})
