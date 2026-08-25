#!/usr/bin/env python3
"""Monthly momentum rotation — with correct date alignment.

The first version of this indexed every ETF by SPY's bar number, which is only
valid if all 28 share an identical calendar. They do not: HYG, KRE, SLV, USO,
XBI and XLRE have later inception dates and therefore fewer bars. Bar 2000 was
2012-12-12 for SPY and 2015-03-20 for HYG, so ranking at a 2012 date read 2015
prices for those names. That is look-ahead, not sloppiness, and those six
supplied about a quarter of all holdings.

Here every series is aligned onto one date index first, with NaN where an ETF did
not yet exist, and every lookup is by date. A name is only eligible on a date if
it has real prices covering the whole lookback window ending there.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import lab


def panel(series: dict) -> pd.DataFrame:
    """Close prices, dates x tickers, properly aligned."""
    cols = {tk: pd.Series(s.c, index=pd.to_datetime(s.t)) for tk, s in series.items()}
    return pd.DataFrame(cols).sort_index()


def backtest(px: pd.DataFrame, lookback: int, hold_n: int, cost_bps: float,
             skip: int = 21, start=None, end=None):
    idx = px.index
    me = pd.Series(np.arange(len(idx)), index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()

    eq = peak = 1.0
    dd = 0.0
    held: list[str] = []
    curve = []
    changes = 0

    for a, b in zip(me[:-1], me[1:]):
        if start is not None and idx[a] < start:
            continue
        if end is not None and idx[b] > end:
            break
        if a - lookback - skip < 0:
            continue

        past = px.iloc[a - lookback - skip]
        recent = px.iloc[a - skip]
        now = px.iloc[a]
        nxt = px.iloc[b]
        # Eligible only with real data across the whole window AND at both ends
        # of the holding period. NaN means the fund did not exist yet.
        ok = past.notna() & recent.notna() & now.notna() & nxt.notna() & (past > 0)
        mom = (recent / past - 1.0)[ok]
        if mom.empty:
            continue
        pick = list(mom.nlargest(hold_n).index)

        turn = len(set(pick) ^ set(held)) / max(len(pick) + len(held), 1)
        eq *= (1.0 - turn * cost_bps / 10_000.0)
        changes += len(set(pick) - set(held))
        held = pick

        rets = (nxt[pick] / now[pick] - 1.0).to_numpy()
        eq *= (1.0 + float(np.mean(rets)))
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        curve.append((idx[b], eq))

    if not curve:
        return None
    yrs = (curve[-1][0] - curve[0][0]).days / 365.25
    vals = np.array([c[1] for c in curve])
    mret = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0.0])
    return {"eq": eq, "cagr": eq ** (1 / yrs) - 1 if yrs > 0 else 0.0,
            "dd": dd * 100, "years": yrs, "months": len(curve), "changes": changes,
            "sharpe": mret.mean() / mret.std(ddof=1) * np.sqrt(12)
                      if len(mret) > 1 and mret.std(ddof=1) > 0 else 0.0,
            "curve": curve}


def random_pick(px, hold_n, cost_bps, seed, skip=21, lookback=126, start=None, end=None):
    """Identical mechanics, random monthly selection. The honest baseline."""
    rng = np.random.default_rng(seed)
    idx = px.index
    me = pd.Series(np.arange(len(idx)), index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()
    eq = 1.0
    held = []
    curve = []
    for a, b in zip(me[:-1], me[1:]):
        if start is not None and idx[a] < start:
            continue
        if end is not None and idx[b] > end:
            break
        if a - lookback - skip < 0:
            continue
        now, nxt = px.iloc[a], px.iloc[b]
        elig = list(now[now.notna() & nxt.notna()].index)
        if not elig:
            continue
        pick = list(rng.choice(elig, size=min(hold_n, len(elig)), replace=False))
        turn = len(set(pick) ^ set(held)) / max(len(pick) + len(held), 1)
        eq *= (1.0 - turn * cost_bps / 10_000.0)
        held = pick
        eq *= (1.0 + float(np.mean((nxt[pick] / now[pick] - 1.0).to_numpy())))
        curve.append((idx[b], eq))
    if not curve:
        return 0.0
    yrs = (curve[-1][0] - curve[0][0]).days / 365.25
    return eq ** (1 / yrs) - 1 if yrs > 0 else 0.0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=10.0)
    args = p.parse_args()
    px = panel(lab.load("etfs"))
    tr_end = pd.Timestamp(lab.TRAIN_END)
    va_end = pd.Timestamp(lab.VAL_END)
    spy = px["SPY"]

    print(f"\n  CORRECTED — all {px.shape[1]} ETFs aligned by DATE, "
          f"{args.cost_bps:g}bps turnover cost\n")
    for name, lo, hi in (("TRAIN", None, tr_end), ("VAL", tr_end, va_end),
                         ("TEST", va_end, None)):
        sl = spy.loc[(lo or spy.index[0]):(hi or spy.index[-1])].dropna()
        yrs = (sl.index[-1] - sl.index[0]).days / 365.25
        bh = (sl.iloc[-1] / sl.iloc[0]) ** (1 / yrs) - 1
        print(f"  === {name}  {sl.index[0].date()} → {sl.index[-1].date()}  "
              f"({yrs:.1f}y)   SPY {bh:+.1%}/yr")
        print(f"  {'look':>5} {'hold':>5} {'CAGR':>8} {'maxDD':>7} {'sharpe':>7} "
              f"{'random':>8} {'edge':>7}")
        for lb in (63, 126, 252):
            for hn in (2, 3, 5):
                r = backtest(px, lb, hn, args.cost_bps, 21, lo, hi)
                if r is None:
                    continue
                rnd = np.mean([random_pick(px, hn, args.cost_bps, s, 21, lb, lo, hi)
                               for s in range(12)])
                print(f"  {lb:>5} {hn:>5} {r['cagr']*100:>7.1f}% {r['dd']:>6.1f}% "
                      f"{r['sharpe']:>7.2f} {rnd*100:>7.1f}% "
                      f"{(r['cagr']-rnd)*100:>6.1f}%")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
