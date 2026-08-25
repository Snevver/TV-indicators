#!/usr/bin/env python3
"""Backtest ZeroStar Alpha V2: take every signal, apply the ATR stop and target,
and report whether the result actually makes money after costs.

Usage
-----
  python3 backtest.py --csv data/BTCUSD_60.csv
  python3 backtest.py --synthetic random --bars 20000 --seed 7
  python3 backtest.py --csv data.csv --sweep
  python3 backtest.py --csv data.csv --fee-bps 5 --slippage-bps 5 --tp 2.5 --sl 1

Trading rules simulated
-----------------------
* One position at a time, exactly like the indicator's own tracker.
* Entry on the OPEN of the bar after the signal (--fill open, the default), so
  no trade is ever filled at a price the signal itself needed to know.
* Exit at the ATR take-profit or stop-loss, whichever the bar touches. If a bar
  spans both, the stop is taken — the pessimistic reading. If a bar gaps past a
  level, the fill is the open, not the level.
* Costs are charged on both sides as fee + slippage in basis points.

Position sizing is risk-normalised: every trade risks --risk-pct of equity
between entry and stop, so results are reported in R-multiples (1R = one unit of
risked capital) as well as compounded equity.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from dataclasses import dataclass, replace
from typing import Optional, Sequence

from engine import Bar, Settings, Signal, generate_signals


# ─── Trades ──────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    direction: int
    entry_i: int
    exit_i: int
    entry_t: str
    exit_t: str
    entry: float
    exit: float
    tp: float
    sl: float
    r: float           # R-multiple, net of costs
    reason: str        # tp | sl | timeout | eod

    @property
    def bars_held(self) -> int:
        return self.exit_i - self.entry_i


def simulate(
    bars: Sequence[Bar],
    signals: Sequence[Signal],
    s: Settings,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fill: str = "open",
    max_bars: int = 0,
) -> list[Trade]:
    trades: list[Trade] = []
    cost_rate = (fee_bps + slippage_bps) / 10_000.0
    n = len(bars)
    busy_until = -1

    for sig in signals:
        # One position at a time: signals during an open trade are ignored.
        if sig.index <= busy_until:
            continue

        if fill == "close":
            entry_i = sig.index
            entry = sig.close
        else:
            entry_i = sig.index + 1
            if entry_i >= n:
                break
            entry = bars[entry_i].o

        d = sig.direction
        risk = sig.atr * s.sl_mult
        if risk <= 0:
            continue
        tp = entry + d * sig.atr * s.tp_mult
        sl = entry - d * sig.atr * s.sl_mult

        exit_i, exit_px, reason = None, None, ""
        for j in range(entry_i + 1, n):
            b = bars[j]
            if d == 1:
                # Gap through a level fills at the open, which is worse than the level.
                if b.o <= sl:
                    exit_i, exit_px, reason = j, b.o, "sl"
                elif b.o >= tp:
                    exit_i, exit_px, reason = j, b.o, "tp"
                elif b.l <= sl:
                    exit_i, exit_px, reason = j, sl, "sl"     # stop wins ties
                elif b.h >= tp:
                    exit_i, exit_px, reason = j, tp, "tp"
            else:
                if b.o >= sl:
                    exit_i, exit_px, reason = j, b.o, "sl"
                elif b.o <= tp:
                    exit_i, exit_px, reason = j, b.o, "tp"
                elif b.h >= sl:
                    exit_i, exit_px, reason = j, sl, "sl"
                elif b.l <= tp:
                    exit_i, exit_px, reason = j, tp, "tp"
            if exit_i is not None:
                break
            if max_bars and (j - entry_i) >= max_bars:
                exit_i, exit_px, reason = j, b.c, "timeout"
                break

        if exit_i is None:                      # still open at the end of data
            exit_i, exit_px, reason = n - 1, bars[-1].c, "eod"

        gross = (exit_px - entry) * d
        costs = (entry + exit_px) * cost_rate
        r = (gross - costs) / risk

        trades.append(Trade(d, entry_i, exit_i, bars[entry_i].t, bars[exit_i].t,
                            entry, exit_px, tp, sl, r, reason))
        busy_until = exit_i

    return trades


# ─── Metrics ─────────────────────────────────────────────────────────────────

@dataclass
class Stats:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_r: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    t_stat: float = 0.0
    equity_mult: float = 1.0
    max_dd: float = 0.0
    avg_bars: float = 0.0
    exposure: float = 0.0
    max_consec_losses: int = 0
    longs: int = 0
    shorts: int = 0
    long_r: float = 0.0
    short_r: float = 0.0
    ruined: bool = False


def evaluate(trades: Sequence[Trade], bars: Sequence[Bar], risk_pct: float) -> Stats:
    st = Stats()
    st.trades = len(trades)
    if not trades:
        return st

    rs = [t.r for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    st.wins, st.losses = len(wins), len(losses)
    st.win_rate = 100.0 * st.wins / st.trades
    st.total_r = sum(rs)
    st.expectancy = st.total_r / st.trades
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    st.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    st.avg_win_r = (gross_win / len(wins)) if wins else 0.0
    st.avg_loss_r = (-gross_loss / len(losses)) if losses else 0.0

    if st.trades > 1:
        mean = st.expectancy
        var = sum((r - mean) ** 2 for r in rs) / (st.trades - 1)
        sd = math.sqrt(var)
        st.t_stat = (mean / sd * math.sqrt(st.trades)) if sd > 0 else 0.0

    equity, peak, max_dd = 1.0, 1.0, 0.0
    for r in rs:
        equity *= (1.0 + risk_pct * r)
        if equity <= 0:
            st.ruined = True
            equity = 1e-12
            break
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    st.equity_mult = equity
    st.max_dd = 100.0 * max_dd

    st.avg_bars = sum(t.bars_held for t in trades) / st.trades
    st.exposure = 100.0 * sum(t.bars_held for t in trades) / max(len(bars), 1)

    run = best = 0
    for t in trades:
        run = run + 1 if t.r <= 0 else 0
        best = max(best, run)
    st.max_consec_losses = best

    st.longs = sum(1 for t in trades if t.direction == 1)
    st.shorts = st.trades - st.longs
    st.long_r = sum(t.r for t in trades if t.direction == 1)
    st.short_r = sum(t.r for t in trades if t.direction == -1)
    return st


# ─── Data ────────────────────────────────────────────────────────────────────

def load_csv(path: str) -> list[Bar]:
    """Read OHLCV. Accepts TradingView exports and most generic CSVs."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{path}: no rows")

    keys = {k.lower().strip(): k for k in rows[0].keys()}

    def pick(*names: str) -> Optional[str]:
        for nm in names:
            if nm in keys:
                return keys[nm]
        return None

    kt = pick("time", "date", "datetime", "timestamp", "open time")
    ko, kh, kl, kc = pick("open"), pick("high"), pick("low"), pick("close", "close/last", "price")
    kv = pick("volume", "vol", "volume ma")
    missing = [n for n, k in (("open", ko), ("high", kh), ("low", kl), ("close", kc)) if k is None]
    if missing:
        raise SystemExit(f"{path}: missing column(s): {', '.join(missing)}. Found: {list(rows[0])}")

    def num(x: str) -> float:
        return float(str(x).replace(",", "").replace("$", "").strip())

    bars: list[Bar] = []
    for i, row in enumerate(rows):
        try:
            bars.append(Bar(
                t=str(row[kt]).strip() if kt else str(i),
                o=num(row[ko]), h=num(row[kh]), l=num(row[kl]), c=num(row[kc]),
                v=num(row[kv]) if kv and str(row[kv]).strip() not in ("", "nan", "null") else 0.0,
            ))
        except (ValueError, TypeError):
            continue        # skip blank/partial rows rather than dying on them

    if len(bars) > 1 and bars[0].t > bars[-1].t:
        bars.reverse()      # some exports are newest-first
    return bars


