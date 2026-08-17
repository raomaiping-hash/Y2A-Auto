<script setup lang="ts">
import UiModal from './UiModal.vue'

withDefaults(
  defineProps<{
    open: boolean
    title?: string
    message?: string
    confirmText?: string
    cancelText?: string
    danger?: boolean
    loading?: boolean
  }>(),
  {
    title: '确认操作',
    confirmText: '确认',
    cancelText: '取消',
    danger: false,
    loading: false,
  },
)

const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <UiModal :open="open" :title="title" size="sm" @close="emit('close')">
    <p class="confirm-message">{{ message }}</p>
    <slot />
    <template #footer>
      <button class="btn btn-secondary" :disabled="loading" @click="emit('close')">
        {{ cancelText }}
      </button>
      <button
        class="btn"
        :class="danger ? 'btn-danger-solid' : 'btn-primary'"
        :disabled="loading"
        @click="emit('confirm')"
      >
        <span v-if="loading" class="spinner spinner-sm" aria-hidden="true"></span>
        {{ confirmText }}
      </button>
    </template>
  </UiModal>
</template>

<style scoped>
.confirm-message {
  color: var(--text-secondary);
  font-size: var(--fs-md);
  line-height: 1.6;
}
</style>
