# ZeroStar Mean-Reversion Suite

Four generations of a mean-reversion signal indicator, and the research that
killed three of them.

## Use this one

**[`indicators/zerostar-intraday-v4.pine`](indicators/zerostar-intraday-v4.pine)** — 15-minute bars.

```
RSI(2) ≤ 25  +  close above EMA(100)  +  long only
stop 8×ATR(20), target 2R
```

Measured on 5 instruments (S&P, Nasdaq, Russell, Nikkei, gold), 2010-2020, 4bps
round trip, 1% risked per trade, max 3 positions open:

| | Trades/week | Win rate | CAGR | Max drawdown |
|---|---|---|---|---|
| **Held-out test slice** | 2.6 | 37.7% | **+11.0%** | 17.7% |
| Full history | 2.8 | 37.4% | +11.2% | 28.0% |

Test and full history agree to within 0.2% a year, which is the strongest sign
here that the edge is real rather than fitted.

Break-even at 1:2 is 33.3%, so 37% is a genuine but modest edge. It is **not** the
60-70% win rate that signal indicators advertise — see FINDINGS for why that
number is not available at this payoff.

## The full lineup

| Version | Timeframe | Win rate | Test CAGR | Verdict |
|---|---|---|---|---|
| v2 "Alpha" | any | — | — | **Broken.** Its four entry conditions are mutually exclusive; fires zero times in 26 years of SPY |
| v3 "Pullback" | daily | 49.4% | ~+1.3% | Real edge, but ~3 trades a year — untradeable |
| **v4 "Intraday"** | **15-min** | **37.7%** | **+11.0%** | **Ships** |
| v5 "Win-Rate" | 15-min | 53.1% | +4.4% | Wins more often, earns less. Pick knowingly |

### v4 versus v5: the exchange rate

Same instruments, same held-out slice, 1% risk:

| | Win rate | Trades/week | Test CAGR | Full-history return/drawdown |
|---|---|---|---|---|
| v4 (1:2 payoff) | 37.7% | 2.6 | **+11.0%** | 0.40 |
| v5 (1:1 payoff) | 50.7% | 1.2 | -1.0% | **0.65** |

v4 makes more money. v5 wins more often and has shallower drawdowns over the full
history, but its held-out slice was weak. If you will abandon a system during a
losing streak, v5's smoother ride has real value — otherwise v4.

## What the research established

Short version; the numbers are in [`research/FINDINGS.md`](research/FINDINGS.md).

1. **v2 was contradictory, not strict.** An engulfing candle is an *up* bar, while
   its "oversold" and "price fell" conditions both demand recent weakness. The
   conjunction never occurs.
2. **A 60-70% win rate at 1:2 does not exist here.** Best out-of-sample was 51.6%.
   It is reachable at 1:0.5, where break-even is 66.7% — so the win rate is
   handed straight back.
3. **Optimising for win rate is actively harmful.** Every config reaching 60% on a
   validation slice fell to ~36% and negative expectancy on untouched data.
4. **Shorter bars do not buy frequency.** The stop is one ATR, and the ATR shrinks
   with the bar while the spread does not. At 15 minutes a 1×ATR stop makes a
   round trip cost 93% of what you risk. v4 fixes this with a wide stop on a small
   bar — entry frequency comes from bar count, cost drag from stop size.
5. **The edge is equity-index-specific.** Pooled over FX and oil it is negative.
   Trade the basket, not one symbol.
6. **Requiring five instruments to agree is what stopped the overfitting.**
   Single-instrument searches passed validation and died on test roughly 2 times
   in 8; the five-instrument requirement survived 5-6 times in 6.

## Running the research

Dependency-free, Python 3.9+.

```bash
cd research

python3 fetch_data.py                    # daily data (cached in data/)
python3 backtest.py --csv data/SPY_d1.csv
./validate.sh                            # controls with known answers

# Intraday work needs the bars rebuilt first (~5.7GB source, not in git):
#   see the docstring in build_intraday.py
python3 intraday_portfolio.py --test-only
python3 pooled_search.py --tf m15 --symbols indices
```

## Caveats worth repeating

- The Pine scripts have **not been compiled by TradingView** — they were written
  and reasoned about, not parser-verified. Paste one in and check.
- Intraday results assume **4bps round trip**. That is an index-CFD figure; stocks
  and retail spreads are worse, and this strategy is unusually sensitive to it.
- Backtests are the best case. They contain no funding costs, no partial fills, no
  outages, and no bad decisions made at 3am.
