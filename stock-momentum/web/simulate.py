"""Run the strategy over any window, against the index.

The point of this page is to answer "what would this have done between X and Y",
so the logic has to be the same logic that produced every published figure. The
constants and the ranking below are copied verbatim from the script the reports
were generated from — not re-derived, because a re-derivation that drifts by one
day would quietly make this page lie.

Reads the daily export that ships in the repo. That file is ~45MB gzipped and
takes a few seconds to parse, so the pivoted frame is cached in memory for the
life of the process and every later simulation is instant.
"""
from __future__ import annotations

import os
import threading

# Frozen at validation time. Changing any of these makes this page describe
# something other than what the bot runs.
UNIVERSE = ["AAPL", "GOOGL", "AMZN", "GOOG", "MSFT", "BAC", "XOM", "JPM", "INTC",
            "NFLX", "C", "CSCO", "WFC", "GE", "PFE", "JNJ", "CVX", "T", "QCOM",
            "GS", "WMT", "PG", "IBM", "ORCL", "VZ", "DIS", "HD", "MRK", "BA",
            "BKNG", "MU", "CMCSA", "KO", "MCD", "CAT", "SLB", "COP", "AMGN",
            "UNH", "NVDA"]
LOOKBACK, SKIP, HOLD = 126, 21, 8
COST_BPS = 10.0                       # on the money that moves, each rebalance

DATA = os.environ.get("MOMENTUM_DATA") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "_data-export", "data")

_lock = threading.Lock()
_cache = {}


class NoData(RuntimeError):
    """The price export is missing or unreadable."""


def _load():
    """Pivot both files once, then hand out the same frames forever."""
    with _lock:
        if _cache:
            return _cache
        try:
            import pandas as pd
        except ImportError as exc:
            raise NoData(f"pandas is not installed in this venv ({exc})")

        sp = os.path.join(DATA, "sp500_daily.csv.gz")
        et = os.path.join(DATA, "etfs_daily.csv.gz")
        if not os.path.exists(sp):
            raise NoData(f"no price export at {sp}, it ships with the repo, so "
                         f"a git pull should restore it")
        s = pd.read_csv(sp, usecols=["time", "ticker", "close"])
        s["time"] = pd.to_datetime(s["time"])
        px = (s[s.ticker.isin(UNIVERSE)]
              .pivot(index="time", columns="ticker", values="close").sort_index())

        spy = None
        if os.path.exists(et):
            e = pd.read_csv(et, usecols=["time", "ticker", "close"])
            e["time"] = pd.to_datetime(e["time"])
            spy = (e[e.ticker == "SPY"].set_index("time")["close"]
                   .sort_index().reindex(px.index).ffill())
        _cache["px"], _cache["spy"] = px, spy
        return _cache


def bounds() -> dict:
    """The window the data can actually answer for.

    The first tradable day is LOOKBACK + SKIP bars in — before that there is not
    enough history to rank anything.
    """
    d = _load()
    idx = d["px"].index
    first = idx[LOOKBACK + SKIP + 1]
    return {"min": str(first.date()), "max": str(idx[-1].date()),
            "universe": len(UNIVERSE), "hold": HOLD,
            "has_benchmark": d["spy"] is not None}


def _momentum(px, a):
    """Return over LOOKBACK days ending SKIP days ago. Same as the backtest."""
    past, recent = px.iloc[a - LOOKBACK - SKIP], px.iloc[a - SKIP]
    ok = past.notna() & recent.notna() & px.iloc[a].notna() & (past > 0)
    return ((recent / past - 1.0)[ok]).sort_values(ascending=False)


