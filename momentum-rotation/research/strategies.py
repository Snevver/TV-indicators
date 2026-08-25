"""Parameterised entry signals. A strategy is a boolean mask over bar indices.

Families deliberately span opposing theses — dip buying and breakout buying
cannot both be right about the same market, and finding out which (if either)
survives is the point.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lab import Series

FAMILIES = ["dip_rsi", "dip_z", "downrun", "breakout", "mom", "ma_cross"]


def _pct_rank(a: np.ndarray, window: int) -> np.ndarray:
    """Rolling percentile rank of the latest value within its own history."""
    return pd.Series(a).rolling(window).rank(pct=True).to_numpy()


def raw_signal(s: Series, cfg: dict) -> np.ndarray:
    fam = cfg["family"]
    c = s.c
    n = len(c)

    if fam == "dip_rsi":
        r = s.ind[f"rsi{cfg['rsi_len']}"]
        sig = r < cfg["rsi_thr"]
    elif fam == "dip_z":
        sig = s.ind["z20"] < cfg["z_thr"]
    elif fam == "downrun":
        sig = s.ind["downrun"] >= cfg["run_len"]
    elif fam == "breakout":
        w = cfg["bo_win"]
        hi = pd.Series(c).rolling(w).max().to_numpy()
        prev = np.roll(hi, 1); prev[0] = np.nan
        sig = c >= prev
    elif fam == "mom":
        m = s.ind["mom12_1"]
        sig = m > cfg["mom_thr"]
    elif fam == "ma_cross":
        f = s.ind[f"sma{cfg['ma_fast']}"]
        sl = s.ind[f"sma{cfg['ma_slow']}"]
        up = f > sl
        prev = np.roll(up, 1); prev[0] = False
        sig = up & ~prev if cfg.get("ma_cross_only", True) else up
    else:
        raise ValueError(fam)

    return np.nan_to_num(sig, nan=False).astype(bool)


def apply_filters(s: Series, sig: np.ndarray, cfg: dict) -> np.ndarray:
    c = s.c
    out = sig.copy()

    tf = cfg.get("trend", "none")
    if tf != "none":
        ma = s.ind[f"sma{cfg['trend_len']}"]
        ok = c > ma if tf == "above" else c < ma
        out &= np.nan_to_num(ok, nan=False).astype(bool)

    vf = cfg.get("volfil", "none")
    if vf != "none":
        pr = _pct_rank(s.ind["vol20"], 252)
        ok = pr <= cfg["vol_thr"] if vf == "low" else pr >= cfg["vol_thr"]
        out &= np.nan_to_num(ok, nan=False).astype(bool)

    if cfg.get("gap_bars", 0) > 0:
        g = cfg["gap_bars"]
        idx = np.flatnonzero(out)
        keep = []
        last = -10 ** 9
        for i in idx:
            if i - last >= g:
                keep.append(i)
                last = i
        out = np.zeros_like(out)
        out[keep] = True

    # Warmup: never signal before every indicator the config uses is defined.
    need = max(260, cfg.get("trend_len", 0) + 5)
    out[:need] = False
    return out


def signal(s: Series, cfg: dict) -> np.ndarray:
    return apply_filters(s, raw_signal(s, cfg), cfg)
