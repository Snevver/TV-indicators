<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { store, setTrack, setTimeframe, TIMEFRAMES } from "../store.js";
import { money, ago } from "../format.js";
import Hero from "../components/Hero.vue";
import Holdings from "../components/Holdings.vue";
import MoneyChart from "../components/MoneyChart.vue";
import RegimeGauge from "../components/RegimeGauge.vue";
import Scoreboard from "../components/Scoreboard.vue";
import RankingPanel from "../components/RankingPanel.vue";
import HealthStrip from "../components/HealthStrip.vue";
import LaunchPreview from "../components/LaunchPreview.vue";

const s = computed(() => store.state?.summary || {});
const h = computed(() => store.state?.health || {});
const sym = computed(() => store.state?.symbol || "$");
const empty = computed(() => !Object.keys(s.value.positions || {}).length);
const t212off = computed(() => !h.value?.t212?.configured);
const acct = computed(() => (store.track === "demo" ? "Demo" : "Live"));
const hourly = computed(() => store.hourly?.[store.track] || []);
const candles = computed(() => store.candles?.[store.track] || []);
const paidIn = computed(() => store.paidIn?.[store.track] || []);

// Most recent benchmark mark, for the command bar's vs-S&P line.
const lastBench = computed(() => {
  const r = hourly.value;
  for (let i = r.length - 1; i >= 0; i--)
    if (r[i].bench != null) return Number(r[i].bench);
  return null;
});

// One-second clock for the "next refresh in Ns" countdown.
const now = ref(Date.now());
let clock = null;
onMounted(() => { clock = setInterval(() => (now.value = Date.now()), 1000); });
onBeforeUnmount(() => clearInterval(clock));
const nextIn = computed(() =>
  store.nextPollAt == null
    ? null
    : Math.max(0, Math.round((store.nextPollAt - now.value) / 1000)));

// Fullscreen the chart panel. The chart's height is an explicit prop (a flex
// "fill" container feeds back into a runaway resize), so on entering/leaving
// fullscreen we just recompute that number.
const chartHud = ref(null);
const chartHeight = ref(400);
function syncChartHeight() {
  const fs = document.fullscreenElement === chartHud.value;
  chartHeight.value = fs ? Math.max(320, window.innerHeight - 96) : 400;
}
function toggleFs() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else chartHud.value?.requestFullscreen?.();
}
onMounted(() => {
  document.addEventListener("fullscreenchange", syncChartHeight);
  window.addEventListener("resize", syncChartHeight);
});
onBeforeUnmount(() => {
  document.removeEventListener("fullscreenchange", syncChartHeight);
  window.removeEventListener("resize", syncChartHeight);
});


const health = computed(() => [
  { label: "Bot", value: h.value.bar || "—",
    state: h.value.latest_hours != null && h.value.latest_hours < 36 ? "on" : "warn" },
  { label: "Trading 212", value: h.value.t212?.configured ? "linked" : "off",
    state: h.value.t212?.configured ? "on" : "off" },
  { label: "Last traded", value: s.value.last_rebalance || "never", state: "on" },
  { label: "Feed", value: store.error ? "error" : "nominal",
    state: store.error ? "warn" : "on" },
]);
</script>

