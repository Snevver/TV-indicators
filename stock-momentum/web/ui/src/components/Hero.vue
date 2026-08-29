<script setup>
import NumberFlow from "./NumberFlow.vue";
import { money, pct, signed } from "../format.js";
import { computed } from "vue";

// The command bar. Headline is the HOLDINGS value -- the figure the Trading 212
// Investments tab shows. Cash, total, paid-in and the benchmark sit beside it as
// plainly-labelled cells; positions and the next rebalance close the row.
const props = defineProps({
  s: Object, sym: String, label: String, bench: Number,
  positions: Number, target: Number, nextRebalance: String,
});

const fmt = (v) => money(v, props.sym);
const dir = computed(() => (props.s?.unrealised ?? 0) >= 0 ? "up" : "down");
const held = computed(() => props.s?.invested ?? 0);
const cost = computed(() => held.value - (props.s?.unrealised ?? 0));
const heldPct = computed(() =>
  cost.value > 0 ? (props.s.unrealised / cost.value) * 100 : 0);
const gap = computed(() =>
  props.bench ? (props.s?.total ?? 0) - props.bench : null);
</script>

<template>
  <section class="hud bar" :class="dir">
    <div class="scan"></div>

    <div class="lead">
      <div class="tag">{{ label }} · Trading 212</div>
      <NumberFlow class="big" :value="held" :format="fmt" />
      <div class="row">
        <span class="delta" :class="dir">
          {{ signed(s?.unrealised ?? 0) }} <em>{{ pct(heldPct) }}</em>
        </span>
        <span class="fine">holdings · {{ s?.marked === "t212"
          ? "live from Trading 212" : "marked from Yahoo" }}</span>
      </div>
    </div>

    <dl class="cells">
      <div><dt class="tag">Cash</dt><dd class="mono">{{ money(s?.cash ?? 0, sym) }}</dd>
        <span class="sub">T212 free funds</span></div>
      <div><dt class="tag">Total</dt><dd class="mono">{{ money(s?.total ?? 0, sym) }}</dd>
        <span class="sub">holdings + cash</span></div>
      <div><dt class="tag">Paid in</dt><dd class="mono">{{ money(s?.deposited ?? 0, sym) }}</dd></div>
      <div><dt class="tag">vs S&amp;P 500</dt>
        <dd class="mono">{{ bench ? money(bench, sym) : "—" }}</dd>
        <span class="sub" :class="gap == null ? '' : gap >= 0 ? 'up' : 'down'">
          {{ gap == null ? "no benchmark yet"
             : signed(gap) + (gap >= 0 ? " ahead" : " behind") }}</span></div>
    </dl>

    <div class="meta">
      <div><dt class="tag">Positions</dt>
        <dd class="mono">{{ positions ?? 0 }}<span class="of">/ {{ target ?? 8 }}</span></dd></div>
      <div><dt class="tag">Next rebalance</dt>
        <dd class="mono">{{ (nextRebalance || "—").split(" ")[0] }}</dd>
        <span class="sub">{{ (nextRebalance || "").split(" ")[1] || "" }}</span></div>
    </div>

    <p class="reconcile fine">
      Holdings ≈ T212 <em>Investments</em> tab ·
      Total ≈ account value minus funds the strategy never touched
    </p>
  </section>
</template>

<style scoped>
.bar {
  display: grid; gap: 20px 30px; align-items: start; padding: 20px 24px 8px;
  grid-template-columns: auto 1fr auto;
  grid-template-areas: "lead cells meta" "recon recon recon";
}
.lead { grid-area: lead; display: flex; flex-direction: column; gap: 5px; min-width: 0 }
.cells { grid-area: cells }
.meta { grid-area: meta }
.reconcile { grid-area: recon; padding-top: 6px; border-top: 1px solid var(--hair); margin-top: 4px }
.reconcile em { font-style: normal; color: var(--ink); opacity: .85 }

.big {
  font-size: clamp(2.1rem, 5vw, 3.2rem); line-height: 1; font-weight: 700;
  color: var(--ink); letter-spacing: -.02em; text-shadow: 0 0 32px rgba(0,240,255,.30);
}
.bar.down .big { text-shadow: 0 0 32px rgba(255,77,109,.26) }
.row { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-top: 3px }
.delta {
  font-family: var(--f-mono); font-size: .88rem; font-weight: 700;
  padding: 3px 10px; border: 1px solid transparent;
}
.delta em { font-style: normal; opacity: .8; margin-left: 4px }
.delta.up { color: var(--up); background: var(--up-soft); border-color: rgba(110,255,123,.3) }
.delta.down { color: var(--down); background: var(--down-soft); border-color: rgba(255,77,109,.3) }

.cells, .meta { display: grid; gap: 12px 22px; margin: 0 }
.cells { grid-template-columns: repeat(4, minmax(84px, auto)) }
.meta { grid-template-columns: repeat(2, auto); align-content: start }
.cells div, .meta div { display: flex; flex-direction: column; gap: 1px }
dd { margin: 0; font-size: .95rem; color: var(--ink) }
.meta dd { font-size: 1.1rem }
.of { color: var(--faint); font-size: .8rem; margin-left: 3px }
.sub { font-size: .64rem; color: var(--faint); letter-spacing: .02em }
.sub.up { color: var(--up) } .sub.down { color: var(--down) }

.scan {
  position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background: linear-gradient(100deg, transparent 42%, rgba(0,240,255,.10) 50%, transparent 58%);
  background-size: 260% 100%; animation: sweep 9s ease-in-out infinite;
}
@keyframes sweep { 0%,72% { background-position: 130% 0 } 100% { background-position: -30% 0 } }

@media (max-width: 1100px) {
  .bar { grid-template-columns: 1fr; grid-template-areas: "lead" "cells" "meta" "recon" }
  .cells { grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)) }
}
@media (prefers-reduced-motion: reduce) { .scan { display: none } }
</style>
