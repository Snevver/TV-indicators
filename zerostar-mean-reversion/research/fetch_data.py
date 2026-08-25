#!/usr/bin/env python3
"""Download and cache gold (and other) OHLC history for the backtester.

The cache lives in backtest/data/ and is committed to the repo on purpose: this
session's container is ephemeral, so an uncommitted cache is no cache at all.

  python3 fetch_data.py                 # fetch anything missing
  python3 fetch_data.py --force         # re-download everything
  python3 fetch_data.py --list          # show what is cached

Every file is written with a manifest entry recording the source URL, the SHA256
of the normalised file, the row count and the date range, so you can tell where a
number came from six months from now.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MANIFEST = os.path.join(DATA, "manifest.json")

BASE = "https://raw.githubusercontent.com/ejtraderLabs/historical-data/main"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    scale: float          # divide raw prices by this
    sane_low: float       # post-scaling sanity bounds, so a silent format
    sane_high: float      # change upstream fails loudly instead of quietly
    date_fmt: Optional[str] = None   # strptime format if dates are not ISO


# Upstream carries these 12 symbols. Scale divisors and sanity ranges differ per
# quote currency, so they are declared rather than guessed.
_FX = {
    "AUDJPY": (1_000.0, 50, 150),
    "AUDUSD": (100_000.0, 0.4, 1.3),
    "EURCHF": (100_000.0, 0.8, 1.8),
    "EURGBP": (100_000.0, 0.5, 1.2),
    "EURJPY": (1_000.0, 90, 200),
    "EURUSD": (100_000.0, 0.5, 2.0),
    "GBPJPY": (1_000.0, 100, 250),
    "GBPUSD": (100_000.0, 0.9, 2.5),
    "USDCAD": (100_000.0, 0.9, 1.8),
    "USDCHF": (100_000.0, 0.6, 1.5),
    "USDJPY": (1_000.0, 50, 400),
    "XAUUSD": (100.0, 200, 10_000),
}

SOURCES = {}
for _sym, (_scale, _lo, _hi) in _FX.items():
    for _tf in ("d1", "h4", "h1"):
        _name = f"{_sym}_{_tf}"
        SOURCES[_name] = Source(_name, f"{BASE}/{_sym}/{_sym}{_tf}.csv", _scale, _lo, _hi)


# Equities. Short-horizon mean reversion is best documented in stock indices, and
# this series is both longer (25 years) and fresher (2025) than the FX data.
SOURCES["SPY_d1"] = Source(
    "SPY_d1",
    "https://raw.githubusercontent.com/willhjw/big_movers/main/SPY%20Historical%20Data.csv",
    1.0, 50, 2_000, date_fmt="%m/%d/%Y",
)


def _parse_date(raw: str, fmt: Optional[str]) -> str:
    """Return an ISO string so rows sort chronologically as text."""
    raw = raw.strip()
    if fmt:
        return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(raw, f)
            return dt.strftime("%Y-%m-%d %H:%M:%S" if dt.hour or dt.minute else "%Y-%m-%d")
        except ValueError:
            continue
    return raw


def fetch(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "zerostar-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} for {url}")
        return r.read().decode("utf-8", errors="replace")


def normalise(raw: str, src: Source) -> tuple[str, dict]:
    """Rescale prices to real units and emit a plain time,open,high,low,close,volume CSV."""
    rows = list(csv.DictReader(raw.splitlines()))
    if not rows:
        raise RuntimeError(f"{src.name}: upstream returned no rows")

    keys = {k.lower().strip(): k for k in rows[0]}
    kt = keys.get("date") or keys.get("time") or keys.get("datetime")
    ko, kh, kl, kc = keys.get("open"), keys.get("high"), keys.get("low"), keys.get("close")
    kv = keys.get("tick_volume") or keys.get("volume")
    if not all((kt, ko, kh, kl, kc)):
        raise RuntimeError(f"{src.name}: unexpected columns upstream: {list(rows[0])}")

    out = [["time", "open", "high", "low", "close", "volume"]]
    closes: list[float] = []
    bad = 0
    for row in rows:
        try:
            o = float(row[ko]) / src.scale
            h = float(row[kh]) / src.scale
            l = float(row[kl]) / src.scale
            c = float(row[kc]) / src.scale
            v = float(row[kv]) if kv and str(row[kv]).strip() else 0.0
        except (ValueError, TypeError, KeyError):
            bad += 1
            continue
        # Structural check: a bar whose high is not the highest is corrupt.
        if not (h >= max(o, c) and l <= min(o, c) and l > 0):
            bad += 1
            continue
        try:
            when = _parse_date(str(row[kt]), src.date_fmt)
        except ValueError:
            bad += 1
            continue
        out.append([when, f"{o:.4f}", f"{h:.4f}", f"{l:.4f}", f"{c:.4f}", f"{v:.0f}"])
        closes.append(c)

    header, body_rows = out[0], out[1:]
    body_rows.sort(key=lambda r: r[0])          # chronological, whatever upstream did
    out = [header] + body_rows
    closes = [float(r[4]) for r in body_rows]

    if len(closes) < 100:
        raise RuntimeError(f"{src.name}: only {len(closes)} usable rows")

    med = statistics.median(closes)
    if not (src.sane_low <= med <= src.sane_high):
        raise RuntimeError(
            f"{src.name}: median price {med:.2f} outside expected "
            f"[{src.sane_low}, {src.sane_high}] — upstream format or scale changed"
        )

    body = "\n".join(",".join(r) for r in out) + "\n"
    meta = {
        "source_url": src.url,
        "rows": len(closes),
        "first": out[1][0],
        "last": out[-1][0],
        "median_close": round(med, 2),
        "min_close": round(min(closes), 2),
        "max_close": round(max(closes), 2),
        "scale_divisor": src.scale,
        "dropped_rows": bad,
        "sha256": hashlib.sha256(body.encode()).hexdigest(),
    }
    return body, meta


def load_manifest() -> dict:
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as fh:
            return json.load(fh)
    return {}


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Cache OHLC data for the backtester.")
    p.add_argument("symbols", nargs="*", default=None,
                   help=f"which to fetch (default: all). Known: {', '.join(SOURCES)}")
    p.add_argument("--force", action="store_true", help="re-download even if cached")
    p.add_argument("--list", action="store_true", help="show the cache and exit")
    args = p.parse_args(argv)

    os.makedirs(DATA, exist_ok=True)
    manifest = load_manifest()

    if args.list:
        if not manifest:
            print("Cache is empty. Run: python3 fetch_data.py")
            return 0
        print(f"{'symbol':<12} {'rows':>7}  {'from':<19} {'to':<19} {'median':>9}")
        print("-" * 72)
        for name, m in sorted(manifest.items()):
            print(f"{name:<12} {m['rows']:>7}  {m['first']:<19} {m['last']:<19} {m['median_close']:>9}")
        return 0

    wanted = args.symbols or list(SOURCES)
    unknown = [w for w in wanted if w not in SOURCES]
    if unknown:
        print(f"Unknown symbol(s): {', '.join(unknown)}\nKnown: {', '.join(SOURCES)}", file=sys.stderr)
        return 2

    failed = []
    for name in wanted:
        src = SOURCES[name]
        path = os.path.join(DATA, f"{name}.csv")

        if os.path.exists(path) and not args.force:
            print(f"  cached   {name:<12} {path}")
            continue

        try:
            print(f"  fetching {name:<12} {src.url}")
            body, meta = normalise(fetch(src.url), src)
        except Exception as exc:                       # noqa: BLE001 - report, don't crash the batch
            print(f"  FAILED   {name:<12} {exc}", file=sys.stderr)
            failed.append(name)
            continue

        with open(path, "w", newline="") as fh:
            fh.write(body)
        manifest[name] = meta
        print(f"           {meta['rows']} bars, {meta['first']} → {meta['last']}, "
              f"median ${meta['median_close']}")

    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"\nManifest: {MANIFEST}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
