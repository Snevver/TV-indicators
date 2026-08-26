<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, AreaSeries, LineSeries, HistogramSeries }
  from "lightweight-charts";

// One wrapper over TradingView's lightweight-charts, styled to the console.
// kind: "equity" (account vs paid in), "drawdown" (area), "monthly" (histogram).
const props = defineProps({
  kind: { type: String, default: "equity" },
  data: { type: Object, default: () => ({}) },
  sym: { type: String, default: "$" },
  height: { type: Number, default: 300 },
});

const host = ref(null);
let chart = null, series = [], ro = null;

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

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
    timeScale: { borderColor: "rgba(140,175,215,.12)", fixLeftEdge: true, fixRightEdge: true },
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
  const d = props.data || {};
  const t = d.dates || [];
  if (!t.length) return;

  if (props.kind === "equity") {
    const acct = chart.addSeries(AreaSeries, {
      lineColor: css("--cyan"), lineWidth: 2,
      topColor: "rgba(0,240,255,.26)", bottomColor: "rgba(0,240,255,0)",
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerBorderColor: css("--void"),
      crosshairMarkerBackgroundColor: css("--cyan"),
    });
    acct.setData(t.map((x, i) => ({ time: x, value: d.total[i] })));
    const paid = chart.addSeries(LineSeries, {
      color: css("--amber"), lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    paid.setData(t.map((x, i) => ({ time: x, value: d.deposited[i] })));
    series = [acct, paid];
  } else if (props.kind === "drawdown") {
    const s = chart.addSeries(AreaSeries, {
      lineColor: css("--down"), lineWidth: 2,
      topColor: "rgba(255,77,109,0)", bottomColor: "rgba(255,77,109,.30)",
      invertFilledArea: true, priceLineVisible: false,
    });
    s.setData(t.map((x, i) => ({ time: x, value: d.drawdown[i] })));
    series = [s];
  } else {
    const s = chart.addSeries(HistogramSeries, { priceLineVisible: false });
    s.setData((d.monthly || []).map((m) => ({
      time: m.month + "-01",
      value: m.pct,
      color: m.pct >= 0 ? "rgba(110,255,123,.75)" : "rgba(255,77,109,.75)",
    })));
    series = [s];
  }
  chart.timeScale().fitContent();
}

function range(months) {
  const t = props.data?.dates || [];
  if (!chart || !t.length) return;
  if (!months) return chart.timeScale().fitContent();
  const to = new Date(t[t.length - 1]);
  const from = new Date(to); from.setMonth(from.getMonth() - months);
  chart.timeScale().setVisibleRange({
    from: from.toISOString().slice(0, 10),
    to: t[t.length - 1],
  });
}
defineExpose({ range });

onMounted(() => {
  build();
  ro = new ResizeObserver(() => chart && chart.applyOptions({}));
  ro.observe(host.value);
});
onBeforeUnmount(() => { ro?.disconnect(); chart?.remove(); chart = null; });
watch(() => props.data, paint, { deep: true });
</script>

<template>
  <div class="chartbox" ref="host" :style="{ height: height + 'px' }"></div>
</template>

<style scoped>
.chartbox { width: 100%; position: relative }
</style>
