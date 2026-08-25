# Stock Momentum

Each month, rank 40 large US stocks by their 6-month return and hold the
strongest 8, equally weighted.

**[`indicators/stock-momentum.pine`](indicators/stock-momentum.pine)** — put it on
any of the 40 and it shows BUY/SELL labels on rebalance bars plus the live ranking.

## Results

Universe and parameters were fixed on 2005–2021. The test era was never consulted
during selection. 10bps turnover cost.

| Era | CAGR | maxDD | Sharpe | Random pick | Edge | SPY | SPY Sharpe |
|---|---|---|---|---|---|---|---|
| TRAIN 2005–2015 | 12.7% | 57.6% | 0.69 | 10.2% | **+2.5%** | 4.9% | 0.42 |
| VAL 2016–2021 | 25.8% | 28.2% | 1.30 | 14.3% | **+11.5%** | 14.4% | 0.99 |
| **TEST 2021–2026** | **25.5%** | **18.7%** | **1.15** | 14.1% | **+11.4%** | 11.9% | 0.79 |

Beat the index on **both return and Sharpe in all three eras**, and beat a random
monthly pick of 8 from the same 40 names at the **100th percentile of 20 draws**
in the validation and test eras (85th in training — the era containing the
2008–09 momentum crash).

Random selection is the control that matters. It shares the universe, the
concentration and the survivorship bias — so the difference between them is the
ranking and nothing else.

## Why the modest numbers are the credible ones

An earlier version of this test, run on all 500 stocks and holding the top 2%,
produced a **52-point annual edge**. That result is not real. Its holdings were
CVNA, PLTR, SMCI, APP, HOOD — names that 10–50×'d in 2023–26 and appear in the
data *precisely because they are S&P 500 members today*. In 2021 CVNA nearly went
bankrupt. Picking momentum winners from a list of companies already known to have
succeeded is not a strategy; it is hindsight with extra steps.

The 40-name mega-cap version reports edges of **5 to 10 points a year**, which is
what the published momentum literature reports. That agreement is the reason to
believe it. An edge of 50 points would have been a bug — and twice in this
research, it was.

## The risk, stated plainly

**Momentum crashes.** In 2008–09 this drew down **55.7%**, and in 2009 alone it
underperformed a random pick by **42 points** as beaten-down names exploded
upward. That is the documented failure mode of momentum, not a defect in this
implementation, and **no stop-loss fixes it** — the damage happens through the
monthly rebalance, not intraday.

Size accordingly. This is a concentrated equity portfolio, not a hedge.

## How to trade it

1. Put the indicator on any of the 40 names. The table shows the live ranking.
2. On the first trading day of each month, hold the top 8, equal weight.
3. Sell what dropped out, buy what came in. Typically 1–3 changes.
4. Nothing else until next month.

**Current basket** (data through 2026-08-24): MU, INTC, CSCO, CAT, AAPL, COP,
JNJ, MRK. Bottom of the list: ORCL −35%, IBM −27%, CMCSA −24%.

You are always fully invested across 8 names, an eighth of the account each.
There is no stop and no target — the exit is the ranking.

## Caveats

**Survivorship.** The 40 are current index members with long histories, so firms
that failed are absent and the **absolute** returns are flattered. The edge over
random is the trustworthy number, since both arms share the bias. Mega-caps that
were already large in 2005 distort far less than small names that later grew
tenfold — which is why the universe is defined by liquidity and data length
rather than by picking winners.

**Ticker format.** BRK.B and F were excluded because dotted and dashed tickers
fail to resolve on some feeds — an invalid-symbol error on a live chart is how
this surfaced. The exclusion is a plumbing rule, not a returns filter, and the
universe was re-validated from scratch with their replacements (NVDA, plus the
next name by liquidity) included. GOOG and GOOGL are both present; the tested
universe contained both.

**No exchange prefixes.** TradingView resolves bare tickers itself, which avoids
the invalid-symbol error a wrong exchange guess produces.

**Not compiled by TradingView.** The Pine is written and reasoned about, not
parser-verified. The sibling `momentum-rotation` indicator, which shares this
structure, was verified correct against its backtest on a live chart.

## What this beat

Six approaches were tested and discarded before this one: intraday mean
reversion, a wickless-candle retest, overnight holding, dip-buying 500 stocks,
long/short momentum, and searched trend-following on both ETFs and stocks. Each
was invented by a parameter search, and each failed the multiple-testing bar it
therefore had to clear. Details in [`../momentum-rotation/`](../momentum-rotation/)
and [`../zerostar-mean-reversion/`](../zerostar-mean-reversion/).

This one was not invented here. That is why it survived.
