<script setup lang="ts">
withDefaults(
  defineProps<{
    icon?: string
    title?: string
    description?: string
  }>(),
  { icon: 'bi-inbox', title: '暂无数据', description: '' },
)
</script>

<template>
  <div class="empty-state">
    <div class="empty-icon">
      <i class="bi" :class="icon"></i>
    </div>
    <div class="empty-title">{{ title }}</div>
    <div v-if="description" class="empty-desc">{{ description }}</div>
    <slot />
  </div>
</template>

<style scoped>
.empty-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text-secondary);
}
.empty-desc {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  max-width: 420px;
}
</style>
