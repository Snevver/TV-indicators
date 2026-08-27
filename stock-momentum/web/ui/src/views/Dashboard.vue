<script setup>
import { computed, ref } from "vue";
import { store } from "../store.js";
import { money, pct, hoursAgo, ago } from "../format.js";
import Hero from "../components/Hero.vue";
import MetricRail from "../components/MetricRail.vue";
import Holdings from "../components/Holdings.vue";
import TimeChart from "../components/TimeChart.vue";
import RankingPanel from "../components/RankingPanel.vue";
import HealthStrip from "../components/HealthStrip.vue";
import LaunchPreview from "../components/LaunchPreview.vue";

const s = computed(() => store.state?.summary || {});
const h = computed(() => store.state?.health || {});
const sym = computed(() => store.state?.symbol || "$");
const hist = computed(() => store.history || {});
const empty = computed(() => !Object.keys(s.value.positions || {}).length);
// Three blank charts are ~650px of dead space before the bot has ever marked
// the book. Show one honest line instead until there is something to plot.
const hasCurve = computed(() => (hist.value.dates || []).length > 1);
const t212off = computed(() => !h.value?.t212?.configured);
// "Demo" / "Live", from whichever Trading 212 environment the bot is on.
const acct = computed(() => {
  const e = h.value?.t212?.env || "";
  return e ? e[0].toUpperCase() + e.slice(1) : "Trading 212";
});

const equity = ref(null);
const RANGES = [{ l: "1M", m: 1 }, { l: "3M", m: 3 }, { l: "ALL", m: 0 }];
const active = ref("ALL");
const setRange = (r) => { active.value = r.l; equity.value?.range(r.m); };

const metrics = computed(() => [
  { k: "Positions", v: String(Object.keys(s.value.positions || {}).length),
    s: `of ${h.value.hold || 8} target` },
  { k: "Next rebalance", v: (h.value.next_rebalance || "-").split(" ")[0],
    s: (h.value.next_rebalance || "").split(" ")[1] || "unknown" },
  { k: "Last traded", v: s.value.last_rebalance || "never",
    s: "monthly" },
  { k: "Worst drop", v: (hist.value.maxdd ?? 0).toFixed(1) + "%",
    s: "from the high", tone: (hist.value.maxdd ?? 0) < -0.05 ? "down" : "" },
  { k: "Price feed", v: h.value.bar || "-", s: hoursAgo(h.value.latest_hours) },
]);

const health = computed(() => [
  { label: "Bot", value: hoursAgo(h.value.latest_hours),
    state: h.value.latest_hours != null && h.value.latest_hours < 36 ? "on" : "warn" },
  { label: "Trading 212", value: h.value.t212?.configured ? (h.value.t212.env || "on").toUpperCase() : "off",
    state: h.value.t212?.configured ? "on" : "off" },
  { label: "Automatic", value: h.value.autotrade ? "on" : "off",
    state: h.value.autotrade ? "on" : "" },
  { label: "Feed", value: store.error ? "error" : "nominal", state: store.error ? "warn" : "on" },
]);
</script>