def synthetic(kind: str, n: int, seed: int) -> list[Bar]:
    """Generate bars with no edge in them, as a null hypothesis to test against.

    random     — geometric random walk with volatility clustering
    trend      — the same walk plus a persistent upward drift
    meanrevert — an Ornstein-Uhlenbeck-ish pull back toward a slow average
    """
    rng = random.Random(seed)
    price, vol, bars = 100.0, 0.01, []
    ma = price
    for i in range(n):
        vol = max(0.002, min(0.05, vol * 0.97 + 0.03 * abs(rng.gauss(0, 0.012))))
        drift = 0.0
        if kind == "trend":
            drift = 0.0004
        elif kind == "meanrevert":
            drift = 0.02 * (ma - price) / price
        ret = drift + rng.gauss(0, vol)
        o = price
        c = max(0.01, o * (1 + ret))
        wick = abs(rng.gauss(0, vol)) * o * 0.7
        h = max(o, c) + wick * rng.random()
        l = max(0.005, min(o, c) - wick * rng.random())
        bars.append(Bar(t=f"t{i:06d}", o=o, h=h, l=l, c=c, v=abs(rng.gauss(1000, 300))))
        price = c
        ma += (price - ma) * 0.01
    return bars


# ─── Reporting ───────────────────────────────────────────────────────────────

