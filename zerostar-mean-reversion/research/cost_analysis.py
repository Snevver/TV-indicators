#!/usr/bin/env python3
"""Why more trades does not mean more money.

The stop distance is one ATR. As you drop to smaller bars the ATR shrinks with
them — but the spread and commission you pay per round trip do not. So the cost
of a trade, measured as a fraction of the money you are risking on it, explodes.

That is the whole reason a signal indicator can look great on a daily chart and
bankrupt you on a 15-minute one.
"""
import statistics
from backtest import load_csv, simulate, evaluate
from engine import Settings, atr
from engine_v3 import Config, generate

FEE_BPS, SLIP_BPS = 2.0, 2.0
ROUND_TRIP = 2 * (FEE_BPS + SLIP_BPS) / 10_000.0     # both sides, as a fraction

cfg = Config(rsi_len=5, rsi_buy=35, use_rsi=True, down_days=3, stability=0.3,
             regime="with_trend", trend_len=100, longs=True, shorts=False,
             gap=1, atr_len=14, tp=2.0, sl=1.0)
s = Settings(tp_mult=2.0, sl_mult=1.0, atr_length=14)

print(f"\n  Costs assumed: {FEE_BPS:g}bps fee + {SLIP_BPS:g}bps slippage per side "
      f"= {ROUND_TRIP*10000:.0f}bps round trip\n")
print(f"  {'timeframe':<11} {'trades/wk':>9} {'1R (% price)':>13} {'cost as % of 1R':>16} | "
      f"{'GROSS exp':>10} {'NET exp':>9}")
print("  " + "-" * 78)

YEARS = {"SPY_d1": 26.2, "SPX_h4": 8.13, "SPX_h1": 8.13, "SPX_m15": 8.13}
for tf, yrs in YEARS.items():
    bars = load_csv(f"data/{tf}.csv")
    a = atr(bars, 14)
    atr_pct = statistics.median(a[i] / bars[i].c for i in range(len(bars)) if a[i])
    sigs = generate(bars, cfg)
    net = evaluate(simulate(bars, sigs, s, FEE_BPS, SLIP_BPS, "open", 0), bars, 0.01)
    gross = evaluate(simulate(bars, sigs, s, 0.0, 0.0, "open", 0), bars, 0.01)
    print(f"  {tf:<11} {net.trades/(yrs*52):>9.2f} {atr_pct*100:>12.3f}% "
          f"{100*ROUND_TRIP/atr_pct:>15.1f}% | {gross.expectancy:>+10.3f} "
          f"{net.expectancy:>+9.3f}")

print("  " + "-" * 78)
print("  Read the last two columns together: the gross edge barely changes, but the")
print("  toll does. On 15-minute bars you hand over most of your risk unit before")
print("  the trade has done anything.\n")
