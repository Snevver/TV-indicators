#!/usr/bin/env python3
"""Hourly value snapshot for the dashboard's money-over-time chart.

Every hour, systemd runs this once. For each book (demo, live) it values the
STRATEGY's holdings -- cash (the bot's ledger) plus the value of the shares --
not the whole Trading 212 account, so free funds sitting in the account do not
inflate the line. It also works out what the same deposits would be worth today
if they had gone into a broad-market ETF instead, and appends a row per book to
hourly.csv.

Share value comes from Trading 212 itself for the account a key is configured
for (T212_ENV), so the chart matches the app; the other book, and everything
when there is no key, falls back to a yfinance mark. The benchmark ETF is
always yfinance. No momentum_bot import. To run it by hand:

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

# Optional, exactly like in momentum_bot: a missing or broken t212.py must not
# stop the tracker. It reads its configuration at import from the same env files
# systemd loads for this unit.
try:
    import t212
except Exception:                                    # noqa: BLE001
    t212 = None

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
LATEST = os.path.join(HERE, "latest.json")
DEPOSITS = os.path.join(HERE, "deposits.csv")
HOURLY = os.path.join(HERE, "hourly.csv")

# Tried in order until one returns a usable series. The first three are the same
# S&P 500 UCITS ETF listed in EUR (Xetra, Amsterdam, Milan), so the line is in
# the same currency as the books. ^GSPC is a last resort: it is the index in USD
# points, so its SHAPE is right but its level drifts from a EUR account by the
# EUR/USD move. Override the whole list with MOMENTUM_BENCH_TICKER (comma list).
BENCH_TICKERS = [t.strip() for t in os.environ.get(
    "MOMENTUM_BENCH_TICKER", "SXR8.DE,IUSA.AS,SXR8.MI,^GSPC").split(",")
    if t.strip()]


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


def fresh_latest_totals(max_age_s: int = 3600) -> dict:
    """{track: total} from latest.json, per track, but only for a track whose
    `as_of` stamp is within the last max_age_s seconds (~one tracker cycle).
    That total is the exact figure the dashboard header shows (the bot's mark()
    via refresh_live / --json), so the chart's last live point lands on the same
    number instead of tracker's own slightly different holdings scope and FX. A
    track the bot has not refreshed recently -> absent, and the caller keeps its
    own mark for it."""
    trk = (_json(LATEST, {}).get("tracks") or {})
    now = datetime.now(timezone.utc)
    out = {}
    for name, v in trk.items():
        if not isinstance(v, dict) or v.get("total") is None:
            continue
        try:
            age = (now - datetime.fromisoformat(v["as_of"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age <= max_age_s:
            out[name] = float(v["total"])
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


def broker_holdings() -> dict:
    """{track: holdings value in the account currency} from Trading 212 itself,
    for the one account a key is configured for (T212_ENV).

    Trading 212 reports it as invested + ppl -- cost basis plus open P&L -- which
    is the figure on its Investments screen. Empty when there is no key or the
    call fails; the caller then falls back to the yfinance mark.
    """
    if t212 is None or not getattr(t212, "configured", lambda: False)():
        return {}
    env = getattr(t212, "ENV", "")
    if env not in ("demo", "live"):
        return {}
    try:
        snap = t212.snapshot()
    except Exception as exc:                              # noqa: BLE001
        print(f"  ! Trading 212 read failed ({type(exc).__name__}: {exc})")
        return {}
    ac = (snap or {}).get("account_cash") or {}
    val = float(ac.get("invested") or 0.0) + float(ac.get("ppl") or 0.0)
    return {env: round(val, 2)} if val > 0 else {}


def strategy_total(book: dict, px: dict, held_value=None):
    """Cash plus the value of the held shares, or None for a book never funded.

    `held_value` (optional) is Trading 212's own figure for the shares; when
    given it replaces the yfinance mark, so the line matches the app.
    """
    positions = book.get("positions") or {}
    cash = float(book.get("cash") or 0.0)
    if not positions and not cash and not float(book.get("deposited") or 0.0):
        return None
    if held_value is not None:
        return round(cash + held_value, 2)
    total = cash
    for tk, sh in positions.items():
        p = px.get(tk)
        if p:
            total += float(sh) * p
    return round(total, 2)


def _bench_one(ticker: str, start_date: str):
    """One ticker's price series, hourly if yfinance will give it, daily if not.

    Hourly matters: this script runs every hour and the money-over-time chart
    draws the account line hourly, so a daily benchmark can only step once a day
    and reads as a flat line next to it -- which is exactly the bug this fixes.

    Keys are 'YYYY-MM-DDTHH' for the hourly series, 'YYYY-MM-DD' for the daily
    fallback. Returns (closes, latest) or (None, None).
    """
    import yfinance as yf
    try:
        span = (datetime.now(timezone.utc).date()
                - datetime.fromisoformat(start_date).date()).days + 5
    except ValueError:
        span = 400

    attempts = []
    if span <= 720:                          # yfinance caps 1h history at ~730d
        attempts.append(("%Y-%m-%dT%H",
                         dict(period=f"{max(span, 7)}d", interval="1h")))
    attempts.append(("%Y-%m-%d", dict(start=start_date, interval="1d")))

    for fmt, kw in attempts:
        try:
            raw = yf.download(ticker, progress=False, threads=False,
                              auto_adjust=True, **kw)
        except Exception as exc:                          # noqa: BLE001
            print(f"  ! benchmark {ticker} {kw['interval']}: "
                  f"{type(exc).__name__}: {exc}")
            continue
        if raw is None or raw.empty:
            continue
        close = raw["Close"]
        if hasattr(close, "columns"):        # a 1-column frame on some versions
            close = close.iloc[:, 0]
        closes = {d.strftime(fmt): float(v) for d, v in close.dropna().items()}
        if len(closes) >= 2:                 # one bar is a flat line, not a series
            return closes, closes[max(closes)]
    return None, None


def bench_series(start_date: str):
    """The first benchmark ticker that returns a usable series.
    Returns (closes, latest, ticker), or (None, None, None)."""
    for tk in BENCH_TICKERS:
        closes, latest = _bench_one(tk, start_date)
        if closes:
            return closes, latest, tk
    print(f"  ! no benchmark ticker returned data ({', '.join(BENCH_TICKERS)})")
    return None, None, None


def _on_or_before(closes: dict, day: str):
    """The ETF price on `day`, or the last one before it (weekend / holiday).

    Keys may be 'YYYY-MM-DD' (daily) or 'YYYY-MM-DDTHH' (hourly); `day` is always
    a plain date, so compare on the date part and take the last bar of that day.
    """
    keys = sorted(k for k in closes if k[:10] <= day)
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
    fresh = fresh_latest_totals()          # {track: total} the header is showing
    earliest = min((d for rs in deps.values() for d, _ in rs),
                   default=now.strftime("%Y-%m-%d"))

    held = [tk for bk in trk.values() for tk in (bk.get("positions") or {})]
    px = held_prices(held, account_currency())
    closes, latest, bench_tk = bench_series(earliest)
    brk = broker_holdings()                 # {track: value} for the keyed account

    rows = []
    for name in ("demo", "live"):
        bk = trk.get(name)
        if not bk:
            continue
        total = strategy_total(bk, px, brk.get(name))
        if total is None:
            continue                       # book never funded -> no row
        if name in fresh:
            total = round(fresh[name], 2)  # match the dashboard header exactly
        bench = bench_value(deps.get(name, []), closes, latest)
        rows.append((stamp, name, total, bench))
        src = "latest" if name in fresh else ("t212" if name in brk else "yfinance")
        print(f"  {name}: total {total:.2f} ({src})"
              + (f"  bench {bench:.2f} ({bench_tk})" if bench is not None
                 else "  bench -"))

    if rows:
        append_rows(rows)
        print(f"wrote {len(rows)} row(s) to hourly.csv at {stamp}")
    else:
        print("nothing to record (no funded book, or state.json missing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
