import { reactive } from "vue";
import * as api from "./api.js";

// One shared store. The dashboard reads it; the poller keeps it fresh.
// Two real Trading 212 accounts: `track` is the one the account-specific panels
// show; the money-over-time chart holds both.
export const store = reactive({
  track: localStorage.getItem("track") === "demo" ? "demo" : "live",
  state: null,
  history: null,
  rebalances: [],
  hourly: { demo: [], live: [] },
  fetchedAt: null,
  loading: true,
  error: "",
});

export function setTrack(track) {
  if (track !== "demo" && track !== "live") return;
  store.track = track;
  localStorage.setItem("track", track);
  store.loading = true;
  load();
}

export async function load() {
  store.error = "";
  try {
    const [s, h, r, hd, hl] = await Promise.all([
      api.getState(store.track), api.getHistory(store.track), api.getRebalances(),
      api.getHourly("demo"), api.getHourly("live"),
    ]);
    store.state = s; store.history = h; store.rebalances = r.rows || [];
    store.hourly = { demo: hd.rows || [], live: hl.rows || [] };
    store.fetchedAt = Date.now();
  } catch (e) {
    if (e.message !== "signed out") store.error = e.message;
  } finally {
    store.loading = false;
  }
}

// Poll every 30s, but never while the tab is hidden — no reason to keep the
// mini PC awake all night for a page nobody is looking at.
export function startPolling(seconds = 30) {
  let timer = null;
  const tick = () => { if (!document.hidden) load(); };
  const arm = () => { stop(); timer = setInterval(tick, seconds * 1000); };
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else { tick(); arm(); }
  });
  arm();
  return stop;
}
