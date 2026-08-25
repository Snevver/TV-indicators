#!/usr/bin/env python3
"""Long/short cross-sectional momentum. Market-neutral by construction.

The long-only rotation matched the index and did not beat it. But its ranking
does carry information: it beat a random monthly pick by roughly 3 points a year.
In a long-only book that signal is buried under market beta — you are ~100% long
equities, so the index dominates whatever the ranking contributes.

Going long the strongest N and short the weakest N cancels the beta and leaves
the ranking. If cross-sectional momentum is real, this is where it shows up
cleanly. If it is not, this will show that too, with nowhere to hide: a
market-neutral book cannot be rescued by a rising market.

Costs charged on both legs. Short borrow is charged separately, because shorting
is not free and pretending otherwise is how paper strategies beat real ones.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import lab
from rotation2 import panel


def anchors(idx, month_start=True):
    g = pd.Series(np.arange(len(idx)), index=idx).groupby([idx.year, idx.month])
    return (g.first() if month_start else g.last()).to_numpy()


def backtest(px, lookback, n_side, cost_bps=10.0, borrow_bps_yr=50.0, skip=21,
             lo=None, hi=None, short_weight=1.0, month_start=True):
    idx = px.index
    me = anchors(idx, month_start)
    eq = peak = 1.0
    dd = 0.0
    longs: list[str] = []
    shorts: list[str] = []
    curve = []

    for a, b in zip(me[:-1], me[1:]):
        if lo is not None and idx[a] < lo:
            continue
        if hi is not None and idx[b] > hi:
            break
        if a - lookback - skip < 0:
            continue
        past, recent = px.iloc[a - lookback - skip], px.iloc[a - skip]
        now, nxt = px.iloc[a], px.iloc[b]
        ok = past.notna() & recent.notna() & now.notna() & nxt.notna() & (past > 0)
        mom = (recent / past - 1.0)[ok]
        if len(mom) < 2 * n_side + 2:
            continue
        ranked = mom.sort_values(ascending=False)
        L = list(ranked.index[:n_side])
        S = list(ranked.index[-n_side:])

        turn = (len(set(L) ^ set(longs)) + len(set(S) ^ set(shorts))) / \
               max(len(L) + len(longs) + len(S) + len(shorts), 1)
        eq *= (1.0 - turn * cost_bps / 10_000.0)
        longs, shorts = L, S

        rl = float(np.mean((nxt[L] / now[L] - 1.0).to_numpy()))
        rs = float(np.mean((nxt[S] / now[S] - 1.0).to_numpy()))
        days = (idx[b] - idx[a]).days
        borrow = short_weight * borrow_bps_yr / 10_000.0 * days / 365.25
        eq *= (1.0 + rl - short_weight * rs - borrow)

        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        curve.append((idx[b], eq))

    if not curve or eq <= 0:
        return None
    yrs = (curve[-1][0] - curve[0][0]).days / 365.25
    vals = np.array([c[1] for c in curve])
    mret = np.diff(vals) / vals[:-1]
    return {"eq": eq, "cagr": eq ** (1 / yrs) - 1 if yrs > 0 else 0.0,
            "dd": dd * 100, "years": yrs, "months": len(curve),
            "sharpe": mret.mean() / mret.std(ddof=1) * np.sqrt(12)
                      if len(mret) > 1 and mret.std(ddof=1) > 0 else 0.0,
            "rets": mret, "dates": [c[0] for c in curve]}


def spy_monthly(px, lo, hi, month_start=True):
    idx = px.index
    me = anchors(idx, month_start)
    s = px["SPY"]
    out = []
    for a, b in zip(me[:-1], me[1:]):
        if lo is not None and idx[a] < lo:
            continue
        if hi is not None and idx[b] > hi:
            break
        if np.isfinite(s.iloc[a]) and np.isfinite(s.iloc[b]):
            out.append(s.iloc[b] / s.iloc[a] - 1.0)
    return np.array(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=10.0)
    p.add_argument("--borrow-bps", type=float, default=50.0)
    args = p.parse_args()
    px = panel(lab.load("etfs"))
    tr_end, va_end = pd.Timestamp(lab.TRAIN_END), pd.Timestamp(lab.VAL_END)

    print(f"\n  LONG/SHORT MOMENTUM — market neutral, monthly")
    print(f"  {args.cost_bps:g}bps turnover, {args.borrow_bps:g}bps/yr short borrow\n")
    for name, lo, hi in (("TRAIN", None, tr_end), ("VAL", tr_end, va_end),
                         ("TEST", va_end, None)):
        sp = spy_monthly(px, lo, hi)
        yrs = len(sp) / 12
        print(f"  === {name}   SPY {(np.prod(1+sp))**(1/yrs)-1:+.1%}/yr")
        print(f"  {'look':>5} {'n/side':>7} {'CAGR':>8} {'maxDD':>7} {'sharpe':>7} "
              f"{'corr SPY':>9}")
        for lb in (63, 126, 168, 252):
            for ns in (2, 3, 5):
                r = backtest(px, lb, ns, args.cost_bps, args.borrow_bps, 21, lo, hi)
                if r is None:
                    continue
                m = min(len(r["rets"]), len(sp))
                c = np.corrcoef(r["rets"][:m], sp[:m])[0, 1] if m > 3 else float("nan")
                print(f"  {lb:>5} {ns:>7} {r['cagr']*100:>7.1f}% {r['dd']:>6.1f}% "
                      f"{r['sharpe']:>7.2f} {c:>9.2f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
