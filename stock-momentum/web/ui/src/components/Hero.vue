<script setup>
import NumberFlow from "./NumberFlow.vue";
import Sparkline from "./Sparkline.vue";
import { money, pct, signed } from "../format.js";
import { computed } from "vue";

const props = defineProps({ s: Object, sym: String, label: String, series: Array });
const dir = computed(() => (props.s?.pnl ?? 0) >= 0 ? "up" : "down");
const fmt = (v) => money(v, props.sym);
</script>

<template>
  <section class="hero hud" :class="dir">
    <div class="scan"></div>
    <div class="grid">
      <div class="lead">
        <div class="tag">{{ label }} · live account</div>
        <NumberFlow class="big" :value="s?.total ?? 0" :format="fmt" />
        <div class="row">
          <span class="delta" :class="dir">
            {{ signed(s?.pnl ?? 0) }} <em>{{ pct(s?.pnl_pct ?? 0) }}</em>
          </span>
          <span class="fine">against {{ money(s?.deposited ?? 0, sym) }} paid in</span>
        </div>
      </div>
      <dl class="side">
        <div><dt class="tag">Invested</dt><dd class="mono">{{ money(s?.invested ?? 0, sym) }}</dd></div>
        <div><dt class="tag">Cash</dt><dd class="mono">{{ money(s?.cash ?? 0, sym) }}</dd></div>
        <div><dt class="tag">Open</dt><dd class="mono" :class="(s?.unrealised ?? 0) >= 0 ? 'up' : 'down'">{{ signed(s?.unrealised ?? 0) }}</dd></div>
        <div><dt class="tag">Banked</dt><dd class="mono" :class="(s?.realised ?? 0) >= 0 ? 'up' : 'down'">{{ signed(s?.realised ?? 0) }}</dd></div>
      </dl>
    </div>
    <Sparkline :values="series" :dir="dir" />
  </section>
</template>

<style scoped>
.hero { overflow: hidden; padding: 0 }
.grid {
  display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 26px;
  align-items: start; padding: 22px 24px 10px;
}
.lead { display: flex; flex-direction: column; gap: 6px; min-width: 0 }
.big {
  font-size: clamp(2.4rem, 6.5vw, 3.9rem); line-height: 1; font-weight: 700;
  color: var(--ink); letter-spacing: -.02em;
  text-shadow: 0 0 32px rgba(0,240,255,.30);
}
.hero.down .big { text-shadow: 0 0 32px rgba(255,77,109,.26) }
.row { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-top: 4px }
.delta {
  font-family: var(--f-mono); font-size: .92rem; font-weight: 700;
  padding: 3px 11px; border: 1px solid transparent;
}
.delta em { font-style: normal; opacity: .8; margin-left: 4px }
.delta.up { color: var(--up); background: var(--up-soft); border-color: rgba(110,255,123,.3) }
.delta.down { color: var(--down); background: var(--down-soft); border-color: rgba(255,77,109,.3) }

.side { display: grid; grid-template-columns: repeat(2, auto); gap: 12px 26px; margin: 0 }
.side div { display: flex; flex-direction: column; gap: 1px }
.side dt { line-height: 1.4 }
.side dd { margin: 0; font-size: .95rem; color: var(--ink) }

/* a single slow sweep across the panel — the one piece of ambient motion */
.scan {
  position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background: linear-gradient(100deg, transparent 42%, rgba(0,240,255,.10) 50%, transparent 58%);
  background-size: 260% 100%;
  animation: sweep 9s ease-in-out infinite;
}
@keyframes sweep { 0%,72% { background-position: 130% 0 } 100% { background-position: -30% 0 } }

@media (max-width: 720px) {
  .grid { grid-template-columns: minmax(0,1fr); gap: 16px; padding: 18px 16px 8px }
  .side { grid-template-columns: repeat(2, 1fr) }
}
@media (prefers-reduced-motion: reduce) { .scan { display: none } }
</style>
