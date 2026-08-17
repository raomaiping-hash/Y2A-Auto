<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="nf-wrap">
    <div class="nf-code">404</div>
    <p class="nf-text">页面不存在或已被移动</p>
    <RouterLink to="/" class="btn btn-primary">
      <i class="bi bi-house-door"></i> 返回仪表盘
    </RouterLink>
  </div>
</template>

<style scoped>
.nf-wrap {
  min-height: 60vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-4);
}
.nf-code {
  font-size: 84px;
  font-weight: 800;
  letter-spacing: 0.02em;
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  line-height: 1;
}
.nf-text {
  color: var(--text-muted);
}
</style>
