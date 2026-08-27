"""Where the strategy stands on the best data available.

Combines the Yahoo export with the Kaggle delisted extract, then runs the
strategy two ways: over the forty names the bot actually trades, and over
whichever companies were genuinely in the index that month.

The gap between those two lines is the part of the backtest that came from
knowing the answer in advance -- about two points a year, and seventeen points
of drawdown.

Every figure it prints is a floor, not an estimate. 2008 is the thinnest
stretch of the data (see coverage.py) and the names missing from it are the
ones that failed, so the crisis still looks kinder here than it was.

    python3 honest.py
"""
import numpy as np, pandas as pd, sys
sys.path.insert(0, "/home/user/tv-indicators/stock-momentum/web")
import simulate

D = "_data-export/data"
a = pd.read_csv(f"{D}/sp500_daily.csv.gz")
b = pd.read_csv(f"{D}/kaggle_delisted_2005_2017.csv.gz")
both = pd.concat([a, b], ignore_index=True).drop_duplicates(["time","ticker"], keep="first")
both["time"] = pd.to_datetime(both["time"])
print(f"combined: {both.ticker.nunique()} tickers "
      f"({a.ticker.nunique()} yahoo + {b.ticker.nunique()} kaggle)")

px = both.pivot(index="time", columns="ticker", values="close").sort_index()
LB, SK, HOLD, FEE = simulate.LOOKBACK, simulate.SKIP, simulate.HOLD, simulate.COST_BPS/1e4
idx = px.index; cols = list(px.columns); col_of = {c:i for i,c in enumerate(cols)}
V = px.to_numpy(float)
# WHAT HAPPENS WHEN A HOLDING STOPS EXISTING
#
# The old data could not answer this, because nothing in it ever delisted. Now
# that companies leave, a held name's price series simply ends and the account
# value becomes NaN.
#
# Vff carries the last known price forward, so a position that delists is valued
# flat at its final print and sold at the next rebalance. Ranking still uses the
# real matrix, so a delisted name cannot be bought.
#
# That is generous to bankruptcies -- in reality the recovery is usually nil --
# but a delisted-for-bankruptcy stock has typically already collapsed before it
# goes, so the loss is mostly captured on the way down. It is about right for
# acquisitions, which is the more common exit. The data cannot tell the two
# apart, so this errs toward the kinder reading and the result is a floor.
Vff = pd.DataFrame(V).ffill().to_numpy()
anchors = [int(x) for x in (pd.Series(np.arange(len(idx)), index=idx)
           .groupby([idx.year, idx.month]).first().to_numpy()) if x >= LB+SK+1]

mem = pd.read_csv(f"{D}/sp500_membership.csv.gz"); mem["date"] = pd.to_datetime(mem["date"])
mem["ym"] = mem.date.dt.to_period("M")
by_month = {}
for ym, row in zip(mem.ym, mem.tickers):
    ids = [col_of[t.strip()] for t in str(row).split(",") if t.strip() in col_of]
    by_month[ym] = np.array(sorted(set(ids)))

# coverage
print("\ncoverage of the real index")
for y in (2007, 2010, 2013, 2016, 2019, 2022, 2026):
    snap = mem[mem.date.dt.year == y]
    if snap.empty: continue
    want = {t.strip() for t in str(snap.tickers.iloc[0]).split(",") if t.strip()}
    got = set(both[both.time.dt.year == y].ticker.unique())
    p = len(want & got)/len(want)*100
    print(f"  {y}  {len(want&got):>3}/{len(want):<4} {p:>5.0f}%  " + "#"*int(p/5))

def run(pick, label):
    shares, value, curve = {}, 1000.0, []
    for k, a_ in enumerate(anchors):
        sub = pick(idx[a_])
        if sub is None or len(sub) < HOLD: continue
        p = V[a_, sub]; past, recent = V[a_-LB-SK, sub], V[a_-SK, sub]
        ok = np.isfinite(past)&np.isfinite(recent)&np.isfinite(p)&(past>0)
        if ok.sum() < HOLD: continue
        mom = np.where(ok, recent/np.where(past==0,np.nan,past)-1, -np.inf)
        top = {int(sub[j]) for j in np.argsort(-mom)[:HOLD]}
        if not shares:
            value *= (1-FEE); per = value/HOLD
            shares = {j: per/V[a_,j] for j in top}
        else:
            value = sum(n*Vff[a_,j] for j,n in shares.items())
            leaving=[j for j in shares if j not in top]; arriving=[j for j in top if j not in shares]
            cash = sum(shares[j]*Vff[a_,j] for j in leaving)
            value -= cash*(2 if arriving else 1)*FEE; cash -= cash*FEE
            for j in leaving: del shares[j]
            if arriving:
                each = cash/len(arriving)
                for j in arriving: shares[j] = each/V[a_,j]
        nxt = anchors[k+1] if k+1 < len(anchors) else len(idx)-1
        held_at_anchor = sum(n*Vff[a_,j] for j,n in shares.items())
        for i in range(a_, min(nxt, len(idx)-1)+1):
            curve.append(sum(n*Vff[i,j] for j,n in shares.items())
                         + (value - held_at_anchor))
    v = np.array(curve,float); peak = np.maximum.accumulate(v)
    yrs = (idx[-1]-idx[anchors[0]]).days/365.25
    print(f"  {label:<30} ${v[-1]:>9,.0f}  {(v[-1]/1000)**(1/yrs)-1:>6.1%}/yr  "
          f"worst {float(((peak-v)/peak).max()*100):>5.1f}%")

print("\nthe strategy")
FORTY = np.array(sorted(col_of[t] for t in simulate.UNIVERSE if t in col_of))
run(lambda t: FORTY, "the 40 the bot trades")
run(lambda t: by_month.get(pd.Period(t,'M')), "point-in-time membership")
