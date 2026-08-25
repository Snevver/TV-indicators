"""Capital-constrained evaluation. The only objective that means anything.

Mean R per signal is what every earlier search here optimised, and it is a
fiction for anyone with finite capital. Measured on the previous finalist:

    unlimited capacity   29.3% win   +0.138R
    3 concurrent slots    7.4% win   -0.787R

Winners held a slot 4.1x longer than losers, so a small book fills with losers
while the winners sit in positions it could not open. The edge was real and
entirely unreachable.

So: simulate an actual account. Real calendar dates, a cap on open positions, a
fixed fraction of equity risked per trade, compounding. And run the random-entry
baseline through the SAME constraint, because a capped random book has its own
bias and only the difference between them is evidence.
"""
from __future__ import annotations

import numpy as np


def run_account(trades, cap: int, risk_pct: float = 1.0, start: float = 1000.0):
    """`trades` = [(entry_date, exit_date, r)] with real calendar dates."""
    if not trades:
        return None
    tr = sorted(trades)
    ev = []
    for k, (a, b, r) in enumerate(tr):
        ev.append((a, 0, k))
        ev.append((b, 1, k))
    ev.sort(key=lambda x: (x[0], x[1]))

    eq = peak = start
    dd = 0.0
    live = set()
    taken = wins = closed = 0
    rs = []
    for _when, kind, k in ev:
        if kind == 0:
            if cap and len(live) >= cap:
                continue
            live.add(k)
            taken += 1
        elif k in live:
            live.discard(k)
            r = tr[k][2]
            eq *= (1.0 + risk_pct / 100.0 * r)
            rs.append(r)
            wins += int(r > 0)
            closed += 1
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak)
            if eq <= 1e-9:
                return {"ruined": True, "eq": 0.0, "cagr": -1.0, "dd": 100.0,
                        "taken": taken, "win": 0.0, "n": closed, "mean_r": -1.0,
                        "years": 1.0}

    span = tr[-1][1] - tr[0][0]
    years = float(span / np.timedelta64(365, "D"))
    years = years if years > 0 else 1.0
    return {"ruined": False, "eq": eq, "cagr": (eq / start) ** (1 / years) - 1,
            "dd": dd * 100, "taken": taken, "n": closed,
            "win": 100.0 * wins / closed if closed else 0.0,
            "mean_r": float(np.mean(rs)) if rs else 0.0, "years": years}
