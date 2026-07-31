import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', () => {
  const authenticated = ref(false)
  const token = ref('')
  const authError = ref('')

  async function init() {
    // Check debug mode
    try {
      const healthRes = await fetch('/health')
      if (healthRes.ok) {
        const healthData = await healthRes.json()
        if (healthData.debug) {
          authenticated.value = true
          return
        }
      }
    } catch (_) {}

    // Check saved token
    const saved = localStorage.getItem('vllm_auth_token')
    if (saved) {
      token.value = saved
      try {
        const res = await fetch('/health', {
          headers: { 'Authorization': 'Bearer ' + saved },
        })
        if (res.ok) {
          authenticated.value = true
        } else {
          localStorage.removeItem('vllm_auth_token')
        }
      } catch (_) {
        localStorage.removeItem('vllm_auth_token')
      }
    }
  }

  async function doLogin() {
    authError.value = ''
    const t = token.value.trim()
    if (!t) return
    try {
      const res = await fetch('/health', {
        headers: { 'Authorization': 'Bearer ' + t },
      })
      if (res.ok) {
        localStorage.setItem('vllm_auth_token', t)
        authenticated.value = true
      } else {
        authError.value = '密钥无效，请重试'
      }
    } catch (_) {
      authError.value = '无法连接服务器'
    }
  }

  function logout() {
    localStorage.removeItem('vllm_auth_token')
    authenticated.value = false
    token.value = ''
  }

  return { authenticated, token, authError, init, doLogin, logout }
})