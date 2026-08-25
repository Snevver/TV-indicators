# Can this indicator win 60-70% of trades at 1:2?

**No.** Not on any instrument or rule set tested here, and the reason is structural
rather than a failure of tuning. The best honestly-validated result is **~50% at
1:2 on SPY**, which is profitable — comfortably above the 33.3% break-even — but it
is not 60%.

This file records how that was established, because the negative result is worth
more than another plausible-looking backtest.

## The arithmetic of the target

At 1:2, break-even is 33.3%. So:

| Win rate | Expectancy | 243 trades at 1% risk |
|---|---|---|
| 33.3% | 0.00R | flat |
| 50% | +0.50R | ~3.3× |
| **60%** | **+0.80R** | **~7×** |
| **70%** | **+1.10R** | **~14×** |

A 65%-at-1:2 system compounds an account roughly tenfold per few hundred trades.
No public systematic strategy sustains that. When a backtest shows it, the cause is
selection, not edge.

## Why V2 could never have worked

`diagnose.py` counts how often each of V2's conditions is true on SPY daily:

| Condition | Bars true |
|---|---|
| Candle stability ≥ 0.5 | 45.9% |
| RSI(14) ≤ 30 | 1.7% |
| Price fell over 4 bars | 43.0% |
| Bullish engulfing | 3.3% |
| **All four** | **0.0% — zero bars in 26 years** |

The conditions are mutually exclusive by construction: an engulfing candle is an
*up* bar, while "oversold" and "fell" both require recent weakness. V2 was not too
strict, it was contradictory. That is why it fired once in 9.3 years on gold.

## The win-rate / payoff frontier

Win rate is not free. At a fixed target and stop, price must travel `tp` ATRs
before `sl` ATRs, and that path-dependency caps how often you can win no matter how
good the entry is. Searching 1,200 configurations at each payoff on SPY:

| R:R | Break-even | Best out-of-sample win% | Its expectancy | Configs ≥60% win |
|---|---|---|---|---|
| 1:0.5 | 66.7% | 80.0% | +0.285R | 85 |
| 1:0.75 | 57.1% | 72.0% | +0.487R | 55 |
| 1:1 | 50.0% | 65.0% | +0.231R | 9 |
| 1:1.5 | 40.0% | 65.0% | +0.527R | 3 |
| **1:2** | **33.3%** | **51.6%** | +0.447R | **0** |
| 1:3 | 25.0% | 45.5% | +0.664R | 0 |

**Your 60-70% target is reachable — but only at 1:1 or tighter, not at 1:2.** You
can have the win rate or the payoff, not both. Note that expectancy does *not* rise
as win rate does: the 80%-win row earns less per trade than the 45%-win row.

## Why even those numbers are too optimistic

Taking the best of 1,200 out-of-sample results means selecting *on* the holdout,
which stops being a holdout the moment you do. `final_test.py` uses three slices —
search on TRAIN, rank on VALIDATE, report on TEST, which is read exactly once.

Ranking by win rate, at 1:2:

| Train win | Validate win | **Test win** | **Test expectancy** |
|---|---|---|---|
| 36.8% | 60.9% | **39.1%** | **-0.012R** |
| 36.8% | 60.9% | **39.1%** | **-0.025R** |
| 43.1% | 60.0% | **33.3%** | **-0.135R** |
| 38.9% | 60.0% | **33.3%** | **-0.186R** |

Every configuration that hit 60% on the validation slice fell back to ~36% and
negative expectancy on data it had never been selected against. **0 of 5 survived.**
Optimising for win rate optimises for noise.

## What did survive

Ranking by expectancy instead, one configuration held up across all three slices:

```
RSI(5) ≤ 35  +  3 consecutive lower closes  +  body/range ≥ 0.3
             +  close above EMA(100)  +  LONG ONLY  +  1:2 ATR exits

TRAIN 48.6% / +0.419R    VALIDATE 55.0% / +0.531R    TEST 54.2% / +0.567R (PF 2.13)
```

On the full SPY history: **85 trades, 49.4% win rate, +0.41R, PF 1.72, t = +2.42,
max drawdown 7.7%.** Shipped as
[`zerostar-pullback-v3.pine`](../indicators/zerostar-pullback-v3.pine).

Economically it is "buy a stretched pullback inside an established uptrend" — a
well-documented effect, which is a point in its favour: it was not invented by the
search, only located by it.

### Two honest caveats

**It is instrument-specific.** Pooled across the 13 FX and metals series, the same
rules give -0.117R with 5/14 profitable. Equity indices have structural upward drift
and documented dip-buying flow; FX pairs have neither.

| | Trades | Win | Expectancy |
|---|---|---|---|
| SPY daily | 85 | 49.4% | **+0.41R** |
| Pooled FX + gold | 368 | ~31% | **-0.12R** |

**Long-only is load-bearing.** The mirrored short rules lose on every instrument
tested. Fading strength in something with upward drift is a structurally losing bet.

## Reproducing

```bash
python3 diagnose.py data/SPY_d1.csv 0.5 70 4      # why V2 fires zero times
python3 frontier.py data/SPY_d1.csv --n 1200      # the win-rate/payoff frontier
python3 final_test.py data/SPY_d1.csv --n 4000 --rank-by win   # win-rate chasing fails
python3 final_test.py data/SPY_d1.csv --n 4000 --rank-by exp   # what survives
python3 rank_symbols.py h4                        # which instruments suit a fader
```

## The one-line summary

You asked for 60-70% at 1:2. What is available is **~50% at 1:2, which makes money**,
or **65-72% at 1:1 or tighter, which also makes money but no faster**. The
combination you asked for does not exist in this data, and a backtest that claims it
is showing you a selection artefact.
