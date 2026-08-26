#!/usr/bin/env python3
"""Ask EODHD which US symbols it actually has, including delisted ones.

Only 21 of 301 missing names resolved when asked for by ticker, which is too few
for a provider that sells delisted coverage. The likely reason is that we are
asking with the wrong symbols: our missing list comes from index membership data
and uses post-bankruptcy pink-sheet tickers -- LEHMQ, MTLQQ, EKDKQ, WAMUQ -- the
Q-suffixed codes assigned after Chapter 11. Lehman traded as LEH, old GM as GM,
Kodak as EK.

So rather than guessing at symbols, this pulls the provider's own list of US
symbols and saves it. Matching our gaps against real codes and names is then a
lookup instead of a hunch.

    export EODHD_API_KEY=...
    python3 fetch_delisted_list.py

Writes data/eodhd_us_symbols.csv.gz (live) and data/eodhd_us_delisted.csv.gz.
Two API calls. The key is read from the environment and never written down.
"""
import gzip, json, os, sys, urllib.parse, urllib.request

try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
KEY = os.environ.get("EODHD_API_KEY", "").strip()
URL = "https://eodhd.com/api/exchange-symbol-list/US"


def pull(delisted: bool):
    q = {"api_token": KEY, "fmt": "json"}
    if delisted:
        q["delisted"] = "1"
    try:
        with urllib.request.urlopen(f"{URL}?{urllib.parse.urlencode(q)}",
                                    timeout=120) as r:
            rows = json.loads(r.read().decode())
    except Exception as exc:                               # noqa: BLE001
        print(f"  ! {'delisted' if delisted else 'live'} list failed: {exc}")
        return None
    if not isinstance(rows, list) or not rows:
        print(f"  ! {'delisted' if delisted else 'live'} list came back empty")
        return None
    return pd.DataFrame(rows)


def main() -> int:
    if not KEY:
        sys.exit("set EODHD_API_KEY first")
    for delisted, name in ((False, "eodhd_us_symbols"), (True, "eodhd_us_delisted")):
        df = pull(delisted)
        if df is None:
            continue
        p = os.path.join(OUT, name + ".csv.gz")
        df.to_csv(p, index=False, compression="gzip")
        print(f"  wrote {p}  ({len(df):,} symbols, "
              f"columns: {', '.join(df.columns[:6])})")
    print("\nNow push it:\n  git add _data-export/data && "
          "git commit -m 'eodhd symbol lists' && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
