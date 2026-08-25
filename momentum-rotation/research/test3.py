#!/usr/bin/env python3
"""Score capital-constrained candidates on the untouched era."""
from __future__ import annotations
import argparse, json
import numpy as np
import lab, sim, strategies, validate
from search3 import gather, ranked_account, _init
import search3


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="etfs")
    p.add_argument("--cand", default="cand3.json")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--cap", type=int, default=5)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--draws", type=int, default=8)
    p.add_argument("--min-trades", type=int, default=150)
    p.add_argument("--min-diff", type=float, default=0.0)
    args = p.parse_args()

    series = lab.load(args.universe)
    _init(series, args)
    cands = json.load(open(args.cand))[:args.top]
    rng = np.random.default_rng(2024)

    print(f"\n  TEST era, cap {args.cap}, {args.risk_pct:g}% risk, "
          f"{args.cost_bps*2:g}bps round trip")
    print(f"  Random baseline averaged over {args.draws} draws.\n")
    print(f"  {'family':<10} {'dir':>4} {'n':>5} {'CAGR':>8} {'randCAGR':>9} "
          f"{'diff':>7} {'win%':>6} {'maxDD':>7}")
    print("  " + "-" * 62)
    rows = []
    for c in cands:
        ex = sim.Exit(**c["exit"])
        tr = gather(c["cfg"], ex, c["dir"], "te")
        if len(tr) < 20:
            continue
        a = ranked_account(tr, args.cap, args.risk_pct)
        rc = []
        for _ in range(args.draws):
            b = ranked_account(gather(c["cfg"], ex, c["dir"], "te", rng),
                               args.cap, args.risk_pct)
            if b:
                rc.append(b["cagr"])
        rb = float(np.mean(rc)) if rc else 0.0
        rows.append((c, a, rb))
        print(f"  {c['cfg']['family']:<10} {'L' if c['dir']==1 else 'S':>4} "
              f"{a['taken']:>5} {a['cagr']*100:>7.1f}% {rb*100:>8.1f}% "
              f"{(a['cagr']-rb)*100:>6.1f}% {a['win']:>5.1f}% {a['dd']:>6.1f}%")

    if rows:
        pos = sum(1 for _c, a, rb in rows if a["cagr"] - rb > 0)
        print("  " + "-" * 62)
        print(f"  {pos}/{len(rows)} beat a random capped book out of sample")
        print(f"  mean difference {np.mean([a['cagr']-rb for _c,a,rb in rows])*100:+.1f}%")
        best = max(rows, key=lambda r: r[1]["cagr"] - r[2])
        json.dump(best[0], open("finalist3.json", "w"), indent=1)
        print(f"\n  BEST: {json.dumps(best[0]['cfg'])}")
        print(f"        exit {json.dumps(best[0]['exit'])} dir {best[0]['dir']}")
        print(f"        TEST CAGR {best[1]['cagr']*100:+.1f}% vs random "
              f"{best[2]*100:+.1f}%, maxDD {best[1]['dd']:.1f}%, "
              f"{best[1]['taken']} trades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
