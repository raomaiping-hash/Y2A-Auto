<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { dashboardApi } from '@/api/endpoints'
import type { DashboardPayload } from '@/api/types'
import UiStatCard from '@/components/ui/UiStatCard.vue'
import TaskStatusBadge from '@/components/ui/TaskStatusBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toast'
import { formatRelativeTime } from '@/composables/taskMeta'

const tasksStore = useTasksStore()
const toast = useToastStore()

const data = ref<DashboardPayload | null>(null)
const loading = ref(true)

async function load() {
  try {
    data.value = await dashboardApi.get()
  } catch (e) {
    toast.error('加载仪表盘失败', (e as Error).message)
  } finally {
    loading.value = false
  }
}

function onTasksChanged() {
  load()
}

onMounted(() => {
  load()
  window.addEventListener('tasks:changed', onTasksChanged)
})
onBeforeUnmount(() => window.removeEventListener('tasks:changed', onTasksChanged))

function formatLocal(dt?: string): string {
  return formatRelativeTime(dt)
}

function uploadLink(t: { upload_target: string; upload_id: string | null }): string | undefined {
  if (!t.upload_id) return undefined
  if (t.upload_target === 'bilibili') return `https://www.bilibili.com/video/${t.upload_id}`
  if (t.upload_target === 'both') {
    // 双平台展示文本由后端拼接，不再生成单一链接
    return undefined
  }
  return `https://www.acfun.cn/v/ac${t.upload_id}`
}
</script>

<template>
  <div>
    <div class="page-header">
      <div class="page-header-text">
        <h1 class="page-title">仪表盘</h1>
        <p class="page-subtitle">今日概览 · 实时掌握任务与转发情况</p>
      </div>
      <div class="page-actions">
        <RouterLink to="/tasks" class="btn btn-primary btn-sm">
          <i class="bi bi-plus-lg"></i> 新建任务
        </RouterLink>
        <RouterLink to="/monitor" class="btn btn-secondary btn-sm">
          <i class="bi bi-broadcast-pin"></i> 监控
        </RouterLink>
      </div>
    </div>

    <!-- KPI -->
    <div class="kpi-grid">
      <UiStatCard
        label="今日完成"
        :value="data?.stats.completed_today ?? 0"
        icon="bi-patch-check-fill"
        tone="success"
        :loading="loading"
      />
      <UiStatCard
        label="今日失败"
        :value="data?.stats.failed_today ?? 0"
        icon="bi-shield-x"
        tone="danger"
        :loading="loading"
      />
      <UiStatCard
        label="今日新增"
        :value="data?.stats.created_today ?? 0"
        icon="bi-node-plus-fill"
        tone="accent"
        :loading="loading"
      />
      <UiStatCard
        label="进行中"
        :value="data?.stats.in_progress ?? 0"
        icon="bi-lightning-charge-fill"
        tone="info"
        :loading="loading"
      />
    </div>

    <!-- 队列状态 -->
    <div class="queue-grid">
      <RouterLink to="/review" class="queue-card card queue-card--warning">
        <div class="queue-body">
          <div class="queue-icon"><i class="bi bi-hourglass-split"></i></div>
          <div>
            <div class="queue-label">待审核</div>
            <div class="queue-value">{{ data?.stats.awaiting_review ?? 0 }}</div>
          </div>
        </div>
        <i class="bi bi-chevron-right queue-arrow"></i>
      </RouterLink>
      <RouterLink to="/tasks" class="queue-card card">
        <div class="queue-body">
          <div class="queue-icon"><i class="bi bi-list-ul"></i></div>
          <div>
            <div class="queue-label">等待处理</div>
            <div class="queue-value">{{ data?.stats.pending_total ?? 0 }}</div>
          </div>
        </div>
        <i class="bi bi-chevron-right queue-arrow"></i>
      </RouterLink>
      <RouterLink to="/tasks" class="queue-card card queue-card--accent">
        <div class="queue-body">
          <div class="queue-icon"><i class="bi bi-cloud-arrow-up-fill"></i></div>
          <div>
            <div class="queue-label">准备上传</div>
            <div class="queue-value">{{ data?.stats.ready_total ?? 0 }}</div>
          </div>
        </div>
        <i class="bi bi-chevron-right queue-arrow"></i>
      </RouterLink>
      <RouterLink to="/tasks" class="queue-card card queue-card--danger">
        <div class="queue-body">
          <div class="queue-icon"><i class="bi bi-bug-fill"></i></div>
          <div>
            <div class="queue-label">失败总数</div>
            <div class="queue-value">{{ data?.stats.failed_total ?? 0 }}</div>
          </div>
        </div>
        <i class="bi bi-chevron-right queue-arrow"></i>
      </RouterLink>
    </div>

    <!-- 最近动态 -->
    <div class="card mt-4">
      <div class="card-header">
        <div class="card-title"><i class="bi bi-broadcast-pin"></i> 最近动态</div>
        <RouterLink to="/tasks" class="btn btn-ghost btn-sm">
          查看全部 <i class="bi bi-arrow-right"></i>
        </RouterLink>
      </div>
      <div v-if="loading" class="skeleton-list">
        <div v-for="i in 5" :key="i" class="skeleton" style="height: 20px"></div>
      </div>
      <div v-else-if="!data?.recent_tasks.length" class="p-4">
        <UiEmpty icon="bi-clock-history" title="暂无任务动态" description="添加第一个 YouTube 视频任务后，处理进度会显示在这里。" />
      </div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th style="width: 64px">ID</th>
              <th>标题</th>
              <th class="ta-center">状态</th>
              <th class="ta-center">平台</th>
              <th class="ta-center">更新时间</th>
              <th class="ta-right">结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in data?.recent_tasks" :key="t.id" class="row-click" @click="$router.push(`/tasks/${t.id}`)">
              <td class="mono text-muted">{{ t.id.slice(0, 6) }}…</td>
              <td class="clamp-2" style="max-width: 380px">{{ t.title }}</td>
              <td class="ta-center"><TaskStatusBadge :status="t.status" /></td>
              <td class="ta-center">
                <span class="target-chip">{{ t.upload_target === 'both' ? '双平台' : t.upload_target === 'bilibili' ? 'B站' : 'AcFun' }}</span>
              </td>
              <td class="ta-center text-muted fs-sm">{{ formatLocal(t.updated_at) }}</td>
              <td class="ta-right">
                <template v-if="t.upload_id">
                  <a
                    v-if="uploadLink(t)"
                    :href="uploadLink(t)"
                    target="_blank"
                    rel="noopener"
                    class="badge badge-success result-link"
                    @click.stop
                  >
                    {{ t.upload_id }} <i class="bi bi-box-arrow-up-right"></i>
                  </a>
                  <span v-else class="badge badge-success">{{ t.upload_id }}</span>
                </template>
                <span v-else class="badge badge-secondary">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card-footer text-muted fs-sm">
        总任务数：{{ data?.stats.total_tasks ?? 0 }}
      </div>
    </div>

    <!-- 实时状态提示 -->
    <div class="live-hint mt-3">
      <span class="live-dot" :class="{ on: tasksStore.connected }"></span>
      {{ tasksStore.connected ? '实时更新已连接' : '实时更新未连接' }}
    </div>
  </div>
