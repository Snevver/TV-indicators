#!/usr/bin/env python3
"""Monthly momentum rotation. A different shape of strategy entirely.

Everything searched so far is signal-triggered: a rule fires, a position opens,
an exit closes it. That structure created the capacity problem — winners hogged
slots while losers churned through them.

Rotation has no such problem. On the last trading day of each month, rank the
universe, hold the top N equal-weight, and hold them until the next rebalance.
Slot turnover is fixed by the calendar. Capacity is exactly N by construction.

The thesis (cross-sectional momentum) is one of the most replicated findings in
asset pricing, which matters: it was not invented by this search, so it carries
almost no multiple-testing burden.

The absolute-momentum switch is Faber's: if the asset is below its own long
moving average, hold cash instead. It converts a relative-strength rotation into
one that can step aside in a bear market.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import lab


def month_ends(dates: np.ndarray) -> np.ndarray:
    s = pd.Series(np.arange(len(dates)), index=pd.to_datetime(dates))
    return s.groupby([s.index.year, s.index.month]).last().to_numpy()


def backtest(series: dict, lookback: int, hold_n: int, cost_bps: float,
             abs_filter: bool, ma_len: int, skip: int, start_i=None, end_i=None):
    tickers = sorted(series)
    ref = series[tickers[0]]
    dates = ref.t
    me = month_ends(dates)

    eq = 1.0
    peak = 1.0
    dd = 0.0
    held: list[str] = []
    curve = []
    trades = 0

    for a, b in zip(me[:-1], me[1:]):
        if start_i is not None and a < start_i:
            continue
        if end_i is not None and b > end_i:
            break
        if a < lookback + skip + 5:
            continue

        # Rank on data available AT the rebalance close.
        scores = []
        for tk in tickers:
            s = series[tk]
            if b >= len(s) or a >= len(s):
                continue
            if a - lookback - skip < 0:
                continue
            past = s.c[a - lookback - skip]
            recent = s.c[a - skip]
            if not np.isfinite(past) or past <= 0:
                continue
            mom = recent / past - 1.0
            if abs_filter:
                ma = s.ind.get(f"sma{ma_len}")
                if ma is None or not np.isfinite(ma[a]) or s.c[a] <= ma[a]:
                    continue           # below its own trend -> not eligible
            scores.append((mom, tk))
        scores.sort(reverse=True)
        pick = [tk for _m, tk in scores[:hold_n]]

        # Cost only on the names that actually changed.
        turn = len(set(pick) ^ set(held)) / max(len(pick) + len(held), 1)
        eq *= (1.0 - turn * cost_bps / 10_000.0)
        trades += len(set(pick) - set(held))
        held = pick

        if pick:
            rets = []
            for tk in pick:
                s = series[tk]
                if b < len(s):
                    rets.append(s.c[b] / s.c[a] - 1.0)
            if rets:
                eq *= (1.0 + float(np.mean(rets)))
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        curve.append((dates[b], eq))

    if not curve:
        return None
    yrs = (pd.Timestamp(curve[-1][0]) - pd.Timestamp(curve[0][0])).days / 365.25
    rets = np.array([c[1] for c in curve])
    mret = np.diff(rets) / rets[:-1] if len(rets) > 1 else np.array([0.0])
    return {"eq": eq, "cagr": eq ** (1 / yrs) - 1 if yrs > 0 else 0.0,
            "dd": dd * 100, "years": yrs, "months": len(curve), "trades": trades,
            "sharpe": mret.mean() / mret.std(ddof=1) * np.sqrt(12)
                      if len(mret) > 1 and mret.std(ddof=1) > 0 else 0.0}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=10.0)
    args = p.parse_args()
    series = lab.load("etfs")
    ref = series["SPY"]
    tr_end = int(np.searchsorted(ref.t, np.datetime64(lab.TRAIN_END)))
    va_end = int(np.searchsorted(ref.t, np.datetime64(lab.VAL_END)))

    print(f"\n  Monthly rotation over {len(series)} ETFs, {args.cost_bps:g}bps turnover cost")
    print(f"  Benchmark: SPY buy & hold\n")
    for name, lo, hi in (("TRAIN", None, tr_end), ("VAL", tr_end, va_end),
                         ("TEST", va_end, None)):
        a = lo if lo is not None else 0
        b = hi if hi is not None else len(ref) - 1
        bh = ref.c[b] / ref.c[a]
        yrs = (pd.Timestamp(ref.t[b]) - pd.Timestamp(ref.t[a])).days / 365.25
        print(f"  === {name}  ({str(ref.t[a])[:10]} → {str(ref.t[b])[:10]}, {yrs:.1f}y)"
              f"   SPY {bh**(1/yrs)-1:+.1%}/yr")
        print(f"  {'look':>5} {'hold':>5} {'absF':>5} {'CAGR':>8} {'maxDD':>7} "
              f"{'sharpe':>7} {'trades':>7}")
        for lb in (63, 126, 252):
            for hn in (1, 3, 5):
                for af in (False, True):
                    r = backtest(series, lb, hn, args.cost_bps, af, 200, 21, lo, hi)
                    if r is None:
                        continue
                    print(f"  {lb:>5} {hn:>5} {str(af):>5} {r['cagr']*100:>7.1f}% "
                          f"{r['dd']:>6.1f}% {r['sharpe']:>7.2f} {r['trades']:>7}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
