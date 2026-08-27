<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, AreaSeries, LineSeries } from "lightweight-charts";

// The hourly money-over-time curve: the real account value against what the
// same deposits would be worth in the benchmark ETF. `rows` is
// [{time, total, bench}] with an ISO hour string and either value possibly null.
const props = defineProps({
  rows: { type: Array, default: () => [] },
  faint: { type: Array, default: () => [] },   // the other account, shown dim
  sym: { type: String, default: "$" },
  height: { type: Number, default: 300 },
});

const host = ref(null);
let chart = null, series = [], ro = null;

const css = (n) =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const at = (r) => Math.floor(Date.parse(r.time) / 1000);

// lightweight-charts wants strictly ascending, unique timestamps and no nulls.
function points(rows, key) {
  const out = [];
  let last = 0;
  for (const r of rows) {
    const t = at(r);
    if (!t || t <= last || r[key] == null) continue;
    out.push({ time: t, value: Number(r[key]) });
    last = t;
  }
  return out;
}

function build() {
  if (!host.value) return;
  chart = createChart(host.value, {
    height: props.height,
    autoSize: true,
    layout: {
      background: { color: "transparent" },
      textColor: css("--faint"),
      fontFamily: css("--f-mono") || "monospace",
      fontSize: 10,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: "rgba(140,175,215,.06)" },
      horzLines: { color: "rgba(140,175,215,.08)" },
    },
    rightPriceScale: { borderColor: "rgba(140,175,215,.12)" },
    timeScale: {
      borderColor: "rgba(140,175,215,.12)",
      timeVisible: true, secondsVisible: false,
      fixLeftEdge: true, fixRightEdge: true,
    },
    crosshair: {
      mode: 0,
      vertLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
      horzLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
    },
    handleScale: { axisPressedMouseMove: false },
  });
  paint();
}

function clear() {
  series.forEach((s) => { try { chart.removeSeries(s); } catch (_) {} });
  series = [];
}

function paint() {
  if (!chart) return;
  clear();
  const acctPts = points(props.rows, "total");
  if (!acctPts.length) return;

  const other = points(props.faint, "total");
  if (other.length) {
    const o = chart.addSeries(LineSeries, {
      color: css("--faint"), lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    o.setData(other);
    series.push(o);
  }

  const acct = chart.addSeries(AreaSeries, {
    lineColor: css("--cyan"), lineWidth: 2,
    topColor: "rgba(0,240,255,.26)", bottomColor: "rgba(0,240,255,0)",
    priceLineVisible: false, lastValueVisible: true,
    crosshairMarkerBorderColor: css("--void"),
    crosshairMarkerBackgroundColor: css("--cyan"),
  });
  acct.setData(acctPts);
  series.push(acct);

  const bench = chart.addSeries(LineSeries, {
    color: css("--amber"), lineWidth: 1, lineStyle: LineStyle.Dashed,
    priceLineVisible: false, lastValueVisible: true,
    crosshairMarkerVisible: false,
  });
  bench.setData(points(props.rows, "bench"));
  series.push(bench);

  chart.timeScale().fitContent();
}

onMounted(() => {
  build();
  ro = new ResizeObserver(() => chart && chart.applyOptions({}));
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => [props.rows, props.faint], paint, { deep: true });
</script>

<template>
  <div class="chartbox" ref="host" :style="{ height: height + 'px' }"></div>
</template>

<style scoped>
.chartbox { width: 100%; position: relative }
</style>
