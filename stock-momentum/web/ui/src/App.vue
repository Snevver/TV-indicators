<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from "vue";
import { store, load, startPolling } from "./store.js";
import Dashboard from "./views/Dashboard.vue";
import Settings from "./views/Settings.vue";
import Strategy from "./views/Strategy.vue";
import Simulate from "./views/Simulate.vue";

// A router this small does not need a router library.
const route = ref(location.pathname);
const VIEWS = { "/": Dashboard, "/simulate": Simulate,
                "/strategy": Strategy, "/settings": Settings };
const view = computed(() => VIEWS[route.value] || Dashboard);

function go(path, ev) {
  ev?.preventDefault();
  if (route.value === path) return;
  history.pushState({}, "", path);
  route.value = path;
  window.scrollTo({ top: 0 });
}
const onPop = () => (route.value = location.pathname);

let stop = null;
onMounted(() => {
  window.addEventListener("popstate", onPop);
  load();
  stop = startPolling(30);
});
onBeforeUnmount(() => { window.removeEventListener("popstate", onPop); stop?.(); });

const NAV = [
  { p: "/", l: "Dashboard" },
  { p: "/simulate", l: "Simulate" },
  { p: "/strategy", l: "Strategy" },
  { p: "/settings", l: "Settings" },
];
</script>

<template>
  <header class="chrome">
    <a class="brand" href="/" @click="go('/', $event)">
      <span class="mark"></span>
      <span class="name">MOMENTUM</span>
      <span class="ver tag">v2</span>
    </a>
    <nav>
      <a v-for="n in NAV" :key="n.p" :href="n.p" :class="{ on: route === n.p }"
         @click="go(n.p, $event)">{{ n.l }}</a>
    </nav>
    <form method="post" action="/logout" class="out">
      <input type="hidden" name="csrf" :value="csrfToken" />
      <button class="quiet" type="submit">Sign out</button>
    </form>
  </header>

  <main class="shell">
    <div v-if="store.loading" class="boot">
      <span class="pulse"></span><span class="tag">establishing link…</span>
    </div>
    <component v-else :is="view" />
  </main>
</template>

<script>
export default {
  computed: {
    csrfToken() {
      return document.querySelector('meta[name="csrf"]')?.content || "";
    },
  },
};
</script>

<style scoped>
.chrome {
  position: sticky; top: 0; z-index: 30; display: flex; align-items: center;
  gap: 22px; flex-wrap: wrap; padding: 0 clamp(14px, 3vw, 28px); height: 58px;
  background: rgba(5,9,17,.82); backdrop-filter: blur(16px) saturate(1.3);
  border-bottom: 1px solid var(--edge);
}
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none }
.mark { width: 9px; height: 9px; background: var(--cyan); box-shadow: var(--glow-cyan);
  transform: rotate(45deg); animation: blip 2.6s ease-in-out infinite }
.name { font-family: var(--f-mono); font-weight: 700; font-size: .92rem;
  letter-spacing: .22em; color: var(--ink) }
.ver { color: var(--cyan); opacity: .75 }
nav { display: flex; gap: 4px; flex: 1; min-width: 0 }
/* Four items no longer fit a phone in one row. Let them wrap rather
   than push the document wider than the viewport. */
@media (max-width: 640px) { nav { flex-wrap: wrap; flex-basis: 100%; order: 3 } }
nav a { font-family: var(--f-mono); font-size: .72rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--faint); padding: 7px 13px;
  border: 1px solid transparent; transition: .14s }
nav a:hover { color: var(--body); border-color: var(--hair); text-shadow: none }
nav a.on { color: var(--cyan); border-color: var(--edge-hot);
  background: rgba(0,240,255,.07); text-shadow: none }
.out { margin: 0 }

.shell { width: 100%; margin: 0; padding: 24px clamp(14px, 2vw, 32px) 88px }
/* Very wide screens only: stop lines of prose running to 3000px. */
@media (min-width: 2200px) { .shell { max-width: 2100px; margin: 0 auto } }
.boot { display: flex; align-items: center; gap: 12px; padding: 80px 0;
  justify-content: center }
.pulse { width: 10px; height: 10px; background: var(--cyan); transform: rotate(45deg);
  box-shadow: var(--glow-cyan); animation: blip 1.1s ease-in-out infinite }
@media (max-width: 640px) {
  .chrome { height: auto; padding: 10px 14px; gap: 10px }
  .brand { flex: 1 }
  nav a { padding: 6px 10px; font-size: .68rem }
}
</style>
