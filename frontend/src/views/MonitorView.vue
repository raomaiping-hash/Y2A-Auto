<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { monitorApi } from '@/api/endpoints'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import type { MonitorConfig } from '@/api/types'
import { formatDbTime } from '@/composables/taskMeta'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiConfirm from '@/components/ui/UiConfirm.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiProgress from '@/components/ui/UiProgress.vue'

const router = useRouter()
const toast = useToastStore()

const configs = ref<MonitorConfig[]>([])
const history = ref<Record<string, unknown>[]>([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const res = (await monitorApi.status()) as unknown as { configs: MonitorConfig[]; history: Record<string, unknown>[] }
    configs.value = res.configs ?? []
    history.value = res.history ?? []
  } catch (e) {
    toast.error('加载监控数据失败', (e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

/* ---- 立即执行 + 进度轮询 ---- */
const runState = ref<{ open: boolean; configId: number | null; name: string; operationId: string | null; progress: { message: string; detail: string; percent: number | null; done: boolean; success: boolean } | null }>({
  open: false,
  configId: null,
  name: '',
  operationId: null,
  progress: null,
})

let pollTimer: ReturnType<typeof setInterval> | null = null

async function runConfig(cfg: MonitorConfig) {
  try {
    const res = (await monitorApi.run(Number(cfg.id))) as unknown as { success: boolean; message?: string; operation_id?: string }
    runState.value = {
      open: true,
      configId: Number(cfg.id),
      name: String(cfg.name ?? ''),
      operationId: res.operation_id ?? null,
      progress: { message: '监控任务已启动', detail: '', percent: null, done: false, success: false },
    }
    if (!res.operation_id) {
      toast.info(res.message || '监控已启动')
      runState.value.open = false
      return
    }
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(pollRun, 1200)
  } catch (e) {
    toast.error('启动监控失败', e instanceof ApiError ? e.message : '请稍后重试')
  }
}

async function pollRun() {
  if (!runState.value.operationId) return
  try {
    const p = (await monitorApi.runStatus(runState.value.operationId)) as unknown as {
      found: boolean; message: string; detail: string; percent: number | null; done: boolean; success: boolean
    }
    if (!p.found) {
      stopPolling('监控任务状态已丢失')
      return
    }
    runState.value.progress = { message: p.message, detail: p.detail, percent: p.percent, done: p.done, success: p.success }
    if (p.done) {
      stopPolling()
      if (p.success) toast.success('监控执行完成', p.message)
      else toast.error('监控执行结束', p.message || '请查看日志')
      load()
    }
  } catch {
    stopPolling('无法获取监控进度')
  }
}

function stopPolling(message?: string) {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (message) toast.error(message)
  runState.value.open = false
  runState.value.operationId = null
}

function toggleEnabled(cfg: MonitorConfig) {
  const target = !cfg.enabled
  monitorApi.update(Number(cfg.id), { ...cfg, enabled: target })
    .then(() => {
      cfg.enabled = target
      toast.success(target ? '监控已启用' : '监控已停用')
    })
    .catch((e) => toast.error('更新失败', e instanceof ApiError ? e.message : '请稍后重试'))
}

const confirmState = ref<{ open: boolean; title: string; message: string; action: () => Promise<unknown> } | null>(null)

async function runConfirm() {
  if (!confirmState.value) return
  try {
    await confirmState.value.action()
    confirmState.value = null
    load()
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
    confirmState.value = null
  }
}

function askDelete(cfg: MonitorConfig) {
  confirmState.value = {
    open: true,
    title: '删除监控配置',
    message: `确定要删除监控配置「${cfg.name}」吗？`,
    action: async () => {
      await monitorApi.remove(Number(cfg.id))
      toast.success('监控配置已删除')
    },
  }
}

function restoreConfigs() {
  confirmState.value = {
    open: true,
    title: '恢复默认监控配置',
    message: '将根据 config 目录下的配置文件恢复监控配置，确定继续吗？',
    action: async () => {
      await monitorApi.restoreConfigs()
      toast.success('已恢复默认监控配置')
    },
  }
}

function typeLabel(t?: string): string {
  if (t === 'youtube_search') return '关键词搜索'
  if (t === 'channel_search') return '频道搜索'
  return 'YouTube 监控'
}

function formatViews(v: unknown): string {
  const n = Number(v ?? 0)
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  return String(n)
}

function formatTime(dt?: string): string {
  return formatDbTime(dt)
}
</script>

<template>
  <div>
    <div class="page-header">
      <div class="page-header-text">
        <h1 class="page-title">YouTube 监控</h1>
        <p class="page-subtitle">定时抓取频道 / 关键词新视频，自动加入搬运队列</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" @click="restoreConfigs">
          <i class="bi bi-arrow-counterclockwise"></i> 恢复默认配置
        </button>
        <button class="btn btn-primary btn-sm" @click="router.push('/monitor/config/new')">
          <i class="bi bi-plus-lg"></i> 新建监控
        </button>
      </div>
    </div>

    <div v-if="loading" class="card card-pad">
      <UiSkeleton :rows="6" />
    </div>

    <div v-else-if="!configs.length" class="card">
      <UiEmpty
        icon="bi-broadcast-pin"
        title="暂无监控配置"
        description="创建监控后，系统会按计划抓取 YouTube 视频并保存发现历史。"
      >
        <button class="btn btn-primary btn-sm mt-3" @click="router.push('/monitor/config/new')">
          <i class="bi bi-plus-lg"></i> 新建监控
        </button>
      </UiEmpty>
    </div>

    <template v-else>
      <!-- 监控配置卡片 -->
      <div class="monitor-grid">
        <div v-for="cfg in configs" :key="cfg.id" class="card monitor-card">
          <div class="monitor-card-head">
            <div class="monitor-icon" :class="{ off: !cfg.enabled }">
              <i class="bi bi-broadcast-pin"></i>
            </div>
            <div class="grow" style="min-width: 0">
              <div class="monitor-name truncate">{{ cfg.name }}</div>
              <div class="monitor-type">
                {{ typeLabel(cfg.monitor_type as string) }}
                · {{ cfg.channel_mode === 'historical' ? '历史模式' : '最新模式' }}
                · {{ cfg.schedule_type === 'manual' ? '手动' : `每 ${cfg.schedule_interval} 分钟` }}
              </div>
            </div>
            <span class="badge" :class="cfg.enabled ? 'badge-success' : 'badge-secondary'" @click="toggleEnabled(cfg)" style="cursor: pointer">
              <i class="bi" :class="cfg.enabled ? 'bi-play-fill' : 'bi-pause-fill'"></i>
              {{ cfg.enabled ? '运行中' : '已停用' }}
            </span>
          </div>

          <div class="monitor-card-body">
            <div class="monitor-meta">
              <span><i class="bi bi-clock"></i> 最近执行：{{ formatTime(cfg.last_run_time as string) }}</span>
              <span><i class="bi bi-list-ol"></i> 已发现 {{ cfg.history_count ?? 0 }} 个视频</span>
            </div>
            <div v-if="cfg.keywords" class="monitor-keywords clamp-2" :title="String(cfg.keywords)">
              关键词：{{ cfg.keywords }}
            </div>
            <div v-else-if="cfg.channel_ids" class="monitor-keywords clamp-2" :title="String(cfg.channel_ids)">
              频道：{{ cfg.channel_ids }}
            </div>
          </div>

          <div class="monitor-card-foot">
            <button class="btn btn-primary btn-sm" :disabled="!cfg.enabled" @click="runConfig(cfg)">
              <i class="bi bi-play-fill"></i> 立即执行
            </button>
            <div class="flex gap-2">
              <button class="btn btn-ghost btn-sm" @click="router.push(`/monitor/config/${cfg.id}/history`)">
                <i class="bi bi-clock-history"></i> 历史
              </button>
              <button class="btn btn-ghost btn-sm" @click="router.push(`/monitor/config/${cfg.id}`)">
                <i class="bi bi-pencil-square"></i> 编辑
              </button>
              <button class="btn-icon danger" aria-label="删除" @click="askDelete(cfg)">
                <i class="bi bi-trash3"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近发现 -->
      <div class="card mt-4">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-clock-history"></i> 最近发现</div>
        </div>
        <div v-if="!history.length" class="p-4">
          <UiEmpty icon="bi-inbox" title="暂无发现记录" description="执行监控后会在这里展示抓取到的视频。" />
        </div>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>视频</th>
                <th class="ta-center">类型</th>
                <th class="ta-right">播放</th>
                <th class="ta-right">点赞</th>
                <th class="ta-center">发布时间</th>
                <th class="ta-center">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(v, i) in history" :key="i">
                <td>
                  <div class="clamp-1" style="max-width: 420px" :title="String(v.video_title)">{{ v.video_title }}</div>
                  <div class="fs-xs text-muted">{{ v.channel_title }}</div>
                </td>
                <td class="ta-center">
                  <span class="badge badge-secondary">{{ v.video_type }}</span>
                </td>
                <td class="ta-right mono">{{ formatViews(v.view_count) }}</td>
                <td class="ta-right mono">{{ formatViews(v.like_count) }}</td>
                <td class="ta-center text-muted fs-sm">{{ formatTime(v.published_at as string) }}</td>
                <td class="ta-center">
                  <span v-if="v.added_to_tasks" class="badge badge-success">已入队</span>
                  <span v-else class="badge badge-secondary">未处理</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- 监控执行进度弹窗 -->
    <UiModal :open="runState.open" :title="`正在执行：${runState.name}`" size="sm" :close-on-backdrop="false" @close="stopPolling()">
      <div v-if="runState.progress" class="run-progress">
        <div class="run-message">{{ runState.progress.message }}</div>
        <div v-if="runState.progress.detail" class="run-detail">{{ runState.progress.detail }}</div>
        <UiProgress
          class="mt-3"
          :value="runState.progress.percent ?? 0"
          :indeterminate="runState.progress.percent === null"
          tone="accent"
        />
        <div class="flex justify-center mt-4">
          <button class="btn btn-secondary btn-sm" @click="stopPolling()">关闭</button>
        </div>
      </div>
    </UiModal>

    <UiConfirm
      :open="confirmState?.open ?? false"
      :title="confirmState?.title ?? ''"
      :message="confirmState?.message ?? ''"
      :danger="true"
      @close="confirmState = null"
      @confirm="runConfirm"
    />
  </div>
</template>

<style scoped>
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

.monitor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--sp-4);
}
.monitor-card {
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.monitor-card-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.monitor-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--accent-soft);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.05rem;
  flex-shrink: 0;
}
.monitor-icon.off {
  background: var(--bg-raised);
  color: var(--text-muted);
}
.monitor-name {
  font-size: var(--fs-lg);
  font-weight: 600;
}
.monitor-type {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  margin-top: 2px;
}
.monitor-card-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.monitor-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.monitor-keywords {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}
.monitor-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--border-subtle);
}

.ta-center { text-align: center; }
.ta-right { text-align: right; }
.clamp-1 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-message {
  font-size: var(--fs-md);
  font-weight: 600;
}
.run-detail {
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
  line-height: 1.6;
}
</style>
