"""Backtest math: _stats and _irr. `python test_simulate.py`.

These produce the headline numbers on the Simulate page. _irr is the one that
matters most: with money arriving every month, final/first - 1 counts your own
deposits as profit, so the page shows a money-weighted rate instead. If _irr
drifts, the "beat the index by X" verdict is wrong.
"""
import sys

import simulate as sim

try:
    import numpy  # noqa: F401
except ImportError:
    print("skip: numpy not installed")
    sys.exit(0)


def _close(a, b, tol=0.05):
    return abs(a - b) < tol


# ------------------------------------------------------------------------ _stats

def test_stats_simple_gain_over_a_year():
    s = sim._stats(["2024-01-01", "2025-01-01"], [100.0, 110.0])
    assert s["final"] == 110.0
    assert _close(s["ret_pct"], 10.0)
    assert _close(s["cagr_pct"], 10.0)
    assert s["maxdd_pct"] == 0.0


def test_stats_measures_worst_drawdown():
    s = sim._stats(["2024-01-01", "2024-06-01", "2024-12-01"],
                   [100.0, 120.0, 90.0])
    assert _close(s["maxdd_pct"], 25.0)          # 90 is 25% under the 120 peak


def test_stats_too_short_is_safe():
    s = sim._stats(["2024-01-01"], [100.0])
    assert s["final"] == 100.0 and s["maxdd_pct"] == 0.0 and s["cagr_pct"] is None


# -------------------------------------------------------------------------- _irr

def test_irr_single_flow_pair_is_the_plain_return():
    # 1000 in at t=0, 1100 back at t=1  ->  10% a year.
    assert _close(sim._irr([(0.0, -1000.0), (1.0, 1100.0)], 1.0), 10.0)


def test_irr_no_growth_is_zero():
    assert _close(sim._irr([(0.0, -1000.0), (1.0, 1000.0)], 1.0), 0.0)


def test_irr_rewards_earlier_money_less():
    # Same total paid in and same final value, but half the money arrives at the
    # midpoint -> the money-weighted rate is higher than the naive 5%.
    early = sim._irr([(0.0, -2000.0), (1.0, 2100.0)], 1.0)
    late = sim._irr([(0.0, -1000.0), (0.5, -1000.0), (1.0, 2100.0)], 1.0)
    assert late > early


def test_irr_unsolvable_is_nan():
    r = sim._irr([(0.0, -1000.0), (1.0, -50.0)], 1.0)   # never any money back
    assert r != r                                        # NaN


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print("all passed" if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
