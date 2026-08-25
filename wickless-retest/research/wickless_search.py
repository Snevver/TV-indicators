#!/usr/bin/env python3
"""Search the wickless-retest parameter space, pooled across instruments.

Same discipline as pooled_search.py, because it is the only thing that stopped
the earlier indicators from fooling us: a configuration must be profitable on
several instruments at once, in BOTH a training slice and a separate validation
slice, before it is scored — once — on a test slice it has never touched.

Objective is pooled R per year, with a floor on trade frequency.
"""
from __future__ import annotations

import argparse
import os
import random
from dataclasses import asdict
from multiprocessing import Pool

from backtest import load_csv, evaluate
from engine_wickless import WConfig, simulate_wickless
from search_yield import bars_per_year

SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "SPX500", "NAS100"]

SPACE = {
    "wick_tol":      [0.0, 0.0, 0.02, 0.05],
    "min_body":      [0.0, 0.0, 0.3, 0.5, 0.7],
    "trend_len":     [20, 50, 100, 200],
    "trend_mode":    ["ema", "ema", "off"],
    "expiry":        [10, 20, 50, 100, 200],
    "min_move_atr":  [0.25, 0.5, 1.0, 2.0, 3.0],
    "one_level":     [False, True],
    "atr_len":       [14, 20],
    "sl_lookback":   [3, 5, 10, 20],
    "sl_buffer_atr": [0.2, 0.5, 1.0, 2.0],
    "min_stop_atr":  [0.0, 0.5, 1.0, 2.0],
    "rr":            [1.0, 1.0, 1.5, 2.0],
}
DIRECTIONS = [(True, True), (True, False), (False, True)]

_DATA = _A = None


def _init(data, args):
    global _DATA, _A
    _DATA, _A = data, args


def _sample(rng):
    kw = {k: rng.choice(v) for k, v in SPACE.items()}
    longs, shorts = rng.choice(DIRECTIONS)
    return WConfig(longs=longs, shorts=shorts, **kw)


def _score(cfg, slice_name):
    total_r = 0.0
    total_trades = wins = hits = 0
    total_years = 0.0
    per = []
    for sym in SYMBOLS:
        bars = _DATA[sym][slice_name]
        tr = simulate_wickless(bars, cfg, _A.fee_bps, _A.slippage_bps)
        st = evaluate(tr, bars, 0.01)
        if st.trades == 0:
            per.append(0.0)
            continue
        total_r += st.total_r
        total_trades += st.trades
        wins += st.wins
        total_years += len(bars) / _DATA[sym]["bpy"]
        hits += int(st.expectancy > 0)
        per.append(st.expectancy)
    if total_trades == 0 or total_years == 0:
        return None
    span = total_years / len(SYMBOLS)
    return {"r_per_year": total_r / span, "trades_per_year": total_trades / span,
            "expectancy": total_r / total_trades, "win": 100.0 * wins / total_trades,
            "hits": hits, "per": per}


def _trial(seed):
    rng = random.Random(seed)
    cfg = _sample(rng)
    tr = _score(cfg, "train")
    if tr is None or tr["hits"] < _A.min_hit or tr["expectancy"] <= 0:
        return None
    if tr["trades_per_year"] < _A.min_per_year:
        return None
    va = _score(cfg, "val")
    if va is None or va["hits"] < _A.min_hit or va["expectancy"] <= 0:
        return None
    if va["trades_per_year"] < _A.min_per_year:
        return None
    return (asdict(cfg), va["r_per_year"], va)


