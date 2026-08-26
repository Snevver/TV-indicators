# Data export

Claude's sandbox cannot reach any market-data host — Yahoo, Stooq, Binance and
the rest are all denied by the container's egress policy. It *can* read GitHub.
So the handoff is: you fetch, you push, it pulls.

```bash
pip install yfinance pandas
python export_for_claude.py
git add _data-export/data && git commit -m "data export" && git push
```

Then tell Claude it is pushed.

## What it grabs

| File | Contents |
|---|---|
| `data/etfs_daily.csv.gz` | 28 liquid ETFs, daily, 2005 → today |
| `data/sp500_daily.csv.gz` | Current S&P 500 members, daily, 2005 → today |
| `data/intraday15m_sample.csv.gz` | 60 days of 15-minute bars, 4 ETFs |

Long format throughout: `time, ticker, open, high, low, close, volume`.

## Two things to know

**The intraday file is a sample, not a backtest set.** Yahoo only serves about 60
days of 15-minute history, which is far too short to measure an edge. It is there
to confirm the intraday indicators behave correctly on current data.

**The stock list is now every historical member, not just today's.** It used to be
today's 500, which is a fantasy: running them back to 2005 asks what would have
happened if you had known in 2005 which companies would still be standing in
2026. Measured on this data, 974 tickers were in the index at some point since
2005, so that list was missing 479 of them — 49% of the real universe, and
exactly the half that went bankrupt, was acquired, or fell out.

`data/sp500_membership.csv.gz` holds monthly point-in-time membership from 2004,
derived from [fja05680/sp500](https://github.com/fja05680/sp500) (MIT). The
exporter downloads everything that list has ever contained.

**Some bias remains, and it is now a number rather than a shrug.** Yahoo drops
most companies that went bankrupt, so their prices cannot be fetched at all. The
exporter writes `data/missing_tickers.txt` naming every one it could not get, so
the size of the remaining gap is visible instead of assumed.

To use it honestly, a backtest must rank only the names that were in the index
in the month being tested — the membership file is what makes that possible.
