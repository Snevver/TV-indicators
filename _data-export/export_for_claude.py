#!/usr/bin/env python3
"""Run this on YOUR machine. It fetches data Claude's sandbox cannot reach.

Claude runs in a cloud container whose network policy blocks Yahoo, Stooq and
every other market-data host. It can read GitHub, so the handoff is: you fetch,
you push, it pulls.

    pip install yfinance pandas
    python export_for_claude.py
    git add data && git commit -m "data export" && git push

Takes a few minutes and writes ~25MB. Everything lands in ./data as gzipped CSV.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    sys.exit("pip install yfinance pandas")

START = "2005-01-01"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BATCH = 100

# Liquid ETFs first: index exposure, sectors, bonds, commodities, volatility.
# These matter more than individual names — they are what a broad-market
# strategy would actually trade, and they have clean long histories.
ETFS = ["SPY", "QQQ", "IWM", "DIA", "MDY", "EFA", "EEM", "TLT", "IEF", "HYG",
        "LQD", "GLD", "SLV", "USO", "XLE", "XLF", "XLK", "XLV", "XLI", "XLP",
        "XLY", "XLU", "XLB", "XLRE", "XBI", "SMH", "KRE", "VNQ"]

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def sp500():
    try:
        req = urllib.request.Request(SP500_URL, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode()
        syms = pd.read_html(io.StringIO(html))[0]["Symbol"].tolist()
        return [s.replace(".", "-") for s in syms]
    except Exception as exc:
        print(f"  ! constituent list failed ({exc}); ETFs only")
        return []


def grab(tickers, label):
    """Download in batches, return one long-format frame."""
    frames = []
    for k in range(0, len(tickers), BATCH):
        chunk = tickers[k:k + BATCH]
        print(f"  {label}: {k + 1}-{k + len(chunk)} of {len(tickers)}")
        raw = yf.download(chunk, start=START, group_by="ticker", progress=False,
                          threads=True, auto_adjust=False)
        for t in chunk:
            try:
                sub = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                sub = sub.dropna(how="all")
            except (KeyError, ValueError):
                continue
            if len(sub) < 250:
                continue
            df = sub.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            df.columns = ["time", "open", "high", "low", "close", "volume"]
            df.insert(1, "ticker", t)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else None


def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    etf = grab(ETFS, "ETFs")
    if etf is not None:
        p = os.path.join(OUT, "etfs_daily.csv.gz")
        etf.to_csv(p, index=False, compression="gzip")
        print(f"  wrote {p}  ({len(etf):,} rows, "
              f"{os.path.getsize(p)/1e6:.1f}MB, "
              f"{etf.ticker.nunique()} tickers, {etf.time.min()} → {etf.time.max()})")

    syms = sp500()
    if syms:
        stk = grab(syms, "S&P 500")
        if stk is not None:
            p = os.path.join(OUT, "sp500_daily.csv.gz")
            stk.to_csv(p, index=False, compression="gzip")
            print(f"  wrote {p}  ({len(stk):,} rows, "
                  f"{os.path.getsize(p)/1e6:.1f}MB, "
                  f"{stk.ticker.nunique()} tickers, {stk.time.min()} → {stk.time.max()})")

    # yfinance only serves ~60 days of 15-minute bars, so this is a live-check
    # sample rather than a backtest set — useful for confirming the intraday
    # indicators behave on current data, not for measuring an edge.
    try:
        print("  intraday sample (60 days, 15m)")
        intr = yf.download(["SPY", "QQQ", "IWM", "GLD"], period="60d",
                           interval="15m", group_by="ticker", progress=False,
                           auto_adjust=False)
        frames = []
        for t in ["SPY", "QQQ", "IWM", "GLD"]:
            sub = intr[t].dropna(how="all")
            df = sub.reset_index()
            df.columns = ["time", "open", "high", "low", "close", "adj", "volume"][:len(df.columns)]
            df = df[["time", "open", "high", "low", "close", "volume"]]
            df.insert(1, "ticker", t)
            frames.append(df)
        sample = pd.concat(frames, ignore_index=True)
        p = os.path.join(OUT, "intraday15m_sample.csv.gz")
        sample.to_csv(p, index=False, compression="gzip")
        print(f"  wrote {p}  ({len(sample):,} rows)")
    except Exception as exc:
        print(f"  ! intraday sample skipped ({exc})")

    print("\nNow push it:")
    print("  git add _data-export/data && git commit -m 'data export' && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
