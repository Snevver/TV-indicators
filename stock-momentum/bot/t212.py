#!/usr/bin/env python3
"""Optional Trading 212 link. Read-only.

WHY THIS IS OPTIONAL AND STAYS OPTIONAL
Without a key the bot keeps its own book: it assumes you filled at the close of
the rebalance day and you correct it with --fill. That works and is the default.
With a key it reads what you actually hold, so the book stops being a model.

Nothing in here may ever take the bot down. Every call is wrapped, every failure
returns None, and the caller falls back to the local book with a warning. A
broker that is slow, rate-limiting, rejecting the key or returning a shape we
did not expect must not stop a rebalance message going out.

WHAT IT CANNOT DO
Place orders. Trading 212's public API only accepts orders in practice mode, and
this module never sends one in either environment. You place trades yourself.

SETUP (when you are ready — it is fine to leave this off)
  1. Trading 212 app -> Settings -> API. Generate a key for the account you are
     running. You get TWO values: an API key and a secret key. Both are needed --
     the key is the username half and the secret is the password half of an HTTP
     Basic login. Practice and live are separate pairs with separate URLs.
  2. Put them in /etc/momentum-bot.env, which is mode 600:
         T212_API_KEY=...
         T212_API_SECRET=...      # the second value shown when you generated it
         T212_ENV=demo            # or: live
         T212_PIE_ID=12345        # optional, strongly recommended — see below
  3. python momentum_bot.py --t212-probe     # prove the pair works
     python momentum_bot.py --t212-check     # broker vs the bot's book
     python momentum_bot.py --t212-sync      # adopt the broker's numbers

Both values are passwords. They belong in that file and nowhere else — not in
the repo, not in a crontab, not pasted into a chat. If either leaks, revoke the
pair in the app and generate another.

WHY A SEPARATE PIE
/equity/portfolio returns the whole account. If you hold anything else on
Trading 212, the bot would read those positions as if the strategy had bought
them. Setting T212_PIE_ID scopes it to one pie, so the rest of your investing
stays invisible to it and its profit and loss measures only this strategy.
"""
from __future__ import annotations

import json
import os
import time

API_KEY = os.environ.get("T212_API_KEY", "").strip()
API_SECRET = os.environ.get("T212_API_SECRET", "").strip()
ENV = os.environ.get("T212_ENV", "demo").strip().lower()
PIE_ID = os.environ.get("T212_PIE_ID", "").strip()
TIMEOUT = float(os.environ.get("T212_TIMEOUT", "20") or 20)

BASE = {"demo": "https://demo.trading212.com/api/v0",
        "live": "https://live.trading212.com/api/v0"}.get(ENV)

# Trading 212 names instruments like AAPL_US_EQ. Anything we cannot resolve is
# reported rather than guessed at.
OVERRIDES = json.loads(os.environ.get("T212_TICKER_MAP", "{}") or "{}")


class T212Error(Exception):
    """Anything that went wrong talking to the broker. Always caught."""


def configured() -> bool:
    return bool(API_KEY and BASE)


def why_not() -> str:
    if not API_KEY:
        return "T212_API_KEY is not set — using the bot's own book"
    if not BASE:
        return f"T212_ENV must be 'demo' or 'live', not {ENV!r} — using the bot's own book"
    return ""


