import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/overview',
  },
  {
    path: '/overview',
    name: 'overview',
    component: () => import('@/views/OverviewView.vue'),
    meta: { title: '总览' },
  },
  // 旧页面路由重定向（三页已合并为总览页）
  { path: '/community', redirect: '/overview' },
  { path: '/watchlist', redirect: '/overview' },
  { path: '/pr-center', redirect: '/overview' },
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
  {
    path: '/npu-machines',
    name: 'npu-machines',
    component: () => import('@/views/NpuMachinesView.vue'),
    meta: { title: 'NPU 机器' },
  },
  {
    path: '/npu-jobs',
    name: 'npu-jobs',
    component: () => import('@/views/NpuJobsView.vue'),
    meta: { title: '任务中心' },
  },
  {
    path: '/npu-services',
    name: 'npu-services',
    component: () => import('@/views/NpuServicesView.vue'),
    meta: { title: '服务部署' },
  },
  {
    path: '/npu-testing',
    name: 'npu-testing',
    component: () => import('@/views/NpuTestingView.vue'),
    meta: { title: '测试压测' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router