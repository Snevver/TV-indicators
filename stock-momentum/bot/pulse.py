#!/usr/bin/env python3
"""10-second live account sampler for the dashboard's candlestick chart.

systemd fires this once a minute. It reads the live account value about every
10 seconds, then writes ONE 1-minute OHLC row (open, high, low, close over the
samples it took) to samples_1m.csv and exits. Nothing renders below a 1-minute
bar, so raw 10s ticks are not kept -- the minute bar is the smallest unit.

Value = Trading 212's invested + ppl (the Investments-tab figure: what the
holdings are worth right now). Account free funds are excluded -- the strategy
does not control them. One HTTP GET per sample, no yfinance -- so it is safe at
10s where a price download would be rate-limited. Live only; the demo track
stays on the hourly tracker line.

    .venv/bin/python pulse.py

A tick that fails (market data hiccup, a 429) is skipped; the minute still gets
a bar from whatever samples landed. A pulse that raises is worse than a gap.
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone

# t212 reads T212_ENV at import. This sampler is live-only, so pin it before the
# import regardless of what the unit's env files say (same shim momentum_bot.py
# uses for --env).
os.environ["T212_ENV"] = "live"
try:
    import t212
except Exception as exc:                                  # noqa: BLE001
    t212 = None
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    _IMPORT_ERROR = ""

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_1M = os.path.join(HERE, "samples_1m.csv")
COLS = ("time", "track", "open", "high", "low", "close")

SAMPLES_PER_MIN = 6          # one every ~10s


def value():
    """The strategy's holdings value now, from Trading 212: invested + ppl
    (cost basis plus open P/L -- the Investments-tab figure). Account free funds
    are NOT included: the strategy does not control them. None on any failure --
    the caller skips the sample."""
    try:
        c = t212.cash()
        return round(float(c.get("invested") or 0.0)
                     + float(c.get("ppl") or 0.0), 2)
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! {type(exc).__name__}: {exc}")
        return None


def append_bar(ts, track, o, h, l, c) -> None:
    """Append one 1-minute OHLC row. Append-only; the web side buckets these up
    into whatever timeframe the chart asks for."""
    new = not os.path.exists(SAMPLES_1M)
    with open(SAMPLES_1M, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(COLS)
        w.writerow([ts.strftime("%Y-%m-%dT%H:%MZ"), track,
                    f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}"])


def main() -> int:
    if t212 is None:
        print(f"t212 import failed: {_IMPORT_ERROR}")
        return 0
    if not t212.configured():
        print(f"t212 not configured for live: {t212.why_not()}")
        return 0

    minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    vals = []
    for i in range(SAMPLES_PER_MIN):
        v = value()
        if v is not None:
            vals.append(v)
        if i < SAMPLES_PER_MIN - 1:
            time.sleep(10)
        if datetime.now(timezone.utc).replace(second=0, microsecond=0) != minute:
            break                    # next minute has its own run

    if not vals:
        print(f"{minute:%H:%MZ}: no samples")
        return 0
    append_bar(minute, "live", vals[0], max(vals), min(vals), vals[-1])
    print(f"  live {minute:%H:%MZ}  o {vals[0]:.2f}  h {max(vals):.2f}  "
          f"l {min(vals):.2f}  c {vals[-1]:.2f}  ({len(vals)} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
