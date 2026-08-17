<script setup lang="ts">
import { computed } from 'vue'
import UiBadge from './UiBadge.vue'
import { statusActive, statusDisplay, statusTone } from '@/composables/taskMeta'
import type { TaskStatus } from '@/api/types'

const props = defineProps<{ status: TaskStatus }>()

const tone = computed(() => statusTone(props.status))
const active = computed(() => statusActive(props.status))
</script>

<template>
  <UiBadge :tone="tone" :pulse="active" :dot="active">
    {{ statusDisplay(status) }}
  </UiBadge>
</template>
