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

# Sizing and bookkeeping. None of this touches the ranking — the strategy is the
# same whatever these say.
CURRENCY = os.environ.get("MOMENTUM_CURRENCY", "EUR")
SYM = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(CURRENCY, CURRENCY + " ")

# Can your broker buy part of a share? With fractional orders every position
# lands exactly on its target weight and the account size stops mattering.
# Without them a name priced above one slice simply cannot be bought, and the
# basket quietly becomes "the cheap half of the ranking".
FRACTIONAL = os.environ.get("MOMENTUM_FRACTIONAL", "1").lower() not in ("0", "no", "false")

# Don't generate an order for loose change.
MIN_ORDER = float(os.environ.get("MOMENTUM_MIN_ORDER", "1") or 1)

# rebalance : every month, reset all eight to an equal slice. This is what the
#             backtest measured, so it is the default.
# drift     : only trade the names that changed, and let the survivors run.
#             Measured better over 2005-2026 ($48.6k against $36.1k from $1,000)
#             with a smaller drawdown, at the cost of concentration — the
#             largest position was typically 17.6% of the account, peaking at
#             37.9%. Far fewer orders, which matters on a small account.
MODE = os.environ.get("MOMENTUM_MODE", "rebalance").lower()
if MODE not in ("rebalance", "drift"):
    raise SystemExit(f"MOMENTUM_MODE must be 'rebalance' or 'drift', not {MODE!r}")

GREEN = 0x3BA55D    # something changed
BLURPLE = 0x5865F2  # ranked, nothing to do
AMBER = 0xF0A020    # a test: real numbers, nothing saved, do not trade it


EMPTY = {"basket": [], "last_rebalance": None,
         "positions": {},    # ticker -> shares held
         "book": {},         # ticker -> what those shares cost
         "cash": 0.0,        # funded but not currently in a stock
         "deposited": 0.0,   # money you put in, so growth can exclude it
         "realised": 0.0,    # profit and loss already banked by selling
         "equity": []}       # [date, account value] at each rebalance


def load_state() -> dict:
    if os.path.exists(STATE):
        with open(STATE) as fh:
            s = json.load(fh)
        for k, v in EMPTY.items():          # a state.json from an older version
            s.setdefault(k, json.loads(json.dumps(v)))
        return s
    return json.loads(json.dumps(EMPTY))


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


# ---------------------------------------------------------------- the book --
#
# Everything below models the account. None of it can change which eight names
# get picked — that happens in rank(), from prices alone.


def money(x: float) -> str:
    return f"{SYM}{x:,.2f}"


def mark(state, prices) -> dict:
    """Value the book at the latest prices."""
    rows = {}
    for tk, sh in state["positions"].items():
        if sh <= 0 or tk not in prices:
            continue
        value = sh * prices[tk]
        cost = state["book"].get(tk, 0.0)
        rows[tk] = {"shares": sh, "price": prices[tk], "value": value, "cost": cost,
                    "pnl": value - cost,
                    "pnl_pct": (value / cost - 1) * 100 if cost else 0.0}
    invested = sum(r["value"] for r in rows.values())
    total = invested + state["cash"]
    dep = state["deposited"]
    return {"rows": rows, "invested": invested, "cash": state["cash"], "total": total,
            "deposited": dep,
            "pnl": total - dep,
            "pnl_pct": (total / dep - 1) * 100 if dep else 0.0,
            "realised": state["realised"],
            "unrealised": sum(r["pnl"] for r in rows.values())}


def plan(state, prices, basket, total) -> list:
    """The orders that move the current book to the new basket.

    Returns (ticker, delta_shares, cash_delta) with sells first, so the cash to
    pay for the buys exists before they are applied.
    """
    orders, pos = [], state["positions"]
    for tk, sh in sorted(pos.items()):
        if sh > 0 and tk not in basket:
            orders.append((tk, -sh, sh * prices.get(tk, 0.0)))

    if MODE == "drift":
        # Survivors are left exactly as they are. Whatever the sells raised,
        # plus any idle cash, is split over the names that are new this month.
        arriving = [t for t in basket if pos.get(t, 0.0) <= 0]
        if arriving:
            pot = state["cash"] + sum(o[2] for o in orders)
            each = pot / len(arriving)
            for tk in arriving:
                sh = each / prices[tk]
                if not FRACTIONAL:
                    sh = float(int(sh))
                if sh * prices[tk] >= MIN_ORDER:
                    orders.append((tk, sh, -sh * prices[tk]))
        return orders

    slice_ = total / HOLD
    want = {}
    for tk in basket:
        w = slice_ / prices[tk]
        want[tk] = w if FRACTIONAL else float(int(w))   # a part share you cannot buy

    if not FRACTIONAL:
        # Rounding down eight times strands real money — at $10,000 it left 15-19%
        # of the account permanently in cash. Spend what is left on whole shares,
        # always topping up whichever name sits furthest below its target, so the
        # remainder lands where it does the least damage to the equal weighting.
        free = state["cash"] + sum(o[2] for o in orders) - sum(
            (want[t] - pos.get(t, 0.0)) * prices[t] for t in basket)
        while True:
            gaps = [(slice_ - want[t] * prices[t], t) for t in basket
                    if prices[t] <= free + 1e-9]
            if not gaps:
                break
            _, tk = max(gaps)
            want[tk] += 1.0
            free -= prices[tk]

    for tk in basket:
        delta = want[tk] - pos.get(tk, 0.0)
        if abs(delta * prices[tk]) >= MIN_ORDER:
            orders.append((tk, delta, -delta * prices[tk]))
    return orders


