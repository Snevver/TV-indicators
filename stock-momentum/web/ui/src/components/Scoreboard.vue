<script setup>
import { computed } from "vue";
import { signed } from "../format.js";

// Live book return vs the frozen backtest, month by month -- a real
// out-of-sample record that grows one row per rebalance. Data is
// store.state.summary.scoreboard from the bot's --json run.
const props = defineProps({ board: { type: Object, default: () => ({}) } });
const rows = computed(() => props.board?.rows || []);
const total = computed(() => props.board?.total || {});
const cls = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
</script>

<template>
  <div class="hud">
    <div class="hud-head">
      <h2>Live vs backtest</h2>
      <span class="tag">out-of-sample · per rebalance</span>
    </div>
    <div class="hud-body flush">
      <template v-if="rows.length">
        <div class="cum">
          <div><span class="tag">live</span>
            <b class="mono" :class="cls(total.live_pct)">{{ signed(total.live_pct ?? 0) }}%</b></div>
          <div><span class="tag">model</span>
            <b class="mono">{{ signed(total.model_pct ?? 0) }}%</b></div>
          <div><span class="tag">gap</span>
            <b class="mono" :class="cls(total.gap_pct)">{{ signed(total.gap_pct ?? 0) }}%</b></div>
        </div>
        <div class="scroll"><table>
          <thead><tr><th>Month</th><th>Live</th><th>Model</th><th>Δ</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.month">
              <td class="mono">{{ r.month }}</td>
              <td class="mono" :class="cls(r.live_pct)">{{ signed(r.live_pct) }}%</td>
              <td class="mono">{{ r.model_pct == null ? "—" : signed(r.model_pct) + "%" }}</td>
              <td class="mono" :class="cls(r.gap_pct)">
                {{ r.gap_pct == null ? "—" : signed(r.gap_pct) + "%" }}</td>
            </tr>
          </tbody>
        </table></div>
      </template>
      <p v-else class="fine pad">
        First rebalance is logged. The live-versus-backtest record fills in one
        row per month, starting at the next rebalance.
      </p>
    </div>
  </div>
</template>

<style scoped>
.cum {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px;
  background: var(--hair); border-bottom: 1px solid var(--hair);
}
.cum div {
  display: flex; flex-direction: column; gap: 3px; padding: 11px 16px;
  background: var(--panel-solid);
}
.cum b { font-size: 1.05rem; color: var(--ink) }
.pad { padding: 14px 16px }
</style>
