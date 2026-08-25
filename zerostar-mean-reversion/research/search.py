#!/usr/bin/env python3
"""Random search over the v3 config space, with walk-forward validation built in.

The search NEVER reports an in-sample number as a result. Every candidate is
optimised on the first `--train-frac` of the bars and scored on the remainder,
which it has not seen. A configuration that only works in-sample is a fit, not an
edge, and this harness is built to make that visible rather than hide it.

  python3 search.py data/SPY_d1.csv --n 4000
  python3 search.py data/SPY_d1.csv --n 4000 --target-win 60
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import asdict, replace
from multiprocessing import Pool
from typing import Optional

from backtest import load_csv, simulate, evaluate
from engine import Settings
from engine_v3 import Config, generate

SPACE = {
    "rsi_len":   [2, 2, 2, 3, 4, 5, 7, 10, 14],
    "rsi_buy":   [2, 3, 5, 8, 10, 15, 20, 25, 30, 35],
    "use_rsi":   [True, True, True, False],
    "use_z":     [False, False, True],
    "z_len":     [10, 20, 50],
    "z_buy":     [-1.0, -1.5, -2.0, -2.5, -3.0],
    "down_days": [0, 0, 0, 2, 3, 4, 5],
    "stability": [0.0, 0.0, 0.3, 0.5],
    "regime":    ["none", "with_trend", "with_trend", "counter_trend"],
    "trend_len": [50, 100, 150, 200, 300],
    "gap":       [1, 1, 3, 5, 10],
    "atr_len":   [10, 14, 20],
}
DIRECTIONS = [(True, False), (False, True), (True, True)]

_BARS = None
_ARGS = None


def sample(rng: random.Random) -> Config:
    kw = {k: rng.choice(v) for k, v in SPACE.items()}
    longs, shorts = rng.choice(DIRECTIONS)
    kw["rsi_sell"] = 100.0 - kw["rsi_buy"]
    kw["z_sell"] = -kw["z_buy"]
    return Config(longs=longs, shorts=shorts, tp=_ARGS.tp, sl=_ARGS.sl, **kw)


def run(bars, cfg: Config, args):
    sigs = generate(bars, cfg)
    if not sigs:
        return None
    s = Settings(tp_mult=cfg.tp, sl_mult=cfg.sl, atr_length=cfg.atr_len)
    tr = simulate(bars, sigs, s, args.fee_bps, args.slippage_bps, "open", 0)
    return evaluate(tr, bars, 0.01)


def _init(bars, args):
    global _BARS, _ARGS
    _BARS, _ARGS = bars, args


def _trial(seed: int):
    rng = random.Random(seed)
    cfg = sample(rng)
    cut = int(len(_BARS) * _ARGS.train_frac)
    train, test = _BARS[:cut], _BARS[cut:]

    is_st = run(train, cfg, _ARGS)
    if is_st is None or is_st.trades < _ARGS.min_trades:
        return None
    # Only spend time out-of-sample on things that worked in-sample.
    if is_st.expectancy <= 0:
        return None
    oos = run(test, cfg, _ARGS)
    if oos is None or oos.trades < _ARGS.min_oos_trades:
        return None
    return (asdict(cfg), _pack(is_st), _pack(oos))


def _pack(st):
    return {"trades": st.trades, "win": st.win_rate, "exp": st.expectancy,
            "pf": st.profit_factor if st.profit_factor != float("inf") else 999.0,
            "t": st.t_stat, "dd": st.max_dd, "total_r": st.total_r}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--train-frac", type=float, default=0.7)
    p.add_argument("--min-trades", type=int, default=40)
    p.add_argument("--min-oos-trades", type=int, default=20)
    p.add_argument("--fee-bps", type=float, default=2.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--tp", type=float, default=2.0)
    p.add_argument("--sl", type=float, default=1.0)
    p.add_argument("--target-win", type=float, default=60.0)
    p.add_argument("--out", default=None)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    args = p.parse_args()

    bars = load_csv(args.csv)
    print(f"  {args.csv}: {len(bars)} bars ({bars[0].t} → {bars[-1].t})")
    print(f"  R:R locked at {args.sl:g}:{args.tp:g}  →  break-even win rate = "
          f"{100.0*args.sl/(args.tp+args.sl):.1f}%")
    print(f"  Searching {args.n} configs on {args.jobs} cores; "
          f"train={args.train_frac:.0%}, rest held out.\n")

    with Pool(args.jobs, initializer=_init, initargs=(bars, args)) as pool:
        results = [r for r in pool.imap_unordered(
            _trial, range(args.seed, args.seed + args.n), chunksize=16) if r]

    if not results:
        print("  Nothing cleared the in-sample filters.")
        return 1

    print(f"  {len(results)} configs were profitable in-sample and had enough "
          f"out-of-sample trades.\n")

    oos_pos = [r for r in results if r[2]["exp"] > 0]
    print(f"  Of those, {len(oos_pos)} ({100.0*len(oos_pos)/len(results):.1f}%) "
          f"stayed profitable out-of-sample.")
    hit = [r for r in oos_pos if r[2]["win"] >= args.target_win]
    print(f"  {len(hit)} reached the {args.target_win:.0f}% win-rate target "
          f"out-of-sample with positive expectancy.\n")

    results.sort(key=lambda r: r[2]["exp"], reverse=True)
    print("  TOP 12 BY OUT-OF-SAMPLE EXPECTANCY")
    print(f"  {'IS trd':>6} {'IS win':>7} {'IS exp':>8} | {'OOS trd':>7} {'OOS win':>8} "
          f"{'OOS exp':>8} {'OOS PF':>7} {'OOS t':>6}")
    print("  " + "-" * 72)
    for _, is_st, oos in results[:12]:
        print(f"  {is_st['trades']:>6} {is_st['win']:>6.1f}% {is_st['exp']:>+8.3f} | "
              f"{oos['trades']:>7} {oos['win']:>7.1f}% {oos['exp']:>+8.3f} "
              f"{oos['pf']:>7.2f} {oos['t']:>+6.2f}")

    best_win = sorted(oos_pos, key=lambda r: r[2]["win"], reverse=True)[:6]
    if best_win:
        print("\n  HIGHEST OUT-OF-SAMPLE WIN RATE (with positive expectancy)")
        print("  " + "-" * 72)
        for cfg, is_st, oos in best_win:
            print(f"  {oos['win']:>5.1f}% win, {oos['exp']:+.3f}R, {oos['trades']} trades  "
                  f"| rsi({cfg['rsi_len']})<={cfg['rsi_buy']:g} "
                  f"regime={cfg['regime']} dir={'L' if cfg['longs'] else ''}"
                  f"{'S' if cfg['shorts'] else ''} dd={cfg['down_days']}")

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results[:50], fh, indent=2)
        print(f"\n  Wrote top 50 to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