def apply_orders(state, orders, prices) -> None:
    """Record the orders as filled at `prices`. Cost basis moves proportionally
    on a sell, so realised and unrealised P&L never double-count."""
    for tk, dsh, dcash in orders:
        held = state["positions"].get(tk, 0.0)
        cost = state["book"].get(tk, 0.0)
        if dsh < 0:                                   # selling
            sold = min(-dsh, held)
            share = sold / held if held else 0.0
            state["realised"] += sold * prices[tk] - cost * share
            state["book"][tk] = cost * (1 - share)
            state["positions"][tk] = held - sold
        else:                                         # buying
            state["book"][tk] = cost + dsh * prices[tk]
            state["positions"][tk] = held + dsh
        state["cash"] += dcash
        if state["positions"].get(tk, 0.0) <= 1e-9:
            state["positions"].pop(tk, None)
            state["book"].pop(tk, None)
    state["cash"] = max(round(state["cash"], 6), 0.0)


def parse_fill(spec: str):
    """'MU=0.15@829.50' -> ('MU', 0.15, 829.50). Shares may be negative to
    record a sale you made that the bot does not know about."""
    try:
        tk, rest = spec.split("=", 1)
        sh, pr = rest.split("@", 1)
        return tk.strip().upper(), float(sh), float(pr)
    except ValueError:
        raise SystemExit(f"--fill wants TICKER=SHARES@PRICE, got {spec!r}")


