<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useUsersStore } from '@/stores/users'
import { useReposStore } from '@/stores/repos'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()
const usersStore = useUsersStore()
const reposStore = useReposStore()

interface NavItem {
  name: string
  label: string
  kbd: string
  icon: string
}

interface NavGroup {
  label: string
  expanded: boolean
  items: NavItem[]
}

const navGroups = ref<NavGroup[]>([
  {
    label: '社区',
    expanded: true,
    items: [
      { name: 'community', label: '社区动态', kbd: '1', icon: 'M22 12h-4l-3 9L9 3l-3 9H2' },
      { name: 'watchlist', label: '特别关注', kbd: '2', icon: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z' },
      { name: 'pr-center', label: '贡献面板', kbd: '3', icon: 'M9 17 4 12 9 7M20 18v-2a4 4 0 0 0-4-4H4' },
    ],
  },
  {
    label: '任务',
    expanded: true,
    items: [
      { name: 'personal-todo', label: '任务面板', kbd: '4', icon: 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11' },
    ],
  },
  {
    label: '知识',
    expanded: true,
    items: [
      { name: 'intelligence', label: '洞察面板', kbd: '5', icon: 'M11 11a8 8 0 1 0 0-16 8 8 0 0 0 0 16M21 21l-4.35-4.35' },
      { name: 'articles', label: '技术Blog', kbd: '6', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8' },
      { name: 'anatomy', label: '模型拆解', kbd: '7', icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' },
    ],
  },
  {
    label: 'AI 助手',
    expanded: true,
    items: [
      { name: 'ai-agent', label: 'AI Agent', kbd: '8', icon: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z' },
    ],
  },
])

function toggleGroup(index: number) {
  navGroups.value[index].expanded = !navGroups.value[index].expanded
}

function navigate(name: string) {
  router.push({ name })
  appStore.mobileMenuOpen = false
}
</script>

<template>
  <Teleport to="body">
    <div v-if="appStore.mobileMenuOpen" class="mobile-overlay" @click="appStore.mobileMenuOpen = false">
      <div class="mobile-sidebar" @click.stop>
        <div class="brand">
          <div class="brand-mark">
            <span class="brand-logo">vLLM</span>
          </div>
          <div class="brand-name">Assistant</div>
          <div class="brand-sub">贡献者控制台</div>
        </div>
        <nav class="nav-section">
          <template v-for="(group, idx) in navGroups" :key="group.label">
            <div class="nav-group-header" @click="toggleGroup(idx)">
              <svg class="nav-group-arrow" :class="{ expanded: group.expanded }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="9 18 15 12 9 6" />
              </svg>
              <span class="nav-group-label">{{ group.label }}</span>
            </div>
            <div v-show="group.expanded" class="nav-group-items">
              <button v-for="item in group.items" :key="item.name"
                      class="nav-item" :class="{ active: route.name === item.name }"
                      @click="navigate(item.name)">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path :d="item.icon" />
                </svg>
                <span class="nav-kbd">{{ item.kbd }}</span><span>{{ item.label }}</span>
              </button>
            </div>
          </template>
          <button class="nav-item" @click="usersStore.openManager(); appStore.mobileMenuOpen = false">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            <span>用户管理</span>
          </button>
          <button class="nav-item" @click="reposStore.openManager(); appStore.mobileMenuOpen = false">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="13" r="3" />
              <path d="M4 19.5v-4.38a7 7 0 0 1 6-6.93V6.5" />
              <path d="M20 19.5v-4.38a7 7 0 0 0-6-6.93V6.5" />
              <path d="M12 3v3.5" />
              <line x1="3" y1="21" x2="21" y2="21" />
            </svg>
            <span>仓库管理</span>
          </button>
        </nav>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.nav-group-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  margin-top: 4px;
  cursor: pointer;
  user-select: none;
}
.nav-group-header:active {
  opacity: 0.7;
}

.nav-group-arrow {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  transition: transform 0.2s;
}
.nav-group-arrow.expanded {
  transform: rotate(90deg);
}

.nav-group-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-tertiary);
}

.nav-group-items {
  overflow: hidden;
}
</style>