<template>
  <div class="page">
    <div class="topbar">
      <span class="tag acct">{{ acct }} account</span>
      <span class="tick tag">
        <i class="led on"></i>updated {{ ago(store.fetchedAt) }}
      </span>
    </div>

    <p v-if="store.error" class="err">Feed error: {{ store.error }}</p>

    <section v-if="t212off" class="note">
      <h2>Trading 212 is not connected</h2>
      <p class="lede">{{ h.t212?.reason || "No API key is set." }} Set one on the
        Settings page. Until then the bot works out the orders and you place them
        by hand.</p>
      <p class="fine"><a href="/settings">Open Settings</a> to add the key.</p>
    </section>

    <template v-else>
      <Hero :s="s" :sym="sym" :series="hist.total" :label="acct" />
      <MetricRail :items="metrics" />

      <LaunchPreview v-if="empty" :s="s" :h="h" :sym="sym" />

      <div v-if="!empty" class="hud">
        <div class="hud-head"><h2>Holdings</h2>
          <span class="tag">{{ money(s.invested, sym) }} deployed</span></div>
        <div class="hud-body flush">
          <Holdings :positions="s.positions" :sym="sym" :total="s.total" />
        </div>
      </div>

      <div v-if="hasCurve" class="hud">
        <div class="hud-head">
          <h2>Equity curve</h2>
          <div class="seg small">
            <button v-for="r in RANGES" :key="r.l" :class="{ on: active === r.l }"
                    @click="setRange(r)">{{ r.l }}</button>
          </div>
        </div>
        <div class="hud-body">
          <TimeChart ref="equity" kind="equity" :data="hist" :sym="sym" :height="320" />
          <div class="key">
            <span><i class="sw cy"></i>Account</span><span><i class="sw am"></i>Paid in</span>
          </div>
        </div>
      </div>

      <div v-if="hasCurve" class="two">
        <div class="hud">
          <div class="hud-head"><h2>Drawdown</h2>
            <span class="tag">below the high-water mark</span></div>
          <div class="hud-body"><TimeChart kind="drawdown" :data="hist" :height="190" /></div>
        </div>
        <div class="hud">
          <div class="hud-head"><h2>By month</h2></div>
          <div class="hud-body"><TimeChart kind="monthly" :data="hist" :height="190" /></div>
        </div>
      </div>

      <section v-if="!hasCurve" class="hud waiting">
        <span class="tag">Telemetry</span>
        <p class="lede">Charts appear once the bot has marked the book on two
          separate days. It records one point per weeknight, so the curve starts
          filling in from its next run.</p>
      </section>

      <div v-if="store.rebalances.length" class="hud">
        <div class="hud-head"><h2>Rebalance log</h2></div>
        <div class="hud-body flush"><div class="scroll"><table>
          <thead><tr><th>Date</th><th>Bought</th><th>Sold</th><th>Account</th></tr></thead>
          <tbody>
            <tr v-for="r in store.rebalances" :key="r.date">
              <td class="mono">{{ r.date }}</td>
              <td><span v-for="t in r.buys" :key="t" class="pill up">{{ t }}</span>
                  <span v-if="!r.buys.length" class="dim">-</span></td>
              <td><span v-for="t in r.sells" :key="t" class="pill down">{{ t }}</span>
                  <span v-if="!r.sells.length" class="dim">-</span></td>
              <td class="mono">{{ r.account == null ? "-" : money(r.account, sym) }}</td>
            </tr>
          </tbody>
        </table></div></div>
      </div>

      <div class="hud" v-if="h.ranking?.length">
        <div class="hud-head"><h2>Live ranking</h2>
          <span class="tag">six-month momentum, skipping the last month</span></div>
        <div class="hud-body flush">
          <RankingPanel :ranking="h.ranking.slice(0, 14)" :hold="h.hold || 8" />
        </div>
      </div>

      <section class="block">
        <span class="tag">System</span>
        <HealthStrip :items="health" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 20px }
.topbar { display: flex; align-items: center; justify-content: space-between;
  gap: 14px; flex-wrap: wrap }
.tick { display: inline-flex; align-items: center; gap: 8px }
.acct { color: var(--cyan); letter-spacing: .12em }
.seg.small button { padding: 5px 12px; font-size: .68rem }
.two { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)) }
/* Wide screens: holdings and the equity curve sit side by side instead of
   stacking, and the secondary charts go three across. */
@media (min-width: 1500px) {
  .page { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
          gap: 20px; align-items: start }
  .topbar, .hero, .rail, .note, .block { grid-column: 1 / -1 }
  .two { grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)) }
}
.block { display: flex; flex-direction: column; gap: 10px }
.key { display: flex; gap: 18px; padding: 8px 4px 2px; font-size: .74rem; color: var(--faint) }
.key .sw { display: inline-block; width: 14px; height: 2px; margin-right: 7px;
  vertical-align: middle }
.key .cy { background: var(--cyan); box-shadow: 0 0 8px var(--cyan) }
.key .am { background: var(--amber) }
.waiting { padding: 18px 20px; display: flex; flex-direction: column; gap: 7px }
</style>
