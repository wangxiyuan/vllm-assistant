<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const appStore = useAppStore()

const viewTitles: Record<string, string> = {
  'community': '社区动态',
  'watchlist': '特别关注',
  'pr-center': '贡献面板',
  'personal-todo': '任务面板',
  'intelligence': '洞察面板',
  'articles': '技术Blog',
  'anatomy': '模型拆解',
  'ai-agent': 'AI Agent',
}

const viewPlaceholders: Record<string, string> = {
  'community': '搜索 Issues 和 PRs…',
  'watchlist': '搜索关注项…',
  'pr-center': '搜索你的 PR 和 Issue…',
}

const searchSupportedRoutes = new Set(['community', 'watchlist', 'pr-center'])

const currentTitle = viewTitles[route.name as string] || ''
const searchPlaceholder = viewPlaceholders[route.name as string] || '搜索…'
const showSearch = searchSupportedRoutes.has(route.name as string)
</script>

<template>
  <header class="header">
    <div class="header-left">
      <button class="hamburger" @click="appStore.mobileMenuOpen = true" title="菜单">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
      <h1 class="header-title">{{ currentTitle }}</h1>
    </div>
    <div v-if="showSearch" class="header-center">
      <div class="search-bar">
        <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input type="text" v-model="appStore.searchQuery"
               :placeholder="searchPlaceholder" />
        <span class="search-kbd">/</span>
      </div>
    </div>
    <div class="header-actions">
      <div class="sync-status">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
        <span class="sync-text">{{ appStore.syncStatusText }}</span>
        <span v-if="appStore.nextSyncCountdown" class="sync-countdown">{{ appStore.nextSyncCountdown }}</span>
      </div>
      <button class="header-btn" @click="appStore.refreshAll()" title="手动同步 (R)">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
      </button>
    </div>
  </header>
</template>