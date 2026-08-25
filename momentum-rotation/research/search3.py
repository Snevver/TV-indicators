#!/usr/bin/env python3
"""Search on capital-constrained account return. The objective that survives.

Two corrections over the earlier searches, both forced by measurement:

  1. OBJECTIVE. Mean R per signal is unreachable with finite capital. The
     previous finalist scored +0.138R per signal and -0.787R through a 3-slot
     book, because winners held a slot 4.1x longer than losers so the book
     filled with losers. Everything here is scored as the CAGR of an actual
     capped, compounding account, minus the CAGR of random entries run through
     the SAME capped account.

  2. BOUNDED HOLDS. Exits that can run forever destroy slot turnover, so every
     exit sampled here has either a fixed target or a time stop.

Same-day signals are RANKED, not taken first-come: when more names qualify than
there are slots, the strongest signal wins the slot.
"""
from __future__ import annotations

import argparse
import json
import os
from multiprocessing import Pool

import numpy as np

import lab
import sim
import strategies
import validate
from account import run_account

_S = _A = None


def _init(series, args):
    global _S, _A
    _S, _A = series, args


SPACE = {
    "family": ["dip_rsi", "dip_rsi", "dip_z", "downrun", "breakout", "mom", "ma_cross"],
    "rsi_len": [2, 2, 3, 4, 14],
    "rsi_thr": [2, 5, 10, 15, 20, 30],
    "z_thr": [-1.0, -1.5, -2.0, -2.5, -3.0],
    "run_len": [3, 4, 5, 6],
    "bo_win": [20, 50, 100, 252],
    "mom_thr": [0.0, 0.05, 0.10, 0.20],
    "ma_fast": [5, 10, 20, 50],
    "ma_slow": [50, 100, 200],
    "trend": ["none", "above", "above", "below"],
    "trend_len": [50, 100, 200],
    "volfil": ["none", "none", "low", "high"],
    "vol_thr": [0.3, 0.5, 0.7],
    "gap_bars": [0, 3, 5, 10],
}
# Bounded exits only. Anything that can hold indefinitely wrecks slot turnover.
EX_SPACE = {
    "stop_atr": [1.0, 1.5, 2.0, 3.0],
    "target_r": [1.0, 1.5, 2.0, 3.0],
    "trail_atr": [0.0, 0.0, 2.0, 3.0],
    "trail_after_r": [0.0, 1.0],
    "breakeven_r": [0.0, 0.0, 0.5, 1.0],
    "time_bars": [3, 5, 10, 15, 20, 30],
}
DIRS = [1, 1, 1, -1]

# The value used to rank competing same-day signals, per family. Lower is
# stronger for dips; higher is stronger for momentum.
RANK_KEY = {"dip_rsi": ("rsi", 1), "dip_z": ("z20", 1), "downrun": ("downrun", -1),
            "breakout": ("mom12_1", -1), "mom": ("mom12_1", -1),
            "ma_cross": ("mom12_1", -1)}


def sample(rng):
    cfg = {k: rng.choice(v) for k, v in SPACE.items()}
    if cfg["family"] == "ma_cross":
        cfg["ma_slow"] = max(cfg["ma_slow"], cfg["ma_fast"] * 2)
        cfg["ma_cross_only"] = True
    ex = sim.Exit(**{k: rng.choice(v) for k, v in EX_SPACE.items()})
    return cfg, ex, int(rng.choice(DIRS))


def gather(cfg, ex, dirn, era, rand_rng=None):
    """Trades with real dates plus a rank score for same-day contention."""
    key, sign = RANK_KEY.get(cfg["family"], ("z20", 1))
    out = []
    for tk, s in _S.items():
        km = lab.era_masks(s)[{"tr": 0, "va": 1, "te": 2}[era]]
        m = strategies.signal(s, cfg) & km
        k = int(m.sum())
        if k == 0:
            continue
        use = m
        if rand_rng is not None:
            use = validate.random_mask(len(s), k, rand_rng) & km
        arr = s.ind.get(key)
        for t in sim.simulate(s, use, ex, _A.cost_bps, dirn):
            i = t.i_in - 1
            score = float(arr[i]) * sign if arr is not None and np.isfinite(arr[i]) else 0.0
            out.append((s.t[t.i_in], s.t[t.i_out], t.r, score))
    return out


