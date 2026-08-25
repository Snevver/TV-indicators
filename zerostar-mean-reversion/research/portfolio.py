#!/usr/bin/env python3
"""Run V3 across a basket of stocks on ONE account, risking 1% per trade.

Frequency cannot come from shorter bars — see cost_analysis.py, where a 15-minute
round trip costs 93% of the amount risked. It has to come from more instruments.
One stock on daily bars gives ~3 signals a year; 500 stocks give a few a week,
with each trade still risking only 1% and each bar still large enough that the
spread is a rounding error.

Realism notes, all of which make the result WORSE than a naive run:
  * one shared equity curve, so 1% risk means 1% of the whole account
  * a cap on how many positions may be open at once, since 40 open trades at 1%
    each is a 40% bet, not a 1% one
  * signals arriving when the cap is full are DROPPED, not queued
  * entries fill at the next bar's open, exits at the ATR target or stop

  * SURVIVORSHIP BIAS: this dataset is the S&P 500 membership as of 2018, so it
    excludes every company that went bankrupt or was delisted during the window.
    The real-world number is lower than whatever this prints. It cannot be fixed
    from this data; treat the result as an upper bound.
"""
from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass

from backtest import Bar, load_csv, simulate
from engine import Settings
from engine_v3 import Config, generate


@dataclass
class PortfolioTrade:
    symbol: str
    entry_t: str
    exit_t: str
    r: float


def walk(all_trades, args, max_open: int) -> dict:
    """Replay every signal against one account. Returns summary numbers."""
    equity = args.capital
    peak, max_dd = equity, 0.0
    open_n = 0
    taken = wins = closed = 0

    events = []
    for t in all_trades:
        events.append((t.entry_t, 0, t))
        events.append((t.exit_t, 1, t))
    events.sort(key=lambda e: (e[0], e[1]))

    accepted = set()
    for _when, kind, t in events:
        if kind == 0:
            if max_open and open_n >= max_open:
                continue
            open_n += 1
            accepted.add(id(t))
            taken += 1
        else:
            if id(t) not in accepted:
                continue
            open_n -= 1
            equity *= (1.0 + (args.risk_pct / 100.0) * t.r)
            wins += int(t.r > 0)
            closed += 1
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)

    years = 5.0
    return {"taken": taken, "per_week": taken / (years * 52),
            "win": 100.0 * wins / closed if closed else 0.0,
            "equity": equity, "dd": max_dd,
            "cagr": (equity / args.capital) ** (1 / years) - 1}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="data/stocks")
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--max-open", type=int, default=10,
                   help="cap on simultaneous positions (0 = unlimited)")
    p.add_argument("--fee-bps", type=float, default=2.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--sweep", action="store_true",
                   help="try several concurrency caps and compare")
    args = p.parse_args()

    cfg = Config(rsi_len=5, rsi_buy=35, use_rsi=True, down_days=3, stability=0.3,
                 regime="with_trend", trend_len=100, longs=True, shorts=False,
                 gap=1, atr_len=14, tp=2.0, sl=1.0)
    s = Settings(tp_mult=2.0, sl_mult=1.0, atr_length=14)

    if not os.path.isdir(args.dir):
        tarball = os.path.join(os.path.dirname(args.dir) or ".", "stocks_sp500_5yr.tar.gz")
        if os.path.exists(tarball):
            import tarfile
            print(f"  Extracting {tarball} ...")
            with tarfile.open(tarball) as tf:
                tf.extractall(os.path.dirname(args.dir) or ".")
        else:
            print(f"  {args.dir} not found and no tarball beside it.")
            return 2

    files = sorted(glob.glob(os.path.join(args.dir, "*.csv")))
    if args.max_symbols:
        files = files[:args.max_symbols]
    print(f"\n  Scanning {len(files)} symbols...")

    all_trades: list[PortfolioTrade] = []
    first_day, last_day = None, None
    skipped = 0
    for path in files:
        try:
            bars = load_csv(path)
        except SystemExit:
            skipped += 1
            continue
        if len(bars) < 250:
            skipped += 1
            continue
        first_day = bars[0].t if first_day is None else min(first_day, bars[0].t)
        last_day = bars[-1].t if last_day is None else max(last_day, bars[-1].t)
        sym = os.path.basename(path).split("_")[0]
        for t in simulate(bars, generate(bars, cfg), s,
                          args.fee_bps, args.slippage_bps, "open", 0):
            all_trades.append(PortfolioTrade(sym, t.entry_t, t.exit_t, t.r))

    if not all_trades:
        print("  No trades.")
        return 1

    all_trades.sort(key=lambda t: t.entry_t)
    years = 5.0
    print(f"  {len(all_trades)} raw signals across {len(files)-skipped} symbols, "
          f"{first_day} → {last_day}\n")

    if args.sweep:
        print(f"  {'max open':>9} {'trades/wk':>10} {'win%':>7} {'final $':>10} "
              f"{'CAGR':>8} {'maxDD':>8}")
        print("  " + "-" * 56)
        for cap in (1, 2, 3, 5, 10, 20, 0):
            r = walk(all_trades, args, cap)
            label = "unlimited" if cap == 0 else str(cap)
            print(f"  {label:>9} {r['per_week']:>10.2f} {r['win']:>6.1f}% "
                  f"{r['equity']:>10,.0f} {r['cagr']*100:>+7.1f}% {r['dd']*100:>7.1f}%")
        print("  " + "-" * 56)
        return 0

    # ── Walk the calendar with one shared account ────────────────────────────
    equity = args.capital
    peak, max_dd = equity, 0.0
    open_positions: list[PortfolioTrade] = []
    taken, dropped, wins = 0, 0, 0
    curve = []

    events = []
    for t in all_trades:
        events.append((t.entry_t, 0, t))       # 0 = open, sorts before close
        events.append((t.exit_t, 1, t))
    events.sort(key=lambda e: (e[0], e[1]))

    accepted: set[int] = set()
    for when, kind, t in events:
        if kind == 0:
            if args.max_open and len(open_positions) >= args.max_open:
                dropped += 1
                continue
            open_positions.append(t)
            accepted.add(id(t))
            taken += 1
        else:
            if id(t) not in accepted:
                continue
            open_positions = [o for o in open_positions if o is not t]
            equity *= (1.0 + (args.risk_pct / 100.0) * t.r)
            wins += int(t.r > 0)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)
            curve.append((when, equity))

    print("  RESULT — one account, "
          f"{args.risk_pct:g}% risked per trade, max {args.max_open or '∞'} open at once")
    print("  " + "-" * 66)
    print(f"  Trades taken            {taken}   ({taken/(years*52):.2f} per week)")
    print(f"  Signals dropped (full)  {dropped}")
    print(f"  Win rate                {100.0*wins/taken:.1f}%")
    print(f"  Starting capital        ${args.capital:,.2f}")
    print(f"  Ending capital          ${equity:,.2f}   "
          f"({100*(equity-args.capital)/args.capital:+.1f}%)")
    cagr = (equity / args.capital) ** (1 / years) - 1
    print(f"  Compound annual return  {cagr*100:+.1f}% a year")
    print(f"  Worst drawdown          {max_dd*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