def line(label: str, value: str) -> str:
    return f"  {label:<26}{value}"


def report(bars, sigs, trades, st: Stats, s: Settings, args) -> str:
    bh = 100.0 * (bars[-1].c / bars[0].c - 1.0) if bars else 0.0
    tp_hits = sum(1 for t in trades if t.reason == "tp")
    sl_hits = sum(1 for t in trades if t.reason == "sl")
    other = len(trades) - tp_hits - sl_hits
    skipped = len(sigs) - len(trades)

    verdict = (
        "PROFITABLE" if st.total_r > 0 and st.expectancy > 0 else
        "UNPROFITABLE" if st.trades else "NO TRADES"
    )
    confidence = (
        "not statistically distinguishable from luck" if abs(st.t_stat) < 2 else
        "statistically significant at ~95% (t>2), on this sample"
    )

    out = []
    out.append("=" * 66)
    out.append(f"  ZeroStar Alpha V2 — backtest: {args.label}")
    out.append("=" * 66)
    out.append(line("Bars", f"{len(bars)}  ({bars[0].t} → {bars[-1].t})"))
    out.append(line("Settings", f"stability={s.stability_index} rsi={s.rsi_index} "
                                f"delta={s.delta_length} tp={s.tp_mult}x sl={s.sl_mult}x atr"))
    out.append(line("Costs", f"{args.fee_bps} bps fee + {args.slippage_bps} bps slippage per side"))
    out.append(line("Fill", f"{args.fill} of bar after signal"))
    out.append("")
    out.append("  SIGNALS")
    out.append(line("Signals fired", f"{len(sigs)}  ({sum(1 for x in sigs if x.direction==1)} buy / "
                                     f"{sum(1 for x in sigs if x.direction==-1)} sell)"))
    out.append(line("Traded / skipped", f"{len(trades)} / {skipped} (position already open)"))
    out.append("")
    out.append("  OUTCOME")
    out.append(line("Trades", str(st.trades)))
    out.append(line("Win rate", f"{st.win_rate:.2f}%   ({st.wins}W / {st.losses}L)"))
    out.append(line("Exits", f"{tp_hits} target, {sl_hits} stop, {other} other"))
    out.append(line("Total R", f"{st.total_r:+.2f}R"))
    out.append(line("Expectancy / trade", f"{st.expectancy:+.4f}R"))
    out.append(line("Profit factor", f"{st.profit_factor:.3f}"))
    out.append(line("Avg win / avg loss", f"{st.avg_win_r:+.3f}R / {st.avg_loss_r:+.3f}R"))
    out.append(line("Long R / short R", f"{st.long_r:+.2f}R ({st.longs}) / {st.short_r:+.2f}R ({st.shorts})"))
    out.append("")
    out.append("  MONEY")
    growth = 100.0 * (st.equity_mult - 1.0)
    out.append(line(f"Equity @ {args.risk_pct*100:g}% risk/trade", f"{growth:+.2f}%" + ("  (ACCOUNT RUINED)" if st.ruined else "")))
    out.append(line("Max drawdown", f"{st.max_dd:.2f}%"))
    out.append(line("Max consecutive losses", str(st.max_consec_losses)))
    out.append(line("Buy & hold, same period", f"{bh:+.2f}%"))
    out.append(line("Avg bars held / exposure", f"{st.avg_bars:.1f} bars / {st.exposure:.1f}% of the time"))
    out.append("")
    out.append("  VERDICT")
    out.append(line("Result", verdict))
    out.append(line("t-statistic of mean R", f"{st.t_stat:+.2f}  — {confidence}"))
    out.append("=" * 66)
    return "\n".join(out)


