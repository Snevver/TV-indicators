<script setup>
import NumberFlow from "./NumberFlow.vue";
import { money, pct, signed } from "../format.js";
import { computed } from "vue";

// The command bar. Headline is TOTAL (holdings + cash) -- own money plus what
// the strategy earned -- the same field the chart and rebalance log use, so
// this figure never disagrees with the rest of the page. The two cells below
// are what was put in and what the same money would be worth in the S&P 500
// instead.
const props = defineProps({
  s: Object, sym: String, label: String, bench: Number,
});

const fmt = (v) => money(v, props.sym);
const dir = computed(() => (props.s?.pnl ?? 0) >= 0 ? "up" : "down");
const held = computed(() => props.s?.total ?? 0);
</script>

<template>
  <section class="hud bar" :class="dir">
    <div class="scan"></div>

    <div class="lead">
      <div class="tag">{{ label }} · Trading 212</div>
      <NumberFlow class="big" :value="held" :format="fmt" />
      <div class="row">
        <span class="delta" :class="dir">
          {{ signed(s?.pnl ?? 0, sym) }} <em>{{ pct(s?.pnl_pct ?? 0) }}</em>
        </span>
      </div>
      <p class="fine breakdown">{{ money(s?.invested ?? 0, sym) }} invested ·
        {{ money(s?.cash ?? 0, sym) }} free funds</p>
    </div>

    <dl class="cells">
      <div><dt class="tag">Paid in</dt><dd class="mono">{{ money(s?.deposited ?? 0, sym) }}</dd></div>
      <div><dt class="tag">vs S&amp;P 500</dt>
        <dd class="mono">{{ bench ? money(bench, sym) : "—" }}</dd></div>
    </dl>
  </section>
</template>

<style scoped>
.bar {
  display: grid; gap: 20px 30px; align-items: start; padding: 20px 24px;
  grid-template-columns: auto 1fr;
}
.lead { display: flex; flex-direction: column; gap: 5px; min-width: 0 }

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
.breakdown { margin-top: 2px }

.cells { display: grid; gap: 12px 22px; margin: 0; grid-template-columns: repeat(2, minmax(100px, auto)) }
.cells div { display: flex; flex-direction: column; gap: 1px }
dd { margin: 0; font-size: .95rem; color: var(--ink) }

.scan {
  position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background: linear-gradient(100deg, transparent 42%, rgba(0,240,255,.10) 50%, transparent 58%);
  background-size: 260% 100%; animation: sweep 9s ease-in-out infinite;
}
@keyframes sweep { 0%,72% { background-position: 130% 0 } 100% { background-position: -30% 0 } }

@media (max-width: 1100px) {
  .bar { grid-template-columns: 1fr }
}
@media (prefers-reduced-motion: reduce) { .scan { display: none } }
</style>
