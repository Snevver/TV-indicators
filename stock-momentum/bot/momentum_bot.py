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
    export MOMENTUM_CAPITAL=3000            # optional: show euros per position
    python momentum_bot.py                  # the daily run
    python momentum_bot.py --status         # what am I holding?
    python momentum_bot.py --dry            # decide, print, post nothing
    python momentum_bot.py --test           # post real numbers, save nothing
    python momentum_bot.py --force          # rebalance now, ignoring the date

State lives in state.json beside this script. Delete it to start fresh; the next
run will then treat every holding as a new buy.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
LOG = os.path.join(HERE, "rebalances.csv")

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

# Account size, only ever used to divide by HOLD so the message can show what to
# put in each name. The strategy does not depend on it.
CAPITAL = float(os.environ.get("MOMENTUM_CAPITAL", "0") or 0)
CURRENCY = os.environ.get("MOMENTUM_CURRENCY", "EUR")

GREEN = 0x3BA55D    # something changed
BLURPLE = 0x5865F2  # ranked, nothing to do
AMBER = 0xF0A020    # a test: real numbers, nothing saved, do not trade it


def load_state() -> dict:
    if os.path.exists(STATE):
        with open(STATE) as fh:
            return json.load(fh)
    return {"basket": [], "last_rebalance": None}


def save_state(s: dict) -> None:
    with open(STATE, "w") as fh:
        json.dump(s, fh, indent=1)


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


def due(px, state) -> bool:
    """True on the first trading day of a month we have not rebalanced in.

    Keyed off the newest BAR, not the wall clock, so holidays and weekends need
    no special handling and a run at any hour behaves the same.
    """
    last_bar = px.index[-1]
    tag = f"{last_bar.year}-{last_bar.month:02d}"
    return state.get("last_rebalance_month") != tag


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


def render_plain(bar, buys, sells, basket, scores) -> str:
    """What goes to the console and the journal. Kept readable in a terminal."""
    lines = [f"Momentum rebalance {bar.date()}",
             f"  BUY  : {', '.join(buys) or '-'}",
             f"  SELL : {', '.join(sells) or '-'}",
             f"  HOLD : {', '.join(basket)}"]
    if CAPITAL:
        lines.append(f"  SIZE : {CURRENCY} {CAPITAL / HOLD:,.0f} per position")
    lines.append("")
    for i, (tk, m) in enumerate(scores.head(12).items(), 1):
        lines.append(f"  {i:>2} {tk:<6} {m * 100:>7.1f}%" + ("  <- hold" if i <= HOLD else ""))
    return "\n".join(lines)


def render_embed(bar, buys, sells, basket, scores, first: bool,
                 test: bool = False) -> dict:
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

    size = f" · {CURRENCY} {CAPITAL / HOLD:,.0f} each" if CAPITAL else ""
    fields = [
        {"name": change_name, "value": change, "inline": False},
        {"name": f"Portfolio — equal weight{size}",
         "value": "```\n" + "\n".join(held) + "\n```", "inline": True},
        {"name": "Next in line",
         "value": "```\n" + "\n".join(bench) + "\n```", "inline": True},
    ]

    title = "Opening position" if first else "Monthly rebalance"
    if test:
        title = "TEST — " + title
    footer = (f"Test message · nothing saved · do not trade this"
              if test else
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


def log_row(when, buys, sells, basket) -> None:
    new = not os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8") as fh:
        if new:
            fh.write("date,buys,sells,basket\n")
        fh.write(f'{when},"{" ".join(buys)}","{" ".join(sells)}","{" ".join(basket)}"\n')


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="decide and print, post nothing")
    p.add_argument("--force", action="store_true", help="rebalance regardless of date")
    p.add_argument("--status", action="store_true", help="show holdings and exit")
    p.add_argument("--test", action="store_true",
                   help="post a real message to Discord, save nothing")
    p.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    args = p.parse_args()

    state = load_state()
    if args.status:
        print(f"basket        : {', '.join(state['basket']) or '(empty)'}")
        print(f"last rebalance: {state.get('last_rebalance') or 'never'}")
        return 0

    px = fetch()
    scores = rank(px)
    basket = list(scores.index[:HOLD])
    held = state.get("basket", [])

    if not (args.force or args.test or due(px, state)):
        print(f"{px.index[-1].date()}: already rebalanced this month "
              f"({state.get('last_rebalance')}). Nothing to do.")
        return 0

    buys = [t for t in basket if t not in held]
    sells = [t for t in held if t not in basket]

    first = not held
    bar = px.index[-1]
    print(render_plain(bar, buys, sells, basket, scores))

    if args.dry:
        print("\n[--dry] nothing posted, state unchanged")
        return 0

    if args.test:
        if not args.webhook:
            raise SystemExit("no webhook set ($DISCORD_WEBHOOK) — nothing to test")
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first,
                                        test=True))
        print("\n[--test] posted to Discord. state.json and rebalances.csv "
              "untouched — this was not a rebalance.")
        return 0

    if not buys and not sells and not first:
        print("\nbasket unchanged — not posting")
    elif args.webhook:
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first))
        print("\nposted to Discord")
    else:
        print("\nno webhook set ($DISCORD_WEBHOOK) — printed only")

    state.update({"basket": basket,
                  "last_rebalance": str(bar.date()),
                  "last_rebalance_month": f"{bar.year}-{bar.month:02d}"})
    save_state(state)
    log_row(bar.date(), buys, sells, basket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
