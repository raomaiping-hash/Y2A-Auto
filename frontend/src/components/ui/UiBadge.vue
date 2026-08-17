<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    tone?: 'success' | 'warning' | 'danger' | 'info' | 'primary' | 'secondary' | 'purple'
    pulse?: boolean
    dot?: boolean
  }>(),
  { tone: 'secondary', pulse: false, dot: false },
)

const cls = computed(() => [`badge badge-${props.tone}`, { 'badge-pulse': props.pulse }])
</script>

<template>
  <span class="ui-badge" :class="cls">
    <span v-if="dot" class="badge-dot" aria-hidden="true"></span>
    <slot />
  </span>
</template>

<style scoped>
.ui-badge {
  display: inline-flex;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
</style>
