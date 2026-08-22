<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { tasksApi } from '@/api/endpoints'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import type { Task, UploadTarget } from '@/api/types'
import { targetLabel, formatRelativeTime, statusDisplay } from '@/composables/taskMeta'
import TaskStatusBadge from '@/components/ui/TaskStatusBadge.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiConfirm from '@/components/ui/UiConfirm.vue'
import UiDropdown, { type DropdownItem } from '@/components/ui/UiDropdown.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiProgress from '@/components/ui/UiProgress.vue'

const store = useTasksStore()
const toast = useToastStore()
const router = useRouter()

const filters = [
  { id: '', label: '全部' },
  { id: 'pending', label: '等待处理' },
  { id: 'awaiting_manual_review', label: '待审核' },
  { id: 'ready_for_upload', label: '准备上传' },
  { id: 'completed', label: '已完成' },
  { id: 'failed', label: '失败' },
]

const activeFilter = ref('')
const searchText = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  store.fetchPage().catch((e) => toast.error('加载任务失败', (e as Error).message))
})

watch(activeFilter, () => {
  store.setFilter(activeFilter.value).catch(() => undefined)
})

watch(searchText, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    store.setQuery(searchText.value.trim()).catch(() => undefined)
  }, 400)
})

/* ---- 新建任务 ---- */
const addOpen = ref(false)
const addUrl = ref('')
const addTarget = ref<UploadTarget>('acfun')
const addSubmitting = ref(false)
const addError = ref('')

function openAdd() {
  addUrl.value = ''
  addTarget.value = 'acfun'
  addError.value = ''
  addOpen.value = true
}

async function submitAdd() {
  if (!addUrl.value.trim() || addSubmitting.value) return
  addError.value = ''
  addSubmitting.value = true
  try {
    const res = await tasksApi.add(addUrl.value.trim(), addTarget.value)
    toast.success(res.message || '任务已添加')
    addOpen.value = false
    store.setPage(1)
  } catch (e) {
    addError.value = e instanceof ApiError ? e.message : '添加失败，请稍后重试'
  } finally {
    addSubmitting.value = false
  }
}

/* ---- 行操作 ---- */
function rowActions(task: Task): DropdownItem[] {
  const status = task.status
  const items: DropdownItem[] = [
    { id: '_status', label: `当前状态：${statusDisplay(status)}`, header: true },
    { id: 'view', label: '查看 / 编辑', icon: 'bi-pencil-square' },
  ]
  if (['pending', 'failed'].includes(status)) {
    items.push({ id: 'start', label: '开始处理', icon: 'bi-play-fill' })
  }
  if (task.can_retry_translation) {
    items.push({ id: 'retry_translation', label: '重试自动翻译', icon: 'bi-translate' })
  }
  if (task.preview_available) {
    items.push({ id: 'preview', label: '预览视频', icon: 'bi-film' })
  }
  const isDubbed = (task as { preview_kind?: string }).preview_kind === 'dubbed'
  if (
    task.preview_available &&
    !isDubbed &&
    ['awaiting_manual_review', 'ready_for_upload', 'completed', 'failed'].includes(status)
  ) {
    items.push({ id: 'dub', label: '生成配音', icon: 'bi-mic-fill', disabled: isDubbed })
  }
  if (['awaiting_manual_review', 'ready_for_upload', 'completed', 'failed'].includes(status)) {
    items.push({ id: 'force_upload', label: '强制上传', icon: 'bi-cloud-arrow-up-fill' })
  }
  // 危险操作分隔
  items.push({ id: '_sep', divider: true } as DropdownItem)
  if (status !== 'completed') {
    items.push({ id: 'abandon', label: '放弃任务', icon: 'bi-slash-circle', danger: true })
  }
  items.push({ id: 'delete', label: '删除任务', icon: 'bi-trash3', danger: true })
  return items
}

const confirmState = ref<{
  open: boolean
  title: string
  message: string
  action: () => Promise<unknown>
} | null>(null)

function askConfirm(title: string, message: string, action: () => Promise<unknown>) {
  confirmState.value = { open: true, title, message, action }
}

async function runConfirm() {
  if (!confirmState.value) return
  const action = confirmState.value.action
  try {
    await action()
    confirmState.value.open = false
    store.fetchPage().catch(() => undefined)
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
    confirmState.value.open = false
  }
}

