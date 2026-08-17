<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tasksApi } from '@/api/endpoints'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import type { Task } from '@/api/types'
import { targetLabel, formatDbTime } from '@/composables/taskMeta'
import TaskStatusBadge from '@/components/ui/TaskStatusBadge.vue'
import UiConfirm from '@/components/ui/UiConfirm.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import CopyButton from '@/components/ui/CopyButton.vue'

interface PartitionEntry { name: string; id: string; description?: string }
interface PartitionGroup { category: string; partitions: (PartitionEntry & { sub_partitions?: PartitionEntry[] })[] }
interface TaskDetailResponse extends Task {
  tags_list?: string[]
  cover_preview?: boolean
  cover_filename?: string
  has_original_cover_backup?: boolean
  is_custom_cover_active?: boolean
  missing_partitions?: string[]
  acfun_partition_mapping?: PartitionGroup[]
  bilibili_partition_mapping?: PartitionGroup[]
}

const route = useRoute()
const router = useRouter()
const toast = useToastStore()

const taskId = computed(() => String(route.params.taskId))
const task = ref<TaskDetailResponse | null>(null)
const loading = ref(true)
const loadError = ref('')

const acfunMapping = ref<PartitionGroup[]>([])
const bilibiliMapping = ref<PartitionGroup[]>([])

/* ---- 表单 ---- */
const title = ref('')
const description = ref('')
const tagsText = ref('')
const partitionAcfun = ref('')
const partitionBilibili = ref('')
const saving = ref(false)
const dirty = ref(false)

const logOpen = ref(false)
const logContent = ref('')
const logLoading = ref(false)
let logTimer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const res = (await tasksApi.get(taskId.value)) as unknown as { task: TaskDetailResponse; acfun_partition_mapping?: PartitionGroup[]; bilibili_partition_mapping?: PartitionGroup[] }
    task.value = res.task
    acfunMapping.value = res.acfun_partition_mapping ?? []
    bilibiliMapping.value = res.bilibili_partition_mapping ?? []
    title.value = task.value.video_title_translated || ''
    description.value = task.value.description_translated || ''
    tagsText.value = (task.value.tags_list ?? []).join(', ')
    partitionAcfun.value = String(task.value.selected_partition_id_acfun || task.value.selected_partition_id || '')
    partitionBilibili.value = String(task.value.selected_partition_id_bilibili || task.value.selected_partition_id || '')
    dirty.value = false
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : '加载任务失败'
  } finally {
    loading.value = false
  }
}

watch([title, description, tagsText, partitionAcfun, partitionBilibili], () => {
  if (task.value) dirty.value = true
})

onMounted(() => load())

