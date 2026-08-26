import { reactive } from "vue";
import * as api from "./api.js";

// One shared store. The dashboard reads it; the poller keeps it fresh.
export const store = reactive({
  track: new URLSearchParams(location.search).get("track") === "live"
    ? "live" : "paper",
  state: null,
  history: null,
  rebalances: [],
  fetchedAt: null,
  loading: true,
  error: "",
  busy: "",
});

export async function load(track = store.track) {
  store.track = track;
  store.error = "";
  try {
    const [s, h, r] = await Promise.all([
      api.getState(track), api.getHistory(track), api.getRebalances(),
    ]);
    store.state = s; store.history = h; store.rebalances = r.rows || [];
    store.fetchedAt = Date.now();
  } catch (e) {
    if (e.message !== "signed out") store.error = e.message;
  } finally {
    store.loading = false;
  }
}

export function setTrack(track) {
  const u = new URL(location.href);
  u.searchParams.set("track", track);
  history.replaceState({}, "", u);
  store.loading = true;
  load(track);
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

export async function act(action) {
  store.busy = action;
  try {
    return await api.runAction(action);
  } finally {
    store.busy = "";
    if (action === "refresh" || action === "sync") await load();
  }
}
