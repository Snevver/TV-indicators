#!/usr/bin/env python3
"""Search demanding the edge survive on BOTH universes.

The first search found a strategy that beat random entries on 500 stocks by
+0.131R on held-out data, then failed a survivorship check: the same rules on 28
ETFs — a universe with no survivorship bias, because the ETFs still exist —
produced +0.013R. Buying crashed stocks looks brilliant when every company that
never recovered has been deleted from the dataset.

So the bar here is joint. A config must beat random entries on:
    stocks TRAIN, stocks VAL, and ETFs TRAIN+VAL combined.
The ETF leg cannot be inflated by survivorship, so passing it is evidence the
edge is a property of price behaviour rather than of the sample.

Everything is still scored as edge over random entries, never against zero.
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
from search import SPACE, EX_SPACE, DIRS, sample

_ST = _ET = _A = None


def _init(st, et, args):
    global _ST, _ET, _A
    _ST, _ET, _A = st, et, args


def edge_on(series, masks, ex, dirn, eras, rng, min_trades) -> dict | None:
    real, rand = [], []
    for tk, s in series.items():
        m = masks.get(tk)
        if m is None:
            continue
        em = lab.era_masks(s)
        keep = np.zeros(len(s), dtype=bool)
        for e in eras:
            keep |= em[{"tr": 0, "va": 1, "te": 2}[e]]
        mm = m & keep
        k = int(mm.sum())
        if k == 0:
            continue
        real += [t.r for t in sim.simulate(s, mm, ex, _A.cost_bps, dirn)]
        for _ in range(2):
            rm = validate.random_mask(len(s), k, rng) & keep
            rand += [t.r for t in sim.simulate(s, rm, ex, _A.cost_bps, dirn)]
    if len(real) < min_trades or len(rand) < 30:
        return None
    return {"n": len(real), "real": float(np.mean(real)),
            "rand": float(np.mean(rand)),
            "edge": float(np.mean(real)) - float(np.mean(rand)),
            # Median edge too: a mean driven by a handful of huge winners is
            # exactly what survivorship bias manufactures.
            "med": float(np.median(real))}


def _trial(seed):
    rng = np.random.default_rng(seed)
    cfg, ex, dirn = sample(rng)
    try:
        m_st = {tk: strategies.signal(s, cfg) for tk, s in _ST.items()}
        m_et = {tk: strategies.signal(s, cfg) for tk, s in _ET.items()}
    except (KeyError, ValueError):
        return None

    st_tr = edge_on(_ST, m_st, ex, dirn, ["tr"], rng, _A.min_trades)
    if st_tr is None or st_tr["edge"] <= 0:
        return None
    et = edge_on(_ET, m_et, ex, dirn, ["tr", "va"], rng, _A.min_etf_trades)
    if et is None or et["edge"] <= _A.min_etf_edge:
        return None
    st_va = edge_on(_ST, m_st, ex, dirn, ["va"], rng, _A.min_trades // 2)
    if st_va is None or st_va["edge"] <= 0:
        return None

    key = {k: (v.item() if hasattr(v, "item") else v) for k, v in cfg.items()}
    return (key, {k: (v.item() if hasattr(v, "item") else v)
                  for k, v in ex.__dict__.items()}, int(dirn),
            st_tr, st_va, et)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=6000)
    p.add_argument("--seed", type=int, default=100000)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--min-trades", type=int, default=1000)
    p.add_argument("--min-etf-trades", type=int, default=250)
    p.add_argument("--min-etf-edge", type=float, default=0.03)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    p.add_argument("--out", default="cand_joint.json")
    args = p.parse_args()

    st = lab.load("sp500")
    et = lab.load("etfs")
    print(f"\n  stocks {len(st)}   ETFs {len(et)}")
    print(f"  Bar: beat random entries on stocks TRAIN, stocks VAL, and")
    print(f"       ETFs TRAIN+VAL (edge > {args.min_etf_edge:g}R, no survivorship bias)")
    print(f"  Sampling {args.n} configs...\n")

    with Pool(args.jobs, initializer=_init, initargs=(st, et, args)) as pool:
        res = [r for r in pool.imap_unordered(_trial,
               range(args.seed, args.seed + args.n), chunksize=4) if r]

    print(f"  {len(res)} configs cleared ALL THREE legs "
          f"({100.0*len(res)/args.n:.2f}% of sampled)\n")
    if not res:
        print("  Nothing survived the joint bar.")
        return 1

    res.sort(key=lambda r: min(r[3]["edge"], r[4]["edge"], r[5]["edge"]),
             reverse=True)
    print(f"  {'family':<10} {'dir':>4} {'ST-tr':>8} {'ST-va':>8} "
          f"{'ETF':>8} {'ETF n':>7} {'min':>8}")
    print("  " + "-" * 62)
    for cfg, exd, dirn, a, b, c in res[:args.top]:
        print(f"  {cfg['family']:<10} {'L' if dirn==1 else 'S':>4} "
              f"{a['edge']:>+8.3f} {b['edge']:>+8.3f} {c['edge']:>+8.3f} "
              f"{c['n']:>7} {min(a['edge'],b['edge'],c['edge']):>+8.3f}")

    with open(args.out, "w") as fh:
        json.dump([{"cfg": a, "exit": b, "dir": d, "train": t, "val": v, "etf": e}
                   for a, b, d, t, v, e in res[:200]], fh, indent=1)
    print(f"\n  wrote {min(len(res),200)} to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
