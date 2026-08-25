# Wickless Retest

Marks candles that opened without hesitation, draws their open as a level, and
alerts when price returns to it.

**[`indicators/wickless-retest.pine`](indicators/wickless-retest.pine)**

## The idea

A bearish candle whose **high equals its open** has no upper wick: sellers were in
control from the opening tick. A bullish candle whose **low equals its open** has no
lower wick. Mark that open as a line, wait for price to come back to it, and take
the trade in the trend direction — sell the retest in a downtrend, buy it in an
uptrend. Stop just beyond the recent swing, target 1:1.

## It did not pass a backtest

Tested on 15-minute bars, 2010-2020, eight instruments, 4bps round-trip cost, with
a three-way train/validate/test split:

| Version | Result |
|---|---|
| Exactly as described (trend filter, tight swing stop, 1:1) | **-0.78R per trade**, 32% win rate against a 50% break-even |
| Best of 1,500 parameter combinations, on held-out data | still negative, about **-0.18R** |
| Search on four equity indices, 1,500 configs | **nothing** passed train and validate |

Wickless candles are not rare — they are 8-28% of all bars depending on the
instrument — so this is not a sample-size problem. There were 4,100 trades in the
full-history run.

### Why it fails, in two parts

**1. The stop is smaller than the spread.** You enter *at* the level, and the level
*is* the recent high or low, so "stop just beyond the swing with a little breathing
room" puts the stop about **0.10% of price** on a 15-minute chart. A 4bp round trip
is then **39% of everything you risk** on the trade. Widening the stop to 2 ATR cut
that to 12% and improved results a lot — the setting mattered more than any other —
but not enough to cross into profit.

| Stop | Stop as % of price | Cost as % of 1R | Gross | Net |
|---|---|---|---|---|
| swing + 0.2 ATR | 0.104% | 38.6% | -0.129R | -0.784R |
| swing + 1.0 ATR | 0.202% | 19.8% | -0.140R | -0.394R |
| swing + 2.0 ATR | 0.330% | 12.1% | -0.172R | -0.320R |

**2. The level does not hold.** Look at the *gross* column above: with costs set to
zero the setup still loses, at 43.5% win rate against a 50% break-even. Price
continues through these levels more often than it reverses from them. Costs make a
losing setup worse; they are not what makes it lose.

### The bug that made it look brilliant

An earlier version of this test reported **+0.26R per trade and 6.8 trades a week**,
profitable on every instrument, surviving five of six out-of-sample checks. It was
wrong. The simulator let a single bar both travel far enough away from the level
*and* return to it — and OHLC data cannot say which happened first inside a bar, so
that quietly assumed the favourable ordering every time. Requiring the level to be
armed by a bar that had already closed erased the entire edge:

| | Expectancy (test slice) |
|---|---|
| With the intrabar assumption | **+0.261R** |
| After the fix | **-0.184R** |

If you find a backtest of this pattern showing a strong edge, check that first.

## What the script is still for

- **Marking the levels** so you can watch how price behaves at them on your own
  instrument and timeframe.
- **Alerts on setup and retest**, so you can judge each one yourself.
- A discretionary trader filtering these by context is doing something a mechanical
  backtest cannot measure. The negative result above says the rule set has no edge
  *on its own*, not that every trader using it is losing.

Two honest gaps: it was **never tested on AUD/CHF** — that data was not available —
and it was tested on indices, majors, gold and oil, which may behave differently
from a low-volatility cross.

## Settings that mattered

Sensitivity on held-out data, before the bug fix but the ordering held after it:

| Parameter | Effect |
|---|---|
| **Minimum move away** | The big one. Below 2 ATR, clearly worse; the further price must travel before the retest counts, the better each trade |
| **Minimum stop distance** | Second biggest. 0.5 ATR was heavily negative; 2 ATR was the best of those tried |
| Reward:risk | Higher paid better per trade; 1:1 gave the highest win rate |
| Wick tolerance | Almost no effect — the detection is robust |
| Body filter | Almost no effect |
| Trend filter | Turning it **off** scored slightly better than on |

Defaults in the script follow the strategy as described, so it behaves the way you
expect. The tooltips flag where testing disagreed.

## Reproducing

```bash
cd research
# 15-minute bars must be built first (~5.7GB source, not in git) —
# see the docstring in build_intraday.py
python3 wickless_search.py --tf m15 --n 1500 --symbols SPX500,NAS100,US2000,JP225
```