def sweep_grid(bars, args, base: Settings, min_trades: Optional[int] = None) -> list:
    """Grid-search the four parameters that matter most. Returns rows sorted by expectancy."""
    floor = args.min_trades if min_trades is None else min_trades
    grid = []
    for stab in (0.3, 0.4, 0.5, 0.6, 0.7):
        for rsi_i in (60, 65, 70, 75, 80):
            for delta in (3, 4, 6, 8):
                for tp in (1.0, 1.5, 2.0, 3.0):
                    s = replace(base, stability_index=stab, rsi_index=rsi_i,
                                delta_length=delta, tp_mult=tp)
                    sigs = generate_signals(bars, s).signals
                    if not sigs:
                        continue
                    tr = simulate(bars, sigs, s, args.fee_bps, args.slippage_bps, args.fill, args.max_bars)
                    st = evaluate(tr, bars, args.risk_pct)
                    if st.trades >= floor:
                        grid.append((st.expectancy, stab, rsi_i, delta, tp, st))
    grid.sort(key=lambda g: g[0], reverse=True)
    return grid


def sweep(bars, args, base: Settings) -> str:
    grid = sweep_grid(bars, args, base)
    if not grid:
        return f"  No parameter set produced at least {args.min_trades} trades."
    profitable = sum(1 for g in grid if g[0] > 0)
    out = ["", "=" * 78, "  PARAMETER SWEEP — sorted by expectancy", "=" * 78,
           f"  {len(grid)} parameter sets tested, {profitable} profitable "
           f"({100.0*profitable/len(grid):.1f}%)", "",
           f"  {'stab':>5} {'rsi':>4} {'delta':>6} {'tp':>5} | {'trades':>7} {'win%':>7} "
           f"{'expectancy':>11} {'totalR':>9} {'PF':>6} {'maxDD%':>7}",
           "  " + "-" * 74]
    for exp, stab, rsi_i, delta, tp, st in grid[:15]:
        out.append(f"  {stab:>5.1f} {rsi_i:>4} {delta:>6} {tp:>5.1f} | {st.trades:>7} "
                   f"{st.win_rate:>6.1f}% {exp:>+11.4f} {st.total_r:>+9.1f} "
                   f"{st.profit_factor:>6.2f} {st.max_dd:>7.1f}")
    out.append("  " + "-" * 74)
    out.append("  ... worst 3:")
    for exp, stab, rsi_i, delta, tp, st in grid[-3:]:
        out.append(f"  {stab:>5.1f} {rsi_i:>4} {delta:>6} {tp:>5.1f} | {st.trades:>7} "
                   f"{st.win_rate:>6.1f}% {exp:>+11.4f} {st.total_r:>+9.1f} "
                   f"{st.profit_factor:>6.2f} {st.max_dd:>7.1f}")
    out.append("")
    out.append("  A handful of green rows in a grid this size is what overfitting looks like.")
    out.append("  Trust the shape of the whole table, not its best row.")
    out.append("=" * 78)
    return "\n".join(out)


