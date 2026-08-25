#!/usr/bin/env python3
"""Volatility-targeted rotation, with a cash filter.

The long/short test killed the idea that this universe holds clean ranking
alpha: market-neutral, the edge went negative out of sample. What DID survive
correction is narrower and duller — over the test era the long-only rotation
earned 10.5% against the index's 11.9% while drawing down 13.6% against 24.8%.
Less return, far less risk.

That is a risk advantage, not a return advantage, and the honest way to use one
is to convert it. Two mechanisms, both standard and neither invented here:

  VOLATILITY TARGETING  scale exposure so the portfolio's realised volatility
                        sits near a target. In calm markets that means leverage
                        above 1; in turbulent ones it means stepping down. This
                        is what raises return without simply adding risk.

  ABSOLUTE MOMENTUM     if a holding is below its own long-term average, hold
                        cash instead. Relative strength alone will happily pick
                        the best of a falling market.

Leverage is not free and is charged for: borrowing above 1x costs a financing
rate, and exposure is capped. Realised volatility is measured on TRAILING
returns only — using the coming month's volatility to size the coming month
would be a look-ahead, and a subtle one.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import lab
from rotation2 import panel
from longshort import anchors, spy_monthly


def backtest(px, lookback, hold_n, target_vol=0.0, max_lev=2.0, finance_bps=400.0,
             cost_bps=10.0, skip=21, abs_filter=False, ma_len=200,
             vol_win=6, lo=None, hi=None, month_start=True):
    idx = px.index
    me = anchors(idx, month_start)
    ma = px.rolling(ma_len).mean()

    eq = peak = 1.0
    dd = 0.0
    held: list[str] = []
    hist: list[float] = []          # trailing monthly returns, for sizing
    curve = []
    lev_log = []

    for a, b in zip(me[:-1], me[1:]):
        if lo is not None and idx[a] < lo:
            continue
        if hi is not None and idx[b] > hi:
            break
        if a - lookback - skip < 0:
            continue

        past, recent = px.iloc[a - lookback - skip], px.iloc[a - skip]
        now, nxt = px.iloc[a], px.iloc[b]
        ok = past.notna() & recent.notna() & now.notna() & nxt.notna() & (past > 0)
        if abs_filter:
            m = ma.iloc[a]
            ok &= m.notna() & (now > m)      # only names above their own trend
        mom = (recent / past - 1.0)[ok]

        pick = list(mom.nlargest(hold_n).index) if not mom.empty else []
        # Fewer than hold_n eligible names means the rest of the book is cash.
        gross = (len(pick) / hold_n) if hold_n else 0.0

        turn = len(set(pick) ^ set(held)) / max(len(pick) + len(held), 1)
        eq *= (1.0 - turn * cost_bps / 10_000.0)
        held = pick

        raw = float(np.mean((nxt[pick] / now[pick] - 1.0).to_numpy())) if pick else 0.0

        # Size on TRAILING volatility only.
        lev = 1.0
        if target_vol > 0:
            if len(hist) >= vol_win:
                rv = float(np.std(hist[-vol_win:], ddof=1)) * np.sqrt(12)
                lev = float(np.clip(target_vol / rv, 0.0, max_lev)) if rv > 1e-6 else 1.0
            else:
                lev = 1.0
        exposure = lev * gross
        lev_log.append(exposure)

        days = (idx[b] - idx[a]).days
        borrow = max(0.0, exposure - 1.0) * finance_bps / 10_000.0 * days / 365.25
        net = exposure * raw - borrow
        eq *= (1.0 + net)
        hist.append(raw * gross)

        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        curve.append((idx[b], eq))
        if eq <= 0:
            return None

    if not curve:
        return None
    yrs = (curve[-1][0] - curve[0][0]).days / 365.25
    vals = np.array([c[1] for c in curve])
    mret = np.diff(vals) / vals[:-1]
    return {"eq": eq, "cagr": eq ** (1 / yrs) - 1 if yrs > 0 else 0.0,
            "dd": dd * 100, "sharpe": mret.mean() / mret.std(ddof=1) * np.sqrt(12)
                      if len(mret) > 1 and mret.std(ddof=1) > 0 else 0.0,
            "avg_lev": float(np.mean(lev_log)), "max_lev": float(np.max(lev_log)),
            "rets": mret, "years": yrs}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--finance-bps", type=float, default=400.0)
    args = p.parse_args()
    px = panel(lab.load("etfs"))
    tr_end, va_end = pd.Timestamp(lab.TRAIN_END), pd.Timestamp(lab.VAL_END)

    print(f"\n  VOLATILITY-TARGETED ROTATION (lookback 168, hold 4)")
    print(f"  Financing above 1x charged at {args.finance_bps/100:g}%/yr. "
          f"Exposure capped at 2x.\n")
    for name, lo, hi in (("TRAIN", None, tr_end), ("VAL", tr_end, va_end),
                         ("TEST", va_end, None)):
        sp = spy_monthly(px, lo, hi)
        yrs = len(sp) / 12
        sp_c = (np.prod(1 + sp)) ** (1 / yrs) - 1
        sp_dd = 0.0
        v = np.cumprod(1 + sp); pk = np.maximum.accumulate(v)
        sp_dd = float(((pk - v) / pk).max() * 100)
        sp_sr = sp.mean() / sp.std(ddof=1) * np.sqrt(12)
        print(f"  === {name}   SPY {sp_c:+.1%}/yr  dd {sp_dd:.1f}%  SR {sp_sr:.2f}")
        print(f"  {'target':>7} {'absF':>5} {'CAGR':>8} {'maxDD':>7} {'sharpe':>7} "
              f"{'avg lev':>8}")
        for tv in (0.0, 0.10, 0.15, 0.20):
            for af in (False, True):
                r = backtest(px, 168, 4, tv, 2.0, args.finance_bps, 10.0, 21,
                             af, 200, 6, lo, hi)
                if r is None:
                    continue
                lab_tv = "none" if tv == 0 else f"{tv:.0%}"
                print(f"  {lab_tv:>7} {str(af):>5} {r['cagr']*100:>7.1f}% "
                      f"{r['dd']:>6.1f}% {r['sharpe']:>7.2f} {r['avg_lev']:>8.2f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
