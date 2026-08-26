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
    <pre v-if="out" class="out">{{ out }}</pre>
  </div>
</template>

<style scoped>
.bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px }
</style>
