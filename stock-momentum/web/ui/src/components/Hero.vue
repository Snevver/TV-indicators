<script setup>
import NumberFlow from "./NumberFlow.vue";
import Sparkline from "./Sparkline.vue";
import { money, pct, signed } from "../format.js";
import { computed } from "vue";

// The headline is the HOLDINGS value -- the eight positions, which is the number
// the Trading 212 Investments tab shows. Cash, total and the benchmark sit under
// it as plainly-labelled context, because conflating them is what made the page
// confusing: total includes uninvested cash the Investments tab never shows.
const props = defineProps({
  s: Object, sym: String, label: String, series: Array, bench: Number,
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
  <section class="hero hud" :class="dir">
    <div class="scan"></div>
    <div class="grid">
      <div class="lead">
        <div class="tag">{{ label }} account · Trading 212</div>
        <NumberFlow class="big" :value="held" :format="fmt" />
        <div class="row">
          <span class="delta" :class="dir">
            {{ signed(s?.unrealised ?? 0) }} <em>{{ pct(heldPct) }}</em>
          </span>
          <span class="fine">holdings · {{ s?.marked === "t212"
            ? "live from Trading 212" : "marked from Yahoo" }}</span>
        </div>
      </div>

      <dl class="breakdown">
        <div>
          <dt class="tag">Cash</dt>
          <dd class="mono">{{ money(s?.cash ?? 0, sym) }}</dd>
          <span class="note">in T212 free funds</span>
        </div>
        <div>
          <dt class="tag">Total</dt>
          <dd class="mono">{{ money(s?.total ?? 0, sym) }}</dd>
          <span class="note">holdings + cash</span>
        </div>
        <div>
          <dt class="tag">Paid in</dt>
          <dd class="mono">{{ money(s?.deposited ?? 0, sym) }}</dd>
          <span class="note">&nbsp;</span>
        </div>
        <div>
          <dt class="tag">vs S&amp;P 500</dt>
          <dd class="mono">{{ bench ? money(bench, sym) : "—" }}</dd>
          <span class="note" :class="gap == null ? '' : gap >= 0 ? 'up' : 'down'">
            {{ gap == null ? "no benchmark yet"
               : signed(gap) + (gap >= 0 ? " ahead" : " behind") }}
          </span>
        </div>
      </dl>
    </div>

    <p class="reconcile fine">
      Holdings ≈ T212 <em>Investments</em> tab ·
      Total ≈ account value minus funds the strategy never touched
    </p>

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

.breakdown { display: grid; grid-template-columns: repeat(2, auto); gap: 14px 26px; margin: 0 }
.breakdown div { display: flex; flex-direction: column; gap: 1px }
.breakdown dt { line-height: 1.4 }
.breakdown dd { margin: 0; font-size: .95rem; color: var(--ink) }
.breakdown .note { font-size: .68rem; color: var(--faint); letter-spacing: .02em }
.breakdown .note.up { color: var(--up) }
.breakdown .note.down { color: var(--down) }

.reconcile { padding: 0 24px 4px }
.reconcile em { font-style: normal; color: var(--ink); opacity: .85 }

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
  .breakdown { grid-template-columns: repeat(2, 1fr) }
  .reconcile { padding: 0 16px 4px }
}
@media (prefers-reduced-motion: reduce) { .scan { display: none } }
</style>