</template>

<style scoped>
.page-header,
.page-title,
.page-subtitle,
.page-actions {
  /* 复用全局 PageHeader 的布局约定 */
}
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin-bottom: var(--sp-5);
}
.page-title {
  font-size: var(--fs-2xl);
  font-weight: 700;
}
.page-subtitle {
  margin-top: 4px;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.page-actions {
  display: flex;
  gap: var(--sp-3);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-4);
}
.queue-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-4);
  margin-top: var(--sp-4);
}
.queue-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-4) var(--sp-5);
  color: inherit;
  transition: border-color var(--dur) var(--ease);
}
.queue-card:hover {
  border-color: var(--border-strong);
}
.queue-body {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.queue-icon {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  background: var(--bg-raised);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  font-size: 1rem;
}
.queue-card--warning .queue-icon { background: var(--warning-soft); color: var(--warning); }
.queue-card--accent .queue-icon { background: var(--accent-soft); color: var(--accent); }
.queue-card--danger .queue-icon { background: var(--danger-soft); color: var(--danger); }
.queue-label {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.queue-value {
  font-size: var(--fs-xl);
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.queue-arrow {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.ta-center { text-align: center; }
.ta-right { text-align: right; }
.target-chip {
  display: inline-flex;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--bg-raised);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.result-link {
  text-decoration: none;
}
.row-click {
  cursor: pointer;
}
.live-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
}
.live-dot.on {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

@media (max-width: 1100px) {
  .kpi-grid,
  .queue-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 560px) {
  .kpi-grid,
  .queue-grid {
    grid-template-columns: 1fr;
  }
}
</style>
