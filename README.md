# Stock momentum

One strategy, traded live, with the code that measured it and the machine that
runs it.

Monthly cross-sectional momentum across 40 US mega-caps: rank by six-month return
ending a month ago, hold the top eight, re-rank on the first trading day of each
month.

| Folder | What it is |
|---|---|
| [`stock-momentum/bot/`](stock-momentum/bot/) | The live bot. Runs daily on a mini PC, posts each rebalance to Discord, keeps its own book, optionally reads Trading 212 |
| [`stock-momentum/web/`](stock-momentum/web/) | A local dashboard on that machine — holdings, curves, settings |
| [`stock-momentum/research/`](stock-momentum/research/) | The backtests behind every number quoted anywhere here |
| [`stock-momentum/indicators/`](stock-momentum/indicators/) | The TradingView Pine version. The bot does not depend on it |
| [`_data-export/`](_data-export/) | Daily OHLCV export the research scripts read |

Start with [`stock-momentum/README.md`](stock-momentum/README.md) for what it does
and what it measured, or [`HOW-TO-TRADE.md`](stock-momentum/HOW-TO-TRADE.md) for
the monthly routine.

## House rules

**Measured results, or it does not ship.** A rule that has never been backtested
against costs is a hypothesis. `research/` carries the code that produced every
figure, so any claim here can be re-run rather than taken on trust.

**Results quoted are out-of-sample**, from slices held back from the search.
Anything can be made to look good on the data it was tuned on.

**Every number is flattered by one thing that cannot be fixed.** The forty-name
universe was chosen in 2026, so the whole history knows which companies survived.
The index is the only honest benchmark on the page.

**No secrets in git.** The Discord webhook, the Trading 212 key and the dashboard
password live in mode-600 files on the machine that runs the bot, never here.
`state.json`, `history.csv` and the rest of the local run state are gitignored for
the same reason: they are that machine's, not the repo's.

**No large price data in git.** Daily CSVs are kept because the research needs
them; intraday bars run to hundreds of megabytes and are rebuildable from
`_data-export/export_for_claude.py`.

## History

This repo used to hold four indicators. The other three — an ETF rotation, a
wickless-candle retest, and a mean-reversion family — were removed once this one
was the only one being traded. They are still in the git history if they are ever
wanted back.
