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
