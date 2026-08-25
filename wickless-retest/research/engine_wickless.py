"""Wickless-candle retest strategy.

The idea, as described:

  1. Find a candle that closed hard in the trend direction with NO wick on the
     side it came from — a bearish candle whose high equals its open (no upper
     wick) in a downtrend, or a bullish candle whose low equals its open (no
     lower wick) in an uptrend. The missing wick says the move began without
     hesitation: sellers were in control from the opening tick.
  2. Mark that open as a line.
  3. Wait for price to come back to it.
  4. Sell the retest in a downtrend, buy it in an uptrend.
  5. Stop just beyond the recent swing, target 1:1.

Entries are LIMIT orders resting at a known price, so a fill at the level is
realistic. Everything is computed from closed bars; nothing reads the future.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from engine import Bar, atr, ema


@dataclass(frozen=True)
class WConfig:
    # ── what counts as wickless ──────────────────────────────────────────────
    wick_tol: float = 0.0        # max wick as a fraction of the bar's range
    min_body: float = 0.0        # min body as a fraction of range (0 = off)

    # ── trend ────────────────────────────────────────────────────────────────
    trend_len: int = 50
    trend_mode: str = "ema"      # ema | ema_slope | off

    # ── the level ────────────────────────────────────────────────────────────
    expiry: int = 50             # bars a level stays live before it is dropped
    min_move_atr: float = 0.5    # price must travel this far away before a
                                 # touch counts as a retest rather than the
                                 # candle simply still being at its own open
    one_level: bool = False      # keep only the newest level per direction

    # ── risk ─────────────────────────────────────────────────────────────────
    atr_len: int = 14
    sl_lookback: int = 10        # swing high/low window for the stop
    sl_buffer_atr: float = 0.2   # breathing room beyond the swing
    min_stop_atr: float = 0.0    # floor on stop distance (0 = off)
    rr: float = 1.0

    # ── direction ────────────────────────────────────────────────────────────
    longs: bool = True
    shorts: bool = True


@dataclass
class WTrade:
    direction: int
    entry_i: int
    exit_i: int
    entry_t: str
    exit_t: str
    entry: float
    exit: float
    sl: float
    tp: float
    r: float
    reason: str

    @property
    def bars_held(self) -> int:
        return self.exit_i - self.entry_i


@dataclass
class _Level:
    price: float
    direction: int          # +1 long setup, -1 short setup
    created: int
    armed: bool = False     # has price moved far enough away yet


def find_wickless(bars: Sequence[Bar], c: WConfig) -> list[tuple[int, int, float]]:
    """Return (bar_index, direction, level_price) for every qualifying candle."""
    out = []
    for i, b in enumerate(bars):
        rng = b.h - b.l
        if rng <= 0:
            continue
        body = abs(b.c - b.o)
        if c.min_body > 0 and body / rng < c.min_body:
            continue
        if b.c < b.o:                                   # bearish
            upper = b.h - b.o
            if upper / rng <= c.wick_tol:
                out.append((i, -1, b.o))                # level = its high = its open
        elif b.c > b.o:                                 # bullish
            lower = b.o - b.l
            if lower / rng <= c.wick_tol:
                out.append((i, 1, b.o))                 # level = its low = its open
    return out


def simulate_wickless(bars: Sequence[Bar], c: WConfig,
                      fee_bps: float = 1.0, slippage_bps: float = 1.0,
                      one_at_a_time: bool = True) -> list[WTrade]:
    n = len(bars)
    closes = [b.c for b in bars]
    a = atr(bars, c.atr_len)
    tr = ema(closes, c.trend_len) if c.trend_mode != "off" else [None] * n
    cost_rate = (fee_bps + slippage_bps) / 10_000.0

    wickless = {}
    for i, d, price in find_wickless(bars, c):
        wickless.setdefault(i, []).append((d, price))

    levels: list[_Level] = []
    trades: list[WTrade] = []
    busy_until = -1

    warmup = max(c.atr_len, c.trend_len, c.sl_lookback) + 2
    for i in range(warmup, n):
        b = bars[i]
        av = a[i]
        if av is None or av <= 0:
            continue

        # ── retire stale levels ──────────────────────────────────────────────
        levels = [lv for lv in levels if i - lv.created <= c.expiry]

        # ── look for a retest ────────────────────────────────────────────────
        if i > busy_until:
            hit: Optional[_Level] = None
            for lv in levels:
                if not lv.armed:
                    continue
                if lv.direction == -1 and b.h >= lv.price and c.shorts:
                    hit = lv
                    break
                if lv.direction == 1 and b.l <= lv.price and c.longs:
                    hit = lv
                    break

            if hit is not None:
                d = hit.direction
                entry = hit.price               # resting limit order
                # The swing is measured over bars that had already CLOSED when
                # the limit order filled. Including the entry bar would use its
                # high/low, which is not known until that bar completes — a
                # look-ahead that quietly inflates results.
                lo = max(0, i - c.sl_lookback)
                if d == -1:
                    swing = max((x.h for x in bars[lo:i]), default=entry)
                    sl = max(swing, entry) + c.sl_buffer_atr * av
                else:
                    swing = min((x.l for x in bars[lo:i]), default=entry)
                    sl = min(swing, entry) - c.sl_buffer_atr * av

                risk = abs(entry - sl)
                if c.min_stop_atr > 0:
                    risk = max(risk, c.min_stop_atr * av)
                    sl = entry - d * risk
                if risk <= 0:
                    levels.remove(hit)
                    continue
                tp = entry + d * risk * c.rr

                # ── walk forward to the exit ─────────────────────────────────
                exit_i = exit_px = None
                reason = ""
                for j in range(i, n):
                    bb = bars[j]
                    if j == i:
                        # On the entry bar only the remainder of the bar is
                        # available, and which of stop/target came first is
                        # unknowable from OHLC. Take the stop: the pessimistic
                        # reading, and the one that cannot flatter the result.
                        if d == -1 and bb.h >= sl:
                            exit_i, exit_px, reason = j, sl, "sl"
                        elif d == 1 and bb.l <= sl:
                            exit_i, exit_px, reason = j, sl, "sl"
                        if exit_i is not None:
                            break
                        continue
                    if d == -1:
                        if bb.h >= sl:
                            exit_i, exit_px, reason = j, sl, "sl"
                        elif bb.l <= tp:
                            exit_i, exit_px, reason = j, tp, "tp"
                    else:
                        if bb.l <= sl:
                            exit_i, exit_px, reason = j, sl, "sl"
                        elif bb.h >= tp:
                            exit_i, exit_px, reason = j, tp, "tp"
                    if exit_i is not None:
                        break
                if exit_i is None:
                    exit_i, exit_px, reason = n - 1, bars[-1].c, "eod"

                gross = (exit_px - entry) * d
                costs = (entry + exit_px) * cost_rate
                trades.append(WTrade(d, i, exit_i, bars[i].t, bars[exit_i].t,
                                     entry, exit_px, sl, tp, (gross - costs) / risk,
                                     reason))
                levels.remove(hit)
                if one_at_a_time:
                    busy_until = exit_i

        # ── arm levels using bars that have CLOSED ──────────────────────────
        # Deliberately after the retest check. Arming here means a level can only
        # be armed by a bar strictly before the one that triggers it. Doing it
        # earlier would let a single bar both travel far enough away (its low)
        # and come back to the level (its high) — and OHLC cannot tell us which
        # happened first, so that ordering would be an assumption in our favour.
        for lv in levels:
            if lv.armed:
                continue
            if lv.direction == -1 and b.l <= lv.price - c.min_move_atr * av:
                lv.armed = True
            elif lv.direction == 1 and b.h >= lv.price + c.min_move_atr * av:
                lv.armed = True

        # ── register new levels from THIS bar (after the retest check, so a
        #    candle can never trigger its own level on the bar that made it) ──
        for d, price in wickless.get(i, []):
            if c.trend_mode != "off":
                tv = tr[i]
                if tv is None:
                    continue
                up = b.c > tv
                if d == 1 and not up:
                    continue
                if d == -1 and up:
                    continue
            if c.one_level:
                levels = [lv for lv in levels if lv.direction != d]
            levels.append(_Level(price=price, direction=d, created=i))

    return trades
