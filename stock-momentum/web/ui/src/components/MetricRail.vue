<script setup>
defineProps({ items: Array });
</script>

<template>
  <div class="rail">
    <div v-for="(m, i) in items" :key="m.k" class="cell hud" :style="{ '--d': i * 60 + 'ms' }">
      <span class="tag">{{ m.k }}</span>
      <span class="v mono" :class="m.tone">{{ m.v }}</span>
      <span class="s">{{ m.s }}</span>
    </div>
  </div>
</template>

<style scoped>
.rail { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)) }
.cell { padding: 13px 15px; display: flex; flex-direction: column; gap: 3px;
  animation: rise .5s ease-out both; animation-delay: var(--d) }
.v { font-size: 1.2rem; font-weight: 600; color: var(--ink); letter-spacing: -.01em }
.s { font-size: .72rem; color: var(--faint) }
@keyframes rise { from { opacity: 0; transform: translateY(8px) } }
@media (prefers-reduced-motion: reduce) { .cell { animation: none } }
</style>