def describe(c: dict) -> str:
    bits = [f"wick<={c['wick_tol']:g}"]
    if c["min_body"]:
        bits.append(f"body>={c['min_body']:g}")
    bits.append(f"trend={c['trend_mode']}{c['trend_len'] if c['trend_mode']!='off' else ''}")
    bits.append(f"expiry{c['expiry']} move{c['min_move_atr']:g}ATR")
    bits.append(f"SL:swing{c['sl_lookback']}+{c['sl_buffer_atr']:g}ATR"
                + (f" floor{c['min_stop_atr']:g}" if c["min_stop_atr"] else ""))
    bits.append(f"rr{c['rr']:g}")
    bits.append(("long" if c["longs"] else "") + ("+short" if c["shorts"] else "-only"))
    if c["one_level"]:
        bits.append("one-level")
    return " ".join(bits)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tf", default="m15")
    p.add_argument("--n", type=int, default=1500)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--min-per-year", type=float, default=50.0)
    p.add_argument("--min-hit", type=int, default=4)
    p.add_argument("--fee-bps", type=float, default=1.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--symbols", default="", help="comma-separated override")
    args = p.parse_args()

    global SYMBOLS
    if args.symbols:
        SYMBOLS = [s.strip() for s in args.symbols.split(",")]

    data = {}
    print(f"\n  Loading {len(SYMBOLS)} instruments at {args.tf}...")
    for sym in SYMBOLS:
        bars = load_csv(f"data/{sym}_{args.tf}.csv")
        n = len(bars)
        a, b = int(n * 0.55), int(n * 0.78)
        data[sym] = {"train": bars[:a], "val": bars[a:b], "test": bars[b:],
                     "bpy": bars_per_year(bars)}
    print(f"  Requiring {args.min_hit}/{len(SYMBOLS)} profitable, "
          f">= {args.min_per_year:g} trades/yr, costs "
          f"{2*(args.fee_bps+args.slippage_bps):.0f}bps round trip.")
    print(f"  Searching {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(data, args)) as pool:
        res = [r for r in pool.imap_unordered(_trial, range(args.seed, args.seed + args.n),
                                              chunksize=4) if r]
    if not res:
        print("  NOTHING passed train AND validate on "
              f"{args.min_hit}+/{len(SYMBOLS)} instruments.")
        print("  No version of this rule set generalised. That is the result.")
        return 1

    res.sort(key=lambda r: r[1], reverse=True)
    print(f"  {len(res)} configs cleared train AND validate.\n")
    print(f"  {'VAL R/yr':>9} {'VAL hit':>8} {'VAL win':>8} | {'TEST hit':>9} "
          f"{'TEST/yr':>8} {'TEST win':>9} {'TEST exp':>9} {'TEST R/yr':>10}")
    print("  " + "-" * 84)

    _init(data, args)
    kept = []
    for cfg_d, v_r, va in res[:args.top]:
        te = _score(WConfig(**cfg_d), "test")
        if te is None:
            continue
        print(f"  {v_r:>+9.2f} {va['hits']:>7}/{len(SYMBOLS)} {va['win']:>7.1f}% | "
              f"{te['hits']:>8}/{len(SYMBOLS)} {te['trades_per_year']:>8.1f} "
              f"{te['win']:>8.1f}% {te['expectancy']:>+9.3f} {te['r_per_year']:>+10.2f}")
        kept.append((cfg_d, te))

    if kept:
        pos = sum(1 for _c, t in kept if t["r_per_year"] > 0)
        print("  " + "-" * 84)
        print(f"  {pos}/{len(kept)} finalists profitable on TEST, mean pooled R/year "
              f"{sum(t['r_per_year'] for _c, t in kept)/len(kept):+.2f}")
        best = max(kept, key=lambda k: k[1]["r_per_year"])
        c, t = best
        print(f"\n  BEST: {t['trades_per_year']:.0f} trades/yr basket "
              f"({t['trades_per_year']/52:.1f}/week), {t['win']:.1f}% win, "
              f"{t['expectancy']:+.3f}R, {t['hits']}/{len(SYMBOLS)} positive")
        print(f"  {describe(c)}")
        for sym, e in zip(SYMBOLS, t["per"]):
            print(f"    {sym:<8} {e:>+8.4f}R")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