def _stats(dates, values):
    """Return, CAGR, worst drawdown, volatility — measured, not annualised from
    a guess about trading days."""
    if len(values) < 2:
        return {"final": values[-1] if values else 0.0, "ret_pct": 0.0,
                "cagr_pct": None, "maxdd_pct": 0.0, "vol_pct": 0.0}
    import numpy as np
    v = np.asarray(values, dtype=float)
    r = np.diff(v) / v[:-1]
    peak = np.maximum.accumulate(v)
    dd = (peak - v) / peak
    days = (np.datetime64(dates[-1]) - np.datetime64(dates[0])) / np.timedelta64(1, "D")
    yrs = max(days / 365.25, 1e-9)
    total = v[-1] / v[0]
    return {"final": round(float(v[-1]), 2),
            "ret_pct": round((total - 1) * 100, 2),
            "cagr_pct": round((total ** (1 / yrs) - 1) * 100, 2) if yrs > 0.4 else None,
            "maxdd_pct": round(float(dd.max()) * 100, 2),
            "vol_pct": round(float(r.std(ddof=1) * (252 ** 0.5)) * 100, 2)
            if len(r) > 2 else 0.0}


def _irr(flows, years) -> float:
    """Annual money-weighted return. `flows` is [(years_from_start, amount)] with
    money paid in negative and the closing value positive.

    With contributions arriving every month, final/first - 1 is not a return at
    all -- it counts your own deposits as profit. This is the rate that actually
    solves the cash flows. Bisection rather than scipy: one dependency less, and
    the bracket is wide enough for anything a market can do.
    """
    def npv(r):
        return sum(a / ((1.0 + r) ** t) for t, a in flows)
    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0 * 100.0


