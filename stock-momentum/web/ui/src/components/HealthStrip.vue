<script setup>
defineProps({ items: Array });
</script>

<template>
  <div class="strip">
    <span v-for="it in items" :key="it.label" class="cell">
      <i class="led" :class="it.state"></i>
      <span class="tag">{{ it.label }}</span>
      <b class="mono">{{ it.value }}</b>
    </span>
  </div>
</template>

<style scoped>
.strip { display: flex; flex-wrap: wrap; gap: 9px }
.cell { display: inline-flex; align-items: center; gap: 9px; padding: 7px 13px;
  border: 1px solid var(--hair); background: rgba(8,14,24,.6) }
.cell b { color: var(--ink); font-size: .78rem; font-weight: 500 }
</style>
