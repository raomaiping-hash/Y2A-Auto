/** /api/v1 端点封装（与 Flask 后端新增的 JSON API 一一对应） */

import { api } from './client'
import type {
  ApiResponse,
  DashboardPayload,
  MonitorConfig,
  PaginationPayload,
  SessionPayload,
  Task,
  TtsVoice,
} from './types'

const V1 = '/api/v1'

/* ---------- 认证 ---------- */
export const authApi = {
  session: () => api<SessionPayload & { csrf_token: string }>(`${V1}/auth/session`),
  login: (password: string) =>
    api<ApiResponse & { csrf_token?: string }>(`${V1}/auth/login`, {
      method: 'POST',
      body: { password },
    }),
  logout: () => api<ApiResponse>(`${V1}/auth/logout`, { method: 'POST' }),
}

/* ---------- 仪表盘 ---------- */
export const dashboardApi = {
  get: () => api<DashboardPayload>(`${V1}/dashboard`),
}

/* ---------- 任务 ---------- */
export const tasksApi = {
  list: (params: { page?: number; per_page?: number; status?: string; q?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.page) qs.set('page', String(params.page))
    if (params.per_page) qs.set('per_page', String(params.per_page))
    if (params.status) qs.set('status', params.status)
    if (params.q) qs.set('q', params.q)
    const suffix = qs.toString() ? `?${qs}` : ''
    return api<PaginationPayload>(`${V1}/tasks${suffix}`)
  },
  get: (taskId: string) => api<Task>(`${V1}/tasks/${taskId}`),
  add: (youtubeUrl: string, uploadTarget?: string) =>
    api<ApiResponse & { task_id?: string; task_ids?: string[]; count?: number }>(`${V1}/tasks`, {
      method: 'POST',
      body: { youtube_url: youtubeUrl, upload_target: uploadTarget },
    }),
  start: (taskId: string) => api<ApiResponse>(`${V1}/tasks/${taskId}/start`, { method: 'POST' }),
  remove: (taskId: string, deleteFiles = true) =>
    api<ApiResponse>(`${V1}/tasks/${taskId}/delete`, {
      method: 'POST',
      body: { delete_files: deleteFiles },
    }),
  clearAll: (deleteFiles = true) =>
    api<ApiResponse>(`${V1}/tasks/clear_all`, { method: 'POST', body: { delete_files: deleteFiles } }),
  retryFailed: () => api<ApiResponse>(`${V1}/tasks/retry_failed`, { method: 'POST' }),
  resetStuck: () => api<ApiResponse>(`${V1}/tasks/reset_stuck`, { method: 'POST' }),
  reprocess: (taskId: string) => api<ApiResponse>(`${V1}/tasks/${taskId}/reprocess`, { method: 'POST' }),
  dub: (taskId: string) => api<ApiResponse>(`${V1}/tasks/${taskId}/dub`, { method: 'POST' }),
  retryTranslation: (taskId: string) =>
    api<ApiResponse>(`${V1}/tasks/${taskId}/retry_translation`, { method: 'POST' }),
  forceUpload: (taskId: string) =>
    api<ApiResponse>(`${V1}/tasks/${taskId}/force_upload`, { method: 'POST' }),
  abandon: (taskId: string, deleteFiles = true) =>
    api<ApiResponse>(`${V1}/tasks/${taskId}/abandon`, {
      method: 'POST',
      body: { delete_files: deleteFiles },
    }),
  update: (taskId: string, fields: Record<string, unknown>) =>
    api<ApiResponse & { task?: Task }>(`${V1}/tasks/${taskId}`, {
      method: 'PATCH',
      body: fields,
    }),
  uploadCover: (taskId: string, file: File) => {
    const fd = new FormData()
    fd.append('cover_file', file)
    return api<ApiResponse>(`${V1}/tasks/${taskId}/cover`, { method: 'POST', formData: fd })
  },
  restoreCover: (taskId: string) =>
    api<ApiResponse>(`${V1}/tasks/${taskId}/cover/restore`, { method: 'POST' }),
  coverUrl: (taskId: string, cacheBust?: string) =>
    `${V1}/tasks/${taskId}/cover${cacheBust ? `?v=${encodeURIComponent(cacheBust)}` : ''}`,
  previewUrl: (taskId: string) => `${V1}/tasks/${taskId}/preview`,
  log: (taskId: string) => api<{ content: string }>(`${V1}/tasks/${taskId}/log`),
}

