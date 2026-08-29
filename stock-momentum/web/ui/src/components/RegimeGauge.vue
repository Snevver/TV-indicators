<script setup>
import { computed } from "vue";

// Universe momentum dispersion: mean 6-month return of the top 8 minus the
// bottom 8. Wide = the strategy has something to sort on. Data is
// store.state.health.regime, written by the bot's --json run.
const props = defineProps({ regime: { type: Object, default: () => ({}) } });
const r = computed(() => props.regime || {});
const has = computed(() => r.value.spread_pct != null);
const filled = computed(() =>
  Math.max(0, Math.min(5, Math.round((r.value.spread_pct || 0) / 8))));
const tone = computed(
  () => ({ wide: "hi", compressed: "lo", neutral: "mid" }[r.value.label] || "mid"));
const sign = (v) => (v > 0 ? "+" : "") + v;
</script>

<template>
  <div class="hud">
    <div class="hud-head">
      <h2>Momentum regime</h2>
      <span class="tag">top 8 vs bottom 8 · 6-month</span>
    </div>
    <div class="hud-body">
      <template v-if="has">
        <div class="meter" :class="tone">
          <i v-for="n in 5" :key="n" :class="{ on: n <= filled }"></i>
        </div>
        <div class="read">
          <span class="big mono">{{ sign(r.spread_pct) }}%</span>
          <span class="lab" :class="tone">{{ r.label }}</span>
        </div>
        <p class="fine">
          Winners {{ sign(r.top_pct) }}% · losers {{ sign(r.bottom_pct) }}%.
          {{ tone === "hi" ? "Wide spread — the strategy has a tailwind."
             : tone === "lo" ? "Compressed — expect it to track the index."
             : "Middling dispersion." }}
        </p>
      </template>
      <p v-else class="fine">No ranking yet — appears after the first bot run.</p>
    </div>
  </div>
</template>

<style scoped>
.meter { display: flex; gap: 6px; margin-bottom: 12px }
.meter i {
  flex: 1; height: 18px; background: rgba(140,175,215,.10);
  border: 1px solid var(--hair);
  clip-path: polygon(5px 0, 100% 0, 100% calc(100% - 5px), calc(100% - 5px) 100%, 0 100%, 0 5px);
  transition: background .2s, box-shadow .2s;
}
.meter.hi i.on { background: var(--lime); box-shadow: var(--glow-lime) }
.meter.mid i.on { background: var(--cyan); box-shadow: var(--glow-cyan) }
.meter.lo i.on { background: var(--amber); box-shadow: 0 0 14px rgba(255,180,67,.5) }
.read { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px }
.read .big { font-size: 1.7rem; font-weight: 700; color: var(--ink); line-height: 1 }
.lab {
  font-family: var(--f-mono); font-size: .64rem; letter-spacing: .18em;
  text-transform: uppercase; padding: 2px 9px; border: 1px solid transparent;
}
.lab.hi { color: var(--lime); border-color: rgba(110,255,123,.3); background: var(--up-soft) }
.lab.mid { color: var(--cyan); border-color: var(--edge-hot); background: rgba(0,240,255,.07) }
.lab.lo { color: var(--amber); border-color: rgba(255,180,67,.3); background: rgba(255,180,67,.06) }
</style>