<template>
  <div class="deck">
    <div class="topbar">
      <div class="seg">
        <button :class="{ on: store.track === 'live' }" @click="setTrack('live')">Live</button>
        <button :class="{ on: store.track === 'demo' }" @click="setTrack('demo')">Demo</button>
      </div>
      <span class="tick tag">
        <i class="led on"></i>updated {{ ago(store.fetchedAt) }}<template
          v-if="nextIn != null"> · next in {{ nextIn }}s</template>
      </span>
    </div>

    <p v-if="store.error" class="err bar-span">Feed error: {{ store.error }}</p>

    <section v-if="t212off" class="note bar-span">
      <h2>Trading 212 is not connected</h2>
      <p class="lede">{{ h.t212?.reason || "No API key is set." }} Set one on the
        Settings page. Until then the bot works out the orders and you place them
        by hand.</p>
      <p class="fine"><a href="/settings">Open Settings</a> to add the key.</p>
    </section>

    <template v-else>
      <Hero :s="s" :sym="sym" :label="acct" :bench="lastBench" />

      <LaunchPreview v-if="empty" :s="s" :h="h" :sym="sym" />

      <div class="cols">
        <div class="focus">
          <div v-if="hourly.length || candles.length" ref="chartHud" class="hud chartpanel">
            <div class="hud-head">
              <h2>{{ acct }} · portfolio</h2>
              <div class="seg small">
                <button v-for="t in TIMEFRAMES" :key="t" :class="{ on: store.tf === t }"
                        @click="setTimeframe(t)">{{ t }}</button>
                <button class="fs" @click="toggleFs" title="Fullscreen">⛶</button>
              </div>
            </div>
            <div class="hud-body">
              <MoneyChart :candles="candles" :paid-in="paidIn" :rows="hourly"
                          :sym="sym" :height="chartHeight" />
              <div class="key">
                <span><i class="sw cy"></i>{{ acct }} · account</span>
                <span v-if="paidIn.length"><i class="sw pi"></i>Paid in</span>
                <span class="fine">· drag the price axis to stretch the candles</span>
              </div>
            </div>
          </div>
          <section v-else-if="!empty" class="hud waiting">
            <span class="tag">Telemetry</span>
            <p class="lede">The chart fills in once the hourly tracker has run a few times.</p>
          </section>

          <div v-if="!empty" class="hud">
            <div class="hud-head"><h2>Holdings</h2>
              <span class="tag">{{ money(s.invested, sym) }} · = T212 Investments tab</span></div>
            <div class="hud-body flush">
              <Holdings :positions="s.positions" :sym="sym" :total="s.total" />
            </div>
          </div>

          <div v-if="store.rebalances.length" class="hud">
            <div class="hud-head"><h2>Rebalance log</h2></div>
            <div class="hud-body flush"><div class="scroll"><table>
              <thead><tr><th>Date</th><th>Bought</th><th>Sold</th><th>Value at close</th></tr></thead>
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
        </div>

        <div class="rail">
          <RegimeGauge :regime="h.regime" />
          <Scoreboard :board="s.scoreboard" />
          <div class="hud" v-if="h.ranking?.length">
            <div class="hud-head"><h2>Live ranking</h2>
              <span class="tag">6-month momentum · skip last month</span></div>
            <div class="hud-body flush">
              <RankingPanel :ranking="h.ranking.slice(0, 14)" :hold="h.hold || 8" />
            </div>
          </div>
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
.deck { display: flex; flex-direction: column; gap: 16px }
.topbar { display: flex; align-items: center; justify-content: space-between;
  gap: 14px; flex-wrap: wrap }
.tick { display: inline-flex; align-items: center; gap: 8px }
.seg.small button { padding: 5px 12px; font-size: .68rem }
.fs { padding: 5px 9px; font-size: .72rem; line-height: 1 }
.waiting { padding: 18px 20px; display: flex; flex-direction: column; gap: 7px }

/* Native fullscreen: solid backdrop, square corners. The chart's own height
   (chartHeight prop) is bumped to the viewport on fullscreenchange -- no flex
   "fill", which would feed back into a runaway resize. */
.chartpanel:fullscreen { background: var(--void); padding: 14px 18px; clip-path: none }
.chartpanel:fullscreen :deep(.chartbox) { max-width: 1400px; margin: 0 auto }
.key { display: flex; gap: 18px; padding: 8px 4px 2px; font-size: .74rem; color: var(--faint) }
.key .sw { display: inline-block; width: 14px; height: 2px; margin-right: 7px; vertical-align: middle }
.key .cy { background: var(--cyan); box-shadow: 0 0 8px var(--cyan) }
.key .am { background: var(--amber) }
.key .fn { background: var(--faint) }
.key .pi { background: var(--faint); height: 0; border-top: 2px dashed var(--faint) }
.block { display: flex; flex-direction: column; gap: 10px }

/* Two instrument columns: a wide focus stack (chart, holdings, log) and a
   narrower rail (regime, scoreboard, ranking). Each column is its own flex
   stack so panels of very different heights still pack tight. One column
   below 1300px. */
.cols { display: flex; flex-direction: column; gap: 16px }
.focus, .rail { display: flex; flex-direction: column; gap: 16px; min-width: 0 }
@media (min-width: 1300px) {
  .cols {
    display: grid; align-items: start;
    grid-template-columns: minmax(0, 1.55fr) minmax(330px, 1fr);
  }
}
</style>
