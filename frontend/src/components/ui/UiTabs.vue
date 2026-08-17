<script setup lang="ts">
export interface TabItem {
  id: string
  label: string
  icon?: string
  badge?: number | string
}

defineProps<{
  tabs: TabItem[]
  modelValue: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()
</script>

<template>
  <div class="ui-tabs" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      role="tab"
      :aria-selected="modelValue === tab.id"
      class="ui-tab"
      :class="{ active: modelValue === tab.id }"
      @click="emit('update:modelValue', tab.id)"
    >
      <i v-if="tab.icon" class="bi" :class="tab.icon"></i>
      <span>{{ tab.label }}</span>
      <span v-if="tab.badge !== undefined" class="ui-tab-badge">{{ tab.badge }}</span>
    </button>
  </div>
</template>

<style scoped>
.ui-tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
}
.ui-tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-secondary);
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.ui-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}
.ui-tab.active {
  background: var(--bg-raised);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}
.ui-tab-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>
