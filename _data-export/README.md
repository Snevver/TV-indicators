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

**The stock list is today's members**, so it carries survivorship bias — companies
that went bankrupt or dropped out are missing, which flatters any long-only
result. The ETF file does not have this problem, which is why it comes first.
