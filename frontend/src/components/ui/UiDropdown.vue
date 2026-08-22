<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

export interface DropdownItem {
  id: string
  label: string
  icon?: string
  danger?: boolean
  disabled?: boolean
  divider?: boolean
  /** 只读头部项（如状态展示），不触发 select 且不可点击 */
  header?: boolean
}

const props = defineProps<{
  items: DropdownItem[]
  align?: 'left' | 'right'
}>()

const emit = defineEmits<{ select: [item: DropdownItem] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})

function onDocClick(e: MouseEvent) {
  const target = e.target as Node
  if (root.value?.contains(target) || menuRef.value?.contains(target)) return
  open.value = false
}

function onSelectItem(item: DropdownItem) {
  if (item.disabled || item.header || item.divider) return
  open.value = false
  emit('select', item)
}

function onWindowScroll() {
  open.value = false
}

/** 固定定位 + 碰撞翻转：避免被表格/滚动容器裁剪，靠近视口底部时向上弹出 */
function positionMenu() {
  const btn = root.value?.getBoundingClientRect()
  if (!btn) return
  const menuW = 172
  const estH = 48 + props.items.filter((i) => !i.divider).length * 34
  let top = btn.bottom + 6
  let left = props.align === 'left' ? btn.left : btn.right - menuW
  if (top + estH > window.innerHeight - 8) {
    top = Math.max(8, btn.top - estH - 6)
  }
  left = Math.max(8, Math.min(left, window.innerWidth - menuW - 8))
  menuStyle.value = {
    position: 'fixed',
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    zIndex: '1200',
    maxHeight: `${window.innerHeight - 16}px`,
    overflowY: 'auto',
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) nextTick(positionMenu)
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('scroll', onWindowScroll, { passive: true })
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('scroll', onWindowScroll)
})
</script>

<template>
  <div ref="root" class="ui-dropdown">
    <button class="btn-icon" aria-haspopup="menu" :aria-expanded="open" @click="toggle">
      <i class="bi bi-three-dots-vertical"></i>
    </button>
    <Teleport to="body">
      <Transition name="dropdown">
        <div
          v-if="open"
          ref="menuRef"
          class="dropdown-menu"
          :class="`dropdown-menu--${align ?? 'right'}`"
          role="menu"
          :style="menuStyle"
        >
          <div v-if="items.some((i) => i.header)" class="dropdown-head">
            <span v-for="i in items.filter((x) => x.header)" :key="i.id">{{ i.label }}</span>
          </div>
          <template v-for="item in items" :key="item.id">
            <div v-if="item.divider" class="dropdown-divider" role="separator"></div>
            <button
              v-else
              role="menuitem"
              class="dropdown-item"
              :class="{ danger: item.danger }"
              :disabled="item.disabled || item.header"
              @click="onSelectItem(item)"
            >
              <i v-if="item.icon" class="bi" :class="item.icon"></i>
              {{ item.label }}
            </button>
          </template>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.ui-dropdown {
  position: relative;
}
.dropdown-menu {
  min-width: 172px;
  padding: 5px;
  background: var(--bg-overlay);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-pop);
}
.dropdown-head {
  padding: 6px 10px 8px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.dropdown-divider {
  height: 1px;
  margin: 5px 4px;
  background: var(--border-subtle);
}
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
  opacity: 0.5;
  cursor: default;
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