function onSelect(task: Task, item: DropdownItem) {
  switch (item.id) {
    case 'view':
      router.push(`/tasks/${task.id}`)
      break
    case 'start':
      tasksApi.start(task.id).then((r) => {
        toast.success(r.message || '任务已启动')
        store.fetchPage().catch(() => undefined)
      }).catch((e) => toast.error('启动失败', e.message))
      break
    case 'retry_translation':
      tasksApi.retryTranslation(task.id).then((r) => {
        toast.success(r.message)
        store.fetchPage().catch(() => undefined)
      }).catch((e) => toast.error('重试失败', e.message))
      break
    case 'preview':
      router.push(`/tasks/${task.id}`)
      break
    case 'dub':
      askConfirm('生成配音', `将用任务「${taskTitle(task)}」现有字幕文件合成配音并替换原声（约几分钟，后台执行）。确定继续吗？`, () => tasksApi.dub(task.id).then((r) => {
        toast.success(r.message || '配音生成已启动')
        store.fetchPage().catch(() => undefined)
      }))
      break
    case 'force_upload':
      tasksApi.forceUpload(task.id).then((r) => {
        toast.info(r.message)
        store.fetchPage().catch(() => undefined)
      }).catch((e) => toast.error('强制上传失败', e.message))
      break
    case 'abandon':
      askConfirm('放弃任务', `确定要放弃任务「${taskTitle(task)}」吗？任务将标记为失败。`, () => tasksApi.abandon(task.id, true))
      break
    case 'delete':
      askConfirm('删除任务', `确定要删除任务「${taskTitle(task)}」吗？其下载文件也会一并删除。`, () => tasksApi.remove(task.id, true))
      break
  }
}

function taskTitle(task: Task): string {
  return task.video_title_translated || task.video_title_original || task.id.slice(0, 8)
}

function formatLocal(dt?: string): string {
  return formatRelativeTime(dt)
}

function uploadProgressValue(task: Task): number | null {
  const p = task.upload_progress
  if (p === null || p === undefined || p === '') return null
  const n = typeof p === 'number' ? p : parseFloat(String(p))
  if (!Number.isFinite(n)) return null
  return Math.min(100, Math.max(0, n))
}
</script>

