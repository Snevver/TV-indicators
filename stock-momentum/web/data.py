"""Everything the dashboard reads. Nothing here imports momentum_bot.

That is deliberate. momentum_bot reads its whole configuration at import time and
reads every MOMENTUM_* variable at import, so a long-lived web process that
imported it would serve stale settings forever and could refuse to start over a
typo in a config file. The web app reads the bot's files instead, and shells out
to a fresh process when it needs live prices.

Every reader here returns something usable when the file is missing, empty, half
written or corrupt. A dashboard that 500s because the bot has not run yet is
worse than one that says "no data".
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import time

BOT = os.environ.get("MOMENTUM_BOT_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot")
STATE = os.path.join(BOT, "state.json")
LATEST = os.path.join(BOT, "latest.json")
HISTORY = os.path.join(BOT, "history.csv")
REBALANCES = os.path.join(BOT, "rebalances.csv")
PYTHON = os.environ.get("MOMENTUM_PYTHON") or os.path.join(BOT, ".venv", "bin", "python")

TRACKS = ("paper", "live")
TRACK_LABEL = {"paper": "Paper", "live": "Trading 212"}


def _json(path, default):
    """Read JSON, tolerating a file that is missing or being rewritten."""
    for attempt in range(3):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return default
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)        # a writer mid-rename; give it a moment
    return default


def state() -> dict:
    s = _json(STATE, {})
    if "tracks" not in s:                       # schema 1, or nothing yet
        s = {"tracks": {"paper": s, "live": {}}} if s else {"tracks": {}}
    for t in TRACKS:
        s["tracks"].setdefault(t, {})
    return s


def latest() -> dict:
    return _json(LATEST, {})


def _rows(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except (FileNotFoundError, OSError, csv.Error):
        return []


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def history(track: str) -> list:
    """[{date, total, invested, cash, deposited, pnl, ...}] oldest first."""
    out = []
    for r in _rows(HISTORY):
        if r.get("track") != track:
            continue
        out.append({"date": r.get("date", ""),
                    **{k: _f(r.get(k)) for k in
                       ("total", "invested", "cash", "deposited", "pnl",
                        "realised", "unrealised")},
                    "positions": int(_f(r.get("positions")))})
    out.sort(key=lambda r: r["date"])
    return out


def _maybe(v):
    """A number, or None when the column is absent or blank.

    The difference matters. Rows written before the account columns existed have
    no figure at all, and rendering those as 0.00 would claim the account was
    empty rather than admitting it was never recorded.
    """
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rebalances() -> list:
    """Newest first — the dashboard shows the most recent month at the top."""
    out = []
    for r in _rows(REBALANCES):
        out.append({"date": r.get("date", ""),
                    "buys": [t for t in (r.get("buys") or "").split() if t],
                    "sells": [t for t in (r.get("sells") or "").split() if t],
                    "basket": [t for t in (r.get("basket") or "").split() if t],
                    **{k: _maybe(r.get(k)) for k in
                       ("account", "cash", "deposited", "pnl")}})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def curve(track: str) -> dict:
    """The equity series plus the derived numbers the charts need.

    Falls back to state.json's per-rebalance `equity` list when history.csv has
    nothing yet, so a freshly installed dashboard still draws something.
    """
    rows = history(track)
    if not rows:
        eq = (state()["tracks"].get(track) or {}).get("equity") or []
        rows = [{"date": d, "total": _f(v), "deposited": 0.0, "invested": _f(v),
                 "cash": 0.0, "pnl": 0.0, "realised": 0.0, "unrealised": 0.0,
                 "positions": 0} for d, v in eq]
    if not rows:
        return {"dates": [], "total": [], "deposited": [], "drawdown": [],
                "monthly": [], "peak": 0.0, "maxdd": 0.0}

    dates = [r["date"] for r in rows]
    total = [r["total"] for r in rows]
    dep = [r["deposited"] for r in rows]

    peak, dd = total[0] or 0.0, []
    for v in total:
        peak = max(peak, v)
        dd.append(0.0 if peak <= 0 else (v - peak) / peak * 100.0)

    monthly, seen = [], {}
    for r in rows:                       # last value in each calendar month
        seen[r["date"][:7]] = r["total"]
    months = sorted(seen)
    for i, mth in enumerate(months):
        if i == 0:
            base = rows[0]["total"]
        else:
            base = seen[months[i - 1]]
        monthly.append({"month": mth,
                        "pct": 0.0 if not base else (seen[mth] / base - 1) * 100.0})

    return {"dates": dates, "total": total, "deposited": dep, "drawdown": dd,
            "monthly": monthly, "peak": peak, "maxdd": min(dd) if dd else 0.0}


def summary(track: str) -> dict:
    """The 'Now' panel. Prefers latest.json; falls back to raw state."""
    lat = latest()
    t = (lat.get("tracks") or {}).get(track)
    if t:
        return {**t, "stale": False, "bar": lat.get("bar", ""),
                "generated": lat.get("generated", "")}
    bk = state()["tracks"].get(track) or {}
    invested = 0.0                      # no prices without a bot run
    return {"total": _f(bk.get("cash")) + invested, "invested": invested,
            "cash": _f(bk.get("cash")), "deposited": _f(bk.get("deposited")),
            "pnl": 0.0, "pnl_pct": 0.0, "realised": _f(bk.get("realised")),
            "unrealised": 0.0, "positions": {}, "basket": bk.get("basket") or [],
            "last_rebalance": bk.get("last_rebalance"),
            "symbol": "$", "currency": "USD",
            "equity": bk.get("equity") or [], "stale": True, "bar": "",
            "generated": ""}


def health() -> dict:
    """What the Health panel reports. Never raises."""
    lat = latest()

    def age(path):
        try:
            return time.time() - os.path.getmtime(path)
        except OSError:
            return None

    return {"latest_age": age(LATEST), "state_age": age(STATE),
            "has_history": bool(history("paper") or history("live")),
            "bar": lat.get("bar", ""), "mode": lat.get("mode", ""),
            "track": lat.get("track", ""), "currency": lat.get("currency", ""),
            "next_rebalance": lat.get("next_rebalance", ""),
            "due": lat.get("due"), "ranking": lat.get("ranking") or [],
            "hold": lat.get("hold") or 8,
            # The opening rebalance credits the monthly contribution before it
            # sizes anything, so the launch preview needs it to promise the right
            # slice rather than one based on today's balance alone.
            "monthly": lat.get("monthly") or 0.0,
            # Whether an approved batch is placed for you or written out for you
            # to place. The page has to be able to say which, because being wrong
            # about it in either direction is the worst kind of surprise.
            "autotrade": bool(lat.get("autotrade")),
            "t212": lat.get("t212") or {},
            "python_ok": os.path.exists(PYTHON)}


# --------------------------------------------------------------- the bot ---
#
# Actions run as a subprocess, always with a fixed argv list. Never a shell
# string, and never anything assembled from request data.

ACTIONS = {
    "refresh": ["--json"],
    "dry": ["--dry"],
    "test": ["--test"],
    "probe": ["--t212-probe"],
    "check": ["--t212-check"],
    "sync": ["--t212-sync"],
    # The smoke test. "offer" only posts to Discord; "poll" is the one that can
    # place a real order, and only ever after your reaction has been read back.
    "smoke_offer": ["--smoke-offer"],
    "smoke_poll": ["--smoke-poll"],
    "smoke_status": ["--smoke-status"],
    # The monthly batch. Read and cancel only, deliberately: --pending-poll is
    # what the timer runs, and a button that sends a whole month of orders in one
    # click is more risk than it is convenience. Cancel is safe by definition --
    # the worst it can do is nothing.
    "pending_status": ["--pending-status"],
    "pending_cancel": ["--pending-cancel"],
    # Sells everything and freezes. Fired by the Settings page right after it
    # writes MOMENTUM_KILL=on; the poller re-fires it if this run failed.
    "kill": ["--kill"],
}


def run_bot(action: str, timeout: int = 180) -> dict:
    """Run one whitelisted bot command. Returns output, never raises."""
    args = ACTIONS.get(action)
    if args is None:
        return {"ok": False, "out": "", "err": f"unknown action {action!r}", "code": -1}
    if not os.path.exists(PYTHON):
        return {"ok": False, "out": "",
                "err": f"no interpreter at {PYTHON} — is the venv built?", "code": -1}
    try:
        p = subprocess.run([PYTHON, "momentum_bot.py", *args], cwd=BOT,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "",
                "err": f"timed out after {timeout}s — the price download can hang",
                "code": -1}
    except OSError as exc:
        return {"ok": False, "out": "", "err": str(exc), "code": -1}
    return {"ok": p.returncode == 0, "out": p.stdout[-8000:],
            "err": p.stderr[-4000:], "code": p.returncode}
