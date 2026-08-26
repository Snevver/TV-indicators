<script setup>
import { ref, watch, onMounted } from "vue";

// Tweens a figure when it changes, so a poll that moves the account reads as
// movement rather than a silent swap. Respects reduced-motion.
const props = defineProps({
  value: { type: Number, default: 0 },
  format: { type: Function, required: true },
  duration: { type: Number, default: 650 },
});

const shown = ref(props.value);
const flashing = ref("");
let raf = null;

function tween(from, to) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || from === to) { shown.value = to; return; }
  const t0 = performance.now();
  cancelAnimationFrame(raf);
  const step = (t) => {
    const p = Math.min(1, (t - t0) / props.duration);
    const e = 1 - Math.pow(1 - p, 3);            // ease-out cubic
    shown.value = from + (to - from) * e;
    if (p < 1) raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}

watch(() => props.value, (to, from) => {
  if (to === from) return;
  flashing.value = to > from ? "flash-up" : "flash-down";
  setTimeout(() => (flashing.value = ""), 700);
  tween(from ?? 0, to);
});
onMounted(() => (shown.value = props.value));
</script>

<template>
  <span class="nf mono" :class="flashing">{{ format(shown) }}</span>
</template>

<style scoped>
.nf { transition: color .2s, text-shadow .2s }
.flash-up   { color: var(--up);   text-shadow: var(--glow-lime) }
.flash-down { color: var(--down); text-shadow: var(--glow-red) }
</style>