def _get(path: str, tries: int = 3):
    """One GET. Raises T212Error on anything that is not a clean 200."""
    import requests
    url = f"{BASE}{path}"
    # Trading 212 authenticates with HTTP Basic: the API key is the username and
    # the secret is the password. requests builds and encodes that header, which
    # is safer than hand-rolling base64 -- a stray newline in the encoded pair is
    # a 401 that looks exactly like a bad key.
    #
    # With no secret set, send the bare key the way this file used to. An older
    # single-value credential still authenticates that way, and it costs nothing
    # to keep working.
    headers = {"Accept": "application/json"}
    auth = (API_KEY, API_SECRET) if API_SECRET else None
    if auth is None:
        headers["Authorization"] = API_KEY
    last = ""
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=headers, auth=auth, timeout=TIMEOUT)
        except Exception as exc:                       # network, DNS, TLS, timeout
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                raise T212Error(f"{path}: 200 but the body was not JSON: {r.text[:200]}")
        if r.status_code == 401:
            missing = ("" if API_SECRET else
                       " T212_API_SECRET is not set, and Trading 212 issues a key "
                       "AND a secret — the key alone is rejected. That is the most "
                       "likely cause.")
            raise T212Error(f"{path}: 401 — the credentials were rejected.{missing} "
                            f"Otherwise: a mistyped pair, or a live key against "
                            f"T212_ENV=demo (or the reverse).")
        if r.status_code == 403:
            raise T212Error(f"{path}: 403 — the key is valid but lacks this "
                            f"permission. Re-generate it with portfolio and "
                            f"history access ticked.")
        if r.status_code == 429:                       # rate limited: back off
            last = "429 rate limited"
            time.sleep(5 * (attempt + 1))
            continue
        raise T212Error(f"{path}: HTTP {r.status_code} — {r.text[:200]}")
    raise T212Error(f"{path}: gave up after {tries} attempts ({last})")


# --------------------------------------------------------------- field mapping
#
# The exact JSON keys are not verified against a live account yet, so read
# tolerantly: try the plausible names, and say so clearly when none match rather
# than silently reporting a zero.

def _pick(d: dict, *names, default=None):
    for n in names:
        if isinstance(d, dict) and n in d and d[n] is not None:
            return d[n]
    return default


