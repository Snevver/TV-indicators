#!/usr/bin/env python3
"""Monthly momentum bot. Runs on your machine, posts the rebalance to Discord.

WHY RUN THIS RATHER THAN A TRADINGVIEW ALERT
The Pine indicator is a reimplementation of the backtest. The two agree today —
that was checked signal by signal on live charts — but they are separate
codebases and could drift. This script computes the ranking with the same logic
the backtest used, so what you are alerted on is what was actually validated. It
also needs no paid TradingView plan, keeps its own record of every rebalance, and
cannot silently stop because an alert expired.

WHAT IT DOES
Run it daily from cron. On any day that is not the first trading day of a new
month it checks, finds nothing to do, and exits quietly. On the first trading day
of a month it re-ranks the 40 names, works out what to buy and sell, posts one
message to Discord, and records the new basket.

    pip install yfinance pandas requests
    export DISCORD_WEBHOOK='https://discord.com/api/webhooks/...'
    python momentum_bot.py --deposit 1000   # tell it what you funded
    python momentum_bot.py                  # the daily run
    python momentum_bot.py --status         # holdings, cash, profit and loss
    python momentum_bot.py --report         # post that snapshot to Discord
    python momentum_bot.py --dry            # decide, print, post nothing
    python momentum_bot.py --test           # post real numbers, save nothing
    python momentum_bot.py --force          # rebalance now, ignoring the date
    python momentum_bot.py --fill MU=0.15@829.50   # correct an assumed fill

WHAT IT KNOWS ABOUT YOUR MONEY
It has no connection to your broker, so it keeps its own book. When it tells you
to rebalance it assumes you filled at that day's closing price and records the
resulting share counts, cash and cost basis. Every later message then marks that
book to the current market, so the numbers stay live without you doing anything.

The book is a model, not the truth. If your fill differed, correct it with
--fill and the P&L follows. If you never bother, the numbers stay close but
slowly drift from the broker's.

State lives in state.json beside this script. Delete it to start fresh; the next
run will then treat every holding as a new buy and forget the book.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- configuration
#
# THE SAME SETTINGS WHEREVER THE BOT IS STARTED FROM
# The dashboard writes ~/.config/momentum/momentum.env; the setup instructions
# put secrets in /etc/momentum-bot.env. systemd loads both for the web service,
# in that order, so the browser wins. The bot's unit used to load only /etc,
# which meant a key, a currency or -- worst of all -- MOMENTUM_TRACK set in the
# browser reached the dashboard and never reached the bot that trades. The two
# could disagree indefinitely, with the dashboard looking authoritative.
#
# Both files are now read here as well, so it no longer matters whether the bot
# was started by systemd or typed at a shell. A real environment variable still
# beats both files, so `T212_ENV=demo python3 momentum_bot.py ...` works for a
# one-off.
#
# This must run BEFORE `import t212`, which reads its configuration at import.
ETC_ENV = "/etc/momentum-bot.env"
USER_ENV = os.path.join(
    os.environ.get("MOMENTUM_CONFIG_DIR")
    or os.path.join(os.path.expanduser("~"), ".config", "momentum"),
    "momentum.env")


def _parse_env_file(path: str):
    """A copy of config.parse_env in the web app. Deliberately duplicated: the
    bot must not import the dashboard, and fifteen lines cost less than that
    coupling. Keep the two in step."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out[k.strip()] = v
    except (FileNotFoundError, OSError):
        return None
    return out


# What the shell really passed in, captured once at import -- before any file has
# been applied. Recomputing this inside the loader would make values it had just
# set look like real exports on a second call.
_PRESET_ENV = frozenset(os.environ)


def _load_env_files() -> list:
    """Apply the env files the way systemd does: in order, later file winning.
    Anything already exported stays untouched. Returns the files actually read."""
    preset = _PRESET_ENV               # what the shell really passed in
    loaded = []
    for path in (ETC_ENV, USER_ENV):
        vals = _parse_env_file(path)
        if vals is None:
            continue
        loaded.append(path)
        for k, v in vals.items():
            if k in preset:
                continue               # an explicit export beats both files
            os.environ[k] = v          # a later file beats an earlier one
    return loaded


ENV_FILES_LOADED = _load_env_files()

# `--env demo|live` picks which Trading 212 account this run acts on. It has to
# be applied here, before `import t212` below reads T212_ENV at import, and it
# also decides which book (TRACK) the run writes. The systemd nightly unit runs
# the bot once per account this way (demo, then live).
#
# Precedence: --env  >  an explicit T212_ENV  >  live. Defaulting to live rather
# than to t212.py's own "demo" keeps --poll and a bare run acting on the real
# account, so a live approval is never left unexecuted because the poller was
# looking at the demo batch file.
if "--env" in sys.argv:
    _ei = sys.argv.index("--env")
    if _ei + 1 < len(sys.argv) and sys.argv[_ei + 1] in ("demo", "live"):
        os.environ["T212_ENV"] = sys.argv[_ei + 1]
os.environ.setdefault("T212_ENV", "live")
if os.environ["T212_ENV"].strip().lower() not in ("demo", "live"):
    os.environ["T212_ENV"] = "live"
# The panic button only ever means the real account. It takes no --env, so pin
# it here rather than trust whatever T212_ENV happened to be.
if "--kill" in sys.argv:
    os.environ["T212_ENV"] = "live"

# Optional broker link. A missing, broken or half-written t212.py must not stop
# the bot running — the whole point of it is that it is not required.
try:
    import t212
except Exception as _t212_exc:                       # noqa: BLE001
    t212 = None
    _T212_IMPORT_ERROR = f"{type(_t212_exc).__name__}: {_t212_exc}"
else:
    _T212_IMPORT_ERROR = ""

# Approval by reaction. Optional in exactly the same way: without it the bot
# posts to the webhook and you trade by hand, which is the default.
try:
    import discord_api
except Exception as _dc_exc:                         # noqa: BLE001
    discord_api = None
    _DISCORD_IMPORT_ERROR = f"{type(_dc_exc).__name__}: {_dc_exc}"
else:
    _DISCORD_IMPORT_ERROR = ""
STATE = os.path.join(HERE, "state.json")
LOG = os.path.join(HERE, "rebalances.csv")
HISTORY = os.path.join(HERE, "history.csv")     # one row per day per track
LATEST = os.path.join(HERE, "latest.json")      # the dashboard's render cache
DEPOSITS = os.path.join(HERE, "deposits.csv")   # dated cash-in events, for the
#                                                 ETF benchmark (see tracker.py)

# Frozen at validation time. Changing this changes the strategy — if you edit it,
# the measured results no longer describe what you are running.
UNIVERSE = ["AAPL", "GOOGL", "AMZN", "GOOG", "MSFT", "BAC", "XOM", "JPM", "INTC",
            "NFLX", "C", "CSCO", "WFC", "GE", "PFE", "JNJ", "CVX", "T", "QCOM",
            "GS", "WMT", "PG", "IBM", "ORCL", "VZ", "DIS", "HD", "MRK", "BA",
            "BKNG", "MU", "CMCSA", "KO", "MCD", "CAT", "SLB", "COP", "AMGN",
            "UNH", "NVDA"]
LOOKBACK = 126      # trading days of momentum
SKIP = 21           # skip the most recent month
HOLD = 8            # positions

# Sizing and bookkeeping. None of this touches the ranking — the strategy is the
# same whatever these say.
#
# Prices come from yfinance in US dollars. Both books are real Trading 212
# accounts in the account currency (EUR here), so prices are converted once --
# see live_fx() -- and every figure is then real money rather than a dollar
# shadow of a euro account.
CURRENCY = "USD"        # default until live_fx() resolves the account currency
SYM = "$"               # reassigned to the account's symbol once resolved


_FX = {}               # cached {rate, ccy, sym, err} for the account currency


