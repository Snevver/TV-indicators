<script setup>
import { ref, computed, onMounted } from "vue";
import * as api from "../api.js";
import { store } from "../store.js";
import { money, pct } from "../format.js";
import SimChart from "../components/SimChart.vue";

const bounds = ref(null);
const result = ref(null);
const error = ref("");
const busy = ref(false);
const loadingData = ref(true);

const form = ref({ start: "2020-01-01", end: "", budget: 1000, monthly: 0 });

const sym = computed(() => store.state?.symbol || "$");

// Windows worth a click, rather than making someone type dates to explore.
const PRESETS = [
  { l: "Year to date", s: "2026-01-01" },
  { l: "Last 5 years", s: "2021-08-26" },
  { l: "Since Covid", s: "2020-01-01" },
  { l: "The 2022 bear", s: "2022-01-01", e: "2022-12-31" },
  { l: "Financial crisis", s: "2007-10-01", e: "2009-06-30" },
  { l: "Everything", s: null },
];

function preset(p) {
  form.value.start = p.s || bounds.value?.min || "2005-09-01";
  form.value.end = p.e || bounds.value?.max || "";
  go();
}

onMounted(async () => {
  try {
    bounds.value = await api.simBounds();
    form.value.end = bounds.value.max;
    loadingData.value = false;
    go();
  } catch (e) {
    error.value = String(e.message || e);
    loadingData.value = false;
  }
});

async function go() {
  busy.value = true; error.value = "";
  try {
    result.value = await api.simulate({
      start: form.value.start, end: form.value.end, budget: form.value.budget,
      monthly: form.value.monthly || 0,
    });
  } catch (e) {
    // The endpoint reports why in the body; surface that rather than a status.
    try {
      const r = await fetch("/api/simulate?" + new URLSearchParams({
        start: form.value.start, end: form.value.end, budget: form.value.budget,
        monthly: form.value.monthly || 0 }),
        { credentials: "same-origin" });
      error.value = (await r.json()).error || String(e.message || e);
    } catch (_) { error.value = String(e.message || e); }
    result.value = null;
  } finally { busy.value = false; }
}

const contrib = computed(() => (result.value?.monthly || 0) > 0);

const ROWS = computed(() => [
  { key: "strategy", label: "Momentum rotation", note: "top 8, rebalanced monthly", swatch: "cy" },
  { key: "spy", label: "S&P 500",
    note: contrib.value ? "the same payments, into the index" : "bought once and held",
    swatch: "am" },
]);

// Only the benchmarks the run actually produced — SPY is absent if the ETF
// export is missing.
const shownRows = computed(() =>
  ROWS.value.filter((r) => result.value?.stats?.[r.key]));

// With money arriving every month, final ÷ first − 1 counts your own deposits as
// profit, so the API sends a money-weighted return instead and leaves ret_pct
// null. Compare whichever one the run actually produced.
const beat = computed(() => {
  const st = result.value?.stats;
  if (!st?.strategy || !st?.spy) return null;
  const a = contrib.value ? st.strategy.irr_pct : st.strategy.ret_pct;
  const b = contrib.value ? st.spy.irr_pct : st.spy.ret_pct;
  if (a === null || b === null || a === undefined || b === undefined) return null;
  return a - b;
});
</script>

