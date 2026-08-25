#!/usr/bin/env python3
"""Search for ANNUAL R, not per-trade expectancy, on intraday bars.

Every earlier search ranked by expectancy per trade, which quietly favours rare,
picky rules: +0.41R three times a year is +1.2R annually, while +0.08R fifty times
a year is +4.0R. The second is better and the old ranking buried it.

Two things make intraday viable and both are searched here:

  WIDE STOPS   the stop is N x ATR. On 15-minute bars a 1xATR stop is ~0.09% of
               price, so an 8bp round trip eats 93% of what you risk. At 12xATR
               the same toll is under 8%. Entry frequency comes from bar count;
               cost drag comes from stop size. They are separate knobs.

  FREQUENCY FLOOR  configs trading less than --min-per-year are discarded before
               they can win on expectancy alone.

Three-way split: search on TRAIN, rank on VALIDATE, report TEST once.
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

_B = _A = None


def bars_per_year(bars) -> float:
    def parse(s):
        for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, f)
            except ValueError:
                continue
        return None
    a, b = parse(bars[0].t), parse(bars[-1].t)
    if not a or not b:
        return 252.0
    yrs = (b - a).days / 365.25
    return len(bars) / yrs if yrs > 0 else 252.0


def _init(bars, args):
    global _B, _A
    _B, _A = bars, args
    S._BARS, S._ARGS = bars, args


# Windows worth trying, in the timestamps the data carries. The hour-by-hour
# autocorrelation scan showed mean reversion concentrated in the US cash session
# and the hours around the European close, so those get their own entries.
SESSIONS = [
    (0, 24), (0, 24),          # no filter, weighted so it stays a real contender
    (13, 20), (13, 17), (16, 20), (13, 16), (16, 19), (18, 21),
    (6, 12), (7, 13), (9, 14), (10, 14), (20, 24),
]


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


def _stats(chunk, cfg, args):
    sigs = generate(chunk, cfg)
    if not sigs:
        return None
    s = Settings(tp_mult=cfg.tp, sl_mult=cfg.sl, atr_length=cfg.atr_len)
    return evaluate(simulate(chunk, sigs, s, args.fee_bps, args.slippage_bps, "open", 0),
                    chunk, 0.01)


def _trial(seed: int):
    rng = random.Random(seed)
    cfg = _sample(rng)
    n = len(_B)
    a, b = int(n * 0.55), int(n * 0.78)
    train, val = _B[:a], _B[a:b]
    bpy = _A.bpy

    tr = _stats(train, cfg, _A)
    if tr is None or tr.trades == 0:
        return None
    tr_yr = tr.trades / (len(train) / bpy)
    if tr_yr < _A.min_per_year or tr.expectancy <= 0:
        return None

    v = _stats(val, cfg, _A)
    if v is None or v.trades == 0:
        return None
    v_yr = v.trades / (len(val) / bpy)
    if v_yr < _A.min_per_year or v.expectancy <= 0:
        return None

    return (asdict(cfg), v.expectancy * v_yr, v_yr, v.win_rate, v.expectancy)


def describe(c: dict) -> str:
    bits = [f"RSI({c['rsi_len']})<={c['rsi_buy']:g}" if c["use_rsi"] else "no-RSI"]
    if c["use_z"]:
        bits.append(f"z{c['z_len']}<={c['z_buy']:g}")
    if c["down_days"]:
        bits.append(f"{c['down_days']}down")
    if c["stability"]:
        bits.append(f"stab{c['stability']:g}")
    bits.append(f"{c['regime']}(EMA{c['trend_len']})" if c["regime"] != "none" else "no-regime")
    bits.append(("long" if c["longs"] else "") + ("+short" if c["shorts"] else "-only"))
    bits.append(f"stop{c['sl']:g}xATR{c['atr_len']} tp{c['tp']/c['sl']:.1f}R gap{c['gap']}")
    if c.get("hour_from", 0) != 0 or c.get("hour_to", 24) != 24:
        bits.append(f"hours{c['hour_from']}-{c['hour_to']}")
    if c.get("skip_monday"):
        bits.append("no-Mon")
    return " ".join(bits)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--min-per-year", type=float, default=50.0)
    p.add_argument("--fee-bps", type=float, default=1.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--stops", default="4,8,12,16,24,32")
    p.add_argument("--rr", default="2.0")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--min-trades", type=int, default=20)
    p.add_argument("--min-oos-trades", type=int, default=10)
    p.add_argument("--train-frac", type=float, default=0.55)
    args = p.parse_args()

    args.stop_choices = [float(x) for x in args.stops.split(",")]
    args.rr_choices = [float(x) for x in args.rr.split(",")]

    bars = load_csv(args.csv)
    args.bpy = bars_per_year(bars)
    n = len(bars)
    a, b = int(n * 0.55), int(n * 0.78)
    test = bars[b:]

    print(f"\n  {args.csv}: {n} bars, ~{args.bpy:,.0f}/year "
          f"({bars[0].t} → {bars[-1].t})")
    print(f"  Costs {args.fee_bps:g}+{args.slippage_bps:g} bps/side "
          f"= {2*(args.fee_bps+args.slippage_bps):.0f}bps round trip")
    print(f"  Stops {args.stop_choices} x ATR, R:R {args.rr_choices}")
    print(f"  Floor {args.min_per_year:g} trades/year. Searching {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(bars, args)) as pool:
        res = [r for r in pool.imap_unordered(_trial, range(args.seed, args.seed + args.n),
                                              chunksize=8) if r]
    if not res:
        print("  Nothing cleared the frequency floor while staying profitable.")
        return 1

    res.sort(key=lambda r: r[1], reverse=True)
    print(f"  {len(res)} configs profitable in train AND validate at "
          f">= {args.min_per_year:g} trades/yr.\n")
    print(f"  {'VAL R/yr':>9} {'VAL/yr':>7} {'VAL win':>8} | {'TEST/yr':>8} "
          f"{'TEST win':>9} {'TEST exp':>9} {'TEST R/yr':>10} {'TEST PF':>8}")
    print("  " + "-" * 82)

    test_years = len(test) / args.bpy
    kept = []
    for cfg_d, v_r, v_yr, v_win, _v_exp in res[:args.top]:
        cfg = Config(**cfg_d)
        st = _stats(test, cfg, args)
        if st is None or st.trades == 0:
            continue
        t_yr = st.trades / test_years
        print(f"  {v_r:>+9.2f} {v_yr:>7.1f} {v_win:>7.1f}% | {t_yr:>8.1f} "
              f"{st.win_rate:>8.1f}% {st.expectancy:>+9.3f} "
              f"{st.expectancy*t_yr:>+10.2f} {st.profit_factor:>8.2f}")
        kept.append((cfg_d, st.expectancy * t_yr, st, t_yr))

    if kept:
        pos = sum(1 for k in kept if k[1] > 0)
        print("  " + "-" * 82)
        print(f"  {pos}/{len(kept)} finalists still profitable on TEST. "
              f"Mean TEST R/year {sum(k[1] for k in kept)/len(kept):+.2f}")
        best = max(kept, key=lambda k: k[1])
        print(f"\n  BEST ON TEST → {best[3]:.0f} trades/yr ({best[3]/52:.1f}/week), "
              f"{best[2].win_rate:.1f}% win, {best[2].expectancy:+.3f}R, "
              f"{best[1]:+.1f}R/yr, maxDD {best[2].max_dd:.1f}%")
        print(f"  {describe(best[0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
