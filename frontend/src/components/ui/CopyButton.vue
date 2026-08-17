<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    text: string
    label?: string
    size?: 'sm' | 'md'
  }>(),
  { size: 'md' },
)

const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
  } catch {
    // 兼容非安全上下文
    const ta = document.createElement('textarea')
    ta.value = props.text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  copied.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1600)
}
</script>

<template>
  <button
    type="button"
    class="copy-btn"
    :class="`copy-btn--${size}`"
    :title="copied ? '已复制' : `复制${label ?? ''}`"
    @click="copy"
  >
    <i class="bi" :class="copied ? 'bi-check-lg' : 'bi-copy'"></i>
  </button>
</template>

<style scoped>
.copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  transition: all var(--dur-fast) var(--ease);
  flex-shrink: 0;
}
.copy-btn:hover {
  color: var(--accent);
  background: var(--accent-soft);
}
.copy-btn--sm {
  width: 22px;
  height: 22px;
  font-size: var(--fs-xs);
}
</style>