def live_fx() -> dict:
    """Rate to turn a USD price into the live account's currency, once, cached.

    Returns {"rate": account-ccy per USD, "ccy": "EUR", "sym": "€", "err": ""}.
    {"rate": 1.0, "ccy": "USD", "sym": "$", "err": ""} when there is no broker or
    the account is already USD. On a real failure to price a non-USD account,
    rate falls back to 1.0 and "err" explains why -- callers that place orders
    refuse in that case rather than size a rebalance wrong.
    """
    if _FX:
        return _FX
    _FX.update(rate=1.0, ccy="USD", sym="$", err="")
    if t212 is None or not t212.configured():
        return _FX
    try:
        acc = (t212.account_currency() or "").upper()
    except Exception as exc:                              # noqa: BLE001
        _FX["err"] = f"could not read the account currency ({exc})"
        return _FX
    if not acc or acc == "USD":
        _FX["ccy"] = acc or "USD"
        return _FX
    try:
        import numpy as np
        import yfinance as yf
        raw = yf.download(f"{acc}USD=X", period="5d", progress=False,
                          auto_adjust=False)
        # yfinance hands back a DataFrame or a Series depending on version;
        # flatten to the last finite Close either way.
        arr = np.asarray(raw["Close"], dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if not len(arr):
            raise ValueError(f"no {acc}USD=X data came back")
        usd_per_unit = float(arr[-1])
        if not (0.01 < usd_per_unit < 100):
            raise ValueError(f"implausible {acc}USD rate {usd_per_unit}")
    except Exception as exc:                              # noqa: BLE001
        _FX.update(ccy=acc, sym="$",
                   err=f"could not get the {acc}/USD rate ({exc})")
        return _FX
    _FX.update(rate=1.0 / usd_per_unit, ccy=acc,
               sym={"EUR": "€", "GBP": "£"}.get(acc, acc + " "), err="")
    return _FX


def to_live(prices: dict) -> dict:
    """USD price dict -> the live account's currency."""
    r = live_fx()["rate"]
    return prices if r == 1.0 else {tk: p * r for tk, p in prices.items()}

# MOMENTUM_MIN_ORDER used to sit here, defaulting to 1, and plan() skipped any
# buy worth less than it. Removed on request: it was one more knob for a case
# that barely arises, since a contribution split eight ways is rarely small.
#
# WHAT IT USED TO ABSORB: Trading 212 will not fill a fractional order below
# about one unit of currency. Nothing now stops the bot printing a line for less
# than that, so if a rebalance ever asks for EUR 0.40 of something the broker
# will refuse it. Skip the line -- the cash stays on the book and goes into next
# month -- or put the floor back here if it starts happening often.

# What the strategy starts with, and what it adds each month. Both are drawn
# from Trading 212 free funds when you approve the buys -- the bot moves no money
# itself, it just sizes the orders to include them and the broker debits free
# funds for the purchases.
#
#   START_BUDGET : seeds an empty live book on the very first rebalance only,
#                  then inert (deposited is set, the guard below stops it).
#   MONTHLY      : added on every rebalance after the first, credited to the
#                  book's cash on the assumption it is sitting in free funds and
#                  spread over the whole new basket by plan().
#
# deposited rises by the same amount so the money is never read as profit. If a
# standing order bounces, the book briefly holds shares it did not pay for and
# the tail order trims itself to what was really there; correct with --fill.
START_BUDGET = float(os.environ.get("MOMENTUM_START_BUDGET", "0") or 0)
MONTHLY = float(os.environ.get("MOMENTUM_MONTHLY", "0") or 0)

# TWO THINGS THAT USED TO BE SETTINGS, AND WHY THEY ARE NOT ANY MORE
#
# Rebalance style. The choice was between resetting all eight to an equal slice
# every month, and trading only the names that changed so survivors run. Drift
# won seven of eight test windows and won the full 2005-2026 history with a
# SMALLER worst fall (55.1% against 59.7%), while placing far fewer orders --
# which on a euro account paying 0.15% per conversion is money as well. Its cost
# is concentration: the largest position ran at a median 17.6% against a fixed
# 12.5%, peaking at 37.8%. Bounded, because the ranking evicts a name eventually
# either way. Drift is now the only behaviour.
#
# Fractional shares. Never a performance setting -- it described whether the
# broker would sell part of a share. Trading 212 does. Whole-share mode at a
# EUR 1,000 account was not merely worse but unusable: six of eight names cost
# more than a slice, so the account could not buy them at all.
#
# IF THE BROKER EVER STOPS SELLING PART SHARES, the unbuyable check that used to
# live here has to come back -- nothing warns you now, because with fractional
# orders nothing can be unbuyable.

# The bot places orders at the broker: the demo account automatically, the live
# account after a Discord reaction. This was once a toggle (MOMENTUM_AUTOTRADE);
# it is not any more, because trading both accounts is the whole point of the
# bot. A run where the plumbing is not ready still fails loudly rather than
# placing something it cannot verify -- see approval_ready() and the batch
# section further down. MOMENTUM_AUTOTRADE in an env file is now inert.
AUTOTRADE = True

# The kill switch. ON: sell every strategy position at market at once and freeze
# all trading until it is cleared. Independent of AUTOTRADE -- "get me out" must
# not depend on another toggle -- so it acts whenever a live order-capable key is
# configured. kill_switch() writes a `kill_done` marker on the live book so it
# runs once, not every poll; clearing MOMENTUM_KILL clears the marker.
KILL = os.environ.get("MOMENTUM_KILL", "").strip().lower() in (
    "1", "on", "yes", "true")

# Two books are kept side by side, one per real Trading 212 account:
#   demo : the practice account. Traded automatically every month (fake money,
#          no approval), so it is a real-execution preview of what live will do.
#   live : the real account. Traded only after a Discord reaction.
# A single run acts on one of them. TRACK follows t212.ENV, which follows
# T212_ENV / --env (applied above, before t212 was imported), so the book this
# run writes always matches the account it talked to. The systemd unit runs the
# bot once per account.
TRACKS = ("demo", "live")
TRACK = (getattr(t212, "ENV", None)
         or os.environ.get("T212_ENV", "").strip().lower() or "live")
if TRACK not in TRACKS:
    raise SystemExit(f"T212_ENV must be 'demo' or 'live', not {TRACK!r}")

GREEN = 0x3BA55D    # something changed
BLURPLE = 0x5865F2  # ranked, nothing to do
AMBER = 0xF0A020    # a test: real numbers, nothing saved, do not trade it


# One track's book. Every money function below takes one of these, not the whole
# state file.
EMPTY_BOOK = {"basket": [], "last_rebalance": None, "last_rebalance_month": None,
              "positions": {},    # ticker -> shares held
              "book": {},         # ticker -> what those shares cost
              "cash": 0.0,        # funded but not currently in a stock
              "deposited": 0.0,   # money you put in, so growth can exclude it
              "realised": 0.0,    # profit and loss already banked by selling
              "equity": []}       # [date, account value] at each rebalance

EMPTY = {"schema": 2, "tracks": {}}


def _blank() -> dict:
    return json.loads(json.dumps(EMPTY_BOOK))


def load_state() -> dict:
    """The whole state file, both tracks, migrated forward if needed."""
    if os.path.exists(STATE):
        with open(STATE) as fh:
            s = json.load(fh)
    else:
        s = json.loads(json.dumps(EMPTY))

    if "tracks" not in s:
        # A schema-1 file: one flat book. It predates the broker link, so the
        # safest home for it is the live track; demo starts fresh.
        s = {"schema": 2,
             "tracks": {"live": {k: s.get(k, _blank()[k]) for k in EMPTY_BOOK},
                        "demo": _blank()}}

    # The simulated 'paper' book was retired when the demo account took its
    # place. Drop it so nothing downstream renders a stale third track.
    s.get("tracks", {}).pop("paper", None)

    for name in TRACKS:
        bk = s["tracks"].setdefault(name, _blank())
        for k, v in EMPTY_BOOK.items():
            bk.setdefault(k, json.loads(json.dumps(v)))
    s["schema"] = 2
    return s


def book(state: dict, name: str = "") -> dict:
    """One track's book. Defaults to the track this run is trading."""
    return state["tracks"][name or TRACK]


def save_state(s: dict) -> None:
    """Write via a temp file in the same directory, then rename.

    The dashboard reads state.json while the bot may be writing it. A plain
    truncate-and-write hands the reader a half-finished file; os.replace is
    atomic, so a reader sees either the old file or the new one.
    """
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(s, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, STATE)


def fetch(days: int = 400):
    import yfinance as yf
    import pandas as pd
    raw = yf.download(UNIVERSE, period=f"{days}d", progress=False, threads=True,
                      auto_adjust=False, group_by="ticker")
    cols = {}
    for tk in UNIVERSE:
        try:
            s = (raw[tk] if isinstance(raw.columns, pd.MultiIndex) else raw)["Close"]
            s = s.dropna()
            if len(s) > LOOKBACK + SKIP + 5:
                cols[tk] = s
        except (KeyError, ValueError):
            continue
    if len(cols) < HOLD * 2:
        raise SystemExit(f"only {len(cols)} usable tickers - aborting rather than "
                         f"ranking a broken universe")
    return pd.DataFrame(cols).sort_index()


def rank(px):
    """Momentum over LOOKBACK days ending SKIP days ago. Same as the backtest."""
    if len(px) < LOOKBACK + SKIP + 1:
        raise SystemExit("not enough history")
    recent = px.iloc[-1 - SKIP]
    past = px.iloc[-1 - SKIP - LOOKBACK]
    ok = recent.notna() & past.notna() & (past > 0)
    return ((recent / past - 1.0)[ok]).sort_values(ascending=False)


def due(px, bk) -> bool:
    """True on the first trading day of a month we have not rebalanced in.

    Keyed off the newest BAR, not the wall clock, so holidays and weekends need
    no special handling and a run at any hour behaves the same.
    """
    last_bar = px.index[-1]
    tag = f"{last_bar.year}-{last_bar.month:02d}"
    if bk.get("last_rebalance_month") == tag:
        return False

    if bk.get("last_rebalance_month"):
        # Warm start. Any day in a month we have not traded yet is fair game:
        # if the machine was off for the first three days of the month we still
        # want to catch up rather than skip the month entirely.
        return True

    # Cold start — an empty book, which is what a fresh --deposit leaves behind.
    # Here "a month we have not rebalanced in" is every month, so the check above
    # is not enough on its own: without this, funding the account on the 25th
    # opens a position on the 25th. Require the newest bar to genuinely be the
    # first trading day of its month.
    seen = sum(1 for d in px.index
               if (d.year, d.month) == (last_bar.year, last_bar.month))
    return seen <= 1


# ---------------------------------------------------------------- the book --
#
# Everything below models the account. None of it can change which eight names
# get picked — that happens in rank(), from prices alone.


def money(x: float) -> str:
    return f"{SYM}{x:,.2f}"


def mark(bk, prices) -> dict:
    """Value the book at the latest prices."""
    rows = {}
    for tk, sh in bk["positions"].items():
        if sh <= 0 or tk not in prices:
            continue
        value = sh * prices[tk]
        cost = bk["book"].get(tk, 0.0)
        rows[tk] = {"shares": sh, "price": prices[tk], "value": value, "cost": cost,
                    "pnl": value - cost,
                    "pnl_pct": (value / cost - 1) * 100 if cost else 0.0}
    invested = sum(r["value"] for r in rows.values())
    total = invested + bk["cash"]
    dep = bk["deposited"]
    return {"rows": rows, "invested": invested, "cash": bk["cash"], "total": total,
            "deposited": dep,
            "pnl": total - dep,
            "pnl_pct": (total / dep - 1) * 100 if dep else 0.0,
            "realised": bk["realised"],
            "unrealised": sum(r["pnl"] for r in rows.values())}


# A fully-invested rebalance sized to the last cent has no room for Trading 212's
# ~0.15% currency-conversion fee or for quantity rounding, so the final buy of the
# batch is rejected for insufficient funds. Hold back this fraction of the
# investable cash; it carries into next month.
CASH_BUFFER = float(os.environ.get("MOMENTUM_CASH_BUFFER", "0.005") or 0.005)

# Trading 212's EUR->USD conversion fee, charged per order on a non-USD account.
# It is real money spent and gone, but averagePrice does not include it, so the
# broker's cost basis plus its free funds fall short of what was paid in by
# roughly this fraction of the holdings. reconcile() subtracts an estimate when
# it re-squares cash, so the account figure does not float a fee it already paid.
# 0 on a USD account, or to turn the estimate off and rely on --fill.
FX_FEE_BPS = float(os.environ.get("MOMENTUM_FX_FEE_BPS", "15") or 15)

# Trading 212 reserves a market buy's cash -- plus a slippage cushion -- until it
# fills. Fired back-to-back, eight reservations stack before any release and the
# last order is refused even though the money is really there. So: a short pause
# between orders (fills clear in seconds during market hours), and on an explicit
# insufficient-funds rejection -- which means the order was NOT placed -- wait for
# the earlier fills to settle and try that same order again.
ORDER_GAP_SEC = float(os.environ.get("MOMENTUM_ORDER_GAP", "2") or 2)
FUNDS_RETRY = (2, 8.0)           # (attempts, seconds to wait) before trimming to fit


def plan(bk, prices, basket, total, contribution: float = 0.0,
         reserve: float = 0.0) -> list:
    """The orders that move the current book to the new basket.

    Whatever the sells raised, plus any idle cash, is split over the names that
    are new this month; survivors are not trimmed to fund them, which is what
    lets winners run. Returns (ticker, delta_shares, cash_delta) with sells
    first, so the cash to pay for the buys exists before they are applied.

    `contribution` is this month's new money, which bk["cash"] already holds. It
    is taken back out of the pot that funds the arrivals and spread over the
    whole basket instead -- survivors included. Measured against putting it all
    into the arrivals, that won seven of eight windows and the full history, by
    about 1.3%. A narrow win, but it is also what a Trading 212 pie does with a
    standing order. With contribution=0 this function is unchanged.

    `reserve` (0..1) holds back that fraction of the cash being deployed, so a
    real broker's fees and rounding do not sink the last order. 0.0 for paper.
    """
    pos = bk["positions"]
    sells = []
    for tk, sh in sorted(pos.items()):
        if sh > 0 and tk not in basket:
            sells.append((tk, -sh, sh * prices.get(tk, 0.0)))

    # A name with no price today cannot be sized, so it is skipped rather than
    # guessed at. Sells above already tolerate this; spreading a contribution
    # over the whole basket is the first thing that can reach a survivor.
    def priced(tickers):
        return [t for t in tickers if prices.get(t, 0.0) > 0]

    keep = 1.0 - max(0.0, min(reserve, 0.5))
    buys = {}
    arriving = priced(t for t in basket if pos.get(t, 0.0) <= 0)
    pot = (bk["cash"] + sum(o[2] for o in sells) - contribution) * keep
    if arriving and pot > 0:
        each = pot / len(arriving)
        for tk in arriving:
            buys[tk] = buys.get(tk, 0.0) + each / prices[tk]
    spread_over = priced(basket)
    if contribution > 0 and spread_over:
        each = contribution * keep / len(spread_over)
        for tk in spread_over:
            buys[tk] = buys.get(tk, 0.0) + each / prices[tk]

    orders = list(sells)
    for tk in basket:                      # basket order, so the message reads well
        sh = buys.get(tk, 0.0)
        if sh > 0:
            orders.append((tk, sh, -sh * prices[tk]))
    return orders


def apply_orders(bk, orders, prices) -> None:
    """Record the orders as filled at `prices`. Cost basis moves proportionally
    on a sell, so realised and unrealised P&L never double-count."""
    for tk, dsh, dcash in orders:
        held = bk["positions"].get(tk, 0.0)
        cost = bk["book"].get(tk, 0.0)
        if dsh < 0:                                   # selling
            sold = min(-dsh, held)
            share = sold / held if held else 0.0
            bk["realised"] += sold * prices[tk] - cost * share
            bk["book"][tk] = cost * (1 - share)
            bk["positions"][tk] = held - sold
        else:                                         # buying
            bk["book"][tk] = cost + dsh * prices[tk]
            bk["positions"][tk] = held + dsh
        bk["cash"] += dcash
        if bk["positions"].get(tk, 0.0) <= 1e-9:
            bk["positions"].pop(tk, None)
            bk["book"].pop(tk, None)
    bk["cash"] = max(round(bk["cash"], 6), 0.0)


def parse_fill(spec: str):
    """'MU=0.15@829.50' -> ('MU', 0.15, 829.50). Shares may be negative to
    record a sale you made that the bot does not know about."""
    try:
        tk, rest = spec.split("=", 1)
        sh, pr = rest.split("@", 1)
        return tk.strip().upper(), float(sh), float(pr)
    except ValueError:
        raise SystemExit(f"--fill wants TICKER=SHARES@PRICE, got {spec!r}")


def refresh(state, snap=None) -> bool:
    """Mirror the broker into this run's book (demo or live). Returns True if
    anything was read.

    Each run talks to one Trading 212 account (t212.ENV / --env) and mirrors it
    into the matching book. Silent when there is no key — that is the normal
    case and not a problem.

    `snap` lets a caller that has ALREADY fetched a broker snapshot pass it in
    rather than have this fetch a second one -- /equity/portfolio is rate
    limited to one call every few seconds, so two back to back is asking for a
    429.
    """
    if snap is None:
        snap = broker()
    if snap is None:
        return False
    live = book(state, TRACK)
    # A broker that reports nothing while the book holds positions is far more
    # likely to be a mapping or permissions problem than a portfolio you emptied
    # by hand. Never let the automatic path act on it — --t212-sync --force is
    # how you say you really did sell everything.
    if live["positions"] and not snap["positions"]:
        print(f"  ! Trading 212 ({t212.ENV}) reports no positions, but the "
              f"{TRACK} book holds {len(live['positions'])}. Not adopting that - "
              f"it would erase the book. Check --t212-probe, or --t212-sync "
              f"--force if you really did sell everything.")
        return False
    diffs = reconcile(live, snap, adopt=True)
    save_state(state)
    where = "account"
    print(f"  [Trading 212 {t212.ENV}/{where}] {len(snap['positions'])} positions"
          + (f", {len(diffs)} corrected" if diffs else ", already matching"))
    return True


def broker() -> dict | None:
    """The broker's view, or None if it is not set up or did not answer."""
    if t212 is None:
        if _T212_IMPORT_ERROR:
            print(f"  ! t212.py did not load ({_T212_IMPORT_ERROR}) - using the "
                  f"bot's own book")
        return None
    try:
        if not t212.configured():
            return None
        return t212.snapshot(universe=UNIVERSE)
    except Exception as exc:                          # belt and braces
        print(f"  ! Trading 212 link failed ({type(exc).__name__}: {exc}) - "
              f"using the bot's own book")
        return None


def t212_strategy_value(snap) -> dict:
    """The strategy's holdings from a broker snapshot, valued in the account
    currency and SCOPED to the non-pie universe positions -- so a pie, or a
    manual buy elsewhere on the same account, cannot leak into the strategy's
    numbers.

    Per position: EUR value = the USD market value at today's rate; EUR
    unrealised = Trading 212's own ppl + fxPpl (exact, per line); EUR cost =
    value - unrealised. Only the value carries the small yfinance-rate
    approximation, and it cancels out of unrealised. Returns
    {ticker: {"value": eur, "cost": eur, "shares": n}}, or {} with no snapshot.
    """
    pos = (snap or {}).get("positions") or {}
    if not pos:
        return {}
    fx = live_fx()["rate"]
    out = {}
    for tk, p in pos.items():
        sh = float(p.get("shares") or 0.0)
        val_usd = float(p.get("value") or 0.0)
        if sh <= 0 or val_usd <= 0:
            continue
        value_eur = val_usd * fx
        unrl = float(p.get("ppl_eur") or 0.0) + float(p.get("fxppl_eur") or 0.0)
        out[tk] = {"value": value_eur, "cost": value_eur - unrl, "shares": sh}
    return out


def t212_held_prices(snap) -> dict:
    """Per-share prices in the account currency from Trading 212's own quotes,
    so the dashboard's holdings value matches the app rather than a yfinance
    mark. {} with no snapshot, so callers fall back to the yfinance mark."""
    return {tk: v["value"] / v["shares"]
            for tk, v in t212_strategy_value(snap).items() if v["shares"] > 0}


def reconcile(bk, snap, adopt: bool, resquare_cash: bool = True) -> list:
    """Compare the bot's book with the broker's. Returns the differences.

    With adopt=False nothing changes — this is the report --t212-check prints.
    With adopt=True the broker wins, because it is the one that actually holds
    the shares. Money paid in is never touched: the broker cannot know what you
    funded versus what you earned, and overwriting it would turn a deposit into
    a profit.

    `resquare_cash` gates the cash re-square below. It re-derives cash from a
    cost basis built out of the broker's per-line value and its own EUR ppl/
    fxPpl, but that value is converted through OUR fx quote (a cached, minutes-
    stale yfinance rate), not the broker's own. Off-hours, when a held name's
    price is frozen but EUR/USD keeps trading, that mismatch alone can move
    cash by several euros with nothing in the account actually changing.
    refresh_live() calls this every ~90s and passes False so that noise never
    reaches the dashboard; the full run still re-squares once a day, when a
    fresh fx quote is closer to whatever rate the broker used.
    """
    diffs, mine = [], bk["positions"]
    theirs = snap["positions"]
    for tk in sorted(set(mine) | set(theirs)):
        a, b = mine.get(tk, 0.0), theirs.get(tk, {}).get("shares", 0.0)
        # Scale the tolerance: brokers round share counts for display, and a
        # difference of a millionth of a share is noise, not a discrepancy.
        if abs(a - b) > max(1e-6, 1e-4 * max(a, b)):
            diffs.append((tk, a, b))
    # Cash is deliberately NOT compared, and never adopted. See below.

    if adopt:
        bk["positions"] = {tk: p["shares"] for tk, p in theirs.items()}

        # COST BASIS: from Trading 212's own per-line figures, SCOPED to the
        # non-pie universe positions.
        #
        # This used to spread /equity/account/cash's `invested` across the
        # names. That figure is account-WIDE: on a live account that also holds
        # a Vanguard pie it is the strategy's basis PLUS EUR2,080 of pie, and
        # every strategy name would inherit a slice of the pie. t212_strategy_
        # value() instead values each non-pie position on its own -- USD market
        # value at today's rate, minus Trading 212's exact per-line ppl+fxPpl
        # -- so a pie or a manual buy elsewhere cannot leak in, and the basis
        # only moves when a fill does.
        sv = t212_strategy_value(snap)
        if sv:
            bk["book"] = {tk: round(sv[tk]["cost"], 6) for tk in sv}
        else:
            fx = live_fx()["rate"]
            bk["book"] = {tk: round(float(p.get("cost") or 0.0) * fx, 6)
                          for tk, p in theirs.items()}

        # CASH: re-square the ledger against that basis.
        #
        # THE BROKER OWNS THE POSITIONS. THE BOT OWNS THE CASH. Trading 212
        # reports one pool of free funds for the whole account, and the
        # strategy is only a part of it, so that number is never adopted as the
        # strategy's cash.
        #
        # But cash is a LEDGER, and once the real cost basis is known the
        # identity  cash = deposited + realised - sum(basis) - fees  has to
        # hold: every euro paid in is in a position, is cash, or was a fee.
        # The plan sizes orders at the assumed close; the fills land a little
        # cheaper or dearer, and that gap has been silently missing from cash
        # -- EUR5 the demo book thought it had spent and had not.
        #
        # `fees` is Trading 212's EUR->USD conversion charge (FX_FEE_BPS,
        # ~0.15%). averagePrice does not include it, so without this term the
        # account figure floats a fee it already paid: on the demo book, the
        # whole account was down EUR0.84 while the dashboard read +EUR1.43.
        # An estimate on the current holdings, not a per-order tally -- close
        # for a drift book that mostly bought once, and --fill still corrects
        # a fill exactly. Zero on a USD account (no conversion happens).
        if bk["book"] and resquare_cash:
            basis = sum(bk["book"].values())
            fee = (basis * FX_FEE_BPS / 10_000.0
                   if live_fx().get("ccy", "USD") != "USD" else 0.0)
            raw = round(bk["deposited"] + bk["realised"] - basis - fee, 2)
            if -1.0 <= raw <= bk["deposited"] * 1.25 and abs(raw - bk["cash"]) >= 0.01:
                print(f"  cash re-squared to the broker's cost basis"
                      f"{f' (less ~{money(fee)} FX fee)' if fee else ''}: "
                      f"{money(bk['cash'])} -> {money(max(raw, 0.0))}")
                bk["cash"] = max(raw, 0.0)

        if not bk["deposited"] and not START_BUDGET:
            # Nothing declared and no Starting amount set. The account total is
            # not a safe answer either -- it includes everything else you own --
            # so say so and change nothing. (With START_BUDGET set the opening
            # rebalance seeds it moments from now, so this would just be noise.)
            print(f"  ! nothing has been paid in on record, so there is no "
                  f"starting balance to measure against.\n"
                  f"    Set a Starting amount on the Settings page, or run "
                  f"--deposit AMOUNT. The account holds {money(snap['total'])}, "
                  f"but that is the whole account, not this strategy.")
    return diffs


def post(webhook: str, payload: dict) -> None:
    import requests
    r = requests.post(webhook, json=payload, timeout=20)
    if r.status_code not in (200, 204):
        raise SystemExit(f"discord rejected the post ({r.status_code}): {r.text[:200]}")


def next_month_label(bar) -> str:
    """'October 2026' — the month the next rebalance falls in.

    Deliberately not a date. The first trading day of a month is not always the
    1st, and naming a specific day here would occasionally be a holiday.
    """
    y, m = (bar.year + 1, 1) if bar.month == 12 else (bar.year, bar.month + 1)
    return f"{calendar.month_name[m]} {y}"


def render_orders(orders, prices) -> list:
    """The orders as lines you can read straight onto a broker screen."""
    out = []
    for tk, dsh, dcash in orders:
        verb = "SELL" if dsh < 0 else "BUY "
        # Always the real quantity. Formatting a 0.68-share order as "1" because
        # the account is in whole-share mode would put a wrong number on a broker
        # screen — and leftover part-shares from an earlier run still need selling.
        qty = f"{abs(dsh):,.4f}".rstrip("0").rstrip(".")
        out.append(f"  {verb} {qty:>10} {tk:<5} @ {money(prices[tk]):>11}"
                   f"  = {money(abs(dcash))}")
    return out


def render_book(m) -> list:
    """The account as it stands, richest position first."""
    out = []
    for tk, r in sorted(m["rows"].items(), key=lambda kv: -kv[1]["value"]):
        w = r["value"] / m["total"] * 100 if m["total"] else 0
        qty = f'{r["shares"]:.4f}'.rstrip("0").rstrip(".")
        out.append(f"  {tk:<5} {qty:>9} sh  {money(r['value']):>11}  "
                   f"{w:>4.1f}%  {r['pnl_pct']:>+6.1f}%")
    return out


def render_plain(bar, buys, sells, basket, scores, m=None, orders=None,
                 prices=None) -> str:
    """What goes to the console and the journal. Kept readable in a terminal."""
    lines = [f"Momentum rebalance {bar.date()}",
             f"  BUY  : {', '.join(buys) or '-'}",
             f"  SELL : {', '.join(sells) or '-'}",
             f"  HOLD : {', '.join(basket)}"]
    if m and m["deposited"]:
        lines += ["",
                  f"  ACCOUNT   : {money(m['total'])}   "
                  f"({m['pnl']:+,.2f} = {m['pnl_pct']:+.1f}% on {money(m['deposited'])} in)",
                  f"  invested  : {money(m['invested'])}",
                  f"  cash      : {money(m['cash'])}",
                  f"  slice      : {money(m['total'] / HOLD)} per name"]
    if orders and prices is not None:
        lines += ["", f"  ORDERS ({len(orders)}):"] + render_orders(orders, prices)
    lines.append("")
    for i, (tk, mo) in enumerate(scores.head(12).items(), 1):
        lines.append(f"  {i:>2} {tk:<6} {mo * 100:>7.1f}%" + ("  <- hold" if i <= HOLD else ""))
    return "\n".join(lines)


def clip(v: str, limit: int = 1024) -> str:
    """Discord rejects a field value over 1024 characters."""
    if len(v) <= limit:
        return v
    cut = v[:limit - 24].rsplit("\n", 1)[0]
    return cut + "\n… truncated\n```"


def render_embed(bar, buys, sells, basket, scores, first: bool,
                 test: bool = False, m=None, orders=None, prices=None) -> dict:
    """The Discord payload. An embed rather than a wall of text: the changes are
    the thing you act on, so they go at the top in a diff block, where Discord
    colours additions green and removals red on its own."""
    changed = bool(buys or sells)

    if first:
        change = "```diff\n" + "\n".join(f"+ {t}" for t in basket) + "\n```"
        change_name = f"Opening position - {len(basket)} names"
    elif changed:
        rows = [f"+ {t}" for t in buys] + [f"- {t}" for t in sells]
        change = "```diff\n" + "\n".join(rows) + "\n```"
        change_name = f"Changes - {len(buys)} in, {len(sells)} out"
    else:
        change = "```\nNo change. Same eight names as last month.\n```"
        change_name = "Changes - none"

    held = [f"{i:>2}  {tk:<5} {m * 100:>7.1f}%"
            for i, (tk, m) in enumerate(scores.head(HOLD).items(), 1)]
    bench = [f"{i:>2}  {tk:<5} {m * 100:>7.1f}%"
             for i, (tk, m) in enumerate(scores.iloc[HOLD:HOLD + 4].items(), HOLD + 1)]

    fields = [{"name": change_name, "value": change, "inline": False}]

    if orders and prices is not None:
        rows = render_orders(orders, prices)
        fields.append({"name": f"Orders - {len(orders)} to place",
                       "value": clip("```\n" + "\n".join(rows) + "\n```"),
                       "inline": False})

    size = f" · {money(m['total'] / HOLD)} each" if m and m["total"] else ""
    fields += [
        {"name": f"Portfolio - equal weight{size}",
         "value": "```\n" + "\n".join(held) + "\n```", "inline": True},
        {"name": "Next in line",
         "value": "```\n" + "\n".join(bench) + "\n```", "inline": True},
    ]

    if m and m["deposited"]:
        sign = "+" if m["pnl"] >= 0 else "-"
        fields.append({
            "name": "Your account",
            "value": ("```diff\n"
                      f"{sign} {money(m['total'])}   {m['pnl_pct']:+.1f}%\n"
                      "```"
                      f"in {money(m['deposited'])} · "
                      f"invested {money(m['invested'])} · cash {money(m['cash'])}"),
            "inline": False})

    title = "Opening position" if first else "Monthly rebalance"
    if test:
        title = "TEST - " + title
    footer = ("Test message · nothing saved · do not trade this" if test else
              f"Buy near the US close · next rebalance {next_month_label(bar)}")

    return {"embeds": [{
        "title": title,
        "description": f"**{bar.strftime('%-d %B %Y')}** · 6-month momentum, "
                       f"top {HOLD} of {len(UNIVERSE)}",
        "color": AMBER if test else (GREEN if (changed or first) else BLURPLE),
        "fields": fields,
        "footer": {"text": footer},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}


def render_snapshot(bar, m, bk) -> dict:
    """A between-rebalances portfolio update. No decisions in it — just where
    the account stands right now."""
    rows = render_book(m) or ["  (nothing held)"]
    sign = "+" if m["pnl"] >= 0 else "-"
    fields = [
        {"name": "Value",
         "value": ("```diff\n"
                   f"{sign} {money(m['total'])}   {m['pnl_pct']:+.1f}%\n```"
                   f"in {money(m['deposited'])} · "
                   f"open {m['unrealised']:+,.2f} · banked {m['realised']:+,.2f}"),
         "inline": False},
        {"name": f"Holdings - {len(m['rows'])} names · cash {money(m['cash'])}",
         "value": clip("```\n" + "\n".join(rows) + "\n```"), "inline": False},
    ]
    return {"embeds": [{
        "title": "Portfolio",
        "description": f"**{bar.strftime('%-d %B %Y')}** · marked at the latest close",
        "color": GREEN if m["pnl"] >= 0 else 0xC0392B,
        "fields": fields,
        "footer": {"text": f"Held since {bk.get('last_rebalance') or '-'} · "
                           f"next rebalance {next_month_label(bar)}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}


# ---------------------------------------------------- the autotrade embeds
#
# The batch messages -- propose, placed, skipped, expired, kill -- go out as
# coloured Discord embeds with structured fields, matching render_embed() above.
# One builder, one accent per kind.
GREY = 0x6B7280
RED = 0xC0392B


def _nd(s) -> str:
    """No em dashes in anything a person reads."""
    return str(s).replace(" — ", " - ").replace("—", "-")


def _embed(title, color, desc="", fields=None, footer="") -> dict:
    e = {"title": _nd(title), "color": color,
         "timestamp": datetime.now(timezone.utc).isoformat()}
    if desc:
        e["description"] = _nd(desc)
    if fields:
        e["fields"] = [{"name": _nd(f["name"]),
                        "value": clip(_nd(f["value"])),
                        "inline": f.get("inline", False)} for f in fields]
    if footer:
        e["footer"] = {"text": _nd(footer)}
    return e


def _block(lines) -> str:
    return "```\n" + "\n".join(str(x) for x in lines) + "\n```"


HISTORY_COLS = ("date", "track", "total", "invested", "cash", "deposited",
                "pnl", "realised", "unrealised", "positions")


def record_day(when, track_name, m) -> None:
    """Append one day's mark to history.csv, replacing any row already there for
    the same day and track.

    The bot wakes every weeknight and usually has nothing to do; that no-op run
    has already computed mark(), so recording it costs nothing and is what gives
    the charts daily resolution instead of one point a month.
    """
    import csv
    if not m["rows"] and not m["deposited"] and not m["cash"]:
        return          # a track that was never funded is not worth a daily row
    key = (str(when), track_name)
    rows, seen = [], False
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if (r.get("date"), r.get("track")) == key:
                        seen = True
                        continue
                    rows.append(r)
        except (OSError, csv.Error):
            rows, seen = [], False      # unreadable history is not worth dying for
    rows.append({"date": str(when), "track": track_name,
                 "total": f'{m["total"]:.2f}', "invested": f'{m["invested"]:.2f}',
                 "cash": f'{m["cash"]:.2f}', "deposited": f'{m["deposited"]:.2f}',
                 "pnl": f'{m["pnl"]:.2f}', "realised": f'{m["realised"]:.2f}',
                 "unrealised": f'{m["unrealised"]:.2f}',
                 "positions": str(len(m["rows"]))})
    rows.sort(key=lambda r: (r["date"], r["track"]))
    tmp = HISTORY + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(HISTORY_COLS), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, HISTORY)
    if seen:
        return


def append_deposit(track_name, when, amount) -> None:
    """Record a dated cash-in (or, negative, cash-out) event.

    tracker.py replays this file to work out how many ETF units the same money
    would have bought on the same days, which is the benchmark the dashboard
    draws the real account against. Append-only; a plain CSV the tracker reads.
    """
    import csv
    amount = float(amount)
    if not amount:
        return
    new = not os.path.exists(DEPOSITS)
    tmp = DEPOSITS + ".tmp"
    rows = []
    if not new:
        try:
            with open(DEPOSITS, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        except (OSError, csv.Error):
            rows = []
    rows.append({"time": str(when), "track": track_name, "amount": f"{amount:.2f}"})
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=("time", "track", "amount"))
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, DEPOSITS)


def _track_row(bk, m, sym, ccy, marked="yahoo") -> dict:
    """One track's money block for latest.json. Shared by the full snapshot and
    the light --refresh-live patch, so the two shapes never drift.

    `marked` is where the held-share prices came from -- "t212" for the account
    that was read from the broker, "yahoo" otherwise -- so the dashboard can say
    which without guessing.
    """
    return {
        "symbol": sym, "currency": ccy, "marked": marked,
        "as_of": datetime.now(timezone.utc).isoformat(),   # per-track staleness;
        # latest.json's top-level `generated` moves on every track's refresh, so
        # it cannot tell you whether THIS track's figures are fresh.
        "total": round(m["total"], 2), "invested": round(m["invested"], 2),
        "cash": round(m["cash"], 2), "deposited": round(m["deposited"], 2),
        "pnl": round(m["pnl"], 2), "pnl_pct": round(m["pnl_pct"], 2),
        "realised": round(m["realised"], 2), "unrealised": round(m["unrealised"], 2),
        "basket": bk["basket"], "last_rebalance": bk["last_rebalance"],
        "equity": bk["equity"],
        "positions": {tk: {"shares": r["shares"], "price": round(r["price"], 2),
                           "value": round(r["value"], 2), "cost": round(r["cost"], 2),
                           "pnl": round(r["pnl"], 2), "pnl_pct": round(r["pnl_pct"], 2),
                           "weight_pct": round(r["value"] / m["total"] * 100, 2)
                           if m["total"] else 0.0}
                      for tk, r in m["rows"].items()},
    }


def regime_gauge(scores) -> dict:
    """How much dispersion there is in the universe's momentum right now: the
    mean 6-month return of the top HOLD names minus the mean of the bottom HOLD.

    Wide = momentum has something to sort on and the strategy has a tailwind.
    Compressed = winners and losers are barely distinguishable, so expect the
    strategy to track the index. Informational only -- it changes nothing.
    """
    if scores is None or len(scores) < 2 * HOLD:
        return {}
    top = float(scores.head(HOLD).mean())
    bot = float(scores.tail(HOLD).mean())
    spread = top - bot
    label = ("wide" if spread >= 0.25 else
             "compressed" if spread < 0.12 else "neutral")
    return {"spread_pct": round(spread * 100, 1),
            "top_pct": round(top * 100, 1),
            "bottom_pct": round(bot * 100, 1), "label": label}


def snapshot_payload(state, prices, scores, bar, held_px=None) -> dict:
    """Everything the dashboard renders from, both tracks.

    `held_px` (optional) is {ticker: account-currency price/share} from Trading
    212's own quotes -- see t212_held_prices(). When given, the account this run
    talked to (TRACK) is marked with those instead of the yfinance prices, so
    its holdings value matches the Trading 212 app to the cent. The other track,
    and every track when held_px is absent, still use the yfinance mark.
    """
    fx = live_fx()
    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "bar": str(bar.date()) if hasattr(bar, "date") else str(bar),
           "currency": fx["ccy"], "symbol": fx["sym"], "track": TRACK, "hold": HOLD,
           # The opening rebalance credits this before it sizes anything, so a
           # preview that leaves it out promises the wrong slice.
           "monthly": MONTHLY,
           # The dashboard has to be able to say whether the bot will place the
           # orders or only suggest them. Getting that wrong in either direction
           # is the worst kind of surprise.
           "autotrade": AUTOTRADE,
           "next_rebalance": next_month_label(bar),
           "ranking": [{"ticker": tk, "momentum_pct": round(float(v) * 100, 2),
                        "held": i < HOLD}
                       for i, (tk, v) in enumerate(scores.items())][:20],
           "regime": regime_gauge(scores),
           "tracks": {}}
    for name in TRACKS:
        bk = book(state, name)
        # Both books are real Trading 212 accounts in the account currency, so
        # both are marked with the converted prices -- except the account this
        # run read from the broker, whose held names are marked at Trading 212's
        # own prices so the dashboard equals the app.
        px_live = dict(to_live(prices))
        from_t212 = bool(held_px and name == TRACK)
        if from_t212:
            px_live.update(held_px)
        row = _track_row(bk, mark(bk, px_live), fx["sym"], fx["ccy"],
                         "t212" if from_t212 else "yahoo")
        out["tracks"][name] = row
    out["t212"] = {"available": t212 is not None,
                   "configured": bool(t212 is not None and t212.configured()),
                   "reason": (t212.why_not() if t212 is not None else
                              _T212_IMPORT_ERROR),
                   "env": getattr(t212, "ENV", ""),
                   }
    return out


def write_latest(payload: dict) -> None:
    tmp = LATEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    os.replace(tmp, LATEST)


def refresh_live(state) -> int:
    """A cheap latest.json refresh: Trading 212's holdings value only -- no price
    download, no ranking, no state.json write. A frequent systemd timer runs this
    so the dashboard's money figures move between the nightly full --json runs.

    It patches only the track this run read (TRACK), keeps ranking / bar /
    next-rebalance from the last full run, and does NOT rewrite latest.json when
    nothing moved by a cent -- so a closed market costs one broker read and no
    disk write.
    """
    snap = broker()
    held_px = t212_held_prices(snap)
    if not held_px:
        print("  no priceable Trading 212 holdings - latest.json left as is")
        return 0
    bk = book(state, TRACK)
    # In memory only, no save_state. resquare_cash=False: see reconcile()'s
    # docstring -- a live poll's fx quote is too stale to re-derive cash from
    # without chasing FX noise on every tick.
    reconcile(bk, snap, adopt=True, resquare_cash=False)
    m = mark(bk, held_px)

    try:
        with open(LATEST, encoding="utf-8") as fh:
            payload = json.load(fh)
        row = payload["tracks"][TRACK]
    except (OSError, json.JSONDecodeError, KeyError):
        print("  latest.json not ready - run --json once first")
        return 0

    fx = live_fx()
    fresh = _track_row(bk, m, fx["sym"], fx["ccy"], "t212")

    # Show what Trading 212 shows for the account, to the cent -- not mark()'s
    # reconstruction from the bot's cash ledger (which re-squares only nightly,
    # against an *estimated* FX fee). `total` / `invested` are the holdings
    # market value (cost basis + ppl); `pnl` is `ppl` alone -- the positions'
    # open profit, the number the app's P/L shows. It deliberately does NOT
    # subtract the one-off EUR->USD conversion fee: that is an entry cost, not
    # performance, and folding it in made the P/L read ~EUR9 worse than the app.
    # Account free funds are excluded (not the strategy's). state.json is
    # untouched -- that stays the strategy's own accounting.
    ac = (snap or {}).get("account_cash") or {}
    ppl = float(ac.get("ppl") or 0.0)
    held = float(ac.get("invested") or 0.0) + ppl
    if held > 0:
        basis = held - ppl                        # cost basis of the positions
        fresh["total"] = round(held, 2)
        fresh["invested"] = round(held, 2)
        fresh["cash"] = 0.0
        fresh["pnl"] = round(ppl, 2)
        fresh["unrealised"] = round(ppl, 2)
        fresh["pnl_pct"] = round(ppl / basis * 100, 2) if basis else 0.0

    # Always write. This used to skip when no money figure had moved a cent, to
    # save a disk write on a dead market -- but pulse.py now patches the money
    # fields every ~10s, so this run's job is really to keep the per-position
    # rows (which pulse does not touch) ~90s fresh. Merge, not replace: keep
    # anything else the full --json run added.
    row.update(fresh)
    payload["generated"] = datetime.now(timezone.utc).isoformat()
    write_latest(payload)
    print(f"  {TRACK}: {money(fresh['total'])} ({fresh['pnl']:+.2f}) - "
          f"latest.json refreshed")
    return 0


# ------------------------------------------------------------- the smoke test
#
# One real order, for about a euro, to prove the chain end to end: dashboard ->
# Discord -> your reaction -> Trading 212 -> a filled order -> and back out again.
# Nothing else exercises all of that at once, and the parts that break in
# practice are the joins between them.
#
# IT KEEPS ITS OWN FILE. state.json holds the strategy's book, and a test buying
# something the strategy did not choose has no business writing to it. Worst
# case, smoke.json is deleted and nothing of value is lost.
#
# The one thing it does share with the strategy is the account. AAPL is in the
# universe, so while the test position is open the bot would count it as its
# own -- which is exactly why the test closes it again, and why --smoke-status
# exists to say whether anything is still open.
SMOKE = os.path.join(HERE, "smoke.json")
SMOKE_TICKER = "AAPL"
SMOKE_MAX_USD = 5.0          # a hard ceiling, so a typo cannot buy a holiday
SMOKE_EXPIRY_MIN = 30        # an offer older than this quoted a price that moved
SMOKE_WATCH_SEC = 90         # how long one poll waits for a reaction before exiting


def _smoke_expired(s: dict) -> bool:
    when = s.get("offered_at")
    if not when:
        return False
    try:
        made = datetime.fromisoformat(str(when))
    except ValueError:
        return False
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - made).total_seconds() > SMOKE_EXPIRY_MIN * 60


def load_smoke() -> dict:
    try:
        with open(SMOKE, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_smoke(d: dict) -> None:
    tmp = SMOKE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, SMOKE)


def smoke_describe(s: dict) -> str:
    if not s:
        return "no test outstanding."
    stage = s.get("stage", "?")
    line = (f"stage    : {stage}\n"
            f"message  : {s.get('message_id')}\n"
            f"what     : {s.get('qty')} of {s.get('code')} "
            f"(about ${s.get('notional', 0):.2f})")
    if stage == "bought":
        line += ("\n\n  A POSITION IS OPEN. Until it is sold, the bot counts it as "
                 "its own\n  holding, because AAPL is one of the forty. React "
                 f"{discord_api.CROSS if discord_api else 'X'} to close it.")
    return line


# ------------------------------------------------- the monthly batch of orders
#
# The rebalance already works out exactly what to trade. This is what turns that
# list into orders at Trading 212 once you have said yes.
#
# The demo account is traded automatically; the live account waits for your
# Discord reaction. There is no longer a switch for this -- trading both accounts
# is what the bot is for.
#
# THE SHAPE, AND WHY
# One run proposes; a later run executes. In between there is a file on disk with
# the whole batch in it, one record per order.
#
#   propose : plan the orders, resolve every instrument code, post them to
#             Discord with a checkmark, write pending.json, and STOP. The month
#             is not marked done, the book is not moved, nothing is ordered.
#   execute : the poller sees your reaction, then walks the batch in order --
#             sells first, because their proceeds are what pays for the buys.
#
# Splitting it that way is what makes an approval mean something. A single run
# that asked and then acted would have to hold the decision in memory for as long
# as you took to answer; this one can be killed, rebooted or upgraded in the gap
# and the batch is still exactly where it was.
#
# WHAT HAPPENS IF IT DIES HALFWAY
# Each order is written as 'sending' BEFORE the request goes out and 'sent'
# after. So a run that dies after three of eight leaves order four as 'pending'
# and orders one to three as 'sent', and the next poll starts at four. If it dies
# DURING an order, that one stays 'sending' -- meaning nobody knows whether the
# broker got it -- and the batch stops dead rather than guessing. The same is
# true of a network failure: an order that timed out may still have been filled,
# so it is never, ever retried.
#
# That is the one rule everything here is arranged around: A REQUEST THAT MIGHT
# HAVE PLACED AN ORDER IS NEVER SENT TWICE.

# One batch file per account. The demo run places and settles in a single
# process, but it still keeps a record so a crash mid-batch can be resumed, and a
# separate name keeps a --poll tick (live only) from ever reading the demo batch.
# ponytail: two files keyed by env; live keeps its old filename so nothing migrates.
PENDING = os.path.join(HERE, "pending.json" if TRACK != "demo" else "pending-demo.json")
PENDING_EXPIRY_H = 6         # an approval this old approved prices that have moved
PENDING_WATCH_SEC = 90       # how long one poll waits before exiting

# Stages that mean a batch is live: a new one cannot be proposed over the top,
# and the poller has work to do.
PENDING_OPEN = ("offered", "trading", "stuck")

# Order states. 'sending' is the dangerous one and the reason the file is written
# twice per order.
DONE_STATES = ("sent", "skipped")


def load_pending() -> dict:
    try:
        with open(PENDING, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_pending(d: dict) -> None:
    """Written whole, then moved into place, and fsynced first.

    An order file that is half-written is worse than none: the next run would
    read a batch whose order states do not match what the broker was actually
    sent. os.replace is atomic, so a reader sees either the old file or the new
    one and never a torn one.
    """
    tmp = PENDING + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, PENDING)


def pending_expired(p: dict) -> bool:
    when = p.get("offered_at")
    if not when:
        return False
    try:
        made = datetime.fromisoformat(str(when))
    except ValueError:
        return False
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - made).total_seconds() > PENDING_EXPIRY_H * 3600


def pending_line(o: dict, state: bool = True) -> str:
    """One order as a line. `state` off while the batch is only a proposal --
    there is no state worth showing yet, and 'pending' eight times reads as
    though something is wrong."""
    side = "SELL" if o["shares"] < 0 else "BUY "
    flag = {"pending": " ", "sending": "?", "sent": "*", "skipped": "-",
            "failed": "!", "unknown": "?"}.get(o.get("state"), "?")
    line = (f"{flag} {side} {abs(o['shares']):.6f} {o['ticker']:<6} "
            f"{money(abs(o['cash'])):>12}")
    return line + (f"   {o.get('state', '?')}" if state else "")


def pending_describe(p: dict) -> str:
    if not p:
        return "no batch outstanding."
    lines = [f"stage    : {p.get('stage')}",
             f"month    : {p.get('month')}   (planned from the {p.get('bar')} close)",
             f"track    : {p.get('track')}",
             f"message  : {p.get('message_id')}",
             f"orders   : {len(p.get('orders', []))}"]
    lines += ["  " + pending_line(o) for o in p.get("orders", [])]
    if p.get("error"):
        lines.append(f"\nlast error: {p['error']}")
    if p.get("stage") == "stuck":
        lines.append(
            "\n  * = already sent to the broker.  ? = UNKNOWN, may or may not\n"
            "  have been placed. Open the Trading 212 app and compare, then:\n"
            "    --pending-resume    carry on from the first untouched order\n"
            "    --pending-abandon   record what did go through and stop there")
    return "\n".join(lines)


def resume_point(orders: list):
    """Index of the first order still to send, or (None, why) if it is not safe.

    Safe means every order before it definitely happened or definitely did not.
    'pending' has not been tried; 'failed' got a definitive rejection (a 400/403
    from Trading 212, never sent) -- both are safe to send now. Only 'sending'
    (died mid-request) and 'unknown' (a network timeout that may or may not have
    reached the broker) leave a hole nothing after them can be sent across.
    """
    for i, o in enumerate(orders):
        st = o.get("state")
        if st in DONE_STATES:
            continue
        if st in ("pending", "failed"):
            return i, ""
        return None, (f"order {i + 1} ({o['ticker']}) is {st!r} - its fate is not "
                      f"known, so nothing after it can be sent safely")
    return None, "every order is finished"


def propose_batch(name, bar, basket, orders, prices, paid_in, m,
                  monthly: float = 0.0, start: float = 0.0,
                  require_approval: bool = True) -> int:
    """Save the month's orders as a pending batch. Places nothing.

    `start` (opening rebalance only) and `monthly` (every one after) are what
    settle_batch will add to the book's cash and `deposited` once the orders are
    actually sent -- the rebalance run does not save the book, so this is where
    the money becomes real.

    With `require_approval` (live), an approval card with ✅/❌ is posted and the
    batch waits for the poller. Without it (demo), no card is posted and the
    caller runs execute_batch() straight away.

    Returns a process exit code. Anything that would make execution unsafe is
    caught HERE, before you are asked, rather than halfway through the batch --
    an approval you gave on a message that then failed to execute is the worst
    of both.
    """
    d = discord_api
    codes = t212.resolve_universe([o[0] for o in orders])["map"]
    missing = [o[0] for o in orders if not codes.get(o[0])]
    if missing:
        raise SystemExit(
            f"not proposing: {', '.join(missing)} did not resolve to a Trading "
            f"212 instrument.\nRun --t212-instruments to see the whole mapping. "
            f"Placing part of a rebalance is worse than placing none.")

    spend = sum(-o[2] for o in orders if o[2] < 0)
    raise_ = sum(o[2] for o in orders if o[2] > 0)
    # Two ceilings, both meant to catch a bug in the sizing rather than a bad
    # market. Neither should ever fire.
    if spend > m["total"] * 1.05 + 1:
        raise SystemExit(f"not proposing: the buys come to {money(spend)} against "
                         f"an account of {money(m['total'])}. That is a sizing "
                         f"bug, not a rebalance.")
    snap = broker()
    free = (snap or {}).get("cash")
    if free is not None and spend - raise_ > free + 0.01:
        print(f"  ! the buys need {money(spend - raise_)} more than the sells "
              f"raise, and Trading 212 shows {money(free)} free in the whole "
              f"account.\n    Some of these will be rejected. Move money in "
              f"first, or cancel with {d.CROSS}.")

    # Quantities are truncated to what Trading 212 will actually accept and send,
    # so the message you approve is the trade that fills -- not a value a few
    # decimals finer that the broker would 400.
    recs = [{"ticker": tk, "code": codes[tk], "shares": t212._round_qty(sh),
             "cash": round(dc, 2), "price": round(float(prices[tk]), 4),
             "state": "pending"} for tk, sh, dc in orders]

    n_sell = sum(1 for o in orders if o[2] > 0)
    n_buy = len(orders) - n_sell
    fields = [
        {"name": f"Orders ({len(recs)})",
         "value": _block(pending_line(o, state=False) for o in recs)},
        {"name": "Basket after", "value": ", ".join(basket)},
        {"name": "Sells raise", "value": money(raise_), "inline": True},
        {"name": "Buys spend", "value": money(spend), "inline": True},
        {"name": "Account", "value": money(m["total"]), "inline": True},
    ]
    if start:
        fields.append({"name": "Starting amount",
                       "value": f"{money(start)}, from your free funds"})
    elif paid_in:
        fields.append({"name": "This month",
                       "value": f"{money(paid_in)} added, from your free funds"})
    mid = ""
    if require_approval:
        embed = _embed(
            "Rebalance to approve", AMBER,
            desc=f"**{bar.date()}** · {n_sell} sell, {n_buy} buy · sizes from that "
                 f"day's close, so fills will not match to the cent",
            fields=fields,
            footer=f"React ✅ to place, ❌ to skip. Only you count. "
                   f"Expires in {PENDING_EXPIRY_H}h. Sells go first, then buys.")
        mid = d.post(content=f"<@{d.OWNER_ID}>", embeds=[embed])
        d.offer_tick(mid, d.TICK)
        d.offer_tick(mid, d.CROSS)

    save_pending({"stage": "offered", "track": name, "bar": str(bar.date()),
                  "month": f"{bar.year}-{bar.month:02d}",
                  "message_id": mid, "basket": basket, "paid_in": paid_in,
                  # Carried in the batch because the rebalance run deliberately
                  # does not save the book -- nothing is true yet. settle_batch
                  # records them, so a month that is cancelled never books money
                  # the strategy did not actually put to work.
                  "monthly": monthly, "start": start,
                  "offered_at": datetime.now(timezone.utc).isoformat(),
                  "orders": recs})
    if require_approval:
        print(f"\nproposed in Discord (message {mid}). NOTHING has been ordered "
              f"and the month is not marked done.\nReact {d.TICK} and the poller "
              f"places them; react {d.CROSS} or wait {PENDING_EXPIRY_H}h and it "
              f"does not.")
    else:
        print(f"\n{name} batch saved. Placing it now (no approval on demo).")
    return 0


def settle_batch(state, p, why: str):
    """Write the orders that actually went to the broker into the book, and
    return the marked account (or None if it was already settled).

    Only 'sent' orders count. An order that was never sent, or whose fate is
    unknown, must not move the book -- the book would then describe a portfolio
    nobody holds, which is the one thing worse than an out-of-date one.

    Fills are recorded at the price the batch was PLANNED at, which is the same
    assumption the manual instructions have always made. Positions correct
    themselves on the next run, because refresh() reads them back from the
    broker; cash does not, so if a fill was far from the close, --fill is what
    fixes it.
    """
    if p.get("settled_at"):
        # Settling twice would book the month's contribution twice and apply
        # every fill again. --pending-abandon on a batch that already finished is
        # the way that happens.
        print(f"already settled at {p['settled_at']} ({p.get('settled_because')}) "
              f", not doing it again.")
        return None
    bk = book(state, p["track"])
    # The rebalance run credited these in memory and then threw the book away
    # unsaved, so this is the first moment they are real: the starting amount on
    # the opening batch, or the monthly contribution after. Cash so apply_orders
    # below can spend them, deposited so they are not read as profit.
    added = float(p.get("start") or 0.0) + float(p.get("monthly") or 0.0)
    bk["cash"] += added
    bk["deposited"] += added
    if added:
        append_deposit(p["track"], p["bar"], added)
    done = [o for o in p["orders"] if o.get("state") == "sent"]
    orders = [(o["ticker"], o["shares"], o["cash"]) for o in done]
    prices = {o["ticker"]: o["price"] for o in p["orders"]}
    apply_orders(bk, orders, prices)
    after = mark(bk, prices)
    bar = p["bar"]
    bk["equity"].append([bar, round(after["total"], 2)])
    bk.update({"basket": p["basket"], "last_rebalance": bar,
               "last_rebalance_month": p["month"]})
    save_state(state)
    buys = [o["ticker"] for o in done if o["shares"] > 0]
    sells = [o["ticker"] for o in done if o["shares"] < 0]
    log_row(bar, buys, sells, p["basket"], after["total"], after["cash"],
            after["deposited"], after["pnl"], p["track"])
    p["settled_at"] = datetime.now(timezone.utc).isoformat()
    p["settled_because"] = why
    save_pending(p)
    print(f"recorded {len(done)} of {len(p['orders'])} orders on the "
          f"{p['track']} book · account {money(after['total'])} · cash "
          f"{money(after['cash'])}")

    # The dashboard renders from latest.json, which is written by the nightly
    # --json run. Without this it would go on showing last month's basket until
    # tomorrow evening -- on the one day of the month anybody is actually
    # looking. A failure here costs a stale page, not a wrong book, so it is
    # caught: the book above is already saved.
    try:
        px = fetch()
        usd = px.iloc[-1].to_dict()
        scores = rank(px)
        for t in TRACKS:
            record_day(px.index[-1].date(), t,
                       mark(book(state, t), to_live(usd)))
        write_latest(snapshot_payload(state, usd, scores, px.index[-1]))
    except (Exception, SystemExit) as exc:                 # noqa: BLE001
        # SystemExit is in there on purpose: fetch() raises it when the price
        # download comes back unusable. Letting that through would abort the run
        # AFTER the orders were sent and the book saved, which reads as a failed
        # rebalance when in fact the only casualty is a stale page.
        print(f"  ! the book is saved, but the dashboard cache is not: {exc}")
    return after


def kill_switch(state) -> int:
    """Sell every strategy position at market, at once, and freeze. Runs once:
    a `kill_done` marker on the live book stops it repeating while MOMENTUM_KILL
    stays on. Clearing the setting clears the marker (see main())."""
    live = book(state, "live")
    d = discord_api

    # 1. No batch may go out while this is on. Abandon anything open.
    pend = load_pending()
    if pend.get("stage") in PENDING_OPEN:
        pend["stage"] = "abandoned"
        pend["error"] = "killswitch"
        save_pending(pend)
        if d is not None and d.configured():
            d.delete_message(pend.get("message_id"))
        print("  killswitch: abandoned the open batch.")

    if live.get("kill_done"):
        print("killswitch already executed; MOMENTUM_KILL is still on. Frozen.")
        return 0

    def _confirm(desc, fields=None):
        if d is not None and d.configured():
            try:
                d.post(embeds=[_embed("KILL SWITCH", RED, desc=desc, fields=fields)],
                       channel=d.CONFIRM_CHANNEL_ID)
            except Exception as exc:                       # noqa: BLE001
                print(f"  ! could not post the killswitch summary ({exc})")

    # 2. Can we place orders at all?
    if t212 is None or not t212.configured():
        why = _T212_IMPORT_ERROR or (t212.why_not() if t212 else "no broker")
        names = ", ".join(sorted(live.get("positions", {}))) or "(none on record)"
        _confirm(f"Armed, but the bot cannot place orders ({why}). "
                 f"Sell these by hand now, then the freeze holds until the "
                 f"Kill switch is turned off.",
                 fields=[{"name": "Sell by hand", "value": names}])
        live["kill_done"] = True
        save_state(state)
        print(f"killswitch: cannot trade ({why}). Posted a manual list; frozen.")
        return 1

    snap = broker()
    pos = (snap or {}).get("positions", {})
    if not pos:
        live["kill_done"] = True
        live["basket"] = []
        save_state(state)
        _confirm("Armed. Trading 212 shows no strategy positions, so there is "
                 "nothing to sell. Trading is frozen until the Kill switch is "
                 "turned off.")
        print("killswitch: no strategy positions at the broker. Frozen.")
        return 0

    # 3. Sell each, at market, pacing like execute_batch.
    try:
        px = fetch()
        book_prices = to_live(px.iloc[-1].to_dict())
    except (Exception, SystemExit):                        # noqa: BLE001
        book_prices = {}
    codes = t212.resolve_universe(list(pos))["map"]
    sold, failed = [], []
    for tk, info in sorted(pos.items()):
        sh = float(info.get("shares") or 0.0)
        if sh <= 0 or tk not in codes:
            failed.append((tk, "no shares or no instrument code"))
            continue
        try:
            t212.place_market_order(codes[tk], -abs(sh))
            sold.append((tk, sh))
            print(f"  * sold {sh} {tk}")
        except Exception as exc:                           # noqa: BLE001
            failed.append((tk, str(exc)[:200]))
            print(f"  ! {tk}: {exc}")
        time.sleep(ORDER_GAP_SEC)

    # 4. Move the book flat. apply_orders keeps realised P&L and the cash ledger
    #    right when prices are in hand; without them the positions are still
    #    cleared and the next refresh() re-adopts the real (empty) portfolio and
    #    a --fill fixes any cash drift.
    if sold and book_prices:
        apply_orders(live, [(tk, -sh, sh * book_prices.get(tk, 0.0))
                            for tk, sh in sold], book_prices)
    for tk, _ in (sold + failed):
        live["positions"].pop(tk, None)
        live["book"].pop(tk, None)
    live["basket"] = []
    live["kill_done"] = True
    after = mark(live, book_prices)
    live["equity"].append([str(datetime.now(timezone.utc).date()),
                           round(after["total"], 2)])
    save_state(state)
    log_row(str(datetime.now(timezone.utc).date()), [], [t for t, _ in sold], [],
            after["total"], after["cash"], after["deposited"], after["pnl"], "live")
    try:
        px = fetch()
        for t in TRACKS:
            record_day(px.index[-1].date(), t,
                       mark(book(state, t), to_live(px.iloc[-1].to_dict())))
        write_latest(snapshot_payload(state, px.iloc[-1].to_dict(),
                                      rank(px), px.index[-1]))
    except (Exception, SystemExit) as exc:                 # noqa: BLE001
        print(f"  ! book saved, dashboard cache not: {exc}")

    fields = [{"name": f"Sold ({len(sold)})",
               "value": (", ".join(t for t, _ in sold) or "-")},
              {"name": "Account is now cash",
               "value": money(after["cash"]), "inline": True}]
    if failed:
        fields.append({"name": f"Could not sell ({len(failed)})",
                       "value": ", ".join(f"{t} ({e})" for t, e in failed)
                                + "  - close these by hand"})
    _confirm("Sold everything at market. Trading is frozen until the Kill switch "
             "is turned back off.", fields=fields)
    print(f"killswitch done: {len(sold)} sold, {len(failed)} failed. Frozen.")
    return 0 if not failed else 1


def execute_batch(state, p) -> int:
    """Send the batch to the broker, in order, stopping at the first surprise."""
    d = discord_api
    orders = p["orders"]
    start, why = resume_point(orders)
    if start is None:
        if any(o.get("state") not in DONE_STATES for o in orders):
            p["stage"] = "stuck"
            p["error"] = why
            save_pending(p)
            print(f"not safe to continue: {why}\n\n{pending_describe(p)}")
            return 1
        p["stage"] = "done"
        save_pending(p)
        settle_batch(state, p, "all orders sent")
        return 0

    p["stage"] = "trading"
    save_pending(p)

    # THE BUYS WERE SIZED ON THE ASSUMPTION THAT THE SELLS RAISE WHAT THEY SAID.
    #
    # If a sell turns out smaller than planned -- or does not happen at all,
    # because the position was sold by hand -- every buy behind it is now asking
    # for money that is not there. Left alone, the broker rejects them one at a
    # time and a tidy situation becomes a halted batch.
    #
    # So the shortfall is carried forward and the remaining buys are scaled down
    # to fit it. Planned buys B are covered by sells S plus idle cash C, with
    # B <= S + C. Raise only S - short, and what is affordable is B - short, so
    # every buy is multiplied by (B - short) / B. Small, proportional, and it
    # keeps the basket rather than dropping whichever name came last.
    planned_buys = sum(-o["cash"] for o in orders if o["shares"] > 0
                       and o.get("state") not in DONE_STATES)
    short = 0.0

    for i in range(start, len(orders)):
        o = orders[i]
        if o.get("state") in DONE_STATES:
            continue

        if o["shares"] > 0 and short > 0 and planned_buys > 0:
            scale = (planned_buys - short) / planned_buys
            if scale <= 0:
                p["stage"] = "stuck"
                p["error"] = (f"the sells raised {money(short)} less than planned, "
                              f"which is everything the buys needed")
                save_pending(p)
                d.post(f"⚠️ Stopped before buying anything. The sells raised "
                       f"{money(short)} less than the plan assumed, enough that "
                       f"there is nothing left to buy with.\nNothing further was "
                       f"sent. Check the app and `--pending-status`.")
                d.delete_message(p.get("message_id"))
                print(p["error"])
                return 1
            o["shares"] = round(o["shares"] * scale, 6)
            o["cash"] = round(o["cash"] * scale, 2)
            o["note"] = f"scaled to {scale:.3f} - the sells raised less than planned"
            if o["shares"] <= 0:
                o["state"] = "skipped"
                o["note"] = "nothing left to buy with after the sells fell short"
                o["cash"] = 0.0
                save_pending(p)
                continue

        if o["shares"] < 0:
            # NEVER SELL WHAT YOU DO NOT HOLD. The book can be a day stale and
            # the broker cannot; a sell sized from the book against a position
            # that is not there any more is a short, not a rebalance.
            held = None
            try:
                held = t212.positions(universe=UNIVERSE).get(
                    o["ticker"], {}).get("shares")
            except Exception as exc:                       # noqa: BLE001
                p["stage"] = "stuck"
                p["error"] = f"could not read positions before selling: {exc}"
                save_pending(p)
                d.post(f"⚠️ Stopped before selling `{o['ticker']}` - could not "
                       f"read the position back from Trading 212 ({exc}). "
                       f"Nothing further was sent.")
                d.delete_message(p.get("message_id"))
                print(p["error"])
                return 1
            if not held or held <= 1e-9:
                short += o["cash"]                  # proceeds that will not arrive
                o["state"] = "skipped"
                o["note"] = "broker shows no position"
                o["cash"] = 0.0
                save_pending(p)
                print(f"  - {o['ticker']}: nothing held at the broker, skipping "
                      f"the sell")
                continue
            if held < abs(o["shares"]) - 1e-9:
                # Sell what is there. Selling the difference short is not a
                # smaller version of the right answer, it is a different trade.
                o["note"] = (f"asked for {abs(o['shares'])}, broker holds {held}")
                was = o["cash"]
                o["cash"] = round(o["cash"] * held / abs(o["shares"]), 2)
                short += was - o["cash"]
                o["shares"] = -round(float(held), 6)
                print(f"  ! {o['ticker']}: {o['note']} - selling what is there")

        o["state"] = "sending"
        save_pending(p)                     # BEFORE the request. Always.

        def _send(qty):
            try:
                return t212.place_market_order(o["code"], qty), ""
            except Exception as exc:                       # noqa: BLE001
                return None, str(exc)

        def _short(m):
            return bool(m) and "insufficient-free-for-stocks" in m

        # Planned size first. On an insufficient-funds rejection of a buy: wait
        # once for earlier reservations to release, then shrink this order to the
        # ACTUAL free cash with a widening haircut. Trading 212 holds back a few
        # percent of a market buy for slippage, and the mid-market FX rate the
        # batch was sized at understates the real euro cost -- so the last name
        # ends up a little light. Better than a halted batch.
        price = abs(o["cash"]) / o["shares"] if o["shares"] else 0.0
        want = o["shares"]
        resp, msg = _send(want)
        if _short(msg) and want > 0:
            print(f"  … {o['ticker']}: funds reserved, waiting {FUNDS_RETRY[1]:.0f}s")
            time.sleep(FUNDS_RETRY[1])
            resp, msg = _send(want)
            for hair in (0.95, 0.90, 0.85, 0.78):
                if not _short(msg):
                    break
                try:
                    free = float(t212.cash().get("free", 0.0))
                except Exception:                         # noqa: BLE001
                    free = 0.0
                fit = min(want, t212._round_qty(free * hair / price)) if price > 0 else 0.0
                if fit <= 0:
                    o.update(state="skipped", cash=0.0,
                             note=f"only {money(free)} free - nothing left to buy with")
                    save_pending(p)
                    print(f"  - {o['ticker']}: {o['note']}")
                    msg = ""
                    break
                o["shares"] = fit
                o["cash"] = -round(fit * price, 2)
                o["note"] = f"trimmed to {fit} to fit {money(free)} free"
                print(f"  ! {o['ticker']}: {money(free)} free - trying {fit} of {want}")
                resp, msg = _send(fit)

        if o.get("state") == "skipped":
            continue
        if msg:
            # t212._post marks a request whose outcome it could not learn with
            # UNKNOWN. That order might be live at the broker, so it is left as
            # 'sending' and never touched again by anything automatic.
            o["state"] = "unknown" if msg.startswith("UNKNOWN") else "failed"
            o["error"] = msg
            p["stage"] = "stuck"
            p["error"] = f"{o['ticker']}: {msg}"
            save_pending(p)
            # The halt is the new actionable thing, so it stays in the approvals
            # channel; the answered prompt above it is removed.
            d.post(f"⚠️ **Stopped part-way through the rebalance.**\n"
                   f"`{o['ticker']}` came back: {msg[:400]}\n\n"
                   f"{len([x for x in orders if x.get('state') == 'sent'])} of "
                   f"{len(orders)} orders were sent before this. Nothing after it "
                   f"was. Check the app, then run `--pending-status` on the box.")
            d.delete_message(p.get("message_id"))
            print(f"halted at {o['ticker']}: {msg}")
            return 1
        o["state"] = "sent"
        o["response"] = resp
        o["sent_at"] = datetime.now(timezone.utc).isoformat()
        save_pending(p)
        print(f"  * {'sold' if o['shares'] < 0 else 'bought'} "
              f"{abs(o['shares'])} {o['ticker']}")
        time.sleep(ORDER_GAP_SEC)           # let this fill before the next stacks

    p["stage"] = "done"
    save_pending(p)
    after = settle_batch(state, p, "all orders sent") or {}
    sent = [o for o in orders if o.get("state") == "sent"]
    skipped = [o for o in orders if o.get("state") == "skipped"]
    sold = [o["ticker"] for o in sent if o["shares"] < 0]
    bought = [o["ticker"] for o in sent if o["shares"] > 0]
    fields = [
        {"name": f"Sold ({len(sold)})", "value": ", ".join(sold) or "-", "inline": True},
        {"name": f"Bought ({len(bought)})", "value": ", ".join(bought) or "-", "inline": True},
        {"name": "Basket", "value": ", ".join(book(state, p["track"]).get("basket", []))},
        {"name": "Account",
         "value": f"{money(after.get('total', 0.0))}  "
                  f"({after.get('pnl_pct', 0.0):+.1f}% on {money(after.get('deposited', 0.0))})"},
    ]
    if skipped:
        fields.append({"name": "Skipped",
                       "value": f"{len(skipped)} (nothing held to sell)"})
    d.post(embeds=[_embed(
        f"Rebalance placed - {p['month']}", GREEN,
        desc=f"{len(sent)} orders sent. Market orders fill at the market, so "
             f"check the app for the actual fills.",
        fields=fields)], channel=d.CONFIRM_CHANNEL_ID)
    d.delete_message(p.get("message_id"))       # the approval is answered
    return 0


LOG_COLS = ("date", "buys", "sells", "basket", "account", "cash", "deposited", "pnl", "track")


def log_row(when, buys, sells, basket, total=0.0, cash=0.0,
            deposited=0.0, pnl=0.0, track="") -> None:
    """Record one rebalance, replacing any row already logged for that date on
    the same track. Demo and live share this file, so the key is (date, track) —
    without the track the two accounts' same-day rebalances overwrite each other
    and the dashboard cannot tell them apart.

    Two things this has to survive.

    An older version of this file wrote a four-column header. Appending
    eight-column rows underneath it left the money columns unreadable — a reader
    maps by the header, so account, cash, deposited and pnl came back empty and
    were rendered as zero, which is a lie about what happened. So the header is
    checked on every write and the file rewritten when it is stale, with the old
    rows kept and their missing columns left genuinely blank.

    And a second run on a day already logged used to append a duplicate. Now it
    replaces, which also makes --force idempotent.
    """
    import csv
    rows = []
    if os.path.exists(LOG):
        try:
            with open(LOG, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    r.pop(None, None)               # extra fields under a short header
                    if (r.get("date"), r.get("track") or "") != (str(when), track):
                        rows.append(r)
        except (OSError, csv.Error):
            rows = []

    rows.append({"date": str(when), "buys": " ".join(buys), "sells": " ".join(sells),
                 "basket": " ".join(basket), "account": f"{total:.2f}",
                 "cash": f"{cash:.2f}", "deposited": f"{deposited:.2f}",
                 "pnl": f"{pnl:.2f}", "track": track})
    rows.sort(key=lambda r: (r.get("date") or "", r.get("track") or ""))

    tmp = LOG + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(LOG_COLS), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LOG_COLS})
    os.replace(tmp, LOG)


def env_source_line() -> str:
    """Where settings actually came from. Printed by --status and --t212-probe
    because 'the dashboard says one thing and the bot does another' is otherwise
    invisible."""
    if not ENV_FILES_LOADED:
        return (f"config    : no env file found ({ETC_ENV}, {USER_ENV}) - "
                f"using defaults and whatever is exported")
    names = ", ".join(ENV_FILES_LOADED)
    return f"config    : {names}" + ("" if len(ENV_FILES_LOADED) > 1 else
                                     "  (the other was not found)")


def smoke_poll(once: bool) -> int:
    """The reaction-driven half of the smoke test. Split out so --poll can
    run it alongside the monthly batch in one process, rather than starving
    one of them while the other waits."""
    d = discord_api
    s = load_smoke()
    if not s:
        print("nothing offered. Run --smoke-offer first.")
        return 0
    stage = s.get("stage")

    if stage in ("buying", "selling", "unknown"):
        print(f"stage is {stage!r} - a previous run did not finish cleanly.\n"
              f"Check the Trading 212 app, then delete {SMOKE} once the "
              f"position matches what you expect.")
        if s.get("error"):
            print(f"last error: {s['error']}")
        return 1

    if stage not in ("offered", "bought"):
        print(f"nothing to do (stage {stage!r}).")
        return 0

    # An offer that has been sitting around is not an offer any more: the
    # price it quoted has moved on, and a tick three days later should not
    # buy at today's. The sell prompt never expires -- an open position has
    # to stay closeable.
    if stage == "offered" and _smoke_expired(s):
        s["stage"] = "expired"
        save_smoke(s)
        d.post(f"{d.CROSS} Smoke test expired after {SMOKE_EXPIRY_MIN} "
               f"minutes. Nothing was ordered.")
        print("offer expired; nothing ordered.")
        return 0

    # Each stage watches its own message, so a stale reaction on an old one
    # cannot drive the next step.
    watch = s["message_id"] if stage == "offered" else s.get("sell_message_id")
    want = d.TICK if stage == "offered" else d.CROSS
    if not watch:
        print(f"no message to watch for stage {stage!r}.")
        return 1
    # Discord cannot call us, so somebody has to ask. Asking once a minute
    # means up to a minute of nothing happening while you stare at the
    # message. Instead one run stays for a while and asks every few seconds,
    # so a reaction lands in about the time it takes to notice you made it.
    #
    # A gateway websocket would be instant, and an interactions webhook would
    # be too -- but that needs a public HTTPS endpoint, and this dashboard is
    # deliberately not reachable from the internet. Polling briefly is the
    # version that does not require opening the box up.
    deadline = time.monotonic() + (SMOKE_WATCH_SEC if not once else 0)
    while True:
        if d.approved_by_owner(watch, want):
            break
        if time.monotonic() >= deadline:
            print(f"waiting for {want} from the owner on message {watch} "
                  f"(stage: {stage}).")
            return 0
        time.sleep(3)

    if stage == "offered":
        # Written BEFORE the order goes out. If this run dies between the
        # request and the reply, the next one must not read "offered" and
        # buy a second time -- it reads "buying" and asks for reconciliation.
        s["stage"] = "buying"
        save_smoke(s)
        try:
            resp = t212.place_market_order(s["code"], s["qty"])
        except t212.T212Error as exc:
            s["stage"] = "unknown"
            s["error"] = str(exc)
            save_smoke(s)
            d.post(f"⚠️ Smoke test buy did not complete cleanly: {exc}")
            raise SystemExit(f"{exc}")
        s.update({"stage": "bought", "buy_response": resp,
                  "bought_at": datetime.now(timezone.utc).isoformat()})
        save_smoke(s)
        # A fresh message with a single reaction, rather than a second
        # reaction on the first one: the question has changed, so the thing
        # you are answering should change with it.
        sell_id = d.post(
            f"{d.TICK} **Bought {s['qty']} of `{s['code']}`.**\n"
            f"Broker said: `{json.dumps(resp, default=str)[:300]}`\n\n"
            f"Check it in the Trading 212 app, then react {d.CROSS} **on this "
            f"message** to sell it straight back.")
        d.offer_tick(sell_id, d.CROSS)
        s["sell_message_id"] = sell_id
        save_smoke(s)
        print(f"BOUGHT {s['qty']} {s['code']}\n"
              f"{json.dumps(resp, indent=1, default=str)}\n"
              f"asked about selling in message {sell_id}")
        return 0

    if stage == "bought":
        # NEVER SELL WHAT YOU DO NOT HOLD.
        #
        # "The buy was accepted" and "the buy filled" are different claims.
        # Outside regular hours an order can sit pending for hours, and the
        # response says so rather than reporting a fill. Selling against a
        # position that does not exist yet is how a test turns into a short.
        #
        # So the broker is asked what is actually there, and the sell is for
        # what it says, not for what the buy requested.
        held = None
        try:
            pos = t212.positions(universe=UNIVERSE)
            held = pos.get(SMOKE_TICKER, {}).get("shares")
        except Exception as exc:                       # noqa: BLE001
            print(f"  ! could not read the position back ({exc})")
        if held is None or held <= 0:
            d.post(f"⚠️ Not selling: Trading 212 shows no {SMOKE_TICKER} "
                   f"position.\nThe buy was accepted but may not have filled "
                   f"- outside US market hours it can sit pending. Check the "
                   f"app; react {d.CROSS} again once it shows.")
            print(f"refusing to sell: broker reports no {SMOKE_TICKER} "
                  f"holding (buy may still be pending).")
            return 1
        want_qty = min(abs(float(s["qty"])), float(held))
        if abs(want_qty - abs(float(s["qty"]))) > 1e-9:
            print(f"  ! selling {want_qty} rather than {s['qty']} - that is "
                  f"what the broker shows as held.")
        s["stage"] = "selling"
        s["sell_qty"] = want_qty
        save_smoke(s)
        try:
            # Exactly what the broker says is held, which is normally what
            # was bought. Not "a euro's worth" recomputed -- the price has
            # moved since, and a recomputed size would leave a sliver behind
            # or try to sell more than exists.
            resp = t212.place_market_order(s["code"], -abs(float(s["sell_qty"])))
        except t212.T212Error as exc:
            s["stage"] = "unknown"
            s["error"] = str(exc)
            save_smoke(s)
            d.post(f"⚠️ Smoke test sell did not complete cleanly: {exc}")
            raise SystemExit(f"{exc}")
        s.update({"stage": "closed", "sell_response": resp,
                  "closed_at": datetime.now(timezone.utc).isoformat()})
        save_smoke(s)
        d.post(f"{d.TICK} Sold {s['sell_qty']} of `{s['code']}` back. Round "
               f"trip complete - the whole chain works end to end.\n"
               f"Broker said: `{json.dumps(resp, default=str)[:400]}`")
        print(f"SOLD {s['sell_qty']} {s['code']}\n"
              f"{json.dumps(resp, indent=1, default=str)}")
        return 0

    print(f"nothing to do (stage {stage!r}).")
    return 0


def approval_ready() -> str:
    """Empty when the broker and Discord can both be used, otherwise the reason.

    Everything that places an order goes through here first, so a missing key is
    a sentence rather than an AttributeError three frames deep.
    """
    if t212 is None:
        return f"t212.py did not load: {_T212_IMPORT_ERROR}"
    if discord_api is None:
        return f"discord_api.py did not load: {_DISCORD_IMPORT_ERROR}"
    if not t212.configured():
        return t212.why_not()
    if not discord_api.configured():
        return f"Discord approval is {discord_api.why_not()}"
    fx = live_fx()
    if fx["err"]:
        # Sizing a live rebalance without the rate would deploy the wrong amount,
        # exactly the bug this whole conversion exists to fix. Skip the month.
        return fx["err"] + " - not sizing a live rebalance without it"
    return ""


def pending_poll(state, once: bool) -> int:
    """Read the answer to this month's proposal and act on it."""
    d = discord_api
    p = load_pending()
    stage = p.get("stage")

    # A run that died mid-batch left this. It is not waiting on an answer -- you
    # already gave one -- so it picks up where it stopped without asking again.
    if stage == "trading":
        print("resuming a batch that was interrupted")
        return execute_batch(state, p)
    if stage != "offered":
        return 0

    # Prices move. An approval given tomorrow would be approving sizes worked
    # out from a close that is two days old, which is a different trade from the
    # one that was shown.
    if pending_expired(p):
        p["stage"] = "expired"
        save_pending(p)
        d.post(embeds=[_embed(
            f"Rebalance expired - {p['month']}", GREY,
            desc=f"No answer in {PENDING_EXPIRY_H} hours. Nothing was ordered and "
                 f"the book has not moved. Run it again with --force when ready.")],
            channel=d.CONFIRM_CHANNEL_ID)
        d.delete_message(p.get("message_id"))
        print("proposal expired; nothing ordered.")
        return 0

    deadline = time.monotonic() + (0 if once else PENDING_WATCH_SEC)
    while True:
        choice = d.owner_choice(p["message_id"])
        if choice:
            break
        if time.monotonic() >= deadline:
            print(f"waiting for an answer on message {p['message_id']} "
                  f"({len(p['orders'])} orders, {p['month']}).")
            return 0
        time.sleep(3)

    if choice == "no":
        p["stage"] = "cancelled"
        p["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        save_pending(p)
        skipped_in = float(p.get("start") or 0.0) or float(p.get("monthly") or 0.0)
        desc = ("Nothing was ordered and the book has not moved; it still holds "
                "last month's basket. Run it again with --force to change your mind.")
        if skipped_in:
            desc += (f"\n\n{money(skipped_in)} was not drawn from free funds or "
                     f"recorded as paid in, since no rebalance happened.")
        d.post(embeds=[_embed(f"Skipped - {p['month']}", GREY, desc=desc)],
               channel=d.CONFIRM_CHANNEL_ID)
        d.delete_message(p.get("message_id"))
        print("cancelled; nothing ordered.")
        return 0

    return execute_batch(state, p)


def poll_all(state, once: bool) -> int:
    """What the timer runs every minute.

    THE IDLE PATH TOUCHES NOTHING. With no test and no batch outstanding this
    reads two small files and returns, so running it sixty times an hour costs
    nothing and there is no reason to make the schedule cleverer.

    Both are polled in the same process, deliberately. Doing one per tick would
    mean a smoke position left open for a week -- which is a perfectly normal
    thing to forget -- starving the monthly rebalance behind it.
    """
    if KILL:
        # The dashboard fires --kill on the toggle, but if that failed this is
        # the safety net: within a minute the poller sells and freezes. It never
        # runs the batch or smoke polls while armed.
        return kill_switch(state) if not book(state, "live").get("kill_done") else 0

    smoke = load_smoke()
    pend = load_pending()
    smoke_waiting = smoke.get("stage") in ("offered", "bought")
    # 'stuck' is deliberately absent: a batch that stopped on a surprise waits
    # for a person, and a poller that kept trying is exactly what must not happen.
    pend_waiting = pend.get("stage") in ("offered", "trading")
    if not (smoke_waiting or pend_waiting):
        return 0

    why = approval_ready()
    if why:
        print(f"something is waiting, but: {why}")
        return 1

    rc = 0
    if pend_waiting:
        rc |= pending_poll(state, once) and 1
    if smoke_waiting:
        rc |= smoke_poll(once) and 1
    return rc


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="decide and print, post nothing")
    p.add_argument("--force", action="store_true", help="rebalance regardless of date")
    p.add_argument("--status", action="store_true", help="show the account and exit")
    p.add_argument("--json", action="store_true",
                   help="machine-readable status for the dashboard; posts nothing")
    p.add_argument("--refresh-live", action="store_true",
                   help="cheap latest.json money refresh: Trading 212 read only, "
                        "no price download or ranking. For a frequent timer.")
    p.add_argument("--report", action="store_true",
                   help="post the account to Discord without rebalancing")
    p.add_argument("--test", action="store_true",
                   help="post a real message to Discord, save nothing")
    p.add_argument("--env", choices=TRACKS, default=None,
                   help="which Trading 212 account to act on: demo or live "
                        "(default from T212_ENV). Read before the broker is "
                        "imported, so it also picks the key pair.")
    p.add_argument("--deposit", type=float, metavar="AMOUNT",
                   help="record money paid into the account")
    p.add_argument("--withdraw", type=float, metavar="AMOUNT",
                   help="record money taken out")
    p.add_argument("--fill", action="append", metavar="TICKER=SHARES@PRICE",
                   help="correct an assumed fill; repeatable")
    p.add_argument("--discord-confirm", metavar="MESSAGE_ID",
                   help="read back who ticked a message posted by --discord-check")
    p.add_argument("--discord-check", action="store_true",
                   help="verify the bot token, channel and owner id; posts one "
                        "test message you can approve, and changes nothing else")
    p.add_argument("--smoke-offer", action="store_true",
                   help="offer a real ~1 EUR test buy of AAPL in Discord. Posts "
                        "the message and the two reactions; places nothing.")
    p.add_argument("--smoke-poll", action="store_true",
                   help="act on the reaction to a smoke test: tick buys, cross "
                        "sells it back. THIS PLACES A REAL ORDER.")
    p.add_argument("--smoke-status", action="store_true",
                   help="say whether a test position is still open")
    p.add_argument("--smoke-once", action="store_true",
                   help="check for a reaction once and exit, instead of watching "
                        "for a minute or so")
    p.add_argument("--pending-status", action="store_true",
                   help="show the month's proposed orders and what happened to "
                        "each one")
    p.add_argument("--pending-poll", action="store_true",
                   help="act on the reaction to this month's orders. THIS PLACES "
                        "REAL ORDERS.")
    p.add_argument("--pending-cancel", action="store_true",
                   help="drop an outstanding proposal without placing anything")
    p.add_argument("--pending-resume", action="store_true",
                   help="after a halt, carry on from the first order that was "
                        "definitely never sent. Read --pending-status first.")
    p.add_argument("--pending-abandon", action="store_true",
                   help="after a halt, record the orders that did go through and "
                        "stop there. The month counts as rebalanced.")
    p.add_argument("--poll", action="store_true",
                   help="what the timer runs: act on any reaction, smoke test or "
                        "monthly batch. Does nothing when nothing is waiting.")
    p.add_argument("--kill", action="store_true",
                   help="sell every strategy position at market and freeze all "
                        "trading. Needs MOMENTUM_KILL=on. THIS PLACES REAL ORDERS.")
    p.add_argument("--t212-find", metavar="TEXT",
                   help="search the broker's instrument list by code or name; "
                        "read-only, for names --t212-instruments could not resolve")
    p.add_argument("--t212-instruments", action="store_true",
                   help="resolve the universe to Trading 212 instrument codes; "
                        "read-only, and required before any order can be placed")
    p.add_argument("--transactions", type=int, metavar="N", nargs="?", const=50,
                   help="print the last N Trading 212 cash transactions (deposits, "
                        "fees, interest) as JSON, then exit. Read-only.")
    p.add_argument("--t212-probe", action="store_true",
                   help="print what Trading 212 returns; read-only, changes nothing")
    p.add_argument("--t212-check", action="store_true",
                   help="compare the live book with the broker; changes nothing")
    p.add_argument("--t212-sync", action="store_true",
                   help="adopt the broker's positions and cash as the truth")
    p.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    args = p.parse_args()

    state = load_state()
    name = TRACK                    # follows --env / T212_ENV; see the shim above
    bk = book(state, name)

    # money() prints in the account currency (via live_fx, resolved on first
    # use). Both demo and live are real Trading 212 accounts.
    global SYM
    _fx = live_fx()
    SYM = _fx["sym"]
    if _fx["err"]:
        print(f"  ! {_fx['err']} - figures shown in USD for now")

    # --- the kill switch --------------------------------------------------
    # Blocks trading, not reading -- --status / --json / --t212-* still work so
    # you can see the frozen account. --kill, --poll and the rebalance run are
    # what actually execute it; --pending-poll / --pending-resume refuse.
    if not KILL and book(state, "live").get("kill_done"):
        # Turned back off -- clear the marker so a future arm works.
        book(state, "live").pop("kill_done", None)
        save_state(state)
        print("MOMENTUM_KILL is off - the kill switch is re-armed for next time.")

    if args.kill:
        if not KILL:
            raise SystemExit("MOMENTUM_KILL is not on - arm it on the Settings "
                             "page (or export MOMENTUM_KILL=on) first.")
        return kill_switch(state)

    # --- this month's orders, and the timer that carries them out -----------
    if args.pending_status:
        print(pending_describe(load_pending()))
        return 0

    if args.poll:
        return poll_all(state, args.smoke_once)

    if args.pending_poll:
        if KILL:
            raise SystemExit("MOMENTUM_KILL is on - refusing to place orders.")
        why = approval_ready()
        if why:
            raise SystemExit(why)
        return pending_poll(state, args.smoke_once)

    if args.pending_cancel:
        pend = load_pending()
        if pend.get("stage") != "offered":
            raise SystemExit(f"nothing to cancel (stage "
                             f"{pend.get('stage') or 'none'!r}).\n"
                             + pending_describe(pend))
        pend["stage"] = "cancelled"
        pend["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        save_pending(pend)
        if discord_api is not None and discord_api.configured():
            discord_api.delete_message(pend.get("message_id"))
        print(f"cancelled {pend['month']}; nothing was ordered.")
        return 0

    if args.pending_resume or args.pending_abandon:
        if KILL and args.pending_resume:
            raise SystemExit("MOMENTUM_KILL is on - refusing to place orders.")
        pend = load_pending()
        if pend.get("stage") != "stuck":
            raise SystemExit(f"only a halted batch can be resumed or abandoned "
                             f"(stage {pend.get('stage') or 'none'!r}).")
        if args.pending_abandon:
            # You have looked at the app and decided the rest is not going to be
            # sent. Record what definitely was, so the book stops describing a
            # portfolio nobody holds, and close the month.
            pend["stage"] = "abandoned"
            save_pending(pend)
            settle_batch(state, pend, "abandoned by hand after a halt")
            print("\nThe month is now marked rebalanced. Anything the broker "
                  "filled that is\nnot in the list above is invisible to the "
                  "book - put it right with --fill.")
            return 0
        # Resuming clears the halt so execute_batch will look again. It still
        # refuses if an order's fate is genuinely unknown; --pending-abandon is
        # the way past that, because only you can read the app.
        why = approval_ready()
        if why:
            raise SystemExit(why)
        pend["stage"] = "trading"
        pend.pop("error", None)
        save_pending(pend)
        return execute_batch(state, pend)

    # --- the optional broker link -------------------------------------------
    if args.discord_check:
        if discord_api is None:
            raise SystemExit(f"discord_api.py did not load: {_DISCORD_IMPORT_ERROR}")
        print(env_source_line())
        d = discord_api
        if not d.configured():
            raise SystemExit(f"Discord approval is {d.why_not()}.\n"
                             f"Fill those in on the Settings page.")
        try:
            who = d.me()
            print(f"bot      : {who.get('username')}#{who.get('discriminator','0')} "
                  f"(id {who.get('id')})")
            ch = d.channel()
            print(f"channel  : #{ch.get('name')} (id {ch.get('id')})")
            print(f"owner    : {d.OWNER_ID}  - only a tick from this id approves\n")
            mid = d.post("**Setup check.** Tick this message to prove approval "
                         "works. Nothing is ordered either way.")
            d.offer_tick(mid)
            print(f"posted message {mid} and added {d.TICK}.")
            print("\nTick it in Discord, then run this again to confirm it was read:")
            print(f"  python3 momentum_bot.py --discord-confirm {mid}")
            return 0
        except d.DiscordError as exc:
            raise SystemExit(f"Discord: {exc}")

    if args.discord_confirm:
        if discord_api is None:
            raise SystemExit(f"discord_api.py did not load: {_DISCORD_IMPORT_ERROR}")
        d = discord_api
        if not d.configured():
            raise SystemExit(f"Discord approval is {d.why_not()}")
        try:
            who = d.reactors(args.discord_confirm)
        except d.DiscordError as exc:
            raise SystemExit(f"Discord: {exc}")
        if not who:
            print("nobody has ticked it yet.")
            return 1
        if d.OWNER_ID in who:
            print(f"approved by {d.OWNER_ID}. Reaction approval works.")
            return 0
        print(f"ticked by {', '.join(who)}, but none of them is DISCORD_OWNER_ID "
              f"({d.OWNER_ID}). Not approved - check the owner id is yours.")
        return 1

    if args.smoke_status:
        print(smoke_describe(load_smoke()))
        return 0

    if args.smoke_offer or args.smoke_poll:
        if t212 is None:
            raise SystemExit(f"t212.py did not load: {_T212_IMPORT_ERROR}")
        if discord_api is None:
            raise SystemExit(f"discord_api.py did not load: {_DISCORD_IMPORT_ERROR}")
        if not t212.configured():
            raise SystemExit(t212.why_not())
        if not discord_api.configured():
            raise SystemExit(f"Discord approval is {discord_api.why_not()}")
        d = discord_api
        s = load_smoke()

    if args.smoke_offer:
        if s.get("stage") == "bought":
            raise SystemExit("a test position is already open - close it first:\n"
                             + smoke_describe(s))
        code = t212.resolve_universe([SMOKE_TICKER])["map"].get(SMOKE_TICKER)
        if not code:
            raise SystemExit(f"{SMOKE_TICKER} did not resolve to an instrument code")
        px = fetch()
        last = float(px[SMOKE_TICKER].iloc[-1])
        target = min(2.0, SMOKE_MAX_USD)      # ~1 EUR is under the broker minimum
        # Truncate to exactly what place_market_order will send, so the message,
        # the cap check and the fill are the same number.
        qty = t212._round_qty(target / last)
        notional = qty * last
        if qty <= 0:
            raise SystemExit(f"{SMOKE_TICKER} at ${last:,.2f} - ${target:.2f} is "
                             f"below the smallest orderable quantity")
        if notional > SMOKE_MAX_USD:
            raise SystemExit(f"refusing: {notional:.2f} is over the {SMOKE_MAX_USD} cap")

        # One message, one reaction, one decision. Offering buy and sell on the
        # same message meant reading two answers off one object and hoping you
        # meant the newer one; the sell is now asked for separately, after the
        # buy has actually happened.
        body = (f"**Smoke test - this places a REAL order for about "
                f"${notional:.2f}.**\n\n"
                f"React {d.TICK} to buy {qty} of `{code}` "
                f"(~${notional:.2f} at the last close of ${last:,.2f}).\n"
                f"I will ask about selling it back afterwards, in a new message.\n\n"
                f"Only a reaction from <@{d.OWNER_ID}> counts. Expires in "
                f"{SMOKE_EXPIRY_MIN} minutes - ignore it and nothing happens.\n"
                f"US market hours only; outside them the order sits unfilled.")
        mid = d.post(body)
        d.offer_tick(mid, d.TICK)
        save_smoke({"stage": "offered", "message_id": mid, "code": code,
                    "qty": qty, "last": last, "notional": notional,
                    "offered_at": datetime.now(timezone.utc).isoformat()})
        print(f"offered in Discord (message {mid}):\n  buy {qty} {code} "
              f"~${notional:.2f}\n\nReact {d.TICK} - the timer will do the rest.")
        return 0

    if args.smoke_poll:
        return smoke_poll(args.smoke_once)

    if args.t212_find:
        if t212 is None:
            raise SystemExit(f"t212.py did not load: {_T212_IMPORT_ERROR}")
        if not t212.configured():
            raise SystemExit(t212.why_not())
        hits = t212.find_instruments(args.t212_find)
        if not hits:
            print(f"nothing matching {args.t212_find!r}")
            # A miss can mean the instrument is absent, or that the field being
            # searched is not called what this code assumes. Show a real row so
            # the difference is visible instead of guessed at.
            try:
                rows = t212.instruments()
                if rows:
                    print(f"\n  {len(rows):,} instruments searched. Fields on a "
                          f"row: {', '.join(sorted(rows[0]))}")
                    print(f"  Example: {json.dumps(rows[0], default=str)[:400]}")
                    print("\n  If none of those fields is a company name, this "
                          "search only ever matched codes.")
            except Exception as exc:                       # noqa: BLE001
                print(f"  (could not show a sample row: {exc})")
            return 1
        print(f"{len(hits)} match(es) for {args.t212_find!r}:\n")
        for h in hits:
            print(f"  {h['code']:<18} {str(h['type'])[:8]:<8} "
                  f"{str(h['currency'])[:4]:<4} {h['isin'] or '':<14} {h['name'][:40]}")
        return 0

    if args.t212_instruments:
        if t212 is None:
            raise SystemExit(f"t212.py did not load: {_T212_IMPORT_ERROR}")
        print(env_source_line())
        if not t212.configured():
            raise SystemExit(t212.why_not())
        r = t212.resolve_universe(UNIVERSE)
        print(f"{r['checked']:,} instruments listed by the broker\n")
        for tk in UNIVERSE:
            code = r["map"].get(tk)
            note = ""
            if tk in r.get("renamed", {}):
                info = r["renamed"][tk]
                note = f"   <- renamed; {info['name']}, ISIN {info['isin']}"
            print(f"  {tk:<6} -> {code}{note}" if code else f"  {tk:<6} -> ??")
        if r["ambiguous"]:
            print("\n  AMBIGUOUS - more than one plausible code, so none was chosen:")
            for tk, codes in sorted(r["ambiguous"].items()):
                print(f"    {tk}: {', '.join(codes)}")
        if r["missing"]:
            print(f"\n  NOT FOUND: {', '.join(r['missing'])}")
        clean = not r["ambiguous"] and not r["missing"]
        print(f"\n  {len(r['map'])}/{len(UNIVERSE)} resolved."
              + ("" if clean else "  Orders cannot be placed until every name resolves."))
        return 0 if clean else 1

    if args.transactions is not None:
        if t212 is None:
            raise SystemExit(f"t212.py did not load: {_T212_IMPORT_ERROR}")
        if not t212.configured():
            raise SystemExit(t212.why_not())
        print(json.dumps(t212.fees(args.transactions), indent=1, default=str))
        return 0

    if args.t212_probe:
        if t212 is None:
            raise SystemExit(f"t212.py did not load: {_T212_IMPORT_ERROR}")
        print(env_source_line())
        return t212.probe()

    if args.t212_check or args.t212_sync:
        if t212 is None:
            raise SystemExit(f"t212.py did not load: {_T212_IMPORT_ERROR}")
        if not t212.configured():
            raise SystemExit(t212.why_not() + "\n"
                             "Set T212_API_KEY and T212_ENV in the config, then: "
                             "set -a; . /etc/momentum-bot.env; set +a")
        snap = broker()
        if snap is None:
            return 1
        # Acts on this run's book (demo or live), against the account --env
        # picked.
        live = book(state, TRACK)
        scope = "non-pie holdings in the universe"
        print(f"Trading 212 ({t212.ENV}) - {scope}")
        print(f"  holds {len(snap['positions'])} names worth {money(snap['invested'])}")
        print(f"  the account's free funds are {money(snap['cash'])} - that is the "
              f"WHOLE account,\n  not this strategy's, and the bot never adopts it "
              f"as its own.")
        if (args.t212_sync and live["positions"] and not snap["positions"]
                and not args.force):
            raise SystemExit(
                f"  the broker reports no positions but the {TRACK} book holds "
                f"{len(live['positions'])}.\n"
                f"  Refusing to erase it. If you really did sell everything, "
                f"repeat with --force.")
        diffs = reconcile(live, snap, adopt=args.t212_sync)
        if not diffs:
            print(f"  the {TRACK} book already matches. Nothing to do.")
        else:
            print(f"\n  {'':<8} {'bot thinks':>14} {'broker says':>14}")
            for tk, a, b in diffs:
                print(f"  {tk:<8} {a:>14,.4f} {b:>14,.4f}")
            if args.t212_sync:
                save_state(state)
                # Trading 212's per-share price is USD; the live book is in the
                # account currency, so convert before marking.
                m = mark(live, to_live({tk: q["value"] / q["shares"]
                                        for tk, q in snap["positions"].items()
                                        if q["shares"]}))
                print(f"\n  adopted into the {TRACK} book. account {money(m['total'])}, "
                      f"{money(m['deposited'])} paid in")
            else:
                print("\n  nothing changed. --t212-sync adopts the broker's numbers.")
        return 0

    # --- cash in and out -----------------------------------------------------
    for amount, sign, verb in ((args.deposit, 1, "deposited"),
                               (args.withdraw, -1, "withdrew")):
        if amount is None:
            continue
        if amount <= 0:
            raise SystemExit(f"--{'deposit' if sign > 0 else 'withdraw'} wants a "
                             f"positive amount")
        if sign < 0 and amount > bk["cash"] + 1e-9:
            raise SystemExit(f"only {money(bk['cash'])} in cash on the {name} book - "
                             f"sell something first, or withdraw less")
        bk["cash"] += sign * amount
        bk["deposited"] += sign * amount
        save_state(state)
        append_deposit(name, datetime.now(timezone.utc).date(), sign * amount)
        print(f"{verb} {money(amount)} to the {name} book - cash now "
              f"{money(bk['cash'])}, {money(bk['deposited'])} paid in overall")

    # --- corrections to what the bot assumed --------------------------------
    if args.fill:
        for spec in args.fill:
            tk, sh, pr = parse_fill(spec)
            apply_orders(bk, [(tk, sh, -sh * pr)], {tk: pr})
            print(f"recorded {'buy' if sh > 0 else 'sell'} of {abs(sh)} {tk} "
                  f"@ {money(pr)} on the {name} book - cash now {money(bk['cash'])}")
        save_state(state)

    if args.deposit is not None or args.withdraw is not None or args.fill:
        if not (args.status or args.report or args.json):
            return 0

    # --- light money-only refresh, for a frequent timer --------------------
    if args.refresh_live:
        return refresh_live(state)

    # --- machine-readable, for the dashboard --------------------------------
    if args.json:
        snap = broker()                 # one fetch, shared with refresh() below
        refresh(state, snap)
        px = fetch()
        prices = px.iloc[-1].to_dict()
        scores = rank(px)
        # Trading 212's own holdings prices for the account this run read, so the
        # dashboard's value matches the app rather than a yfinance mark.
        held_px = t212_held_prices(snap)
        payload = snapshot_payload(state, prices, scores, px.index[-1],
                                   held_px=held_px)
        payload["due"] = due(px, book(state, name))
        write_latest(payload)
        for t in TRACKS:
            px_live = dict(to_live(prices))
            if held_px and t == TRACK:
                px_live.update(held_px)
            record_day(px.index[-1].date(), t, mark(book(state, t), px_live))
        print(json.dumps(payload, indent=1, default=str))
        return 0

    # --- the account, marked to the latest close ----------------------------
    if args.status or args.report:
        if not bk["positions"]:
            m = mark(bk, {})
            print(env_source_line())
            print(f"track         : {name}")
            print(f"basket        : {', '.join(bk['basket']) or '(empty)'}")
            print(f"last rebalance: {bk.get('last_rebalance') or 'never'}")
            print(f"cash          : {money(m['cash'])}")
            print(f"paid in       : {money(m['deposited'])}")
            if not args.report:
                return 0
        else:
            refresh(state)
            px = fetch()
            usd = px.iloc[-1].to_dict()
            m = mark(bk, to_live(usd))
            print(env_source_line())
            print(f"ACCOUNT   {money(m['total'])}   "
                  f"{m['pnl']:+,.2f} = {m['pnl_pct']:+.1f}% "
                  f"on {money(m['deposited'])} paid in")
            print(f"  invested  {money(m['invested'])}   "
                  f"cash {money(m['cash'])}   [{name}]")
            print(f"  open      {m['unrealised']:+,.2f}   "
                  f"banked {m['realised']:+,.2f}")
            print(f"  since     {bk.get('last_rebalance') or 'never'}\n")
            print("\n".join(render_book(m)))
        if args.report:
            if not args.webhook:
                raise SystemExit("no webhook set ($DISCORD_WEBHOOK)")
            bar = px.index[-1] if bk["positions"] else datetime.now(timezone.utc)
            post(args.webhook, render_snapshot(bar, m, bk))
            print("\nposted to Discord")
        return 0

    if KILL:
        if book(state, "live").get("kill_done"):
            print("MOMENTUM_KILL is on - no rebalance. Turn it off to resume.")
            return 0
        return kill_switch(state)

    refresh(state)
    px = fetch()
    prices = px.iloc[-1].to_dict()                     # USD, straight from yfinance
    # Both books are real accounts in the account currency, so the prices this
    # run sizes and marks with are converted.
    book_prices = to_live(prices)
    scores = rank(px)
    basket = list(scores.index[:HOLD])
    held = bk.get("basket", [])
    bar = px.index[-1]

    if not (args.force or args.test or due(px, bk)):
        m = mark(bk, book_prices)
        if bk.get("last_rebalance"):
            print(f"{bar.date()}: already rebalanced this month "
                  f"({bk.get('last_rebalance')}). Nothing to do.")
        else:
            print(f"{bar.date()}: funded but not started - the opening position "
                  f"waits for the first trading day of {next_month_label(bar)}.")
        if m["deposited"]:
            print(f"  account {money(m['total'])}  {m['pnl_pct']:+.1f}%")
        # Nothing to trade, but this is still a day worth recording — it is what
        # gives the dashboard a daily line rather than a monthly staircase.
        for t in TRACKS:
            record_day(bar.date(), t,
                       mark(book(state, t), to_live(prices)))
        write_latest(snapshot_payload(state, prices, scores, bar))
        return 0

    # A month can only be out for approval once. Without this, tomorrow's run
    # would see an unmarked month, plan the same trades again, and post a second
    # set of orders over the top of the first -- and a tick on either message
    # would place them. The month is not marked done until the orders are
    # actually sent, so this file is what holds the place in the meantime.
    pend = load_pending()
    tag = f"{bar.year}-{bar.month:02d}"
    if pend.get("stage") in PENDING_OPEN and not (args.dry or args.test):
        if name == "demo":
            # Nothing polls the demo batch file, so a demo run that died
            # mid-batch would wedge here forever. Finish it instead.
            print(f"resuming an unfinished demo batch ({pend.get('month')}).")
            return execute_batch(state, pend)
        print(f"{pend.get('month')} is already out for approval - not planning it "
              f"again.\n\n{pending_describe(pend)}")
        return 0
    if (pend.get("month") == tag and pend.get("stage") in ("cancelled", "expired")
            and not (args.force or args.dry or args.test)):
        # You said no, or you let it lapse. Re-posting the same orders every day
        # until you gave in would make the checkmark meaningless.
        print(f"{tag} was {pend['stage']} - not offering it again. Use --force if "
              f"you have changed your mind.")
        return 0

    buys = [t for t in basket if t not in held]
    sells = [t for t in held if t not in basket]
    first = not held

    # Money going in this rebalance, both drawn from Trading 212 free funds when
    # you approve the buys. --dry and --test return before the save below, and
    # the autotrade path returns before it too -- settle_batch applies the exact
    # same credit once the orders are actually sent.
    #
    #   opening : the Starting amount, on the very first rebalance of an empty
    #             book (demo or live). The `not bk["deposited"]` guard makes it
    #             inert after.
    #   monthly : the contribution, every rebalance after the first. Not on the
    #             opening one -- that is the amount you are seeding by hand.
    #
    # Both credit cash (so plan() can spend them) and deposited (so they are not
    # read as profit), on the assumption the euros are in free funds.
    opening = 0.0
    if first and START_BUDGET > 0 and not bk["deposited"]:
        opening = START_BUDGET
        bk["cash"] += opening
        bk["deposited"] += opening

    paid_in_today = 0.0
    if MONTHLY > 0 and not first:
        paid_in_today = MONTHLY
        bk["cash"] += MONTHLY
        bk["deposited"] += MONTHLY

    m = mark(bk, book_prices)
    orders = (plan(bk, book_prices, basket, m["total"], contribution=paid_in_today,
                   reserve=CASH_BUFFER)
              if m["total"] > 0 else [])
    print(render_plain(bar, buys, sells, basket, scores, m, orders, book_prices))
    if opening:
        print(f"\n  + {money(opening)} starting amount, drawn from your Trading "
              f"212 free funds and split over the {len(basket)} opening positions.")
    if paid_in_today:
        print(f"\n  + {money(paid_in_today)} contribution this month, drawn from "
              f"free funds and spread over all {len(basket)} holdings. If a "
              f"standing order bounced, correct it with --fill and set Monthly "
              f"to 0 until it is reliable.")
    if MONTHLY > 0 and first:
        print(f"\n  ({money(MONTHLY)} monthly contribution starts next month - "
              f"this is the opening rebalance.)")
    if m["total"] <= 0:
        print("\n  ! nothing to size against - set a Starting amount on the "
              "Settings page, or run --deposit AMOUNT.")

    if args.dry:
        print("\n[--dry] nothing posted, state unchanged")
        return 0

    if args.test:
        if not args.webhook:
            raise SystemExit("no webhook set ($DISCORD_WEBHOOK) - nothing to test")
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first,
                                        test=True, m=m, orders=orders,
                                        prices=book_prices))
        print("\n[--test] posted to Discord. state.json and rebalances.csv "
              "untouched - this was not a rebalance, and the book did not move.")
        return 0

    # When there is a batch to place, the execution path below posts its own
    # Discord message (an approval card for live, a record for demo). The webhook
    # embed would just be a second copy of the same eight lines, so it is skipped.
    if not buys and not sells and not first and not orders:
        print("\nbasket unchanged and nothing to trim - not posting")
    elif orders:
        print("\n(skipping the webhook card - the Discord message below covers it)")
    elif args.webhook:
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first,
                                        m=m, orders=orders, prices=book_prices))
        print("\nposted to Discord")
    else:
        print("\nno webhook set ($DISCORD_WEBHOOK) - printed only")

    # EXECUTION FORKS BY ACCOUNT.
    #
    #   live : the batch goes out for approval. Nothing is placed and the month
    #          stays unmarked until a reaction lands and the poller runs
    #          execute_batch(); everything below is deferred to settle_batch().
    #   demo : fake money, so there is nothing to approve. The batch is placed
    #          and settled right here, in this process, and a record is posted to
    #          the demo channel.
    #
    # With no batch to place (orders empty) the run falls through to the tail
    # below, which just marks the month checked so it is not re-planned tomorrow.
    if orders:
        why = approval_ready()
        if why:
            raise SystemExit(f"cannot place the {name} batch: {why}")
        if name == "demo":
            propose_batch(name, bar, basket, orders, book_prices,
                          paid_in_today, m, monthly=0.0 if first else MONTHLY,
                          start=opening, require_approval=False)
            # Reload the state. This run's in-memory book was already credited
            # the starting amount / contribution above, and settle_batch credits
            # them again -- the live path dodges that by exiting here and letting
            # a fresh --poll process settle. The demo path settles in-process, so
            # it has to start from a clean book the same way that process would.
            return execute_batch(load_state(), load_pending())
        return propose_batch(name, bar, basket, orders, book_prices,
                             paid_in_today, m,
                             monthly=0.0 if first else MONTHLY,
                             start=opening)

    # Assume the orders filled at today's close. --fill corrects any that did not.
    apply_orders(bk, orders, book_prices)
    after = mark(bk, book_prices)
    bk["equity"].append([str(bar.date()), round(after["total"], 2)])
    bk.update({"basket": basket,
               "last_rebalance": str(bar.date()),
               "last_rebalance_month": f"{bar.year}-{bar.month:02d}"})
    save_state(state)
    log_row(bar.date(), buys, sells, basket, after["total"], after["cash"],
            after["deposited"], after["pnl"], name)
    for t in TRACKS:
        record_day(bar.date(), t, mark(book(state, t), to_live(prices)))
    write_latest(snapshot_payload(state, prices, scores, bar))
    if orders:
        print(f"recorded {len(orders)} fills at the {bar.date()} close · "
              f"account {money(after['total'])} · cash {money(after['cash'])}")
        print("if your fills differed:  --fill TICKER=SHARES@PRICE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
