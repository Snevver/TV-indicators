"""Trade simulation. Everything that decides whether a number is real lives here.

Rules, all chosen to be pessimistic where reality is ambiguous:

  ENTRY   the next bar's OPEN after the signal bar. A signal derived from a close
          cannot be filled at that close.
  STOP    checked before the target on every bar. When one bar's range spans both,
          OHLC cannot say which came first, so the loss is taken.
  GAPS    if a bar opens beyond a level, the fill is the open, not the level.
  COSTS   charged on both sides, in basis points of price.
  RISK    every result is in R, where 1R is the initial stop distance. This makes
          trades comparable across tickers and volatility regimes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lab import Series


@dataclass(frozen=True)
class Exit:
    stop_atr: float = 2.0        # initial stop, in ATRs
    target_r: float = 2.0        # fixed target in R; 0 = none
    trail_atr: float = 0.0       # trail this many ATRs behind the extreme; 0 = off
    trail_after_r: float = 0.0   # trailing engages after this much profit
    breakeven_r: float = 0.0     # move stop to entry after this much profit
    time_bars: int = 0           # force exit after N bars; 0 = never
    atr_key: str = "atr14"


@dataclass
class Trade:
    ti: str
    dirn: int
    i_in: int
    i_out: int
    r: float
    reason: str
    bars: int


def simulate(s: Series, entries: np.ndarray, ex: Exit,
             cost_bps: float = 5.0, dirn: int = 1,
             one_at_a_time: bool = True) -> list[Trade]:
    """`entries` is a boolean mask on bar indices. Returns trades in R."""
    n = len(s)
    atr = s.ind[ex.atr_key]
    o, h, l, c = s.o, s.h, s.l, s.c
    cost = cost_bps / 10_000.0
    idx = np.flatnonzero(entries)
    out: list[Trade] = []
    busy = -1

    for i in idx:
        if i + 1 >= n:
            break
        if one_at_a_time and i <= busy:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        entry = o[i + 1]
        risk = a * ex.stop_atr
        if risk <= 0 or not np.isfinite(entry):
            continue

        stop = entry - dirn * risk
        tgt = entry + dirn * risk * ex.target_r if ex.target_r > 0 else None
        best = entry
        i_out = px = None
        why = ""

        for j in range(i + 1, n):
            hj, lj, oj = h[j], l[j], o[j]

            if j > i + 1:                      # entry bar: only the fill happened
                # 1. stop, gap-aware, pessimistic
                if dirn == 1 and lj <= stop:
                    i_out, px, why = j, min(stop, oj), "sl"
                elif dirn == -1 and hj >= stop:
                    i_out, px, why = j, max(stop, oj), "sl"
                if i_out is not None:
                    break
                # 2. target
                if tgt is not None:
                    if dirn == 1 and hj >= tgt:
                        i_out, px, why = j, max(tgt, oj), "tp"
                    elif dirn == -1 and lj <= tgt:
                        i_out, px, why = j, min(tgt, oj), "tp"
                    if i_out is not None:
                        break
                # 3. time stop
                if ex.time_bars and (j - i - 1) >= ex.time_bars:
                    i_out, px, why = j, c[j], "time"
                    break

            # 4. stop management, from completed extremes only
            best = max(best, hj) if dirn == 1 else min(best, lj)
            prof = ((best - entry) if dirn == 1 else (entry - best)) / risk
            if ex.breakeven_r > 0 and prof >= ex.breakeven_r:
                stop = max(stop, entry) if dirn == 1 else min(stop, entry)
            if ex.trail_atr > 0 and prof >= ex.trail_after_r:
                ts = best - dirn * ex.trail_atr * a
                stop = max(stop, ts) if dirn == 1 else min(stop, ts)

        if i_out is None:
            i_out, px, why = n - 1, c[-1], "eod"

        gross = (px - entry) * dirn
        r = (gross - (entry + px) * cost) / risk
        out.append(Trade(s.ticker, dirn, i + 1, i_out, r, why, i_out - i - 1))
        if one_at_a_time:
            busy = i_out
    return out


def stats(trades: list[Trade], years: float) -> dict:
    if not trades:
        return {"n": 0, "win": 0.0, "exp": 0.0, "ry": 0.0, "pf": 0.0,
                "t": 0.0, "bars": 0.0}
    r = np.array([t.r for t in trades])
    wins = r[r > 0]
    loss = r[r <= 0]
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return {"n": len(r), "win": 100.0 * len(wins) / len(r), "exp": r.mean(),
            "ry": r.sum() / years if years > 0 else 0.0,
            "pf": wins.sum() / abs(loss.sum()) if len(loss) and loss.sum() < 0 else float("inf"),
            "t": r.mean() / sd * np.sqrt(len(r)) if sd > 0 else 0.0,
            "bars": float(np.mean([t.bars for t in trades]))}


def equity(trades: list[Trade], risk_pct: float = 1.0, cap: int = 0,
           start: float = 1000.0) -> dict:
    """Replay trades from many tickers against ONE account.

    Trades are opened in date order. `cap` limits simultaneous positions; a
    signal arriving while the book is full is dropped, not queued. Every trade
    risks `risk_pct` of CURRENT equity, so the curve compounds.
    """
    if not trades:
        return {"end": start, "cagr": 0.0, "dd": 0.0, "taken": 0, "win": 0.0}
    ev = []
    for k, t in enumerate(trades):
        ev.append((t.i_in, 0, k))
        ev.append((t.i_out, 1, k))
    ev.sort()
    eq = peak = start
    dd = 0.0
    live = set()
    taken = wins = closed = 0
    for _, kind, k in ev:
        if kind == 0:
            if cap and len(live) >= cap:
                continue
            live.add(k)
            taken += 1
        elif k in live:
            live.discard(k)
            eq *= (1.0 + risk_pct / 100.0 * trades[k].r)
            wins += int(trades[k].r > 0)
            closed += 1
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak)
    return {"end": eq, "dd": dd * 100, "taken": taken,
            "win": 100.0 * wins / closed if closed else 0.0}
