# Cached market data

Committed to the repo on purpose. The container this was fetched in is ephemeral,
so a cache that only exists on disk is not a cache — it is a file that disappears.

| File | Bars | Coverage | Median |
|---|---|---|---|
| `XAUUSD_d1.csv` | 2,400 | 2012-11-14 → 2022-03-04 | $1,308 |
| `XAUUSD_h4.csv` | 14,400 | 2012-10-26 → 2022-03-04 | $1,310 |
| `XAUUSD_h1.csv` | 57,600 | 2012-05-17 → 2022-03-04 | $1,316 |
| `EURUSD_d1.csv` | 2,400 | 2012-12-04 → 2022-03-04 | 1.15 |
| `USDJPY_d1.csv` | 2,400 | 2012-12-04 → 2022-03-04 | 109.34 |

EURUSD and USDJPY are controls — they answer "is this result about gold, or about
the indicator?"

## Provenance

Source: [`ejtraderLabs/historical-data`](https://github.com/ejtraderLabs/historical-data),
fetched over `raw.githubusercontent.com`. `manifest.json` records the source URL,
row count, date range, price range and a SHA256 of each normalised file.

Upstream stores prices as integers (gold ×100, EURUSD ×100000, USDJPY ×1000).
`fetch_data.py` rescales to real units, drops structurally impossible bars (high
below the body, non-positive low), and refuses to write a file whose median price
falls outside a per-symbol sanity range — so a silent format change upstream fails
loudly instead of quietly poisoning a backtest.

## The limitation that matters

**This data ends 2022-03-04.** It does not include the 2022–2026 gold regime, which
is precisely the period most people asking about gold care about. Every gold
conclusion in the parent README is a statement about 2012–2022 and nothing else.

The fix is a one-liner: export the recent range from TradingView (right-click the
chart → *Export chart data*) and run `backtest.py --csv` against it. The public
mirrors that carry fresher gold data are blocked by this environment's egress
policy — see the parent README.

## Refreshing

```bash
python3 fetch_data.py --list      # what is cached
python3 fetch_data.py --force     # re-download and re-verify
```
