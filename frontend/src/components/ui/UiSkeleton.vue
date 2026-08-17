<script setup lang="ts">
withDefaults(
  defineProps<{
    rows?: number
    lineHeight?: number
  }>(),
  { rows: 4, lineHeight: 18 },
)
</script>

<template>
  <div class="skeleton-list" role="status" aria-label="加载中">
    <div
      v-for="i in rows"
      :key="i"
      class="skeleton"
      :style="{ height: lineHeight + 'px', width: i === rows ? '62%' : '100%' }"
    ></div>
  </div>
</template>

<style scoped>
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: var(--sp-4);
}
</style>
