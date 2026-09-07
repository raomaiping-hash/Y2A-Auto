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

@media (max-width: 767px) {
  .nf-wrap {
    min-height: 100dvh;
    padding: var(--sp-6) var(--sp-4);
    text-align: center;
    gap: var(--sp-5);
  }
  .nf-code {
    font-size: 64px;
  }
  .nf-wrap .btn {
    min-height: 48px;
    height: 48px;
    padding: 0 var(--sp-6);
  }
}
</style>
