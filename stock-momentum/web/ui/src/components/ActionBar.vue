<script setup>
import { ref } from "vue";
import { store, act } from "../store.js";

const out = ref("");
const ACTIONS = [
  { id: "dry", label: "Dry run" },
  { id: "refresh", label: "Refresh prices" },
  { id: "test", label: "Test Discord" },
  { id: "probe", label: "Probe T212" },
  { id: "check", label: "Compare broker" },
];

// Kept apart from the row above, and styled differently, because one of these
// can spend real money. "Offer" only posts to Discord; "Apply" is the one that
// places an order, and only ever after reading your reaction back.
const SMOKE = [
  { id: "smoke_offer", label: "Offer test trade" },
  { id: "smoke_poll", label: "Apply my reaction" },
  { id: "smoke_status", label: "Test status" },
];

async function go(id) {
  out.value = `> ${id}\nrunning… a price download can take up to a minute.`;
  const r = await act(id);
  out.value = ((r.out || "") + (r.err ? "\n" + r.err : "")).trim()
    || (r.ok ? "done — no output" : "failed with no output");
}
</script>

<template>
  <div>
    <div class="bar">
      <button v-for="a in ACTIONS" :key="a.id" class="quiet"
              :disabled="!!store.busy" @click="go(a.id)">
        {{ store.busy === a.id ? "running…" : a.label }}
      </button>
    </div>

    <div class="bar live">
      <span class="tag warn">Real money · ~$2 round trip</span>
      <button v-for="a in SMOKE" :key="a.id" class="quiet"
              :disabled="!!store.busy" @click="go(a.id)">
        {{ store.busy === a.id ? "running…" : a.label }}
      </button>
    </div>
    <pre v-if="out" class="out">{{ out }}</pre>
  </div>
</template>

<style scoped>
.bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px }
.bar.live { align-items: center; padding: 8px 10px; border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--amber) 35%, transparent);
  background: color-mix(in srgb, var(--amber) 7%, transparent) }
.tag.warn { color: var(--amber); letter-spacing: .06em }
</style>
