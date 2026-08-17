import { defineStore } from 'pinia'

export type ToastKind = 'success' | 'error' | 'warning' | 'info'

export interface ToastItem {
  id: number
  kind: ToastKind
  title: string
  message?: string
  duration: number
}

let seed = 0

export const useToastStore = defineStore('toast', {
  state: () => ({
    items: [] as ToastItem[],
  }),
  actions: {
    push(kind: ToastKind, title: string | undefined, message?: string, duration = 4200) {
      const id = ++seed
      const fallback = kind === 'error' ? '操作失败' : kind === 'success' ? '操作成功' : '提示'
      this.items.push({ id, kind, title: title || fallback, message, duration })
      if (duration > 0) {
        setTimeout(() => this.remove(id), duration)
      }
      return id
    },
    success(title?: string, message?: string) {
      return this.push('success', title, message)
    },
    error(title?: string, message?: string) {
      return this.push('error', title, message, 6500)
    },
    warning(title?: string, message?: string) {
      return this.push('warning', title, message, 5200)
    },
    info(title?: string, message?: string) {
      return this.push('info', title, message)
    },
    remove(id: number) {
      const idx = this.items.findIndex((t) => t.id === id)
      if (idx >= 0) this.items.splice(idx, 1)
    },
  },
})
