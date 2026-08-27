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

WHAT IT DOES NOT DO
Place orders. Not because it cannot -- Trading 212's API does accept live market
orders now, and a key with the "Orders - Execute" permission could send them --
but because it deliberately does not. Reading the account correctly has to be
proven before anything writes to it, and the field mapping below is still
unverified against a real account. Every request in this file is a GET. You
place trades yourself.

SETUP (when you are ready — it is fine to leave this off)
  1. Trading 212 app -> Settings -> API. Generate a key for the account you are
     running. You get TWO values: an API key and a secret key. Both are needed --
     the key is the username half and the secret is the password half of an HTTP
     Basic login. Practice and live are separate pairs with separate URLs.
  2. Put them in /etc/momentum-bot.env, which is mode 600. Name them for the
     account they belong to, so demo and live can both be stored:
         T212_API_KEY_DEMO=...      T212_API_SECRET_DEMO=...
         T212_API_KEY_LIVE=...      T212_API_SECRET_LIVE=...
         T212_ENV=demo             # or: live -- picks which pair is used
     A plain T212_API_KEY / T212_API_SECRET still works if you only have one.
  3. python momentum_bot.py --t212-probe     # prove the pair works
     python momentum_bot.py --t212-check     # broker vs the bot's book
     python momentum_bot.py --t212-sync      # adopt the broker's numbers

Both values are passwords. They belong in that file and nowhere else — not in
the repo, not in a crontab, not pasted into a chat. If either leaks, revoke the
pair in the app and generate another.

WHY THERE IS NO PIE
A pie looked like the way to fence the strategy off from the rest of an account.
It is not, for two reasons found in the API rather than guessed at:

  * Nothing can put money into a pie. The pie endpoints are create, read,
    update, duplicate and delete, and update sets target weights only -- it does
    not trade. So a bot cannot fund a pie, and Trading 212 does not let a pie
    hold uninvested cash either.
  * The pie API is deprecated. It still answers, but it is documented as no
    longer supported and subject to change.

