<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  totalPages: number
  total?: number
}>()

const emit = defineEmits<{ change: [page: number] }>()

const pages = computed<number[]>(() => {
  const list: number[] = []
  const total = Math.max(1, props.totalPages)
  for (let p = 1; p <= total; p++) {
    if (total <= 7 || p === 1 || p === total || Math.abs(p - props.page) <= 1) {
      list.push(p)
    }
  }
  const out: number[] = []
  let prev = 0
  for (const p of list) {
    if (prev && p - prev > 1) out.push(-1)
    out.push(p)
    prev = p
  }
  return out
})

function go(p: number) {
  if (p < 1 || p > props.totalPages || p === props.page) return
  emit('change', p)
}
</script>

<template>
  <div class="ui-pagination">
    <button class="page-btn" :disabled="page <= 1" aria-label="上一页" @click="go(page - 1)">
      <i class="bi bi-chevron-left"></i>
    </button>
    <template v-for="(p, i) in pages" :key="i">
      <span v-if="p === -1" class="page-ellipsis">…</span>
      <button v-else class="page-btn" :class="{ active: p === page }" @click="go(p)">
        {{ p }}
      </button>
    </template>
    <button
      class="page-btn"
      :disabled="page >= totalPages"
      aria-label="下一页"
      @click="go(page + 1)"
    >
      <i class="bi bi-chevron-right"></i>
    </button>
    <span v-if="total !== undefined" class="page-total">共 {{ total }} 条</span>
  </div>
</template>

<style scoped>
.ui-pagination {
  display: flex;
  align-items: center;
  gap: 4px;
}
.page-btn {
  min-width: 30px;
  height: 30px;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all var(--dur-fast) var(--ease);
}
.page-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.page-btn.active {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent);
  font-weight: 600;
}
.page-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.page-ellipsis {
  color: var(--text-muted);
  padding: 0 2px;
}
.page-total {
  margin-left: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
</style>
