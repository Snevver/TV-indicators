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
    python momentum_bot.py                  # the daily run
    python momentum_bot.py --status         # what am I holding?
    python momentum_bot.py --dry            # decide, print, post nothing
    python momentum_bot.py --force          # rebalance now, ignoring the date

State lives in state.json beside this script. Delete it to start fresh; the next
run will then treat every holding as a new buy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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


def post(webhook: str, text: str) -> None:
    import requests
    r = requests.post(webhook, json={"content": text}, timeout=20)
    if r.status_code not in (200, 204):
        raise SystemExit(f"discord rejected the post ({r.status_code}): {r.text[:200]}")


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

    if not (args.force or due(px, state)):
        print(f"{px.index[-1].date()}: already rebalanced this month "
              f"({state.get('last_rebalance')}). Nothing to do.")
        return 0

    buys = [t for t in basket if t not in held]
    sells = [t for t in held if t not in basket]

    lines = [f"**Momentum rebalance** {px.index[-1].date()}",
             f"BUY: {', '.join(buys) if buys else '—'}",
             f"SELL: {', '.join(sells) if sells else '—'}",
             f"Hold: {', '.join(basket)}",
             "",
             "```",
             f"{'#':>2} {'ticker':<7} {'6m momentum':>12}"]
    for i, (tk, m) in enumerate(scores.head(12).items(), 1):
        lines.append(f"{i:>2} {tk:<7} {m*100:>11.1f}%" + ("  <-- hold" if i <= HOLD else ""))
    lines.append("```")
    msg = "\n".join(lines)
    print(msg)

    if args.dry:
        print("\n[--dry] nothing posted, state unchanged")
        return 0

    if not buys and not sells:
        print("\nbasket unchanged — not posting")
    elif args.webhook:
        post(args.webhook, msg)
        print("\nposted to Discord")
    else:
        print("\nno webhook set ($DISCORD_WEBHOOK) — printed only")

    last_bar = px.index[-1]
    state.update({"basket": basket,
                  "last_rebalance": str(last_bar.date()),
                  "last_rebalance_month": f"{last_bar.year}-{last_bar.month:02d}"})
    save_state(state)
    log_row(last_bar.date(), buys, sells, basket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
