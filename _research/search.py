#!/usr/bin/env python3
"""Search for an entry+exit that beats RANDOM ENTRIES, not zero.

Three phases, each cheaper to fail than the last:

  1. TRAIN   sample configs, keep those whose edge over random entries is positive
  2. VAL     survivors must repeat it on data they were not sampled against
  3. TEST    the finalists are scored once, with a full placebo null and a
             family-wise correction for how hard we searched

The family-wise step is the one most backtests skip. Searching N configs over
pure noise produces a best-of-N that looks good; comparing the winner to the
distribution of best-of-N placebos is what tells you whether it is more than that.
"""
from __future__ import annotations

import argparse
import json
import os
import random as pyrandom
from multiprocessing import Pool

import numpy as np

import lab
import sim
import strategies
import validate

RAND_DRAWS = 3          # random-entry baselines averaged per config

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
EX_SPACE = {
    "stop_atr": [1.0, 1.5, 2.0, 3.0, 4.0],
    "target_r": [0.0, 1.0, 1.5, 2.0, 3.0, 4.0],
    "trail_atr": [0.0, 0.0, 2.0, 3.0, 4.0],
    "trail_after_r": [0.0, 1.0],
    "breakeven_r": [0.0, 0.0, 0.5, 1.0],
    "time_bars": [0, 5, 10, 20, 40],
}
DIRS = [1, 1, 1, -1]

_S = _A = None


def _init(series, args):
    global _S, _A
    _S, _A = series, args


def sample(rng) -> tuple[dict, sim.Exit, int]:
    cfg = {k: rng.choice(v) for k, v in SPACE.items()}
    if cfg["family"] == "ma_cross":
        cfg["ma_slow"] = max(cfg["ma_slow"], cfg["ma_fast"] * 2)
        cfg["ma_cross_only"] = bool(rng.random() < 0.7)
    ex = sim.Exit(**{k: rng.choice(v) for k, v in EX_SPACE.items()})
    if ex.target_r == 0 and ex.trail_atr == 0 and ex.time_bars == 0:
        ex = sim.Exit(**{**ex.__dict__, "time_bars": 20})
    return cfg, ex, int(rng.choice(DIRS))


def quick_edge(masks, ex, dirn, era, rng) -> dict | None:
    """Real minus random-entry mean R, pooled. No placebos — this is the sieve."""
    real, rand, n = [], [], 0
    for tk, s in _S.items():
        keep = {"tr": 0, "va": 1, "te": 2}[era]
        km = lab.era_masks(s)[keep]
        mm = masks[tk] & km
        k = int(mm.sum())
        if k == 0:
            continue
        n += k
        real += [t.r for t in sim.simulate(s, mm, ex, _A.cost_bps, dirn)]
        for _ in range(RAND_DRAWS):
            rm = validate.random_mask(len(s), k, rng) & km
            rand += [t.r for t in sim.simulate(s, rm, ex, _A.cost_bps, dirn)]
    if len(real) < _A.min_trades or len(rand) < 30:
        return None
    return {"n": len(real), "real": float(np.mean(real)),
            "rand": float(np.mean(rand)),
            "edge": float(np.mean(real)) - float(np.mean(rand))}


def _trial(seed):
    rng = np.random.default_rng(seed)
    cfg, ex, dirn = sample(rng)
    try:
        masks = {tk: strategies.signal(s, cfg) for tk, s in _S.items()}
    except (KeyError, ValueError):
        return None
    tr = quick_edge(masks, ex, dirn, "tr", rng)
    if tr is None or tr["edge"] <= _A.min_edge:
        return None
    va = quick_edge(masks, ex, dirn, "va", rng)
    if va is None or va["edge"] <= 0:
        return None
    key = {k: (v.item() if hasattr(v, "item") else v) for k, v in cfg.items()}
    return (key, ex.__dict__, dirn, tr, va)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="etfs")
    p.add_argument("--n", type=int, default=4000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--min-trades", type=int, default=150)
    p.add_argument("--min-edge", type=float, default=0.0)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--out", default="candidates.json")
    args = p.parse_args()

    series = lab.load(args.universe)
    print(f"\n  {args.universe}: {len(series)} tickers")
    print(f"  TRAIN ≤{lab.TRAIN_END}   VAL ≤{lab.VAL_END}   TEST after")
    print(f"  Cost {args.cost_bps:g}bps/side. Bar: must beat RANDOM ENTRIES.")
    print(f"  Sampling {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(series, args)) as pool:
        res = [r for r in pool.imap_unordered(_trial,
               range(args.seed, args.seed + args.n), chunksize=8) if r]

    print(f"  {len(res)} configs beat random entries in BOTH train and val "
          f"({100.0*len(res)/args.n:.1f}% of those sampled)\n")
    if not res:
        print("  Nothing cleared the bar. That is the result.")
        return 1

    res.sort(key=lambda r: min(r[3]["edge"], r[4]["edge"]), reverse=True)
    print(f"  {'family':<10} {'dir':>4} {'TR n':>6} {'TR edge':>8} "
          f"{'VA n':>6} {'VA edge':>8} {'min':>8}")
    print("  " + "-" * 62)
    for cfg, exd, dirn, tr, va in res[:args.top]:
        print(f"  {cfg['family']:<10} {'L' if dirn==1 else 'S':>4} {tr['n']:>6} "
              f"{tr['edge']:>+8.3f} {va['n']:>6} {va['edge']:>+8.3f} "
              f"{min(tr['edge'],va['edge']):>+8.3f}")

    def plain(x):
        """numpy scalars are not JSON-serialisable; unwrap them."""
        if hasattr(x, "item"):
            return x.item()
        if isinstance(x, dict):
            return {k: plain(v) for k, v in x.items()}
        return x

    with open(args.out, "w") as fh:
        json.dump([{"cfg": plain(c), "exit": plain(e), "dir": int(d),
                    "train": plain(t), "val": plain(v)}
                   for c, e, d, t, v in res[:200]], fh, indent=1)
    print(f"\n  wrote {min(len(res),200)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
