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
MEMBERSHIP = os.path.join(OUT, "sp500_membership.csv.gz")


def sp500():
    """Every ticker that was in the index at ANY point, not just today's members.

    THIS IS THE DIFFERENCE BETWEEN A BACKTEST AND A FANTASY. Downloading today's
    500 names and running them back to 2005 asks what would have happened if you
    had known, in 2005, which companies would still be standing in 2026. Measured
    on this data: 974 tickers were in the index at some point since 2005, so the
    old list was missing 479 of them -- 49% of the real universe, and precisely
    the half that went bankrupt, got acquired or fell out.

    The membership file lists them all, so the ones that died are at least
    downloaded and the strategy can be ranked against what actually existed each
    month.

    Yahoo will not have prices for all of them: a company that went bankrupt is
    usually gone from its API entirely. That is fine and expected -- what matters
    is that the gap is reported rather than hidden, so the remaining bias is a
    number instead of a shrug.
    """
    ever = set()
    try:
        m = pd.read_csv(MEMBERSHIP)
        for row in m["tickers"]:
            ever |= {t.strip() for t in str(row).split(",") if t.strip()}
        print(f"  membership file: {len(ever)} tickers ever in the index "
              f"({len(m)} monthly snapshots)")
    except Exception as exc:
        print(f"  ! membership file unreadable ({exc})")

    try:
        req = urllib.request.Request(SP500_URL, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode()
        today = set(pd.read_html(io.StringIO(html))[0]["Symbol"].tolist())
        print(f"  today's members: {len(today)}")
        ever |= today
    except Exception as exc:
        print(f"  ! current constituent list failed ({exc})")

    if not ever:
        print("  ! no ticker list at all; ETFs only")
        return []
    # Yahoo spells share classes with a dash: BRK.B is BRK-B.
    return sorted(t.replace(".", "-") for t in ever)


def retry_singly(missing, label, pause=1.5):
    """Try the failures one at a time, slowly.

    A batch failure is ambiguous. "no timezone found" is what Yahoo says both for
    a company that no longer exists and for a request it declined because too
    many arrived at once -- and the second kind comes back if you ask politely,
    one at a time. Separating them matters: it decides whether a name is a real
    hole in the data or just an impatient download.
    """
    import time
    frames, still = [], []
    for i, t in enumerate(missing, 1):
        if i % 25 == 0:
            print(f"  {label} retry: {i} of {len(missing)}")
        try:
            raw = yf.download(t, start=START, progress=False, threads=False,
                              auto_adjust=False)
        except Exception:                                  # noqa: BLE001
            raw = None
        if raw is None or raw.empty:
            still.append(t)
            time.sleep(pause)
            continue
        df = raw.reset_index()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.rename(columns={"Date": "time", "Open": "open", "High": "high",
                                "Low": "low", "Close": "close", "Volume": "volume"})
        df.insert(1, "ticker", t)
        frames.append(df[["time", "ticker", "open", "high", "low", "close", "volume"]])
        time.sleep(pause)
    print(f"  {label} retry: recovered {len(frames)}, still missing {len(still)}")
    return (pd.concat(frames, ignore_index=True) if frames else None), still


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
            got = set(stk.ticker.unique())
            want = set(syms)
            gone = sorted(want - got)
            if gone:
                print(f"  {len(gone)} failed in batches; retrying one at a time")
                extra, gone = retry_singly(gone, "S&P 500")
                if extra is not None:
                    stk = pd.concat([stk, extra], ignore_index=True)
                    got = set(stk.ticker.unique())
            print(f"  coverage: {len(got)}/{len(want)} tickers returned data; "
                  f"{len(gone)} had none (delisted, or renamed)")
            if gone:
                with open(os.path.join(OUT, "missing_tickers.txt"), "w") as fh:
                    fh.write("\n".join(gone) + "\n")
                print(f"  wrote data/missing_tickers.txt — the remaining bias, "
                      f"named rather than hidden")
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
