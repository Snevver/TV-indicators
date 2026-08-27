"""Runnable check for the benchmark math in tracker.py. `python test_tracker.py`."""
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")
