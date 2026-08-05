import { useAuthStore } from '@/stores/auth'

const API_TIMEOUT = 90000

export async function api<T = any>(
  path: string,
  options: RequestInit & { timeout?: number } = {},
  _timeoutArg?: number | (RequestInit & { timeout?: number }),
): Promise<T> {
  const authStore = useAuthStore()
  const controller = new AbortController()
  let timeout = API_TIMEOUT

  if (typeof _timeoutArg === 'number') {
    timeout = _timeoutArg
  } else if (_timeoutArg && typeof _timeoutArg === 'object' && 'timeout' in _timeoutArg) {
    timeout = (_timeoutArg as any).timeout
  } else if (options.timeout) {
    timeout = options.timeout
  }

  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (authStore.token) {
      headers['Authorization'] = `Bearer ${authStore.token}`
    }

    const { timeout: _t, ...fetchOptions } = options
    const res = await fetch(path, {
      ...fetchOptions,
      headers: { ...headers, ...(fetchOptions.headers as Record<string, string>) },
      signal: controller.signal,
    })

    if (res.status === 401) {
      authStore.logout()
      throw new Error('未授权，请重新登录')
    }
    if (!res.ok) {
      let detail = res.statusText
      try {
        const data = await res.json()
        detail = data.detail || detail
      } catch {}
      throw new Error(detail)
    }
    return res.json()
  } catch (e: any) {
    if (e.name === 'AbortError') throw new Error('请求超时')
    throw e
  } finally {
    clearTimeout(timer)
  }
}