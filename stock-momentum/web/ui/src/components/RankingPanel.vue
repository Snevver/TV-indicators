<script setup>
defineProps({ ranking: Array, hold: { type: Number, default: 8 } });
</script>

<template>
  <div class="scroll">
    <table>
      <thead><tr><th>#</th><th>Name</th><th>6-month momentum</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(r, i) in ranking" :key="r.ticker" :class="{ held: r.held }">
          <td class="mono dim">{{ String(i + 1).padStart(2, '0') }}</td>
          <td class="mono sym">{{ r.ticker }}</td>
          <td class="bar">
            <span class="fill" :style="{
              width: Math.min(100, Math.abs(r.momentum_pct) / Math.max(...ranking.map(x => Math.abs(x.momentum_pct)), 1) * 100) + '%' }"
              :class="r.held ? 'hot' : ''"></span>
            <span class="mono val">{{ r.momentum_pct >= 0 ? '+' : '' }}{{ r.momentum_pct.toFixed(1) }}%</span>
          </td>
          <td><span class="pill" :class="r.held ? 'up' : 'idle'">{{ r.held ? 'held' : 'next' }}</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.sym { font-weight: 700; color: var(--ink); letter-spacing: .05em }
tr.held { background: rgba(0,240,255,.06) }
tr.held:hover { background: rgba(0,240,255,.10) }
.bar { position: relative; text-align: left; min-width: 190px }
.fill { display: inline-block; vertical-align: middle; height: 5px;
  background: rgba(140,175,215,.25); margin-right: 11px; max-width: 120px }
.fill.hot { background: var(--cyan); box-shadow: 0 0 10px rgba(0,240,255,.7) }
.val { font-size: .79rem; color: var(--body) }
</style>
