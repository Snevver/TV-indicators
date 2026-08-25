"""A more general signal engine, built to be searched over.

The V2 engine hard-ANDs four conditions that turn out to be mutually exclusive:
on 26 years of SPY its buy signal fires exactly zero times at default settings.
This version separates the ideas so each can be switched on independently:

  ENTRY TRIGGER   what makes a bar interesting (RSI extreme, z-score, run of down
                  closes, Bollinger break) — any combination, ANDed
  REGIME FILTER   when the trigger is allowed to fire (above/below a long MA)
  DIRECTION       long-only, short-only, or both. This matters more than it looks:
                  an instrument with upward drift punishes symmetric shorting
  EXIT            ATR target and stop, optionally a time stop or an RSI exit

Everything is computed from closed bars only. Nothing reads the future.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from engine import Bar, Signal, atr, ema, rsi, sma

# ── Indicator cache ──────────────────────────────────────────────────────────
# A parameter search re-evaluates the same RSI/EMA/ATR series thousands of times
# over the same bars. Computing them once per (series, kind, length) turns a
# 40-minute sweep into a 2-minute one. Keyed by id() of the bar list, which is
# safe here because the lists are built once and never mutated.
_CACHE: dict = {}
_CACHE_OWNER: list = []


def _cached(bars, kind: str, length: int, fn):
    key = (id(bars), kind, length)
    hit = _CACHE.get(key)
    if hit is None:
        hit = fn()
        if len(_CACHE) > 400:
            _CACHE.clear()
            _CACHE_OWNER.clear()
        _CACHE[key] = hit
        _CACHE_OWNER.append(bars)      # keep a reference so id() cannot be reused
    return hit


@dataclass(frozen=True)
class Config:
    # ── entry triggers (all enabled ones must agree) ─────────────────────────
    rsi_len: int = 2
    rsi_buy: float = 10.0          # long when RSI <= this
    rsi_sell: float = 90.0         # short when RSI >= this
    use_rsi: bool = True

    use_z: bool = False            # z-score of close vs its own mean
    z_len: int = 20
    z_buy: float = -2.0
    z_sell: float = 2.0

    down_days: int = 0             # require N consecutive lower closes (0 = off)
    stability: float = 0.0         # candle body/range floor (0 = off)

    # ── regime filter ────────────────────────────────────────────────────────
    trend_len: int = 200
    regime: str = "none"           # none | with_trend | counter_trend

    # ── direction ────────────────────────────────────────────────────────────
    longs: bool = True
    shorts: bool = True

    # ── session ──────────────────────────────────────────────────────────────
    # Intraday behaviour is not uniform across the day: the open is volatile and
    # trending, the middle of the session is quiet and mean-reverting, the close
    # has its own flow. A rule that works at 10:00 can lose at 15:00. Daily bars
    # cannot express this at all.
    hour_from: int = 0             # inclusive, exchange time as stamped in the data
    hour_to: int = 24              # exclusive
    skip_monday: bool = False

    # ── spacing ──────────────────────────────────────────────────────────────
    gap: int = 1                   # minimum bars between signals
    no_repeat: bool = False

    # ── exit ─────────────────────────────────────────────────────────────────
    atr_len: int = 14
    tp: float = 2.0
    sl: float = 1.0


def _hours(bars) -> list:
    """Hour-of-day per bar, parsed once and cached — parsing 240k timestamps per
    candidate would dominate a search."""
    key = (id(bars), "hour", 0)
    hit = _CACHE.get(key)
    if hit is None:
        out = []
        for b in bars:
            s = b.t
            try:
                out.append(int(s[11:13]) if len(s) >= 13 else -1)
            except ValueError:
                out.append(-1)
        hit = out
        _CACHE[key] = hit
        _CACHE_OWNER.append(bars)
    return hit


def _weekdays(bars) -> list:
    key = (id(bars), "wday", 0)
    hit = _CACHE.get(key)
    if hit is None:
        from datetime import datetime
        out = []
        for b in bars:
            try:
                out.append(datetime.strptime(b.t[:10], "%Y-%m-%d").weekday())
            except ValueError:
                out.append(-1)
        hit = out
        _CACHE[key] = hit
        _CACHE_OWNER.append(bars)
    return hit


def zscore(closes: Sequence[float], length: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(closes)
    m = sma(closes, length)
    for i in range(length - 1, len(closes)):
        mean = m[i]
        if mean is None:
            continue
        window = closes[i - length + 1:i + 1]
        var = sum((x - mean) ** 2 for x in window) / length
        sd = var ** 0.5
        out[i] = (closes[i] - mean) / sd if sd > 0 else 0.0
    return out


def generate(bars: Sequence[Bar], c: Config) -> list[Signal]:
    n = len(bars)
    closes = [b.c for b in bars]

    r = _cached(bars, "rsi", c.rsi_len, lambda: rsi(closes, c.rsi_len)) \
        if c.use_rsi else [None] * n
    z = _cached(bars, "z", c.z_len, lambda: zscore(closes, c.z_len)) \
        if c.use_z else [None] * n
    a = _cached(bars, "atr", c.atr_len, lambda: atr(bars, c.atr_len))
    tr = _cached(bars, "ema", c.trend_len, lambda: ema(closes, c.trend_len)) \
        if c.regime != "none" else [None] * n

    session = c.hour_from != 0 or c.hour_to != 24
    hrs = _hours(bars) if session else None
    wds = _weekdays(bars) if c.skip_monday else None

    warmup = max(c.atr_len, c.rsi_len if c.use_rsi else 0,
                 c.z_len if c.use_z else 0,
                 c.trend_len if c.regime != "none" else 0,
                 c.down_days) + 2

    sigs: list[Signal] = []
    last_bar: Optional[int] = None
    last_dir = 0

    for i in range(warmup, n):
        av = a[i]
        if av is None or av <= 0:
            continue
        if session:
            h = hrs[i]
            if h < c.hour_from or h >= c.hour_to:
                continue
        if c.skip_monday and wds[i] == 0:
            continue

        b = bars[i]

        long_ok = c.longs
        short_ok = c.shorts

        if c.use_rsi:
            rv = r[i]
            if rv is None:
                continue
            long_ok &= rv <= c.rsi_buy
            short_ok &= rv >= c.rsi_sell

        if c.use_z:
            zv = z[i]
            if zv is None:
                continue
            long_ok &= zv <= c.z_buy
            short_ok &= zv >= c.z_sell

        if c.down_days > 0:
            down = all(closes[i - k] < closes[i - k - 1] for k in range(c.down_days))
            up = all(closes[i - k] > closes[i - k - 1] for k in range(c.down_days))
            long_ok &= down
            short_ok &= up

        if c.stability > 0:
            rng = b.h - b.l
            st = (abs(b.c - b.o) / rng) if rng > 0 else 0.0
            ok = st >= c.stability
            long_ok &= ok
            short_ok &= ok

        if c.regime != "none":
            tv = tr[i]
            if tv is None:
                continue
            above = b.c > tv
            if c.regime == "with_trend":
                long_ok &= above
                short_ok &= not above
            else:                                    # counter_trend
                long_ok &= not above
                short_ok &= above

        if not (long_ok or short_ok):
            continue
        if long_ok and short_ok:                     # contradictory, take neither
            continue

        if last_bar is not None and (i - last_bar) < c.gap:
            continue
        d = 1 if long_ok else -1
        if c.no_repeat and d == last_dir:
            continue

        sigs.append(Signal(index=i, t=b.t, direction=d, close=b.c, atr=av,
                           rsi=(r[i] if r[i] is not None else 0.0)))
        last_bar, last_dir = i, d

    return sigs
