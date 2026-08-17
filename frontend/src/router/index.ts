import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '仪表盘' },
        },
        {
          path: 'tasks',
          name: 'tasks',
          component: () => import('@/views/TasksView.vue'),
          meta: { title: '任务列表' },
        },
        {
          path: 'tasks/:taskId',
          name: 'task-detail',
          component: () => import('@/views/TaskDetailView.vue'),
          meta: { title: '任务详情' },
        },
        {
          path: 'review',
          name: 'review',
          component: () => import('@/views/ManualReviewView.vue'),
          meta: { title: '人工审核' },
        },
        {
          path: 'monitor',
          name: 'monitor',
          component: () => import('@/views/MonitorView.vue'),
          meta: { title: 'YouTube 监控' },
        },
        {
          path: 'monitor/config/:configId',
          name: 'monitor-config',
          component: () => import('@/views/MonitorConfigView.vue'),
          meta: { title: '监控配置' },
        },
        {
          path: 'monitor/config/:configId/history',
          name: 'monitor-history',
          component: () => import('@/views/MonitorHistoryView.vue'),
          meta: { title: '监控历史' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: '设置中心' },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { title: '页面不存在' },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.booted) {
    try {
      await auth.bootstrap()
    } catch {
      /* 后端不可用时进入登录页兜底 */
      auth.booted = true
    }
  }
  if (to.meta.public) {
    // 已登录用户访问登录页 → 回仪表盘
    if (auth.authenticated) return { path: '/' }
    return true
  }
  if (auth.passwordProtectionEnabled && !auth.authenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · Y2A-Auto` : 'Y2A-Auto · 控制台'
})

export default router