def walk_forward(bars, args, base: Settings) -> str:
    """Optimise on the first slice of history, then trade the winner on the rest.

    This is the only question that matters. Any setting can be made to look good on
    the data it was chosen from; the test is whether it survives data it has never
    seen. In-sample results below are, by construction, the best of hundreds of
    tries. Out-of-sample results are one honest try.
    """
    cut = int(len(bars) * args.train_frac)
    train, test = bars[:cut], bars[cut:]
    if len(test) < 250:
        return "  Not enough out-of-sample bars to test."

    grid = sweep_grid(train, args, base, min_trades=max(10, args.min_trades // 2))
    if not grid:
        return "  No parameter set cleared the trade floor in-sample."

    out = ["", "=" * 78,
           "  WALK-FORWARD — optimise on the past, trade the future", "=" * 78,
           f"  In-sample:     {len(train)} bars  ({train[0].t} → {train[-1].t})",
           f"  Out-of-sample: {len(test)} bars  ({test[0].t} → {test[-1].t})",
           f"  {len(grid)} parameter sets optimised in-sample; top {args.wf_top} carried forward.",
           "",
           f"  {'stab':>5} {'rsi':>4} {'dlt':>4} {'tp':>4} | {'IS trades':>9} {'IS exp':>9} "
           f"| {'OOS trades':>10} {'OOS exp':>9} {'OOS totalR':>11} {'OOS PF':>7}",
           "  " + "-" * 74]

    survived = 0
    oos_expectancies = []
    for exp, stab, rsi_i, delta, tp, is_st in grid[:args.wf_top]:
        s = replace(base, stability_index=stab, rsi_index=rsi_i, delta_length=delta, tp_mult=tp)
        sigs = generate_signals(test, s).signals
        tr = simulate(test, sigs, s, args.fee_bps, args.slippage_bps, args.fill, args.max_bars)
        st = evaluate(tr, test, args.risk_pct)
        if st.trades:
            oos_expectancies.append(st.expectancy)
            survived += int(st.expectancy > 0)
        out.append(f"  {stab:>5.1f} {rsi_i:>4} {delta:>4} {tp:>4.1f} | {is_st.trades:>9} "
                   f"{exp:>+9.4f} | {st.trades:>10} {st.expectancy:>+9.4f} "
                   f"{st.total_r:>+11.2f} {st.profit_factor:>7.2f}")

    out.append("  " + "-" * 74)
    if oos_expectancies:
        mean_oos = sum(oos_expectancies) / len(oos_expectancies)
        out.append(f"  {survived}/{len(oos_expectancies)} of the in-sample winners stayed "
                   f"profitable out-of-sample.")
        out.append(f"  Mean out-of-sample expectancy: {mean_oos:+.4f}R")
        out.append("")
        if mean_oos > 0.02 and survived > len(oos_expectancies) / 2:
            out.append("  READ: the edge survived unseen data. Weak evidence it is real.")
        else:
            out.append("  READ: the in-sample edge did NOT survive unseen data. That is the")
            out.append("        signature of curve-fitting, not of a tradeable strategy.")
    out.append("=" * 78)
    return "\n".join(out)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Backtest the ZeroStar Alpha V2 indicator.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="OHLCV CSV file (TradingView export works as-is)")
    src.add_argument("--synthetic", choices=["random", "trend", "meanrevert"],
                     help="generate bars with no real edge, as a control")
    p.add_argument("--bars", type=int, default=20000, help="synthetic bar count")
    p.add_argument("--seed", type=int, default=1, help="synthetic RNG seed")

    p.add_argument("--stability", type=float, default=0.5)
    p.add_argument("--rsi-index", type=int, default=70)
    p.add_argument("--rsi-length", type=int, default=14)
    p.add_argument("--delta", type=int, default=4)
    p.add_argument("--no-engulf", action="store_true", help="drop the engulfing requirement")
    p.add_argument("--gap", type=int, default=6, help="minimum bars between signals")
    p.add_argument("--allow-repeats", action="store_true")
    p.add_argument("--trend", action="store_true", help="enable the EMA trend filter")
    p.add_argument("--trend-mode", choices=["With trend", "Counter trend"], default="Counter trend")
    p.add_argument("--trend-len", type=int, default=200)
    p.add_argument("--volume", action="store_true", help="require volume expansion")

    p.add_argument("--atr", type=int, default=14)
    p.add_argument("--tp", type=float, default=2.0, help="take profit, in ATRs")
    p.add_argument("--sl", type=float, default=1.0, help="stop loss, in ATRs")
    p.add_argument("--max-bars", type=int, default=0, help="force an exit after N bars (0 = never)")

    p.add_argument("--fee-bps", type=float, default=2.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--fill", choices=["open", "close"], default="open",
                   help="'open' = next bar's open (realistic); 'close' = signal bar's close")
    p.add_argument("--risk-pct", type=float, default=0.01, help="fraction of equity risked per trade")

    p.add_argument("--sweep", action="store_true", help="grid-search the parameters")
    p.add_argument("--min-trades", type=int, default=30, help="sweep: ignore sets below this many trades")
    p.add_argument("--trades-csv", help="write every trade to this path")
    p.add_argument("--walk-forward", action="store_true",
                   help="optimise on early history, then test the winners on later history")
    p.add_argument("--train-frac", type=float, default=0.7,
                   help="fraction of bars used for in-sample optimisation")
    p.add_argument("--wf-top", type=int, default=10,
                   help="how many in-sample winners to carry out-of-sample")
    args = p.parse_args(argv)

    if args.csv:
        bars = load_csv(args.csv)
        args.label = args.csv
    else:
        bars = synthetic(args.synthetic, args.bars, args.seed)
        args.label = f"synthetic/{args.synthetic} seed={args.seed}"

    if len(bars) < 250:
        print(f"Only {len(bars)} bars — too few to say anything.", file=sys.stderr)
        return 2

    s = Settings(
        stability_index=args.stability, rsi_index=args.rsi_index, rsi_length=args.rsi_length,
        delta_length=args.delta, require_engulf=not args.no_engulf,
        no_repeat=not args.allow_repeats, label_gap=args.gap,
        use_trend=args.trend, trend_len=args.trend_len, trend_mode=args.trend_mode,
        use_vol=args.volume, atr_length=args.atr, tp_mult=args.tp, sl_mult=args.sl,
    )

    sigs = generate_signals(bars, s).signals
    trades = simulate(bars, sigs, s, args.fee_bps, args.slippage_bps, args.fill, args.max_bars)
    st = evaluate(trades, bars, args.risk_pct)
    print(report(bars, sigs, trades, st, s, args))

    if args.trades_csv:
        with open(args.trades_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["dir", "entry_time", "exit_time", "entry", "exit", "tp", "sl", "R", "reason", "bars"])
            for t in trades:
                w.writerow([("long" if t.direction == 1 else "short"), t.entry_t, t.exit_t,
                            f"{t.entry:.8f}", f"{t.exit:.8f}", f"{t.tp:.8f}", f"{t.sl:.8f}",
                            f"{t.r:.4f}", t.reason, t.bars_held])
        print(f"\n  Wrote {len(trades)} trades to {args.trades_csv}")

    if args.sweep:
        print(sweep(bars, args, s))
    if args.walk_forward:
        print(walk_forward(bars, args, s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
