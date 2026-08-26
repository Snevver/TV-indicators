#!/usr/bin/env python3
"""How much of the real S&P 500 can we actually price, year by year?

Every backtest here rests on this table, so it belongs in the repo rather than in
a chat log.

The gap is not random and it is not evenly spread. Yahoo removes a company when
it stops trading, so the names missing from the price export are the ones that
failed -- and the further back you look, the more of them there are, because more
time has passed for them to fail in. The result is that the EARLY years are the
most flattered, and 2008 is the worst affected of all.

Nothing here fixes that. It measures it, so any number quoted from a backtest can
be quoted with its coverage attached.

    python3 coverage.py
"""
from __future__ import annotations

import os
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "_data-export", "data")
PRICES = os.path.join(DATA, "sp500_daily.csv.gz")
MEMBERS = os.path.join(DATA, "sp500_membership.csv.gz")


def main() -> int:
    for p in (PRICES, MEMBERS):
        if not os.path.exists(p):
            sys.exit(f"missing {p} — see _data-export/README.md")

    px = pd.read_csv(PRICES, usecols=["time", "ticker"])
    px["time"] = pd.to_datetime(px["time"])
    mem = pd.read_csv(MEMBERS)
    mem["date"] = pd.to_datetime(mem["date"])

    # Membership starts in 2004 and prices in 2005, so the first year would
    # otherwise report 0% coverage and be crowned the worst -- an artefact of
    # where the files begin, not a hole in the data.
    first = px.time.min().year
    mem = mem[mem.date.dt.year >= first]

    print("How much of the real index we can price, by year\n")
    print(f"{'year':<6} {'priced':>7} {'in index':>9} {'coverage':>9}")
    worst = (None, 101.0)
    for year in sorted(mem.date.dt.year.unique()):
        snap = mem[mem.date.dt.year == year]
        if snap.empty:
            continue
        want = {t.strip() for t in str(snap.tickers.iloc[0]).split(",") if t.strip()}
        got = set(px[px.time.dt.year == year].ticker.unique())
        if not want:
            continue
        pct = len(want & got) / len(want) * 100
        if pct < worst[1]:
            worst = (year, pct)
        if year % 3 == 0 or year == max(mem.date.dt.year):
            print(f"{year:<6} {len(want & got):>7} {len(want):>9} {pct:>8.0f}%  "
                  + "#" * int(pct / 5))

    print(f"\nThinnest year: {worst[0]} at {worst[1]:.0f}% of the index priced.")
    print("\nThe missing names are the ones that stopped trading, so a backtest\n"
          "never has to hold anything that went to zero. Returns are flattered,\n"
          "and drawdowns more so -- most of all in the earliest years.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
