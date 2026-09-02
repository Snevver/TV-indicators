<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, LineType, AreaSeries, LineSeries,
         CandlestickSeries } from "lightweight-charts";
import { money } from "../format.js";

// The account as candlesticks (OHLC bars from samples_1m.csv, bucketed to the
// chosen timeframe), plus a dashed step line at what's been paid in so it's
// clear when the account is above or below cost. `rows` is a fallback account
// line, used only when `fallback` is set (the demo track, which has no sampler).
const props = defineProps({
  candles: { type: Array, default: () => [] },   // [{time, open, high, low, close}]
  paidIn: { type: Array, default: () => [] },    // [{time, value}]
  rows: { type: Array, default: () => [] },      // [{time, total}] hourly, fallback only
  fallback: { type: Boolean, default: false },   // draw the hourly line when no bars
  sym: { type: String, default: "$" },
  height: { type: Number, default: 380 },
});

const host = ref(null);
const legend = ref(null);          // {o,h,l,c,up} under the cursor, or the last bar
// Series are created once and kept across polls -- tearing them down and
// re-adding every refresh is what reset the view. On a refresh we only
// setData().
let chart = null, candleS = null, lineS = null, paidS = null, ro = null;
let lastBar = null, framedCount = -99, hovering = false;

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

// Paid-in amount in force at time t (the step line's last value at or before t).
function paidAt(t) {
  let v = null;
  for (const p of props.paidIn) {
    if (Number(p.time) <= t) v = +p.value;
    else break;
  }
  if (v == null && props.paidIn.length) v = +props.paidIn[props.paidIn.length - 1].value;
  return v;
}

function setLegend(bar, t) {
  if (!bar) { legend.value = null; return; }
  const base = paidAt(t || lastBar?.time || 0);
  legend.value = {
    o: bar.open, h: bar.high, l: bar.low, c: bar.close,
    up: bar.close >= bar.open,
    // % the account is above (or below) what's been paid in, at this bar.
    pct: base ? (bar.close - base) / base * 100 : null,
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
    hovering = param.time != null;
    const bar = candleS && param.seriesData.get(candleS);
    if (bar) setLegend(bar, param.time);
    else setLegend(lastBar, lastBar?.time);   // cursor off chart -> last bar
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
    }
    candleS.setData(bars);
    lastBar = bars[bars.length - 1];
    if (!hovering) setLegend(lastBar, lastBar.time);
  } else {
    candleS = drop(candleS);
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

  const paid = stepline(props.paidIn);
  if (paid.length) {
    if (!paidS) {
      paidS = chart.addSeries(LineSeries, {
        color: css("--faint"), lineWidth: 1, lineStyle: LineStyle.Dashed,
        lineType: LineType.WithSteps,
        priceLineVisible: false, lastValueVisible: true,
        crosshairMarkerVisible: false,
      });
    }
    paidS.setData(paid);
  } else {
    paidS = drop(paidS);
  }

  // Frame the candles to their own extent (the weeks-long paid-in line would
  // otherwise squash them). Only on the first load or a big change -- timeframe
  // or track switch, where the bar count jumps. A routine poll adds one bar and
  // must not touch the user's zoom/pan.
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
// never `auto`, never dependent on the chart's own size -- so resize() can't
// feed back into a grow loop (the fullscreen-stretch bug).
onMounted(() => {
  build();
  ro = new ResizeObserver(() => {
    if (chart && host.value) {
      chart.resize(host.value.clientWidth, host.value.clientHeight);
    }
  });
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => [props.candles, props.paidIn, props.rows], render, { deep: true });
</script>

<template>
  <div class="chartbox" :style="{ height: height + 'px' }">
    <div v-if="legend" class="ohlc" :class="legend.up ? 'up' : 'down'">
      <span>O <b>{{ f(legend.o) }}</b></span>
      <span>H <b>{{ f(legend.h) }}</b></span>
      <span>L <b>{{ f(legend.l) }}</b></span>
      <span>C <b>{{ f(legend.c) }}</b></span>
      <span v-if="legend.pct != null" class="pct" :class="legend.pct >= 0 ? 'up' : 'down'">
        {{ legend.pct >= 0 ? "▲" : "▼" }} {{ Math.abs(legend.pct).toFixed(2) }}%
        <span class="vp">vs paid in</span>
      </span>
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
.ohlc.up b { color: var(--up) }
.ohlc.down b { color: var(--down) }
.ohlc .pct { font-weight: 600 }
.ohlc .pct.up { color: var(--up) }
.ohlc .pct.down { color: var(--down) }
.ohlc .vp { font-weight: 400; color: var(--faint); opacity: .7 }
</style>
