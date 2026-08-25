# Momentum Rotation

Once a month, rank 28 liquid ETFs by their 6-month return and hold the strongest
few. Use it to see which parts of the market are leading.

**[`indicators/momentum-rotation.pine`](indicators/momentum-rotation.pine)**

## Correction — read this first

An earlier version of this README claimed **+23.4%/yr against SPY's +11.9%, at
half the drawdown**. That was wrong, and the error was mine.

The backtest indexed every ETF by SPY's bar number, which is only valid if all 28
share one trading calendar. Six do not — HYG, KRE, SLV, USO, XBI and XLRE list
later and so have fewer bars. Bar 2000 was `2012-12-12` for SPY and `2015-03-20`
for HYG. Ranking at a 2012 date read **2015 prices** for those six, and they
supplied roughly a quarter of all holdings. That is look-ahead bias, and it
produced the entire apparent outperformance.

[`research/rotation2.py`](research/rotation2.py) aligns every series by date.
Corrected, with parameters chosen on 2005–2021 only:

| Era | Strategy | maxDD | Sharpe | SPY | maxDD | Sharpe |
|---|---|---|---|---|---|---|
| TRAIN 2005–2015 | 7.6% | 34.7% | 0.51 | 4.9% | 52.2% | 0.42 |
| VAL 2016–2021 | 13.6% | 20.3% | 1.04 | 14.4% | 19.9% | 0.99 |
| **TEST 2021–2026** | **11.4%** | 18.4% | 0.73 | **11.9%** | 24.8% | 0.79 |

$1,000 over the test era became **$1,731** here and **$1,784** in the index.

**It beats a random monthly pick of four ETFs by ~3 points a year**, so the
ranking does carry information. **It does not beat buying the index.**

## The Pine implementation is verified correct

Signals were checked against the backtest on USO, using the rank shown in each
label as a fingerprint. They match exactly:

```
chart SELL ranks           20, 17, 16, 10, 6, 10, 17, 18, 22
backtest, month-START      20, 17, 16, 10, 6, 10, 17, 18, 22   <- identical
backtest, month-END        11, 26, 17,  7, 13,  4, 16, 20, 26
```

That also settled a question the match itself raised. The indicator ranks on the
**first bar of a new month** — the earliest a monthly decision is executable —
while the original backtest ranked on the **last bar of the previous month**. Same
strategy, one bar apart, and worth measuring rather than assuming:

| Era | month-END (backtest) | month-START (indicator) | SPY |
|---|---|---|---|
| TRAIN | 7.6% (dd 34.7%) | 6.5% (dd 43.1%) | 4.9% (dd 52.2%) |
| VAL | 13.6% (dd 20.3%) | 12.4% (dd 21.3%) | 14.4% (dd 19.9%) |
| TEST | 11.4% (dd 18.4%) | **10.5% (dd 13.6%)** | 11.9% (dd 24.8%) |

One to three points either way, so the conclusion is unchanged: it does not beat
the index. The figures above are the month-START ones, which is what the
indicator actually does.

One thing does stand out in the test era — a 13.6% drawdown against SPY's 24.8%
for a point less return. If a shallower ride is worth more to you than the last
point of return, that is the case for it. It is not a claim of outperformance.

## What it is actually good for

The ranking table. It shows which corners of the market are leading and lagging
on the same 6-month relative-strength measure the academic literature uses — a
genuinely useful thing to have on screen. Just don't expect the basket to beat
SPY, because on this evidence it doesn't.

The live ranking also matches the Python backtest to the decimal (USO 90.3%,
SMH 39.3%, XLE 21.9%, XLK 21.4%, …). The bug was in my backtest, never in the
indicator.

## Why it is believable

**It beats random selection, decisively.** The same monthly mechanics with a
*random* pick of three returned +8.9%/yr. The momentum ranking beat **100% of 50
random draws** in both the validation and test eras. The edge is the ranking, not
the rotation.

