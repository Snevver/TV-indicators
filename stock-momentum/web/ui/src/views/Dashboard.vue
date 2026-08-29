<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { store, setTrack } from "../store.js";
import { money, hoursAgo, ago } from "../format.js";
import Hero from "../components/Hero.vue";
import MetricRail from "../components/MetricRail.vue";
import Holdings from "../components/Holdings.vue";
import MoneyChart from "../components/MoneyChart.vue";
import RankingPanel from "../components/RankingPanel.vue";
import HealthStrip from "../components/HealthStrip.vue";
import LaunchPreview from "../components/LaunchPreview.vue";

const s = computed(() => store.state?.summary || {});
const h = computed(() => store.state?.health || {});
const sym = computed(() => store.state?.symbol || "$");
const hist = computed(() => store.history || {});
const empty = computed(() => !Object.keys(s.value.positions || {}).length);
const t212off = computed(() => !h.value?.t212?.configured);
const acct = computed(() => (store.track === "demo" ? "Demo" : "Live"));
const hourly = computed(() => store.hourly?.[store.track] || []);

// The most recent benchmark mark, for the header's "vs S&P 500" line.
const lastBench = computed(() => {
  const r = hourly.value;
  for (let i = r.length - 1; i >= 0; i--)
    if (r[i].bench != null) return Number(r[i].bench);
  return null;
});
// Every benchmark point identical == the stale "flat at the deposit" rows from
// before the tracker fetched the ETF hourly. Warn once rather than leave a
// mystery flat segment.
const benchStale = computed(() => {
  const b = hourly.value.map((r) => r.bench).filter((v) => v != null);
  return b.length > 2 && b.every((v) => Math.abs(v - b[0]) < 0.005);
});

const money2 = ref(null);
const RANGES = [{ l: "24H", h: 24 }, { l: "1M", h: 720 }, { l: "ALL", h: 0 }];
const active = ref("ALL");
const setRange = (r) => { active.value = r.l; money2.value?.range(r.h); };

// A one-second clock, only for the "next refresh in Ns" countdown in the topbar.
const now = ref(Date.now());
let clock = null;
onMounted(() => { clock = setInterval(() => (now.value = Date.now()), 1000); });
onBeforeUnmount(() => clearInterval(clock));
const nextIn = computed(() =>
  store.nextPollAt == null
    ? null
    : Math.max(0, Math.round((store.nextPollAt - now.value) / 1000)));

const metrics = computed(() => [
  { k: "Positions", v: String(Object.keys(s.value.positions || {}).length),
    s: `of ${h.value.hold || 8} target` },
  { k: "Next rebalance", v: (h.value.next_rebalance || "-").split(" ")[0],
    s: (h.value.next_rebalance || "").split(" ")[1] || "unknown" },
  { k: "Last traded", v: s.value.last_rebalance || "never", s: "monthly" },
  { k: "Worst drop", v: (hist.value.maxdd ?? 0).toFixed(1) + "%",
    s: "from the high", tone: (hist.value.maxdd ?? 0) < -0.05 ? "down" : "" },
  { k: "Price feed", v: h.value.bar || "-", s: hoursAgo(h.value.latest_hours) },
]);

const health = computed(() => [
  { label: "Bot", value: hoursAgo(h.value.latest_hours),
    state: h.value.latest_hours != null && h.value.latest_hours < 36 ? "on" : "warn" },
  { label: "Trading 212", value: h.value.t212?.configured ? "on" : "off",
    state: h.value.t212?.configured ? "on" : "off" },
  { label: "Feed", value: store.error ? "error" : "nominal",
    state: store.error ? "warn" : "on" },
]);
</script>

<template>
  <div class="page">
    <div class="topbar">
      <div class="seg">
        <button :class="{ on: store.track === 'live' }"
                @click="setTrack('live')">Live</button>
        <button :class="{ on: store.track === 'demo' }"
                @click="setTrack('demo')">Demo</button>
      </div>
      <span class="tick tag">
        <i class="led on"></i>updated {{ ago(store.fetchedAt) }}<template
          v-if="nextIn != null"> · next in {{ nextIn }}s</template>
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
      <Hero :s="s" :sym="sym" :series="hist.total" :label="acct" :bench="lastBench" />
      <MetricRail :items="metrics" />

      <LaunchPreview v-if="empty" :s="s" :h="h" :sym="sym" />

      <div v-if="hourly.length" class="hud wide">
        <div class="hud-head">
          <h2>You vs the S&amp;P 500</h2>
          <div class="seg small">
            <button v-for="r in RANGES" :key="r.l" :class="{ on: active === r.l }"
                    @click="setRange(r)">{{ r.l }}</button>
          </div>
        </div>
        <div class="hud-body">
          <MoneyChart ref="money2" :rows="hourly" :sym="sym" :height="340" />
          <div class="key">
            <span><i class="sw cy"></i>{{ acct }} account · total</span>
            <span><i class="sw am"></i>Same money in an S&amp;P 500 ETF</span>
          </div>
          <p v-if="benchStale" class="fine flat-note">
            The benchmark's earliest points are flat — that is data from before
            the tracker began fetching the ETF hourly. It clears as new points
            arrive.
          </p>
        </div>
      </div>

      <section v-else-if="!empty" class="hud waiting">
        <span class="tag">Telemetry</span>
        <p class="lede">The chart fills in once the hourly tracker has run a few
          times.</p>
      </section>

      <div v-if="!empty" class="hud">
        <div class="hud-head"><h2>Holdings</h2>
          <span class="tag">{{ money(s.invested, sym) }} · matches T212 Investments tab</span></div>
        <div class="hud-body flush">
          <Holdings :positions="s.positions" :sym="sym" :total="s.total" />
        </div>
      </div>

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
.seg.small button { padding: 5px 12px; font-size: .68rem }
/* Wide screens: holdings and the ranking sit side by side instead of stacking. */
@media (min-width: 1500px) {
  .page { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
          gap: 20px; align-items: start }
  .topbar, .hero, .rail, .note, .block, .wide, .waiting { grid-column: 1 / -1 }
}
.block { display: flex; flex-direction: column; gap: 10px }
.key { display: flex; gap: 18px; padding: 8px 4px 2px; font-size: .74rem; color: var(--faint) }
.key .sw { display: inline-block; width: 14px; height: 2px; margin-right: 7px;
  vertical-align: middle }
.key .cy { background: var(--cyan); box-shadow: 0 0 8px var(--cyan) }
.key .am { background: var(--amber) }
.flat-note { padding: 2px 4px 0; max-width: 60ch }
.waiting { padding: 18px 20px; display: flex; flex-direction: column; gap: 7px }
</style>
