import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/community',
  },
  {
    path: '/community',
    name: 'community',
    component: () => import('@/views/CommunityView.vue'),
    meta: { title: '社区动态' },
  },
  {
    path: '/watchlist',
    name: 'watchlist',
    component: () => import('@/views/WatchlistView.vue'),
    meta: { title: '特别关注' },
  },
  {
    path: '/pr-center',
    name: 'pr-center',
    component: () => import('@/views/PRCenterView.vue'),
    meta: { title: '贡献面板' },
  },
  {
    path: '/personal-todo',
    name: 'personal-todo',
    component: () => import('@/views/PersonalTodoView.vue'),
    meta: { title: '任务面板' },
  },
  {
    path: '/intelligence',
    name: 'intelligence',
    component: () => import('@/views/IntelligenceView.vue'),
    meta: { title: '洞察面板' },
  },
  {
    path: '/articles',
    name: 'articles',
    component: () => import('@/views/ArticlesView.vue'),
    meta: { title: '技术Blog' },
  },
  {
    path: '/anatomy',
    name: 'anatomy',
    component: () => import('@/views/ModelAnatomyView.vue'),
    meta: { title: '模型拆解' },
  },
  {
    path: '/ai-agent',
    name: 'ai-agent',
    component: () => import('@/views/AIAgentView.vue'),
    meta: { title: 'AI Agent' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router