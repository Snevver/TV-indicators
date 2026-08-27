#!/usr/bin/env python3
"""Hourly value snapshot for the dashboard's money-over-time chart.

Every hour, systemd runs this once. It reads the total value of the demo and
live Trading 212 accounts, works out what the same deposits would be worth today
if they had gone into a broad-market ETF instead, and appends a row per account
to hourly.csv. The dashboard draws the real curve against the ETF one.

It is deliberately standalone: it does not import momentum_bot or the env-locked
t212 module, so it can talk to both accounts in one run. systemd supplies the
credentials through EnvironmentFile; to run it by hand:

    set -a; . /etc/momentum-bot.env; set +a
    python tracker.py

Anything missing (market closed, yfinance hiccup, one account not configured) is
skipped with what is available still written. A tracker that raises is worse
than a gap in the curve.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEPOSITS = os.path.join(HERE, "deposits.csv")
HOURLY = os.path.join(HERE, "hourly.csv")

BENCH_TICKER = os.environ.get("MOMENTUM_BENCH_TICKER", "SXR8.DE").strip()

BASES = {"demo": "https://demo.trading212.com/api/v0",
         "live": "https://live.trading212.com/api/v0"}


def _creds(env: str):
    """(key, secret) for one account, plain T212_API_KEY as a one-key fallback."""
    sfx = env.upper()
    key = (os.environ.get(f"T212_API_KEY_{sfx}")
           or os.environ.get("T212_API_KEY", "")).strip()
    secret = (os.environ.get(f"T212_API_SECRET_{sfx}")
              or os.environ.get("T212_API_SECRET", "")).strip()
    return key, secret


def account_total(env: str):
    """The whole account's value in its own currency, or None."""
    key, secret = _creds(env)
    if not key:
        return None
    import requests
    headers = {"Accept": "application/json"}
    auth = (key, secret) if secret else None
    if auth is None:
        headers["Authorization"] = key
    try:
        r = requests.get(f"{BASES[env]}/equity/account/cash",
                         headers=headers, auth=auth, timeout=20)
        if r.status_code != 200:
            print(f"  ! {env}: /equity/account/cash returned {r.status_code}")
            return None
        d = r.json()
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! {env}: {type(exc).__name__}: {exc}")
        return None
    for k in ("total", "totalValue", "equity"):
        if d.get(k) is not None:
            return float(d[k])
    # Last resort: free + invested.
    free = d.get("free") or d.get("freeForStocks") or d.get("cash") or 0.0
    inv = d.get("invested") or d.get("investedValue") or 0.0
    return float(free) + float(inv)


def deposits_by_track():
    """{track: [(date, amount), ...]} from the bot's deposits.csv."""
    out = {}
    try:
        with open(DEPOSITS, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    d = str(row["time"])[:10]
                    amt = float(row["amount"])
                except (KeyError, ValueError, TypeError):
                    continue
                out.setdefault(row.get("track", ""), []).append((d, amt))
    except (FileNotFoundError, OSError):
        pass
    return out


def bench_series(start_date: str):
    """Daily closes for the benchmark ETF, {YYYY-MM-DD: close}, plus the latest.

    Returns (closes, latest) or (None, None) if the download came back empty.
    """
    import yfinance as yf
    try:
        raw = yf.download(BENCH_TICKER, start=start_date, progress=False,
                          threads=False, auto_adjust=True)
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! benchmark {BENCH_TICKER}: {type(exc).__name__}: {exc}")
        return None, None
    if raw is None or raw.empty:
        print(f"  ! benchmark {BENCH_TICKER}: no data")
        return None, None
    close = raw["Close"]
    if hasattr(close, "columns"):            # a 1-column frame on some versions
        close = close.iloc[:, 0]
    closes = {d.strftime("%Y-%m-%d"): float(v)
              for d, v in close.dropna().items()}
    if not closes:
        return None, None
    latest = closes[max(closes)]
    return closes, latest


def _on_or_before(closes: dict, day: str) -> float | None:
    """The ETF close on `day`, or the last one before it (weekend / holiday)."""
    keys = sorted(k for k in closes if k <= day)
    return closes[keys[-1]] if keys else None


def bench_value(deposits, closes, latest) -> float | None:
    """What those deposits, made on those days, would be worth in the ETF now."""
    if not deposits or not closes:
        return None
    units = 0.0
    for day, amount in deposits:
        px = _on_or_before(closes, day) or latest
        if px:
            units += amount / px
    return round(units * latest, 2)


def append_rows(rows):
    """Append (time, series, total, bench) rows, replacing any for the same
    (time, series). Atomic tmp + rename."""
    keys = {(r[0], r[1]) for r in rows}
    keep = []
    try:
        with open(HOURLY, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if (r.get("time"), r.get("series")) not in keys:
                    keep.append(r)
    except (FileNotFoundError, OSError):
        pass
    tmp = HOURLY + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=("time", "series", "total", "bench"))
        w.writeheader()
        for r in keep:
            w.writerow({k: r.get(k, "") for k in
                        ("time", "series", "total", "bench")})
        for t, s, total, bench in rows:
            w.writerow({"time": t, "series": s,
                        "total": "" if total is None else f"{total:.2f}",
                        "bench": "" if bench is None else f"{bench:.2f}"})
    os.replace(tmp, HOURLY)


def main() -> int:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    stamp = now.strftime("%Y-%m-%dT%H:00Z")

    deps = deposits_by_track()
    earliest = min((d for rows in deps.values() for d, _ in rows),
                   default=now.strftime("%Y-%m-%d"))
    closes, latest = bench_series(earliest)

    rows = []
    for env in ("demo", "live"):
        total = account_total(env)
        if total is None:
            continue
        bench = bench_value(deps.get(env, []), closes, latest)
        rows.append((stamp, env, total, bench))
        print(f"  {env}: total {total:.2f}"
              + (f"  bench {bench:.2f}" if bench is not None else ""))

    if rows:
        append_rows(rows)
        print(f"wrote {len(rows)} row(s) to hourly.csv at {stamp}")
    else:
        print("nothing to record (no account configured or reachable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
