/** 与 Flask 后端对齐的类型定义 */

export type TaskStatus =
  | 'pending'
  | 'fetching_info'
  | 'info_fetched'
  | 'downloading'
  | 'downloaded'
  | 'asr_transcribing'
  | 'translating_subtitle'
  | 'encoding_video'
  | 'translating'
  | 'tagging'
  | 'partitioning'
  | 'moderating'
  | 'awaiting_manual_review'
  | 'ready_for_upload'
  | 'uploading'
  | 'completed'
  | 'failed'
  | string

export type UploadTarget = 'acfun' | 'bilibili' | 'both'

export interface Task {
  id: string
  youtube_url?: string
  video_title_original?: string
  video_title_translated?: string
  title?: string
  description_translated?: string
  video_description_original?: string
  video_description_translated?: string
  tags?: string
  cover_path?: string
  status: TaskStatus
  upload_target?: string
  upload_progress?: string | number | null
  progress?: string | number | null
  error_message?: string | null
  acfun_upload_response?: string | null
  bilibili_upload_response?: string | null
  selected_partition_id?: string
  recommended_partition_id?: string
  selected_partition_id_acfun?: string
  recommended_partition_id_acfun?: string
  selected_partition_id_bilibili?: string
  recommended_partition_id_bilibili?: string
  created_at?: string
  updated_at?: string
  can_retry_translation?: boolean
  preview_available?: boolean
  preview_kind?: 'embedded' | 'original' | 'none'
  [key: string]: unknown
}

export interface DashboardStats {
  total_tasks: number
  awaiting_review: number
  failed_total: number
  pending_total: number
  ready_total: number
  in_progress: number
  completed_today: number
  failed_today: number
  created_today: number
}

export interface RecentTask {
  id: string
  title: string
  status: TaskStatus
  updated_at: string
  upload_target: string
  upload_id: string | null
}

export interface DashboardPayload {
  stats: DashboardStats
  recent_tasks: RecentTask[]
}

export interface RuntimeToolStatus {
  status: 'ok' | 'warn' | 'missing' | 'disabled' | 'error' | 'unknown'
  path?: string | null
  message?: string
  free_gb?: number | null
}

export interface SystemHealthPayload {
  runtime_tools?: {
    ffmpeg?: RuntimeToolStatus
    ffprobe?: RuntimeToolStatus
    vad?: RuntimeToolStatus
    asr?: RuntimeToolStatus
    disk?: RuntimeToolStatus
  }
  [key: string]: unknown
}

export interface SessionPayload {
  authenticated: boolean
  password_protection_enabled: boolean
  locked_until: number | null
  remaining_attempts: number | null
}

export interface ApiResponse<T = unknown> {
  success: boolean
  message?: string
  data?: T
  [key: string]: unknown
}

export interface PaginationPayload {
  tasks: Task[]
  total: number
  page: number
  per_page: number
  total_pages: number
  has_prev: boolean
  has_next: boolean
}

export interface MonitorConfig {
  id: number
  name: string
  type: string
  [key: string]: unknown
}

export interface TaskStreamEvent {
  type: string
  task_id?: string
  task?: Task
  [key: string]: unknown
}

/* ---- 任务详情 / 分区 ---- */
export interface PartitionEntry {
  name: string
  id: string
  description?: string
}

export interface PartitionGroup {
  category: string
  partitions: (PartitionEntry & { sub_partitions?: PartitionEntry[] })[]
}

export interface TaskDetail extends Task {
  tags_list?: string[]
  cover_preview?: boolean
  cover_filename?: string
  has_original_cover_backup?: boolean
  is_custom_cover_active?: boolean
  missing_partitions?: string[]
}

export interface TaskDetailPayload {
  success: boolean
  task: TaskDetail
  acfun_partition_mapping?: PartitionGroup[]
  bilibili_partition_mapping?: PartitionGroup[]
}

export interface TaskUpdatePayload {
  success: boolean
  message?: string
  task?: TaskDetail
}

/* ---- 监控 ---- */
export interface MonitorHistoryStats {
  total_records: number
  added_to_tasks: number
  avg_views: number
  avg_likes: number
}

export interface MonitorHistoryPayload {
  success: boolean
  history: Record<string, unknown>[]
  config: Record<string, unknown> | null
  stats: MonitorHistoryStats
}

export interface MonitorStatusPayload {
  success: boolean
  configs: MonitorConfig[]
  history: Record<string, unknown>[]
}

export interface MonitorConfigPayload {
  success: boolean
  config: MonitorConfig
}

export interface MonitorRunPayload {
  success: boolean
  message?: string
  operation_id?: string
  config_id?: number
}

export interface MonitorRunStatusPayload {
  found: boolean
  config_id?: number | null
  message: string
  detail: string
  done: boolean
  level: string
  success: boolean | null
  percent?: number | null
}

/* ---- 设置 ---- */
export interface TgBotTokenPayload {
  success: boolean
  message?: string
  token?: string
  state?: Record<string, unknown>
}

export interface SettingsSaveProgressEntry {
  category: string
  text: string
}

export interface SettingsSaveProgressPayload {
  found: boolean
  message: string
  detail: string
  percent: number | null
  done: boolean
  success: boolean
  messages: SettingsSaveProgressEntry[]
}

export interface SettingsSavePayload {
  success: boolean
  message?: string
  operation_id?: string
  csrf_token?: string
}

export interface SettingsPayload {
  success?: boolean
  config: Record<string, unknown>
  whisper_languages?: string[]
  acfun_partition_mapping?: Record<string, unknown>
  bilibili_partition_mapping?: Record<string, unknown>
  builtin_prompts?: Record<string, unknown>
  tgbot_token_state?: Record<string, unknown>
  csrf_token?: string
}
