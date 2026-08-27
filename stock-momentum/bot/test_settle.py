"""settle_batch: the money credit happens once, not per call. `python test_settle.py`.

The demo autotrade path settles in the same process that planned the rebalance,
which once credited the starting amount twice (the rebalance code credits the
in-memory book, then settle_batch credits it again). settle_batch's own contract
is "the book has not been credited yet, and settling twice is refused" -- this
pins both halves.
"""
import os
import sys
import tempfile

sys.argv = ["x"]
import momentum_bot as bot            # noqa: E402


def _paths(d):
    bot.STATE = os.path.join(d, "state.json")
    bot.PENDING = os.path.join(d, "pending.json")
    bot.LOG = os.path.join(d, "rebalances.csv")
    bot.DEPOSITS = os.path.join(d, "deposits.csv")


def _fresh_state():
    return {"schema": 2, "tracks": {"demo": bot._blank(), "live": bot._blank()}}


def _batch():
    return {
        "stage": "done", "track": "demo", "bar": "2026-09-01", "month": "2026-09",
        "basket": ["AAA", "BBB"], "start": 1000.0, "monthly": 0.0,
        "orders": [
            {"ticker": "AAA", "shares": 6.0, "cash": -600.0, "price": 100.0,
             "state": "sent"},
            {"ticker": "BBB", "shares": 4.0, "cash": -396.0, "price": 99.0,
             "state": "sent"},
        ],
    }


def test_settle_credits_the_starting_amount_exactly_once():
    with tempfile.TemporaryDirectory() as d:
        _paths(d)
        state, p = _fresh_state(), _batch()
        after = bot.settle_batch(state, p, "test")
        bk = state["tracks"]["demo"]
        assert bk["deposited"] == 1000.0, bk["deposited"]        # not 2000
        # 1000 in, 996 spent on shares -> ~4 left.
        assert abs(bk["cash"] - 4.0) < 1e-6, bk["cash"]
        assert bk["positions"] == {"AAA": 6.0, "BBB": 4.0}
        assert after["deposited"] == 1000.0


def test_settle_is_refused_a_second_time():
    with tempfile.TemporaryDirectory() as d:
        _paths(d)
        state, p = _fresh_state(), _batch()
        bot.settle_batch(state, p, "first")
        dep_after_first = state["tracks"]["demo"]["deposited"]
        again = bot.settle_batch(state, p, "second")             # p now has settled_at
        assert again is None
        assert state["tracks"]["demo"]["deposited"] == dep_after_first


def test_settle_writes_a_dated_deposit_row():
    with tempfile.TemporaryDirectory() as d:
        _paths(d)
        state, p = _fresh_state(), _batch()
        bot.settle_batch(state, p, "test")
        with open(bot.DEPOSITS, encoding="utf-8") as fh:
            body = fh.read()
        assert "demo,1000.00" in body and body.count("\n") == 2   # header + 1 row


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
