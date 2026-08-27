#!/usr/bin/env python3
"""Hourly value snapshot for the dashboard's money-over-time chart.

Every hour, systemd runs this once. For each book (demo, live) it values the
STRATEGY's holdings -- cash plus shares times the latest price -- not the whole
Trading 212 account, so free funds sitting in the account do not inflate the
line. It also works out what the same deposits would be worth today if they had
gone into a broad-market ETF instead, and appends a row per book to hourly.csv.

Standalone on purpose: it reads state.json and yfinance, nothing else. No broker
call, no momentum_bot import. To run it by hand:

    .venv/bin/python tracker.py

Anything missing (market closed, yfinance hiccup, a book never funded) is skipped
with what is available still written. A tracker that raises is worse than a gap
in the curve.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
LATEST = os.path.join(HERE, "latest.json")
DEPOSITS = os.path.join(HERE, "deposits.csv")
HOURLY = os.path.join(HERE, "hourly.csv")

BENCH_TICKER = os.environ.get("MOMENTUM_BENCH_TICKER", "SXR8.DE").strip()


def _json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, OSError, ValueError):
        return default


def books() -> dict:
    """{track: book} from state.json, or {}."""
    return (_json(STATE, {}).get("tracks") or {})


def account_currency() -> str:
    """The currency the books are kept in, from the bot's render cache. EUR is
    the bot's own default when it cannot ask Trading 212."""
    return str(_json(LATEST, {}).get("currency") or "EUR").upper()


def deposits_by_track() -> dict:
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


def _last_close(raw, sym, multi):
    try:
        col = raw[sym]["Close"] if multi else raw["Close"]
        col = col.dropna()
        return float(col.iloc[-1]) if len(col) else None
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def held_prices(tickers, ccy: str) -> dict:
    """{ticker: latest price in `ccy`} for the held names.

    yfinance prices are USD. If the books are in another currency the bot's own
    rule is used: fetch CCYUSD=X and divide (EURUSD ~ 1.17 -> 1 USD = 0.85 EUR).
    """
    want = sorted(set(tickers))
    if not want:
        return {}
    import pandas as pd
    import yfinance as yf
    syms = want + ([] if ccy == "USD" else [f"{ccy}USD=X"])
    try:
        raw = yf.download(syms, period="5d", progress=False, threads=False,
                          auto_adjust=True, group_by="ticker")
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! prices: {type(exc).__name__}: {exc}")
        return {}
    if raw is None or raw.empty:
        print("  ! prices: nothing came back")
        return {}
    multi = isinstance(raw.columns, pd.MultiIndex)

    usd = {tk: _last_close(raw, tk, multi) for tk in want}
    usd = {k: v for k, v in usd.items() if v}
    rate = 1.0
    if ccy != "USD":
        rate = _last_close(raw, f"{ccy}USD=X", multi)
        if not rate:
            print(f"  ! no {ccy}USD=X rate; cannot value the books")
            return {}
    return {tk: p / rate for tk, p in usd.items()}


def strategy_total(book: dict, px: dict):
    """Cash plus the value of the held shares, or None for a book never funded."""
    positions = book.get("positions") or {}
    cash = float(book.get("cash") or 0.0)
    if not positions and not cash and not float(book.get("deposited") or 0.0):
        return None
    total = cash
    for tk, sh in positions.items():
        p = px.get(tk)
        if p:
            total += float(sh) * p
    return round(total, 2)


def bench_series(start_date: str):
    """Daily closes for the benchmark ETF, {YYYY-MM-DD: close}, plus the latest.
    Returns (closes, latest), or (None, None) if the download was empty."""
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
    return closes, closes[max(closes)]


def _on_or_before(closes: dict, day: str):
    """The ETF close on `day`, or the last one before it (weekend / holiday)."""
    keys = sorted(k for k in closes if k <= day)
    return closes[keys[-1]] if keys else None


def bench_value(deposits, closes, latest):
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
            w.writerow({k: r.get(k, "") for k in ("time", "series", "total", "bench")})
        for t, s, total, bench in rows:
            w.writerow({"time": t, "series": s,
                        "total": "" if total is None else f"{total:.2f}",
                        "bench": "" if bench is None else f"{bench:.2f}"})
    os.replace(tmp, HOURLY)


def main() -> int:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    stamp = now.strftime("%Y-%m-%dT%H:00Z")

    trk = books()
    deps = deposits_by_track()
    earliest = min((d for rs in deps.values() for d, _ in rs),
                   default=now.strftime("%Y-%m-%d"))

    held = [tk for bk in trk.values() for tk in (bk.get("positions") or {})]
    px = held_prices(held, account_currency())
    closes, latest = bench_series(earliest)

    rows = []
    for name in ("demo", "live"):
        bk = trk.get(name)
        if not bk:
            continue
        total = strategy_total(bk, px)
        if total is None:
            continue
        bench = bench_value(deps.get(name, []), closes, latest)
        rows.append((stamp, name, total, bench))
        print(f"  {name}: total {total:.2f}"
              + (f"  bench {bench:.2f}" if bench is not None else ""))

    if rows:
        append_rows(rows)
        print(f"wrote {len(rows)} row(s) to hourly.csv at {stamp}")
    else:
        print("nothing to record (no funded book, or state.json missing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
