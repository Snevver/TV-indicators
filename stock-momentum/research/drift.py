"""Does it matter whether you re-equalise all eight every month, or only trade
the names that changed?

Two ways to run the same signal:
  FULL  - every month, total the account and reset all eight to value/8.
  DRIFT - only sell the leavers and buy the arrivals with the proceeds. The names
          that stayed are left alone, so winners grow into a bigger slice.

Also counts how much of the basket is actually buyable in whole shares at a
given account size.
"""
import json, numpy as np, pandas as pd
D="/home/user/tv-indicators/_data-export/data"
U=["AAPL","GOOGL","AMZN","GOOG","MSFT","BAC","XOM","JPM","INTC","NFLX","C","CSCO","WFC","GE","PFE","JNJ","CVX","T","QCOM","GS","WMT","PG","IBM","ORCL","VZ","DIS","HD","MRK","BA","BKNG","MU","CMCSA","KO","MCD","CAT","SLB","COP","AMGN","UNH","NVDA"]
LOOKBACK,SKIP,HOLD,COST_BPS,BASE=126,21,8,10.0,1000.0
s=pd.read_csv(f"{D}/sp500_daily.csv.gz",usecols=["time","ticker","close"]); s["time"]=pd.to_datetime(s["time"])
px=s[s.ticker.isin(U)].pivot(index="time",columns="ticker",values="close").sort_index()
idx=px.index
anch=pd.Series(np.arange(len(idx)),index=idx).groupby([idx.year,idx.month]).first().to_numpy()
anch=[int(a) for a in anch if a>=LOOKBACK+SKIP+1]; end_i=len(idx)-1
def mom(a):
    past,recent=px.iloc[a-LOOKBACK-SKIP],px.iloc[a-SKIP]
    ok=past.notna()&recent.notna()&px.iloc[a].notna()&(past>0)
    return ((recent/past-1.0)[ok]).sort_values(ascending=False)

def run(mode):
    shares,curve,val={}, [], BASE
    for k,a in enumerate(anch):
        top=list(mom(a).index[:HOLD]); p=px.iloc[a]
        if not shares:
            val*= (1-COST_BPS/10_000); shares={t:(val/HOLD)/p[t] for t in top}
        elif mode=="full":
            val=sum(n*p[t] for t,n in shares.items())
            turn=len(set(top)^set(shares))/(len(top)+len(shares))
            val*=(1-turn*COST_BPS/10_000); shares={t:(val/HOLD)/p[t] for t in top}
        else:  # drift: keep survivors untouched, split leavers' cash over arrivals
            leave=[t for t in shares if t not in top]; arrive=[t for t in top if t not in shares]
            cash=sum(shares[t]*p[t] for t in leave)
            cash*=(1-COST_BPS/10_000*2)     # a sell and a buy on the traded money
            for t in leave: del shares[t]
            if arrive:
                for t in arrive: shares[t]=(cash/len(arrive))/p[t]
            elif cash: pass
        nxt=anch[k+1] if k+1<len(anch) else end_i+1
        for i in range(a,min(nxt,end_i+1)):
            curve.append((idx[i],sum(n*px.iloc[i][t] for t,n in shares.items())))
    return pd.Series(dict(curve))

def stats(c):
    r=c.pct_change().dropna(); dd=(c.cummax()-c)/c.cummax()
    yrs=(c.index[-1]-c.index[0]).days/365.25
    return dict(final=round(float(c.iloc[-1]),0),cagr=round((float(c.iloc[-1]/c.iloc[0])**(1/yrs)-1)*100,2),
                dd=round(float(dd.max())*100,1),vol=round(float(r.std()*np.sqrt(252))*100,1))
f,d=run("full"),run("drift")
print("FULL  re-equalise all eight :",stats(f))
print("DRIFT trade only the changes:",stats(d))
for lbl,c in (("full",f),("drift",d)):
    for y0,y1 in ((2007,2009),(2020,2020),(2022,2022),(2026,2026)):
        w=c[(c.index.year>=y0)&(c.index.year<=y1)]
        print(f"   {lbl:5s} {y0}-{y1}: {float(w.iloc[-1]/w.iloc[0]-1)*100:+6.1f}%")

# ---- whole-share reality check --------------------------------------------
print("\nWHOLE SHARES: what fits in an equal slice, at the last rebalance")
a=anch[-1]; top=list(mom(a).index[:HOLD]); p=px.iloc[a]
for acct in (1000,2500,5000,10000):
    slice_=acct/HOLD
    rows=[(t,float(p[t]),int(slice_//p[t])) for t in top]
    unb=[t for t,pr,n in rows if n==0]
    dev=np.mean([abs(n*pr-slice_)/slice_ for t,pr,n in rows if n>0])*100
    print(f"  ${acct:>6,}  slice ${slice_:>7,.0f}  unbuyable {len(unb)}/8 {unb}  avg weight error {dev:.1f}%")
print("\n  prices in that basket:", {t: round(float(p[t]),2) for t in top})
json.dump({"full":stats(f),"drift":stats(d)},open("drift.json","w"))
