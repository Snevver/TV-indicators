"""state.json migration and the batch-resume helpers. `python test_state.py`.

The migration matters because the file on the mini PC predates the demo/live
split, and a wrong move here is what put "demo stats on the live page". The
resume helpers decide whether a half-sent batch can be picked up or must wait
for a human -- getting that wrong either strands the batch or double-sends an
order.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.argv = ["x"]
import momentum_bot as bot            # noqa: E402


def _load(tmp, obj):
    if obj is None:
        if os.path.exists(tmp):
            os.unlink(tmp)
    else:
        with open(tmp, "w") as fh:
            json.dump(obj, fh)
    bot.STATE = tmp
    return bot.load_state()


# ------------------------------------------------------------------ load_state

def test_missing_file_gives_two_empty_tracks():
    with tempfile.TemporaryDirectory() as d:
        s = _load(os.path.join(d, "state.json"), None)
        assert set(s["tracks"]) == {"demo", "live"}
        assert s["tracks"]["demo"]["cash"] == 0.0
        assert s["schema"] == 2


def test_paper_book_is_dropped_live_is_kept():
    with tempfile.TemporaryDirectory() as d:
        old = {"schema": 2, "tracks": {
            "paper": {**bot._blank(), "cash": 999.0},
            "live": {**bot._blank(), "cash": 123.0, "deposited": 100.0}}}
        s = _load(os.path.join(d, "state.json"), old)
        assert "paper" not in s["tracks"]
        assert s["tracks"]["live"]["cash"] == 123.0
        assert s["tracks"]["demo"]["cash"] == 0.0          # created fresh


def test_schema_1_flat_book_becomes_the_live_track():
    with tempfile.TemporaryDirectory() as d:
        flat = {**bot._blank(), "cash": 500.0, "deposited": 500.0,
                "basket": ["AAA"]}
        s = _load(os.path.join(d, "state.json"), flat)
        assert s["tracks"]["live"]["cash"] == 500.0
        assert s["tracks"]["live"]["basket"] == ["AAA"]
        assert s["tracks"]["demo"]["cash"] == 0.0


def test_load_state_backfills_missing_keys():
    with tempfile.TemporaryDirectory() as d:
        partial = {"schema": 2, "tracks": {"live": {"cash": 10.0}, "demo": {}}}
        s = _load(os.path.join(d, "state.json"), partial)
        for k in bot.EMPTY_BOOK:
            assert k in s["tracks"]["live"] and k in s["tracks"]["demo"]
        assert s["tracks"]["live"]["cash"] == 10.0


def test_book_selects_the_named_track():
    s = {"tracks": {"demo": {"cash": 1.0}, "live": {"cash": 2.0}}}
    assert bot.book(s, "demo")["cash"] == 1.0
    assert bot.book(s, "live")["cash"] == 2.0


# ---------------------------------------------------------------- resume_point

def test_resume_point_skips_finished_orders():
    orders = [{"state": "sent", "ticker": "A"},
              {"state": "skipped", "ticker": "B"},
              {"state": "pending", "ticker": "C"}]
    i, why = bot.resume_point(orders)
    assert i == 2 and why == ""


def test_resume_point_allows_a_failed_order():
    # 'failed' is a definitive 400: never placed, safe to send now.
    orders = [{"state": "sent", "ticker": "A"}, {"state": "failed", "ticker": "B"}]
    i, why = bot.resume_point(orders)
    assert i == 1 and why == ""


def test_resume_point_blocks_on_an_unknown_order():
    # 'sending'/'unknown' = may or may not have reached the broker. Stop.
    orders = [{"state": "sent", "ticker": "A"},
              {"state": "unknown", "ticker": "B"},
              {"state": "pending", "ticker": "C"}]
    i, why = bot.resume_point(orders)
    assert i is None and "not " in why


def test_resume_point_all_done():
    i, why = bot.resume_point([{"state": "sent"}, {"state": "skipped"}])
    assert i is None and "finished" in why


# -------------------------------------------------------------- pending_expired

def test_pending_expired_by_age():
    old = (datetime.now(timezone.utc)
           - timedelta(hours=bot.PENDING_EXPIRY_H + 1)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    assert bot.pending_expired({"offered_at": old}) is True
    assert bot.pending_expired({"offered_at": fresh}) is False
    assert bot.pending_expired({}) is False                  # nothing to judge


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
