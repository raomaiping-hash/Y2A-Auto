import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light' | 'system'
export type ResolvedTheme = 'dark' | 'light'

const STORAGE_KEY = 'y2a-theme'

function readStoredMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'dark' || v === 'light' || v === 'system') return v
  } catch {
    /* localStorage 不可用时回退默认 */
  }
  return 'dark'
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return mode
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readStoredMode())
  const resolved = ref<ResolvedTheme>(resolveTheme(mode.value))

  function apply() {
    document.documentElement.dataset.theme = resolved.value
  }

  function setMode(next: ThemeMode) {
    mode.value = next
    resolved.value = resolveTheme(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* 忽略持久化失败 */
    }
    apply()
  }

  /** 应用启动时调用：立即生效并监听系统主题变化 */
  function init() {
    apply()
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', () => {
      if (mode.value === 'system') {
        resolved.value = resolveTheme('system')
        apply()
      }
    })
  }

  return { mode, resolved, setMode, init }
})
