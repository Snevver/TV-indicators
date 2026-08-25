#!/usr/bin/env python3
"""What $1,000 following ZeroStar Pullback V3 on SPY would have done this year.

Indicators are warmed up on the FULL history, then only trades ENTERED on or after
--from are counted, so the EMA(100) and friends are correct rather than restarting
from scratch in January.
"""
import argparse
from backtest import load_csv, simulate, evaluate
from engine import Settings
from engine_v3 import Config, generate

p = argparse.ArgumentParser()
p.add_argument("--from", dest="start", default="2026-01-01")
p.add_argument("--capital", type=float, default=1000.0)
p.add_argument("--risk-pct", type=float, default=1.0)
p.add_argument("--fee-bps", type=float, default=2.0)
p.add_argument("--slippage-bps", type=float, default=2.0)
a = p.parse_args()

cfg = Config(rsi_len=5, rsi_buy=35, use_rsi=True, down_days=3, stability=0.3,
             regime="with_trend", trend_len=100, longs=True, shorts=False,
             gap=1, atr_len=14, tp=2.0, sl=1.0)
s = Settings(tp_mult=2.0, sl_mult=1.0, atr_length=14)

bars = load_csv("data/SPY_d1.csv")
trades = simulate(bars, generate(bars, cfg), s, a.fee_bps, a.slippage_bps, "open", 0)
ytd = [t for t in trades if t.entry_t >= a.start]

print(f"\n  SPY, ZeroStar Pullback V3, risk 1 : reward 2")
print(f"  Data available: {bars[0].t} → {bars[-1].t}")
print(f"  Counting trades entered on or after {a.start}\n")

if not ytd:
    print("  No trades in that window.")
    raise SystemExit(0)

print(f"  {'#':>2} {'entered':<12} {'exited':<12} {'entry':>8} {'exit':>8} "
      f"{'result':>7} {'R':>7}")
print("  " + "-" * 66)
for i, t in enumerate(ytd, 1):
    outcome = "WIN" if t.r > 0 else "LOSS"
    print(f"  {i:>2} {t.entry_t:<12} {t.exit_t:<12} {t.entry:>8.2f} {t.exit:>8.2f} "
          f"{outcome:>7} {t.r:>+7.2f}")

wins = sum(1 for t in ytd if t.r > 0)
print("  " + "-" * 66)
print(f"  {len(ytd)} trades, {wins} wins, {len(ytd)-wins} losses "
      f"→ win rate {100.0*wins/len(ytd):.1f}%")
print(f"  Total: {sum(t.r for t in ytd):+.2f}R\n")

print("  WHAT THAT DOES TO $1,000")
print("  " + "-" * 66)
for risk in (1.0, 2.0, 5.0):
    eq = a.capital
    for t in ytd:
        eq *= (1.0 + (risk / 100.0) * t.r)
    pnl = eq - a.capital
    print(f"  Risking {risk:>3.0f}% of the account per trade  →  "
          f"${eq:>8.2f}   ({pnl:+.2f}, {100*pnl/a.capital:+.1f}%)")

# Buy-and-hold over the identical window, for comparison.
win = [b for b in bars if b.t >= a.start]
bh = a.capital * (win[-1].c / win[0].o)
print(f"\n  Just buying SPY and holding on {win[0].t}  →  "
      f"${bh:>8.2f}   ({bh-a.capital:+.2f}, {100*(bh-a.capital)/a.capital:+.1f}%)")
print(f"  (SPY went {win[0].o:.2f} → {win[-1].c:.2f} over the same period)\n")
