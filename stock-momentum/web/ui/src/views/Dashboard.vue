<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { store, setTrack } from "../store.js";
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
const modelRows = computed(() => store.model?.[store.track] || []);
const nPos = computed(() => Object.keys(s.value.positions || {}).length);

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

const money2 = ref(null);
const RANGES = [{ l: "24H", h: 24 }, { l: "1M", h: 720 }, { l: "ALL", h: 0 }];
const active = ref("ALL");
const setRange = (r) => { active.value = r.l; money2.value?.range(r.h); };

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
      <Hero class="a-bar" :s="s" :sym="sym" :label="acct" :bench="lastBench"
            :positions="nPos" :target="h.hold || 8"
            :nextRebalance="h.next_rebalance" />

      <LaunchPreview v-if="empty" class="bar-span" :s="s" :h="h" :sym="sym" />

      <div v-if="hourly.length" class="hud a-chart">
        <div class="hud-head">
          <h2>You vs the S&amp;P 500</h2>
          <div class="seg small">
            <button v-for="r in RANGES" :key="r.l" :class="{ on: active === r.l }"
                    @click="setRange(r)">{{ r.l }}</button>
          </div>
        </div>
        <div class="hud-body">
          <MoneyChart ref="money2" :rows="hourly" :model="modelRows"
                      :sym="sym" :height="360" />
          <div class="key">
            <span><i class="sw cy"></i>{{ acct }} · total</span>
            <span><i class="sw am"></i>S&amp;P 500 ETF</span>
            <span v-if="modelRows.length"><i class="sw fn"></i>Strategy · backtested</span>
          </div>
        </div>
      </div>
      <section v-else-if="!empty" class="hud a-chart waiting">
        <span class="tag">Telemetry</span>
        <p class="lede">The chart fills in once the hourly tracker has run a few times.</p>
      </section>

      <RegimeGauge class="a-regime" :regime="h.regime" />
      <Scoreboard class="a-score" :board="s.scoreboard" />

      <div v-if="!empty" class="hud a-hold">
        <div class="hud-head"><h2>Holdings</h2>
          <span class="tag">{{ money(s.invested, sym) }} · = T212 Investments tab</span></div>
        <div class="hud-body flush">
          <Holdings :positions="s.positions" :sym="sym" :total="s.total" />
        </div>
      </div>

      <div class="hud a-rank" v-if="h.ranking?.length">
        <div class="hud-head"><h2>Live ranking</h2>
          <span class="tag">6-month momentum, skipping the last month</span></div>
        <div class="hud-body flush">
          <RankingPanel :ranking="h.ranking.slice(0, 14)" :hold="h.hold || 8" />
        </div>
      </div>

      <div v-if="store.rebalances.length" class="hud a-log">
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

      <section class="block a-health">
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
.waiting { padding: 18px 20px; display: flex; flex-direction: column; gap: 7px }
.key { display: flex; gap: 18px; padding: 8px 4px 2px; font-size: .74rem; color: var(--faint) }
.key .sw { display: inline-block; width: 14px; height: 2px; margin-right: 7px; vertical-align: middle }
.key .cy { background: var(--cyan); box-shadow: 0 0 8px var(--cyan) }
.key .am { background: var(--amber) }
.key .fn { background: var(--faint) }
.block { display: flex; flex-direction: column; gap: 10px }

/* The command-centre grid: a wide focus column (command bar + chart + tables)
   and a narrower instrument column (regime + scoreboard). Collapses to one
   column below 1300px. */
@media (min-width: 1300px) {
  .deck {
    display: grid; gap: 16px; align-items: start;
    grid-template-columns: minmax(0, 1.55fr) minmax(320px, 1fr);
    grid-template-areas:
      "topbar topbar"
      "bar    bar"
      "chart  regime"
      "chart  score"
      "hold   rank"
      "log    log"
      "health health";
  }
  .topbar { grid-area: topbar }
  .a-bar { grid-area: bar } .a-chart { grid-area: chart }
  .a-regime { grid-area: regime } .a-score { grid-area: score }
  .a-hold { grid-area: hold } .a-rank { grid-area: rank }
  .a-log { grid-area: log } .a-health { grid-area: health }
  .bar-span { grid-column: 1 / -1 }
}
</style>
