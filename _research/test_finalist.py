#!/usr/bin/env python3
"""Score the chosen strategy on the untouched era. One look.

Reports the placebo-corrected edge, and what the strategy would have done to a
real account: compounding, one position per name, a cap on simultaneous
positions, and a fixed fraction of equity risked per trade.
"""
from __future__ import annotations

import argparse
import json

import numpy as np

import lab
import sim
import strategies
import validate
from finalists import placebo_scores


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="sp500")
    p.add_argument("--finalist", default="finalist.json")
    p.add_argument("--placebos", type=int, default=200)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--caps", default="3,5,8,12")
    args = p.parse_args()

    series = lab.load(args.universe)
    with open(args.finalist) as fh:
        c = json.load(fh)
    ex = sim.Exit(**c["exit"])
    dirn = c["dir"]
    masks = {tk: strategies.signal(s, c["cfg"]) for tk, s in series.items()}

    rng = np.random.default_rng(99)
    offsets = [int(x) for x in rng.integers(300, 5000, size=args.placebos)]

    print(f"\n  {json.dumps(c['cfg'])}")
    print(f"  exit {json.dumps(c['exit'])}  dir {dirn}\n")
    print(f"  {'era':<6} {'n':>7} {'real R':>8} {'random R':>9} {'EDGE':>8} "
          f"{'z':>6} {'p':>7}")
    print("  " + "-" * 56)
    for era, label in (("tr", "TRAIN"), ("va", "VAL"), ("te", "TEST")):
        r = placebo_scores(series, masks, ex, dirn, era, offsets, args.cost_bps)
        if r is None:
            print(f"  {label:<6} (insufficient)")
            continue
        null = r["null"][np.isfinite(r["null"])]
        z = (r["edge"] - null.mean()) / null.std(ddof=1) if null.std(ddof=1) > 0 else 0
        pv = (1 + np.sum(null >= r["edge"])) / (1 + len(null))
        print(f"  {label:<6} {r['n']:>7} {r['real']:>+8.3f} {r['rand']:>+9.3f} "
              f"{r['edge']:>+8.3f} {z:>+6.2f} {pv:>6.1%}")

    # ---- what it does to an account, on the test era only ----
    print(f"\n  ACCOUNT SIMULATION — TEST era only, {args.risk_pct:g}% risked per trade")
    print("  " + "-" * 66)
    trades = []
    te_years = None
    for tk, s in series.items():
        te = lab.era_masks(s)[2]
        if te.sum() < 50:
            continue
        if te_years is None:
            te_years = te.sum() / 252
        for t in sim.simulate(s, masks[tk] & te, ex, args.cost_bps, dirn):
            trades.append(t)
    if not trades:
        print("  no trades in the test era")
        return 1
    trades.sort(key=lambda t: t.i_in)

    r = np.array([t.r for t in trades])
    print(f"  {len(trades)} trades over {te_years:.1f} years "
          f"({len(trades)/te_years/52:.1f} per week), "
          f"{100*np.mean(r>0):.1f}% win, mean {r.mean():+.3f}R, "
          f"median {np.median(r):+.3f}R")
    print(f"  {'cap':>5} {'taken':>7} {'/wk':>6} {'win%':>7} {'$1000→':>10} "
          f"{'CAGR':>8} {'maxDD':>8}")
    for cap in [int(x) for x in args.caps.split(",")]:
        e = sim.equity(trades, args.risk_pct, cap)
        cagr = (e["end"] / 1000.0) ** (1 / te_years) - 1
        print(f"  {cap:>5} {e['taken']:>7} {e['taken']/te_years/52:>6.1f} "
              f"{e['win']:>6.1f}% {e['end']:>10,.0f} {cagr*100:>+7.1f}% "
              f"{e['dd']:>7.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
