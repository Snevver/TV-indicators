#!/usr/bin/env python3
"""Phase 3: does the winner beat the BEST OF N PLACEBOS, not just random entries?

Searching N configs over pure noise still produces a best-of-N that looks good.
The Westfall-Young max-statistic correction asks the right question: build the
distribution of "best result a search this wide produces by luck", then see where
the real winner sits in it.

Placebo draw k uses the SAME time shift across every candidate, so the k-th
placebo of each candidate is one coherent draw of "the whole search, but noise".
Candidates are compared as z-scores rather than raw R, so a naturally noisy
config cannot set the bar for everyone.
"""
from __future__ import annotations

import argparse
import json

import numpy as np

import lab
import sim
import strategies
import validate


def placebo_scores(series, masks, ex, dirn, era, offsets, cost_bps):
    """Mean R for each shared time shift, and the real mean R, pooled."""
    keep_i = {"tr": 0, "va": 1, "te": 2}[era]
    real, rand = [], []
    tot = np.zeros(len(offsets))
    cnt = np.zeros(len(offsets))
    rng = np.random.default_rng(12345)

    for tk, s in series.items():
        km = lab.era_masks(s)[keep_i]
        mm = masks[tk] & km
        k = int(mm.sum())
        if k == 0:
            continue
        real += [t.r for t in sim.simulate(s, mm, ex, cost_bps, dirn)]
        for _ in range(3):
            rm = validate.random_mask(len(s), k, rng) & km
            rand += [t.r for t in sim.simulate(s, rm, ex, cost_bps, dirn)]
        n = len(s)
        for j, off in enumerate(offsets):
            pm = validate.shift_mask(masks[tk], off % n) & km
            tt = sim.simulate(s, pm, ex, cost_bps, dirn)
            if tt:
                tot[j] += sum(x.r for x in tt)
                cnt[j] += len(tt)

    if len(real) < 40 or len(rand) < 20:
        return None
    ok = cnt >= 20
    if ok.sum() < 20:
        return None
    rand_m = float(np.mean(rand))
    null = np.full(len(offsets), np.nan)
    null[ok] = tot[ok] / cnt[ok] - rand_m
    return {"real": float(np.mean(real)), "rand": rand_m,
            "edge": float(np.mean(real)) - rand_m, "n": len(real), "null": null}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="etfs")
    p.add_argument("--candidates", default="candidates.json")
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--placebos", type=int, default=200)
    p.add_argument("--cost-bps", type=float, default=5.0)
    args = p.parse_args()

    series = lab.load(args.universe)
    with open(args.candidates) as fh:
        cands = json.load(fh)[:args.top]
    rng = np.random.default_rng(7)
    offsets = [int(x) for x in rng.integers(300, 5000, size=args.placebos)]

    print(f"\n  {len(cands)} candidates x {args.placebos} shared placebo shifts")
    print(f"  Scored on VALIDATION. Shifts are shared, so column k across all")
    print(f"  candidates is one coherent draw of 'this search, but noise'.\n")

    rows = []
    for c in cands:
        ex = sim.Exit(**c["exit"])
        masks = {tk: strategies.signal(s, c["cfg"]) for tk, s in series.items()}
        r = placebo_scores(series, masks, ex, c["dir"], "va", offsets, args.cost_bps)
        if r is None:
            continue
        good = np.isfinite(r["null"])
        nm, nsd = np.nanmean(r["null"]), np.nanstd(r["null"], ddof=1)
        if not np.isfinite(nsd) or nsd <= 0:
            continue
        r["z"] = (r["edge"] - nm) / nsd
        r["zn"] = (r["null"] - nm) / nsd
        r["p_own"] = (1 + np.nansum(r["null"] >= r["edge"])) / (1 + good.sum())
        rows.append((c, r))

    if not rows:
        print("  No candidate produced a usable placebo null.")
        return 1

    rows.sort(key=lambda kv: -kv[1]["z"])
    print(f"  {'family':<10} {'dir':>4} {'n':>6} {'edge':>8} {'z':>6} {'own p':>7}")
    print("  " + "-" * 50)
    for c, r in rows[:12]:
        print(f"  {c['cfg']['family']:<10} {'L' if c['dir']==1 else 'S':>4} "
              f"{r['n']:>6} {r['edge']:>+8.3f} {r['z']:>+6.2f} {r['p_own']:>6.1%}")

    # Westfall-Young: the null of the MAXIMUM z across candidates, per shift.
    Z = np.vstack([r["zn"] for _, r in rows])
    with np.errstate(invalid="ignore"):
        max_null = np.nanmax(Z, axis=0)
    max_null = max_null[np.isfinite(max_null)]
    best_z = rows[0][1]["z"]
    fam_p = (1 + np.sum(max_null >= best_z)) / (1 + len(max_null))

    print("\n  " + "=" * 62)
    print("  MULTIPLE-TESTING BAR (Westfall-Young max-statistic)")
    print("  " + "=" * 62)
    print(f"  Configs originally searched : 4000")
    print(f"  Candidates carried here     : {len(rows)}")
    print(f"  Best candidate z            : {best_z:+.2f}")
    print(f"  Best-of-placebos, median    : {np.median(max_null):+.2f}")
    print(f"  Best-of-placebos, 95th pct  : {np.percentile(max_null, 95):+.2f}")
    print(f"  FAMILY-WISE p               : {fam_p:.1%}")
    print(f"    = chance a search this wide over NOISE beats the real winner")
    print(f"\n  >> {'CLEARS the bar' if fam_p <= 0.05 else 'does NOT clear the bar'}")

    best_c, best_r = rows[0]
    print("\n  BEST CANDIDATE")
    print(f"    {json.dumps(best_c['cfg'])}")
    print(f"    exit {json.dumps(best_c['exit'])}  dir {best_c['dir']}")
    with open("finalist.json", "w") as fh:
        json.dump(best_c, fh, indent=1)
    print("    written to finalist.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
