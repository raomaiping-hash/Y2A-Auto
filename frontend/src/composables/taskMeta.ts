/** 任务状态 → 展示文案 / 徽章色调（对齐后端 task_status_display / task_status_color） */

import type { TaskStatus } from '@/api/types'

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'primary' | 'secondary'

const DISPLAY: Record<string, string> = {
  pending: '等待处理',
  fetching_info: '采集信息中',
  info_fetched: '信息已采集',
  downloading: '下载中',
  downloaded: '下载完成',
  asr_transcribing: '语音转写中',
  translating_subtitle: '翻译字幕中',
  encoding_video: '转码视频中',
  translating: '翻译中',
  tagging: '生成标签中',
  partitioning: '推荐分区中',
  moderating: '内容审核中',
  awaiting_manual_review: '等待人工审核',
  ready_for_upload: '准备上传',
  uploading: '上传中',
  completed: '已完成',
  failed: '失败',
}

const TONE: Record<string, StatusTone> = {
  pending: 'secondary',
  fetching_info: 'info',
  info_fetched: 'info',
  downloading: 'info',
  downloaded: 'info',
  asr_transcribing: 'info',
  translating_subtitle: 'info',
  encoding_video: 'info',
  translating: 'info',
  tagging: 'info',
  partitioning: 'info',
  moderating: 'info',
  awaiting_manual_review: 'warning',
  ready_for_upload: 'primary',
  uploading: 'primary',
  completed: 'success',
  failed: 'danger',
}

/** 运行中（应显示脉冲动画）的状态 */
const ACTIVE: Set<string> = new Set([
  'fetching_info',
  'downloading',
  'asr_transcribing',
  'translating_subtitle',
  'encoding_video',
  'translating',
  'tagging',
  'partitioning',
  'moderating',
  'uploading',
])

export function statusDisplay(status: TaskStatus): string {
  return DISPLAY[status] ?? status
}

export function statusTone(status: TaskStatus): StatusTone {
  return TONE[status] ?? 'secondary'
}

export function statusActive(status: TaskStatus): boolean {
  return ACTIVE.has(status)
}

/** 上传平台展示名 */
export function targetLabel(target?: string): string {
  if (target === 'both') return '双平台'
  if (target === 'bilibili') return 'bilibili'
  return 'AcFun'
}

/**
 * 解析后端数据库时间。
 * 后端以 UTC 存储 "YYYY-MM-DD HH:MM:SS"（无时区标记），
 * 前端需补 Z 再解析，否则按本地时间理解会偏移数小时。
 */
export function parseDbTime(dt?: string | null): Date | null {
  if (!dt) return null
  const s = String(dt)
  const hasZone = s.includes('T') || s.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(s)
  const iso = hasZone ? s : `${s.replace(' ', 'T')}Z`
  const d = new Date(iso)
  return isNaN(d.getTime()) ? null : d
}

/** 相对时间（刚刚 / N 分钟前 / …） */
export function formatRelativeTime(dt?: string | null): string {
  const d = parseDbTime(dt)
  if (!d) return dt ? String(dt) : '—'
  const n = new Date()
  const ms = n.getTime() - d.getTime()
  const m = Math.floor(ms / 60000)
  const h = Math.floor(ms / 3600000)
  const days = Math.floor(ms / 86400000)
  if (m < 5) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  if (h < 24 && d.toDateString() === n.toDateString()) return `${h} 小时前`
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  return d.toLocaleDateString('zh-CN')
}

/** 完整本地时间字符串 */
export function formatDbTime(dt?: string | null): string {
  const d = parseDbTime(dt)
  if (!d) return dt ? String(dt) : '—'
  return d.toLocaleString('zh-CN')
}
