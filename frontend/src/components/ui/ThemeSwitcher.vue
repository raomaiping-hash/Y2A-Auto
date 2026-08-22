<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useThemeStore, type ThemeMode } from '@/stores/theme'

const theme = useThemeStore()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const options: { mode: ThemeMode; label: string; icon: string }[] = [
  { mode: 'dark', label: '深色', icon: 'bi-moon-stars-fill' },
  { mode: 'light', label: '浅色', icon: 'bi-sun-fill' },
  { mode: 'system', label: '跟随系统', icon: 'bi-circle-half' },
]

const triggerIcon = ref<Record<ThemeMode, string>>({
  dark: 'bi-moon-stars-fill',
  light: 'bi-sun-fill',
  system: 'bi-circle-half',
})

function onDocClick(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}

function pick(mode: ThemeMode) {
  theme.setMode(mode)
  open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="root" class="theme-switcher">
    <button
      class="btn-icon"
      :aria-label="`主题：${options.find(o => o.mode === theme.mode)?.label ?? theme.mode}`"
      aria-haspopup="menu"
      :aria-expanded="open"
      title="界面主题"
      @click="open = !open"
    >
      <i class="bi" :class="triggerIcon[theme.mode]"></i>
    </button>
    <Transition name="dropdown">
      <div v-if="open" class="theme-menu" role="menu">
        <button
          v-for="opt in options"
          :key="opt.mode"
          role="menuitem"
          class="theme-item"
          :class="{ active: theme.mode === opt.mode }"
          @click="pick(opt.mode)"
        >
          <i class="bi" :class="opt.icon"></i>
          <span>{{ opt.label }}</span>
          <i v-if="theme.mode === opt.mode" class="bi bi-check2 theme-check"></i>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.theme-switcher {
  position: relative;
}
.theme-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 1100;
  min-width: 148px;
  padding: 5px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-pop);
}
.theme-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--text-primary);
  text-align: left;
  transition: background var(--dur-fast) var(--ease);
}
.theme-item:hover {
  background: var(--bg-hover);
}
.theme-item.active {
  color: var(--accent);
  background: var(--accent-soft);
}
.theme-check {
  margin-left: auto;
}
.theme-item:not(.active) .theme-check {
  display: none;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
