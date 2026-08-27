<script setup>
import { ref, computed, onMounted } from "vue";
import * as api from "../api.js";

const rows = ref([]); const creds = ref([]); const errors = ref({});
const saved = ref(false); const paths = ref({}); const busy = ref(false);
const form = ref({}); const killOut = ref("");

// Choice values come back as the bot stores them; option lists are lowercase.
function seed(f) {
  const v = f.value ?? "";
  return f.choices ? String(v).toLowerCase() : v;
}

const fields = computed(() => rows.value.filter((f) => f.kind !== "button"));
const kill = computed(() => rows.value.find((f) => f.kind === "button"));

async function load() {
  const d = await api.getConfig();
  rows.value = d.fields; creds.value = d.credentials || []; paths.value = d.paths;
  d.fields.forEach((f) => (form.value[f.name] = seed(f)));
}

onMounted(load);

async function post() {
  const d = await api.saveConfig({ ...form.value });
  if (d.errors && Object.keys(d.errors).length) { errors.value = d.errors; return false; }
  rows.value = d.fields; creds.value = d.credentials || [];
  d.fields.forEach((f) => (form.value[f.name] = seed(f)));
  return true;
}

async function save() {
  busy.value = true; saved.value = false; errors.value = {};
  try {
    if (await post()) saved.value = true;
  } catch (e) { errors.value = { _: String(e) }; }
  finally { busy.value = false; }
}

async function armKill() {
  if (!window.confirm(
    "Arm the kill switch?\n\nThis sells EVERY strategy position at market " +
    "immediately and freezes all trading until you press it again.")) return;
  busy.value = true; saved.value = false; errors.value = {}; killOut.value = "";
  form.value[kill.value.name] = "on";
  try {
    if (!await post()) return;
    killOut.value = "selling everything and freezing…";
    const r = await api.runAction("kill");
    killOut.value = ((r.out || "") + (r.err ? "\n" + r.err : "")).trim()
      || (r.ok ? "kill switch armed." : "kill switch failed with no output");
  } catch (e) { errors.value = { _: String(e) }; }
  finally { busy.value = false; }
}

async function resumeTrading() {
  busy.value = true; saved.value = false; errors.value = {}; killOut.value = "";
  form.value[kill.value.name] = "off";
  try {
    if (await post()) killOut.value = "trading resumed. The next bot run rebuilds the basket.";
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

    <form class="hud form" @submit.prevent="save">
      <div v-for="f in fields" :key="f.name" class="field" :class="{ bad: errors[f.name] }">
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

    <section v-if="kill" class="hud danger" :class="{ armed: kill.armed }">
      <h2>{{ kill.label }}</h2>
      <p class="help">{{ kill.help }}</p>
      <pre v-if="killOut" class="out">{{ killOut }}</pre>
      <p v-if="kill.armed" class="frozen">Trading is frozen.</p>
      <button v-if="!kill.armed" type="button" class="arm" :disabled="busy"
              @click="armKill">{{ busy ? "Working…" : "Arm kill switch" }}</button>
      <button v-else type="button" class="resume" :disabled="busy"
              @click="resumeTrading">{{ busy ? "Working…" : "Resume trading" }}</button>
    </section>

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

.danger { padding: 18px 24px; display: flex; flex-direction: column; gap: 10px;
  align-items: flex-start; border-left: 2px solid var(--down) }
.danger.armed { border-left-color: var(--down); background: rgba(255,77,109,.06) }
.danger h2 { margin: 0; font-size: .95rem; color: var(--down) }
.danger .frozen { font-size: .85rem; color: var(--down); font-weight: 600 }
.danger .out { width: 100%; white-space: pre-wrap }
.arm, .resume { border-color: var(--down); color: var(--down) }
.arm:hover:not(:disabled) { background: var(--down); color: var(--void) }
.resume { border-color: var(--up); color: var(--up) }
.resume:hover:not(:disabled) { background: var(--up); color: var(--void) }

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
