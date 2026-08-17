<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { monitorApi } from '@/api/endpoints'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiToggle from '@/components/ui/UiToggle.vue'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()

const configIdParam = computed(() => String(route.params.configId))
const isEdit = computed(() => configIdParam.value !== 'new')
const loading = ref(isEdit.value)
const submitting = ref(false)

const form = reactive({
  name: '',
  enabled: true,
  monitor_type: 'youtube_search' as string,
  channel_mode: 'latest' as string,
  region_code: 'US',
  category_id: '0',
  time_period: 7,
  max_results: 10,
  min_view_count: 0,
  min_like_count: 0,
  min_comment_count: 0,
  keywords: '',
  exclude_keywords: '',
  channel_ids: '',
  channel_keywords: '',
  exclude_channel_ids: '',
  min_duration: 0,
  max_duration: 0,
  schedule_type: 'manual' as string,
  schedule_interval: 120,
  order_by: 'viewCount',
  start_date: '',
  end_date: '',
  latest_days: 7,
  latest_max_results: 20,
  rate_limit_requests: 20,
  rate_limit_window: 60,
  auto_add_to_tasks: false,
  video_types: ['video', 'short', 'live'] as string[],
})

async function load() {
  try {
    const res = (await monitorApi.config(Number(configIdParam.value))) as unknown as { config: Record<string, unknown> }
    const cfg = res.config ?? {}
    form.name = String(cfg.name ?? '')
    form.enabled = !!cfg.enabled
    form.monitor_type = String(cfg.monitor_type ?? 'youtube_search')
    form.channel_mode = String(cfg.channel_mode ?? 'latest')
    form.region_code = String(cfg.region_code ?? 'US')
    form.category_id = String(cfg.category_id ?? '0')
    form.time_period = Number(cfg.time_period ?? 7)
    form.max_results = Number(cfg.max_results ?? 10)
    form.min_view_count = Number(cfg.min_view_count ?? 0)
    form.min_like_count = Number(cfg.min_like_count ?? 0)
    form.min_comment_count = Number(cfg.min_comment_count ?? 0)
    form.keywords = String(cfg.keywords ?? '')
    form.exclude_keywords = String(cfg.exclude_keywords ?? '')
    form.channel_ids = String(cfg.channel_ids ?? '')
    form.channel_keywords = String(cfg.channel_keywords ?? '')
    form.exclude_channel_ids = String(cfg.exclude_channel_ids ?? '')
    form.min_duration = Number(cfg.min_duration ?? 0)
    form.max_duration = Number(cfg.max_duration ?? 0)
    form.schedule_type = String(cfg.schedule_type ?? 'manual')
    form.schedule_interval = Number(cfg.schedule_interval ?? 120)
    form.order_by = String(cfg.order_by ?? 'viewCount')
    form.start_date = String(cfg.start_date ?? '')
    form.end_date = String(cfg.end_date ?? '')
    form.latest_days = Number(cfg.latest_days ?? 7)
    form.latest_max_results = Number(cfg.latest_max_results ?? 20)
    form.rate_limit_requests = Number(cfg.rate_limit_requests ?? 20)
    form.rate_limit_window = Number(cfg.rate_limit_window ?? 60)
    form.auto_add_to_tasks = !!cfg.auto_add_to_tasks
    const vt = String(cfg.video_types ?? '')
    form.video_types = vt ? vt.split(',').filter((v) => v) : ['video', 'short', 'live']
  } catch (e) {
    toast.error('加载配置失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (isEdit.value) load()
})

function toggleVideoType(t: string) {
  const idx = form.video_types.indexOf(t)
  if (idx >= 0) form.video_types.splice(idx, 1)
  else form.video_types.push(t)
}

async function submit() {
  if (!form.name.trim() || submitting.value) {
    if (!form.name.trim()) toast.warning('请填写配置名称')
    return
  }
  submitting.value = true
  try {
    const payload: Record<string, unknown> = {
      ...form,
      video_types: form.video_types,
    }
    if (isEdit.value) {
      await monitorApi.update(Number(configIdParam.value), payload)
      toast.success('监控配置更新成功！')
    } else {
      await monitorApi.create(payload)
      toast.success('监控配置创建成功！')
    }
    router.push('/monitor')
  } catch (e) {
    toast.error('保存失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    submitting.value = false
  }
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
          <h1 class="page-title">{{ isEdit ? '编辑监控配置' : '新建监控配置' }}</h1>
        </div>
        <p class="page-subtitle">定时抓取 YouTube 频道 / 关键词视频</p>
      </div>
    </div>

    <div v-if="loading" class="card card-pad">
      <UiSkeleton :rows="8" />
    </div>

    <form v-else class="cfg-grid" @submit.prevent="submit">
      <!-- 基本信息 -->
      <div class="card">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-sliders"></i> 基本信息</div>
        </div>
        <div class="card-body cfg-body">
          <label class="field">
            <span class="field-label">配置名称 <span class="text-danger">*</span></span>
            <input v-model="form.name" class="input" placeholder="例如：数码评测搬运" />
          </label>

          <div class="field">
            <span class="field-label">监控类型</span>
            <select v-model="form.monitor_type" class="select">
              <option value="youtube_search">关键词搜索</option>
              <option value="channel_search">频道监控</option>
            </select>
          </div>

          <div class="field">
            <span class="field-label">抓取模式</span>
            <select v-model="form.channel_mode" class="select">
              <option value="latest">最新模式（增量抓取）</option>
              <option value="historical">历史模式（回溯抓取）</option>
            </select>
          </div>

          <div class="field">
            <span class="field-label">视频类型</span>
            <div class="flex gap-2 flex-wrap">
              <label class="type-chip" :class="{ on: form.video_types.includes('video') }">
                <input type="checkbox" class="visually-hidden" @change="toggleVideoType('video')" />
                普通视频
              </label>
              <label class="type-chip" :class="{ on: form.video_types.includes('short') }">
                <input type="checkbox" class="visually-hidden" @change="toggleVideoType('short')" />
                Shorts
              </label>
              <label class="type-chip" :class="{ on: form.video_types.includes('live') }">
                <input type="checkbox" class="visually-hidden" @change="toggleVideoType('live')" />
                直播
              </label>
            </div>
          </div>

          <label class="field">
            <span class="field-label">地区代码</span>
            <select v-model="form.region_code" class="select">
              <option value="US">US（美国）</option>
              <option value="JP">JP（日本）</option>
              <option value="KR">KR（韩国）</option>
              <option value="GB">GB（英国）</option>
              <option value="DE">DE（德国）</option>
              <option value="FR">FR（法国）</option>
              <option value="TW">TW（台湾）</option>
              <option value="HK">HK（香港）</option>
            </select>
          </label>

          <div class="flex items-center justify-between p-3 toggle-row">
            <div>
              <div class="fs-md">启用该监控</div>
              <div class="fs-xs text-muted">关闭后定时任务将暂停，仍可手动执行</div>
            </div>
            <UiToggle v-model="form.enabled" />
          </div>
        </div>
      </div>

      <!-- 筛选条件 -->
      <div class="card">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-funnel"></i> 筛选条件</div>
        </div>
        <div class="card-body cfg-body">
          <template v-if="form.monitor_type === 'youtube_search'">
            <label class="field">
              <span class="field-label">搜索关键词</span>
              <input v-model="form.keywords" class="input" placeholder="例如：iPhone 评测" />
            </label>
            <label class="field">
              <span class="field-label">排除关键词（逗号分隔）</span>
              <input v-model="form.exclude_keywords" class="input" placeholder="例如：直播, 广告" />
            </label>
          </template>

          <template v-if="form.monitor_type === 'channel_search'">
            <label class="field">
              <span class="field-label">频道 ID（逗号分隔）</span>
              <input v-model="form.channel_ids" class="input" placeholder="例如：UCxxxxxx, UCyyyyyy" />
            </label>
            <label class="field">
              <span class="field-label">频道关键词</span>
              <input v-model="form.channel_keywords" class="input" placeholder="按名称搜索频道" />
            </label>
            <label class="field">
              <span class="field-label">排除频道 ID（逗号分隔）</span>
              <input v-model="form.exclude_channel_ids" class="input" />
            </label>
          </template>

          <div class="grid-2">
            <label class="field">
              <span class="field-label">最低播放量</span>
              <input v-model.number="form.min_view_count" type="number" min="0" class="input" />
            </label>
            <label class="field">
              <span class="field-label">最低点赞数</span>
              <input v-model.number="form.min_like_count" type="number" min="0" class="input" />
            </label>
            <label class="field">
              <span class="field-label">最低评论数</span>
              <input v-model.number="form.min_comment_count" type="number" min="0" class="input" />
            </label>
            <label class="field">
              <span class="field-label">单次抓取上限</span>
              <input v-model.number="form.max_results" type="number" min="1" max="50" class="input" />
            </label>
            <label class="field">
              <span class="field-label">最短时长（秒）</span>
              <input v-model.number="form.min_duration" type="number" min="0" class="input" />
            </label>
            <label class="field">
              <span class="field-label">最长时长（秒，0=不限）</span>
              <input v-model.number="form.max_duration" type="number" min="0" class="input" />
            </label>
          </div>

          <template v-if="form.channel_mode === 'historical'">
            <div class="grid-2">
              <label class="field">
                <span class="field-label">开始日期</span>
                <input v-model="form.start_date" type="date" class="input" />
              </label>
              <label class="field">
                <span class="field-label">结束日期</span>
                <input v-model="form.end_date" type="date" class="input" />
              </label>
            </div>
          </template>
        </div>
      </div>

      <!-- 执行计划 -->
      <div class="card">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-calendar-check"></i> 执行计划</div>
        </div>
        <div class="card-body cfg-body">
          <label class="field">
            <span class="field-label">调度方式</span>
            <select v-model="form.schedule_type" class="select">
              <option value="manual">手动执行</option>
              <option value="interval">定时执行</option>
            </select>
          </label>

          <template v-if="form.schedule_type === 'interval'">
            <label class="field">
              <span class="field-label">执行间隔（分钟）</span>
              <input v-model.number="form.schedule_interval" type="number" min="15" class="input" />
            </label>
          </template>

          <label class="field">
            <span class="field-label">排序方式</span>
            <select v-model="form.order_by" class="select">
              <option value="viewCount">播放量</option>
              <option value="date">日期</option>
              <option value="relevance">相关性</option>
            </select>
          </label>

          <div class="flex items-center justify-between p-3 toggle-row">
            <div>
              <div class="fs-md">发现后自动加入任务队列</div>
              <div class="fs-xs text-muted">开启后新发现的视频将自动开始搬运流程</div>
            </div>
            <UiToggle v-model="form.auto_add_to_tasks" />
          </div>
        </div>
      </div>

      <!-- 操作 -->
      <div class="card">
        <div class="card-body flex justify-between items-center">
          <span class="fs-xs text-muted">保存后立即生效，定时任务将在下一次调度时更新</span>
          <div class="flex gap-2">
            <button type="button" class="btn btn-secondary" @click="router.push('/monitor')">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="submitting">
              <span v-if="submitting" class="spinner spinner-sm"></span>
              {{ isEdit ? '保存修改' : '创建配置' }}
            </button>
          </div>
        </div>
      </div>
    </form>
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

.cfg-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-4);
  align-items: start;
}
.cfg-grid > .card:last-child {
  grid-column: 1 / -1;
}
@media (max-width: 960px) {
  .cfg-grid {
    grid-template-columns: 1fr;
  }
  .cfg-grid > .card:last-child {
    grid-column: auto;
  }
}

.cfg-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}
@media (max-width: 560px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}

.type-chip {
  display: inline-flex;
  align-items: center;
  padding: 7px 14px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border-default);
  background: var(--bg-raised);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
  user-select: none;
}
.type-chip.on {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent);
  font-weight: 500;
}

.toggle-row {
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
</style>
