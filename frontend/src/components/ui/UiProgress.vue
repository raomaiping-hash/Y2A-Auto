<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number | string | null | undefined
    indeterminate?: boolean
    tone?: 'accent' | 'success' | 'warning' | 'danger'
    label?: string
    striped?: boolean
  }>(),
  { indeterminate: false, tone: 'accent', striped: false },
)

const pct = computed(() => {
  if (props.indeterminate) return 100
  const v = Number(props.value)
  if (!Number.isFinite(v)) return 0
  return Math.max(0, Math.min(100, v))
})

const barClass = computed(() => [
  'progress-bar',
  `progress-bar--${props.tone}`,
  { striped: props.striped || props.indeterminate },
])
</script>

<template>
  <div class="ui-progress">
    <div class="progress">
      <div class="progress-bar" :class="barClass" :style="{ width: pct + '%' }"></div>
    </div>
    <span v-if="label !== undefined" class="progress-label">{{ label ?? '' }}</span>
  </div>
</template>

<style scoped>
.ui-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.ui-progress .progress {
  flex: 1;
}
.progress-bar--success { background: var(--success); }
.progress-bar--warning { background: var(--warning); }
.progress-bar--danger { background: var(--danger); }
.progress-label {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  white-space: nowrap;
}
</style>
