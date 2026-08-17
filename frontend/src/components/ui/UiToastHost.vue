<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const store = useToastStore()

const ICONS: Record<string, string> = {
  success: 'bi-check-circle-fill',
  error: 'bi-x-octagon-fill',
  warning: 'bi-exclamation-triangle-fill',
  info: 'bi-info-circle-fill',
}
</script>

<template>
  <Teleport to="body">
    <div class="toast-host" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="t in store.items" :key="t.id" class="toast" :class="`toast--${t.kind}`">
          <i class="toast-icon bi" :class="ICONS[t.kind]"></i>
          <div class="toast-body">
            <div class="toast-title">{{ t.title }}</div>
            <div v-if="t.message" class="toast-message">{{ t.message }}</div>
          </div>
          <button class="toast-close" aria-label="关闭" @click="store.remove(t.id)">
            <i class="bi bi-x"></i>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: calc(var(--topbar-height) + 12px);
  right: 16px;
  z-index: 1300;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(380px, calc(100vw - 32px));
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 13px 14px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-pop);
}
.toast-icon {
  font-size: 1.05rem;
  margin-top: 1px;
  flex-shrink: 0;
}
.toast--success .toast-icon { color: var(--success); }
.toast--error .toast-icon { color: var(--danger); }
.toast--warning .toast-icon { color: var(--warning); }
.toast--info .toast-icon { color: var(--info); }
.toast-body { flex: 1; min-width: 0; }
.toast-title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
}
.toast-message {
  margin-top: 2px;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  word-break: break-word;
}
.toast-close {
  color: var(--text-muted);
  font-size: 0.9rem;
  padding: 2px;
  border-radius: 4px;
  transition: color var(--dur-fast) var(--ease);
}
.toast-close:hover {
  color: var(--text-primary);
}

.toast-enter-active,
.toast-leave-active {
  transition: all var(--dur) var(--ease);
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(24px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(24px);
}
</style>