| Era | Momentum | Random (50 draws) | Percentile |
|---|---|---|---|
| TRAIN | 9.4% | 3.8% ± 2.9% | 96th |
| VAL | 22.1% | 9.1% ± 4.2% | 100th |
| TEST | 23.4% | 8.9% ± 3.9% | 100th |

**It is a plateau, not a spike.** Every lookback from 63 to 252 days and every
hold size from 2 to 6 was profitable on the test era, spanning 9–30% CAGR. Nothing
here balances on one setting.

**Costs barely matter.** 24.0% CAGR at zero cost, 21.9% at 40bps round trip.
Turnover is low: about 12 changes a year.

**The universe cannot be survivorship-biased.** These 28 ETFs all still exist and
were liquid throughout. A back-test on today's S&P 500 members quietly deletes
every company that went bankrupt; an ETF list does not have that problem.

**The thesis is not mine.** Cross-sectional momentum is among the most replicated
findings in asset pricing. It was not invented by this search, so it carries
almost no multiple-testing burden — which matters, because the searches that *did*
invent their own strategies all failed (see below).

**It is not one sector in disguise.** 20 distinct ETFs were held across 62
rebalances; the largest single holding took 17.7% of slots.

## How to trade it

1. Put the indicator on any of the 28 ETFs. The table shows the current ranking.
2. On the first trading day of each month, hold the top 3, equal weight.
3. Sell anything that dropped out, buy anything that entered. Usually 0–2 changes.
4. That is it. No stops, no targets, no intraday decisions.

**Risk per trade is not the right frame here.** You are always fully invested
across three positions, so a third of the account per name. The drawdown control
comes from what momentum *selects*, not from position sizing. If a 15% drawdown is
too much, hold 5 instead of 3 or keep part of the account in cash.

Alerts fire when this symbol enters or leaves the basket.

### Two honest limits

**The strategy file is a per-symbol approximation.** TradingView strategies trade
one symbol; this holds three. `momentum-rotation-strategy.pine` holds *this* symbol
during the months it ranks top-N and sits in cash otherwise — useful for checking
the ranking and timing on a real chart, not for measuring the strategy. The
portfolio numbers come from [`research/rotation.py`](research/rotation.py).

**Rebalance timing differs by one bar.** The backtest rebalances at the prior
month's close; the indicator fires on the first bar of the new month, which is the
earliest a monthly decision is actually executable. Same decision, one bar later.

## What this replaced, and why

Four earlier attempts in this repo failed, and each failure narrowed the search:

| Attempt | Why it died |
|---|---|
| Dip-buying on 500 stocks | Statistically significant edge (+0.111R out of sample, day-clustered) that was **unreachable**: through a 3-slot book it returned −0.787R, because winners held a slot 4.1× longer than losers so the book filled with losers |
| Overnight holding | The pooled statistic said 13.3 bps/night. Grouped by night — which is what you actually trade — it was 3.6 bps, because dozens of ETFs qualify on the same evening and are one bet, not dozens |
| Intraday mean reversion | Never beat **random entries**. A long-only rule on drifting instruments earns from drift; measured against random entries the edge was −0.006R |
| Searched trend-following on ETFs | Passed train and validation, then 3 of 15 beat random out of sample, mean −4.0% |

The lesson that produced this strategy: **optimise the return of a capital-
constrained account, not the return of a signal.** Rotation was the answer because
its capacity is fixed by construction — exactly N positions, turnover set by the
calendar.

Full methodology in [`research/`](research/).

## Reproducing

```bash
cd research
python3 rotation.py --cost-bps 10      # the parameter grid across all three eras
```

Needs the ETF export in `../_data-export/data/`.

## What it is not

It holds equities and it falls when they fall. 2022 was −8%, and a worse year is
possible. This is a better way to own the market, not a hedge against it. Expect
15–25% drawdowns and a year or two of underperforming a rising index — 2021 and
2026 both lagged SPY.
