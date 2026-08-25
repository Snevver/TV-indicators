#!/usr/bin/env python3
"""Map the trade-off between risk:reward and win rate.

Win rate is not a free parameter. At a fixed target and stop, price must travel
`tp` ATRs before it travels `sl` ATRs, and that path-dependency sets a ceiling on
how often you can win regardless of how good the entry is. This script finds, for
each R:R, the best out-of-sample win rate that still comes with a positive
expectancy — so the two numbers can be read against each other honestly.
"""
from __future__ import annotations

import argparse
import os
import random
from dataclasses import asdict
from multiprocessing import Pool

from backtest import load_csv, simulate, evaluate
from engine import Settings
from engine_v3 import Config, generate
import search as S


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--n", type=int, default=1200)
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--min-trades", type=int, default=40)
    p.add_argument("--min-oos-trades", type=int, default=20)
    p.add_argument("--fee-bps", type=float, default=2.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--target-win", type=float, default=60.0)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    bars = load_csv(args.csv)
    print(f"\n  {args.csv}: {len(bars)} bars ({bars[0].t} → {bars[-1].t})")
    print(f"  {args.n} configs searched per R:R level, out-of-sample scored.\n")
    print(f"  {'R:R':>7} {'break-even':>11} | {'best OOS win%':>14} {'its exp':>9} "
          f"{'trades':>7} | {'best OOS exp':>13} {'its win%':>9} {'n≥target':>9}")
    print("  " + "-" * 92)

    for sl, tp in [(1.0, 0.5), (1.0, 0.75), (1.0, 1.0), (1.0, 1.5),
                   (1.0, 2.0), (1.0, 3.0)]:
        args.tp, args.sl = tp, sl
        with Pool(args.jobs, initializer=S._init, initargs=(bars, args)) as pool:
            res = [r for r in pool.imap_unordered(
                S._trial, range(args.seed, args.seed + args.n), chunksize=16) if r]

        oos_pos = [r for r in res if r[2]["exp"] > 0]
        be = 100.0 * sl / (tp + sl)
        if not oos_pos:
            print(f"  {sl:g}:{tp:<5g} {be:>10.1f}% | {'—':>14}")
            continue

        by_win = max(oos_pos, key=lambda r: r[2]["win"])
        by_exp = max(oos_pos, key=lambda r: r[2]["exp"])
        hit = sum(1 for r in oos_pos if r[2]["win"] >= args.target_win)

        print(f"  {sl:g}:{tp:<5g} {be:>10.1f}% | {by_win[2]['win']:>13.1f}% "
              f"{by_win[2]['exp']:>+9.3f} {by_win[2]['trades']:>7} | "
              f"{by_exp[2]['exp']:>+13.3f} {by_exp[2]['win']:>8.1f}% {hit:>9}")

    print("\n  'n≥target' counts configs reaching the win-rate target out-of-sample")
    print("  WITH positive expectancy. A high win rate at a low R:R is easy and often")
    print("  worthless; the two columns must be read together.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
