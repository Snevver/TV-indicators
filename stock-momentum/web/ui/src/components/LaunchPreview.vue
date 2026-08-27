<script setup>
import { computed } from "vue";
import { money } from "../format.js";

// Shown while the book is empty. Before trading starts this is the only screen
// worth having: what the strategy would buy on the first trading day, and the
// exact orders at this account's size.
const props = defineProps({ s: Object, h: Object, sym: String });

// The first rebalance pays in the monthly contribution before it sizes
// anything, so the slice is (what you hold now + this month's payment) / 8.
// Leaving it out promised a smaller slice than the bot would actually buy.
const monthly = computed(() => Number(props.h?.monthly) || 0);
const pot = computed(() => (props.s?.total || 0) + monthly.value);
const slice = computed(() => pot.value / (props.h?.hold || 8));
const picks = computed(() => (props.h?.ranking || []).filter((r) => r.held));
</script>

<template>
  <section class="hud launch">
    <div class="hud-head">
      <div class="ttl">
        <span class="tag">Standing by</span>
        <h2>What happens on the first trading day</h2>
      </div>
      <span class="when tag">{{ h?.next_rebalance || "next month" }}</span>
    </div>

    <div class="hud-body">
      <p class="lede">
        Nothing is held yet. On the first trading day of the month the bot ranks
        the forty names, takes the top {{ h?.hold || 8 }}, and posts these orders
        to Discord. This is that list as it stands right now; it will move
        before then.
      </p>

      <div v-if="picks.length" class="picks">
        <div v-for="(p, i) in picks" :key="p.ticker" class="pick"
             :style="{ '--d': i * 70 + 'ms' }">
          <span class="rank mono">{{ String(i + 1).padStart(2, '0') }}</span>
          <span class="sym mono">{{ p.ticker }}</span>
          <span class="mom mono">{{ p.momentum_pct >= 0 ? '+' : '' }}{{ p.momentum_pct.toFixed(1) }}%</span>
          <span class="amt mono">{{ money(slice, sym) }}</span>
        </div>
      </div>
      <p v-else class="fine">
        No ranking cached yet. It fills in on the bot's next run.
      </p>

      <div v-if="picks.length" class="foot">
        <span class="tag">
          <template v-if="monthly">{{ money(s?.total || 0, sym) }} +
            {{ money(monthly, sym) }} paid in</template>
          <template v-else>{{ money(s?.total || 0, sym) }}</template>
          ÷ {{ h?.hold || 8 }} = {{ money(slice, sym) }} per name</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.launch { position: relative; overflow: hidden }
.ttl { display: flex; flex-direction: column; gap: 3px }
.when { color: var(--cyan) }
.picks { display: flex; flex-direction: column; gap: 6px; margin-top: 14px }
.pick {
  display: grid; grid-template-columns: 34px 78px 1fr auto auto; gap: 12px;
  align-items: center; padding: 9px 12px;
  border: 1px solid var(--hair); background: rgba(0,240,255,.035);
  animation: in .45s ease-out both; animation-delay: var(--d);
}
.rank { color: var(--faint); font-size: .72rem }
.sym { font-weight: 700; color: var(--ink); letter-spacing: .06em }
.mom { color: var(--up); font-size: .8rem }
.amt { color: var(--cyan); font-size: .85rem; font-weight: 500 }
.foot { margin-top: 13px; padding-top: 11px; border-top: 1px solid var(--hair) }
@keyframes in { from { opacity: 0; transform: translateY(6px) } }
@media (max-width: 640px) {
  .pick { grid-template-columns: 30px 1fr auto; row-gap: 4px }
  .mom { grid-column: 2 }
}
@media (prefers-reduced-motion: reduce) { .pick { animation: none } }
</style>