<template>
  <div class="page">
    <div class="head">
      <span class="tag">Backtest</span>
      <h1>Simulate a window</h1>
      <p class="lede">Run the same rules the bot follows over any past period and
        see it against simply buying the index and holding. Same ranking, same
        monthly trade, same 10 basis points on the money that moves — only the
        names that changed are traded, exactly as the bot does it.</p>
    </div>

    <div v-if="loadingData" class="hud pad">
      <span class="tag">Loading twenty-one years of daily prices…</span>
    </div>

    <template v-else>
      <form class="hud controls" @submit.prevent="go">
        <div class="f">
          <label class="tag" for="s">Start</label>
          <input id="s" type="date" v-model="form.start"
                 :min="bounds?.min" :max="bounds?.max">
        </div>
        <div class="f">
          <label class="tag" for="e">End</label>
          <input id="e" type="date" v-model="form.end"
                 :min="bounds?.min" :max="bounds?.max">
        </div>
        <div class="f">
          <label class="tag" for="b">Budget</label>
          <input id="b" type="number" v-model.number="form.budget" min="1" step="any">
        </div>
        <div class="f">
          <label class="tag" for="mo">Monthly</label>
          <input id="mo" type="number" v-model.number="form.monthly" min="0" step="any"
                 title="Paid in on every rebalance after the first. 0 for none.">
        </div>
        <button type="submit" :disabled="busy">{{ busy ? "Running…" : "Run" }}</button>
      </form>

      <div class="presets">
        <button v-for="p in PRESETS" :key="p.l" class="quiet" :disabled="busy"
                @click="preset(p)">{{ p.l }}</button>
      </div>

      <p v-if="error" class="err">{{ error }}</p>

      <template v-if="result && !error">
        <div class="verdict hud" v-if="beat !== null">
          <span class="tag">{{ result.start }} → {{ result.end }}</span>
          <p class="line" v-if="!contrib">
            <b class="mono" :class="beat >= 0 ? 'up' : 'down'">
              {{ money(result.stats.strategy.final, sym) }}</b>
            against <b class="mono">{{ money(result.stats.spy.final, sym) }}</b>
            from the index — the rotation was
            <b :class="beat >= 0 ? 'up' : 'down'">{{ Math.abs(beat).toFixed(1) }}
            points</b> {{ beat >= 0 ? "ahead" : "behind" }} over the window,
            through a worst fall of
            <b class="down mono">{{ result.stats.strategy.maxdd_pct.toFixed(1) }}%</b>.
          </p>
          <p class="line" v-else>
            You paid in <b class="mono">{{ money(result.stats.strategy.paid_in, sym) }}</b>
            and finished with
            <b class="mono" :class="beat >= 0 ? 'up' : 'down'">
              {{ money(result.stats.strategy.final, sym) }}</b> —
            a gain of
            <b class="mono" :class="result.stats.strategy.gain >= 0 ? 'up' : 'down'">
              {{ money(result.stats.strategy.gain, sym) }}</b>, worth
            <b :class="beat >= 0 ? 'up' : 'down'">{{ result.stats.strategy.irr_pct?.toFixed(1) }}%
            a year</b>. The same payments into the index made
            <b class="mono">{{ money(result.stats.spy.gain, sym) }}</b>
            at <b>{{ result.stats.spy.irr_pct?.toFixed(1) }}%</b>, through a worst
            fall of
            <b class="down mono">{{ result.stats.strategy.maxdd_pct.toFixed(1) }}%</b>.
          </p>
          <p class="line sub" v-if="contrib">
            Because money keeps arriving, a plain start-to-finish percentage would
            count your own deposits as profit. The yearly figure above is
            money-weighted, and the index receives the same amount on the same
            days so the comparison is like for like.
          </p>
        </div>

        <div class="hud">
          <div class="hud-head">
            <h2>Growth of {{ money(result.budget, sym) }}<template v-if="contrib">
              plus {{ money(result.monthly, sym) }} a month</template></h2>
            <span class="tag">{{ result.rebalances.length }} rebalances</span>
          </div>
          <div class="hud-body">
            <SimChart :result="result" :sym="sym" />
            <div class="key">
              <span v-for="r in shownRows" :key="r.key">
                <i class="sw" :class="r.swatch"></i>{{ r.label }}
              </span>
            </div>
          </div>
        </div>

        <div class="hud">
          <div class="hud-head"><h2>Side by side</h2></div>
          <div class="hud-body flush"><div class="scroll"><table>
            <thead><tr>
              <th>Strategy</th><th>Final</th><th>Return</th><th>A year</th>
              <th>Worst fall</th><th>Volatility</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in shownRows" :key="r.key"
                  :class="{ lead: r.key === 'strategy' }">
                <td>
                  <i class="sw" :class="r.swatch"></i>
                  <b>{{ r.label }}</b><span class="sub">{{ r.note }}</span>
                </td>
                <td class="mono">{{ money(result.stats[r.key].final, sym) }}</td>
                <td class="mono" v-if="result.stats[r.key].ret_pct == null">—</td>
                <td class="mono" v-else
                    :class="result.stats[r.key].ret_pct >= 0 ? 'up' : 'down'">
                  {{ pct(result.stats[r.key].ret_pct, 1) }}</td>
                <td class="mono">{{ (result.stats[r.key].irr_pct
                  ?? result.stats[r.key].cagr_pct) == null ? "—"
                  : pct(result.stats[r.key].irr_pct ?? result.stats[r.key].cagr_pct, 1) }}</td>
                <td class="mono down">−{{ result.stats[r.key].maxdd_pct.toFixed(1) }}%</td>
                <td class="mono dim">{{ result.stats[r.key].vol_pct.toFixed(0) }}%</td>
              </tr>
            </tbody>
          </table></div></div>
        </div>

        <div class="hud">
          <div class="hud-head"><h2>Every rebalance</h2>
            <span class="tag">what it held, and what the account was worth</span></div>
          <div class="hud-body flush tallwrap"><div class="scroll tall"><table>
            <thead><tr><th>Date</th><th>Account</th><th>Held</th></tr></thead>
            <tbody>
              <tr v-for="r in result.rebalances" :key="r.date">
                <td class="mono">{{ r.date }}</td>
                <td class="mono">{{ money(r.value, sym) }}</td>
                <td class="basket">
                  <span v-for="t in r.basket" :key="t" class="pill idle">{{ t }}</span>
                </td>
              </tr>
            </tbody>
          </table></div></div>
        </div>

        <p class="fine caveat">
          The rotation picks from forty names chosen in 2026, so it is flattered
          by knowing which companies survived — a list drawn in 2010 would have
          held some that later went nowhere. The index line has no such
          hindsight in it, which is exactly why it is the one worth comparing
          against. Dividends are excluded from the stocks and included in the
          index, which understates the rotation slightly.
        </p>
      </template>
    </template>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; width: 100% }
