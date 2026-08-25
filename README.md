# TV-Indicators

TradingView indicators, one folder each. Every folder is self-contained: the Pine
scripts, the research that produced them, and the numbers they actually achieved.

| Folder | What it is | Status |
|---|---|---|
| [`zerostar-mean-reversion/`](zerostar-mean-reversion/) | Intraday and daily mean-reversion signal indicators, v2 → v5 | **v4 is the one to use** |
| [`stock-momentum/`](stock-momentum/) | Monthly momentum across 40 mega-caps, hold top 8 | **Best in the repo** — beat SPY on return and Sharpe in all three eras |
| [`momentum-rotation/`](momentum-rotation/) | Monthly ETF rotation on 6-month relative strength | Ranking tool. Beats a random ETF pick by ~3%/yr but does **not** beat buying SPY |
| [`wickless-retest/`](wickless-retest/) | Wickless-candle levels and retest alerts | Marking tool — the rules did not pass a backtest |

## House rules

**Every indicator ships with its measured results, or it does not ship.** A Pine
script that has never been backtested against costs is a hypothesis, not an
indicator. Each folder carries the backtest that produced its numbers so any claim
can be re-run.

**Results quoted are out-of-sample.** Anything can be made to look good on the data
it was tuned on. The numbers in these READMEs come from slices held back from the
search — see each folder's `research/FINDINGS.md` for the method.

**No price data in git.** Daily CSVs are small enough to keep; intraday bars run to
hundreds of megabytes and are rebuildable from the fetch scripts. `.gitignore`
enforces this.

## Adding a new indicator

```
your-indicator-name/
├── README.md            what it does, and what it measured
├── indicators/          the .pine files (indicator + strategy twin)
└── research/            backtest code, data, findings
```

Copying `zerostar-mean-reversion/research/` is a reasonable starting point — the
backtester there is dependency-free and reads any OHLCV CSV.
