import { defineStore } from 'pinia'
import { authApi } from '@/api/endpoints'
import { setCsrfToken } from '@/api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    booted: false,
    authenticated: false,
    passwordProtectionEnabled: false,
    lockedUntil: null as number | null,
    remainingAttempts: null as number | null,
  }),
  getters: {
    locked: (state): boolean =>
      !!state.lockedUntil && state.lockedUntil * 1000 > Date.now(),
  },
  actions: {
    /** 应用启动时调用：拉取会话状态 + CSRF token */
    async bootstrap() {
      try {
        const s = await authApi.session()
        this.authenticated = s.authenticated
        this.passwordProtectionEnabled = s.password_protection_enabled
        this.lockedUntil = s.locked_until
        this.remainingAttempts = s.remaining_attempts
        if (s.csrf_token) setCsrfToken(s.csrf_token)
      } finally {
        this.booted = true
      }
    },
    async login(password: string) {
      const res = await authApi.login(password)
      if (res.csrf_token) setCsrfToken(res.csrf_token)
      await this.bootstrap()
      return res
    },
    async logout() {
      try {
        await authApi.logout()
      } catch {
        /* 忽略登出错误 */
      }
      this.authenticated = false
      this.booted = true
    },
  },
})
