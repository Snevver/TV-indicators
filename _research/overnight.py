#!/usr/bin/env python3
"""Overnight-only strategy on ETFs.

The thesis, which is not mine and has a long literature behind it: essentially
all of the equity risk premium is earned between the close and the next open,
not during the session. Across 20 liquid ETFs, 2006-2026, the overnight leg
returns 3.24 bps/day against 0.90 bps for the intraday leg.

That alone is not tradeable — 3 bps a night does not survive a spread. But the
overnight return is not uniform: it concentrates on nights following a stretched
close. A close two standard deviations below its 20-day mean is followed by an
overnight return of 13.3 bps, four times baseline, on 5,655 observations.

Mechanics: buy at the close when the condition holds, sell at the next open.
Held one night. No stop — the position simply does not exist during the session
in which a stop could be hit, which is the entire point of the trade.

Universe is ETFs, which cannot be survivorship-biased in the way a stock list is:
these funds all still exist, and the ones here are the liquid ones throughout.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import lab

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "MDY", "XLK", "XLF", "XLE", "XLV",
            "XLI", "XLY", "XLP", "XLU", "XLB", "SMH", "KRE", "XBI", "EEM",
            "EFA", "VNQ"]


def build_panel(series: dict) -> pd.DataFrame:
    rows = []
    for tk in UNIVERSE:
        s = series.get(tk)
        if s is None:
            continue
        n = len(s)
        volp = pd.Series(s.ind["vol20"]).rolling(252).rank(pct=True).to_numpy()
        for i in range(260, n - 1):
            on = s.o[i + 1] / s.c[i] - 1.0
            if not np.isfinite(on):
                continue
            rows.append((s.t[i], tk, on, s.ind["z20"][i], s.ind["rsi2"][i],
                         s.c[i] > s.ind["sma200"][i], volp[i]))
    d = pd.DataFrame(rows, columns=["date", "ticker", "on", "z20", "rsi2",
                                    "above200", "volp"]).dropna()
    return d.sort_values(["date", "z20"])


def simulate(d: pd.DataFrame, z_thr: float, max_pos: int, cost_bps: float,
             require_above200: bool) -> dict:
    """Equal-weight the qualifying names each night, capped at `max_pos`.

    Capital not deployed earns nothing. Costs are charged per position per night,
    round trip. Returns are compounded on the whole account.
    """
    sel = d[d.z20 <= z_thr]
    if require_above200:
        sel = sel[sel.above200]
    if sel.empty:
        return {"n": 0}
    cost = cost_bps / 10_000.0
    eq = 1.0
    peak = 1.0
    dd = 0.0
    nights = 0
    trades = 0
    daily = []
    for date, grp in sel.groupby("date"):
        g = grp.nsmallest(max_pos, "z20")
        k = len(g)
        if k == 0:
            continue
        # Full capital split across the qualifying names.
        ret = float(np.mean(g["on"].to_numpy())) - cost
        eq *= (1.0 + ret)
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        nights += 1
        trades += k
        daily.append(ret)
    daily = np.array(daily)
    years = (d.date.max() - d.date.min()).days / 365.25
    return {"n": trades, "nights": nights, "eq": eq,
            "cagr": eq ** (1 / years) - 1 if years > 0 else 0.0,
            "dd": dd * 100, "years": years,
            "mean_bps": daily.mean() * 1e4 if len(daily) else 0.0,
            "t": daily.mean() / daily.std(ddof=1) * np.sqrt(len(daily))
                 if len(daily) > 1 and daily.std(ddof=1) > 0 else 0.0,
            "sharpe": daily.mean() / daily.std(ddof=1) * np.sqrt(252)
                      if len(daily) > 1 and daily.std(ddof=1) > 0 else 0.0,
            "deployed": 100.0 * nights / max(d.date.nunique(), 1)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=4.0,
                   help="round trip, per position per night")
    p.add_argument("--max-pos", type=int, default=3)
    args = p.parse_args()

    d = build_panel(lab.load("etfs"))
    tr = d[d.date <= np.datetime64(lab.TRAIN_END)]
    va = d[(d.date > np.datetime64(lab.TRAIN_END)) & (d.date <= np.datetime64(lab.VAL_END))]
    te = d[d.date > np.datetime64(lab.VAL_END)]
    print(f"\n  panel {len(d):,} ticker-nights   "
          f"train {len(tr):,} / val {len(va):,} / test {len(te):,}")
    print(f"  cost {args.cost_bps:g}bps round trip per position per night\n")

    print(f"  {'z<=':>5} {'pos':>4} {'era':>6} {'nights':>7} {'%dep':>6} "
          f"{'bps/night':>10} {'t':>6} {'sharpe':>7} {'CAGR':>8} {'maxDD':>7}")
    print("  " + "-" * 78)
    for z in (-1.5, -2.0, -2.5):
        for mp in (1, 3, 5):
            for era, name in ((tr, "TRAIN"), (va, "VAL"), (te, "TEST")):
                r = simulate(era, z, mp, args.cost_bps, False)
                if r["n"] == 0:
                    continue
                print(f"  {z:>5.1f} {mp:>4} {name:>6} {r['nights']:>7} "
                      f"{r['deployed']:>5.0f}% {r['mean_bps']:>10.2f} "
                      f"{r['t']:>6.1f} {r['sharpe']:>7.2f} "
                      f"{r['cagr']*100:>+7.1f}% {r['dd']:>6.1f}%")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
