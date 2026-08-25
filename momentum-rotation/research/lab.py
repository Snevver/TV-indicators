"""Research harness: load once, index once, then run thousands of strategies fast.

Design notes that matter for trusting the output:

  * Indicators are computed per ticker on the FULL series, then sliced by date.
    Slicing after computation means a 2021 signal sees the same EMA it would have
    seen live. Computing per slice would restart every moving average at the slice
    boundary, which is a different (and wrong) strategy.

  * Every array is float64 numpy. A strategy is a boolean mask over bar indices.

  * ENTRY IS ALWAYS THE NEXT BAR'S OPEN. A signal computed from today's close can
    only be acted on tomorrow morning. Nothing here fills at the close it was
    derived from.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "_data-export", "data")

# Three eras. TRAIN to search, VAL to choose, TEST looked at once at the end.
TRAIN_END = "2015-12-31"
VAL_END = "2021-06-30"


@dataclass
class Series:
    """One ticker, everything precomputed."""
    ticker: str
    t: np.ndarray          # datetime64
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    ind: dict              # name -> np.ndarray

    def __len__(self):
        return len(self.c)


def _rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    # Wilder smoothing, matching Pine's ta.rsi
    au = np.empty_like(c); ad = np.empty_like(c)
    au[:n] = np.nan; ad[:n] = np.nan
    au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
    a = 1.0 / n
    for i in range(n + 1, len(c)):
        au[i] = a * up[i] + (1 - a) * au[i - 1]
        ad[i] = a * dn[i] + (1 - a) * ad[i - 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        out = 100 - 100 / (1 + rs)
    out[ad == 0] = 100.0
    out[(au == 0) & (ad > 0)] = 0.0
    return out


def _ema(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(c, np.nan)
    if len(c) < n:
        return out
    a = 2.0 / (n + 1)
    out[n - 1] = c[:n].mean()
    for i in range(n, len(c)):
        out[i] = a * c[i] + (1 - a) * out[i - 1]
    return out


def _sma(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(c, np.nan)
    if len(c) < n:
        return out
    cs = np.cumsum(np.insert(c, 0, 0.0))
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def _atr(h, l, c, n: int) -> np.ndarray:
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full_like(c, np.nan)
    if len(c) < n:
        return out
    out[n - 1] = tr[:n].mean()
    a = 1.0 / n
    for i in range(n, len(c)):
        out[i] = a * tr[i] + (1 - a) * out[i - 1]
    return out


def _rolling_std(c: np.ndarray, n: int) -> np.ndarray:
    s = pd.Series(c)
    return s.rolling(n).std(ddof=0).to_numpy()


def build(df: pd.DataFrame, ticker: str) -> Series | None:
    df = df.sort_values("time")
    c = df["close"].to_numpy(float)
    if len(c) < 500:
        return None
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    v = df["volume"].to_numpy(float)
    if not np.all(np.isfinite(c)) or c.min() <= 0:
        return None

    ind = {}
    for n in (2, 3, 4, 14):
        ind[f"rsi{n}"] = _rsi(c, n)
    for n in (5, 10, 20, 50, 100, 200):
        ind[f"sma{n}"] = _sma(c, n)
    for n in (20, 50, 200):
        ind[f"ema{n}"] = _ema(c, n)
    for n in (14, 20):
        ind[f"atr{n}"] = _atr(h, l, c, n)

    ret = np.zeros_like(c)
    ret[1:] = c[1:] / c[:-1] - 1.0
    ind["ret"] = ret
    for n in (20, 60):
        ind[f"vol{n}"] = pd.Series(ret).rolling(n).std(ddof=0).to_numpy() * np.sqrt(252)
    # Distance from the 20-day mean, in standard deviations
    sd20 = _rolling_std(c, 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        ind["z20"] = (c - ind["sma20"]) / sd20
    # Momentum: 12-month return skipping the most recent month, the standard
    # academic construction (the skip avoids short-term reversal contaminating it)
    mom = np.full_like(c, np.nan)
    if len(c) > 252:
        mom[252:] = c[231:-21] / c[:-252] - 1.0
    ind["mom12_1"] = mom
    # Consecutive down closes
    down = np.zeros_like(c)
    dd = ret < 0
    run = 0
    for i in range(len(c)):
        run = run + 1 if dd[i] else 0
        down[i] = run
    ind["downrun"] = down
    ind["dollarvol"] = pd.Series(c * v).rolling(20).median().to_numpy()

    return Series(ticker, df["time"].to_numpy(), o, h, l, c, v, ind)


def load(which: str = "etfs", min_dollar_vol: float = 5e6) -> dict[str, Series]:
    path = os.path.join(DATA, f"{which}_daily.csv.gz")
    raw = pd.read_csv(path, parse_dates=["time"])
    out = {}
    for tk, grp in raw.groupby("ticker"):
        s = build(grp, tk)
        if s is None:
            continue
        dv = s.ind["dollarvol"]
        med = np.nanmedian(dv)
        # Below this, the cost model is fiction and the fills would not exist.
        if not np.isfinite(med) or med < min_dollar_vol:
            continue
        out[tk] = s
    return out


def era_masks(s: Series):
    """Boolean masks for the three eras, aligned to this ticker's bars."""
    t = s.t
    tr = t <= np.datetime64(TRAIN_END)
    va = (t > np.datetime64(TRAIN_END)) & (t <= np.datetime64(VAL_END))
    te = t > np.datetime64(VAL_END)
    return tr, va, te