/* ---- 保存 ---- */
async function save(forceUpload = false) {
  if (!task.value || saving.value) return
  saving.value = true
  try {
    const res = (await tasksApi.update(taskId.value, {
      video_title_translated: title.value,
      description_translated: description.value,
      tags: tagsText.value,
      selected_partition_id_acfun: partitionAcfun.value,
      selected_partition_id_bilibili: partitionBilibili.value,
      force_upload: forceUpload,
    })) as unknown as { success: boolean; message?: string; task?: TaskDetailResponse }
    toast.success(res.message || '任务已保存')
    if (res.task) task.value = res.task
    dirty.value = false
    if (forceUpload) router.push('/review')
  } catch (e) {
    toast.error('保存失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    saving.value = false
  }
}

/* ---- 操作 ---- */
async function startTask() {
  try {
    const r = await tasksApi.start(taskId.value)
    toast.success(r.message)
    load()
  } catch (e) {
    toast.error('启动失败', (e as Error).message)
  }
}

async function forceUpload() {
  if (!task.value || dirty.value) {
    await save(true)
    return
  }
  try {
    const r = await tasksApi.forceUpload(taskId.value)
    toast.info(r.message)
    load()
  } catch (e) {
    toast.error('强制上传失败', (e as Error).message)
  }
}

async function retryTranslation() {
  try {
    const r = await tasksApi.retryTranslation(taskId.value)
    toast.success(r.message)
    load()
  } catch (e) {
    toast.error('重试失败', (e as Error).message)
  }
}

const confirmState = ref<{ open: boolean; title: string; message: string; action: () => Promise<unknown> } | null>(null)

function askDelete() {
  confirmState.value = {
    open: true,
    title: '删除任务',
    message: '确定要删除该任务吗？其下载文件也会一并删除。',
    action: async () => {
      await tasksApi.remove(taskId.value, true)
      router.push('/tasks')
    },
  }
}

function askAbandon() {
  confirmState.value = {
    open: true,
    title: '放弃任务',
    message: '确定要放弃该任务吗？任务将标记为失败。',
    action: async () => {
      await tasksApi.abandon(taskId.value, true)
      load()
    },
  }
}

async function runConfirm() {
  if (!confirmState.value) return
  const action = confirmState.value.action
  try {
    await action()
    confirmState.value = null
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
    confirmState.value = null
  }
}

/* ---- 封面 ---- */
const coverVersion = ref(0)
const coverInput = ref<HTMLInputElement | null>(null)

function coverUrl(): string {
  return tasksApi.coverUrl(taskId.value, String(coverVersion.value))
}

function pickCover() {
  coverInput.value?.click()
}

async function onCoverPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    await tasksApi.uploadCover(taskId.value, file)
    toast.success('任务封面已更新')
    coverVersion.value++
    input.value = ''
  } catch (err) {
    toast.error('更换封面失败', err instanceof ApiError ? err.message : '请稍后重试')
  }
}

async function restoreCover() {
  try {
    await tasksApi.restoreCover(taskId.value)
    toast.success('已恢复原始封面')
    coverVersion.value++
  } catch (e) {
    toast.error('恢复失败', (e as Error).message)
  }
}

/* ---- 日志 ---- */
async function fetchLog() {
  if (!logOpen.value) return
  logLoading.value = true
  try {
    const res = await tasksApi.log(taskId.value)
    logContent.value = res.content
  } catch {
    /* 忽略轮询错误 */
  } finally {
    logLoading.value = false
  }
}

watch(logOpen, (open) => {
  if (open) {
    fetchLog()
    logTimer = setInterval(fetchLog, 3000)
  } else if (logTimer) {
    clearInterval(logTimer)
    logTimer = null
  }
})
onBeforeUnmount(() => {
  if (logTimer) clearInterval(logTimer)
})

const canStart = computed(() => ['pending', 'failed'].includes(task.value?.status ?? ''))
const canForceUpload = computed(() => ['awaiting_manual_review', 'ready_for_upload', 'completed', 'failed'].includes(task.value?.status ?? ''))
const canRetryTranslation = computed(() => !!task.value?.can_retry_translation)

function formatTime(dt?: string): string {
  return formatDbTime(dt)
}
</script>

