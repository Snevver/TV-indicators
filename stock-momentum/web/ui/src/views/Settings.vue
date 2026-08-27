<script setup>
import { ref, onMounted } from "vue";
import * as api from "../api.js";

const rows = ref([]); const creds = ref([]); const errors = ref({});
const saved = ref(false); const paths = ref({}); const busy = ref(false);
const form = ref({}); const killOut = ref("");

const stored = (name) => {
  const f = rows.value.find((x) => x.name === name);
  return f ? seed(f) : "";
};

// Choice values come back as the bot stores them; the option list is lowercase.
// Normalise so the <select> matches instead of rendering blank.
function seed(f) {
  const v = f.value ?? "";
  return f.choices ? String(v).toLowerCase() : v;
}

async function load() {
  const d = await api.getConfig();
  rows.value = d.fields; creds.value = d.credentials || []; paths.value = d.paths;
  d.fields.forEach((f) => (form.value[f.name] = seed(f)));
}

onMounted(load);

async function save() {
  const arming = form.value.MOMENTUM_KILL === "on" && stored("MOMENTUM_KILL") !== "on";
  if (arming && !window.confirm(
    "Turn ON the kill switch?\n\nThis sells EVERY strategy position at market " +
    "immediately and freezes all trading until you turn it back off.")) {
    form.value.MOMENTUM_KILL = stored("MOMENTUM_KILL") || "off";
    return;
  }
  busy.value = true; saved.value = false; errors.value = {}; killOut.value = "";
  try {
    const d = await api.saveConfig({ ...form.value });
    if (d.errors && Object.keys(d.errors).length) { errors.value = d.errors; return; }
    saved.value = true; rows.value = d.fields; creds.value = d.credentials || [];
    d.fields.forEach((f) => (form.value[f.name] = seed(f)));
    if (arming) {
      killOut.value = "running the kill switch…";
      const r = await api.runAction("kill");
      killOut.value = ((r.out || "") + (r.err ? "\n" + r.err : "")).trim()
        || (r.ok ? "kill switch done." : "kill switch failed with no output");
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
      A few things live here. Everything else (the Trading&nbsp;212 keys, the
      Discord webhook and bot token, the channel and your user id) is set once
      over SSH in <code>{{ paths.etc }}</code> and only shown below.
    </p>

    <p v-if="saved" class="ok">Saved. The next bot run picks it up.</p>
    <p v-if="errors._" class="err">{{ errors._ }}</p>
    <pre v-if="killOut" class="out">{{ killOut }}</pre>

    <form class="hud form" @submit.prevent="save">
      <div v-for="f in rows" :key="f.name" class="field" :class="{ bad: errors[f.name] }">
        <label :for="f.name">{{ f.label }}</label>
        <p class="help">{{ f.help }}</p>

        <select v-if="f.choices" :id="f.name" v-model="form[f.name]">
          <option v-for="c in f.choices" :key="c" :value="c">{{ c }}</option>
        </select>
        <input v-else :id="f.name" v-model="form[f.name]" type="text">

        <p v-if="errors[f.name]" class="err">{{ errors[f.name] }}</p>
      </div>
      <button type="submit" :disabled="busy">{{ busy ? "Saving…" : "Save" }}</button>
    </form>

    <section class="hud creds">
      <h2>Credentials</h2>
      <p class="help">
        Set in <code>{{ paths.etc }}</code> (mode 600, over SSH). Editing that
        file needs no restart; the next bot run reads it.
      </p>
      <ul>
        <li v-for="c in creds" :key="c.label">
          <span class="mark" :class="{ on: c.set }">{{ c.set ? "✓" : "✗" }}</span>
          <span class="cl">{{ c.label }}</span>
          <code class="cn">{{ c.note }}</code>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; max-width: 620px; margin: 0 auto }
.form { padding: 22px 24px; display: flex; flex-direction: column; gap: 20px;
  align-items: flex-start }
.field { display: flex; flex-direction: column; gap: 5px; width: 100% }
.field.bad input, .field.bad select { border-color: var(--red) }
.help { font-size: .77rem; color: var(--faint); max-width: 56ch }
.ok { color: var(--up); font-size: .85rem }
.creds { padding: 18px 24px }
.creds h2 { margin: 0 0 4px; font-size: .95rem }
.creds ul { list-style: none; margin: 12px 0 0; padding: 0; display: flex;
  flex-direction: column; gap: 9px }
.creds li { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap }
.mark { font-weight: 700; color: var(--red) }
.mark.on { color: var(--up) }
.cl { font-size: .85rem }
.cn { font-size: .72rem; color: var(--faint) }
</style>
