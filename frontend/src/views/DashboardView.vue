<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { dashboardApi, healthApi } from '@/api/endpoints'
import type { DashboardPayload, SystemHealthPayload } from '@/api/types'
import UiStatCard from '@/components/ui/UiStatCard.vue'
import TaskStatusBadge from '@/components/ui/TaskStatusBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiModal from '@/components/ui/UiModal.vue'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toast'
import { formatRelativeTime } from '@/composables/taskMeta'

const tasksStore = useTasksStore()
const toast = useToastStore()

const showGuide = ref(false)

const data = ref<DashboardPayload | null>(null)
const loading = ref(true)
const health = ref<SystemHealthPayload | null>(null)

async function load() {
  try {
    data.value = await dashboardApi.get()
  } catch (e) {
    toast.error('加载仪表盘失败', (e as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadHealth() {
  try {
    health.value = (await healthApi.get()) as SystemHealthPayload
  } catch {
    /* 健康检查失败不阻塞页面 */
  }
}

const healthItems = computed(() => {
  const tools = health.value?.runtime_tools ?? {}
  const items: { label: string; status: string; text: string }[] = []
  if (tools.ffmpeg) items.push({ label: 'FFmpeg', status: tools.ffmpeg.status ?? 'unknown', text: tools.ffmpeg.path ? '已就绪' : '未安装' })
  if (tools.vad) items.push({ label: 'VAD 语音分段', status: tools.vad.status ?? 'unknown', text: tools.vad.message ?? '' })
  if (tools.asr) items.push({ label: '语音识别', status: tools.asr.status ?? 'unknown', text: tools.asr.message ?? '' })
  if (tools.disk) items.push({ label: '磁盘剩余', status: tools.disk.status ?? 'unknown', text: `${tools.disk.free_gb ?? '?'} GB` })
  return items
})

function onTasksChanged() {
  load()
}

onMounted(() => {
  load()
  loadHealth()
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
        <button class="btn btn-ghost btn-sm" @click="showGuide = true">
          <i class="bi bi-ui-checks-grid"></i> 快速入门
        </button>
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

    <!-- 系统环境 -->
    <div class="card env-card">
      <div class="card-header">
        <div class="card-title"><i class="bi bi-pc-display"></i> 系统环境</div>
        <button v-if="health" class="btn btn-ghost btn-sm" title="重新检查" @click="loadHealth">
          <i class="bi bi-arrow-clockwise"></i>
        </button>
      </div>
      <div class="env-items">
        <div v-for="item in healthItems" :key="item.label" class="env-item">
          <span class="env-dot" :class="`env-dot--${item.status}`"></span>
          <span class="env-label">{{ item.label }}</span>
          <span class="env-text">{{ item.text || '—' }}</span>
        </div>
        <div v-if="!healthItems.length" class="env-empty text-muted fs-sm">环境信息不可用</div>
      </div>
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

    <!-- 快速入门引导 -->
    <UiModal :open="showGuide" title="快速入门" size="md" @close="showGuide = false">
      <div class="guide-steps">
        <div class="guide-step">
          <div class="guide-step-title"><span class="guide-no">1</span> 准备工作</div>
          <ul>
            <li>确保已在「设置中心」配置目标投稿平台账号（AcFun / bilibili）</li>
            <li>如需 AI 功能，配置 OpenAI API Key</li>
            <li>如需内容审核，配置阿里云内容安全 API</li>
          </ul>
        </div>
        <div class="guide-step">
          <div class="guide-step-title"><span class="guide-no">2</span> 添加任务</div>
          <ul>
            <li>进入「任务列表」页面，点击「新建任务」</li>
            <li>粘贴 YouTube 视频 / 播放列表 URL</li>
          </ul>
        </div>
        <div class="guide-step">
          <div class="guide-step-title"><span class="guide-no">3</span> 自动处理</div>
          <ul>
            <li>系统自动下载视频内容</li>
            <li>AI 自动翻译标题与简介、生成标签并推荐分区</li>
            <li>按配置执行内容安全审核</li>
          </ul>
        </div>
        <div class="guide-step">
          <div class="guide-step-title"><span class="guide-no">4</span> 审核与上传</div>
          <ul>
            <li>审核通过的任务自动上传</li>
            <li>需人工处理时在「人工审核」页修改内容</li>
            <li>修改后可「强制上传」立即发布</li>
          </ul>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-primary" @click="showGuide = false">了解了</button>
      </template>
    </UiModal>
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

/* 系统环境 */
.env-card {
  margin-top: var(--sp-5);
}
.env-items {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-6);
  padding: var(--sp-4);
}
.env-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
}
.env-label {
  color: var(--text-secondary);
}
.env-text {
  color: var(--text-primary);
}
.env-empty {
  padding: var(--sp-2) 0;
}
.env-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.env-dot--ok { background: var(--success); box-shadow: 0 0 6px var(--success); }
.env-dot--warn { background: var(--warning); }
.env-dot--missing, .env-dot--disabled { background: var(--text-muted); }
.env-dot--error, .env-dot--unknown { background: var(--danger); }

/* 快速入门 */
.guide-steps {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.guide-step-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-weight: 600;
  font-size: var(--fs-md);
  margin-bottom: var(--sp-1);
}
.guide-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--accent-gradient);
  color: #fff;
  font-size: var(--fs-xs);
  flex-shrink: 0;
}
.guide-step ul {
  margin: 0;
  padding-left: 30px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.guide-step li {
  color: var(--text-secondary);
  font-size: var(--fs-sm);
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
