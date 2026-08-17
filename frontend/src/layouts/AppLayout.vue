<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { useTasksStore } from '@/stores/tasks'
import UiToastHost from '@/components/ui/UiToastHost.vue'

const auth = useAuthStore()
const toast = useToastStore()
const tasksStore = useTasksStore()
const route = useRoute()

const sidebarOpen = ref(false) // 移动端抽屉

interface NavItem {
  to: string
  label: string
  icon: string
  badgeKey?: 'awaiting' | 'pending'
  match: (path: string) => boolean
}

const navItems: NavItem[] = [
  { to: '/', label: '仪表盘', icon: 'bi-grid-1x2-fill', match: (p) => p === '/' },
  { to: '/tasks', label: '任务列表', icon: 'bi-collection-play-fill', match: (p) => p.startsWith('/tasks') },
  { to: '/review', label: '人工审核', icon: 'bi-patch-check-fill', match: (p) => p.startsWith('/review') },
  { to: '/monitor', label: 'YouTube 监控', icon: 'bi-broadcast-pin', match: (p) => p.startsWith('/monitor') },
  { to: '/settings', label: '设置中心', icon: 'bi-sliders2', match: (p) => p.startsWith('/settings') },
]

const pageTitle = computed(() => {
  const meta = route.meta
  const t = typeof meta.title === 'string' ? meta.title : ''
  return t || 'Y2A-Auto'
})

function isActive(item: NavItem): boolean {
  return item.match(route.path)
}

async function onLogout() {
  await auth.logout()
  toast.info('已退出登录')
  window.location.href = '/ui/'
}

// 监听 401 事件：会话失效回登录页
function onUnauthorized() {
  auth.authenticated = false
  if (!route.path.startsWith('/login')) {
    toast.warning('登录状态已失效', '请重新登录')
    window.location.href = '/ui/login'
  }
}

onMounted(() => {
  window.addEventListener('auth:unauthorized', onUnauthorized)
  // 全局任务实时流：布局挂载期间保持连接
  tasksStore.connectStream()
})
onBeforeUnmount(() => {
  window.removeEventListener('auth:unauthorized', onUnauthorized)
  tasksStore.disconnectStream()
})
</script>

<template>
  <div class="app-shell">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ 'sidebar--open': sidebarOpen }">
      <div class="sidebar-brand">
        <div class="brand-logo">
          <i class="bi bi-play-btn-fill"></i>
        </div>
        <div class="brand-text">
          <span class="brand-name">Y2A-Auto</span>
          <span class="brand-sub">搬运控制台</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div class="nav-section-label">导航</div>
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: isActive(item) }"
          @click="sidebarOpen = false"
        >
          <i class="bi nav-item-icon" :class="item.icon"></i>
          <span class="nav-item-label">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <div class="sidebar-user">
          <div class="user-avatar"><i class="bi bi-person-fill"></i></div>
          <div class="user-meta">
            <div class="user-name">本机管理员</div>
            <div class="user-status"><span class="status-dot"></span>运行中</div>
          </div>
        </div>
        <button class="btn btn-ghost btn-sm logout-btn" @click="onLogout">
          <i class="bi bi-box-arrow-right"></i> 退出登录
        </button>
      </div>
    </aside>

    <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false"></div>

    <!-- 主区域 -->
    <div class="main-col">
      <header class="topbar">
        <button class="btn-icon topbar-menu" aria-label="打开导航" @click="sidebarOpen = !sidebarOpen">
          <i class="bi bi-list"></i>
        </button>
        <h2 class="topbar-title">{{ pageTitle }}</h2>
        <div class="topbar-spacer"></div>
        <RouterLink to="/tasks" class="btn btn-primary btn-sm topbar-add">
          <i class="bi bi-plus-lg"></i> 新建任务
        </RouterLink>
      </header>

      <main class="content">
        <RouterView />
      </main>
    </div>

    <UiToastHost />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}

/* ---- 侧边栏 ---- */
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  background: #0c111a;
  border-right: 1px solid var(--border-subtle);
  z-index: 1050;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 16px 18px;
  height: var(--topbar-height);
  border-bottom: 1px solid var(--border-subtle);
}
.brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--accent-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 1.05rem;
  box-shadow: 0 2px 10px var(--accent-glow);
  flex-shrink: 0;
}
.brand-name {
  display: block;
  font-weight: 700;
  font-size: var(--fs-lg);
  letter-spacing: -0.01em;
  line-height: 1.15;
}
.brand-sub {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
}

.sidebar-nav {
  flex: 1;
  padding: var(--sp-4) 12px;
  overflow-y: auto;
}
.nav-section-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  padding: 0 10px 8px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 10px;
  margin-bottom: 2px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-md);
  font-weight: 500;
  color: var(--text-secondary);
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.nav-item:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.nav-item.active {
  color: var(--text-primary);
  background: var(--accent-soft);
}
.nav-item.active .nav-item-icon {
  color: var(--accent);
}
.nav-item-icon {
  width: 18px;
  text-align: center;
  font-size: 0.95rem;
  flex-shrink: 0;
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: 12px;
  width: 3px;
  height: 22px;
  border-radius: var(--radius-full);
  background: var(--accent);
}
.nav-item {
  position: relative;
}

.sidebar-footer {
  padding: var(--sp-3) var(--sp-4);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.sidebar-user {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-raised);
  border: 1px solid var(--border-default);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  font-size: 0.9rem;
}
.user-name {
  font-size: var(--fs-sm);
  font-weight: 600;
}
.user-status {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 5px;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}
.logout-btn {
  width: 100%;
  justify-content: center;
}

/* ---- 主栏 ---- */
.main-col {
  flex: 1;
  min-width: 0;
  margin-left: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 1020;
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-6);
  background: rgba(10, 14, 21, 0.82);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border-subtle);
}
.topbar-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}
.topbar-spacer {
  flex: 1;
}
.topbar-menu {
  display: none;
}

.content {
  flex: 1;
  padding: var(--sp-6);
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
}

.sidebar-backdrop {
  display: none;
}

/* ---- 响应式 ---- */
@media (max-width: 900px) {
  .sidebar {
    transform: translateX(-100%);
    transition: transform var(--dur) var(--ease);
  }
  .sidebar--open {
    transform: translateX(0);
    box-shadow: var(--shadow-pop);
  }
  .sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 1040;
    background: rgba(4, 7, 12, 0.6);
  }
  .main-col {
    margin-left: 0;
  }
  .topbar-menu {
    display: inline-flex;
  }
  .topbar {
    padding: 0 var(--sp-4);
  }
  .content {
    padding: var(--sp-4);
  }
}
</style>
