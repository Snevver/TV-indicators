"""Every timeline in the report, each one starting from $1,000.

One engine, many windows. The strategy is run once over the full history and the
resulting daily equity curve is sliced; each slice is then rebased so it opens at
$1,000. That matters: rebasing a slice is not the same as running the strategy
fresh inside it, but the shape and the percentages are identical either way, and
it keeps every window on the same set of decisions.

Benchmarks are built the same way for each window: SPY, and the forty names held
equal-weight and never touched.

Rebalances happen at the CLOSE of the first trading day of each month, which is
the point stockmom.py measures.
"""
import json
import numpy as np
import pandas as pd

D = "/home/user/tv-indicators/_data-export/data"
U = ["AAPL","GOOGL","AMZN","GOOG","MSFT","BAC","XOM","JPM","INTC","NFLX","C","CSCO",
     "WFC","GE","PFE","JNJ","CVX","T","QCOM","GS","WMT","PG","IBM","ORCL","VZ","DIS",
     "HD","MRK","BA","BKNG","MU","CMCSA","KO","MCD","CAT","SLB","COP","AMGN","UNH","NVDA"]
LOOKBACK, SKIP, HOLD, COST_BPS, BASE = 126, 21, 8, 10.0, 1000.0

s = pd.read_csv(f"{D}/sp500_daily.csv.gz", usecols=["time","ticker","close"])
s["time"] = pd.to_datetime(s["time"])
px = s[s.ticker.isin(U)].pivot(index="time", columns="ticker", values="close").sort_index()

e = pd.read_csv(f"{D}/etfs_daily.csv.gz", usecols=["time","ticker","close"])
e["time"] = pd.to_datetime(e["time"])
spy = e[e.ticker == "SPY"].set_index("time")["close"].sort_index().reindex(px.index).ffill()

idx = px.index
anch = pd.Series(np.arange(len(idx)), index=idx).groupby([idx.year, idx.month]).first().to_numpy()
anch = [int(a) for a in anch if a >= LOOKBACK + SKIP + 1]
end_i = len(idx) - 1
print("full history:", idx[anch[0]].date(), "->", idx[end_i].date(), f"({len(anch)} rebalances)")


def momentum(a):
    past, recent = px.iloc[a - LOOKBACK - SKIP], px.iloc[a - SKIP]
    ok = past.notna() & recent.notna() & px.iloc[a].notna() & (past > 0)
    return ((recent / past - 1.0)[ok]).sort_values(ascending=False)


# ---- run the strategy once, over everything --------------------------------
cash, shares, curve, log = BASE, {}, [], []
for k, a in enumerate(anch):
    top = list(momentum(a).index[:HOLD])
    prices = px.iloc[a]
    value = cash if not shares else sum(n * prices[t] for t, n in shares.items())
    turn = len(set(top) ^ set(shares)) / max(len(top) + len(shares), 1)
    value *= (1.0 - turn * COST_BPS / 10_000.0)
    shares = {t: (value / HOLD) / prices[t] for t in top}
    log.append({"date": str(idx[a].date()), "basket": top,
                "value": round(value, 2), "turnover": round(turn, 3),
                "kept": len(set(top) & set(log[-1]["basket"])) if log else 0})
    nxt = anch[k + 1] if k + 1 < len(anch) else end_i + 1
    for i in range(a, min(nxt, end_i + 1)):
        curve.append((idx[i], sum(n * px.iloc[i][t] for t, n in shares.items())))

strat = pd.Series(dict(curve))

# equal-weight all forty, rebalanced never — one buy at the very start, held.
# Names with no price at the start are simply not in it.
live0 = [t for t in U if not np.isnan(px.iloc[anch[0]][t])]
n40 = {t: (BASE / len(live0)) / px.iloc[anch[0]][t] for t in live0}
all40 = pd.Series({idx[i]: sum(k * px.iloc[i][t] for t, k in n40.items())
                   for i in range(anch[0], end_i + 1)})

full = pd.DataFrame({"strategy": strat, "all40": all40,
                     "spy": spy.iloc[anch[0]:end_i + 1]}).dropna()


def stats(c):
    r = c.pct_change().dropna()
    peak = c.cummax()
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    tot = float(c.iloc[-1] / c.iloc[0])
    dd = (peak - c) / peak
    return {"final": round(float(c.iloc[0] and BASE * tot), 2),
            "ret_pct": round((tot - 1) * 100, 2),
            "cagr_pct": round((tot ** (1 / yrs) - 1) * 100, 2) if yrs > 0.5 else None,
            "maxdd_pct": round(float(dd.max()) * 100, 2),
            "maxdd_date": str(dd.idxmax().date()),
            "vol_ann_pct": round(float(r.std() * np.sqrt(252)) * 100, 2),
            "sharpe": round(float(r.mean() / r.std() * np.sqrt(252)), 2),
            "best_day_pct": round(float(r.max()) * 100, 2),
            "worst_day_pct": round(float(r.min()) * 100, 2),
            "years": round(yrs, 2)}


