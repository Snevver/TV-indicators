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

# Optional broker link. A missing, broken or half-written t212.py must not stop
# the bot running — the whole point of it is that it is not required.
try:
    import t212
except Exception as _t212_exc:                       # noqa: BLE001
    t212 = None
    _T212_IMPORT_ERROR = f"{type(_t212_exc).__name__}: {_t212_exc}"
else:
    _T212_IMPORT_ERROR = ""
STATE = os.path.join(HERE, "state.json")
LOG = os.path.join(HERE, "rebalances.csv")
HISTORY = os.path.join(HERE, "history.csv")     # one row per day per track
LATEST = os.path.join(HERE, "latest.json")      # the dashboard's render cache

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
CURRENCY = os.environ.get("MOMENTUM_CURRENCY", "EUR")
SYM = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(CURRENCY, CURRENCY + " ")

# Don't generate an order for loose change.
MIN_ORDER = float(os.environ.get("MOMENTUM_MIN_ORDER", "1") or 1)

# What a standing order pays in each month. Credited to the PAPER book on
# rebalance day and spread over all eight holdings -- sell proceeds keep funding
# the arriving names on their own, which is how it was measured. 0 turns it off.
#
# Paper only, deliberately. The live book takes its cash from Trading 212, so
# crediting it here would count the same euros twice. And the paper book is a
# model: if the transfer bounces, this number is a claim about money that never
# arrived, which is why every message that uses it says so.
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

