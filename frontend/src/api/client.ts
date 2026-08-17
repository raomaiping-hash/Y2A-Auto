/** 统一 fetch 封装：JSON、CSRF 头、401 处理、错误标准化 */

export class ApiError extends Error {
  status: number
  payload: Record<string, unknown>

  constructor(status: number, message: string, payload: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

export function getCsrfToken(): string | null {
  return csrfToken
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  formData?: FormData
  headers?: Record<string, string>
  signal?: AbortSignal
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, formData, headers = {}, signal } = options
  const isMutating = method !== 'GET'

  const finalHeaders: Record<string, string> = {
    ...headers,
  }
  if (isMutating && csrfToken) {
    finalHeaders['X-CSRF-Token'] = csrfToken
  }
  if (body !== undefined && !formData) {
    finalHeaders['Content-Type'] = 'application/json'
  }

  const res = await fetch(path, {
    method,
    headers: finalHeaders,
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
    credentials: 'same-origin',
    signal,
  })

  // SSE 之类由调用方自行处理
  if (res.status === 204) return undefined as T

  let data: Record<string, unknown> | null = null
  const contentType = res.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try {
      data = await res.json()
    } catch {
      /* ignore */
    }
  }

  if (!res.ok) {
    const msg =
      (data && typeof data.message === 'string' && data.message) ||
      (data && typeof data.error === 'string' && data.error) ||
      `请求失败 (HTTP ${res.status})`
    if (res.status === 401) {
      // 会话失效：回到登录页
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    }
    throw new ApiError(res.status, msg, data ?? {})
  }

  // 成功响应里若带 csrf_token 则刷新本地缓存
  if (data && typeof data.csrf_token === 'string') {
    setCsrfToken(data.csrf_token)
  }

  return data as T
}

/** 事件流（SSE）封装 */
export function openEventStream(
  path: string,
  onEvent: (event: Record<string, unknown>) => void,
  onError?: (err: unknown) => void,
): { close: () => void } {
  const source = new EventSource(path, { withCredentials: true })
  source.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data)
      onEvent(parsed)
    } catch {
      /* 忽略非 JSON 消息 */
    }
  }
  source.onerror = (e) => {
    onError?.(e)
  }
  return {
    close: () => source.close(),
  }
}
