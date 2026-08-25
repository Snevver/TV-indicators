"""YTD 2026 equity curves, EUR 3,000 start. Daily marks, not monthly points.

Reproduces the figures on the year-to-date chart: the rotation against holding
January's basket, holding all forty, and the index. Run it against the exported
daily data in _data-export/data.

Rebalances at the CLOSE of the first trading day of each month, which is what
stockmom.py measures. Between rebalances the share counts are fixed, so the
curve moves with prices rather than being interpolated.
"""
import json
import numpy as np
import pandas as pd

D = "/home/user/tv-indicators/_data-export/data"
U = ["AAPL","GOOGL","AMZN","GOOG","MSFT","BAC","XOM","JPM","INTC","NFLX","C","CSCO",
     "WFC","GE","PFE","JNJ","CVX","T","QCOM","GS","WMT","PG","IBM","ORCL","VZ","DIS",
     "HD","MRK","BA","BKNG","MU","CMCSA","KO","MCD","CAT","SLB","COP","AMGN","UNH","NVDA"]
LOOKBACK, SKIP, HOLD, COST_BPS, START = 126, 21, 8, 10.0, 3000.0

s = pd.read_csv(f"{D}/sp500_daily.csv.gz", usecols=["time","ticker","close"])
s["time"] = pd.to_datetime(s["time"])
px = s[s.ticker.isin(U)].pivot(index="time", columns="ticker", values="close").sort_index()

e = pd.read_csv(f"{D}/etfs_daily.csv.gz", usecols=["time","ticker","close"])
e["time"] = pd.to_datetime(e["time"])
spy = e[e.ticker == "SPY"].set_index("time")["close"].sort_index().reindex(px.index).ffill()

idx = px.index
anch = pd.Series(np.arange(len(idx)), index=idx).groupby([idx.year, idx.month]).first().to_numpy()
ytd = [a for a in anch if idx[a].year == 2026]
start_i, end_i = ytd[0], len(idx) - 1
print("YTD window:", idx[start_i].date(), "->", idx[end_i].date())
print("rebalance dates:", [str(idx[a].date()) for a in ytd])

def momentum(a):
    past, recent = px.iloc[a - LOOKBACK - SKIP], px.iloc[a - SKIP]
    ok = past.notna() & recent.notna() & px.iloc[a].notna() & (past > 0)
    return ((recent / past - 1.0)[ok]).sort_values(ascending=False)

# ---- strategy: rebalance monthly ------------------------------------------
cash, shares, curve, log = START, {}, [], []
for k, a in enumerate(ytd):
    top = list(momentum(a).index[:HOLD])
    prices = px.iloc[a]
    value = cash if not shares else sum(n * prices[t] for t, n in shares.items())
    turn = len(set(top) ^ set(shares)) / max(len(top) + len(shares), 1)
    value *= (1.0 - turn * COST_BPS / 10_000.0)
    shares = {t: (value / HOLD) / prices[t] for t in top}
    log.append({"date": str(idx[a].date()), "basket": top,
                "value": round(value, 2), "turnover": round(turn, 3)})
    nxt = ytd[k + 1] if k + 1 < len(ytd) else end_i + 1
    for i in range(a, min(nxt, end_i + 1)):
        curve.append((idx[i], sum(n * px.iloc[i][t] for t, n in shares.items())))

strat = pd.Series(dict(curve))

# ---- three buy-and-holds ---------------------------------------------------
def hold(tickers, i0):
    p0 = px.iloc[i0]
    n = {t: (START / len(tickers)) / p0[t] for t in tickers}
    return pd.Series({idx[i]: sum(k * px.iloc[i][t] for t, k in n.items())
                      for i in range(i0, end_i + 1)})

jan_basket = log[0]["basket"]
janhold = hold(jan_basket, start_i)
all40 = hold([t for t in U if not np.isnan(px.iloc[start_i][t])], start_i)
spyc = spy.iloc[start_i:end_i + 1] / spy.iloc[start_i] * START

out = pd.DataFrame({"strategy": strat, "jan_hold": janhold,
                    "all40": all40, "spy": spyc}).dropna()

def stats(c):
    r = c.pct_change().dropna()
    peak = c.cummax()
    return {"final": round(float(c.iloc[-1]), 2),
            "ret_pct": round(float(c.iloc[-1] / c.iloc[0] - 1) * 100, 2),
            "maxdd_pct": round(float(((peak - c) / peak).max()) * 100, 2),
            "vol_ann_pct": round(float(r.std() * np.sqrt(252)) * 100, 2),
            "best_day_pct": round(float(r.max()) * 100, 2),
            "worst_day_pct": round(float(r.min()) * 100, 2)}

res = {k: stats(out[k]) for k in out.columns}
print(json.dumps(res, indent=1))
print("\njan basket:", jan_basket)
for r in log:
    print(r["date"], f'{r["value"]:>8.0f}', "turn", r["turnover"], r["basket"])

out.round(2).to_csv("ytd_curves.csv")
json.dump({"stats": res, "log": log, "start": str(out.index[0].date()),
           "end": str(out.index[-1].date())},
          open("ytd_stats.json", "w"), indent=1)
