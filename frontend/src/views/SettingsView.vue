<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { settingsApi } from '@/api/endpoints'
import { useToastStore } from '@/stores/toast'
import { ApiError } from '@/api/client'
import type { TtsVoice } from '@/api/types'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiConfirm from '@/components/ui/UiConfirm.vue'
import CopyButton from '@/components/ui/CopyButton.vue'

/* ================= 字段 schema ================= */
type FieldType = 'text' | 'password' | 'number' | 'select' | 'textarea' | 'toggle'
interface FieldDef {
  key: string
  label: string
  type: FieldType
  hint?: string
  placeholder?: string
  options?: { value: string; label: string }[]
  full?: boolean
  step?: string
  sensitive?: boolean
}

interface SectionDef {
  id: string
  title: string
  icon: string
  desc?: string
  fields: FieldDef[]
}

const SECTIONS: SectionDef[] = [
  {
    id: 'run',
    title: '运行概览',
    icon: 'bi-speedometer2',
    desc: '自动化流水线总开关与任务调度参数',
    fields: [
      { key: 'AUTO_MODE_ENABLED', label: '无人值守自动投稿', type: 'toggle', hint: '开启后任务全流程自动完成（下载→处理→上传），否则需手动审核/上传' },
      { key: 'UPLOAD_TARGET_DEFAULT', label: '默认投稿平台', type: 'select', options: [{ value: 'acfun', label: 'AcFun' }, { value: 'bilibili', label: 'bilibili' }, { value: 'both', label: '双平台' }] },
      { key: 'TRANSLATE_TITLE', label: '自动翻译标题', type: 'toggle' },
      { key: 'TRANSLATE_DESCRIPTION', label: '自动翻译简介', type: 'toggle' },
      { key: 'GENERATE_TAGS', label: 'AI 生成标签', type: 'toggle' },
      { key: 'YOUTUBE_UPLOADER_AS_FIRST_TAG', label: 'YouTube 作者作为首标签', type: 'toggle' },
      { key: 'RECOMMEND_PARTITION', label: 'AI 推荐分区', type: 'toggle' },
      { key: 'RECOMMEND_PARTITION_WITH_COVER', label: '分区推荐参考封面', type: 'toggle' },
      { key: 'UPLOAD_APPEND_REPOST_NOTICE', label: '追加转载声明', type: 'toggle', hint: '自动在简介中追加转载说明' },
      { key: 'DELETE_DOWNLOAD_FILES_AFTER_UPLOAD', label: '上传后删除下载文件', type: 'toggle' },
      { key: 'MAX_CONCURRENT_TASKS', label: '最大并发任务数', type: 'number', hint: '同时处理的搬运任务上限' },
      { key: 'MAX_CONCURRENT_UPLOADS', label: '最大并发上传数', type: 'number' },
      { key: 'FIXED_PARTITION_ID', label: 'AcFun 固定分区 ID', type: 'text', hint: '设置后推荐分区直接使用该 ID（可选）' },
      { key: 'FIXED_PARTITION_ID_BILIBILI', label: 'bilibili 固定分区 ID', type: 'text' },
      { key: 'COVER_PROCESSING_MODE', label: '封面处理方式', type: 'select', options: [{ value: 'crop', label: '裁剪 (crop)' }, { value: 'contain', label: '留边 (contain)' }] },
    ],
  },
  {
    id: 'account',
    title: '账号与网络',
    icon: 'bi-globe2',
    desc: '平台账号、Cookies 与网络代理',
    fields: [
      { key: 'ACFUN_USERNAME', label: 'AcFun 用户名', type: 'text' },
      { key: 'ACFUN_PASSWORD', label: 'AcFun 密码', type: 'password', sensitive: true },
      { key: 'YOUTUBE_PROXY_ENABLED', label: '启用 YouTube 下载代理', type: 'toggle' },
      { key: 'YOUTUBE_PROXY_URL', label: '代理地址', type: 'text', placeholder: 'http://127.0.0.1:7890 或 socks5://…', full: true },
      { key: 'YOUTUBE_PROXY_USERNAME', label: '代理用户名', type: 'text' },
      { key: 'YOUTUBE_PROXY_PASSWORD', label: '代理密码', type: 'password', sensitive: true },
      { key: 'YOUTUBE_DOWNLOAD_THREADS', label: '下载线程数', type: 'number' },
      { key: 'YOUTUBE_DOWNLOAD_QUALITY_MODE', label: '画质模式', type: 'select', options: [{ value: 'highest', label: '最高画质' }, { value: 'manual', label: '手动指定上限' }] },
      { key: 'YOUTUBE_DOWNLOAD_MAX_HEIGHT', label: '画质上限', type: 'select', options: ['2160', '1440', '1080', '720', '480', '360'].map((v) => ({ value: v, label: `${v}p` })) },
      { key: 'YOUTUBE_THROTTLED_RATE', label: '限速', type: 'text', placeholder: '如 1M / 500K，留空不限' },
    ],
  },
  {
    id: 'moderation',
    title: '内容审核',
    icon: 'bi-shield-check',
    desc: '阿里云内容安全（上传前自动审核）',
    fields: [
      { key: 'CONTENT_MODERATION_ENABLED', label: '启用内容审核', type: 'toggle', hint: '启用后视频元信息将先经阿里云 Green 审核' },
      { key: 'ALIYUN_ACCESS_KEY_ID', label: 'AccessKey ID', type: 'text', sensitive: true },
      { key: 'ALIYUN_ACCESS_KEY_SECRET', label: 'AccessKey Secret', type: 'password', sensitive: true },
      { key: 'ALIYUN_CONTENT_MODERATION_REGION', label: '区域', type: 'text', placeholder: 'cn-shanghai' },
      { key: 'ALIYUN_TEXT_MODERATION_SERVICE', label: '文本审核服务', type: 'text', placeholder: 'comment_detection_pro' },
    ],
  },
  {
    id: 'ai',
    title: 'AI 模型',
    icon: 'bi-cpu',
    desc: 'OpenAI 兼容接口（标题/简介翻译、标签、分区）',
    fields: [
      { key: 'OPENAI_API_KEY', label: 'OpenAI API Key', type: 'password', sensitive: true, full: true },
      { key: 'OPENAI_BASE_URL', label: 'API 地址', type: 'text', placeholder: 'https://api.openai.com/v1', full: true },
      { key: 'OPENAI_MODEL_NAME', label: '模型名称', type: 'text', placeholder: 'gpt-3.5-turbo' },
      { key: 'OPENAI_TIMEOUT_SECONDS', label: '请求超时（秒）', type: 'number', hint: '思考模型建议 ≥300' },
      { key: 'OPENAI_THINKING_ENABLED', label: '主模型启用思考模式', type: 'toggle' },
      { key: 'SUBTITLE_OPENAI_API_KEY', label: '字幕翻译独立 Key', type: 'password', sensitive: true, hint: '留空则回退到上方 Key' },
      { key: 'SUBTITLE_OPENAI_BASE_URL', label: '字幕翻译独立地址', type: 'text', hint: '留空则回退到上方地址' },
      { key: 'SUBTITLE_OPENAI_MODEL_NAME', label: '字幕翻译模型', type: 'text' },
      { key: 'SUBTITLE_OPENAI_THINKING_ENABLED', label: '字幕翻译思考模式', type: 'toggle' },
    ],
  },
  {
    id: 'subtitle',
    title: '字幕处理',
    icon: 'bi-badge-cc',
    desc: '字幕翻译、质检、烧录与后处理',
    fields: [
      { key: 'SUBTITLE_TRANSLATION_ENABLED', label: '启用字幕翻译', type: 'toggle' },
      { key: 'YOUTUBE_AUTO_GENERATED_SUBTITLES_ENABLED', label: '下载 YouTube 自动字幕', type: 'toggle', hint: '关闭=不下载自动字幕（自动字幕有滚动式重复）；此时有人工字幕用人工字幕，无人工字幕则由语音识别(ASR)生成无重复字幕', full: true },
      { key: 'SUBTITLE_SOURCE_LANGUAGE', label: '源语言', type: 'text', placeholder: 'auto / en / ja / ko' },
      { key: 'SUBTITLE_TARGET_LANGUAGE', label: '目标语言', type: 'text', placeholder: 'zh / en / ja / ko' },
      { key: 'SUBTITLE_FONT_NAME', label: '烧录字体', type: 'text', hint: 'fonts/ 目录内的字体文件名' },
      { key: 'SUBTITLE_API_PROVIDER', label: '翻译服务商', type: 'text', placeholder: 'openai' },
      { key: 'SUBTITLE_BATCH_SIZE', label: '翻译批次大小', type: 'number' },
      { key: 'SUBTITLE_MAX_RETRIES', label: '翻译重试次数', type: 'number' },
      { key: 'SUBTITLE_RETRY_DELAY', label: '重试延迟（秒）', type: 'number' },
      { key: 'SUBTITLE_MAX_WORKERS', label: '翻译并发线程', type: 'number' },
      { key: 'SUBTITLE_EMBED_IN_VIDEO', label: '字幕烧录进视频', type: 'toggle' },
      { key: 'SUBTITLE_KEEP_ORIGINAL', label: '保留原始字幕文件', type: 'toggle' },
      { key: 'SUBTITLE_QC_ENABLED', label: '启用字幕质检', type: 'toggle', hint: '质量优先：质检失败则不烧录字幕，任务仍会完成' },
      { key: 'SUBTITLE_QC_PROVIDER', label: '质检服务商', type: 'text', placeholder: 'openai' },
      { key: 'SUBTITLE_QC_MODEL_NAME', label: '质检模型', type: 'text', hint: '留空回退字幕翻译/主模型' },
      { key: 'SUBTITLE_QC_THINKING_ENABLED', label: '质检思考模式', type: 'toggle' },
      { key: 'SUBTITLE_QC_THRESHOLD', label: '质检通过阈值 (0-1)', type: 'number', step: '0.05' },
      { key: 'SUBTITLE_QC_SAMPLE_MAX_ITEMS', label: '质检抽样条目上限', type: 'number' },
      { key: 'SUBTITLE_QC_MAX_CHARS', label: '质检最大字符数', type: 'number' },
      { key: 'SUBTITLE_NORMALIZE_PUNCTUATION', label: '标准化标点', type: 'toggle' },
      { key: 'SUBTITLE_FILTER_FILLER_WORDS', label: '过滤填充词', type: 'toggle', hint: '如 um、uh 等' },
      { key: 'SUBTITLE_MAX_LINE_LENGTH_ENABLED', label: '限制每行字符数', type: 'toggle' },
      { key: 'SUBTITLE_MAX_LINE_LENGTH', label: '每行最大字符数', type: 'number' },
      { key: 'SUBTITLE_MAX_LINES_ENABLED', label: '限制字幕行数', type: 'toggle' },
      { key: 'SUBTITLE_MAX_LINES', label: '每条最大行数', type: 'number' },
      { key: 'SUBTITLE_TIME_OFFSET_ENABLED', label: '启用时间偏移', type: 'toggle' },
      { key: 'SUBTITLE_TIME_OFFSET_S', label: '时间偏移（秒）', type: 'number', step: '0.1' },
      { key: 'SUBTITLE_MIN_CUE_DURATION_ENABLED', label: '启用最短时长', type: 'toggle' },
      { key: 'SUBTITLE_MIN_CUE_DURATION_S', label: '最短时长（秒）', type: 'number', step: '0.1' },
      { key: 'SUBTITLE_MERGE_GAP_ENABLED', label: '启用间隙合并', type: 'toggle' },
      { key: 'SUBTITLE_MERGE_GAP_S', label: '合并间隙（秒）', type: 'number', step: '0.1' },
      { key: 'SUBTITLE_MIN_TEXT_LENGTH_ENABLED', label: '启用最短文本长度', type: 'toggle' },
      { key: 'SUBTITLE_MIN_TEXT_LENGTH', label: '最短文本长度', type: 'number' },
    ],
  },
  {
    id: 'speech',
    title: '语音识别',
    icon: 'bi-mic',
    desc: '无字幕视频的 ASR 转写（Whisper / Voxtral）与 VAD',
    fields: [
      { key: 'SPEECH_RECOGNITION_ENABLED', label: '启用语音识别', type: 'toggle' },
      { key: 'SPEECH_RECOGNITION_PROVIDER', label: '识别引擎', type: 'select', options: [{ value: 'whisper', label: 'Whisper（OpenAI 兼容）' }, { value: 'voxtral', label: 'Voxtral（Mistral）' }] },
      { key: 'WHISPER_API_KEY', label: 'Whisper API Key', type: 'password', sensitive: true },
      { key: 'WHISPER_BASE_URL', label: 'Whisper 地址', type: 'text', hint: '留空回退 OpenAI 地址' },
      { key: 'WHISPER_MODEL_NAME', label: 'Whisper 模型', type: 'text', placeholder: 'whisper-1' },
      { key: 'WHISPER_LANGUAGE', label: '强制语言', type: 'text', hint: '如 en / zh，空=自动检测' },
      { key: 'WHISPER_PROMPT', label: '转写提示词', type: 'textarea', hint: '引导生成，减少幻觉；部分 OpenAI 兼容端点（如 grok-stt 网关）不支持 prompt，填了会自动去掉重试', full: true },
      { key: 'WHISPER_TRANSLATE', label: '转写时翻译为英文', type: 'toggle' },
      { key: 'WHISPER_MAX_RETRIES', label: '转写重试次数', type: 'number' },
      { key: 'WHISPER_RETRY_DELAY_S', label: '重试延迟（秒）', type: 'number', step: '0.5' },
      { key: 'TTS_DUB_ENABLED', label: '启用配音（替换原声）', type: 'toggle', hint: '用翻译后字幕合成为语音替换原声，背景音保持不变' },
      { key: 'TTS_DUB_API_KEY', label: 'Fish Audio API Key', type: 'password', sensitive: true },
      { key: 'TTS_DUB_BASE_URL', label: 'Fish Audio 地址', type: 'text', hint: '默认 https://api.fish.audio' },
      { key: 'TTS_DUB_MODEL', label: 'TTS 模型', type: 'text', placeholder: 's2.1-pro-free' },
      { key: 'TTS_DUB_REFERENCE_MODE', label: '声音来源', type: 'select', options: [{ value: 'auto', label: '自动克隆原说话人' }, { value: 'voice_id', label: '固定声音 ID' }, { value: 'none', label: '默认音色' }] },
      { key: 'TTS_DUB_VOICE_ID', label: '声音 ID（reference_id）', type: 'text', hint: '预建克隆模型 ID；声音来源选固定时生效' },
      { key: 'TTS_DUB_SPEED', label: '语速', type: 'number', step: '0.1', hint: '0.5–2.0，超窗自动加速适配' },
      { key: 'TTS_DUB_BACKGROUND_MODE', label: '背景处理', type: 'select', options: [{ value: 'separate', label: '分离伴奏（推荐，保持背景音）' }, { value: 'duck', label: '压低原声（更快，保留部分原声）' }] },
      { key: 'TTS_DUB_MAX_DURATION_MINUTES', label: '分离上限（分钟）', type: 'number', hint: '超过自动转压低模式（保护 CPU）' },
      { key: 'TTS_DUB_MAX_RETRIES', label: '合成重试次数', type: 'number' },
      { key: 'TTS_DUB_RETRY_DELAY', label: '重试延迟（秒）', type: 'number' },
      { key: 'VOXTRAL_API_KEY', label: 'Voxtral API Key', type: 'password', sensitive: true },
      { key: 'VOXTRAL_BASE_URL', label: 'Voxtral 地址', type: 'text' },
      { key: 'VOXTRAL_MODEL_NAME', label: 'Voxtral 模型', type: 'text' },
      { key: 'VOXTRAL_DIARIZE', label: '启用说话人分离', type: 'toggle' },
      { key: 'VOXTRAL_CONTEXT_BIAS', label: '上下文偏置', type: 'text' },
      { key: 'VOXTRAL_LANGUAGE', label: '强制语言', type: 'text' },
      { key: 'VOXTRAL_MAX_AUDIO_DURATION_S', label: '最大音频时长（秒）', type: 'number' },
      { key: 'VAD_ENABLED', label: '启用 VAD 语音活动检测', type: 'toggle' },
      { key: 'VAD_SILERO_THRESHOLD', label: 'VAD 阈值', type: 'number', step: '0.05' },
      { key: 'VAD_SILERO_MIN_SPEECH_MS', label: '最短语音（ms）', type: 'number' },
      { key: 'VAD_SILERO_MIN_SILENCE_MS', label: '最短静音（ms）', type: 'number' },
      { key: 'VAD_SILERO_MAX_SPEECH_S', label: '最长语音（秒）', type: 'number' },
      { key: 'VAD_SILERO_SPEECH_PAD_MS', label: '边界填充（ms）', type: 'number' },
      { key: 'VAD_MAX_SEGMENT_S', label: '最大搜索窗（秒）', type: 'number', step: '0.5' },
      { key: 'AUDIO_CHUNK_WINDOW_S', label: '音频分片窗口（秒）', type: 'number', step: '0.5' },
      { key: 'AUDIO_CHUNK_OVERLAP_S', label: '分片重叠（秒）', type: 'number', step: '0.1' },
      { key: 'VAD_MERGE_GAP_S', label: '合并间隙（秒）', type: 'number', step: '0.05' },
      { key: 'VAD_MIN_SEGMENT_S', label: '最短片段（秒）', type: 'number', step: '0.1' },
      { key: 'VAD_MAX_SEGMENT_S_FOR_SPLIT', label: '拆分上限（秒）', type: 'number', step: '0.5' },
    ],
  },
  {
    id: 'video',
    title: '视频转码',
    icon: 'bi-film',
    desc: '字幕烧录的硬件/CPU 编码与 FFmpeg',
    fields: [
      { key: 'VIDEO_ENCODER', label: '编码器', type: 'select', options: [{ value: 'auto', label: '自动检测' }, { value: 'cpu', label: 'CPU (H.264)' }, { value: 'nvidia', label: 'NVIDIA (HEVC)' }, { value: 'intel', label: 'Intel (HEVC)' }, { value: 'amd', label: 'AMD (HEVC)' }] },
      { key: 'VIDEO_CPU_PRESET', label: 'CPU 常规预设', type: 'select', options: ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'].map((v) => ({ value: v, label: v })) },
      { key: 'VIDEO_CPU_PRESET_HD', label: 'CPU 高清预设', type: 'select', options: ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'].map((v) => ({ value: v, label: v })), hint: '1440p+ 且超 10 分钟时使用' },
      { key: 'VIDEO_CUSTOM_PARAMS_ENABLED', label: '启用自定义编码参数', type: 'toggle' },
      { key: 'VIDEO_CUSTOM_PARAMS', label: '自定义 FFmpeg 参数', type: 'textarea', placeholder: '例如：-preset faster -crf 23', full: true },
      { key: 'FFMPEG_LOCATION', label: '自定义 FFmpeg 路径', type: 'text', hint: '留空使用内置版本' },
      { key: 'FFMPEG_AUTO_DOWNLOAD', label: 'Windows 自动补齐 FFmpeg', type: 'toggle' },
    ],
  },
  {
    id: 'monitor',
    title: '监控与维护',
    icon: 'bi-broadcast-pin',
    desc: 'YouTube API、日志与下载清理',
    fields: [
      { key: 'YOUTUBE_API_KEY', label: 'YouTube Data API 密钥', type: 'password', sensitive: true, full: true },
      { key: 'YOUTUBE_API_PROXY_ENABLED', label: '监控 API 独立代理', type: 'toggle' },
      { key: 'YOUTUBE_API_PROXY_URL', label: '监控代理地址', type: 'text', full: true },
      { key: 'YOUTUBE_API_PROXY_USERNAME', label: '监控代理用户名', type: 'text' },
      { key: 'YOUTUBE_API_PROXY_PASSWORD', label: '监控代理密码', type: 'password', sensitive: true },
      { key: 'LOG_CLEANUP_ENABLED', label: '启用日志自动清理', type: 'toggle' },
      { key: 'LOG_CLEANUP_HOURS', label: '日志保留时长（小时）', type: 'number' },
      { key: 'LOG_CLEANUP_INTERVAL', label: '日志清理间隔（小时）', type: 'number' },
      { key: 'DOWNLOAD_CLEANUP_ENABLED', label: '启用下载自动清理', type: 'toggle' },
      { key: 'DOWNLOAD_CLEANUP_HOURS', label: '下载保留时长（小时）', type: 'number' },
      { key: 'DOWNLOAD_CLEANUP_INTERVAL', label: '下载清理间隔（小时）', type: 'number' },
    ],
  },
  {
    id: 'notify',
    title: '通知推送',
    icon: 'bi-bell',
    desc: '企业微信 / Server酱 / message-pusher',
    fields: [
      { key: 'NOTIFY_ENABLED', label: '启用消息推送', type: 'toggle' },
      { key: 'NOTIFY_EVENT_TASK_ADDED', label: '任务添加事件', type: 'toggle' },
      { key: 'NOTIFY_EVENT_TASK_COMPLETED', label: '任务完成事件', type: 'toggle' },
      { key: 'NOTIFY_EVENT_TASK_FAILED', label: '任务失败事件', type: 'toggle' },
      { key: 'NOTIFY_EVENT_LOGIN_SUCCESS', label: '登录成功事件', type: 'toggle' },
      { key: 'NOTIFY_EVENT_LOGIN_LOCKED', label: '登录锁定事件', type: 'toggle' },
      { key: 'NOTIFY_EVENT_QR_LOGIN_SUCCESS', label: '扫码登录成功事件', type: 'toggle' },
      { key: 'NOTIFY_EVENT_QR_LOGIN_FAILED', label: '扫码登录失败事件', type: 'toggle' },
      { key: 'NOTIFY_WECOM_ENABLED', label: '启用企业微信', type: 'toggle' },
      { key: 'NOTIFY_WECOM_WEBHOOK_URL', label: '企业微信 Webhook', type: 'text', full: true },
      { key: 'NOTIFY_SERVERCHAN_ENABLED', label: '启用 Server酱', type: 'toggle' },
      { key: 'NOTIFY_SERVERCHAN_SENDKEY', label: 'Server酱 SendKey', type: 'password', sensitive: true },
      { key: 'NOTIFY_MESSAGE_PUSHER_ENABLED', label: '启用 message-pusher', type: 'toggle' },
      { key: 'NOTIFY_MESSAGE_PUSHER_SERVER', label: '服务地址', type: 'text', full: true },
      { key: 'NOTIFY_MESSAGE_PUSHER_USERNAME', label: '用户名', type: 'text' },
      { key: 'NOTIFY_MESSAGE_PUSHER_TOKEN', label: 'Token', type: 'password', sensitive: true },
      { key: 'NOTIFY_MESSAGE_PUSHER_CHANNEL', label: '频道标识', type: 'text' },
    ],
  },
  {
    id: 'security',
    title: '安全',
    icon: 'bi-shield-lock',
    desc: '登录保护、密码与 Telegram Bot Token',
    fields: [
      { key: 'password_protection_enabled', label: '启用密码保护', type: 'toggle', hint: '开启后访问控制台需输入管理密码' },
      { key: 'LOGIN_MAX_FAILED_ATTEMPTS', label: '最大失败次数', type: 'number', hint: '达到后触发临时锁定' },
      { key: 'LOGIN_LOCKOUT_MINUTES', label: '锁定时长（分钟）', type: 'number' },
      { key: 'LOGIN_SESSION_TIMEOUT_MINUTES', label: '会话超时（分钟）', type: 'number', hint: '最小 1 分钟，访问会自动续期' },
    ],
  },
]

const PROMPTS = [
  { id: 'SUBTITLE_TRANSLATE', label: '字幕翻译主提示词' },
  { id: 'SUBTITLE_TRANSLATE_STRICT', label: '字幕翻译严格补救提示词' },
  { id: 'METADATA_TRANSLATE', label: '标题/简介翻译主提示词' },
  { id: 'METADATA_DESC_RETRY', label: '简介重试提示词' },
]

/* ================= 状态 ================= */
const toast = useToastStore()

const loading = ref(true)
const form = reactive<Record<string, any>>({})
const passwordSet = ref(false)
const tgbotState = ref<Record<string, unknown>>({})
const cookiecloudStatus = ref<Record<string, unknown>>({})

const newPassword = ref('')
const confirmPassword = ref('')

const activeSection = ref('run')
const sectionsRef = ref<Record<string, HTMLElement | null>>({})

const cookieFiles = reactive<{ youtube: File | null; acfun: File | null; bilibili: File | null }>({
  youtube: null,
  acfun: null,
  bilibili: null,
})

async function load() {
  loading.value = true
  try {
    const res = (await settingsApi.get()) as unknown as {
      config: Record<string, unknown>
      tgbot_token_state: Record<string, unknown>
      cookiecloud_status?: Record<string, unknown>
    }
    for (const key of Object.keys(res.config ?? {})) {
      form[key] = res.config[key]
    }
    passwordSet.value = !!res.config.password_set
    tgbotState.value = res.tgbot_token_state ?? {}
    cookiecloudStatus.value = res.config.COOKIECLOUD_LAST_SYNC_AT
      ? {
          at: res.config.COOKIECLOUD_LAST_SYNC_AT,
          status: res.config.COOKIECLOUD_LAST_SYNC_STATUS,
          message: res.config.COOKIECLOUD_LAST_SYNC_MESSAGE,
        }
      : {}
  } catch (e) {
    toast.error('加载设置失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  window.addEventListener('scroll', onSettingsScroll, { passive: true })
})

function boolOf(v: unknown): boolean {
  if (typeof v === 'boolean') return v
  return ['true', '1', 'on', 'yes'].includes(String(v ?? '').toLowerCase())
}

function setToggle(key: string, val: boolean) {
  form[key] = val
}

/* ---- 保存 ---- */
const saveOpen = ref(false)
const saveProgress = ref<{ message: string; detail: string; percent: number | null; done: boolean; success: boolean; messages: { category: string; text: string }[] } | null>(null)
const saveSubmitting = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function saveSettings() {
  if (saveSubmitting.value) return
  if (boolOf(form.password_protection_enabled) && newPassword.value) {
    if (newPassword.value !== confirmPassword.value) {
      toast.warning('两次输入的新密码不一致')
      return
    }
    if (newPassword.value.length < 6) {
      toast.warning('新密码至少需要 6 个字符')
      return
    }
  }

  saveSubmitting.value = true
  const fd = new FormData()
  for (const section of SECTIONS) {
    for (const f of section.fields) {
      const v = form[f.key]
      if (v === undefined || v === null) continue
      if (f.type === 'toggle') {
        fd.append(f.key, boolOf(v) ? 'on' : 'off')
      } else {
        fd.append(f.key, String(v))
      }
    }
  }
  for (const prompt of PROMPTS) {
    const mode = form[`${prompt.id}_MODE`]
    const text = form[`${prompt.id}_TEXT`]
    if (mode !== undefined) fd.append(`${prompt.id}_MODE`, String(mode))
    if (text !== undefined) fd.append(`${prompt.id}_TEXT`, String(text ?? ''))
  }
  if (newPassword.value) {
    fd.append('new_password', newPassword.value)
    fd.append('confirm_password', confirmPassword.value)
  }
  if (cookieFiles.youtube) fd.append('youtube_cookies_file', cookieFiles.youtube)
  if (cookieFiles.acfun) fd.append('acfun_cookies_file', cookieFiles.acfun)
  if (cookieFiles.bilibili) fd.append('bilibili_cookies_file', cookieFiles.bilibili)

  try {
    const res = (await settingsApi.save(fd)) as unknown as { operation_id?: string; success: boolean }
    if (!res.operation_id) {
      toast.success('设置已保存')
      saveSubmitting.value = false
      return
    }
    lastOperationId = res.operation_id
    saveOpen.value = true
    saveProgress.value = { message: '正在保存设置', detail: '保存任务已创建，正在后台执行。', percent: null, done: false, success: false, messages: [] }
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(pollSave, 900)
  } catch (e) {
    toast.error('保存失败', e instanceof ApiError ? e.message : '请稍后重试')
    saveSubmitting.value = false
  }
}

async function pollSave() {
  try {
    const p = (await settingsApi.saveProgress(lastOperationId)) as unknown as {
      found: boolean; message: string; detail: string; percent: number | null
      done: boolean; success: boolean; messages: { category: string; text: string }[]
    }
    if (!p.found) {
      finishSave(false, '保存状态已丢失')
      return
    }
    saveProgress.value = { message: p.message, detail: p.detail, percent: p.percent, done: p.done, success: p.success, messages: p.messages ?? [] }
    if (p.done) {
      finishSave(p.success, p.message)
    }
  } catch {
    finishSave(false, '无法获取保存进度')
  }
}

let lastOperationId = ''

function finishSave(success: boolean, message: string) {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  saveSubmitting.value = false
  saveOpen.value = false
  if (success) toast.success('设置已保存', message)
  else toast.warning('保存结束', message)
  newPassword.value = ''
  confirmPassword.value = ''
  cookieFiles.youtube = null
  cookieFiles.acfun = null
  cookieFiles.bilibili = null
  load()
}

/* ---- CookieCloud ---- */
const cookiecloudBusy = ref(false)

async function testCookiecloud() {
  cookiecloudBusy.value = true
  try {
    const res = await settingsApi.testCookiecloud()
    if (res.success) toast.success('CookieCloud 连接成功', res.message)
    else toast.error('CookieCloud 测试失败', res.message)
  } catch (e) {
    toast.error('CookieCloud 测试失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    cookiecloudBusy.value = false
  }
}

async function syncCookiecloud() {
  cookiecloudBusy.value = true
  try {
    const res = await settingsApi.syncCookiecloud()
    if (res.success) toast.success('CookieCloud 同步成功', res.message)
    else toast.error('CookieCloud 同步失败', res.message)
    load()
  } catch (e) {
    toast.error('CookieCloud 同步失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    cookiecloudBusy.value = false
  }
}

/* ---- 扫码登录 ---- */
const qrModal = ref<{ open: boolean; platform: 'acfun' | 'bilibili'; image: string; sessionId: string; status: string }>({
  open: false,
  platform: 'acfun',
  image: '',
  sessionId: '',
  status: '',
})
let qrTimer: ReturnType<typeof setInterval> | null = null

async function startQr(platform: 'acfun' | 'bilibili') {
  try {
    const api = platform === 'acfun' ? settingsApi.acfunQrStart : settingsApi.bilibiliQrStart
    const res = (await api()) as unknown as { success: boolean; session_id?: string; image_base64?: string; mime_type?: string }
    if (!res.success || !res.session_id) {
      toast.error('发起扫码登录失败', '请稍后重试')
      return
    }
    qrModal.value = {
      open: true,
      platform,
      image: `data:${res.mime_type ?? 'image/png'};base64,${res.image_base64 ?? ''}`,
      sessionId: res.session_id,
      status: 'waiting',
    }
    if (qrTimer) clearInterval(qrTimer)
    qrTimer = setInterval(pollQr, 1500)
  } catch (e) {
    toast.error('发起扫码登录失败', e instanceof ApiError ? e.message : '请稍后重试')
  }
}

async function pollQr() {
  const m = qrModal.value
  if (!m.open || !m.sessionId) return
  try {
    const api = m.platform === 'acfun' ? settingsApi.acfunQrStatus : settingsApi.bilibiliQrStatus
    const res = (await api(m.sessionId)) as unknown as { success: boolean; status?: string; message?: string }
    if (!res.success) {
      closeQr()
      toast.error('扫码登录失败', res.message)
      return
    }
    const status = res.status ?? ''
    if (status === 'done') {
      closeQr()
      toast.success('扫码登录成功', `${m.platform === 'acfun' ? 'AcFun' : 'bilibili'} Cookies 已写入`)
      load()
    } else if (status === 'timeout') {
      closeQr()
      toast.warning('二维码已过期，请重新发起')
    } else if (status === 'failed') {
      closeQr()
      toast.error('扫码登录失败', res.message)
    } else {
      m.status = status
    }
  } catch {
    /* 忽略轮询错误 */
  }
}

function closeQr() {
  if (qrTimer) {
    clearInterval(qrTimer)
    qrTimer = null
  }
  qrModal.value.open = false
}

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (qrTimer) clearInterval(qrTimer)
  window.removeEventListener('scroll', onSettingsScroll)
})

/* ---- 通知测试 ---- */
const notifyTestBusy = ref('')
async function testNotify(channel: string) {
  notifyTestBusy.value = channel
  try {
    const res = await settingsApi.testNotification(channel)
    if (res.success) toast.success(res.message)
    else toast.error('发送失败', res.message)
  } catch (e) {
    toast.error('发送失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    notifyTestBusy.value = ''
  }
}

/* ---- TTS 合成测试 ---- */
const ttsTestBusy = ref(false)
async function testTts() {
  ttsTestBusy.value = true
  try {
    const res = await settingsApi.ttsTest('这是一段语音合成测试。')
    if (res.success) toast.success(res.message)
    else toast.error('合成失败', res.message)
  } catch (e) {
    toast.error('合成失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    ttsTestBusy.value = false
  }
}

/* ---- 公开说话人（Voice Library） ---- */
const voicesQuery = ref('')
const voiceList = ref<TtsVoice[]>([])
const voicesLoading = ref(false)
const voicePreviewBusyId = ref('')
let voiceAudio: HTMLAudioElement | null = null

async function loadVoices() {
  voicesLoading.value = true
  try {
    const res = await settingsApi.ttsVoices({ q: voicesQuery.value || undefined, page_size: 30 })
    voiceList.value = res.items ?? []
  } catch (e) {
    toast.error('加载说话人失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    voicesLoading.value = false
  }
}

async function previewVoice(v: TtsVoice) {
  voicePreviewBusyId.value = v.id
  try {
    const res = await settingsApi.ttsPreview(v.id)
    if (!res.audio_base64) {
      toast.error('试听失败', '无音频数据')
      return
    }
    const bin = atob(res.audio_base64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    const url = URL.createObjectURL(new Blob([bytes], { type: res.mime || 'audio/mpeg' }))
    if (voiceAudio) {
      voiceAudio.pause()
      URL.revokeObjectURL(voiceAudio.dataset.url || '')
    }
    voiceAudio = new Audio(url)
    voiceAudio.dataset.url = url
    await voiceAudio.play()
  } catch (e) {
    toast.error('试听失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    voicePreviewBusyId.value = ''
  }
}

function useVoice(v: TtsVoice) {
  form.TTS_DUB_VOICE_ID = v.id
  form.TTS_DUB_REFERENCE_MODE = 'voice_id'
  toast.success(`已选用说话人「${v.title}」`)
}

/* ---- TG Bot Token ---- */
const tgBusy = ref(false)
async function tgAction(action: 'generate' | 'revoke') {
  tgBusy.value = true
  try {
    const res = (await settingsApi.tgbotToken(action)) as unknown as { success: boolean; message?: string; token?: string; state?: Record<string, unknown> }
    if (res.success) {
      tgbotState.value = res.state ?? {}
      toast.success(res.message || '操作成功')
      if (res.token) {
        tgToken.value = res.token
      }
    } else {
      toast.error('操作失败', res.message)
    }
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
  } finally {
    tgBusy.value = false
  }
}
const tgToken = ref('')

/* ---- 维护操作 ---- */
const confirmState = ref<{ open: boolean; title: string; message: string; action: () => Promise<unknown> } | null>(null)
async function runConfirm() {
  if (!confirmState.value) return
  try {
    await confirmState.value.action()
    confirmState.value = null
  } catch (e) {
    toast.error('操作失败', e instanceof ApiError ? e.message : '请稍后重试')
    confirmState.value = null
  }
}
function clearAllLogs() {
  confirmState.value = {
    open: true,
    title: '清空日志',
    message: '将清空 app.log、task_manager.log 及所有任务日志文件，确定继续吗？',
    action: async () => {
      const r = await settingsApi.clearLogs({ all: true })
      toast.success(r.message || '日志已清空')
    },
  }
}
function cleanupDownloads() {
  confirmState.value = {
    open: true,
    title: '清理下载内容',
    message: '将删除超过保留时长的下载任务目录，确定继续吗？',
    action: async () => {
      const r = await settingsApi.cleanupDownloads({ hours: Number(form.DOWNLOAD_CLEANUP_HOURS ?? 72) })
      toast.success(r.message || '下载内容已清理')
    },
  }
}
function cleanupLogsOld() {
  confirmState.value = {
    open: true,
    title: '清理旧日志',
    message: `将删除 ${form.LOG_CLEANUP_HOURS ?? 168} 小时前的日志文件，确定继续吗？`,
    action: async () => {
      const r = await settingsApi.clearLogs({ hours: Number(form.LOG_CLEANUP_HOURS ?? 168) })
      toast.success(r.message || '日志已清理')
    },
  }
}

/* ---- 分区重置 ---- */
function resetSection(section: SectionDef) {
  const keys = section.fields.map((f) => f.key)
  confirmState.value = {
    open: true,
    title: `重置「${section.title}」`,
    message: `将把该分组的 ${keys.length} 个配置项恢复为默认值，确定继续吗？`,
    action: async () => {
      await settingsApi.resetGroup(keys)
      toast.success('已重置为默认值')
      load()
    },
  }
}

/* ---- 滚动高亮 ---- */
let pendingScrollTarget: string | null = null
let pendingPrevTop: number | null = null
let pendingScrollTimer: ReturnType<typeof setTimeout> | null = null

function scrollToSection(id: string) {
  activeSection.value = id
  // 平滑滚动期间把高亮钉在目标分组；到达目标或用户反向滚动时恢复位置跟随
  pendingScrollTarget = id
  pendingPrevTop = null
  if (pendingScrollTimer) clearTimeout(pendingScrollTimer)
  pendingScrollTimer = setTimeout(() => {
    pendingScrollTarget = null
  }, 1500)
  sectionsRef.value[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 页面滚动时按可见位置更新左侧菜单高亮（反向联动） */
function onSettingsScroll() {
  const threshold = 120 // 该值以下（页面顶部区域）视为"当前所在分组"
  if (pendingScrollTarget) {
    const targetEl = sectionsRef.value[pendingScrollTarget]
    if (targetEl) {
      const top = targetEl.getBoundingClientRect().top
      const reached = top <= threshold + 10
      const movingAway = pendingPrevTop !== null && top > pendingPrevTop + 2
      if (reached || movingAway) {
        pendingScrollTarget = null
        pendingPrevTop = null
      } else {
        pendingPrevTop = top
        return // 仍在接近目标：高亮保持目标分组
      }
    } else {
      pendingScrollTarget = null
    }
  }
  const sections = Object.entries(sectionsRef.value).filter(([, el]) => el)
  if (!sections.length) return
  let current = sections[0][0]
  for (const [id, el] of sections) {
    if ((el as HTMLElement).getBoundingClientRect().top <= threshold) current = id
  }
  // 滚动到底部时选中最后一组
  const nearBottom =
    window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8
  if (nearBottom) current = sections[sections.length - 1][0]
  if (current !== activeSection.value) activeSection.value = current
}
</script>

<template>
  <div>
    <div class="page-header">
      <div class="page-header-text">
        <h1 class="page-title">设置中心</h1>
        <p class="page-subtitle">配置搬运流水线、平台账号与系统维护</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" :disabled="saveSubmitting" @click="saveSettings">
          <span v-if="saveSubmitting" class="spinner spinner-sm"></span>
          <i v-else class="bi bi-check-lg"></i> 保存全部设置
        </button>
      </div>
    </div>

    <div class="settings-layout">
      <!-- 分组导航 -->
      <aside class="settings-nav card">
        <button
          v-for="section in SECTIONS"
          :key="section.id"
          class="settings-nav-item"
          :class="{ active: activeSection === section.id }"
          @click="scrollToSection(section.id)"
        >
          <i class="bi" :class="section.icon"></i>
          <span>{{ section.title }}</span>
        </button>
      </aside>

      <!-- 内容 -->
      <div class="settings-content">
        <div v-if="loading" class="card card-pad">
          <UiSkeleton :rows="14" />
        </div>

        <template v-else>
          <!-- 账号与网络：Cookies / 扫码 / CookieCloud 附加卡片 -->
          <section
            v-for="section in SECTIONS"
            :key="section.id"
            :ref="(el) => (sectionsRef[section.id] = el as HTMLElement | null)"
            class="card section-card"
          >
            <div class="card-header">
              <div class="card-title">
                <i class="bi" :class="section.icon"></i> {{ section.title }}
              </div>
              <button class="btn btn-ghost btn-sm" @click="resetSection(section)">
                <i class="bi bi-arrow-counterclockwise"></i> 重置本组
              </button>
            </div>
            <div v-if="section.desc" class="section-desc">{{ section.desc }}</div>
            <div class="card-body fields-grid">
              <div v-for="f in section.fields" :key="f.key" class="field" :class="{ 'field-full': f.full }">
                <template v-if="f.type === 'toggle'">
                  <div class="toggle-field">
                    <UiToggle
                      :model-value="boolOf(form[f.key])"
                      @update:model-value="setToggle(f.key, $event)"
                    />
                    <div class="grow">
                      <div class="fs-md">{{ f.label }}</div>
                      <div v-if="f.hint" class="fs-xs text-muted">{{ f.hint }}</div>
                    </div>
                  </div>
                </template>
                <template v-else>
                  <span class="field-label">
                    {{ f.label }}
                    <span v-if="f.sensitive" class="sensitive-tag">敏感</span>
                  </span>
                  <input
                    v-if="f.type === 'text' || f.type === 'password' || f.type === 'number'"
                    v-model="form[f.key]"
                    :type="f.type === 'number' ? 'number' : f.type"
                    :step="f.step"
                    class="input"
                    :placeholder="f.placeholder"
                    :autocomplete="f.sensitive ? 'new-password' : 'off'"
                  />
                  <select v-else-if="f.type === 'select'" v-model="form[f.key]" class="select">
                    <option v-for="opt in f.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                  <textarea v-else v-model="form[f.key]" class="textarea" rows="3" :placeholder="f.placeholder"></textarea>
                  <span v-if="f.hint" class="field-hint">{{ f.hint }}</span>
                </template>
              </div>

              <!-- 账号与网络附加：Cookies 上传 -->
              <div v-if="section.id === 'account'" class="field field-full">
                <span class="field-label">Cookies 文件</span>
                <div class="cookie-uploads">
                  <div class="cookie-row">
                    <div class="cookie-meta">
                      <div class="fs-sm">YouTube Cookies</div>
                      <div class="fs-xs text-muted mono">{{ form.YOUTUBE_COOKIES_PATH || 'cookies/yt_cookies.txt' }}</div>
                    </div>
                    <label class="btn btn-secondary btn-sm cookie-pick">
                      <i class="bi bi-upload"></i> {{ cookieFiles.youtube ? cookieFiles.youtube.name : '上传文件' }}
                      <input type="file" class="visually-hidden" @change="(e) => (cookieFiles.youtube = (e.target as HTMLInputElement).files?.[0] ?? null)" />
                    </label>
                  </div>
                  <div class="cookie-row">
                    <div class="cookie-meta">
                      <div class="fs-sm">AcFun Cookies</div>
                      <div class="fs-xs text-muted mono">{{ form.ACFUN_COOKIES_PATH || 'cookies/ac_cookies.json' }}</div>
                    </div>
                    <div class="flex gap-2 items-center">
                      <label class="btn btn-secondary btn-sm cookie-pick">
                        <i class="bi bi-upload"></i> {{ cookieFiles.acfun ? cookieFiles.acfun.name : '上传文件' }}
                        <input type="file" class="visually-hidden" @change="(e) => (cookieFiles.acfun = (e.target as HTMLInputElement).files?.[0] ?? null)" />
                      </label>
                      <button class="btn btn-primary btn-sm" @click="startQr('acfun')">
                        <i class="bi bi-qr-code-scan"></i> 扫码登录
                      </button>
                    </div>
                  </div>
                  <div class="cookie-row">
                    <div class="cookie-meta">
                      <div class="fs-sm">bilibili Cookies</div>
                      <div class="fs-xs text-muted mono">{{ form.BILIBILI_COOKIES_PATH || 'cookies/bili_cookies.json' }}</div>
                    </div>
                    <div class="flex gap-2 items-center">
                      <label class="btn btn-secondary btn-sm cookie-pick">
                        <i class="bi bi-upload"></i> {{ cookieFiles.bilibili ? cookieFiles.bilibili.name : '上传文件' }}
                        <input type="file" class="visually-hidden" @change="(e) => (cookieFiles.bilibili = (e.target as HTMLInputElement).files?.[0] ?? null)" />
                      </label>
                      <button class="btn btn-primary btn-sm" @click="startQr('bilibili')">
                        <i class="bi bi-qr-code-scan"></i> 扫码登录
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- CookieCloud 附加 -->
              <div v-if="section.id === 'account'" class="field field-full">
                <span class="field-label">CookieCloud 同步</span>
                <div class="cookiecloud-box">
                  <div class="grid-2">
                    <label class="field">
                      <span class="field-label">服务地址</span>
                      <input v-model="form.COOKIECLOUD_SERVER_URL" class="input" placeholder="https://…" />
                    </label>
                    <label class="field">
                      <span class="field-label">UUID</span>
                      <input v-model="form.COOKIECLOUD_UUID" class="input" />
                    </label>
                    <label class="field">
                      <span class="field-label">密码</span>
                      <input v-model="form.COOKIECLOUD_PASSWORD" type="password" class="input" autocomplete="new-password" />
                    </label>
                    <label class="field">
                      <span class="field-label">加密方式</span>
                      <select v-model="form.COOKIECLOUD_CRYPTO_TYPE" class="select">
                        <option value="auto">自动 (auto)</option>
                        <option value="legacy">legacy</option>
                        <option value="aes-128-cbc-fixed">aes-128-cbc-fixed</option>
                      </select>
                    </label>
                  </div>
                  <div class="flex items-center justify-between flex-wrap gap-2 mt-3">
                    <UiToggle
                      :model-value="boolOf(form.COOKIECLOUD_ENABLED)"
                      label="启用 CookieCloud"
                      hint="保存设置后自动拉取 YouTube Cookies"
                      @update:model-value="setToggle('COOKIECLOUD_ENABLED', $event)"
                    />
                    <div class="flex gap-2">
                      <button class="btn btn-secondary btn-sm" :disabled="cookiecloudBusy" @click="testCookiecloud">
                        <span v-if="cookiecloudBusy" class="spinner spinner-sm"></span>
                        <i v-else class="bi bi-plug"></i> 测试连接
                      </button>
                      <button class="btn btn-primary btn-sm" :disabled="cookiecloudBusy" @click="syncCookiecloud">
                        <i class="bi bi-cloud-download"></i> 立即同步
                      </button>
                    </div>
                  </div>
                  <div v-if="cookiecloudStatus.at" class="callout mt-3" :class="cookiecloudStatus.status === 'success' ? 'callout-success' : 'callout-warning'">
                    <i class="bi bi-clock-history"></i>
                    <span>上次同步：{{ cookiecloudStatus.at }} · {{ cookiecloudStatus.message }}</span>
                  </div>
                </div>
              </div>

              <!-- 语音识别附加：TTS 合成测试 -->
              <div v-if="section.id === 'speech'" class="field field-full">
                <span class="field-label">测试语音合成（Fish Audio）</span>
                <div class="flex gap-2 flex-wrap">
                  <button class="btn btn-secondary btn-sm" :disabled="ttsTestBusy" @click="testTts">
                    <span v-if="ttsTestBusy" class="spinner spinner-sm"></span>
                    <i v-else class="bi bi-soundwave"></i> 合成测试
                  </button>
                </div>
              </div>

              <!-- 语音识别附加：公开说话人列表 -->
              <div v-if="section.id === 'speech'" class="field field-full">
                <span class="field-label">公开说话人（Voice Library）</span>
                <div class="flex gap-2 flex-wrap mb-2">
                  <input
                    v-model="voicesQuery"
                    class="input voice-search"
                    placeholder="按标题搜索…"
                    @keyup.enter="loadVoices"
                  />
                  <button class="btn btn-secondary btn-sm" :disabled="voicesLoading" @click="loadVoices">
                    <span v-if="voicesLoading" class="spinner spinner-sm"></span>
                    <i v-else class="bi bi-arrow-clockwise"></i> 刷新列表
                  </button>
                </div>
                <div v-if="voiceList.length" class="voice-list">
                  <div v-for="v in voiceList" :key="v.id" class="voice-row">
                    <div class="grow" style="min-width: 0">
                      <div class="voice-title clamp-1">
                        {{ v.title }}
                        <span v-if="v.languages?.length" class="voice-meta"> · {{ (v.languages || []).slice(0, 4).join(', ') }}</span>
                      </div>
                      <div class="fs-xs text-muted clamp-1 voice-meta">{{ (v.tags || []).slice(0, 4).join(' / ') || v.id.slice(0, 12) }}</div>
                    </div>
                    <button class="btn btn-ghost btn-sm" :disabled="voicePreviewBusyId === v.id" @click="previewVoice(v)">
                      <span v-if="voicePreviewBusyId === v.id" class="spinner spinner-sm"></span>
                      <i v-else class="bi bi-play-circle"></i> 试听
                    </button>
                    <button class="btn btn-secondary btn-sm" :disabled="form.TTS_DUB_VOICE_ID === v.id" @click="useVoice(v)">
                      <i class="bi bi-check2"></i> {{ form.TTS_DUB_VOICE_ID === v.id ? '已选用' : '使用' }}
                    </button>
                  </div>
                </div>
                <div v-else class="text-muted fs-xs">{{ voicesLoading ? '加载中…' : '点击「刷新列表」拉取公开说话人' }}</div>
              </div>

              <!-- 通知推送附加：测试按钮 -->
              <div v-if="section.id === 'notify'" class="field field-full">
                <span class="field-label">发送测试消息</span>
                <div class="flex gap-2 flex-wrap">
                  <button class="btn btn-secondary btn-sm" :disabled="notifyTestBusy !== ''" @click="testNotify('wecom')">
                    <span v-if="notifyTestBusy === 'wecom'" class="spinner spinner-sm"></span>
                    <i v-else class="bi bi-wechat"></i> 企业微信
                  </button>
                  <button class="btn btn-secondary btn-sm" :disabled="notifyTestBusy !== ''" @click="testNotify('serverchan')">
                    <span v-if="notifyTestBusy === 'serverchan'" class="spinner spinner-sm"></span>
                    <i v-else class="bi bi-send"></i> Server酱
                  </button>
                  <button class="btn btn-secondary btn-sm" :disabled="notifyTestBusy !== ''" @click="testNotify('message_pusher')">
                    <span v-if="notifyTestBusy === 'message_pusher'" class="spinner spinner-sm"></span>
                    <i v-else class="bi bi-chat-dots"></i> message-pusher
                  </button>
                </div>
              </div>

              <!-- 监控与维护附加：手动清理 -->
              <div v-if="section.id === 'monitor'" class="field field-full">
                <span class="field-label">手动维护</span>
                <div class="flex gap-2 flex-wrap">
                  <button class="btn btn-secondary btn-sm" @click="cleanupLogsOld">
                    <i class="bi bi-file-earmark-x"></i> 清理旧日志
                  </button>
                  <button class="btn btn-danger btn-sm" @click="clearAllLogs">
                    <i class="bi bi-trash3"></i> 清空全部日志
                  </button>
                  <button class="btn btn-danger btn-sm" @click="cleanupDownloads">
                    <i class="bi bi-folder-x"></i> 清理下载内容
                  </button>
                </div>
              </div>

              <!-- 安全附加：密码设置 + TG Token -->
              <div v-if="section.id === 'security'" class="field field-full">
                <span class="field-label">管理密码</span>
                <div class="grid-2">
                  <label class="field">
                    <span class="field-label">{{ passwordSet ? '新密码（留空保持不变）' : '设置密码' }}</span>
                    <input v-model="newPassword" type="password" class="input" autocomplete="new-password" placeholder="至少 6 位" />
                  </label>
                  <label class="field">
                    <span class="field-label">确认新密码</span>
                    <input v-model="confirmPassword" type="password" class="input" autocomplete="new-password" />
                  </label>
                </div>
                <div class="divider"></div>
                <div class="tgbot-box">
                  <div class="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <div class="fs-md">Telegram Bot API Token</div>
                      <div class="fs-xs text-muted">供自部署 Telegram 机器人 / 浏览器扩展调用</div>
                    </div>
                    <div class="flex gap-2">
                      <button class="btn btn-primary btn-sm" :disabled="tgBusy" @click="tgAction('generate')">
                        <span v-if="tgBusy" class="spinner spinner-sm"></span>
                        <i v-else class="bi bi-arrow-repeat"></i> {{ tgbotState.created_at ? '重新生成' : '生成 Token' }}
                      </button>
                      <button v-if="tgbotState.created_at" class="btn btn-danger btn-sm" :disabled="tgBusy" @click="tgAction('revoke')">
                        <i class="bi bi-x-octagon"></i> 撤销
                      </button>
                    </div>
                  </div>
                  <div v-if="tgToken" class="callout callout-success mt-3">
                    <i class="bi bi-key-fill"></i>
                    <span class="mono grow">{{ tgToken }}</span>
                    <CopyButton :text="tgToken" />
                  </div>
                  <div v-else-if="tgbotState.created_at" class="fs-xs text-muted mt-2">
                    当前 Token 尾号：<span class="mono">{{ tgbotState.last4 }}</span> · 创建于 {{ tgbotState.created_at }}
                  </div>
                </div>
              </div>

              <!-- Prompt 中心 -->
              <div v-if="section.id === 'subtitle' || section.id === 'ai'" class="field field-full">
                <template v-if="section.id === 'ai'">
                  <span class="field-label">Prompt 中心（AI 提示词）</span>
                  <div class="prompt-list">
                    <div v-for="prompt in PROMPTS" :key="prompt.id" class="prompt-item">
                      <div class="flex items-center justify-between flex-wrap gap-2">
                        <div class="fs-sm" style="font-weight: 600">{{ prompt.label }}</div>
                        <select v-model="form[`${prompt.id}_MODE`]" class="select select-sm">
                          <option value="builtin">使用内置</option>
                          <option value="append">内置 + 追加</option>
                          <option value="override">完全覆盖</option>
                        </select>
                      </div>
                      <textarea
                        v-if="String(form[`${prompt.id}_MODE`] ?? 'builtin') !== 'builtin'"
                        v-model="form[`${prompt.id}_TEXT`]"
                        class="textarea mt-2"
                        rows="3"
                        :placeholder="`自定义 Prompt 文本（最多 3000 字符）`"
                      ></textarea>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </section>

          <!-- 底部保存 -->
          <div class="card save-bar">
            <div class="flex items-center justify-between flex-wrap gap-3">
              <span class="fs-sm text-muted">修改后点击保存，配置将立即生效并同步到任务处理器</span>
              <button class="btn btn-primary" :disabled="saveSubmitting" @click="saveSettings">
                <span v-if="saveSubmitting" class="spinner spinner-sm"></span>
                <i v-else class="bi bi-check-lg"></i> 保存全部设置
              </button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 保存进度弹窗 -->
    <UiModal :open="saveOpen" title="正在保存设置" size="sm" :close-on-backdrop="false" @close="saveOpen = false">
      <div v-if="saveProgress">
        <div class="fs-md" style="font-weight: 600">{{ saveProgress.message }}</div>
        <div v-if="saveProgress.detail" class="fs-xs text-muted mt-2">{{ saveProgress.detail }}</div>
        <UiProgress class="mt-3" :value="saveProgress.percent ?? 0" :indeterminate="saveProgress.percent === null" tone="accent" />
        <div v-if="saveProgress.messages?.length" class="save-messages mt-3">
          <div v-for="(msg, i) in saveProgress.messages" :key="i" class="save-msg" :class="`save-msg--${msg.category}`">
            {{ msg.text }}
          </div>
        </div>
      </div>
    </UiModal>

    <!-- 扫码登录弹窗 -->
    <UiModal :open="qrModal.open" :title="`${qrModal.platform === 'acfun' ? 'AcFun' : 'bilibili'} 扫码登录`" size="sm" @close="closeQr">
      <div class="qr-box">
        <img v-if="qrModal.image" :src="qrModal.image" alt="登录二维码" class="qr-image" />
        <div class="qr-hint">
          <template v-if="qrModal.status === 'waiting'">请使用手机 App 扫码确认登录</template>
          <template v-else-if="qrModal.status === 'scanned'">已扫码，请在手机上确认</template>
          <template v-else-if="qrModal.status === 'confirmed'">已确认，正在写入 Cookies…</template>
          <template v-else>等待扫码…</template>
        </div>
      </div>
    </UiModal>

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
.voice-search {
  max-width: 220px;
}
.voice-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px;
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.voice-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  transition: background var(--dur-fast) var(--ease);
}
.voice-row:hover {
  background: var(--bg-hover);
}
.voice-title {
  font-size: var(--fs-sm);
  color: var(--text-primary);
}
.voice-meta {
  font-size: var(--fs-xs);
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

.settings-layout {
  display: grid;
  grid-template-columns: 216px minmax(0, 1fr);
  gap: var(--sp-5);
  align-items: start;
}
@media (max-width: 960px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
  .settings-nav {
    position: static;
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 4px;
    padding: 8px;
  }
}

.settings-nav {
  position: sticky;
  top: calc(var(--topbar-height) + var(--sp-6));
  padding: 8px;
}
.settings-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  text-align: left;
  transition: all var(--dur-fast) var(--ease);
}
.settings-nav-item:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.settings-nav-item.active {
  color: var(--accent);
  background: var(--accent-soft);
  font-weight: 600;
}
@media (max-width: 960px) {
  .settings-nav-item {
    width: auto;
  }
}

.settings-content {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  min-width: 0;
  scroll-margin-top: calc(var(--topbar-height) + var(--sp-4));
}
.section-card {
  scroll-margin-top: calc(var(--topbar-height) + var(--sp-4));
}
.section-desc {
  padding: 0 var(--sp-5);
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.fields-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4) var(--sp-5);
}
@media (max-width: 720px) {
  .fields-grid {
    grid-template-columns: 1fr;
  }
}
.field-full {
  grid-column: 1 / -1;
}
.toggle-field {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.sensitive-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 10px;
  font-weight: 600;
  vertical-align: 1px;
}

.cookie-uploads {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.cookie-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding: 12px 14px;
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.cookie-pick {
  cursor: pointer;
}

.cookiecloud-box,
.tgbot-box {
  padding: var(--sp-4);
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}
@media (max-width: 720px) {
  .grid-2 {
    grid-template-columns: 1fr;
  }
}

.prompt-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.prompt-item {
  padding: var(--sp-4);
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}
.select-sm {
  width: auto;
  height: 30px;
  padding: 4px 30px 4px 10px;
  font-size: var(--fs-sm);
}

.save-bar {
  padding: var(--sp-4) var(--sp-5);
}

.save-messages {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow-y: auto;
}
.save-msg {
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  background: var(--bg-raised);
  color: var(--text-secondary);
}
.save-msg--warning {
  background: var(--warning-soft);
  color: var(--warning);
}
.save-msg--danger {
  background: var(--danger-soft);
  color: var(--danger);
}
.save-msg--success {
  background: var(--success-soft);
  color: var(--success);
}

.qr-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-3);
}
.qr-image {
  width: 220px;
  height: 220px;
  border-radius: var(--radius-md);
  background: #fff;
  padding: 8px;
}
.qr-hint {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}
</style>