def unbuyable(basket, prices, total) -> list:
    """Names the account cannot hold at an equal weight without part shares."""
    if FRACTIONAL:
        return []
    return [t for t in basket if prices[t] > total / HOLD]


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
                  f"  slice      : {money(m['total'] / HOLD)} per name   [{MODE}]"]
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
                 test: bool = False, m=None, orders=None, prices=None,
                 cannot=()) -> dict:
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
    if test:
        footer = "Test message · nothing saved · do not trade this"
    elif cannot:
        footer = (f"{', '.join(cannot)} cost more than one slice — turn on "
                  f"fractional shares or add funds")
    else:
        footer = f"Buy near the US close · next rebalance {next_month_label(bar)}"

    return {"embeds": [{
        "title": title,
        "description": f"**{bar.strftime('%-d %B %Y')}** · 6-month momentum, "
                       f"top {HOLD} of {len(UNIVERSE)}",
        "color": AMBER if (test or cannot) else (GREEN if (changed or first) else BLURPLE),
        "fields": fields,
        "footer": {"text": footer},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}


def render_snapshot(bar, m, state) -> dict:
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
        "footer": {"text": f"Held since {state.get('last_rebalance') or '—'} · "
                           f"next rebalance {next_month_label(bar)}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}


def log_row(when, buys, sells, basket, total=0.0, cash=0.0,
            deposited=0.0, pnl=0.0) -> None:
    new = not os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8") as fh:
        if new:
            fh.write("date,buys,sells,basket,account,cash,deposited,pnl\n")
        fh.write(f'{when},"{" ".join(buys)}","{" ".join(sells)}","{" ".join(basket)}",'
                 f'{total:.2f},{cash:.2f},{deposited:.2f},{pnl:.2f}\n')


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="decide and print, post nothing")
    p.add_argument("--force", action="store_true", help="rebalance regardless of date")
    p.add_argument("--status", action="store_true", help="show the account and exit")
    p.add_argument("--report", action="store_true",
                   help="post the account to Discord without rebalancing")
    p.add_argument("--test", action="store_true",
                   help="post a real message to Discord, save nothing")
    p.add_argument("--deposit", type=float, metavar="AMOUNT",
                   help="record money paid into the account")
    p.add_argument("--withdraw", type=float, metavar="AMOUNT",
                   help="record money taken out")
    p.add_argument("--fill", action="append", metavar="TICKER=SHARES@PRICE",
                   help="correct an assumed fill; repeatable")
    p.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK", ""))
    args = p.parse_args()

    state = load_state()

    # --- cash in and out -----------------------------------------------------
    for amount, sign, verb in ((args.deposit, 1, "deposited"),
                               (args.withdraw, -1, "withdrew")):
        if amount is None:
            continue
        if amount <= 0:
            raise SystemExit(f"--{verb[:-2] if sign > 0 else 'withdraw'} wants a "
                             f"positive amount")
        if sign < 0 and amount > state["cash"] + 1e-9:
            raise SystemExit(f"only {money(state['cash'])} in cash — sell something "
                             f"first, or withdraw less")
        state["cash"] += sign * amount
        state["deposited"] += sign * amount
        save_state(state)
        print(f"{verb} {money(amount)} — cash now {money(state['cash'])}, "
              f"{money(state['deposited'])} paid in overall")

    # --- corrections to what the bot assumed --------------------------------
    if args.fill:
        for spec in args.fill:
            tk, sh, pr = parse_fill(spec)
            apply_orders(state, [(tk, sh, -sh * pr)], {tk: pr})
            print(f"recorded {'buy' if sh > 0 else 'sell'} of {abs(sh)} {tk} "
                  f"@ {money(pr)} — cash now {money(state['cash'])}")
        save_state(state)

    if args.deposit is not None or args.withdraw is not None or args.fill:
        if not (args.status or args.report):
            return 0

    # --- the account, marked to the latest close ----------------------------
    if args.status or args.report:
        if not state["positions"]:
            m = mark(state, {})
            print(f"basket        : {', '.join(state['basket']) or '(empty)'}")
            print(f"last rebalance: {state.get('last_rebalance') or 'never'}")
            print(f"cash          : {money(m['cash'])}")
            print(f"paid in       : {money(m['deposited'])}")
            if not args.report:
                return 0
        else:
            px = fetch()
            m = mark(state, px.iloc[-1].to_dict())
            print(f"ACCOUNT   {money(m['total'])}   "
                  f"{m['pnl']:+,.2f} = {m['pnl_pct']:+.1f}% "
                  f"on {money(m['deposited'])} paid in")
            print(f"  invested  {money(m['invested'])}   "
                  f"cash {money(m['cash'])}   [{MODE}]")
            print(f"  open      {m['unrealised']:+,.2f}   "
                  f"banked {m['realised']:+,.2f}")
            print(f"  since     {state.get('last_rebalance') or 'never'}\n")
            print("\n".join(render_book(m)))
        if args.report:
            if not args.webhook:
                raise SystemExit("no webhook set ($DISCORD_WEBHOOK)")
            bar = px.index[-1] if state["positions"] else datetime.now(timezone.utc)
            post(args.webhook, render_snapshot(bar, m, state))
            print("\nposted to Discord")
        return 0

    px = fetch()
    prices = px.iloc[-1].to_dict()
    scores = rank(px)
    basket = list(scores.index[:HOLD])
    held = state.get("basket", [])

    if not (args.force or args.test or due(px, state)):
        m = mark(state, prices)
        print(f"{px.index[-1].date()}: already rebalanced this month "
              f"({state.get('last_rebalance')}). Nothing to do.")
        if m["deposited"]:
            print(f"  account {money(m['total'])}  {m['pnl_pct']:+.1f}%")
        return 0

    buys = [t for t in basket if t not in held]
    sells = [t for t in held if t not in basket]
    first = not held
    bar = px.index[-1]

    m = mark(state, prices)
    orders = plan(state, prices, basket, m["total"]) if m["total"] > 0 else []
    cannot = unbuyable(basket, prices, m["total"]) if m["total"] > 0 else []

    print(render_plain(bar, buys, sells, basket, scores, m, orders, prices))
    if cannot:
        print(f"\n  ! {', '.join(cannot)} cost more than one "
              f"{money(m['total'] / HOLD)} slice and cannot be bought whole.")
        print("    Set MOMENTUM_FRACTIONAL=1 if your broker sells part shares, "
              "or add funds.")
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
                                        prices=prices, cannot=cannot))
        print("\n[--test] posted to Discord. state.json and rebalances.csv "
              "untouched — this was not a rebalance, and the book did not move.")
        return 0

    if not buys and not sells and not first and not orders:
        print("\nbasket unchanged and nothing to trim — not posting")
    elif args.webhook:
        post(args.webhook, render_embed(bar, buys, sells, basket, scores, first,
                                        m=m, orders=orders, prices=prices,
                                        cannot=cannot))
        print("\nposted to Discord")
    else:
        print("\nno webhook set ($DISCORD_WEBHOOK) — printed only")

    # Assume the orders filled at today's close. --fill corrects any that did not.
    apply_orders(state, orders, prices)
    after = mark(state, prices)
    state["equity"].append([str(bar.date()), round(after["total"], 2)])
    state.update({"basket": basket,
                  "last_rebalance": str(bar.date()),
                  "last_rebalance_month": f"{bar.year}-{bar.month:02d}"})
    save_state(state)
    log_row(bar.date(), buys, sells, basket, after["total"], after["cash"],
            after["deposited"], after["pnl"])
    if orders:
        print(f"recorded {len(orders)} fills at the {bar.date()} close · "
              f"account {money(after['total'])} · cash {money(after['cash'])}")
        print("if your fills differed:  --fill TICKER=SHARES@PRICE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
