#!/usr/bin/env python3
"""Build 5-minute and 15-minute bars from 1-minute sources.

Handles both layouts in FutureSharks/financial-data:

  HistData  DAT_ASCII_<SYM>_M1_<year>.csv, semicolon separated, no header,
            `YYYYMMDD HHMMSS;o;h;l;c;v`
  Oanda     <year>/oanda-<SYM>-<year>-<month>.csv, comma separated, WITH header,
            `time,close,high,low,open,volume` — note the column order

The 1-minute source is ~5.7GB and is not kept in this repo. Rebuild with:

    GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 \\
        https://github.com/FutureSharks/financial-data /tmp/findata
    python3 build_intraday.py --all /tmp/findata/pyfinancialdata/data
    rm -rf /tmp/findata
"""
from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime

TIMEFRAMES = {"m5": 5, "m15": 15}
HERE = os.path.dirname(os.path.abspath(__file__))

# Liquid, tradeable, and diverse enough that a result on one is not a result on
# all of them. Names are (subpath, output symbol).
BASKET = [
    ("currencies/oanda/SPX500_USD", "SPX500"),
    ("currencies/oanda/NAS100_USD", "NAS100"),
    ("currencies/oanda/US2000_USD", "US2000"),
    ("currencies/oanda/XAU_USD",    "XAUUSD"),
    ("currencies/oanda/JP225_USD",  "JP225"),
    ("currencies/oanda/EUR_USD",    "EURUSD"),
    ("currencies/oanda/GBP_USD",    "GBPUSD"),
    ("currencies/oanda/WTICO_USD",  "WTI"),
]


def parse_histdata(path):
    out = []
    with open(path) as fh:
        for ln in fh:
            parts = ln.strip().split(";")
            if len(parts) < 5:
                continue
            try:
                dt = datetime.strptime(parts[0], "%Y%m%d %H%M%S")
                o, h, l, c = map(float, parts[1:5])
                v = float(parts[5]) if len(parts) > 5 else 0.0
            except (ValueError, IndexError):
                continue
            out.append((dt, o, h, l, c, v))
    return out


def parse_oanda(path):
    out = []
    with open(path) as fh:
        header = fh.readline().strip().split(",")
        try:
            it, ic, ih, il, io = (header.index("time"), header.index("close"),
                                  header.index("high"), header.index("low"),
                                  header.index("open"))
            iv = header.index("volume") if "volume" in header else None
        except ValueError:
            return out
        for ln in fh:
            parts = ln.strip().split(",")
            if len(parts) <= max(it, ic, ih, il, io):
                continue
            try:
                dt = datetime.strptime(parts[it], "%Y-%m-%d %H:%M:%S")
                o, h, l, c = (float(parts[io]), float(parts[ih]),
                              float(parts[il]), float(parts[ic]))
                v = float(parts[iv]) if iv is not None and parts[iv] else 0.0
            except (ValueError, IndexError):
                continue
            out.append((dt, o, h, l, c, v))
    return out


def load_tree(directory: str):
    files = sorted(glob.glob(os.path.join(directory, "**", "*.csv"), recursive=True))
    rows = []
    for path in files:
        base = os.path.basename(path)
        chunk = parse_histdata(path) if base.startswith("DAT_ASCII") else parse_oanda(path)
        rows.extend(chunk)
    # Drop structurally impossible bars rather than trusting the source.
    rows = [r for r in rows if r[3] > 0 and r[2] >= max(r[1], r[4]) and r[3] <= min(r[1], r[4])]
    rows.sort(key=lambda r: r[0])
    return rows


def resample(rows, minutes: int):
    """Fixed buckets. An empty bucket is omitted, never forward-filled — a
    synthetic bar would invent a high and a low that nobody could have traded."""
    out, cur, stamp = [], None, None
    o = h = l = c = None
    v = 0.0
    for dt, ro, rh, rl, rc, rv in rows:
        key = (dt.toordinal(), (dt.hour * 60 + dt.minute) // minutes)
        if key != cur:
            if cur is not None:
                out.append((stamp, o, h, l, c, v))
            cur = key
            o, h, l, c, v = ro, rh, rl, rc, rv
            bm = ((dt.hour * 60 + dt.minute) // minutes) * minutes
            stamp = dt.replace(hour=bm // 60, minute=bm % 60, second=0, microsecond=0)
        else:
            h, l, c = max(h, rh), min(l, rl), rc
            v += rv
    if cur is not None:
        out.append((stamp, o, h, l, c, v))
    return out


def write(symbol: str, tf: str, bars) -> str:
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    path = os.path.join(HERE, "data", f"{symbol}_{tf}.csv")
    with open(path, "w") as fh:
        fh.write("time,open,high,low,close,volume\n")
        for dt, o, h, l, c, v in bars:
            fh.write(f"{dt:%Y-%m-%d %H:%M:%S},{o:.5f},{h:.5f},{l:.5f},{c:.5f},{v:.0f}\n")
    return path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("root", help="path to pyfinancialdata/data")
    p.add_argument("--all", action="store_true", help="build the whole basket")
    p.add_argument("--symbol", help="one subpath, e.g. currencies/oanda/XAU_USD")
    p.add_argument("--name", help="output symbol name when using --symbol")
    p.add_argument("--since", default="2010", help="ignore bars before this year")
    args = p.parse_args()

    targets = BASKET if args.all else [(args.symbol, args.name or "OUT")]
    cutoff = datetime(int(args.since), 1, 1)

    for sub, name in targets:
        directory = os.path.join(args.root, sub)
        if not os.path.isdir(directory):
            print(f"  MISSING {sub}")
            continue
        rows = [r for r in load_tree(directory) if r[0] >= cutoff]
        if not rows:
            print(f"  {name}: no usable rows")
            continue
        line = f"  {name:<8} {len(rows):>9} m1 bars  {rows[0][0]:%Y-%m-%d} → {rows[-1][0]:%Y-%m-%d}"
        for tf, minutes in TIMEFRAMES.items():
            bars = resample(rows, minutes)
            path = write(name, tf, bars)
            line += f"  |  {tf}: {len(bars):>7} ({os.path.getsize(path)/1e6:.0f}MB)"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
