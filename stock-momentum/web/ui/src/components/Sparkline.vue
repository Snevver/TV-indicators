<script setup>
import { computed } from "vue";
const props = defineProps({ values: { type: Array, default: () => [] }, dir: String });
const W = 1000, H = 74;

const path = computed(() => {
  const v = props.values || [];
  if (v.length < 2) return null;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const pts = v.map((y, i) => [
    (W * i) / (v.length - 1),
    6 + (H - 14) * (1 - (y - lo) / span),
  ]);
  return {
    line: pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "),
    area: `0,${H} ` + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ") + ` ${W},${H}`,
    end: pts[pts.length - 1],
  };
});
</script>

<template>
  <svg v-if="path" class="spark" :class="dir" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none"
       aria-hidden="true">
    <defs>
      <linearGradient :id="`sg-${dir}`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" class="g0" /><stop offset="100%" class="g1" />
      </linearGradient>
    </defs>
    <polygon :points="path.area" :fill="`url(#sg-${dir})`" />
    <polyline :points="path.line" class="ln" />
    <circle :cx="path.end[0]" :cy="path.end[1]" r="4" class="tipdot" />
  </svg>
  <div v-else class="spark-empty tag">awaiting first marks</div>
</template>

<style scoped>
.spark { display: block; width: 100%; height: 74px }
.ln { fill: none; stroke-width: 2.5; vector-effect: non-scaling-stroke }
.spark.up .ln { stroke: var(--up); filter: drop-shadow(0 0 6px rgba(110,255,123,.6)) }
.spark.down .ln { stroke: var(--down); filter: drop-shadow(0 0 6px rgba(255,77,109,.6)) }
.spark.up .tipdot { fill: var(--up); filter: drop-shadow(0 0 8px var(--up)) }
.spark.down .tipdot { fill: var(--down); filter: drop-shadow(0 0 8px var(--down)) }
.spark.up .g0 { stop-color: var(--up); stop-opacity: .22 }
.spark.down .g0 { stop-color: var(--down); stop-opacity: .22 }
.g1 { stop-color: currentColor; stop-opacity: 0 }
.spark-empty { padding: 20px 24px 22px; opacity: .5 }
</style>
