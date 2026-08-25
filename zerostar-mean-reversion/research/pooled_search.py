#!/usr/bin/env python3
"""Search for one rule set that works across EIGHT instruments at once.

Every single-instrument search so far produced the same pattern: a config passes
train and validate, then fails on test. That is what fitting one price series
looks like. Requiring the same parameters to profit on eight unrelated markets —
US large cap, US tech, US small cap, gold, Japanese equity, two FX pairs and oil —
makes that far harder. Noise does not line up eight ways at once.

Selection rules, all applied on data the final report never sees:
  TRAIN     >= --min-hit of 8 instruments profitable, pooled frequency above floor
  VALIDATE  same requirement, ranked by pooled R per year
  TEST      the finalists are scored once, and consistency there is the result

Pooled R/year is the objective, because that is what compounds: +0.05R eighty
times a year beats +0.40R three times a year.
"""
from __future__ import annotations

import argparse
import os
import random
from dataclasses import asdict
from datetime import datetime
from multiprocessing import Pool

from backtest import load_csv, simulate, evaluate
from engine import Settings
from engine_v3 import Config, generate
import search as S
from search_yield import SESSIONS, bars_per_year, describe

# Default basket. The equity-index subset is the economically motivated one: the
# daily study found the edge to be index-specific BEFORE any intraday run, and the
# first pooled intraday search reproduced the same split independently (indices and
# gold positive, FX and oil negative). Restricting to indices is therefore a
# standing hypothesis being tested, not a post-hoc pick.
ALL_SYMBOLS = ["SPX500", "NAS100", "US2000", "XAUUSD", "JP225", "EURUSD", "GBPUSD", "WTI"]
INDEX_SYMBOLS = ["SPX500", "NAS100", "US2000", "JP225", "XAUUSD"]
SYMBOLS = list(ALL_SYMBOLS)

_DATA = _A = None


def _init(data, args):
    global _DATA, _A
    _DATA, _A = data, args


def _sample(rng):
    kw = {k: rng.choice(v) for k, v in S.SPACE.items()}
    hf, ht = rng.choice(SESSIONS)
    kw["hour_from"], kw["hour_to"] = hf, ht
    kw["skip_monday"] = rng.random() < 0.15
    longs, shorts = rng.choice(S.DIRECTIONS)
    kw["rsi_sell"] = 100.0 - kw["rsi_buy"]
    kw["z_sell"] = -kw["z_buy"]
    slm = rng.choice(_A.stop_choices)
    rr = rng.choice(_A.rr_choices)
    return Config(longs=longs, shorts=shorts, sl=slm, tp=slm * rr, **kw)


