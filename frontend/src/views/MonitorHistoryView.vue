<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { monitorApi } from '@/api/endpoints'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import { formatDbTime } from '@/composables/taskMeta'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiConfirm from '@/components/ui/UiConfirm.vue'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()

const configId = computed(() => Number(route.params.configId))
const history = ref<Record<string, unknown>[]>([])
const config = ref<Record<string, unknown> | null>(null)
const stats = ref({ total_records: 0, added_to_tasks: 0, avg_views: 0, avg_likes: 0 })
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const res = (await monitorApi.history(configId.value)) as unknown as {
      history: Record<string, unknown>[]; config: Record<string, unknown> | null;
      stats: { total_records: number; added_to_tasks: number; avg_views: number; avg_likes: number }
    }
    history.value = res.history ?? []
    config.value = res.config
    stats.value = res.stats
  } catch (e) {
    toast.error('加载历史记录失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const adding = ref<Set<string>>(new Set())

async function addToTasks(video: Record<string, unknown>) {
  const videoId = String(video.video_id)
  if (adding.value.has(videoId)) return
  adding.value.add(videoId)
  try {
    const r = await monitorApi.addToTasks(configId.value, [videoId])
    toast.success(r.message || '已加入任务队列')
    load()
  } catch (e) {
    toast.error('加入任务失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    adding.value.delete(videoId)
  }
}

const confirmState = ref<{ open: boolean; title: string; message: string; action: () => Promise<unknown> } | null>(null)

function askClear() {
  confirmState.value = {
    open: true,
    title: '清空历史记录',
    message: '确定要清空该监控配置的全部发现历史吗？',
    action: async () => {
      await monitorApi.clearHistory(configId.value)
      toast.success('历史记录已清空')
      load()
    },
  }
}

async function runConfirm() {
  if (!confirmState.value) return
  try {
    await confirmState.value.action()
    confirmState.value = null
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
    confirmState.value = null
  }
}

function formatViews(v: unknown): string {
  const n = Number(v ?? 0)
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  return String(n)
}

function formatTime(dt?: string): string {
  return formatDbTime(dt)
}

function videoUrl(video: Record<string, unknown>): string {
  return `https://www.youtube.com/watch?v=${video.video_id}`
}
</script>

<template>
  <div>
    <div class="page-header">
      <div class="page-header-text">
        <div class="flex items-center gap-2">
          <button class="btn-icon" aria-label="返回" @click="router.push('/monitor')">
            <i class="bi bi-arrow-left"></i>
          </button>
          <h1 class="page-title">监控历史</h1>
        </div>
        <p class="page-subtitle">
          {{ config?.name ?? `配置 #${configId}` }} · 共 {{ stats.total_records }} 条记录 ·
          已入队 {{ stats.added_to_tasks }} · 平均播放 {{ formatViews(stats.avg_views) }}
        </p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" @click="router.push(`/monitor/config/${configId}`)">
          <i class="bi bi-pencil-square"></i> 编辑配置
        </button>
        <button class="btn btn-danger btn-sm" @click="askClear">
          <i class="bi bi-trash3"></i> 清空历史
        </button>
      </div>
    </div>

    <div v-if="loading" class="card card-pad">
      <UiSkeleton :rows="8" />
    </div>
    <div v-else-if="!history.length" class="card">
      <UiEmpty
        icon="bi-clock-history"
        title="暂无发现记录"
        description="执行一次监控后，抓取到的视频会记录在这里。"
      >
        <button class="btn btn-primary btn-sm mt-3" @click="router.push('/monitor')">返回监控</button>
      </UiEmpty>
    </div>
    <div v-else class="card table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>视频</th>
            <th class="ta-center">类型</th>
            <th class="ta-right">播放</th>
            <th class="ta-right">点赞</th>
            <th class="ta-right">评论</th>
            <th class="ta-center">时长</th>
            <th class="ta-center">发布时间</th>
            <th class="ta-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(v, i) in history" :key="i">
            <td style="max-width: 340px">
              <div class="clamp-1" :title="String(v.video_title)">{{ v.video_title }}</div>
              <div class="fs-xs text-muted">{{ v.channel_title }}</div>
            </td>
            <td class="ta-center">
              <span class="badge badge-secondary">{{ v.video_type }}</span>
            </td>
            <td class="ta-right mono">{{ formatViews(v.view_count) }}</td>
            <td class="ta-right mono">{{ formatViews(v.like_count) }}</td>
            <td class="ta-right mono">{{ formatViews(v.comment_count) }}</td>
            <td class="ta-center mono text-muted">{{ v.duration ?? '—' }}</td>
            <td class="ta-center text-muted fs-sm">{{ formatTime(v.published_at as string) }}</td>
            <td class="ta-right">
              <div class="flex gap-2 justify-end items-center">
                <a class="btn-icon" :href="videoUrl(v)" target="_blank" rel="noopener" aria-label="在 YouTube 打开">
                  <i class="bi bi-box-arrow-up-right"></i>
                </a>
                <button
                  v-if="!v.added_to_tasks"
                  class="btn btn-primary btn-sm"
                  :disabled="adding.has(String(v.video_id))"
                  @click="addToTasks(v)"
                >
                  <span v-if="adding.has(String(v.video_id))" class="spinner spinner-sm"></span>
                  加入任务
                </button>
                <span v-else class="badge badge-success">已入队</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

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
.ta-center { text-align: center; }
.ta-right { text-align: right; }
.clamp-1 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
