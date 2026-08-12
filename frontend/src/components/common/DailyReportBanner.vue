<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const report = ref<any>(null)
const dismissed = ref(false)

onMounted(async () => {
  if (!authStore.authenticated) return
  try {
    const data: any = await api('/api/intelligence/reports/daily/latest')
    if (data && data.report) {
      report.value = data.report
      // 检查今天是否已经关闭过
      try {
        const today = new Date().toISOString().slice(0, 10)
        const dismissedDate = localStorage.getItem('daily_report_dismissed')
        if (dismissedDate === today) {
          dismissed.value = true
        }
      } catch (_) {
        // localStorage 不可用，忽略
      }
    }
  } catch (_) {
    // silently fail
  }
})

function goToReport() {
  if (!report.value) return
  const id = report.value.id
  closeBanner()
  router.push(`/intelligence?report_id=${id}`)
}

function closeBanner() {
  dismissed.value = true
  try {
    const today = new Date().toISOString().slice(0, 10)
    localStorage.setItem('daily_report_dismissed', today)
  } catch (_) {
    // localStorage 不可用（隐私模式等），忽略
  }
}
</script>

<template>
  <div v-if="report && !dismissed" class="daily-report-banner">
    <span class="banner-icon">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
    </span>
    <span class="banner-text" @click="goToReport">
      {{ report.title }} · 点击查看今日贡献指南
    </span>
    <button class="banner-close" @click="closeBanner" title="关闭">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>
  </div>
</template>

<style scoped>
.daily-report-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: linear-gradient(135deg, #9a5b12 0%, #7a440b 100%);
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}
.daily-report-banner:hover {
  opacity: 0.92;
}
.banner-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.banner-text {
  flex: 1;
  cursor: pointer;
}
.banner-close {
  background: none;
  border: none;
  color: rgba(255,255,255,0.7);
  font-size: 16px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.banner-close:hover {
  background: rgba(255,255,255,0.15);
  color: #fff;
}
</style>