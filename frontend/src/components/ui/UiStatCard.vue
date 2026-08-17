<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string
    value: number | string
    icon?: string
    tone?: 'accent' | 'success' | 'warning' | 'danger' | 'info' | 'neutral'
    hint?: string
    loading?: boolean
  }>(),
  { tone: 'neutral', loading: false },
)
</script>

<template>
  <div class="stat-card card" :class="`stat-card--${tone}`">
    <div class="stat-card-body">
      <div class="stat-icon" :class="`stat-icon--${tone}`">
        <i class="bi" :class="icon"></i>
      </div>
      <div class="stat-meta">
        <div class="stat-label">{{ label }}</div>
        <div class="stat-value">
          <span v-if="loading" class="skeleton stat-skeleton"></span>
          <template v-else>{{ value }}</template>
        </div>
        <div v-if="hint" class="stat-hint">{{ hint }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  position: relative;
  overflow: hidden;
  transition: border-color var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.stat-card:hover {
  border-color: var(--border-default);
}
.stat-card-body {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-5);
}
.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  flex-shrink: 0;
}
.stat-icon--accent { background: var(--accent-soft); color: var(--accent); }
.stat-icon--success { background: var(--success-soft); color: var(--success); }
.stat-icon--warning { background: var(--warning-soft); color: var(--warning); }
.stat-icon--danger { background: var(--danger-soft); color: var(--danger); }
.stat-icon--info { background: var(--info-soft); color: var(--info); }
.stat-icon--neutral { background: var(--bg-raised); color: var(--text-secondary); }
.stat-label {
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}
.stat-value {
  font-size: var(--fs-2xl);
  font-weight: 700;
  line-height: 1.15;
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}
.stat-hint {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.stat-skeleton {
  display: inline-block;
  width: 44px;
  height: 28px;
}
.stat-card--accent::before,
.stat-card--success::before,
.stat-card--warning::before,
.stat-card--danger::before,
.stat-card--info::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--tone-color, transparent);
}
.stat-card--accent { --tone-color: var(--accent); }
.stat-card--success { --tone-color: var(--success); }
.stat-card--warning { --tone-color: var(--warning); }
.stat-card--danger { --tone-color: var(--danger); }
.stat-card--info { --tone-color: var(--info); }
</style>
