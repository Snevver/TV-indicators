<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, AreaSeries, LineSeries } from "lightweight-charts";

// Your account against what the same money would be worth in an S&P 500 ETF.
// `rows` is [{time, total, bench}] with an ISO hour string; either value may be
// null. The account line is `total` (holdings + cash) because that is the whole
// of the money being compared. Range is driven from the parent via range().
const props = defineProps({
  rows: { type: Array, default: () => [] },
  model: { type: Array, default: () => [] },   // [{time, value}] daily backtest
  sym: { type: String, default: "$" },
  height: { type: Number, default: 320 },
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

// null unless every visible bench point is the same value -- that is the stale
// "flat at the deposit" data from before the tracker fetched the ETF hourly, and
// the parent uses this to show a one-line caveat rather than a mystery.
const benchFlat = ref(false);

function paint() {
  if (!chart) return;
  clear();
  const acctPts = points(props.rows, "total");
  if (!acctPts.length) return;

  const acct = chart.addSeries(AreaSeries, {
    lineColor: css("--cyan"), lineWidth: 2,
    topColor: "rgba(0,240,255,.26)", bottomColor: "rgba(0,240,255,0)",
    priceLineVisible: false, lastValueVisible: true,
    crosshairMarkerBorderColor: css("--void"),
    crosshairMarkerBackgroundColor: css("--cyan"),
  });
  acct.setData(acctPts);
  series.push(acct);

  const benchPts = points(props.rows, "bench");
  benchFlat.value = benchPts.length > 2 &&
    benchPts.every((p) => Math.abs(p.value - benchPts[0].value) < 0.005);
  if (benchPts.length) {
    const bench = chart.addSeries(LineSeries, {
      color: css("--amber"), lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    bench.setData(benchPts);
    series.push(bench);
  }

  // The frozen backtest, run forward from the funding date. Daily, so it steps
  // where the live line is smooth -- deliberately a quiet reference line.
  const modelPts = points(props.model, "value");
  if (modelPts.length) {
    const bt = chart.addSeries(LineSeries, {
      color: css("--faint"), lineWidth: 1,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    bt.setData(modelPts);
    series.push(bt);
  }

  chart.timeScale().fitContent();
}

// Show the last `hours` of data, or everything when hours is 0.
function range(hours) {
  const rows = props.rows || [];
  if (!chart || !rows.length) return;
  if (!hours) return chart.timeScale().fitContent();
  const last = at(rows[rows.length - 1]);
  chart.timeScale().setVisibleRange({ from: last - hours * 3600, to: last });
}
defineExpose({ range, benchFlat });

onMounted(() => {
  build();
  ro = new ResizeObserver(() => chart && chart.applyOptions({}));
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => [props.rows, props.model], paint, { deep: true });
</script>

<template>
  <div class="chartbox" ref="host" :style="{ height: height + 'px' }"></div>
</template>

<style scoped>
.chartbox { width: 100%; position: relative }
</style>
