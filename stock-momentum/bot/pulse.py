#!/usr/bin/env python3
"""10-second live account sampler for the dashboard.

systemd fires this once a minute. Every ~10 seconds it reads the live account's
open profit/loss from Trading 212 and does two things:

- patches `latest.json` (the dashboard's header figure — total, invested, P/L),
  so the big number on screen moves within ~10s of the market instead of every
  ~90s;
- collects the samples and, at the end of the minute, writes ONE 1-minute OHLC
  row to `samples_1m.csv` for the candlestick chart.

Value = Trading 212's `ppl` (open P/L on the positions, in euros — the number
the app shows). Profit, not capital: when a contribution is deployed the new
shares enter at cost basis and add ~0 to ppl, so there is no step in the chart.
One HTTP GET per sample, no yfinance — safe at 10s where a price download would
be rate-limited. Live only; the demo track stays on the hourly tracker line.

    .venv/bin/python pulse.py

A tick that fails (a hiccup, a 429) is skipped; the minute still gets a bar from
whatever samples landed. A pulse that raises is worse than a gap.
"""
from __future__ import annotations

import csv
import json
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
LATEST = os.path.join(HERE, "latest.json")
COLS = ("time", "track", "open", "high", "low", "close")

SAMPLES_PER_MIN = 6          # one every ~10s


def sample():
    """(ppl, invested) from Trading 212, or (None, None) on any failure."""
    try:
        c = t212.cash()
        return round(float(c.get("ppl") or 0.0), 2), float(c.get("invested") or 0.0)
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! {type(exc).__name__}: {exc}")
        return None, None


def patch_latest(ppl: float, cost_basis: float) -> None:
    """Update latest.json's live money fields from one tick. Same figures the
    momentum-live refresh writes (holdings market value; P/L = ppl, no FX-fee
    subtraction), just far more often. Leaves positions / ranking / scoreboard
    to the ~90s full refresh. Silently does nothing if latest.json isn't ready."""
    try:
        with open(LATEST, encoding="utf-8") as fh:
            payload = json.load(fh)
        row = payload["tracks"]["live"]
    except (OSError, ValueError, KeyError):
        return
    held = cost_basis + ppl
    if held <= 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    row.update({"total": round(held, 2), "invested": round(held, 2), "cash": 0.0,
                "pnl": round(ppl, 2), "unrealised": round(ppl, 2),
                "pnl_pct": round(ppl / cost_basis * 100, 2) if cost_basis else 0.0,
                "as_of": now})
    payload["generated"] = now
    tmp = LATEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    os.replace(tmp, LATEST)


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
        ppl, invested = sample()
        if ppl is not None:
            vals.append(ppl)
            patch_latest(ppl, invested)
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
