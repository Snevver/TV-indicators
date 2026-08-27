"""tracker.py: the benchmark math and the strategy valuation. `python test_tracker.py`.

The valuation must be cash + shares*price -- the STRATEGY's slice -- not the
whole Trading 212 account, or free funds sitting in the account inflate the
money-over-time line.
"""
import sys
import tracker


def test_on_or_before_picks_last_close_not_after():
    closes = {"2026-01-02": 100.0, "2026-01-05": 110.0, "2026-01-06": 111.0}
    assert tracker._on_or_before(closes, "2026-01-05") == 110.0
    # A Saturday: fall back to Friday's close, never Monday's.
    assert tracker._on_or_before(closes, "2026-01-03") == 100.0
    # Before the series starts: no answer.
    assert tracker._on_or_before(closes, "2025-12-31") is None


def test_bench_value_is_money_weighted():
    # 100 in at price 100 (1 unit) + 100 in at price 50 (2 units) = 3 units.
    # Now at price 200 -> 600.
    closes = {"2026-01-02": 100.0, "2026-02-02": 50.0, "2026-03-02": 200.0}
    deposits = [("2026-01-02", 100.0), ("2026-02-02", 100.0)]
    assert tracker.bench_value(deposits, closes, 200.0) == 600.0


def test_bench_value_none_without_data():
    assert tracker.bench_value([], {"2026-01-02": 100.0}, 100.0) is None
    assert tracker.bench_value([("2026-01-02", 100.0)], None, None) is None


def test_strategy_total_is_cash_plus_held_shares():
    book = {"cash": 1004.98, "deposited": 2000.0,
            "positions": {"AAA": 2.0, "BBB": 1.0}}
    px = {"AAA": 100.0, "BBB": 24.0}
    # 1004.98 + 200 + 24 = 1228.98  -- NOT the 5000 sitting in the account.
    assert tracker.strategy_total(book, px) == 1228.98


def test_strategy_total_tolerates_a_missing_price():
    book = {"cash": 50.0, "deposited": 50.0, "positions": {"AAA": 3.0}}
    assert tracker.strategy_total(book, {}) == 50.0        # just the cash


def test_strategy_total_none_for_an_unfunded_book():
    assert tracker.strategy_total({"cash": 0.0, "positions": {}}, {}) is None
    assert tracker.strategy_total({}, {}) is None


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
