#!/usr/bin/env python3
"""Which instrument suits a mean-reversion fader?

Two independent readings per symbol:

1. VARIANCE RATIO — a property of the market itself, with no reference to the
   indicator. VR(q) = Var(q-bar returns) / (q x Var(1-bar returns)). A random walk
   gives 1.0. Below 1.0 means moves get partly given back (mean-reverting, good for
   a fader). Above 1.0 means moves persist (trending, bad for a fader).

2. The indicator's measured expectancy on that symbol.

If the two agree, the ranking is telling you something structural rather than a
quirk of one backtest.
"""
from __future__ import annotations

import glob
import os
import statistics
import sys

from backtest import load_csv, simulate, evaluate
from engine import Settings, generate_signals


def variance_ratio(closes, q: int) -> float:
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    if len(rets) < q * 10:
        return float("nan")
    var1 = statistics.pvariance(rets)
    qrets = [closes[i] / closes[i - q] - 1.0 for i in range(q, len(closes))]
    varq = statistics.pvariance(qrets)
    return varq / (q * var1) if var1 > 0 else float("nan")


def lag1_autocorr(closes) -> float:
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    m = statistics.fmean(rets)
    num = sum((rets[i] - m) * (rets[i - 1] - m) for i in range(1, len(rets)))
    den = sum((r - m) ** 2 for r in rets)
    return num / den if den else float("nan")


def main() -> int:
    tf = sys.argv[1] if len(sys.argv) > 1 else "h4"
    here = os.path.dirname(os.path.abspath(__file__))
    files = sorted(glob.glob(os.path.join(here, "data", f"*_{tf}.csv")))
    if not files:
        print(f"No cached *_{tf}.csv files. Run fetch_data.py first.")
        return 2

    s = Settings(stability_index=0.3, rsi_index=60, label_gap=3)

    print(f"\n  Timeframe: {tf}    settings: stability=0.3 rsi=60 gap=3 tp=2.0 sl=1.0")
    print(f"  Variance ratio < 1.00 = mean-reverting (good for a fader), > 1.00 = trending\n")
    print(f"  {'symbol':<10} {'VR(5)':>7} {'VR(20)':>7} {'AC(1)':>8} | "
          f"{'trades':>7} {'win%':>7} {'expectancy':>11} {'PF':>6} {'t':>6}")
    print("  " + "-" * 82)

    rows = []
    for path in files:
        name = os.path.basename(path).replace(".csv", "")
        bars = load_csv(path)
        closes = [b.c for b in bars]
        vr5, vr20, ac = variance_ratio(closes, 5), variance_ratio(closes, 20), lag1_autocorr(closes)

        sigs = generate_signals(bars, s).signals
        tr = simulate(bars, sigs, s, 2.0, 2.0, "open", 0)
        st = evaluate(tr, bars, 0.01)
        rows.append((st.expectancy if st.trades >= 20 else float("-inf"),
                     name, vr5, vr20, ac, st))

    rows.sort(reverse=True)
    for _, name, vr5, vr20, ac, st in rows:
        note = "" if st.trades >= 20 else "  (too few)"
        print(f"  {name:<10} {vr5:>7.3f} {vr20:>7.3f} {ac:>8.4f} | "
              f"{st.trades:>7} {st.win_rate:>6.1f}% {st.expectancy:>+11.4f} "
              f"{st.profit_factor:>6.2f} {st.t_stat:>+6.2f}{note}")

    usable = [r for r in rows if r[5].trades >= 20]
    if usable:
        vrs = [r[3] for r in usable if r[3] == r[3]]
        exps = [r[5].expectancy for r in usable]
        if len(vrs) > 2:
            m_vr, m_e = statistics.fmean(vrs), statistics.fmean(exps)
            num = sum((r[3] - m_vr) * (r[5].expectancy - m_e) for r in usable if r[3] == r[3])
            d1 = sum((r[3] - m_vr) ** 2 for r in usable if r[3] == r[3])
            d2 = sum((r[5].expectancy - m_e) ** 2 for r in usable)
            corr = num / (d1 * d2) ** 0.5 if d1 and d2 else float("nan")
            print("  " + "-" * 82)
            print(f"  Correlation between VR(20) and expectancy: {corr:+.3f}")
            print("  (negative = the more trending the market, the worse this indicator does)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
