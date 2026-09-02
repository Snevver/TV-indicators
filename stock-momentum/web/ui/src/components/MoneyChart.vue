<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, AreaSeries, LineSeries, CandlestickSeries }
  from "lightweight-charts";

// Your account against what the same money would be worth in an S&P 500 ETF.
// The account series is `candles` (OHLC bars from samples_1m.csv, bucketed to
// the chosen timeframe) -- drawn as candlesticks when mode === "candle", else
// as an area line of the bar closes. `rows` [{time, total, bench}] is still the
// hourly source for the amber S&P line (and a fallback account line before the
// sampler has produced anything). `model` is the daily backtest.
const props = defineProps({
  rows: { type: Array, default: () => [] },
  model: { type: Array, default: () => [] },
  candles: { type: Array, default: () => [] },   // [{time, open, high, low, close}]
  mode: { type: String, default: "line" },       // "line" | "candle"
  rangeHours: { type: Number, default: 0 },      // line mode: visible window; 0 = all
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

// Candle bars: server sends `time` already as int UTC seconds.
function ohlc(bars) {
  const out = [];
  let last = 0;
  for (const b of bars) {
    const t = Number(b.time);
    if (!t || t <= last) continue;
    out.push({ time: t, open: +b.open, high: +b.high, low: +b.low, close: +b.close });
    last = t;
  }
  return out;
}

function closes(bars) {
  const out = [];
  let last = 0;
  for (const b of bars) {
    const t = Number(b.time);
    if (!t || t <= last || b.close == null) continue;
    out.push({ time: t, value: +b.close });
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

  const candlePts = ohlc(props.candles);
  const linePts = props.candles.length ? closes(props.candles)
                                       : points(props.rows, "total");

  if (props.mode === "candle" && candlePts.length) {
    const cs = chart.addSeries(CandlestickSeries, {
      upColor: css("--up"), downColor: css("--down"),
      borderUpColor: css("--up"), borderDownColor: css("--down"),
      wickUpColor: css("--up"), wickDownColor: css("--down"),
      priceLineVisible: false, lastValueVisible: true,
    });
    cs.setData(candlePts);
    series.push(cs);
  } else if (linePts.length) {
    const acct = chart.addSeries(AreaSeries, {
      lineColor: css("--cyan"), lineWidth: 2,
      topColor: "rgba(0,240,255,.26)", bottomColor: "rgba(0,240,255,0)",
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerBorderColor: css("--void"),
      crosshairMarkerBackgroundColor: css("--cyan"),
    });
    acct.setData(linePts);
    series.push(acct);
  } else {
    return;
  }

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

  // The frozen backtest, run forward from the funding date. Daily -- too coarse
  // to sit under intraday candles, so line mode only. Held back until it is a
  // real line (>= 8 points) rather than a 2-point stub.
  if (props.mode !== "candle") {
    const modelPts = points(props.model, "value");
    if (modelPts.length >= 8) {
      const bt = chart.addSeries(LineSeries, {
        color: css("--faint"), lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      bt.setData(modelPts);
      series.push(bt);
    }
  }

  applyWindow();
}

// Line mode with a range picked: show that many trailing hours. Otherwise fit
// everything (candles always fit -- the timeframe already bounds the bar count).
function applyWindow() {
  if (!chart) return;
  const bars = props.candles;
  if (props.mode === "line" && props.rangeHours && bars.length) {
    const last = Number(bars[bars.length - 1].time);
    chart.timeScale().setVisibleRange({
      from: last - props.rangeHours * 3600, to: last,
    });
  } else {
    chart.timeScale().fitContent();
  }
}
defineExpose({ benchFlat });

onMounted(() => {
  build();
  ro = new ResizeObserver(() => chart && chart.applyOptions({}));
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => [props.rows, props.model, props.candles, props.mode, props.rangeHours],
      paint, { deep: true });
</script>

<template>
  <div class="chartbox" ref="host" :style="{ height: height + 'px' }"></div>
</template>

<style scoped>
.chartbox { width: 100%; position: relative }
</style>