def symbol(raw: str) -> str:
    """'AAPL_US_EQ' -> 'AAPL'. Overridable via T212_TICKER_MAP."""
    if raw in OVERRIDES:
        return OVERRIDES[raw]
    s = str(raw)
    for suffix in ("_US_EQ", "_EQ", "_US"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.split("_")[0].upper()


def cash() -> dict:
    """{'free', 'invested', 'total'} in the account's own currency."""
    d = _get("/equity/account/cash")
    if not isinstance(d, dict):
        raise T212Error(f"cash: expected an object, got {type(d).__name__}")
    return {"free": float(_pick(d, "free", "freeForStocks", "cash", default=0.0) or 0.0),
            "invested": float(_pick(d, "invested", "investedValue", default=0.0) or 0.0),
            "total": float(_pick(d, "total", "totalValue", "equity", default=0.0) or 0.0),
            "ppl": float(_pick(d, "ppl", "result", "pnl", default=0.0) or 0.0),
            "raw": d}


def positions() -> dict:
    """{TICKER: {'shares', 'avg_price', 'value'}} for the pie, or the account."""
    if PIE_ID:
        d = _get(f"/equity/pies/{PIE_ID}")
        items = _pick(d, "instruments", "positions", "holdings", default=[]) or []
        if not items:
            raise T212Error(f"pie {PIE_ID} came back with no instruments — check "
                            f"T212_PIE_ID against --t212-probe")
    else:
        raw_body = _get("/equity/portfolio")
        if isinstance(raw_body, list):
            items = raw_body
        elif isinstance(raw_body, dict):
            items = _pick(raw_body, "positions", "instruments", default=None)
            if items is None:
                # A dict we do not recognise is a mapping problem, not an empty
                # portfolio. Saying "you hold nothing" here would wipe the book.
                raise T212Error(
                    f"/equity/portfolio returned an object with none of the keys "
                    f"this code knows ({', '.join(sorted(raw_body))[:120]}). "
                    f"Run --t212-probe and the mapping can be corrected.")
        else:
            raise T212Error(f"/equity/portfolio returned {type(raw_body).__name__}, "
                            f"expected a list of positions")

    out = {}
    skipped = 0
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        raw = _pick(it, "ticker", "instrument", "symbol", "instrumentCode")
        qty = _pick(it, "quantity", "ownedQuantity", "shares", "sharesCount")
        if raw is None or qty is None:
            skipped += 1
            continue
        avg = _pick(it, "averagePrice", "avgPrice", "averageEntryPrice", "price")
        cur = _pick(it, "currentPrice", "currentValue", "lastPrice")
        val = _pick(it, "value", "currentValue", "marketValue")
        qty = float(qty)
        if qty <= 0:
            continue
        avg = float(avg) if avg is not None else 0.0
        if val is None:
            val = qty * float(cur) if cur is not None else 0.0
        out[symbol(raw)] = {"shares": qty, "avg_price": avg, "value": float(val),
                            "cost": qty * avg, "raw_ticker": str(raw)}

    if items and not out:
        # The broker sent rows and not one of them parsed. That is a mapping
        # failure. Reporting it as an empty portfolio would delete the book.
        raise T212Error(f"{len(items)} positions came back but none could be read "
                        f"— the field names differ from what this code expects. "
                        f"Run --t212-probe.")
    if skipped:
        print(f"  ! Trading 212: {skipped} of {len(items)} rows could not be read")
    return out


def fees(limit: int = 50) -> list:
    """Recent transactions, so the real charges can be read rather than modelled.

    The shape of this one is the least certain of the three; it is only ever used
    for reporting, never for the book.
    """
    d = _get(f"/history/transactions?limit={limit}")
    items = d if isinstance(d, list) else (_pick(d, "items", "transactions", default=[]) or [])
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(_pick(it, "type", "action", default="")).upper()
        amt = _pick(it, "amount", "value", default=0.0)
        out.append({"type": kind,
                    "amount": float(amt or 0.0),
                    "when": _pick(it, "dateTime", "time", "date", default=""),
                    "raw": it})
    return out


def probe() -> int:
    """Print exactly what the account returns, so the mapping above can be
    finished against reality instead of guessed at. Read-only."""
    if not configured():
        print(why_not() or "not configured")
        print("\nSet T212_API_KEY, T212_API_SECRET and T212_ENV in "
              "/etc/momentum-bot.env, then:")
        print("  set -a; . /etc/momentum-bot.env; set +a")
        return 1

    print(f"env      : {ENV}")
    print(f"base     : {BASE}")
    print(f"key      : {API_KEY[:4]}…{API_KEY[-3:]} ({len(API_KEY)} chars)")
    if API_SECRET:
        print(f"secret   : {API_SECRET[:4]}…{API_SECRET[-3:]} "
              f"({len(API_SECRET)} chars)")
        print("auth     : HTTP Basic (key as username, secret as password)")
    else:
        print("secret   : NOT SET — sending the bare key, which Trading 212 will "
              "most likely reject with a 401")
        print("auth     : bare Authorization header (legacy single-key form)")
    print(f"pie      : {PIE_ID or '(whole account — set T212_PIE_ID to scope it)'}")
    print()

    checks = [("cash", "/equity/account/cash"),
              ("portfolio", "/equity/portfolio"),
              ("pies", "/equity/pies")]
    if PIE_ID:
        checks.append((f"pie {PIE_ID}", f"/equity/pies/{PIE_ID}"))
    checks.append(("transactions", "/history/transactions?limit=5"))

    ok = 0
    for name, path in checks:
        print(f"--- {name}  GET {path}")
        try:
            d = _get(path, tries=1)
        except T212Error as exc:
            print(f"    FAILED: {exc}\n")
            continue
        except Exception as exc:
            print(f"    FAILED: {type(exc).__name__}: {exc}\n")
            continue
        ok += 1
        body = json.dumps(d, indent=1, default=str)
        print("    " + "\n    ".join(body.splitlines()[:40]))
        if len(body.splitlines()) > 40:
            print(f"    … {len(body.splitlines()) - 40} more lines")
        print()
        time.sleep(1.2)          # the API rate-limits hard; do not hammer it

    print(f"{ok}/{len(checks)} endpoints answered.")
    if ok:
        print("\nNothing above is secret except the key, which is masked. Paste it "
              "back and the field mapping can be finished against the real shapes.")
    return 0 if ok else 1


def snapshot() -> dict | None:
    """Everything the bot needs, or None. Never raises."""
    if not configured():
        return None
    try:
        pos = positions()
    except Exception as exc:
        print(f"  ! Trading 212: {exc}")
        print("    falling back to the bot's own book")
        return None
    try:
        c = cash()
    except Exception as exc:
        print(f"  ! Trading 212: positions read, cash did not ({exc})")
        c = None
    invested = sum(p["value"] for p in pos.values())
    free = (c or {}).get("free", 0.0) if not PIE_ID else 0.0
    return {"positions": pos, "cash": free, "invested": invested,
            "total": invested + free, "account_cash": c, "scoped_to_pie": bool(PIE_ID)}
