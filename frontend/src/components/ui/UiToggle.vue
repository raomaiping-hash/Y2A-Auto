<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: boolean
    disabled?: boolean
    label?: string
    hint?: string
  }>(),
  { disabled: false },
)

const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <label class="ui-toggle-row" :class="{ disabled }">
    <button
      type="button"
      role="switch"
      :aria-checked="modelValue"
      :disabled="disabled"
      class="toggle"
      :class="{ on: modelValue }"
      @click="toggle"
    ></button>
    <span v-if="label || hint" class="ui-toggle-text">
      <span v-if="label" class="ui-toggle-label">{{ label }}</span>
      <span v-if="hint" class="ui-toggle-hint">{{ hint }}</span>
    </span>
  </label>
</template>

<style scoped>
.ui-toggle-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.ui-toggle-row.disabled {
  cursor: not-allowed;
}
.ui-toggle-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.ui-toggle-label {
  font-size: var(--fs-md);
  color: var(--text-primary);
}
.ui-toggle-hint {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
</style>
