#!/usr/bin/env python3
"""Fill the holes Yahoo leaves, using EODHD.

Yahoo removes a company when it stops trading, which is exactly backwards for a
backtest: the names it drops are the failures. After two Yahoo passes, 301 of 992
historical S&P 500 members were still missing here -- among them Lehman,
Washington Mutual, Bear Stearns, Merrill, Countrywide, old GM and Kodak. A
backtest that cannot see those is a backtest where nothing was allowed to go to
zero.

EODHD keeps delisted symbols. This asks it for whatever is still missing and
MERGES the result into the existing export, so the 691 tickers already fetched
are not touched.

    export EODHD_API_KEY=...            # never written to a file, never committed
    python3 fetch_missing_eodhd.py

Run it again freely: it re-reads what is missing each time, so an interrupted run
just resumes.

THE KEY IS A PASSWORD. It goes in the environment for one command and nowhere
else. If it has ever been pasted somewhere it should not be, rotate it on the
EODHD dashboard -- that costs nothing and removes the problem entirely.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
PRICES = os.path.join(OUT, "sp500_daily.csv.gz")
MISSING = os.path.join(OUT, "missing_tickers.txt")
START = "2005-01-01"
PAUSE = 0.15                      # polite; EODHD allows far more than this
EOD = "https://eodhd.com/api/eod/{sym}.US"

KEY = os.environ.get("EODHD_API_KEY", "").strip()


def one(ticker: str):
    """One symbol's daily history, or None. Never raises."""
    q = urllib.parse.urlencode({"api_token": KEY, "fmt": "json", "from": START,
                                "period": "d", "order": "a"})
    url = f"{EOD.format(sym=urllib.parse.quote(ticker))}?{q}"
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as exc:
        # 402/429 mean the plan or the day's quota is spent. That is not a
        # missing ticker, and treating it as one would quietly shrink the
        # universe -- so it stops the run instead.
        if exc.code in (401, 402, 403, 429):
            raise SystemExit(
                f"\nEODHD returned {exc.code} on {ticker}. That is an auth or "
                f"quota answer, not a missing symbol.\n"
                f"Check the key and the plan's daily allowance, then run again — "
                f"it resumes where it stopped.")
        return None
    except Exception:                                      # noqa: BLE001
        return None
    try:
        rows = json.loads(body)
    except ValueError:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    df = pd.DataFrame(rows)
    if "date" not in df or "close" not in df:
        return None
    df = df.rename(columns={"date": "time", "adjusted_close": "adj"})
    for c in ("open", "high", "low", "close", "volume"):
        if c not in df:
            df[c] = 0
    df.insert(1, "ticker", ticker)
    # Same three columns as the main export: anything wider re-inflates the file
    # past GitHub's limit the moment it is merged.
    df["close"] = pd.to_numeric(df["close"], errors="coerce").round(4)
    return df[["time", "ticker", "close"]]


def main() -> int:
    if not KEY:
        sys.exit("set EODHD_API_KEY first:  export EODHD_API_KEY=...")
    if not os.path.exists(MISSING):
        sys.exit(f"no {MISSING} — run export_for_claude.py first")

    want = [l.strip() for l in open(MISSING) if l.strip()]
    print(f"{len(want)} tickers to try")

    got, still, frames = 0, [], []
    for i, t in enumerate(want, 1):
        df = one(t)
        if df is None or df.empty:
            still.append(t)
        else:
            frames.append(df)
            got += 1
        if i % 25 == 0:
            print(f"  {i} of {len(want)} — recovered {got}")
        time.sleep(PAUSE)

    print(f"\nrecovered {got}, still missing {len(still)}")
    if not frames:
        print("nothing to merge.")
        return 1

    new = pd.concat(frames, ignore_index=True)
    old = pd.read_csv(PRICES)
    before = old.ticker.nunique()
    merged = pd.concat([old, new], ignore_index=True)
    # A ticker fetched twice would double every row and silently double its
    # weight in any average. Keep the first of each date/ticker pair.
    merged = merged.drop_duplicates(subset=["time", "ticker"], keep="first")
    merged = merged.sort_values(["ticker", "time"])
    merged.to_csv(PRICES, index=False, compression="gzip")
    print(f"{PRICES}: {before} -> {merged.ticker.nunique()} tickers, "
          f"{len(merged):,} rows, {os.path.getsize(PRICES)/1e6:.1f}MB")

    with open(MISSING, "w") as fh:
        fh.write("\n".join(still) + ("\n" if still else ""))
    print(f"{MISSING}: now {len(still)} names — what remains unavailable")
    print("\nNow push it:\n  git add _data-export/data && "
          "git commit -m 'fill gaps from eodhd' && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
