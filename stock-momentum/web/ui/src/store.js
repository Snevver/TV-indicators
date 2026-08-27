import { reactive } from "vue";
import * as api from "./api.js";

// One shared store. The dashboard reads it; the poller keeps it fresh.
// The dashboard shows one thing now: the connected Trading 212 account.
export const store = reactive({
  track: "live",
  state: null,
  history: null,
  rebalances: [],
  fetchedAt: null,
  loading: true,
  error: "",
});

export async function load() {
  store.error = "";
  try {
    const [s, h, r] = await Promise.all([
      api.getState("live"), api.getHistory("live"), api.getRebalances(),
    ]);
    store.state = s; store.history = h; store.rebalances = r.rows || [];
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
