<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <div class="placeholder">
    <div class="spinner spinner-lg"></div>
    <p>{{ title }}页面正在建设中…</p>
  </div>
</template>

<style scoped>
.placeholder {
  min-height: 50vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-4);
  color: var(--text-muted);
}

@media (max-width: 767px) {
  .placeholder {
    min-height: 60vh;
    padding: var(--sp-6) var(--sp-4);
    text-align: center;
  }
  .placeholder p {
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}
</style>
