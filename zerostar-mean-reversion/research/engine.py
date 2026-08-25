"""Python port of the ZeroStar Alpha V2 signal engine.

This mirrors indicators/zerostar-alpha-v2.pine rule for rule, including Pine's
Wilder (RMA) smoothing for RSI/ATR and its SMA seeding for EMA, so that signals
produced here line up with the ones TradingView draws.

Pure standard library: no pandas, no numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence


# ─── Data ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Bar:
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass(frozen=True)
class Settings:
    """Defaults match the .pine file's input defaults exactly."""
    stability_index: float = 0.5
    rsi_index: int = 70
    rsi_length: int = 14
    delta_length: int = 4
    require_engulf: bool = True

    no_repeat: bool = True
    label_gap: int = 6
    use_trend: bool = False
    trend_len: int = 200
    trend_mode: str = "Counter trend"   # or "With trend"
    use_vol: bool = False
    vol_len: int = 20
    vol_mult: float = 1.5

    atr_length: int = 14
    tp_mult: float = 2.0
    sl_mult: float = 1.0


@dataclass(frozen=True, slots=True)
class Signal:
    index: int
    t: str
    direction: int      # +1 buy, -1 sell
    close: float
    atr: float
    rsi: float


# ─── Pine-equivalent series maths ────────────────────────────────────────────

def sma(values: Sequence[float], length: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= length:
            run -= values[i - length]
        if i >= length - 1:
            out[i] = run / length
    return out


def rma(values: Sequence[float], length: int) -> list[Optional[float]]:
    """Pine's ta.rma: Wilder smoothing seeded with an SMA of the first `length`."""
    out: list[Optional[float]] = [None] * len(values)
    if length <= 0 or len(values) < length:
        return out
    seed = sum(values[:length]) / length
    out[length - 1] = seed
    prev = seed
    alpha = 1.0 / length
    for i in range(length, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def ema(values: Sequence[float], length: int) -> list[Optional[float]]:
    """Pine's ta.ema: seeded with an SMA of the first `length` values."""
    out: list[Optional[float]] = [None] * len(values)
    if length <= 0 or len(values) < length:
        return out
    seed = sum(values[:length]) / length
    out[length - 1] = seed
    prev = seed
    alpha = 2.0 / (length + 1)
    for i in range(length, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(closes: Sequence[float], length: int) -> list[Optional[float]]:
    """Pine's ta.rsi: RMA of gains / RMA of losses."""
    n = len(closes)
    if n < 2:
        return [None] * n
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains[i] = max(d, 0.0)
        losses[i] = max(-d, 0.0)
    # Pine drops the first bar (no change defined), so smooth from index 1 on.
    ag = rma(gains[1:], length)
    al = rma(losses[1:], length)
    out: list[Optional[float]] = [None] * n
    for i in range(1, n):
        g, l = ag[i - 1], al[i - 1]
        if g is None or l is None:
            continue
        if l == 0:
            out[i] = 100.0
        elif g == 0:
            out[i] = 0.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + g / l)
    return out


def atr(bars: Sequence[Bar], length: int) -> list[Optional[float]]:
    """Pine's ta.atr: RMA of true range."""
    tr = [0.0] * len(bars)
    for i, b in enumerate(bars):
        if i == 0:
            tr[i] = b.h - b.l
        else:
            pc = bars[i - 1].c
            tr[i] = max(b.h - b.l, abs(b.h - pc), abs(b.l - pc))
    return rma(tr, length)


# ─── Signal engine ───────────────────────────────────────────────────────────

@dataclass
class EngineResult:
    signals: list[Signal] = field(default_factory=list)
    rsi: list[Optional[float]] = field(default_factory=list)
    atr: list[Optional[float]] = field(default_factory=list)
    raw_buy: int = 0     # candidates before gating (cooldown / no-repeat)
    raw_sell: int = 0


def generate_signals(bars: Sequence[Bar], s: Settings = Settings()) -> EngineResult:
    """Walk the bars once and emit confirmed signals.

    Every rule reads only the current and previous bars, so nothing here can see
    the future — the same non-repainting guarantee the Pine version makes.
    """
    n = len(bars)
    closes = [b.c for b in bars]
    volumes = [b.v for b in bars]

    rsi_s = rsi(closes, s.rsi_length)
    atr_s = atr(bars, s.atr_length)
    ema_s = ema(closes, s.trend_len) if s.use_trend else [None] * n
    vol_s = sma(volumes, s.vol_len) if s.use_vol else [None] * n

    res = EngineResult(rsi=rsi_s, atr=atr_s)
    last_signal_bar: Optional[int] = None
    last_dir = 0

    ob = float(s.rsi_index)
    os_ = 100.0 - s.rsi_index
    with_trend = s.trend_mode == "With trend"

    for i in range(n):
        if i < s.delta_length or i < 1:
            continue
        r = rsi_s[i]
        a = atr_s[i]
        if r is None or a is None or a <= 0:
            continue

        b, p = bars[i], bars[i - 1]

        rng = b.h - b.l
        body = abs(b.c - b.o)
        stability = (body / rng) if rng > 0 else 0.0
        stable = stability >= s.stability_index

        fell = b.c < bars[i - s.delta_length].c
        rose = b.c > bars[i - s.delta_length].c

        bull_engulf = b.c > b.o and p.c < p.o and b.c >= p.o and b.o <= p.c
        bear_engulf = b.c < b.o and p.c > p.o and b.c <= p.o and b.o >= p.c
        bull_pattern = bull_engulf if s.require_engulf else b.c > b.o
        bear_pattern = bear_engulf if s.require_engulf else b.c < b.o

        if s.use_trend:
            e = ema_s[i]
            if e is None:
                continue
            above = b.c > e
            trend_ok_buy = (not above) if not with_trend else above
            trend_ok_sell = above if not with_trend else (not above)
        else:
            trend_ok_buy = trend_ok_sell = True

        if s.use_vol:
            va = vol_s[i]
            vol_ok = va is not None and va > 0 and b.v > va * s.vol_mult
        else:
            vol_ok = True

        raw_buy = bull_pattern and stable and r <= os_ and fell and trend_ok_buy and vol_ok
        raw_sell = bear_pattern and stable and r >= ob and rose and trend_ok_sell and vol_ok
        res.raw_buy += int(raw_buy)
        res.raw_sell += int(raw_sell)

        gap_ok = last_signal_bar is None or (i - last_signal_bar) >= s.label_gap
        buy = raw_buy and gap_ok and (not s.no_repeat or last_dir != 1)
        sell = raw_sell and gap_ok and (not s.no_repeat or last_dir != -1)

        if buy or sell:
            direction = 1 if buy else -1
            res.signals.append(Signal(index=i, t=b.t, direction=direction, close=b.c, atr=a, rsi=r))
            last_signal_bar = i
            last_dir = direction

    return res
