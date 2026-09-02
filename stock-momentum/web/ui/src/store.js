import { reactive } from "vue";
import * as api from "./api.js";

// How often the page pulls fresh figures. pulse.py writes a new 1-minute candle
// bar each minute, so ~60s keeps the chart within a bar of live. The header
// figures (latest.json, ~90s server timer) just refresh a touch more often than
// they change -- harmless.
export const POLL_SECONDS = 60;

// Candlestick timeframes the chart offers; must match data.py TF_SECONDS + "1M".
export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "60m", "4h", "1d", "1M"];

const ls = (k, ok, dflt) => (ok.includes(localStorage.getItem(k))
  ? localStorage.getItem(k) : dflt);

// One shared store. The dashboard reads it; the poller keeps it fresh.
// Two real Trading 212 accounts: `track` is the one the account-specific panels
// show; the money-over-time chart holds both.
export const store = reactive({
  track: localStorage.getItem("track") === "demo" ? "demo" : "live",
  tf: ls("tf", TIMEFRAMES, "15m"),
  state: null,
  history: null,
  rebalances: [],
  hourly: { demo: [], live: [] },
  model: { demo: [], live: [] },      // the frozen backtest, per track
  candles: { demo: [], live: [] },    // P/L OHLC bars for the account, per track
  fetchedAt: null,
  nextPollAt: null,          // epoch ms of the next scheduled fetch, for the countdown
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

export function setTimeframe(tf) {
  if (!TIMEFRAMES.includes(tf)) return;
  store.tf = tf;
  localStorage.setItem("tf", tf);
  load();
}

export async function load() {
  store.error = "";
  try {
    const track = store.track;
    const wantCandles = track === "live";
    const [s, h, r, hd, hl, cd] = await Promise.all([
      api.getState(track), api.getHistory(track), api.getRebalances(track),
      api.getHourly("demo"), api.getHourly("live"),
      wantCandles ? api.getCandles(track, store.tf) : Promise.resolve(null),
    ]);
    store.state = s; store.history = h; store.rebalances = r.rows || [];
    store.hourly = { demo: hd.rows || [], live: hl.rows || [] };
    store.model = { demo: hd.model || [], live: hl.model || [] };
    store.candles = { ...store.candles, [track]: (cd && cd.bars) || [] };
    store.fetchedAt = Date.now();
  } catch (e) {
    if (e.message !== "signed out") store.error = e.message;
  } finally {
    store.loading = false;
    // Every fetch -- scheduled, manual, or a track switch -- restarts the clock.
    store.nextPollAt = Date.now() + POLL_SECONDS * 1000;
  }
}

// Poll on POLL_SECONDS, but never while the tab is hidden — no reason to keep
// the mini PC awake all night for a page nobody is looking at.
export function startPolling(seconds = POLL_SECONDS) {
  let timer = null;
  const tick = () => { if (!document.hidden) load(); };
  const arm = () => {
    stop();
    store.nextPollAt = Date.now() + seconds * 1000;
    timer = setInterval(tick, seconds * 1000);
  };
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else { tick(); arm(); }
  });
  arm();
  return stop;
}
