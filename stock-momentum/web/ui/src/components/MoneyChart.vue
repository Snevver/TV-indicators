<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, AreaSeries, CandlestickSeries, TickMarkType }
  from "lightweight-charts";
import { signed } from "../format.js";

// The account's open profit/loss (euros) as candlesticks -- OHLC bars from
// samples_1m.csv, bucketed to the chosen timeframe. It is P/L, not capital, so a
// monthly contribution doesn't put a step in it. A faint line marks break-even.
// `rows` is a fallback account line, used only when `fallback` is set (the demo
// track, which has no sampler).
const props = defineProps({
  candles: { type: Array, default: () => [] },   // [{time, open, high, low, close}] = P/L
  rows: { type: Array, default: () => [] },       // [{time, total}] hourly, fallback only
  fallback: { type: Boolean, default: false },
  deposited: { type: Number, default: 0 },        // for the % readout
  sym: { type: String, default: "$" },
  height: { type: Number, default: 380 },
});

const host = ref(null);
const legend = ref(null);          // {o,h,l,c,up,pct} under the cursor, or the last bar
// Series are created once and kept across polls -- tearing them down and
// re-adding every refresh is what reset the view. On a refresh we only setData().
let chart = null, candleS = null, lineS = null, zeroLine = null, ro = null;
let lastBar = null, framedCount = -99, hovering = false;

const css = (n) =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const f = (v) => signed(v, props.sym);

const at = (r) => Math.floor(Date.parse(r.time) / 1000);

// Lightweight Charts labels its time axis in UTC by default, not the
// viewer's local timezone -- these hand it Date, which formats local.
const tickTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const tickDate = (t) => new Date(t * 1000).toLocaleDateString([], { day: "2-digit", month: "short" });
const tickMarkFormatter = (t, kind) =>
  kind >= TickMarkType.Time ? tickTime(t) : tickDate(t);

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

// Fallback only: an account line from the hourly rows, until candle bars exist.
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
  const chg = bar.close - bar.open;              // this bar's move, in P/L euros
  legend.value = {
    o: bar.open, h: bar.high, l: bar.low, c: bar.close,
    up: chg >= 0,                                 // colour follows the candle
    chg,
    pct: props.deposited ? chg / props.deposited * 100 : null,
  };
}

function build() {
  if (!host.value) return;
  chart = createChart(host.value, {
    width: host.value.clientWidth || 600,
    height: host.value.clientHeight || props.height,
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
      scaleMargins: { top: 0.12, bottom: 0.1 },
    },
    timeScale: {
      borderColor: "rgba(140,175,215,.12)",
      timeVisible: true, secondsVisible: false,
      tickMarkFormatter,
    },
    localization: { timeFormatter: tickTime },
    crosshair: {
      mode: 0,
      vertLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
      horzLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
    },
    // Drag the PRICE axis to stretch the candles vertically; double-click resets.
    handleScale: { axisPressedMouseMove: { time: false, price: true } },
  });

  chart.subscribeCrosshairMove((param) => {
    hovering = param.time != null;
    const bar = candleS && param.seriesData.get(candleS);
    if (bar) setLegend(bar);
    else setLegend(lastBar);          // cursor off chart -> last bar
  });

  render();
}

function drop(s) { if (s) { try { chart.removeSeries(s); } catch (_) {} } return null; }

function render() {
  if (!chart) return;

  const bars = ohlc(props.candles);
  const line = !bars.length && props.fallback ? rowLine(props.rows) : [];

  if (bars.length) {
    lineS = drop(lineS);
    if (!candleS) {
      candleS = chart.addSeries(CandlestickSeries, {
        upColor: css("--up"), downColor: css("--down"),
        borderUpColor: css("--up"), borderDownColor: css("--down"),
        wickUpColor: css("--up"), wickDownColor: css("--down"),
        priceLineVisible: false, lastValueVisible: true,
      });
      zeroLine = candleS.createPriceLine({
        price: 0, color: css("--faint"), lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "break-even",
      });
    }
    candleS.setData(bars);
    lastBar = bars[bars.length - 1];
    if (!hovering) setLegend(lastBar);
  } else {
    candleS = drop(candleS); zeroLine = null;
    lastBar = null;
    if (line.length) {
      if (!lineS) {
        lineS = chart.addSeries(AreaSeries, {
          lineColor: css("--cyan"), lineWidth: 2,
          topColor: "rgba(0,240,255,.26)", bottomColor: "rgba(0,240,255,0)",
          priceLineVisible: false, lastValueVisible: true,
        });
      }
      lineS.setData(line);
    } else {
      lineS = drop(lineS);
    }
    if (!hovering) setLegend(null);
  }

  // Frame to the bars' own extent, once -- on first load or a big change
  // (timeframe / track switch, where the bar count jumps). A routine poll adds
  // one bar and must not touch the user's zoom/pan.
  const ts = chart.timeScale();
  if (bars.length) {
    if (Math.abs(bars.length - framedCount) > 3) {
      const span = bars.length > 1 ? bars[1].time - bars[0].time : 60;
      ts.setVisibleRange({
        from: bars[0].time - span,
        to: bars[bars.length - 1].time + span * 4,
      });
      framedCount = bars.length;
    }
  } else if (line.length) {
    if (framedCount !== -1) { ts.fitContent(); framedCount = -1; }
  } else {
    framedCount = -99;
  }
}

// Explicit resize, not autoSize. The observed element (.host) is sized by
// .chartbox, whose height is a definite pixel value from the `height` prop --
// never dependent on the chart's own size -- so resize() can't feed back into a
// grow loop (the fullscreen-stretch bug).
onMounted(() => {
  build();
  ro = new ResizeObserver(() => {
    if (chart && host.value) chart.resize(host.value.clientWidth, host.value.clientHeight);
  });
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => [props.candles, props.rows, props.deposited], render, { deep: true });
</script>

<template>
  <div class="chartbox" :style="{ height: height + 'px' }">
    <div v-if="legend" class="ohlc" :class="legend.up ? 'up' : 'down'">
      <span>O <b>{{ f(legend.o) }}</b></span>
      <span>H <b>{{ f(legend.h) }}</b></span>
      <span>L <b>{{ f(legend.l) }}</b></span>
      <span>C <b>{{ f(legend.c) }}</b></span>
      <span class="pct">{{ f(legend.chg) }}<template
        v-if="legend.pct != null"> ({{ legend.pct >= 0 ? "+" : "" }}{{ legend.pct.toFixed(2) }}%)</template></span>
    </div>
    <div class="host" ref="host"></div>
  </div>
</template>

<style scoped>
.chartbox { width: 100%; position: relative }
.host { width: 100%; height: 100% }
.ohlc {
  position: absolute; top: 6px; left: 8px; right: 8px; z-index: 3;
  display: flex; gap: 6px 12px; flex-wrap: wrap; pointer-events: none;
  font-family: var(--f-mono); font-size: .72rem; letter-spacing: .02em;
  color: var(--faint);
}
.ohlc b { font-weight: 600 }
.ohlc.up b, .ohlc.up .pct { color: var(--up) }
.ohlc.down b, .ohlc.down .pct { color: var(--down) }
.ohlc .pct { font-weight: 600 }
</style>