/* ---------- 设置 ---------- */
export const settingsApi = {
  get: () => api<{ config: Record<string, unknown>; partitions: Record<string, unknown> }>(`${V1}/settings`),
  save: (formData: FormData) =>
    api<ApiResponse & { operation_id?: string }>(`${V1}/settings`, {
      method: 'POST',
      formData,
    }),
  saveProgress: (operationId: string) =>
    api<Record<string, unknown>>(`${V1}/settings/save-progress/${operationId}`),
  reset: () => api<ApiResponse>(`${V1}/settings/reset`, { method: 'POST' }),
  resetGroup: (keys: string[]) =>
    api<ApiResponse>(`${V1}/settings/reset`, { method: 'POST', body: { keys } }),
  tgbotToken: (action: 'generate' | 'revoke') =>
    api<ApiResponse & { token?: string; state?: Record<string, unknown> }>(`${V1}/settings/tgbot-token`, {
      method: 'POST',
      body: { action },
    }),
  testNotification: (channel: string) =>
    api<ApiResponse>(`${V1}/settings/notifications/test`, { method: 'POST', body: { channel } }),
  ttsTest: (text: string) =>
    api<ApiResponse & { duration_ms?: number; model?: string }>(`${V1}/settings/tts/test`, { method: 'POST', body: { text } }),
  ttsVoices: (params?: { q?: string; page?: number; page_size?: number }) =>
    api<ApiResponse & { total?: number; has_more?: boolean; items?: TtsVoice[] }>(
      `${V1}/settings/tts/voices?${new URLSearchParams((params ?? {}) as Record<string, string>).toString()}`,
    ),
  ttsPreview: (voiceId: string) =>
    api<ApiResponse & { audio_base64?: string; mime?: string }>(`${V1}/settings/tts/preview`, { method: 'POST', body: { voice_id: voiceId } }),
  testCookiecloud: () =>
    api<ApiResponse>(`${V1}/settings/cookiecloud/test`, { method: 'POST' }),
  syncCookiecloud: () =>
    api<ApiResponse>(`${V1}/settings/cookiecloud/sync`, { method: 'POST' }),
  acfunQrStart: () => api<ApiResponse & { session_id?: string; qr_image?: string }>(`${V1}/settings/acfun/qrcode/start`, { method: 'POST' }),
  acfunQrStatus: (sessionId: string) =>
    api<ApiResponse>(`${V1}/settings/acfun/qrcode/status/${sessionId}`),
  bilibiliQrStart: () => api<ApiResponse & { session_id?: string; qr_image?: string }>(`${V1}/settings/bilibili/qrcode/start`, { method: 'POST' }),
  bilibiliQrStatus: (sessionId: string) =>
    api<ApiResponse>(`${V1}/settings/bilibili/qrcode/status/${sessionId}`),
  clearLogs: (payload: { hours?: number; all?: boolean }) =>
    api<ApiResponse>(`${V1}/maintenance/clear_logs`, { method: 'POST', body: payload }),
  cleanupDownloads: (payload: { hours?: number; all?: boolean }) =>
    api<ApiResponse>(`${V1}/maintenance/cleanup_downloads`, { method: 'POST', body: payload }),
}

/* ---------- 系统健康 ---------- */
export const healthApi = {
  get: () => api<Record<string, unknown>>(`${V1}/system_health`),
}

/* ---------- YouTube 监控 ---------- */
export const monitorApi = {
  status: () => api<Record<string, unknown>>(`${V1}/monitor`),
  configs: () => api<{ configs: MonitorConfig[] }>(`${V1}/monitor/configs`),
  config: (configId: number) =>
    api<{ config: MonitorConfig }>(`${V1}/monitor/configs/${configId}`),
  create: (payload: Record<string, unknown>) =>
    api<ApiResponse & { config_id?: number }>(`${V1}/monitor/configs`, { method: 'POST', body: payload }),
  update: (configId: number, payload: Record<string, unknown>) =>
    api<ApiResponse>(`${V1}/monitor/configs/${configId}`, { method: 'PATCH', body: payload }),
  remove: (configId: number) =>
    api<ApiResponse>(`${V1}/monitor/configs/${configId}`, { method: 'DELETE' }),
  run: (configId: number) =>
    api<ApiResponse & { operation_id?: string }>(`${V1}/monitor/configs/${configId}/run`, { method: 'POST' }),
  runStatus: (operationId: string) =>
    api<Record<string, unknown>>(`${V1}/monitor/run-status/${operationId}`),
  history: (configId: number) =>
    api<{ videos: Record<string, unknown>[] }>(`${V1}/monitor/configs/${configId}/history`),
  addToTasks: (configId: number, videoIds: string[]) =>
    api<ApiResponse>(`${V1}/monitor/add_to_tasks`, { method: 'POST', body: { config_id: configId, video_ids: videoIds } }),
  clearHistory: (configId: number) =>
    api<ApiResponse>(`${V1}/monitor/configs/${configId}/history/clear`, { method: 'POST' }),
  clearAllHistory: () => api<ApiResponse>(`${V1}/monitor/history/clear_all`, { method: 'POST' }),
  restoreConfigs: () => api<ApiResponse>(`${V1}/monitor/restore_configs`, { method: 'POST' }),
  resetOffset: (configId: number) =>
    api<ApiResponse>(`${V1}/monitor/configs/${configId}/reset_offset`, { method: 'POST' }),
}