<template>
  <div>
    <div class="page-header">
      <div class="page-header-text">
        <h1 class="page-title">任务列表</h1>
        <p class="page-subtitle">共 {{ store.total }} 个任务 · 实时同步处理进度</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" @click="tasksApi.retryFailed().then(r => { toast.success(r.message); store.fetchPage().catch(() => undefined) }).catch(e => toast.error('重试失败', e.message))">
          <i class="bi bi-arrow-repeat"></i> 重试失败
        </button>
        <button class="btn btn-secondary btn-sm" @click="tasksApi.resetStuck().then(r => { toast.success(r.message); store.fetchPage().catch(() => undefined) }).catch(e => toast.error('操作失败', e.message))">
          <i class="bi bi-arrow-counterclockwise"></i> 重置卡住
        </button>
        <button class="btn btn-danger btn-sm" @click="askConfirm('清空所有任务', '确定要清空所有任务吗？此操作不可恢复，任务文件也会一并删除。', () => tasksApi.clearAll(true))">
          <i class="bi bi-trash3"></i> 清空全部
        </button>
        <button class="btn btn-primary btn-sm" @click="openAdd">
          <i class="bi bi-plus-lg"></i> 新建任务
        </button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-tabs">
        <button
          v-for="f in filters"
          :key="f.id"
          class="filter-tab"
          :class="{ active: activeFilter === f.id }"
          @click="activeFilter = f.id"
        >
          {{ f.label }}
        </button>
      </div>
      <div class="filter-search">
        <i class="bi bi-search"></i>
        <input v-model="searchText" class="input" placeholder="搜索标题 / YouTube 链接…" />
      </div>
    </div>

    <!-- 列表 -->
    <div class="card mt-3">
      <div v-if="store.loading && !store.items.length" class="p-4">
        <UiSkeleton :rows="8" />
      </div>
      <div v-else-if="!store.items.length" class="p-4">
        <UiEmpty
          icon="bi-collection-play"
          title="暂无任务"
          description="添加一个 YouTube 视频链接，系统将自动完成下载、字幕、审核与上传。"
        >
          <button class="btn btn-primary btn-sm mt-3" @click="openAdd">
            <i class="bi bi-plus-lg"></i> 新建任务
          </button>
        </UiEmpty>
      </div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th style="width: 72px">ID</th>
              <th>标题</th>
              <th class="ta-center" style="width: 92px">平台</th>
              <th class="ta-center" style="width: 160px">状态</th>
              <th style="width: 150px">进度</th>
              <th class="ta-center" style="width: 110px">更新时间</th>
              <th class="ta-right" style="width: 48px"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in store.items" :key="task.id" class="row-click" @click="router.push(`/tasks/${task.id}`)">
              <td class="mono text-muted" :title="task.id">{{ task.id.slice(0, 6) }}…</td>
              <td style="max-width: 340px">
                <div class="clamp-2 task-title">{{ task.video_title_translated || task.video_title_original || '（未获取标题）' }}</div>
                <div v-if="task.video_title_translated && task.video_title_original && task.video_title_translated !== task.video_title_original" class="task-origin clamp-1" :title="task.video_title_original">
                  {{ task.video_title_original }}
                </div>
              </td>
              <td class="ta-center">
                <span class="target-chip">{{ targetLabel(task.upload_target) }}</span>
              </td>
              <td class="ta-center">
                <TaskStatusBadge :status="task.status" />
                <div v-if="task.error_message" class="task-error clamp-1" :title="task.error_message">
                  <i class="bi bi-exclamation-circle"></i> {{ task.error_message }}
                </div>
              </td>
              <td>
                <UiProgress
                  v-if="uploadProgressValue(task) !== null"
                  :value="uploadProgressValue(task)"
                  tone="accent"
                  :label="`${uploadProgressValue(task)}%`"
                />
                <span v-else class="text-muted fs-xs">—</span>
              </td>
              <td class="ta-center text-muted fs-sm">{{ formatLocal(task.updated_at) }}</td>
              <td class="ta-right" @click.stop>
                <UiDropdown :items="rowActions(task)" @select="onSelect(task, $event)" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="store.totalPages > 1" class="list-footer">
        <UiPagination
          :page="store.page"
          :total-pages="store.totalPages"
          :total="store.total"
          @change="store.setPage($event).catch(() => undefined)"
        />
      </div>
    </div>

    <!-- 新建任务弹窗 -->
    <UiModal :open="addOpen" title="新建搬运任务" size="md" @close="addOpen = false">
      <form @submit.prevent="submitAdd">
        <label class="field mb-3">
          <span class="field-label">YouTube 视频链接</span>
          <input v-model="addUrl" class="input" placeholder="https://www.youtube.com/watch?v=…" autofocus />
          <span class="field-hint">支持单视频链接与播放列表链接（播放列表将批量添加）</span>
          <span v-if="addError" class="field-error">{{ addError }}</span>
        </label>
        <label class="field mb-3">
          <span class="field-label">投稿平台</span>
          <select v-model="addTarget" class="select">
            <option value="acfun">AcFun</option>
            <option value="bilibili">bilibili</option>
            <option value="both">双平台</option>
          </select>
        </label>
        <div class="flex justify-between items-center">
          <span class="fs-xs text-muted">提交后任务进入队列，自动模式将立即开始处理</span>
          <div class="flex gap-2">
            <button type="button" class="btn btn-secondary" @click="addOpen = false">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="addSubmitting || !addUrl.trim()">
              <span v-if="addSubmitting" class="spinner spinner-sm"></span>
              添加任务
            </button>
          </div>
        </div>
      </form>
    </UiModal>

    <!-- 确认弹窗 -->
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
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.filter-tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  flex-wrap: wrap;
}
.filter-tab {
  padding: 6px 13px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  transition: all var(--dur-fast) var(--ease);
}
.filter-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.filter-tab.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}
.filter-search {
  position: relative;
}
.filter-search .bi-search {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
}
.filter-search .input {
  width: 230px;
  height: 34px;
  padding-left: 32px;
}

.ta-center { text-align: center; }
.ta-right { text-align: right; }
.row-click { cursor: pointer; }
.task-title { font-weight: 500; }
.task-origin {
  margin-top: 3px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
  max-width: 320px;
}
.task-error {
  margin-top: 4px;
  font-size: var(--fs-xs);
  color: var(--danger);
  max-width: 200px;
}
.target-chip {
  display: inline-flex;
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: var(--bg-raised);
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-secondary);
}
.list-footer {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-4);
  border-top: 1px solid var(--border-subtle);
}
.clamp-1 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
