#!/usr/bin/env python3
"""Cross-sectional stock momentum — the textbook version, on 500 names.

The ETF work may have failed for a dull reason: 28 assets is a tiny cross
section. The canonical momentum result (Jegadeesh & Titman) is a stock-level
effect measured across thousands of names, where dispersion between winners and
losers is far wider than between sector ETFs.

The benchmark here is deliberately NOT the S&P 500 index. It is the EQUAL-WEIGHT
return of this same 500-name universe. That matters: the universe is today's
index membership, so it is survivorship-biased, and comparing a momentum
portfolio drawn from it against the index would credit momentum with the
survivorship. Both arms drawn from the same biased universe cancels it — what is
left is whether ranking beats not ranking.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import lab
from rotation2 import panel
from longshort import anchors


def backtest(px, lookback, top_frac, cost_bps=10.0, skip=21, lo=None, hi=None,
             short_side=False, month_start=True):
    idx = px.index
    me = anchors(idx, month_start)
    eq = peak = 1.0
    dd = 0.0
    held: list[str] = []
    curve, bench = [], []

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
        if len(mom) < 50:
            continue
        k = max(1, int(len(mom) * top_frac))
        ranked = mom.sort_values(ascending=False)
        L = list(ranked.index[:k])

        fwd = (nxt / now - 1.0)
        bench.append(float(np.mean(fwd[ok].to_numpy())))   # equal-weight universe

        turn = len(set(L) ^ set(held)) / max(len(L) + len(held), 1)
        eq *= (1.0 - turn * cost_bps / 10_000.0)
        held = L
        r = float(np.mean(fwd[L].to_numpy()))
        if short_side:
            S = list(ranked.index[-k:])
            r -= float(np.mean(fwd[S].to_numpy()))
        eq *= (1.0 + r)
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        curve.append((idx[b], eq))
        if eq <= 0:
            return None

    if not curve:
        return None
    yrs = (curve[-1][0] - curve[0][0]).days / 365.25
    vals = np.array([c[1] for c in curve])
    mret = np.diff(vals) / vals[:-1]
    bn = np.array(bench)
    bench_cagr = float(np.prod(1 + bn) ** (12 / len(bn)) - 1) if len(bn) else 0.0
    bv = np.cumprod(1 + bn); bp = np.maximum.accumulate(bv)
    return {"cagr": eq ** (1 / yrs) - 1 if yrs > 0 else 0.0, "dd": dd * 100,
            "sharpe": mret.mean() / mret.std(ddof=1) * np.sqrt(12)
                      if len(mret) > 1 and mret.std(ddof=1) > 0 else 0.0,
            "bench_cagr": bench_cagr, "bench_dd": float(((bp - bv) / bp).max() * 100),
            "bench_sharpe": bn.mean() / bn.std(ddof=1) * np.sqrt(12)
                            if len(bn) > 1 and bn.std(ddof=1) > 0 else 0.0,
            "names": len(held), "years": yrs}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=10.0)
    args = p.parse_args()
    px = panel(lab.load("sp500"))
    print(f"\n  {px.shape[1]} stocks, {px.index[0].date()} → {px.index[-1].date()}")
    tr_end, va_end = pd.Timestamp(lab.TRAIN_END), pd.Timestamp(lab.VAL_END)
    print(f"  Benchmark = EQUAL-WEIGHT of the same universe, so survivorship")
    print(f"  bias sits in both arms and cancels.\n")

    for name, lo, hi in (("TRAIN", None, tr_end), ("VAL", tr_end, va_end),
                         ("TEST", va_end, None)):
        print(f"  === {name}")
        print(f"  {'look':>5} {'top':>6} {'L/S':>5} {'CAGR':>8} {'maxDD':>7} "
              f"{'SR':>6} | {'bench':>7} {'bDD':>6} {'bSR':>6} | {'edge':>7}")
        for lb in (126, 252):
            for tf in (0.02, 0.05, 0.10, 0.20):
                for ss in (False, True):
                    r = backtest(px, lb, tf, args.cost_bps, 21, lo, hi, ss)
                    if r is None:
                        continue
                    print(f"  {lb:>5} {tf:>6.0%} {str(ss):>5} {r['cagr']*100:>7.1f}% "
                          f"{r['dd']:>6.1f}% {r['sharpe']:>6.2f} | "
                          f"{r['bench_cagr']*100:>6.1f}% {r['bench_dd']:>5.1f}% "
                          f"{r['bench_sharpe']:>6.2f} | "
                          f"{(r['cagr']-r['bench_cagr'])*100:>6.1f}%")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
