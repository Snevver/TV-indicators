"""The bar every candidate must clear.

Beating zero is not evidence. A long-only rule on an instrument that drifts
upward makes money from the drift alone, and a search over hundreds of configs
finds apparent edges in pure noise. So each strategy is scored against:

  RANDOM ENTRIES   the same exit, entered on random bars of the same series.
                   This is the baseline the strategy must beat.
  PLACEBO SIGNALS  the strategy's own entries shifted in time. Same count, same
                   clustering, no relationship to the price action. The spread of
                   these is what "no edge" looks like for this exact rule.

EDGE = strategy mean R − random-entry mean R, and its z-score against the
placebo distribution is what gets compared across candidates.
"""
from __future__ import annotations

import numpy as np

import sim
from lab import Series


def random_mask(n: int, count: int, rng, warmup: int = 260) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    if count <= 0 or n - warmup - 3 <= 0:
        return m
    pick = rng.choice(np.arange(warmup, n - 2),
                      size=min(count, n - warmup - 3), replace=False)
    m[pick] = True
    return m


def shift_mask(mask: np.ndarray, offset: int, warmup: int = 260) -> np.ndarray:
    """Roll the signals forward in time, wrapping. Preserves count and spacing."""
    n = len(mask)
    idx = (np.flatnonzero(mask) + offset) % n
    idx = idx[idx >= warmup]
    out = np.zeros(n, dtype=bool)
    out[idx] = True
    return out


def scored(series: dict[str, Series], masks: dict[str, np.ndarray],
           ex: sim.Exit, cost_bps: float, era: str,
           rng, n_placebo: int = 60, dirn: int = 1) -> dict | None:
    """Pooled edge over random entries, with a placebo null. `era` in tr/va/te."""
    import lab
    real_r, rand_r, counts = [], [], 0
    plac = np.zeros(n_placebo)
    plac_n = np.zeros(n_placebo)

    for tk, s in series.items():
        m = masks.get(tk)
        if m is None:
            continue
        tr_m, va_m, te_m = lab.era_masks(s)
        keep = {"tr": tr_m, "va": va_m, "te": te_m}[era]
        mm = m & keep
        k = int(mm.sum())
        if k == 0:
            continue
        counts += k

        for t in sim.simulate(s, mm, ex, cost_bps, dirn):
            real_r.append(t.r)

        rm = random_mask(len(s), k, rng) & keep
        for t in sim.simulate(s, rm, ex, cost_bps, dirn):
            rand_r.append(t.r)

        for p in range(n_placebo):
            off = int(rng.integers(300, max(301, len(s) - 300)))
            pm = shift_mask(m, off) & keep
            tt = sim.simulate(s, pm, ex, cost_bps, dirn)
            if tt:
                plac[p] += sum(x.r for x in tt)
                plac_n[p] += len(tt)

    if len(real_r) < 40 or len(rand_r) < 20:
        return None
    real = float(np.mean(real_r))
    rand = float(np.mean(rand_r))
    ok = plac_n >= 20
    if ok.sum() < 10:
        return None
    null = plac[ok] / plac_n[ok] - rand
    edge = real - rand
    sd = null.std(ddof=1)
    return {"n": len(real_r), "real": real, "rand": rand, "edge": edge,
            "z": (edge - null.mean()) / sd if sd > 0 else 0.0,
            "p": (1 + np.sum(null >= edge)) / (1 + len(null)),
            "null": null, "null_mean": float(null.mean()), "null_sd": float(sd)}
