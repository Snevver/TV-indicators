<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { createChart, LineStyle, LineSeries } from "lightweight-charts";

// Three lines on one scale: the strategy, holding all forty, and the index.
// All start from the same budget, so the vertical gap is the whole answer.
const props = defineProps({ result: Object, sym: { type: String, default: "$" } });
const host = ref(null);
let chart = null, made = [];

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const LINES = [
  { key: "strategy", color: "--cyan", width: 2, style: LineStyle.Solid },
  { key: "hold40", color: "--amber", width: 1.5, style: LineStyle.Solid },
  { key: "spy", color: "--muted", width: 1.5, style: LineStyle.Dashed },
];

function build() {
  chart = createChart(host.value, {
    autoSize: true, height: 420,
    layout: { background: { color: "transparent" }, textColor: css("--faint"),
      fontFamily: css("--f-mono") || "monospace", fontSize: 10,
      attributionLogo: false },
    grid: { vertLines: { color: "rgba(140,175,215,.06)" },
            horzLines: { color: "rgba(140,175,215,.08)" } },
    rightPriceScale: { borderColor: "rgba(140,175,215,.12)" },
    timeScale: { borderColor: "rgba(140,175,215,.12)" },
    crosshair: { mode: 0,
      vertLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") },
      horzLine: { color: css("--cyan"), width: 1, style: LineStyle.Dashed,
                  labelBackgroundColor: css("--cyan-dim") } },
  });
  paint();
}

function paint() {
  if (!chart) return;
  made.forEach((s) => { try { chart.removeSeries(s); } catch (_) {} });
  made = [];
  const r = props.result;
  if (!r?.dates?.length) return;
  for (const spec of LINES) {
    const vals = r[spec.key];
    if (!vals) continue;
    const s = chart.addSeries(LineSeries, {
      color: css(spec.color), lineWidth: spec.width, lineStyle: spec.style,
      priceLineVisible: false, lastValueVisible: true,
    });
    s.setData(r.dates.map((d, i) => ({ time: d, value: vals[i] })));
    made.push(s);
  }
  chart.timeScale().fitContent();
}

onMounted(build);
onBeforeUnmount(() => { chart?.remove(); chart = null; });
watch(() => props.result, paint, { deep: true });
</script>

<template><div class="box" ref="host"></div></template>
<style scoped>.box { width: 100%; height: 420px }</style>
