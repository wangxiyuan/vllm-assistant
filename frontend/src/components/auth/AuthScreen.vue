<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
</script>

<template>
  <div class="auth-overlay">
    <div class="auth-card">
      <div class="auth-brand">
        <div class="brand-logo" style="font-size:18px;padding-left:18px;">vLLM</div>
        <div class="brand-name" style="font-size:28px;font-family:var(--font-display);font-weight:600;">Assistant</div>
        <div class="brand-sub" style="font-size:13px;color:var(--text-tertiary);font-family:var(--font-mono);margin-top:4px;">贡献者任务控制台</div>
      </div>
      <p class="auth-desc">输入 API 密钥以继续</p>
      <form @submit.prevent="authStore.doLogin()" class="auth-form">
        <div class="input-group">
          <input type="password" class="input input-lg" v-model="authStore.token"
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

<style scoped>
.auth-overlay {
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-base); z-index: var(--z-top);
}
.auth-card {
  background: var(--bg-elev-1); border: 1px solid var(--border-faint);
  border-radius: var(--radius-lg); padding: var(--space-9);
  width: 380px; max-width: 90vw; text-align: center;
}
.auth-brand { margin-bottom: var(--space-7); }
.auth-desc { color: var(--text-secondary); margin-bottom: var(--space-6); font-size: var(--text-sm); }
.auth-form .input-group { margin-bottom: var(--space-4); }
.auth-error { color: var(--signal-red); font-size: var(--text-sm); margin-bottom: var(--space-3); }
.auth-btn { width: 100%; }
</style>