<template>
  <div>
    <!-- 顶栏 -->
    <div class="page-header">
      <div class="page-header-text">
        <div class="flex items-center gap-2">
          <button class="btn-icon" aria-label="返回" @click="router.push('/tasks')">
            <i class="bi bi-arrow-left"></i>
          </button>
          <h1 class="page-title">任务详情</h1>
          <TaskStatusBadge v-if="task" :status="task.status" />
        </div>
        <p class="page-subtitle mono">{{ taskId }}</p>
      </div>
      <div class="page-actions" v-if="task">
        <button v-if="canStart" class="btn btn-primary btn-sm" @click="startTask">
          <i class="bi bi-play-fill"></i> 开始处理
        </button>
        <button v-if="canRetryTranslation" class="btn btn-secondary btn-sm" @click="retryTranslation">
          <i class="bi bi-translate"></i> 重试自动翻译
        </button>
        <button v-if="canForceUpload" class="btn btn-success btn-sm" @click="forceUpload">
          <i class="bi bi-cloud-arrow-up-fill"></i> 强制上传
        </button>
        <button v-if="task.status !== 'completed'" class="btn btn-warning btn-sm" @click="askAbandon">
          <i class="bi bi-slash-circle"></i> 放弃
        </button>
        <button class="btn btn-danger btn-sm" @click="askDelete">
          <i class="bi bi-trash3"></i> 删除
        </button>
      </div>
    </div>

    <!-- 加载 / 错误 -->
    <div v-if="loading" class="card card-pad">
      <UiSkeleton :rows="10" />
    </div>
    <div v-else-if="loadError || !task" class="card card-pad">
      <UiEmpty icon="bi-exclamation-triangle" title="无法加载任务" :description="loadError">
        <button class="btn btn-secondary btn-sm mt-3" @click="router.push('/tasks')">返回任务列表</button>
      </UiEmpty>
    </div>

    <template v-else>
      <div class="detail-grid">
        <!-- 左：元数据编辑 -->
        <div class="detail-main">
          <div class="card">
            <div class="card-header">
              <div class="card-title"><i class="bi bi-pencil-square"></i> 元数据编辑</div>
              <span v-if="dirty" class="badge badge-warning">未保存</span>
            </div>
            <div class="card-body">
              <div v-if="task.missing_partitions?.length" class="callout callout-warning mb-4">
                <i class="bi bi-exclamation-triangle-fill"></i>
                <span>上传前需要选择：{{ task.missing_partitions.join('、') }}（或开启分区推荐）</span>
              </div>

              <div class="callout callout-info mb-4">
                <i class="bi bi-translate"></i>
                <span class="truncate" :title="task.video_title_original">{{ task.video_title_original || '原始标题未获取' }}</span>
              </div>

              <label class="field mb-4">
                <span class="field-label">投稿标题（译文）</span>
                <input v-model="title" class="input" placeholder="发布到平台的标题" />
              </label>

              <label class="field mb-4">
                <span class="field-label">简介（译文）</span>
                <textarea v-model="description" class="textarea" rows="6" placeholder="发布到平台的视频简介"></textarea>
              </label>

              <label class="field mb-4">
                <span class="field-label">标签</span>
                <input v-model="tagsText" class="input" placeholder="多个标签用逗号分隔，例如：科技, 数码, 评测" />
              </label>

              <div v-if="(task.upload_target || 'acfun') !== 'bilibili'" class="field mb-4">
                <span class="field-label">AcFun 分区</span>
                <select v-model="partitionAcfun" class="select">
                  <option value="">未选择</option>
                  <optgroup v-for="group in acfunMapping" :key="group.category" :label="group.category">
                    <option v-for="p in group.partitions" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
                  </optgroup>
                </select>
              </div>

              <div v-if="(task.upload_target || 'acfun') !== 'acfun'" class="field mb-4">
                <span class="field-label">bilibili 分区</span>
                <select v-model="partitionBilibili" class="select">
                  <option value="">未选择</option>
                  <optgroup v-for="group in bilibiliMapping" :key="group.category" :label="group.category">
                    <template v-for="p in group.partitions" :key="p.id">
                      <option :value="String(p.id)">{{ p.name }}</option>
                      <option
                        v-for="sub in p.sub_partitions ?? []"
                        :key="`${p.id}-${sub.id}`"
                        :value="String(sub.id)"
                      >
                        └ {{ sub.name }}
                      </option>
                    </template>
                  </optgroup>
                </select>
              </div>

              <div class="flex gap-2 justify-between items-center">
                <span class="fs-xs text-muted">保存后可继续执行上传等操作</span>
                <div class="flex gap-2">
                  <button class="btn btn-secondary" :disabled="saving" @click="save(false)">
                    <span v-if="saving" class="spinner spinner-sm"></span> 保存
                  </button>
                  <button v-if="canForceUpload" class="btn btn-success" :disabled="saving" @click="save(true)">
                    <i class="bi bi-cloud-arrow-up-fill"></i> 保存并上传
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 处理日志 -->
          <div class="card mt-4">
            <div class="card-header">
              <div class="card-title"><i class="bi bi-terminal"></i> 处理日志</div>
              <UiToggle v-model="logOpen" label="自动刷新" />
            </div>
            <div v-if="logOpen" class="card-body">
              <div class="code-block log-block">
                <template v-if="logContent">{{ logContent }}</template>
                <span v-else-if="logLoading" class="text-muted">加载中…</span>
                <span v-else class="text-muted">暂无日志输出</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右：封面与信息 -->
        <div class="detail-side">
          <div class="card">
            <div class="card-header">
              <div class="card-title"><i class="bi bi-image"></i> 封面</div>
            </div>
            <div class="card-body">
              <div class="cover-preview">
                <img
                  v-if="task.cover_preview"
                  :src="coverUrl()"
                  alt="任务封面"
                  @error="($event.target as HTMLImageElement).style.display = 'none'"
                />
                <div v-else class="cover-empty">
                  <i class="bi bi-image"></i>
                  <span>暂无封面</span>
                </div>
              </div>
              <input ref="coverInput" type="file" accept="image/*" class="visually-hidden" @change="onCoverPicked" />
              <div class="flex gap-2 mt-3">
                <button class="btn btn-secondary btn-sm grow" @click="pickCover">
                  <i class="bi bi-upload"></i> 上传新封面
                </button>
                <button
                  v-if="task.has_original_cover_backup"
                  class="btn btn-ghost btn-sm"
                  title="恢复下载时的原始封面"
                  @click="restoreCover"
                >
                  <i class="bi bi-arrow-counterclockwise"></i> 恢复
                </button>
              </div>
            </div>
          </div>

          <div class="card mt-4">
            <div class="card-header">
              <div class="card-title"><i class="bi bi-info-circle"></i> 任务信息</div>
            </div>
            <div class="card-body info-list">
              <div class="info-row">
                <span class="info-key">任务 ID</span>
                <span class="info-value mono flex items-center gap-1">
                  {{ taskId.slice(0, 12) }}…
                  <CopyButton :text="taskId" size="sm" />
                </span>
              </div>
              <div class="info-row">
                <span class="info-key">投稿平台</span>
                <span class="info-value">{{ targetLabel(task.upload_target) }}</span>
              </div>
              <div class="info-row">
                <span class="info-key">原始链接</span>
                <a v-if="task.youtube_url" :href="task.youtube_url" target="_blank" rel="noopener" class="info-value truncate" :title="task.youtube_url">
                  YouTube <i class="bi bi-box-arrow-up-right"></i>
                </a>
                <span v-else class="info-value">—</span>
              </div>
              <div class="info-row">
                <span class="info-key">创建时间</span>
                <span class="info-value">{{ formatTime(task.created_at) }}</span>
              </div>
              <div class="info-row">
                <span class="info-key">更新时间</span>
                <span class="info-value">{{ formatTime(task.updated_at) }}</span>
              </div>
              <div v-if="task.error_message" class="info-row">
                <span class="info-key">错误信息</span>
                <span class="info-value text-danger">{{ task.error_message }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

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
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.page-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: var(--sp-4);
  align-items: start;
}
@media (max-width: 1080px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

.cover-preview {
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--bg-canvas);
  border: 1px solid var(--border-subtle);
}
.cover-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cover-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.cover-empty i {
  font-size: 1.6rem;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.info-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  font-size: var(--fs-sm);
}
.info-key {
  color: var(--text-muted);
  flex-shrink: 0;
}
.info-value {
  color: var(--text-secondary);
  text-align: right;
  max-width: 65%;
  word-break: break-all;
}

.log-block {
  max-height: 420px;
  overflow-y: auto;
  font-size: var(--fs-xs);
  line-height: 1.7;
}
</style>
