<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    size?: 'sm' | 'md' | 'lg' | 'xl'
    closeOnBackdrop?: boolean
    hideClose?: boolean
  }>(),
  { size: 'md', closeOnBackdrop: true, hideClose: false },
)

const emit = defineEmits<{ close: [] }>()

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
  },
)

const sizeClass = computed(() => `ui-modal--${props.size}`)
</script>

<template>
  <Teleport to="body">
    <Transition name="ui-modal">
      <div
        v-if="open"
        class="ui-modal-backdrop"
        @mousedown.self="closeOnBackdrop && emit('close')"
      >
        <div class="ui-modal" :class="sizeClass" role="dialog" aria-modal="true">
          <header v-if="title || !hideClose" class="ui-modal-head">
            <h3 class="ui-modal-title">{{ title }}</h3>
            <button v-if="!hideClose" class="btn-icon" aria-label="关闭" @click="emit('close')">
              <i class="bi bi-x-lg"></i>
            </button>
          </header>
          <div class="ui-modal-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="ui-modal-foot">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ui-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--scrim);
  backdrop-filter: blur(4px);
}
.ui-modal {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 64px);
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-pop);
}
.ui-modal--sm { max-width: 400px; }
.ui-modal--md { max-width: 560px; }
.ui-modal--lg { max-width: 780px; }
.ui-modal--xl { max-width: 1000px; }

.ui-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--border-subtle);
}
.ui-modal-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}
.ui-modal-body {
  padding: var(--sp-5);
  overflow-y: auto;
}
.ui-modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid var(--border-subtle);
}

.ui-modal-enter-active,
.ui-modal-leave-active {
  transition: opacity var(--dur) var(--ease);
}
.ui-modal-enter-active .ui-modal,
.ui-modal-leave-active .ui-modal {
  transition: transform var(--dur) var(--ease), opacity var(--dur) var(--ease);
}
.ui-modal-enter-from,
.ui-modal-leave-to {
  opacity: 0;
}
.ui-modal-enter-from .ui-modal,
.ui-modal-leave-to .ui-modal {
  transform: translateY(10px) scale(0.98);
  opacity: 0;
}
</style>