So the strategy trades in the ordinary portfolio, and positions() scopes itself
instead: non-pie quantity only, intersected with the frozen universe. See its
docstring for what that can and cannot separate.
"""
from __future__ import annotations

import json
import os
import time

ENV = os.environ.get("T212_ENV", "demo").strip().lower()

# Demo and live are separate accounts with separate key pairs. Keeping both in
# the env file means flipping T212_ENV does not also mean re-pasting a key. The
# plain T212_API_KEY / T212_API_SECRET still work as a fallback for a one-key
# setup.
_SFX = ENV.upper()
API_KEY = (os.environ.get(f"T212_API_KEY_{_SFX}")
           or os.environ.get("T212_API_KEY", "")).strip()
API_SECRET = (os.environ.get(f"T212_API_SECRET_{_SFX}")
              or os.environ.get("T212_API_SECRET", "")).strip()
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
        return (f"no key for T212_ENV={ENV!r} — set T212_API_KEY_{_SFX} "
                f"(or a plain T212_API_KEY) — using the bot's own book")
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
                       f" T212_API_SECRET_{_SFX} (or T212_API_SECRET) is not set, "
                       "and Trading 212 issues a key AND a secret — the key alone "
                       "is rejected. That is the most likely cause.")
            raise T212Error(f"{path}: 401 — the credentials were rejected.{missing} "
                            f"Otherwise: a mistyped pair, or the {ENV} key pair is "
                            f"really the {'live' if ENV == 'demo' else 'demo'} one.")
        if r.status_code == 403:
            raise T212Error(f"{path}: 403 — the key is valid but lacks this "
                            f"permission. Re-generate it with portfolio and "
                            f"history access ticked.")
        if r.status_code == 429:                       # rate limited: back off
            # /equity/metadata/instruments is limited far harder than the rest --
            # roughly one call a minute -- so the steps have to clear that, not
            # just pause politely.
            last = "429 rate limited"
            time.sleep(20 * (attempt + 1))
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
    """'AAPL_US_EQ' -> 'AAPL', 'BRK_B_US_EQ' -> 'BRK.B'.

    The remaining underscore is a share class, not padding: taking the first
    token instead turned BRK_B into BRK, quietly relabelling a class B holding
    as class A. Nothing in the current universe has a class suffix, so this has
    never mattered -- but a mapping that answers with the wrong company is worth
    fixing before it does. Overridable via T212_TICKER_MAP.
    """
    if raw in OVERRIDES:
        return OVERRIDES[raw]
    s = str(raw)
    for suffix in ("_US_EQ", "_EQ", "_US"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.replace("_", ".").upper()


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


def positions(universe=None) -> dict:
    """What the strategy holds, as {TICKER: {'shares', 'avg_price', 'value'}}.

    SCOPING WITHOUT A PIE
    A pie cannot be used to fence the strategy off, because Trading 212's API has
    no way to put money into one -- the pie endpoints set target weights and
    nothing else, and they are deprecated besides. So the strategy's holdings sit
    in the ordinary portfolio alongside everything else, and are picked out two
    ways at once:

      1. Only the NON-PIE part of each holding counts. Every position reports
         `pieQuantity`; whatever a pie owns is somebody else's. This is not
         hypothetical -- an existing pie here holds NVDA, which is in the
         strategy's universe, and without the subtraction the bot would think it
         already owned it and never buy it.
      2. Only names in the frozen universe count, which drops manual buys of
         anything else.

    What this cannot separate: a name in the universe bought by hand outside a
    pie. There is no flag distinguishing it, so it will be read as the
    strategy's. Keep discretionary buys inside a pie, or outside those forty
    names.
    """
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
    parsed_any = False          # did any row yield a ticker and a quantity?
    for it in items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        raw = _pick(it, "ticker", "instrument", "symbol", "instrumentCode")
        qty = _pick(it, "quantity", "ownedQuantity", "shares", "sharesCount")
        if raw is None or qty is None:
            skipped += 1
            continue
        parsed_any = True
        avg = _pick(it, "averagePrice", "avgPrice", "averageEntryPrice", "price")
        cur = _pick(it, "currentPrice", "currentValue", "lastPrice")
        val = _pick(it, "value", "currentValue", "marketValue")
        qty = float(qty)
        # Subtract whatever a pie owns; only the loose part is the strategy's.
        pie_qty = _pick(it, "pieQuantity", default=0.0) or 0.0
        qty = qty - float(pie_qty)
        if qty <= 1e-9:
            continue
        tk = symbol(raw)
        if universe is not None and tk not in universe:
            continue
        avg = float(avg) if avg is not None else 0.0
        # Recompute from the non-pie quantity: a reported value covers the whole
        # holding, pie share included, which would overstate what is ours.
        val = qty * float(cur) if cur is not None else (float(val or 0.0))
        out[tk] = {"shares": qty, "avg_price": avg, "value": float(val),
                   "cost": qty * avg, "raw_ticker": str(raw)}

    if items and not out and not parsed_any:
        # The broker sent rows and not one of them parsed. That is a mapping
        # failure. Reporting it as an empty portfolio would delete the book.
        #
        # `parsed_any` matters: an account that holds nothing from the universe
        # is a legitimately empty result, not a mapping failure, and raising
        # there would block the first rebalance from ever opening a position.
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


def _try_env(env_name: str) -> tuple[bool, str]:
    """One read-only GET against a named environment. Returns (worked, detail).

    Used to answer the question a 401 leaves open: is the pair wrong, or is it
    the right pair pointed at the wrong environment? Guessing costs a round trip
    per attempt; asking costs one request.
    """
    import requests
    base = {"demo": "https://demo.trading212.com/api/v0",
            "live": "https://live.trading212.com/api/v0"}[env_name]
    headers = {"Accept": "application/json"}
    auth = (API_KEY, API_SECRET) if API_SECRET else None
    if auth is None:
        headers["Authorization"] = API_KEY
    try:
        r = requests.get(f"{base}/equity/account/cash", headers=headers,
                         auth=auth, timeout=TIMEOUT)
    except Exception as exc:                            # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return r.status_code == 200, f"HTTP {r.status_code}"


def diagnose_401() -> None:
    """Say which environment the credentials actually belong to, if either."""
    other = "live" if ENV == "demo" else "demo"
    print(f"  Checking whether this pair belongs to the {other} environment "
          f"instead...")
    ok, detail = _try_env(other)
    if ok:
        print(f"\n  ==> It does. These are {other.upper()} credentials, and "
              f"T212_ENV is set to {ENV!r}.")
        print(f"      Set 'Which account' to '{other}' on the Settings page "
              f"(or T212_ENV={other} in an env file) and run this again.")
        return
    print(f"      {other}: {detail} - not that either.")
    print("\n  ==> Both environments reject the pair. In order of likelihood:")
    print("      1. The key and secret are in the wrong fields. The API key is")
    print("         the username half; the secret is the password half.")
    print("      2. One was truncated or mis-copied when it was saved.")
    print("      3. The key was revoked, or its creation never completed.")
    print("      Re-generate the pair in the app and save both halves again.")


def probe() -> int:
    """Print exactly what the account returns, so the mapping above can be
    finished against reality instead of guessed at. Read-only."""
    if not configured():
        print(why_not() or "not configured")
        print("\nSet them on the dashboard's Settings page, or by hand in")
        print("  ~/.config/momentum/momentum.env   (what Settings writes)")
        print("  /etc/momentum-bot.env             (mode 600, set over SSH)")
        print("\nBoth are read automatically -- no need to source anything.")
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
    print("scope    : non-pie holdings in the strategy universe "
          "(a pie cannot be funded through the API, so one is not used)")
    print()

    checks = [("cash", "/equity/account/cash"),
              ("portfolio", "/equity/portfolio"),
              ("pies", "/equity/pies")]
    checks.append(("transactions", "/history/transactions?limit=5"))

    ok, unauthorised = 0, False
    for name, path in checks:
        print(f"--- {name}  GET {path}")
        try:
            d = _get(path, tries=1)
        except T212Error as exc:
            if "401" in str(exc):
                unauthorised = True
            print(f"    FAILED: {exc}\n")
            continue
        except Exception as exc:
            print(f"    FAILED: {type(exc).__name__}: {exc}\n")
            continue
        ok += 1
        if path == "/equity/pies" and isinstance(d, list):
            print(f"    {len(d)} pies on this account:")
            for pie in d:
                if not isinstance(pie, dict):
                    continue
                res = pie.get("result") or {}
                inv = res.get("priceAvgInvestedValue", 0) or 0
                val = res.get("priceAvgValue", 0) or 0
                tag = "  <- empty, likely the one you just made" if not inv else ""
                print(f"      id {pie.get('id')}   invested {inv:>10,.2f}   "
                      f"value {val:>10,.2f}   cash {pie.get('cash', 0) or 0:>6,.2f}"
                      f"{tag}")
            print("\n    Listed for reference only. The bot does not read a pie:")
            print("    anything a pie holds is subtracted from what it considers")
            print("    its own, so these stay out of its way.\n")
            time.sleep(1.2)
            continue
        body = json.dumps(d, indent=1, default=str)
        print("    " + "\n    ".join(body.splitlines()[:40]))
        if len(body.splitlines()) > 40:
            print(f"    … {len(body.splitlines()) - 40} more lines")
        print()
        time.sleep(1.2)          # the API rate-limits hard; do not hammer it

    print(f"{ok}/{len(checks)} endpoints answered.")
    if not ok and unauthorised:
        diagnose_401()
    if ok:
        print("\nNothing above is secret except the key, which is masked. Paste it "
              "back and the field mapping can be finished against the real shapes.")
    return 0 if ok else 1


HERE = os.path.dirname(os.path.abspath(__file__))
INSTRUMENTS_CACHE = os.path.join(HERE, "instruments.json")
INSTRUMENTS_MAX_AGE = 24 * 3600          # the broker's list barely moves


def instruments(max_age: float = INSTRUMENTS_MAX_AGE, refresh: bool = False) -> list:
    """The broker's instrument list, cached on disk.

    Nearly sixteen thousand rows, and Trading 212 rate-limits this endpoint far
    harder than the rest -- two lookups in a row is enough to earn a 429. It is
    also close to static: the codes for forty large caps do not change between
    one command and the next. So it is fetched once and kept.

    Delete instruments.json to force a refresh, or pass refresh=True.
    """
    if not refresh:
        try:
            age = time.time() - os.path.getmtime(INSTRUMENTS_CACHE)
            if age < max_age:
                with open(INSTRUMENTS_CACHE, encoding="utf-8") as fh:
                    rows = json.load(fh)
                if isinstance(rows, list) and rows:
                    return rows
        except (OSError, ValueError):
            pass

    rows = _get("/equity/metadata/instruments", tries=4)
    if not isinstance(rows, list):
        raise T212Error(f"/equity/metadata/instruments returned "
                        f"{type(rows).__name__}, expected a list")
    try:
        tmp = INSTRUMENTS_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
        os.replace(tmp, INSTRUMENTS_CACHE)
    except OSError as exc:
        print(f"  ! could not cache the instrument list ({exc}) — it will be "
              f"fetched again next time, which the broker may rate-limit")
    return rows


# Names Trading 212 still lists under a code the company no longer uses. Each
# one is a documented corporate action, verified by ISIN, not a guess -- a wrong
# entry here buys a different company with real money.
#
#   BKNG  The Priceline Group renamed itself Booking Holdings on 2018-02-21 and
#         the ticker moved PCLN -> BKNG on 2018-02-27 (SEC 8-K). Trading 212 kept
#         the old code. Same security: ISIN US09857L1089, which its EUR listing
#         PCE1d_EQ also carries. The USD line is the one the backtest priced.
RENAMES = {"BKNG": "PCLN_US_EQ"}


def resolve_universe(universe) -> dict:
    """Map each strategy ticker to the instrument code an order must name.

    THIS IS THE PREREQUISITE FOR PLACING ANYTHING. symbol() goes the other way --
    AAPL_US_EQ to AAPL -- and is lossy, so it cannot simply be run backwards. An
    order names the broker's code, and inventing one is how a bot buys the wrong
    company. So the codes come from the broker's own list, and anything ambiguous
    is reported rather than picked.

    Matching uses the fields the rows actually carry: `shortName` first, which is
    the plain ticker, falling back to reducing the code. Candidates are then held
    to type STOCK in USD, which is what the backtest priced -- that alone drops
    the European listings, which trade the same ISIN in another currency at
    another price.

    Returns {"map", "renamed", "missing", "ambiguous", "checked"}.
    Read-only.
    """
    rows = instruments()
    wanted = {t.upper() for t in universe}

    known = {}
    cand = {}
    for it in rows:
        if not isinstance(it, dict):
            continue
        code = str(_pick(it, "ticker", "instrumentCode", "code", default="") or "")
        if not code:
            continue
        kind = str(_pick(it, "type", default="") or "").upper()
        cur = str(_pick(it, "currencyCode", "currency", default="") or "").upper()
        short = str(_pick(it, "shortName", default="") or "").upper()
        known[code] = {"type": kind, "cur": cur, "short": short,
                       "isin": _pick(it, "isin", default=""),
                       "name": _pick(it, "name", default="")}
        if kind not in ("STOCK", "EQUITY"):
            continue
        if cur and cur != "USD":
            continue                       # a European line is a different price
        tk = short or symbol(code)
        if tk in wanted:
            cand.setdefault(tk, []).append(code)

    mapping, ambiguous, renamed = {}, {}, {}
    for tk in sorted(wanted):
        codes = cand.get(tk, [])
        if len(codes) > 1:
            us = [c for c in codes if c.endswith("_US_EQ")]
            codes = us if len(us) == 1 else codes
        if len(codes) == 1:
            mapping[tk] = codes[0]
        elif len(codes) > 1:
            ambiguous[tk] = codes
        elif tk in RENAMES:
            code = RENAMES[tk]
            if code in known:
                mapping[tk] = code
                renamed[tk] = {"code": code, "isin": known[code]["isin"],
                               "name": known[code]["name"]}
            else:
                # The override names something the broker no longer lists. Say so
                # rather than quietly falling through to "missing".
                ambiguous[tk] = [f"{code} (from RENAMES, not in the broker's list)"]

    missing = sorted(wanted - set(mapping) - set(ambiguous))
    return {"map": mapping, "renamed": renamed, "missing": missing,
            "ambiguous": ambiguous, "checked": len(rows)}


def find_instruments(text: str, limit: int = 40) -> list:
    """Every instrument whose code or name contains `text`. Read-only.

    For the case resolve_universe() is built to produce rather than paper over:
    a name it could not resolve. Guessing a code buys the wrong company, so the
    answer comes from the broker's own list.
    """
    rows = instruments()
    needle, out = text.strip().upper(), []
    for it in rows:
        if not isinstance(it, dict):
            continue
        code = str(_pick(it, "ticker", "instrumentCode", "code", default="") or "")
        name = str(_pick(it, "name", "prettyName", default="") or "")
        # shortName is searched separately, not as a fallback for name. Trading
        # 212 renamed Booking's shortName to BKNG while keeping the code
        # PCLN_US_EQ, so searching only code and name reported it as missing when
        # it was there all along.
        short = str(_pick(it, "shortName", default="") or "")
        if (needle in code.upper() or needle in name.upper()
                or needle == short.upper()):
            out.append({"code": code, "name": f"{name} ({short})" if short else name,
                        "type": _pick(it, "type", default=""),
                        "currency": _pick(it, "currencyCode", "currency", default=""),
                        "isin": _pick(it, "isin", default="")})
        if len(out) >= limit:
            break
    return out


def _post(path: str, body: dict, tries: int = 2):
    """POST, with the retry rules an order needs rather than the ones a read has.

    A read that times out can be repeated freely. An order cannot: the request
    may have arrived and been filled with the reply lost on the way back, and a
    blind retry would double the position. So a network failure is reported as
    UNKNOWN and never retried -- the caller reconciles against the broker instead
    of guessing. Only an explicit 429, which means the order was definitely not
    accepted, is safe to send again.
    """
    import requests
    url = f"{BASE}{path}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth = (API_KEY, API_SECRET) if API_SECRET else None
    if auth is None:
        headers["Authorization"] = API_KEY
    for attempt in range(tries):
        try:
            r = requests.post(url, headers=headers, auth=auth, json=body,
                              timeout=TIMEOUT)
        except Exception as exc:                       # noqa: BLE001
            raise T212Error(
                f"UNKNOWN: {path} did not answer ({type(exc).__name__}: {exc}). "
                f"The order may or may not have been placed. Deliberately not "
                f"retried -- check the app, then run --t212-sync.")
        if r.status_code == 429:
            wait = 5.0
            try:
                wait = float(r.headers.get("Retry-After", wait))
            except (TypeError, ValueError):
                pass
            if attempt + 1 < tries:
                time.sleep(min(wait + 0.5, 30))
                continue
            raise T212Error(f"{path}: rate limited; not sent")
        if r.status_code in (200, 201):
            try:
                return r.json()
            except ValueError:
                return {"raw_text": r.text[:400]}
        if r.status_code == 401:
            raise T212Error(f"{path}: 401 — credentials rejected")
        if r.status_code == 403:
            raise T212Error(f"{path}: 403 — this key lacks Orders-Execute, or the "
                            f"account may not trade this instrument")
        raise T212Error(f"{path}: HTTP {r.status_code} — {r.text[:300]}")
    raise T212Error(f"{path}: gave up")


def place_market_order(code: str, quantity: float) -> dict:
    """Buy or sell at the market. A NEGATIVE quantity sells.

    THE ONLY FUNCTION IN THIS FILE THAT SPENDS MONEY. Everything else is a GET.

    `code` must come from resolve_universe() -- the broker's own instrument list
    -- never from string-building. The response shape has not been seen against a
    real account, so it is returned whole for the caller to record rather than
    parsed into a shape that might be wrong.
    """
    if not isinstance(code, str) or not code.strip():
        raise T212Error(f"refusing to order without an instrument code ({code!r})")
    q = float(quantity)
    if q != q or q == 0:                               # NaN, or nothing to do
        raise T212Error(f"refusing to order a quantity of {quantity!r}")
    d = _post("/equity/orders/market", {"ticker": code, "quantity": q})
    return d if isinstance(d, dict) else {"raw": d}


def snapshot(universe=None) -> dict | None:
    """Everything the bot needs, or None. Never raises.

    `universe` is the strategy's ticker list; without it every non-pie holding
    counts, which would read hand-bought positions as the strategy's.
    """
    if not configured():
        return None
    try:
        pos = positions(universe=universe)
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
    free = (c or {}).get("free", 0.0)
    return {"positions": pos, "cash": free, "invested": invested,
            "total": invested + free, "account_cash": c}
