<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
</script>

<template>
  <div class="auth-overlay">
    <div class="auth-card">
      <div class="auth-brand">
        <div class="brand-mark">
          <span class="brand-logo">vLLM</span>
          <span class="brand-name">Assistant</span>
        </div>
        <div class="brand-sub">贡献者任务控制台</div>
      </div>
      <p class="auth-desc">输入 API 密钥以继续</p>
      <form @submit.prevent="authStore.doLogin()" class="auth-form">
        <div class="input-group">
          <input type="password" class="input input-lg input-mono" v-model="authStore.token"
                 placeholder="输入 API 密钥…" autofocus />
        </div>
        <p v-if="authStore.authError" class="auth-error">{{ authStore.authError }}</p>
        <button type="submit" class="btn btn-primary btn-lg auth-btn">
          进入控制台
        </button>
      </form>
    </div>
  </div>
</template>

