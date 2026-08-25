# Momentum Rotation

Once a month, rank 28 liquid ETFs by their 6-month return and hold the strongest
three. That is the whole strategy.

**[`indicators/momentum-rotation.pine`](indicators/momentum-rotation.pine)** — put
it on any chart and it tells you whether that symbol is currently one of the three
to hold, with the full ranking in a table.

## Results

Parameters were chosen on 2005–2021 alone. The test era was never consulted during
selection.

| Era | Strategy | SPY | maxDD | Sharpe |
|---|---|---|---|---|
| TRAIN 2005–2015 | +9.4% | +4.9% | 17.2% | 0.63 |
| VAL 2016–2021 | +22.1% | +14.4% | 15.5% | 1.49 |
| **TEST 2021–2026** | **+23.4%** | +11.9% | **14.9%** | 1.07 |

$1,000 over the test era became **$2,908**, against $1,780 for buying SPY — with
roughly half the drawdown.

### Year by year, test era

| Year | Strategy | SPY |
|---|---|---|
| 2021 | +17.6% | +28.8% |
| **2022** | **−8.2%** | **−20.3%** |
| 2023 | +27.5% | +24.1% |
| 2024 | +72.3% | +24.0% |
| 2025 | +16.6% | +16.6% |
| 2026 | +5.3% | +11.8% |

2022 is the year that matters. The index fell 20% and this fell 8%, because
relative strength rotated into energy and commodities while equities sold off.
That is where the halved drawdown comes from — not from clever exits.

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