def ranked_account(trades, cap, risk_pct):
    """Same-day contention resolved by signal strength, then run the account."""
    if not trades:
        return None
    # Rank within each entry date: strongest first.
    by_date = {}
    for tr in trades:
        by_date.setdefault(tr[0], []).append(tr)
    ordered = []
    for dt in sorted(by_date):
        for tr in sorted(by_date[dt], key=lambda x: x[3]):
            ordered.append((tr[0], tr[1], tr[2]))
    return run_account(ordered, cap, risk_pct)


def _trial(seed):
    rng = np.random.default_rng(seed)
    cfg, ex, dirn = sample(rng)
    try:
        tr = gather(cfg, ex, dirn, "tr")
    except (KeyError, ValueError):
        return None
    if len(tr) < _A.min_trades:
        return None
    a = ranked_account(tr, _A.cap, _A.risk_pct)
    if a is None or a["ruined"] or a["taken"] < 60:
        return None
    b = ranked_account(gather(cfg, ex, dirn, "tr", rng), _A.cap, _A.risk_pct)
    if b is None:
        return None
    d_tr = a["cagr"] - b["cagr"]
    if d_tr <= _A.min_diff or a["cagr"] <= 0:
        return None

    va = gather(cfg, ex, dirn, "va")
    if len(va) < _A.min_trades // 3:
        return None
    a2 = ranked_account(va, _A.cap, _A.risk_pct)
    b2 = ranked_account(gather(cfg, ex, dirn, "va", rng), _A.cap, _A.risk_pct)
    if a2 is None or b2 is None or a2["ruined"]:
        return None
    d_va = a2["cagr"] - b2["cagr"]
    if d_va <= 0 or a2["cagr"] <= 0:
        return None

    plain = lambda o: {k: (v.item() if hasattr(v, "item") else v) for k, v in o.items()}
    return (plain(cfg), plain(ex.__dict__), dirn,
            {"cagr": a["cagr"], "dd": a["dd"], "taken": a["taken"],
             "win": a["win"], "diff": d_tr},
            {"cagr": a2["cagr"], "dd": a2["dd"], "taken": a2["taken"],
             "win": a2["win"], "diff": d_va})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="etfs")
    p.add_argument("--n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=500000)
    p.add_argument("--cap", type=int, default=5)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--min-trades", type=int, default=150)
    p.add_argument("--min-diff", type=float, default=0.02)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--out", default="cand3.json")
    args = p.parse_args()

    series = lab.load(args.universe)
    print(f"\n  {args.universe}: {len(series)} tickers   cap {args.cap} positions   "
          f"{args.risk_pct:g}% risk/trade   {args.cost_bps*2:g}bps round trip")
    print(f"  Objective: capped-account CAGR minus RANDOM-ENTRY capped CAGR")
    print(f"  Exits are bounded (target or time stop) so slots turn over")
    print(f"  Sampling {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(series, args)) as pool:
        res = [r for r in pool.imap_unordered(_trial,
               range(args.seed, args.seed + args.n), chunksize=8) if r]

    print(f"  {len(res)} beat a random capped book in BOTH train and val "
          f"({100.0*len(res)/args.n:.1f}%)\n")
    if not res:
        print("  Nothing cleared it.")
        return 1
    res.sort(key=lambda r: min(r[3]["diff"], r[4]["diff"]), reverse=True)
    print(f"  {'family':<10} {'dir':>4} {'TR cagr':>8} {'TR dif':>7} "
          f"{'VA cagr':>8} {'VA dif':>7} {'VA dd':>6} {'VA n':>6}")
    print("  " + "-" * 64)
    for cfg, exd, dirn, a, b in res[:args.top]:
        print(f"  {cfg['family']:<10} {'L' if dirn==1 else 'S':>4} "
              f"{a['cagr']*100:>7.1f}% {a['diff']*100:>6.1f}% "
              f"{b['cagr']*100:>7.1f}% {b['diff']*100:>6.1f}% "
              f"{b['dd']:>5.1f}% {b['taken']:>6}")
    with open(args.out, "w") as fh:
        json.dump([{"cfg": c, "exit": e, "dir": d, "train": t, "val": v}
                   for c, e, d, t, v in res[:150]], fh, indent=1)
    print(f"\n  wrote {min(len(res),150)} to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
