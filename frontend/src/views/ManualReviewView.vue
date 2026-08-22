<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { tasksApi } from '@/api/endpoints'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import type { Task } from '@/api/types'
import TaskStatusBadge from '@/components/ui/TaskStatusBadge.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiConfirm from '@/components/ui/UiConfirm.vue'
import UiModal from '@/components/ui/UiModal.vue'

const router = useRouter()
const toast = useToastStore()

const tasks = ref<Task[]>([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const data = await tasksApi.list({ status: 'awaiting_manual_review', per_page: 100 })
    tasks.value = data.tasks
  } catch (e) {
    toast.error('加载审核列表失败', (e as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const confirmState = ref<{ open: boolean; title: string; message: string; action: () => Promise<unknown> } | null>(null)

async function runConfirm() {
  if (!confirmState.value) return
  const action = confirmState.value.action
  try {
    await action()
    confirmState.value = null
    load()
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
    confirmState.value = null
  }
}

async function forceUploadTask(task: Task) {
  try {
    const r = await tasksApi.forceUpload(task.id)
    toast.info(r.message)
    load()
  } catch (e) {
    toast.error('强制上传失败', e instanceof ApiError ? e.message : '请稍后重试')
  }
}

function askRetry(task: Task) {
  confirmState.value = {
    open: true,
    title: '重试自动翻译',
    message: '重试后，已手动修改的标题、简介、标签和分区选择将被清空并重新生成。确定继续吗？',
    action: async () => {
      const r = await tasksApi.retryTranslation(task.id)
      toast.success(r.message)
    },
  }
}

function askDelete(task: Task) {
  confirmState.value = {
    open: true,
    title: '删除任务',
    message: `确定要删除任务「${taskTitle(task)}」吗？其下载文件也会一并删除。`,
    action: async () => {
      await tasksApi.remove(task.id, true)
      load()
    },
  }
}

// ---- 放弃任务（标记失败，可选同时删除文件） ----
const abandonState = ref<{ open: boolean; task: Task } | null>(null)
const abandonDeleteFiles = ref(true)

function askAbandon(task: Task) {
  abandonDeleteFiles.value = true
  abandonState.value = { open: true, task }
}

// ---- 成品视频预览 ----
const previewState = ref<{ open: boolean; task: Task } | null>(null)

function openPreview(task: Task) {
  previewState.value = { open: true, task }
}

async function confirmAbandon() {
  if (!abandonState.value) return
  const { task } = abandonState.value
  try {
    const r = await tasksApi.abandon(task.id, abandonDeleteFiles.value)
    toast.success(r.message || '任务已废弃')
    abandonState.value = null
    load()
  } catch (e) {
    toast.error('放弃任务失败', e instanceof ApiError ? e.message : '请稍后重试')
    abandonState.value = null
  }
}

function taskTitle(task: Task): string {
  return task.video_title_translated || task.video_title_original || task.id.slice(0, 8)
}

const reviewCount = computed(() => tasks.value.length)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="page-header-text">
        <h1 class="page-title">人工审核</h1>
        <p class="page-subtitle">{{ reviewCount }} 个任务等待处理 · 审核内容并决定是否上传</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" :disabled="loading" @click="load">
          <i class="bi bi-arrow-clockwise"></i> 刷新
        </button>
      </div>
    </div>

    <div v-if="loading" class="card card-pad">
      <UiSkeleton :rows="8" />
    </div>
    <div v-else-if="!tasks.length" class="card">
      <UiEmpty
        icon="bi-patch-check"
        title="暂无待审核任务"
        description="需要人工审核的任务（内容审核不通过 / 翻译缺失等）会出现在这里。"
      />
    </div>
    <div v-else class="review-list">
      <div v-for="task in tasks" :key="task.id" class="card review-card">
        <div class="review-head">
          <div class="flex items-center gap-2 grow" style="min-width: 0">
            <span class="mono text-muted fs-xs">{{ task.id.slice(0, 8) }}</span>
            <TaskStatusBadge :status="task.status" />
          </div>
          <div class="flex gap-2">
            <button class="btn btn-ghost btn-sm" title="预览本地成品视频" @click="openPreview(task)">
              <i class="bi bi-play-circle"></i> 预览
            </button>
            <button v-if="task.can_retry_translation" class="btn btn-secondary btn-sm" @click="askRetry(task)">
              <i class="bi bi-translate"></i> 重试翻译
            </button>
            <button class="btn btn-success btn-sm" @click="forceUploadTask(task)">
              <i class="bi bi-cloud-arrow-up-fill"></i> 强制上传
            </button>
            <button class="btn btn-ghost btn-sm" title="标记为失败并停止处理" @click="askAbandon(task)">
              <i class="bi bi-slash-circle"></i> 放弃
            </button>
            <button class="btn btn-danger btn-sm" @click="askDelete(task)">
              <i class="bi bi-trash3"></i> 删除
            </button>
          </div>
        </div>

        <div class="review-body" @click="router.push(`/tasks/${task.id}`)">
          <div class="review-title clamp-2">{{ task.video_title_translated || task.video_title_original || '（未获取标题）' }}</div>
          <div v-if="task.video_title_original && task.video_title_original !== task.video_title_translated" class="review-origin clamp-1">
            原文：{{ task.video_title_original }}
          </div>
          <div v-if="task.error_message" class="callout callout-danger review-error">
            <i class="bi bi-exclamation-octagon-fill"></i>
            <span>{{ task.error_message }}</span>
          </div>
        </div>

        <div class="review-foot">
          <button class="btn btn-ghost btn-sm" @click="router.push(`/tasks/${task.id}`)">
            编辑元数据 <i class="bi bi-arrow-right"></i>
          </button>
        </div>
      </div>
    </div>

    <UiConfirm
      :open="confirmState?.open ?? false"
      :title="confirmState?.title ?? ''"
      :message="confirmState?.message ?? ''"
      :danger="true"
      @close="confirmState = null"
      @confirm="runConfirm"
    />

    <!-- 放弃任务（可选同时删除文件） -->
    <UiModal
      :open="abandonState?.open ?? false"
      title="确认放弃任务"
      size="sm"
      @close="abandonState = null"
    >
      <p class="abandon-text">
        确定要放弃任务「{{ abandonState ? taskTitle(abandonState.task) : '' }}」吗？任务将标记为失败并停止后续处理。
      </p>
      <label class="abandon-check">
        <input v-model="abandonDeleteFiles" type="checkbox" />
        同时删除任务文件
      </label>
      <template #footer>
        <button class="btn btn-ghost" @click="abandonState = null">取消</button>
        <button class="btn btn-danger-solid" @click="confirmAbandon">
          <i class="bi bi-slash-circle"></i> 放弃任务
        </button>
      </template>
    </UiModal>

    <!-- 成品视频预览 -->
    <UiModal
      :open="previewState?.open ?? false"
      :title="previewState ? `预览：${taskTitle(previewState.task)}` : '预览'"
      size="lg"
      @close="previewState = null"
    >
      <video
        v-if="previewState"
        class="preview-video"
        :src="tasksApi.previewUrl(previewState.task.id)"
        controls
        preload="metadata"
      ></video>
    </UiModal>
  </div>
</template>

<style scoped>
.preview-video {
  display: block;
  width: 100%;
  max-height: 420px;
  border-radius: var(--radius-md);
  background: #000;
  outline: none;
}
.abandon-text {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-md);
  color: var(--text-secondary);
}
.abandon-check {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
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

.review-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.review-card {
  padding: var(--sp-5);
}
.review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}
.review-body {
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: background var(--dur-fast) var(--ease);
}
.review-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}
.review-origin {
  margin-top: 4px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.review-error {
  margin-top: var(--sp-3);
}
.review-foot {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--sp-3);
  border-top: 1px solid var(--border-subtle);
  margin-top: var(--sp-3);
}
.clamp-1 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
