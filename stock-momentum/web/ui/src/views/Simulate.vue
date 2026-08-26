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

const form = ref({
  start: "2020-01-01", end: "", budget: 1000,
  mode: "rebalance", fractional: "1",
});

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
      start: form.value.start, end: form.value.end,
      budget: form.value.budget, mode: form.value.mode,
      fractional: form.value.fractional,
    });
  } catch (e) {
    // The endpoint reports why in the body; surface that rather than a status.
    try {
      const r = await fetch("/api/simulate?" + new URLSearchParams({
        start: form.value.start, end: form.value.end, budget: form.value.budget,
        mode: form.value.mode, fractional: form.value.fractional }),
        { credentials: "same-origin" });
      error.value = (await r.json()).error || String(e.message || e);
    } catch (_) { error.value = String(e.message || e); }
    result.value = null;
  } finally { busy.value = false; }
}

const ROWS = [
  { key: "strategy", label: "Momentum rotation", note: "top 8, rebalanced monthly", swatch: "cy" },
  { key: "hold40", label: "All forty, held", note: "bought once, never touched", swatch: "am" },
  { key: "spy", label: "S&P 500", note: "the index", swatch: "gy" },
];

// Only the benchmarks the run actually produced — SPY is absent if the ETF
// export is missing.
const shownRows = computed(() =>
  ROWS.filter((r) => result.value?.stats?.[r.key]));

const beat = computed(() => {
  const st = result.value?.stats;
  if (!st?.strategy || !st?.spy) return null;
  return st.strategy.ret_pct - st.spy.ret_pct;
});
</script>

<template>
  <div class="page">
    <div class="head">
      <span class="tag">Backtest</span>
      <h1>Simulate a window</h1>
      <p class="lede">Run the same rules the bot follows over any past period and
        see it against simply holding. Same ranking, same monthly rebalance, same
        10 basis points on the money that moves.</p>
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
          <input id="b" type="number" v-model.number="form.budget" min="1" step="100">
        </div>
        <div class="f">
          <label class="tag" for="m">Style</label>
          <select id="m" v-model="form.mode">
            <option value="rebalance">rebalance</option>
            <option value="drift">drift</option>
          </select>
        </div>
        <div class="f">
          <label class="tag" for="fr">Shares</label>
          <select id="fr" v-model="form.fractional">
            <option value="1">fractional</option>
            <option value="0">whole only</option>
          </select>
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
          <p class="line">
            <b class="mono" :class="beat >= 0 ? 'up' : 'down'">
              {{ money(result.stats.strategy.final, sym) }}</b>
            against <b class="mono">{{ money(result.stats.spy.final, sym) }}</b>
            from the index — the rotation was
            <b :class="beat >= 0 ? 'up' : 'down'">{{ Math.abs(beat).toFixed(1) }}
            points</b> {{ beat >= 0 ? "ahead" : "behind" }} over the window,
            through a worst fall of
            <b class="down mono">{{ result.stats.strategy.maxdd_pct.toFixed(1) }}%</b>.
          </p>
        </div>

        <div class="hud">
          <div class="hud-head">
            <h2>Growth of {{ money(result.budget, sym) }}</h2>
            <span class="tag">{{ result.rebalances.length }} rebalances ·
              {{ result.mode }}{{ result.fractional ? "" : " · whole shares" }}</span>
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
                <td class="mono" :class="result.stats[r.key].ret_pct >= 0 ? 'up' : 'down'">
                  {{ pct(result.stats[r.key].ret_pct, 1) }}</td>
                <td class="mono">{{ result.stats[r.key].cagr_pct == null
                  ? "—" : pct(result.stats[r.key].cagr_pct, 1) }}</td>
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
          The forty names were picked in 2026, so every line here — the rotation
          and the buy-and-hold both — is flattered by knowing which companies
          survived. The index is the only benchmark on this page with no
          hindsight in it. Dividends are excluded from the stocks and included in
          the index, which understates the strategy slightly.
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
