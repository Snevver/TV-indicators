<script setup>
import { computed } from "vue";
import { money, pct, shares } from "../format.js";
const props = defineProps({ positions: Object, sym: String, total: Number });

const rows = computed(() => {
  const e = Object.entries(props.positions || {});
  const top = Math.max(...e.map(([, p]) => p.weight_pct || 0), 1);
  return e.sort((a, b) => b[1].value - a[1].value)
          .map(([tk, p]) => ({ tk, ...p, bar: ((p.weight_pct || 0) / top) * 100 }));
});
</script>

<template>
  <div class="scroll">
    <table>
      <thead><tr>
        <th>Name</th><th>Weight</th><th>Shares</th><th>Price</th><th>Value</th><th>P&amp;L</th>
      </tr></thead>
      <tbody>
        <tr v-for="(r, i) in rows" :key="r.tk" :style="{ '--d': i * 45 + 'ms' }" class="in">
          <td class="tk mono">{{ r.tk }}</td>
          <td class="wt">
            <span class="track"><i :style="{ width: r.bar + '%' }"></i></span>
            <span class="mono pcs">{{ (r.weight_pct || 0).toFixed(1) }}%</span>
          </td>
          <td class="mono">{{ shares(r.shares) }}</td>
          <td class="mono">{{ money(r.price, sym) }}</td>
          <td class="mono">{{ money(r.value, sym) }}</td>
          <td class="mono" :class="r.pnl >= 0 ? 'up' : 'down'">{{ pct(r.pnl_pct, 1) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.tk { font-weight: 700; color: var(--ink); letter-spacing: .04em }
.wt { text-align: left; min-width: 128px }
.track { display: inline-block; vertical-align: middle; width: 74px; height: 5px;
  background: rgba(140,175,215,.12); margin-right: 10px; position: relative; overflow: hidden }
.track i { position: absolute; inset: 0 auto 0 0; background: var(--cyan);
  box-shadow: 0 0 10px rgba(0,240,255,.8); animation: grow .7s cubic-bezier(.2,.8,.2,1) both;
  animation-delay: var(--d) }
.pcs { font-size: .78rem; color: var(--body) }
@keyframes grow { from { transform: scaleX(0); transform-origin: left } }
.in { animation: slide .45s ease-out both; animation-delay: var(--d) }
@keyframes slide { from { opacity: 0; transform: translateX(-6px) } }
@media (prefers-reduced-motion: reduce) { .in, .track i { animation: none } }
</style>