def window(label, lo, hi, note=""):
    """Slice the curves, rebase each to $1,000, and measure."""
    w = full.loc[lo:hi]
    if len(w) < 5:
        return None
    reb = w / w.iloc[0] * BASE
    return {"label": label, "note": note,
            "start": str(reb.index[0].date()), "end": str(reb.index[-1].date()),
            "stats": {c: stats(reb[c]) for c in reb.columns},
            "series": {"t": [d.strftime("%Y-%m-%d") for d in reb.index],
                       **{c: [round(float(v), 2) for v in reb[c]] for c in reb.columns}}}


WINDOWS = [
 ("Everything", full.index[0], full.index[-1], "Every rebalance in the data, one continuous run."),
 ("The financial crisis", "2007-10-01", "2009-06-30", "Peak to the bottom and the first leg out."),
 ("The long recovery", "2009-07-01", "2015-12-31", "Six and a half years with no real bear market."),
 ("Flat and choppy", "2015-01-01", "2016-12-31", "Two years the index went nowhere."),
 ("Covid", "2020-01-01", "2020-12-31", "A 34% crash and a full recovery inside one year."),
 ("The 2022 bear", "2022-01-01", "2022-12-31", "Rates up, growth down, a year with nowhere to hide."),
 ("The last five years", "2021-08-25", full.index[-1], "The recent regime, whatever it is."),
 ("This year", "2026-01-02", full.index[-1], "Year to date, the window you already saw."),
]

report = {"generated": str(full.index[-1].date()), "base": BASE,
          "windows": [w for w in (window(*a) for a in WINDOWS) if w]}

# ---- calendar years --------------------------------------------------------
years = []
for y in sorted({d.year for d in full.index}):
    w = full[full.index.year == y]
    if len(w) < 100:
        continue
    prev = full[full.index < w.index[0]]
    o = prev.iloc[-1] if len(prev) else w.iloc[0]
    years.append({"year": y, **{c: round(float(w[c].iloc[-1] / o[c] - 1) * 100, 2)
                                for c in full.columns}})
report["years"] = years

# ---- rolling 12-month returns ---------------------------------------------
roll = {}
for c in full.columns:
    r = (full[c] / full[c].shift(252) - 1).dropna() * 100
    roll[c] = {"median": round(float(r.median()), 2),
               "p05": round(float(r.quantile(0.05)), 2),
               "p95": round(float(r.quantile(0.95)), 2),
               "worst": round(float(r.min()), 2),
               "best": round(float(r.max()), 2),
               "pct_positive": round(float((r > 0).mean()) * 100, 1),
               "hist": np.histogram(r, bins=np.arange(-70, 131, 10))[0].tolist()}
report["rolling12m"] = {"bins": list(range(-70, 130, 10)), **roll}

# ---- drawdown, full history ------------------------------------------------
dd = {}
for c in full.columns:
    d = (full[c].cummax() - full[c]) / full[c].cummax() * -100
    dd[c] = [round(float(v), 2) for v in d]
report["drawdown"] = {"t": [d.strftime("%Y-%m-%d") for d in full.index], **dd}

# ---- turnover / how much actually changes each month -----------------------
kept = [r["kept"] for r in log[1:]]
report["turnover"] = {
    "rebalances": len(log),
    "avg_kept": round(float(np.mean(kept)), 2),
    "kept_hist": {k: int(sum(1 for x in kept if x == k)) for k in range(HOLD + 1)},
    "months_unchanged": int(sum(1 for x in kept if x == HOLD)),
}

# ---- how often each name was held ------------------------------------------
held = {}
for r in log:
    for t in r["basket"]:
        held[t] = held.get(t, 0) + 1
report["held"] = dict(sorted(held.items(), key=lambda kv: -kv[1]))
report["log"] = log

json.dump(report, open("/home/user/tv-indicators/stock-momentum/research/timelines.json", "w"))

for w in report["windows"]:
    st = w["stats"]
    print(f'\n{w["label"]:24s} {w["start"]} -> {w["end"]}')
    for c in ("strategy", "all40", "spy"):
        s_ = st[c]
        print(f'   {c:9s} ${s_["final"]:>9,.0f}  {s_["ret_pct"]:>8.1f}%  '
              f'dd {s_["maxdd_pct"]:>5.1f}%  vol {s_["vol_ann_pct"]:>5.1f}%  sharpe {s_["sharpe"]:>5.2f}')
print("\nturnover:", report["turnover"])
print("rolling 12m:", {k: {kk: vv for kk, vv in v.items() if kk != "hist"} for k, v in roll.items()})
