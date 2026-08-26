<script setup>
import { ref, onMounted } from "vue";
import * as api from "../api.js";

const rows = ref([]); const errors = ref({}); const saved = ref(false);
const paths = ref({}); const busy = ref(false);
const form = ref({}); const clear = ref({});

// Choice values come back as the bot stores them — MOMENTUM_CURRENCY is
// uppercase — while the option list is lowercase. Without normalising, the
// select matches nothing, renders blank, and saves whatever the browser picks.
function seed(f) {
  if (f.secret) return "";
  const v = f.value ?? "";
  return f.choices ? String(v).toLowerCase() : v;
}

onMounted(async () => {
  const d = await api.getConfig();
  rows.value = d.fields; paths.value = d.paths;
  d.fields.forEach((f) => (form.value[f.name] = seed(f)));
});

async function save() {
  busy.value = true; saved.value = false; errors.value = {};
  try {
    const payload = { ...form.value };
    Object.entries(clear.value).forEach(([k, v]) => { if (v) payload["clear__" + k] = "1"; });
    const d = await api.saveConfig(payload);
    if (d.errors && Object.keys(d.errors).length) errors.value = d.errors;
    else {
      saved.value = true; rows.value = d.fields; clear.value = {};
      d.fields.forEach((f) => (form.value[f.name] = seed(f)));
    }
  } catch (e) { errors.value = { _: String(e) }; }
  finally { busy.value = false; }
}
</script>

<template>
  <div class="page">
    <div>
      <span class="tag">Configuration</span>
      <h1>Settings</h1>
    </div>
    <p class="lede">
      Written to <code>{{ paths.config }}</code> at mode 600. The bot reads
      <code>{{ paths.etc }}</code> first and this second, so anything set here wins.
    </p>

    <p v-if="saved" class="ok">Saved. The next bot run picks it up.</p>
    <p v-if="errors._" class="err">{{ errors._ }}</p>

    <form class="hud form" @submit.prevent="save">
      <div v-for="f in rows" :key="f.name" class="field" :class="{ bad: errors[f.name] }">
        <label :for="f.name">{{ f.label }}</label>
        <p class="help">{{ f.help }}</p>

        <select v-if="f.choices" :id="f.name" v-model="form[f.name]">
          <option v-for="c in f.choices" :key="c" :value="c">{{ c }}</option>
        </select>
        <template v-else-if="f.secret">
          <input :id="f.name" v-model="form[f.name]" type="password"
                 autocomplete="new-password"
                 :placeholder="f.set ? `stored · ${f.hint} — blank keeps it` : 'not set'">
          <label class="clear"><input type="checkbox" v-model="clear[f.name]"> Remove it</label>
        </template>
        <input v-else :id="f.name" v-model="form[f.name]" type="text">

        <p v-if="errors[f.name]" class="err">{{ errors[f.name] }}</p>
      </div>
      <button type="submit" :disabled="busy">{{ busy ? "Saving…" : "Save" }}</button>
    </form>

    <section class="note alert">
      <h2>Before switching Trading to live</h2>
      <p class="lede">Add the key, set a pie id, then run <b>Probe T212</b> and
        <b>Compare broker</b> from the dashboard. Only switch once the live book
        matches what Trading 212 actually holds — the bot plans orders from
        whichever book you pick.</p>
      <p class="fine">Without a pie id it reads your whole account, including
        investments unrelated to this strategy.</p>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; max-width: 620px }
.form { padding: 22px 24px; display: flex; flex-direction: column; gap: 20px;
  align-items: flex-start }
.field { display: flex; flex-direction: column; gap: 5px; width: 100% }
.field.bad input, .field.bad select { border-color: var(--red) }
.help { font-size: .77rem; color: var(--faint); max-width: 56ch }
.clear { display: flex; align-items: center; gap: 7px; font-size: .76rem;
  color: var(--muted); font-weight: 400 }
.clear input { width: auto }
.ok { color: var(--up); font-size: .85rem }
</style>
