#!/usr/bin/env python3
"""Three-way split, because a two-way split is not enough once you search.

Selecting the best of N out-of-sample results makes that out-of-sample number
optimistic: you have chosen on it, so it is no longer untouched. The fix is a
third slice that is looked at exactly once.

  TRAIN     search here, keep anything profitable
  VALIDATE  rank the survivors here, pick the top K
  TEST      report the chosen K here — looked at once, never selected on

The TEST column is the only number in this repo that is a genuine estimate of
what you would have got.
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

_B = None
_A = None


def _init(bars, args):
    global _B, _A
    _B, _A = bars, args
    S._BARS, S._ARGS = bars, args


def _trial(seed: int):
    rng = random.Random(seed)
    cfg = S.sample(rng)
    n = len(_B)
    a, b = int(n * 0.55), int(n * 0.78)
    train, val = _B[:a], _B[a:b]

    st_tr = S.run(train, cfg, _A)
    if st_tr is None or st_tr.trades < _A.min_trades or st_tr.expectancy <= 0:
        return None
    st_v = S.run(val, cfg, _A)
    if st_v is None or st_v.trades < _A.min_oos_trades or st_v.expectancy <= 0:
        return None
    return (asdict(cfg), S._pack(st_tr), S._pack(st_v))


def _describe(c: dict) -> str:
    bits = []
    bits.append(f"RSI({c['rsi_len']})<={c['rsi_buy']:g}" if c["use_rsi"] else "no-RSI")
    if c["use_z"]:
        bits.append(f"z{c['z_len']}<={c['z_buy']:g}")
    if c["down_days"]:
        bits.append(f"{c['down_days']}down")
    if c["stability"]:
        bits.append(f"stab>={c['stability']:g}")
    bits.append(f"{c['regime']}(EMA{c['trend_len']})" if c["regime"] != "none" else "no-regime")
    bits.append(("long" if c["longs"] else "") + ("+short" if c["shorts"] else "-only"))
    bits.append(f"gap{c['gap']}")
    bits.append(f"ATR{c['atr_len']}")
    return " ".join(bits)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--n", type=int, default=6000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--min-trades", type=int, default=30)
    p.add_argument("--min-oos-trades", type=int, default=15)
    p.add_argument("--fee-bps", type=float, default=2.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--tp", type=float, default=2.0)
    p.add_argument("--sl", type=float, default=1.0)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--rank-by", choices=["exp", "win"], default="exp")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--train-frac", type=float, default=0.55)   # used by search.run
    args = p.parse_args()

    bars = load_csv(args.csv)
    n = len(bars)
    a, b = int(n * 0.55), int(n * 0.78)
    train, val, test = bars[:a], bars[a:b], bars[b:]

    be = 100.0 * args.sl / (args.tp + args.sl)
    print(f"\n  {args.csv}   R:R = {args.sl:g}:{args.tp:g}   break-even win rate {be:.1f}%")
    print(f"  TRAIN    {len(train):>5} bars  {train[0].t} → {train[-1].t}")
    print(f"  VALIDATE {len(val):>5} bars  {val[0].t} → {val[-1].t}")
    print(f"  TEST     {len(test):>5} bars  {test[0].t} → {test[-1].t}   (touched once)")
    print(f"\n  Searching {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(bars, args)) as pool:
        res = [r for r in pool.imap_unordered(
            _trial, range(args.seed, args.seed + args.n), chunksize=16) if r]

    if not res:
        print("  Nothing survived train+validate.")
        return 1
    print(f"  {len(res)} configs were profitable in BOTH train and validate.")

    key = (lambda r: r[2]["exp"]) if args.rank_by == "exp" else (lambda r: r[2]["win"])
    res.sort(key=key, reverse=True)
    chosen = res[:args.top]

    print(f"  Top {len(chosen)} by validate {args.rank_by}, now scored on TEST:\n")
    print(f"  {'TRAIN win':>10} {'TRAIN exp':>10} | {'VAL win':>8} {'VAL exp':>8} | "
          f"{'TEST trd':>9} {'TEST win':>9} {'TEST exp':>9} {'TEST PF':>8}")
    print("  " + "-" * 84)

    test_wins, test_exps = [], []
    for cfg_d, tr_s, v_s in chosen:
        cfg = Config(**cfg_d)
        st = S.run(test, cfg, args)
        if st is None or st.trades == 0:
            print(f"  {tr_s['win']:>9.1f}% {tr_s['exp']:>+10.3f} | {v_s['win']:>7.1f}% "
                  f"{v_s['exp']:>+8.3f} | {'no trades':>9}")
            continue
        test_wins.append(st.win_rate)
        test_exps.append(st.expectancy)
        print(f"  {tr_s['win']:>9.1f}% {tr_s['exp']:>+10.3f} | {v_s['win']:>7.1f}% "
              f"{v_s['exp']:>+8.3f} | {st.trades:>9} {st.win_rate:>8.1f}% "
              f"{st.expectancy:>+9.3f} {st.profit_factor:>8.2f}")
        print(f"       cfg: {_describe(cfg_d)}")

    if test_wins:
        print("  " + "-" * 84)
        print(f"  MEAN ON TEST:  win {sum(test_wins)/len(test_wins):.1f}%   "
              f"expectancy {sum(test_exps)/len(test_exps):+.3f}R")
        print(f"  ({sum(1 for e in test_exps if e > 0)}/{len(test_exps)} still profitable "
              f"on data never used for search or ranking)")

    if chosen:
        c = chosen[0][0]
        print("\n  BEST CONFIG BY VALIDATE:")
        print(f"    RSI({c['rsi_len']}) <= {c['rsi_buy']:g}" if c['use_rsi'] else "    RSI off")
        print(f"    z-score: {'on, ' + str(c['z_len']) + 'bar <= ' + str(c['z_buy']) if c['use_z'] else 'off'}")
        print(f"    consecutive down closes: {c['down_days']}   stability: {c['stability']}")
        print(f"    regime: {c['regime']} (EMA {c['trend_len']})   "
              f"direction: {'long' if c['longs'] else ''}{'+short' if c['shorts'] else ' only'}")
        print(f"    gap: {c['gap']} bars   ATR: {c['atr_len']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
