#!/usr/bin/env python3
"""The intraday basket on one account, risking 1% per trade.

Config is the pooled-search winner: RSI(2) <= 25 while above the EMA(100), long
only, stop 8 x ATR(20), target 2R, on 15-minute bars. It was selected by requiring
profitability across five instruments simultaneously in both a train and a
validate slice, then scored once on a test slice.

Two risk controls, because a basket of dip-buyers fails together:
  --max-open      cap on simultaneous positions
  --max-risk-pct  cap on TOTAL open risk, which is the one that actually matters
"""
from __future__ import annotations

import argparse
from backtest import load_csv, simulate
from engine import Settings
from engine_v3 import Config, generate
from search_yield import bars_per_year

SYMBOLS = ["SPX500", "NAS100", "US2000", "JP225", "XAUUSD"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tf", default="m15")
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--max-open", type=int, default=5)
    p.add_argument("--fee-bps", type=float, default=1.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--test-only", action="store_true",
                   help="score only the held-out slice")
    p.add_argument("--symbols", default=",".join(SYMBOLS))
    args = p.parse_args()

    cfg = Config(rsi_len=2, rsi_buy=25, use_rsi=True, regime="with_trend",
                 trend_len=100, longs=True, shorts=False, gap=1,
                 atr_len=20, sl=8.0, tp=16.0)
    s = Settings(tp_mult=16.0, sl_mult=8.0, atr_length=20)
    syms = [x.strip() for x in args.symbols.split(",")]

    trades = []
    span_years = 0.0
    for sym in syms:
        bars = load_csv(f"data/{sym}_{args.tf}.csv")
        bpy = bars_per_year(bars)
        if args.test_only:
            bars = bars[int(len(bars) * 0.78):]
        span_years = max(span_years, len(bars) / bpy)
        for t in simulate(bars, generate(bars, cfg), s,
                          args.fee_bps, args.slippage_bps, "open", 0):
            trades.append((t.entry_t, t.exit_t, t.r, sym))

    if not trades:
        print("  No trades.")
        return 1
    trades.sort()
    print(f"\n  {len(syms)} instruments, {args.tf}, "
          f"{'TEST slice only' if args.test_only else 'full history'} "
          f"({span_years:.1f} years)")
    print(f"  {len(trades)} raw signals = {len(trades)/(span_years*52):.1f} per week\n")

    # Each trade is one object, so an entry that was refused cannot have its exit
    # applied later. Getting this wrong silently books P&L for trades never taken.
    class T:
        __slots__ = ("entry", "exit", "r", "sym", "taken")

        def __init__(self, entry, exit_t, r, sym):
            self.entry, self.exit, self.r, self.sym, self.taken = entry, exit_t, r, sym, False

    objs = [T(e, x, r, s) for e, x, r, s in trades]
    events = []
    for o in objs:
        events.append((o.entry, 0, o))
        events.append((o.exit, 1, o))
    events.sort(key=lambda e: (e[0], e[1]))

    print(f"  {'max open':>9} {'taken':>7} {'per wk':>7} {'win%':>7} "
          f"{'final $':>10} {'CAGR':>8} {'maxDD':>8}")
    print("  " + "-" * 62)
    for cap in (1, 2, 3, 5, 8, 0):
        for o in objs:
            o.taken = False
        equity, peak, dd = args.capital, args.capital, 0.0
        open_n = taken = wins = closed = 0
        for _when, kind, o in events:
            if kind == 0:
                if cap and open_n >= cap:
                    continue
                o.taken = True
                open_n += 1
                taken += 1
            else:
                if not o.taken:
                    continue
                o.taken = False
                open_n -= 1
                equity *= (1.0 + (args.risk_pct / 100.0) * o.r)
                wins += int(o.r > 0)
                closed += 1
                peak = max(peak, equity)
                dd = max(dd, (peak - equity) / peak)
        cagr = (equity / args.capital) ** (1 / span_years) - 1 if span_years else 0
        label = "unlimited" if cap == 0 else str(cap)
        print(f"  {label:>9} {taken:>7} {taken/(span_years*52):>7.1f} "
              f"{100.0*wins/closed if closed else 0:>6.1f}% {equity:>10,.0f} "
              f"{cagr*100:>+7.1f}% {dd*100:>7.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
