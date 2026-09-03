import { reactive } from "vue";
import * as api from "./api.js";

// How often the page pulls fresh figures. pulse.py patches latest.json every
// ~10s, so a 20s poll keeps the header's big number close to live. The candle
// bars only change once a minute and rebalances monthly -- re-fetching those on
// the same 20s tick is a few cheap local file reads on the mini PC.
export const POLL_SECONDS = 20;

// Candlestick timeframes the chart offers; must match data.py TF_SECONDS + "1M".
export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "60m", "4h", "1d", "1M"];

const ls = (k, ok, dflt) => (ok.includes(localStorage.getItem(k))
  ? localStorage.getItem(k) : dflt);

// One shared store. The dashboard reads it; the poller keeps it fresh.
// The live Trading 212 account only -- the bot also runs a demo account, but
// the dashboard no longer shows it.
export const store = reactive({
  tf: ls("tf", TIMEFRAMES, "15m"),
  state: null,
  history: null,
  rebalances: [],
  hourly: [],
  candles: [],                // P/L OHLC bars for the account
  fetchedAt: null,
  nextPollAt: null,          // epoch ms of the next scheduled fetch, for the countdown
  loading: true,
  error: "",
});

export function setTimeframe(tf) {
  if (!TIMEFRAMES.includes(tf)) return;
  store.tf = tf;
  localStorage.setItem("tf", tf);
  load();
}

export async function load() {
  store.error = "";
  try {
    const [s, h, r, hd, cd] = await Promise.all([
      api.getState(), api.getHistory(), api.getRebalances(),
      api.getHourly(), api.getCandles(store.tf),
    ]);
    store.state = s; store.history = h; store.rebalances = r.rows || [];
    store.hourly = hd.rows || [];
    store.candles = cd.bars || [];
    store.fetchedAt = Date.now();
  } catch (e) {
    if (e.message !== "signed out") store.error = e.message;
  } finally {
    store.loading = false;
    // Every fetch -- scheduled or manual -- restarts the clock.
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
