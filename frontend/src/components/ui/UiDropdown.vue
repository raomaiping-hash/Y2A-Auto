<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

export interface DropdownItem {
  id: string
  label: string
  icon?: string
  danger?: boolean
  disabled?: boolean
}

const props = defineProps<{
  items: DropdownItem[]
  align?: 'left' | 'right'
}>()

const emit = defineEmits<{ select: [item: DropdownItem] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

function onDocClick(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}

function onSelectItem(item: DropdownItem) {
  open.value = false
  emit('select', item)
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="root" class="ui-dropdown">
    <button class="btn-icon" aria-haspopup="menu" :aria-expanded="open" @click="open = !open">
      <i class="bi bi-three-dots-vertical"></i>
    </button>
    <Transition name="dropdown">
      <div
        v-if="open"
        class="dropdown-menu"
        :class="`dropdown-menu--${align ?? 'right'}`"
        role="menu"
      >
        <button
          v-for="item in items"
          :key="item.id"
          role="menuitem"
          class="dropdown-item"
          :class="{ danger: item.danger }"
          :disabled="item.disabled"
          @click="onSelectItem(item)"
        >
          <i v-if="item.icon" class="bi" :class="item.icon"></i>
          {{ item.label }}
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.ui-dropdown {
  position: relative;
}
.dropdown-menu {
  position: absolute;
  top: calc(100% + 4px);
  z-index: 1100;
  min-width: 168px;
  padding: 5px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-pop);
}
.dropdown-menu--right { right: 0; }
.dropdown-menu--left { left: 0; }
.dropdown-item {
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
.dropdown-item:hover:not(:disabled) {
  background: var(--bg-hover);
}
.dropdown-item.danger {
  color: var(--danger);
}
.dropdown-item.danger:hover:not(:disabled) {
  background: var(--danger-soft);
}
.dropdown-item:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
