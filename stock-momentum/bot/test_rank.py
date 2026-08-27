"""The strategy's brain: rank() and due(). `python test_rank.py`.

rank() picks which eight names get held. It is the one thing in the bot that no
amount of bookkeeping can fix if it is wrong, so this pins the two properties
that matter: it ranks on the six months ENDING A MONTH AGO (not to yesterday),
and it drops names with a broken price history rather than ranking them.
"""
import sys
sys.argv = ["x"]
import momentum_bot as bot            # noqa: E402

try:
    import pandas as pd
except ImportError:
    print("skip: pandas not installed")
    sys.exit(0)

N = bot.LOOKBACK + bot.SKIP + 40      # comfortably more history than rank needs
DATES = pd.bdate_range("2025-01-01", periods=N)


def _series(start, end):
    """A straight ramp from `start` to `end` over the whole window."""
    return [start + (end - start) * i / (N - 1) for i in range(N)]


def test_ranks_the_biggest_riser_over_the_lookback_window_first():
    # WIN rises hard until a month ago; FLAT does nothing; LATE is flat too but
    # spikes in the final SKIP days, which rank() is meant to ignore entirely.
    px = pd.DataFrame(index=DATES)
    px["WIN"] = _series(100, 200)
    px["FLAT"] = _series(100, 100)
    px["LATE"] = _series(100, 100)
    px.loc[px.index[-bot.SKIP:], "LATE"] = 500        # a spike inside the skip zone
    r = bot.rank(px)
    assert r.index[0] == "WIN", list(r.index)
    assert abs(r["LATE"]) < 1e-9, r["LATE"]           # the late spike earns nothing
    assert r["WIN"] > r["FLAT"]


def test_skip_window_is_actually_skipped():
    # Two names identical up to a month ago; one then craters. rank() should still
    # score them the same, because it reads the price as of -1-SKIP.
    px = pd.DataFrame(index=DATES)
    px["A"] = _series(100, 150)
    px["B"] = _series(100, 150)
    px.loc[px.index[-bot.SKIP:], "B"] = 1.0
    r = bot.rank(px)
    assert abs(r["A"] - r["B"]) < 1e-9


def test_drops_names_with_no_usable_history():
    px = pd.DataFrame(index=DATES)
    px["GOOD"] = _series(100, 140)
    px["DEAD"] = [float("nan")] * N
    px["ZERO"] = [0.0] * N                            # past price 0 -> can't divide
    r = bot.rank(px)
    assert "GOOD" in r.index
    assert "DEAD" not in r.index and "ZERO" not in r.index


def test_rank_refuses_too_little_history():
    px = pd.DataFrame({"A": [1.0, 2.0, 3.0]},
                      index=pd.bdate_range("2025-01-01", periods=3))
    try:
        bot.rank(px)
        assert False, "expected SystemExit"
    except SystemExit:
        pass


# ------------------------------------------------------------------------- due

def _px(dates):
    return pd.DataFrame({"A": range(len(dates))}, index=pd.DatetimeIndex(dates))


def test_due_true_on_the_first_trading_day_cold_start():
    px = _px(["2026-08-25", "2026-08-26", "2026-09-01"])   # newest bar alone in Sep
    assert bot.due(px, bot._blank()) is True


def test_not_due_mid_month_cold_start():
    px = _px(["2026-09-01", "2026-09-02", "2026-09-03"])   # 3 bars in Sep already
    assert bot.due(px, bot._blank()) is False


def test_due_catches_up_any_day_when_warm():
    bk = bot._blank()
    bk["last_rebalance_month"] = "2026-08"
    px = _px(["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"])
    assert bot.due(px, bk) is True                          # missed the 1st, still due


def test_not_due_again_in_a_month_already_done():
    bk = bot._blank()
    bk["last_rebalance_month"] = "2026-09"
    px = _px(["2026-09-01", "2026-09-15"])
    assert bot.due(px, bk) is False


# ------------------------------------------------------------- next_month_label

def test_next_month_label_rolls_the_year():
    from datetime import date
    assert bot.next_month_label(date(2026, 11, 15)) == "December 2026"
    assert bot.next_month_label(date(2026, 12, 2)) == "January 2027"


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