.head { display: flex; flex-direction: column; gap: 5px }
.pad { padding: 22px 24px }

.controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end;
  padding: 18px 20px }
.f { display: flex; flex-direction: column; gap: 5px }
.f input, .f select { max-width: 172px; min-width: 132px }
.controls button { margin-left: auto }
.presets { display: flex; flex-wrap: wrap; gap: 7px }
.presets button { font-size: .68rem; padding: 6px 12px }

.verdict { padding: 16px 20px; display: flex; flex-direction: column; gap: 6px;
  border-left: 2px solid var(--cyan) }
.verdict .line { font-size: 1.02rem; color: var(--body); max-width: 78ch;
  line-height: 1.6 }
.verdict b { color: var(--ink) }
/* The caveat under the verdict: present, but not competing with it. */
.verdict .line.sub { font-size: .84rem; color: var(--faint); max-width: 72ch }

.key { display: flex; gap: 20px; flex-wrap: wrap; padding: 10px 4px 2px;
  font-size: .76rem; color: var(--faint) }
.sw { display: inline-block; width: 14px; height: 2.5px; margin-right: 8px;
  vertical-align: middle }
.sw.cy { background: var(--cyan); box-shadow: 0 0 8px var(--cyan) }
.sw.am { background: var(--amber) }
.sw.gy { background: var(--muted) }

td b { color: var(--ink); font-weight: 600 }
td .sub { display: block; font-size: .72rem; color: var(--faint); margin-left: 22px }
tr.lead { background: rgba(0,240,255,.05) }
.basket { text-align: left; white-space: normal; max-width: 460px }
.tallwrap { position: relative }
.tallwrap::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0;
  height: 40px; pointer-events: none;
  background: linear-gradient(transparent, var(--panel-solid)) }
.scroll.tall { max-height: 420px; overflow-y: auto }
.caveat { max-width: 76ch; padding-top: 6px }

@media (max-width: 720px) {
  .controls button { margin-left: 0; width: 100% }
  .f input, .f select { max-width: none }
}
</style>