# Two books are kept side by side.
#   paper : the strategy simulated on assumed fills. Always runs, never touched
#           by the broker, so there is something to measure execution against.
#   live  : what Trading 212 actually holds.
# MOMENTUM_TRACK picks which one the bot plans from and reports on. It does NOT
# decide whether anything is traded -- nothing here ever trades. Every call to
# the broker is a GET; the only POST in this file goes to Discord. Setting it to
# 'live' cannot move money, fund a pie, or place an order, because no code to do
# any of that exists.
#
# What it does change: which holdings the monthly instructions are worked out
# from. Once you are following the live book, orders have to be planned from
# what you really hold, or the bot will tell you to sell something you do not
# own.
TRACKS = ("paper", "live")
TRACK = os.environ.get("MOMENTUM_TRACK", "paper").strip().lower()
if TRACK not in TRACKS:
    raise SystemExit(f"MOMENTUM_TRACK must be 'paper' or 'live', not {TRACK!r}")

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
        # A schema-1 file: one flat book, which was the paper one by definition —
        # nothing had a broker link when it was written.
        s = {"schema": 2,
             "tracks": {"paper": {k: s.get(k, _blank()[k]) for k in EMPTY_BOOK},
                        "live": _blank()}}

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
        raise SystemExit(f"only {len(cols)} usable tickers — aborting rather than "
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


def plan(bk, prices, basket, total, contribution: float = 0.0) -> list:
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

    buys = {}
    arriving = priced(t for t in basket if pos.get(t, 0.0) <= 0)
    pot = bk["cash"] + sum(o[2] for o in sells) - contribution
    if arriving and pot > 0:
        each = pot / len(arriving)
        for tk in arriving:
            buys[tk] = buys.get(tk, 0.0) + each / prices[tk]
    spread_over = priced(basket)
    if contribution > 0 and spread_over:
        each = contribution / len(spread_over)
        for tk in spread_over:
            buys[tk] = buys.get(tk, 0.0) + each / prices[tk]

    orders = list(sells)
    for tk in basket:                      # basket order, so the message reads well
        sh = buys.get(tk, 0.0)
        if sh > 0 and sh * prices[tk] >= MIN_ORDER:
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


def refresh(state) -> bool:
    """Mirror the broker into the LIVE track. Returns True if anything was read.

    This never touches the paper track. Paper is the strategy simulated on
    assumed fills; keeping it independent is the only way to tell later whether
    a bad month was the strategy or your own execution.

    Silent when there is no key — that is the normal case and not a problem.
    """
    snap = broker()
    if snap is None:
        return False
    live = book(state, "live")
    # A broker that reports nothing while the live book holds positions is far
    # more likely to be a mapping or permissions problem than a portfolio you
    # emptied by hand. Never let the automatic path act on it — --t212-sync
    # --force is how you say you really did sell everything.
    if live["positions"] and not snap["positions"]:
        print("  ! Trading 212 reports no positions, but the live book holds "
              f"{len(live['positions'])}. Not adopting that — it would erase "
              f"the book. Check --t212-probe, or --t212-sync --force if you "
              f"really did sell everything.")
        return False
    diffs = reconcile(live, snap, adopt=True)
    save_state(state)
    where = f"pie {t212.PIE_ID}" if snap["scoped_to_pie"] else "account"
    print(f"  [Trading 212 {t212.ENV}/{where}] {len(snap['positions'])} positions"
          + (f", {len(diffs)} corrected" if diffs else ", already matching"))
    return True


def broker() -> dict | None:
    """The broker's view, or None if it is not set up or did not answer."""
    if t212 is None:
        if _T212_IMPORT_ERROR:
            print(f"  ! t212.py did not load ({_T212_IMPORT_ERROR}) — using the "
                  f"bot's own book")
        return None
    try:
        if not t212.configured():
            return None
        return t212.snapshot()
    except Exception as exc:                          # belt and braces
        print(f"  ! Trading 212 link failed ({type(exc).__name__}: {exc}) — "
              f"using the bot's own book")
        return None


def reconcile(bk, snap, adopt: bool) -> list:
    """Compare the bot's book with the broker's. Returns the differences.

    With adopt=False nothing changes — this is the report --t212-check prints.
    With adopt=True the broker wins, because it is the one that actually holds
    the shares. Money paid in is never touched: the broker cannot know what you
    funded versus what you earned, and overwriting it would turn a deposit into
    a profit.
    """
    diffs, mine = [], bk["positions"]
    theirs = snap["positions"]
    for tk in sorted(set(mine) | set(theirs)):
        a, b = mine.get(tk, 0.0), theirs.get(tk, {}).get("shares", 0.0)
        # Scale the tolerance: brokers round share counts for display, and a
        # difference of a millionth of a share is noise, not a discrepancy.
        if abs(a - b) > max(1e-6, 1e-4 * max(a, b)):
            diffs.append((tk, a, b))
    if abs(bk["cash"] - snap["cash"]) > 0.01 and not snap["scoped_to_pie"]:
        diffs.append(("(cash)", bk["cash"], snap["cash"]))

    if adopt:
        bk["positions"] = {tk: p["shares"] for tk, p in theirs.items()}
        bk["book"] = {tk: p["cost"] for tk, p in theirs.items()}
        if not snap["scoped_to_pie"]:
            bk["cash"] = snap["cash"]
        if not bk["deposited"]:
            # Nothing was ever declared, so the only honest starting point is
            # what is there now. Say so rather than quietly inventing a return.
            bk["deposited"] = snap["total"]
            print(f"  note: nothing was paid in on record, so {money(snap['total'])} "
                  f"is being treated as the starting balance. Use --deposit if "
                  f"that is wrong.")
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
        change_name = f"Opening position — {len(basket)} names"
    elif changed:
        rows = [f"+ {t}" for t in buys] + [f"- {t}" for t in sells]
        change = "```diff\n" + "\n".join(rows) + "\n```"
        change_name = f"Changes — {len(buys)} in, {len(sells)} out"
    else:
        change = "```\nNo change. Same eight names as last month.\n```"
        change_name = "Changes — none"

    held = [f"{i:>2}  {tk:<5} {m * 100:>7.1f}%"
            for i, (tk, m) in enumerate(scores.head(HOLD).items(), 1)]
    bench = [f"{i:>2}  {tk:<5} {m * 100:>7.1f}%"
             for i, (tk, m) in enumerate(scores.iloc[HOLD:HOLD + 4].items(), HOLD + 1)]

    fields = [{"name": change_name, "value": change, "inline": False}]

    if orders and prices is not None:
        rows = render_orders(orders, prices)
        fields.append({"name": f"Orders — {len(orders)} to place",
                       "value": clip("```\n" + "\n".join(rows) + "\n```"),
                       "inline": False})

    size = f" · {money(m['total'] / HOLD)} each" if m and m["total"] else ""
    fields += [
        {"name": f"Portfolio — equal weight{size}",
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
        title = "TEST — " + title
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
        {"name": f"Holdings — {len(m['rows'])} names · cash {money(m['cash'])}",
         "value": clip("```\n" + "\n".join(rows) + "\n```"), "inline": False},
    ]
    return {"embeds": [{
        "title": "Portfolio",
        "description": f"**{bar.strftime('%-d %B %Y')}** · marked at the latest close",
        "color": GREEN if m["pnl"] >= 0 else 0xC0392B,
        "fields": fields,
        "footer": {"text": f"Held since {bk.get('last_rebalance') or '—'} · "
                           f"next rebalance {next_month_label(bar)}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}


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


def snapshot_payload(state, prices, scores, bar) -> dict:
    """Everything the dashboard renders from, both tracks, no network needed."""
    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "bar": str(bar.date()) if hasattr(bar, "date") else str(bar),
           "currency": CURRENCY, "symbol": SYM, "track": TRACK, "hold": HOLD,
           "next_rebalance": next_month_label(bar),
           "ranking": [{"ticker": tk, "momentum_pct": round(float(v) * 100, 2),
                        "held": i < HOLD}
                       for i, (tk, v) in enumerate(scores.items())][:20],
           "tracks": {}}
    for name in TRACKS:
        bk = book(state, name)
        m = mark(bk, prices)
        out["tracks"][name] = {
            "total": round(m["total"], 2), "invested": round(m["invested"], 2),
            "cash": round(m["cash"], 2), "deposited": round(m["deposited"], 2),
            "pnl": round(m["pnl"], 2), "pnl_pct": round(m["pnl_pct"], 2),
            "realised": round(m["realised"], 2),
            "unrealised": round(m["unrealised"], 2),
            "basket": bk["basket"], "last_rebalance": bk["last_rebalance"],
            "equity": bk["equity"],
            "positions": {tk: {"shares": r["shares"], "price": round(r["price"], 2),
                               "value": round(r["value"], 2),
                               "cost": round(r["cost"], 2),
                               "pnl": round(r["pnl"], 2),
                               "pnl_pct": round(r["pnl_pct"], 2),
                               "weight_pct": round(r["value"] / m["total"] * 100, 2)
                               if m["total"] else 0.0}
                          for tk, r in m["rows"].items()},
        }
    out["t212"] = {"available": t212 is not None,
                   "configured": bool(t212 is not None and t212.configured()),
                   "reason": (t212.why_not() if t212 is not None else
                              _T212_IMPORT_ERROR),
                   "env": getattr(t212, "ENV", ""),
                   "pie": getattr(t212, "PIE_ID", "")}
    return out


def write_latest(payload: dict) -> None:
    tmp = LATEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    os.replace(tmp, LATEST)


LOG_COLS = ("date", "buys", "sells", "basket", "account", "cash", "deposited", "pnl")


def log_row(when, buys, sells, basket, total=0.0, cash=0.0,
            deposited=0.0, pnl=0.0) -> None:
    """Record one rebalance, replacing any row already logged for that date.

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
                    if r.get("date") != str(when):
                        rows.append(r)
        except (OSError, csv.Error):
            rows = []

    rows.append({"date": str(when), "buys": " ".join(buys), "sells": " ".join(sells),
                 "basket": " ".join(basket), "account": f"{total:.2f}",
                 "cash": f"{cash:.2f}", "deposited": f"{deposited:.2f}",
                 "pnl": f"{pnl:.2f}"})
    rows.sort(key=lambda r: r.get("date") or "")

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
        return (f"config    : no env file found ({ETC_ENV}, {USER_ENV}) — "
                f"using defaults and whatever is exported")
    names = ", ".join(ENV_FILES_LOADED)
    return f"config    : {names}" + ("" if len(ENV_FILES_LOADED) > 1 else
                                     "  (the other was not found)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="decide and print, post nothing")
    p.add_argument("--force", action="store_true", help="rebalance regardless of date")
    p.add_argument("--status", action="store_true", help="show the account and exit")
    p.add_argument("--json", action="store_true",
                   help="machine-readable status for the dashboard; posts nothing")
    p.add_argument("--report", action="store_true",
                   help="post the account to Discord without rebalancing")
    p.add_argument("--test", action="store_true",
                   help="post a real message to Discord, save nothing")
    p.add_argument("--track", choices=TRACKS, default=None,
                   help=f"which book to act on (default {TRACK}, $MOMENTUM_TRACK)")
    p.add_argument("--deposit", type=float, metavar="AMOUNT",
                   help="record money paid into the account")
    p.add_argument("--withdraw", type=float, metavar="AMOUNT",
                   help="record money taken out")
    p.add_argument("--fill", action="append", metavar="TICKER=SHARES@PRICE",
                   help="correct an assumed fill; repeatable")
    p.add_argument("--t212-probe", action="store_true",
                   help="print what Trading 212 returns; read-only, changes nothing")
    p.add_argument("--t212-check", action="store_true",
                   help="compare the live book with the broker; changes nothing")
    p.add_argument("--t212-sync", action="store_true",
                   help="adopt the broker's positions and cash as the truth")
    p.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    args = p.parse_args()

    state = load_state()
    name = args.track or TRACK
    bk = book(state, name)

    # --- the optional broker link -------------------------------------------
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
        # These always act on the live book — it is the one that mirrors the
        # broker. Paper is a simulation and has nothing to reconcile against.
        live = book(state, "live")
        scope = f"pie {t212.PIE_ID}" if snap["scoped_to_pie"] else "the whole account"
        print(f"Trading 212 ({t212.ENV}) — {scope}")
        print(f"  holds {len(snap['positions'])} names worth {money(snap['invested'])}"
              + ("" if snap["scoped_to_pie"] else f", cash {money(snap['cash'])}"))
        if (args.t212_sync and live["positions"] and not snap["positions"]
                and not args.force):
            raise SystemExit(
                f"  the broker reports no positions but the live book holds "
                f"{len(live['positions'])}.\n"
                f"  Refusing to erase it. If you really did sell everything, "
                f"repeat with --force.")
        diffs = reconcile(live, snap, adopt=args.t212_sync)
        if not diffs:
            print("  the live book already matches. Nothing to do.")
        else:
            print(f"\n  {'':<8} {'bot thinks':>14} {'broker says':>14}")
            for tk, a, b in diffs:
                print(f"  {tk:<8} {a:>14,.4f} {b:>14,.4f}")
            if args.t212_sync:
                save_state(state)
                m = mark(live, {tk: q["value"] / q["shares"]
                                for tk, q in snap["positions"].items() if q["shares"]})
                print(f"\n  adopted into the live book. account {money(m['total'])}, "
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
            raise SystemExit(f"only {money(bk['cash'])} in cash on the {name} book — "
                             f"sell something first, or withdraw less")
        bk["cash"] += sign * amount
        bk["deposited"] += sign * amount
        save_state(state)
        print(f"{verb} {money(amount)} to the {name} book — cash now "
              f"{money(bk['cash'])}, {money(bk['deposited'])} paid in overall")

    # --- corrections to what the bot assumed --------------------------------
    if args.fill:
        for spec in args.fill:
            tk, sh, pr = parse_fill(spec)
            apply_orders(bk, [(tk, sh, -sh * pr)], {tk: pr})
            print(f"recorded {'buy' if sh > 0 else 'sell'} of {abs(sh)} {tk} "
                  f"@ {money(pr)} on the {name} book — cash now {money(bk['cash'])}")
        save_state(state)

    if args.deposit is not None or args.withdraw is not None or args.fill:
        if not (args.status or args.report or args.json):
            return 0

    # --- machine-readable, for the dashboard --------------------------------
    if args.json:
        refresh(state)
        px = fetch()
        prices = px.iloc[-1].to_dict()
        scores = rank(px)
        payload = snapshot_payload(state, prices, scores, px.index[-1])
        payload["due"] = due(px, book(state, name))
        write_latest(payload)
        for t in TRACKS:
            record_day(px.index[-1].date(), t, mark(book(state, t), prices))
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
            m = mark(bk, px.iloc[-1].to_dict())
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

    refresh(state)
    px = fetch()
    prices = px.iloc[-1].to_dict()
    scores = rank(px)
    basket = list(scores.index[:HOLD])
    held = bk.get("basket", [])
    bar = px.index[-1]

    if not (args.force or args.test or due(px, bk)):
        m = mark(bk, prices)
        if bk.get("last_rebalance"):
            print(f"{bar.date()}: already rebalanced this month "
                  f"({bk.get('last_rebalance')}). Nothing to do.")
        else:
            print(f"{bar.date()}: funded but not started — the opening position "
                  f"waits for the first trading day of {next_month_label(bar)}.")
        if m["deposited"]:
            print(f"  account {money(m['total'])}  {m['pnl_pct']:+.1f}%")
        # Nothing to trade, but this is still a day worth recording — it is what
        # gives the dashboard a daily line rather than a monthly staircase.
        for t in TRACKS:
            record_day(bar.date(), t, mark(book(state, t), prices))
        write_latest(snapshot_payload(state, prices, scores, bar))
        return 0

    buys = [t for t in basket if t not in held]
    sells = [t for t in held if t not in basket]
    first = not held

    # A standing order lands before the rebalance, so the new money is part of
    # what gets allocated today. --dry and --test return before the save below,
    # so nothing is persisted by a preview.
    #
    # Both tracks record the money as paid in; only the paper track also invents
    # the cash and the orders to spend it.
    #
    #   paper : nothing else knows about the money, so the book adds it and
    #           spreads it over the basket itself.
    #   live  : Trading 212 already holds whatever the standing order bought, so
    #           adding cash here would count it twice -- but `deposited` is the
    #           bot's alone. The broker cannot tell what you funded from what you
    #           earned, and reconcile() deliberately never overwrites it. If it
    #           did not go up here, every euro paid in would be reported as
    #           profit: pay in 100 a month for a year and the book would claim
    #           1,200 of gains it never made.
    paid_in_today = 0.0
    if MONTHLY > 0:
        bk["deposited"] += MONTHLY
        if name == "paper":
            bk["cash"] += MONTHLY
            paid_in_today = MONTHLY

    m = mark(bk, prices)
    orders = (plan(bk, prices, basket, m["total"], contribution=paid_in_today)
              if m["total"] > 0 else [])
    print(render_plain(bar, buys, sells, basket, scores, m, orders, prices))
    if MONTHLY > 0 and not paid_in_today:
        print(f"\n  + {money(MONTHLY)} recorded as paid in this month. On the "
              f"live track Trading 212 already holds whatever it bought, so only "
              f"the paid-in total moves here.")
    if paid_in_today:
        print(f"\n  + {money(paid_in_today)} paid in this month, spread over all "
              f"{len(basket)} holdings.")
        print(f"    The paper book assumes it landed. If the transfer bounced, "
              f"the book now holds shares it did not pay for: correct them with "
              f"--fill TICKER=-SHARES@PRICE and set Monthly to 0 until the "
              f"standing order is reliable. --withdraw only helps while the "
              f"cash is still uninvested, which after this run it is not.")
    if m["total"] <= 0:
        print("\n  ! no money on the book — run --deposit AMOUNT so the sizing "
              "and the profit and loss mean something.")

    if args.dry:
        print("\n[--dry] nothing posted, state unchanged")
        return 0

    if args.test:
        if not args.webhook:
            raise SystemExit("no webhook set ($DISCORD_WEBHOOK) — nothing to test")
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first,
                                        test=True, m=m, orders=orders,
                                        prices=prices))
        print("\n[--test] posted to Discord. state.json and rebalances.csv "
              "untouched — this was not a rebalance, and the book did not move.")
        return 0

    if not buys and not sells and not first and not orders:
        print("\nbasket unchanged and nothing to trim — not posting")
    elif args.webhook:
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first,
                                        m=m, orders=orders, prices=prices))
        print("\nposted to Discord")
    else:
        print("\nno webhook set ($DISCORD_WEBHOOK) — printed only")

    # Assume the orders filled at today's close. --fill corrects any that did not.
    apply_orders(bk, orders, prices)
    after = mark(bk, prices)
    bk["equity"].append([str(bar.date()), round(after["total"], 2)])
    bk.update({"basket": basket,
               "last_rebalance": str(bar.date()),
               "last_rebalance_month": f"{bar.year}-{bar.month:02d}"})
    save_state(state)
    log_row(bar.date(), buys, sells, basket, after["total"], after["cash"],
            after["deposited"], after["pnl"])
    for t in TRACKS:
        record_day(bar.date(), t, mark(book(state, t), prices))
    write_latest(snapshot_payload(state, prices, scores, bar))
    if orders:
        print(f"recorded {len(orders)} fills at the {bar.date()} close · "
              f"account {money(after['total'])} · cash {money(after['cash'])}")
        print("if your fills differed:  --fill TICKER=SHARES@PRICE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