def _score(cfg, slice_name):
    """Run one config over every instrument's slice. Returns pooled numbers."""
    total_r = 0.0
    total_trades = 0
    total_years = 0.0
    hits = 0
    wins = 0
    per = []
    s = Settings(tp_mult=cfg.tp, sl_mult=cfg.sl, atr_length=cfg.atr_len)
    for sym in SYMBOLS:
        bars, bpy = _DATA[sym][slice_name], _DATA[sym]["bpy"]
        sigs = generate(bars, cfg)
        if not sigs:
            per.append(0.0)
            continue
        st = evaluate(simulate(bars, sigs, s, _A.fee_bps, _A.slippage_bps, "open", 0),
                      bars, 0.01)
        if st.trades == 0:
            per.append(0.0)
            continue
        total_r += st.total_r
        total_trades += st.trades
        total_years += len(bars) / bpy
        wins += st.wins
        hits += int(st.expectancy > 0)
        per.append(st.expectancy)
    if total_trades == 0 or total_years == 0:
        return None
    mean_span = total_years / len(SYMBOLS)      # average years covered per instrument
    return {"r_per_year": total_r / mean_span,           # basket total, per year
            "trades_per_year": total_trades / mean_span,  # basket total, per year
            "expectancy": total_r / total_trades,
            "win": 100.0 * wins / total_trades,
            "hits": hits, "trades": total_trades, "per": per}


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
    return (asdict(cfg), va["r_per_year"], va, tr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tf", default="m15", choices=["m5", "m15"])
    p.add_argument("--n", type=int, default=1200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--min-per-year", type=float, default=50.0,
                   help="pooled trades per year per instrument")
    p.add_argument("--min-hit", type=int, default=6, help="of 8 instruments profitable")
    p.add_argument("--fee-bps", type=float, default=1.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--stops", default="4,8,12,16,24,32")
    p.add_argument("--rr", default="1.0,1.5,2.0")
    p.add_argument("--top", type=int, default=6)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--min-trades", type=int, default=20)
    p.add_argument("--min-oos-trades", type=int, default=10)
    p.add_argument("--train-frac", type=float, default=0.55)
    p.add_argument("--rank-by", choices=["yield", "win"], default="yield",
                   help="'win' maximises win rate subject to positive expectancy")
    p.add_argument("--symbols", default="all",
                   help="'all', 'indices', or a comma-separated list")
    args = p.parse_args()

    global SYMBOLS
    if args.symbols == "indices":
        SYMBOLS = list(INDEX_SYMBOLS)
    elif args.symbols != "all":
        SYMBOLS = [s.strip() for s in args.symbols.split(",")]
    args.stop_choices = [float(x) for x in args.stops.split(",")]
    args.rr_choices = [float(x) for x in args.rr.split(",")]

    data = {}
    print(f"\n  Loading {len(SYMBOLS)} instruments at {args.tf}...")
    for sym in SYMBOLS:
        bars = load_csv(f"data/{sym}_{args.tf}.csv")
        n = len(bars)
        a, b = int(n * 0.55), int(n * 0.78)
        data[sym] = {"train": bars[:a], "val": bars[a:b], "test": bars[b:],
                     "bpy": bars_per_year(bars)}
    any_sym = data[SYMBOLS[0]]
    print(f"  TRAIN {any_sym['train'][0].t} → {any_sym['train'][-1].t}")
    print(f"  VAL   {any_sym['val'][0].t} → {any_sym['val'][-1].t}")
    print(f"  TEST  {any_sym['test'][0].t} → {any_sym['test'][-1].t}  (scored once)")
    print(f"\n  Requiring {args.min_hit}/8 instruments profitable, "
          f">= {args.min_per_year:g} trades/yr each.")
    print(f"  Costs {2*(args.fee_bps+args.slippage_bps):.0f}bps round trip. "
          f"Searching {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(data, args)) as pool:
        res = [r for r in pool.imap_unordered(_trial, range(args.seed, args.seed + args.n),
                                              chunksize=4) if r]
    if not res:
        print("  Nothing passed train AND validate on 6+ of 8 instruments.")
        print("  That is itself a result: no rule in this family generalises.")
        return 1

    # Ranking by win rate is only meaningful among configs that actually make
    # money; a high win rate at a poor payoff is a slow loss.
    if args.rank_by == "win":
        res.sort(key=lambda r: r[2]["win"], reverse=True)
    else:
        res.sort(key=lambda r: r[1], reverse=True)
    print(f"  {len(res)} configs cleared train AND validate on {args.min_hit}+/8.\n")
    print(f"  {'VAL R/yr':>9} {'VAL hit':>8} {'VAL win':>8} | {'TEST hit':>9} "
          f"{'TEST/yr':>8} {'TEST win':>9} {'TEST exp':>9} {'TEST R/yr':>10}")
    print("  " + "-" * 84)

    _init(data, args)
    kept = []
    for cfg_d, v_r, va, _tr in res[:args.top]:
        cfg = Config(**cfg_d)
        te = _score(cfg, "test")
        if te is None:
            continue
        print(f"  {v_r:>+9.2f} {va['hits']:>7}/{len(SYMBOLS)} {va['win']:>7.1f}% | {te['hits']:>8}/{len(SYMBOLS)} "
              f"{te['trades_per_year']:>8.1f} {te['win']:>8.1f}% {te['expectancy']:>+9.3f} "
              f"{te['r_per_year']:>+10.2f}")
        kept.append((cfg_d, te))

    if kept:
        print("  " + "-" * 84)
        pos = sum(1 for _c, t in kept if t["r_per_year"] > 0)
        print(f"  {pos}/{len(kept)} finalists profitable on TEST, mean pooled R/year "
              f"{sum(t['r_per_year'] for _c, t in kept)/len(kept):+.2f}")
        best = max(kept, key=lambda k: k[1]["r_per_year"])
        c, t = best
        print(f"\n  BEST: {t['trades_per_year']:.0f} trades/yr across the basket "
              f"({t['trades_per_year']/52:.1f}/week, "
              f"{t['trades_per_year']/len(SYMBOLS):.0f}/yr per instrument), "
              f"{t['win']:.1f}% win, {t['expectancy']:+.3f}R, "
              f"{t['r_per_year']:+.1f}R/yr, {t['hits']}/{len(SYMBOLS)} instruments positive")
        print(f"  {describe(c)}")
        print("\n  Per-instrument expectancy on TEST:")
        for sym, e in zip(SYMBOLS, t["per"]):
            print(f"    {sym:<8} {e:>+8.4f}R")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
