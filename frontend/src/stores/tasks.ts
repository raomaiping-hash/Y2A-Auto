import { defineStore } from 'pinia'
import { tasksApi } from '@/api/endpoints'
import { openEventStream } from '@/api/client'
import type { Task, TaskStreamEvent } from '@/api/types'

/** 任务列表 store：分页、筛选、SSE 实时同步 */
export const useTasksStore = defineStore('tasks', {
  state: () => ({
    items: [] as Task[],
    total: 0,
    page: 1,
    perPage: 20,
    totalPages: 0,
    loading: false,
    statusFilter: '' as string,
    query: '',
    connected: false,
    _reloadTimer: null as ReturnType<typeof setTimeout> | null,
    _closeStream: null as (() => void) | null,
  }),
  actions: {
    async fetchPage() {
      this.loading = true
      try {
        const data = await tasksApi.list({
          page: this.page,
          per_page: this.perPage,
          status: this.statusFilter || undefined,
          q: this.query || undefined,
        })
        this.items = data.tasks
        this.total = data.total
        this.totalPages = data.total_pages
        return data
      } finally {
        this.loading = false
      }
    },

    setPage(page: number) {
      this.page = page
      return this.fetchPage()
    },
    setFilter(status: string) {
      this.statusFilter = status
      this.page = 1
      return this.fetchPage()
    },
    setQuery(q: string) {
      this.query = q
      this.page = 1
      return this.fetchPage()
    },

    /** 连接 SSE 实时流 */
    connectStream() {
      if (this._closeStream) return
      this._closeStream = openEventStream(
        '/api/v1/tasks/stream',
        (raw) => this.handleEvent(raw as TaskStreamEvent),
        () => {
          /* 断线由浏览器 EventSource 自动重连 */
        },
      ).close
      this.connected = true
    },
    disconnectStream() {
      this._closeStream?.()
      this._closeStream = null
      this.connected = false
    },

    handleEvent(event: TaskStreamEvent) {
      const data = (event.data ?? {}) as Record<string, unknown>
      const taskId = typeof data.task_id === 'string' ? data.task_id : undefined

      switch (event.type) {
        case 'task_progress': {
          // 原地更新进度，避免整页刷新造成闪烁
          const task = this.items.find((t) => t.id === taskId)
          if (task) {
            if (data.upload_progress !== undefined) {
              task.upload_progress = data.upload_progress as string | number | null
            }
            if (data.status) task.status = data.status as Task['status']
            if (data.updated_at) task.updated_at = data.updated_at as string
          }
          break
        }
        case 'task_added':
        case 'task_updated':
        case 'task_deleted':
        case 'tasks_cleared':
        default:
          // 结构变化：防抖重载当前页
          if (this._reloadTimer) clearTimeout(this._reloadTimer)
          this._reloadTimer = setTimeout(() => {
            this.fetchPage().catch(() => undefined)
            // 通知其他视图（仪表盘统计等）
            window.dispatchEvent(new CustomEvent('tasks:changed'))
          }, 350)
      }
    },

    async reload() {
      return this.fetchPage()
    },
  },
})
