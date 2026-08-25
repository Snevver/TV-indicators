# Backtesting ZeroStar Alpha V2

Two ways to find out whether the signals make money.

| | What it is | Data | Who runs it |
|---|---|---|---|
| **`strategy()` port** | [`../indicators/zerostar-alpha-v2-strategy.pine`](../indicators/zerostar-alpha-v2-strategy.pine) | TradingView's real history | You, in the Strategy Tester |
| **Python backtester** | `engine.py` + `backtest.py` | Any OHLCV CSV | You, locally — or here |

Gold history is already cached in [`data/`](data/) — jump to
[Gold: the actual result](#gold-the-actual-result) for what it says.

The Pine strategy is the authoritative answer for a given symbol, because it uses
TradingView's own data. The Python version exists because it can do things the
Strategy Tester can't: sweep hundreds of parameter sets in seconds, run controls
against synthetic data, and dump every trade to CSV.

Both fill entries at the **open of the bar after the signal**, never at the signal
bar's own close. That one detail is the difference between an honest backtest and
a flattering one.

## TradingView Strategy Tester

1. Pine Editor → paste `zerostar-alpha-v2-strategy.pine` → **Add to chart**.
2. Open **Properties** and set commission and slippage for *your* broker. The
   defaults (0.04% commission, 2 ticks slippage) are a crypto-ish placeholder.
3. Read the **Performance Summary** tab — net profit, profit factor, max drawdown.
4. Check the **List of Trades** tab for the trade count. Under ~100 trades, the
   numbers are anecdotes.

## Python backtester

No dependencies — standard library only, Python 3.9+.

```bash
cd backtest

# Your own data: TradingView chart → right-click → Export chart data → CSV
python3 backtest.py --csv ~/Downloads/BTCUSD_60.csv

# Real costs, and a per-trade log to inspect
python3 backtest.py --csv data.csv --fee-bps 5 --slippage-bps 5 --trades-csv trades.csv

# How sensitive is it to the settings?
python3 backtest.py --csv data.csv --sweep

# No data handy? Generate a market with no edge in it.
python3 backtest.py --synthetic random --bars 30000 --seed 7

# Cached gold, and the two tests that actually matter
python3 fetch_data.py --list
python3 backtest.py --csv data/XAUUSD_h1.csv --stability 0.3 --rsi-index 60 --gap 3
python3 backtest.py --csv data/XAUUSD_h1.csv --sweep --walk-forward --min-trades 40
```

`--walk-forward` optimises on the first 70% of the bars and trades the winners on the
remaining 30%, which they have never seen. It is the only test in this repo that can
tell a real edge from a lucky fit.

Column names are matched case-insensitively (`time`/`date`, `open`, `high`, `low`,
`close`, `volume`), newest-first files are reversed automatically, and partial rows
are skipped.

### Reading the output

Results are in **R-multiples**: 1R is the distance from entry to stop, so +2R means
the trade made twice what it risked. This makes results comparable across symbols
and volatility regimes in a way that raw percentages are not.

| Metric | What it tells you |
|---|---|
| **Expectancy** | Average R per trade. The single number that matters — positive means an edge, after costs |
| **Profit factor** | Gross wins ÷ gross losses. Below 1.0 loses money |
| **Total R** | Expectancy × trades: the size of the edge, not just its sign |
| **t-statistic** | Whether the edge could just be luck. Below \|2\|, you cannot tell it from noise |
| **Max drawdown** | Worst peak-to-trough on the compounded equity curve |
| **Buy & hold** | The benchmark you have to beat to justify any of this |

`--fill close` reproduces the indicator's own on-chart win-rate table. Expect it to
look better than `--fill open`; the gap between them is roughly what one bar of
hindsight is worth.

## Validation

`./validate.sh` runs four cases whose correct answers are known in advance. Results
from this repo (30,000 bars, `--stability 0.3 --rsi-index 60 --gap 3`, 2bps fee +
2bps slippage):

| Control | Expectancy | Profit factor | Correct? |
|---|---|---|---|
| Random walk (no edge exists) | **-0.037R** | 0.950 | ✅ break-even minus costs |
| Mean-reverting market | **+0.159R** | 1.245 | ✅ finds the edge that is there |
| Trending market, counter-trend mode | **-0.240R** | 0.695 | ✅ bleeds, as it must |
| Random walk, zero costs | **+0.025R** | — | ✅ isolates cost drag |

The first and fourth rows together are the important pair: a simulator that shows a
profit on a random walk has a look-ahead bug. This one shows +0.025R gross decaying
to -0.037R net, which is a cost drag of ~0.06R per trade and nothing else.

The second row proves the reverse — the engine is not blind. When an edge genuinely
exists in the data, it finds it.

## Gold: the actual result

Cached gold history is in [`data/`](data/) — 2,400 daily / 14,400 4-hour / 57,600
hourly XAUUSD bars covering **2012-11 → 2022-03**. Fetch or refresh with
`python3 fetch_data.py`; reproduce everything below with `./gold.sh`.

### First finding: the default settings barely fire

| Timeframe | Bars | Signals | Trades |
|---|---|---|---|
| Daily | 2,400 (9.3 years) | **1** | 1 |
| 4-hour | 14,400 | 7 | 7 |
| Hourly | 57,600 | 27 | 27 |

One signal in nine years of daily gold. The stock defaults are not a strategy, they
are a filter that rejects almost everything. Any conclusion about them is untestable.

### Second finding: loosened enough to measure, it loses

Settings `--stability 0.3 --rsi-index 60 --gap 3`, 2bps fee + 2bps slippage per side:

| Symbol | Trades | Win rate | Expectancy | Profit factor |
|---|---|---|---|---|
| **Gold daily** | 12 | 16.7% | **-0.568R** | 0.37 |
| **Gold 4-hour** | 60 | 33.3% | **-0.241R** | 0.72 |
| **Gold hourly** | 243 | 30.9% | **-0.454R** | 0.54 |

The hourly sample is the only one large enough to trust, and it is damning:
**-110R total, a 68.8% max drawdown, and t = -4.86.** That t-statistic means the
losses are *not* bad luck — a result that extreme happens by chance roughly once in
a million. Buy-and-hold returned +26.8% over the same window.

Two details worth noticing. The average loss is **-1.41R against a 1.0R stop** —
gold gaps through stops, so the risk taken is systematically larger than the risk
planned. And longs and shorts lose about equally (-58R / -52R), so this is not a
directional bias that a filter could fix.

### Third finding: gold is worse than random noise

Sweeping 176 parameter sets on gold hourly, **4 were profitable (2.3%)**. The same
sweep on synthetic data with no edge in it at all returned **31% profitable**.

Being beaten by a random number generator is the strongest evidence in this
document. It says the losses are structural: gold in this period trended through
the exact RSI extremes the indicator fades.

### Fourth finding: the survivors do not survive

Optimising on 2012–2019 and trading the ten best settings on 2019–2022, unseen:

```
 stab  rsi  dlt   tp | IS trades    IS exp | OOS trades   OOS exp  OOS totalR  OOS PF
  0.6   65    3  3.0 |        31   +0.2031 |         17   -0.4193       -7.13    0.60
  0.7   60    3  3.0 |        39   +0.1911 |         16   +0.1605       +2.57    1.19
  0.3   70    6  3.0 |        45   +0.1812 |         14   -0.4483       -6.28    0.56
```

Mean out-of-sample expectancy: **-0.2325R**. Every in-sample edge evaporated.

### Verdict

On 2012–2022 gold, this indicator **loses money on every timeframe tested, at every
parameter set worth trusting**. Not "unproven" — measurably negative, with
significance. Do not trade it on gold as it stands.

That is a real answer, and a cheap one to have found before risking money. If you
want it to work on gold, the honest next step is to change the *thesis* — gold
trends, so a trend-following variant (`--trend --trend-mode "With trend"`) is a
different bet than fading extremes, and needs testing on its own.

## The overfitting warning

`--sweep` on 20,000 bars of **provably edge-free random walk** tested 168 parameter
sets. **52 of them (31%) were profitable.** The best looked like this:

```
 stab  rsi  delta    tp |  trades    win%  expectancy    totalR     PF  maxDD%
  0.3   70      4   3.0 |      25   44.0%     +0.6273     +15.7   1.94     6.0
```

+0.63R expectancy, a 1.94 profit factor, a 6% drawdown — on data generated by a
random number generator, containing no edge of any kind, by construction.

That row is what a curve-fit looks like from the inside. If you sweep parameters on
your own data and post the winner, you have most likely found this. Judge the whole
table: a robust setting sits in a broad neighbourhood of profitable ones, not on a
lonely spike. Then confirm it on data you did not sweep over.

## What none of this includes

Funding rates, borrow costs for shorts, partial fills, exchange downtime, and the
survivorship bias in whichever symbol you chose to test because you already knew it
went up. A backtest is the best case. Trade it accordingly.
