// Every call is same-origin and carries the session cookie. A 401 means the
// session expired, and the only correct response is to go back to the
// server-rendered login page — the SPA never handles the password.
const csrf = () =>
  document.querySelector('meta[name="csrf"]')?.content ||
  window.__CSRF__ || "";

async function req(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (r.status === 401) {
    window.location = "/login";
    throw new Error("signed out");
  }
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const getState = () => req("/api/state");
export const getHistory = () => req("/api/history");
export const getHourly = () => req("/api/hourly");
export const getCandles = (tf) => req(`/api/candles?tf=${tf}`);
export const getRebalances = () => req("/api/rebalances");
export const getConfig = () => req("/api/config");

export const saveConfig = (values) =>
  req("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...values, csrf: csrf() }),
  });

export const runAction = (action) =>
  req("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ action, csrf: csrf() }),
  });

export const simBounds = () => req("/api/simulate/bounds");
export const simulate = (p) =>
  req("/api/simulate?" + new URLSearchParams(p).toString());
