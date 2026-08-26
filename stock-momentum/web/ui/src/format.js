// One place for every figure the interface prints, so a currency change or a
// rounding decision lands everywhere at once.
export const sym = (s) => s?.symbol || "$";

export const money = (v, s = "$", dp = 2) =>
  s + (v ?? 0).toLocaleString("en-US",
    { minimumFractionDigits: dp, maximumFractionDigits: dp });

export const signed = (v, dp = 2) =>
  (v >= 0 ? "+" : "−") + Math.abs(v ?? 0).toLocaleString("en-US",
    { minimumFractionDigits: dp, maximumFractionDigits: dp });

export const pct = (v, dp = 2) =>
  (v >= 0 ? "+" : "−") + Math.abs(v ?? 0).toFixed(dp) + "%";

export const shares = (v) =>
  (v ?? 0).toLocaleString("en-US", { maximumFractionDigits: 4 });

export const ago = (ms) => {
  if (ms == null) return "never";
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return (s / 3600).toFixed(1) + "h ago";
  return Math.round(s / 86400) + "d ago";
};

export const hoursAgo = (h) =>
  h == null ? "never" : h < 1 ? Math.round(h * 60) + "m ago" : h.toFixed(1) + "h ago";