def run(start: str, end: str, budget: float, monthly: float = 0.0,
        cost_bps: float = COST_BPS) -> dict:
    """Simulate the strategy between two dates against holding the index.

    Drift with fractional shares, which is the only configuration the bot runs,
    so this page cannot show a result the bot would not produce.

    `monthly` is paid in on every rebalance after the first. Sell proceeds keep
    funding the arriving names exactly as they always did; only the NEW money is
    spread across the whole basket. Measured over eight windows that beat putting
    it all into the arrivals in seven of them, and won the full history with a
    slightly smaller worst fall -- though only by about 1.3%, so it is a
    preference, not a discovery. It is also what a Trading 212 pie does with a
    standing order, which matters for the live track.
    """
    import numpy as np
    import pandas as pd

    d = _load()
    px, spy = d["px"], d["spy"]
    idx = px.index

    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end)
    if hi <= lo:
        raise ValueError("the end date must be after the start date")
    if monthly < 0:
        raise ValueError("a monthly contribution cannot be negative")

    earliest = idx[LOOKBACK + SKIP + 1]
    if lo < earliest:
        raise ValueError(f"the first date with enough history to rank is "
                         f"{earliest.date()}")
    if lo > idx[-1]:
        raise ValueError(f"the data ends {idx[-1].date()}")

    anchors = (pd.Series(np.arange(len(idx)), index=idx)
               .groupby([idx.year, idx.month]).first().to_numpy())
    anchors = [int(a) for a in anchors
               if a >= LOOKBACK + SKIP + 1 and lo <= idx[a] <= hi]
    if not anchors:
        raise ValueError("that window contains no rebalance date, it needs to "
                         "span at least one first trading day of a month")

    end_i = int(np.searchsorted(idx, hi, side="right") - 1)
    slice_start = anchors[0]
    fee = cost_bps / 10_000.0

    # The arithmetic below is the published one, unchanged: with monthly=0 this
    # loop is the original line for line. Contributions are layered on top so a
    # figure already quoted from this page cannot move underneath it.
    shares, curve, log = {}, [], []
    contributed = 0.0
    flows = []                      # (date, amount paid in) for the IRR
    for k, a in enumerate(anchors):
        top = list(_momentum(px, a).index[:HOLD])
        prices = px.iloc[a]
        value = budget if not shares else sum(n * prices[t] for t, n in shares.items())

        if shares:
            if monthly:
                contributed += monthly
                flows.append((idx[a], monthly))
                value += monthly

            leaving = [t for t in shares if t not in top]
            arriving = [t for t in top if t not in shares]
            cash = sum(shares[t] * prices[t] for t in leaving)
            traded = cash * (2 if arriving else 1)
            value -= traded * fee
            cash -= cash * fee
            for t in leaving:
                del shares[t]
            if arriving:
                each = cash / len(arriving)
                for t in arriving:
                    shares[t] = each / prices[t]

            # New money only, spread over the whole basket. Sell proceeds keep
            # funding the arrivals above, exactly as they always did.
            if monthly:
                value -= monthly * fee
                each = monthly / len(top)
                for t in top:
                    shares[t] = shares.get(t, 0.0) + each / prices[t]
        else:
            contributed += budget
            flows.append((idx[a], budget))
            value *= (1.0 - fee)                  # the opening purchase
            per = value / HOLD
            shares = {t: per / prices[t] for t in top}

        held = sum(n * prices[t] for t, n in shares.items())
        log.append({"date": str(idx[a].date()), "basket": top,
                    "value": round(float(value), 2),
                    "invested": round(float(held), 2),
                    "cash": round(float(value - held), 2),
                    "paid_in": round(float(contributed), 2)})

        nxt = anchors[k + 1] if k + 1 < len(anchors) else end_i + 1
        cash_left = value - held
        for i in range(a, min(nxt, end_i + 1)):
            row = px.iloc[i]
            curve.append((idx[i], sum(n * row[t] for t, n in shares.items()) + cash_left))

    dates = [str(t.date()) for t, _ in curve]
    strat = [round(float(v), 2) for _, v in curve]

    # A full-history run is >5,000 points, which no chart can show and which
    # bloats the response. Stats are computed on the full series above; only the
    # drawn line is thinned, and the last point is always kept.
    step = max(1, len(dates) // 1200)
    def thin(v):
        out = v[::step]
        if out[-1] != v[-1]:
            out = out + [v[-1]]
        return out

    paid_on = {str(t.date()): amt for t, amt in flows}

    def money_stats(values):
        """Money figures come from the account itself; risk figures come from a
        series with the deposits taken out.

        A contribution is not a gain, but on the raw curve it looks exactly like
        one: a +150 step reads as a positive day, inflating volatility and
        papering over falls. So worst fall and volatility are measured on a
        time-weighted series -- each day's return computed after removing that
        day's payment -- which is how a fund reports performance. With
        monthly=0 there is nothing to remove and this reduces to the old numbers
        exactly.
        """
        s = _stats(dates, values)
        if not monthly:
            return s

        tw = [1.0]
        for i in range(1, len(values)):
            prev = values[i - 1]
            added = paid_on.get(dates[i], 0.0)
            tw.append(tw[-1] * (((values[i] - added) / prev) if prev > 0 else 1.0))
        risk = _stats(dates, tw)
        s["maxdd_pct"] = risk["maxdd_pct"]
        s["vol_pct"] = risk["vol_pct"]

        last = pd.Timestamp(dates[-1])
        first = flows[0][0]
        # Time runs forward from the first payment. Measuring it backwards from
        # the end discounts the oldest contribution hardest, which turns a
        # tripled account into a negative rate.
        cf = [((t - first).days / 365.25, -amt) for t, amt in flows]
        span = max((last - first).days / 365.25, 1e-9)
        cf.append((span, values[-1]))
        s["paid_in"] = round(contributed, 2)
        s["gain"] = round(values[-1] - contributed, 2)
        s["ret_pct"] = None                       # meaningless with cash flows
        s["cagr_pct"] = None
        s["irr_pct"] = (round(_irr(cf, span), 2) if span > 0.4 else None)
        return s

    out = {"dates": thin(dates), "strategy": thin(strat),
           "start": dates[0], "end": dates[-1], "budget": budget,
           "monthly": monthly, "paid_in": round(contributed, 2),
           "rebalances": log,
           "stats": {"strategy": money_stats(strat)}}

    if spy is not None:
        base = float(spy.iloc[slice_start])
        if base > 0:
            if monthly:
                # The index has to receive the same money on the same days, or
                # the comparison is rigged: a line that gets fresh cash every
                # month will beat one that does not, whatever it holds.
                by_date = {t: amt for t, amt in flows}
                units, bench = 0.0, []
                for i in range(slice_start, end_i + 1):
                    when = idx[i]
                    if when in by_date:
                        units += by_date[when] / float(spy.iloc[i])
                    bench.append(round(units * float(spy.iloc[i]), 2))
            else:
                bench = [round(float(spy.iloc[i]) / base * budget, 2)
                         for i in range(slice_start, end_i + 1)]
            out["stats"]["spy"] = money_stats(bench)
            out["spy"] = thin(bench)
    return out
