<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, LineType, AreaSeries, LineSeries,
         CandlestickSeries } from "lightweight-charts";
import { money } from "../format.js";

// The account as candlesticks (OHLC bars from samples_1m.csv, bucketed to the
// chosen timeframe), plus a dashed step line at what's been paid in so it's
// clear when the account is above or below cost. `rows` is only a fallback
// account line for the moment before any bars exist.
const props = defineProps({
  candles: { type: Array, default: () => [] },   // [{time, open, high, low, close}]
  paidIn: { type: Array, default: () => [] },    // [{time, value}]
  rows: { type: Array, default: () => [] },      // [{time, total}] hourly, fallback only
  sym: { type: String, default: "$" },
  height: { type: Number, default: 380 },
});

const host = ref(null);
const legend = ref(null);          // {o,h,l,c,up} under the cursor, or the last bar
let chart = null, candleSeries = null, series = [], ro = null;

const css = (n) =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const f = (v) => money(v, props.sym);

const at = (r) => Math.floor(Date.parse(r.time) / 1000);

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

function stepline(pts) {
  const out = [];
  let last = 0;
  for (const p of pts) {
    const t = Number(p.time);
    if (!t || t <= last || p.value == null) continue;
    out.push({ time: t, value: +p.value });
    last = t;
  }
  return out;
}

// Fallback only: an account line from the hourly rows, used until candle bars
// exist.
function rowLine(rows) {
  const out = [];
  let last = 0;
  for (const r of rows) {
    const t = at(r);
    if (!t || t <= last || r.total == null) continue;
    out.push({ time: t, value: Number(r.total) });
    last = t;
  }
  return out;
}

function setLegend(bar) {
  if (!bar) { legend.value = null; return; }
  legend.value = {
    o: bar.open, h: bar.high, l: bar.low, c: bar.close,
    up: bar.close >= bar.open,
  };
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
    rightPriceScale: {
      borderColor: "rgba(140,175,215,.12)",
      scaleMargins: { top: 0.12, bottom: 0.1 },   // candles use most of the height
    },
    timeScale: {
      borderColor: "rgba(140,175,215,.12)",
      timeVisible: true, secondsVisible: false,
    },
    crosshair: {
      mode: 0,
      vertLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
      horzLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
    },
    // Drag the PRICE axis to stretch the candles vertically (TradingView-style);
    // double-click it to reset. Time axis drag stays off.
    handleScale: { axisPressedMouseMove: { time: false, price: true } },
  });

  chart.subscribeCrosshairMove((param) => {
    const bar = candleSeries && param.seriesData.get(candleSeries);
    if (bar) setLegend(bar);
    else setLegend(lastBar);          // cursor off the chart -> show the last bar
  });

  paint();
}

let lastBar = null;

function clear() {
  series.forEach((s) => { try { chart.removeSeries(s); } catch (_) {} });
  series = [];
  candleSeries = null;
}

function paint() {
  if (!chart) return;
  clear();

  const bars = ohlc(props.candles);
  if (bars.length) {
    candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: css("--up"), downColor: css("--down"),
      borderUpColor: css("--up"), borderDownColor: css("--down"),
      wickUpColor: css("--up"), wickDownColor: css("--down"),
      priceLineVisible: false, lastValueVisible: true,
    });
    candleSeries.setData(bars);
    series.push(candleSeries);
    lastBar = bars[bars.length - 1];
    setLegend(lastBar);
  } else {
    const line = rowLine(props.rows);
    if (line.length) {
      const acct = chart.addSeries(AreaSeries, {
        lineColor: css("--cyan"), lineWidth: 2,
        topColor: "rgba(0,240,255,.26)", bottomColor: "rgba(0,240,255,0)",
        priceLineVisible: false, lastValueVisible: true,
      });
      acct.setData(line);
      series.push(acct);
    }
    lastBar = null;
    setLegend(null);
  }

  const paid = stepline(props.paidIn);
  if (paid.length) {
    const pi = chart.addSeries(LineSeries, {
      color: css("--faint"), lineWidth: 1, lineStyle: LineStyle.Dashed,
      lineType: LineType.WithSteps,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    pi.setData(paid);
    series.push(pi);
  }

  chart.timeScale().fitContent();
}

onMounted(() => {
  build();
  ro = new ResizeObserver(() => chart && chart.applyOptions({}));
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => [props.candles, props.paidIn, props.rows], paint, { deep: true });
</script>

<template>
  <div class="chartbox" :style="{ height: height + 'px' }">
    <div v-if="legend" class="ohlc" :class="legend.up ? 'up' : 'down'">
      <span>O <b>{{ f(legend.o) }}</b></span>
      <span>H <b>{{ f(legend.h) }}</b></span>
      <span>L <b>{{ f(legend.l) }}</b></span>
      <span>C <b>{{ f(legend.c) }}</b></span>
    </div>
    <div class="host" ref="host"></div>
  </div>
</template>

<style scoped>
.chartbox { width: 100%; position: relative }
.host { width: 100%; height: 100% }
.ohlc {
  position: absolute; top: 6px; left: 8px; z-index: 3;
  display: flex; gap: 12px; pointer-events: none;
  font-family: var(--f-mono); font-size: .72rem; letter-spacing: .02em;
  color: var(--faint);
}
.ohlc b { font-weight: 600 }
.ohlc.up b { color: var(--up) }
.ohlc.down b { color: var(--down) }
</style>
