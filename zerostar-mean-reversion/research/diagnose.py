#!/usr/bin/env python3
"""How often is each condition true, alone and in conjunction?

Before changing rules blindly, find out which one is doing the filtering. A rule
that fires 3% of the time is not a filter, it is a wall.
"""
import sys
from backtest import load_csv
from engine import rsi, atr, Settings

path = sys.argv[1]
stab_thr = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
rsi_idx = int(sys.argv[3]) if len(sys.argv) > 3 else 70
delta = int(sys.argv[4]) if len(sys.argv) > 4 else 4

bars = load_csv(path)
closes = [b.c for b in bars]
r = rsi(closes, 14)
n = len(bars)

counts = {k: 0 for k in ("stable", "oversold", "fell", "bull_engulf", "bull_candle",
                         "3of4", "ALL(engulf)", "ALL(no engulf)")}
valid = 0
for i in range(max(delta, 1), n):
    if r[i] is None:
        continue
    valid += 1
    b, p = bars[i], bars[i - 1]
    rng = b.h - b.l
    stability = (abs(b.c - b.o) / rng) if rng > 0 else 0.0
    stable = stability >= stab_thr
    oversold = r[i] <= 100 - rsi_idx
    fell = b.c < bars[i - delta].c
    engulf = b.c > b.o and p.c < p.o and b.c >= p.o and b.o <= p.c
    up = b.c > b.o

    counts["stable"] += stable
    counts["oversold"] += oversold
    counts["fell"] += fell
    counts["bull_engulf"] += engulf
    counts["bull_candle"] += up
    counts["3of4"] += (stable + oversold + fell + engulf) >= 3
    counts["ALL(engulf)"] += stable and oversold and fell and engulf
    counts["ALL(no engulf)"] += stable and oversold and fell and up

print(f"\n  {path}   {valid} usable bars")
print(f"  thresholds: stability>={stab_thr}  RSI<={100-rsi_idx}  delta={delta}\n")
print(f"  {'condition':<18} {'bars true':>10} {'% of bars':>11}")
print("  " + "-" * 42)
for k, v in counts.items():
    print(f"  {k:<18} {v:>10} {100.0*v/valid:>10.2f}%")

ind = counts["stable"]/valid * counts["oversold"]/valid * counts["fell"]/valid * counts["bull_engulf"]/valid
print(f"\n  If the four were independent, ALL would fire {100*ind:.4f}% "
      f"({ind*valid:.1f} bars).")
print(f"  It actually fires {counts['ALL(engulf)']} times "
      f"({100.0*counts['ALL(engulf)']/valid:.4f}%).")
print("  The conditions are strongly ANTI-correlated: an engulfing candle is an UP")
print("  bar, but 'oversold' and 'fell' both require recent weakness.\n")
