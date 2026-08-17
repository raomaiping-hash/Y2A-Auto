<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const password = ref('')
const error = ref('')
const submitting = ref(false)

const redirectTarget = computed(() => {
  const r = route.query.redirect
  return typeof r === 'string' && r.startsWith('/') ? r : '/'
})

const lockedText = computed(() => {
  if (!auth.lockedUntil) return ''
  const remain = Math.max(0, auth.lockedUntil * 1000 - Date.now())
  const m = Math.floor(remain / 60000)
  const s = Math.floor((remain % 60000) / 1000)
  return `登录已被临时锁定，请 ${m} 分 ${s} 秒后重试。`
})

async function submit() {
  if (!password.value || submitting.value) return
  error.value = ''
  submitting.value = true
  try {
    const res = await auth.login(password.value)
    if (res.success === false) {
      error.value = res.message || '登录失败'
      await auth.bootstrap()
      return
    }
    await router.replace(redirectTarget.value)
  } catch (e) {
    if (e instanceof ApiError) error.value = e.message
    else error.value = '登录失败，请稍后重试'
    await auth.bootstrap()
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-glow"></div>
    <div class="login-card">
      <div class="login-brand">
        <div class="login-logo"><i class="bi bi-play-btn-fill"></i></div>
        <h1 class="login-name">Y2A-Auto</h1>
        <p class="login-slogan">YouTube 自动搬运 · 控制台</p>
      </div>

      <form class="login-form" @submit.prevent="submit">
        <div v-if="lockedText" class="callout callout-danger login-callout">
          <i class="bi bi-lock-fill"></i>
          <span>{{ lockedText }}</span>
        </div>

        <label class="field">
          <span class="field-label">访问密码</span>
          <div class="login-input-wrap">
            <i class="bi bi-shield-lock-fill login-input-icon"></i>
            <input
              v-model="password"
              type="password"
              class="input login-input"
              placeholder="请输入管理密码"
              autocomplete="current-password"
              :disabled="!!lockedText"
              autofocus
            />
          </div>
          <span v-if="error" class="field-error">{{ error }}</span>
        </label>

        <button
          type="submit"
          class="btn btn-primary btn-lg login-submit"
          :disabled="!!lockedText || submitting || !password"
        >
          <span v-if="submitting" class="spinner" aria-hidden="true"></span>
          {{ submitting ? '验证中…' : '登 录' }}
        </button>
      </form>

      <p class="login-foot">会话保持 · 连续失败将触发临时锁定</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: hidden;
}
.login-glow {
  position: absolute;
  width: 720px;
  height: 720px;
  border-radius: 50%;
  background: radial-gradient(
    circle,
    rgba(109, 141, 255, 0.16) 0%,
    rgba(154, 108, 255, 0.08) 42%,
    transparent 70%
  );
  top: 50%;
  left: 50%;
  transform: translate(-50%, -58%);
  pointer-events: none;
}
.login-card {
  position: relative;
  width: min(420px, 100%);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-pop);
  padding: 44px 40px 28px;
}
.login-brand {
  text-align: center;
  margin-bottom: 32px;
}
.login-logo {
  width: 58px;
  height: 58px;
  margin: 0 auto 14px;
  border-radius: 16px;
  background: var(--accent-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 1.7rem;
  box-shadow: 0 6px 24px var(--accent-glow);
}
.login-name {
  font-size: var(--fs-xl);
  font-weight: 700;
}
.login-slogan {
  margin-top: 4px;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.login-callout {
  margin-bottom: var(--sp-4);
}
.login-input-wrap {
  position: relative;
}
.login-input-icon {
  position: absolute;
  left: 13px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
}
.login-input {
  padding-left: 38px;
  height: 44px;
}
.login-submit {
  width: 100%;
  margin-top: var(--sp-5);
}
.login-foot {
  margin-top: 22px;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
</style>
