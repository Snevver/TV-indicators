"""pulse.py: the 1-minute OHLC writer and the value formula. `python test_pulse.py`.

No network -- t212.cash and the state file are monkeypatched.
"""
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import pulse


def test_append_bar_writes_header_once_then_rows():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "samples_1m.csv")
    old = pulse.SAMPLES_1M
    pulse.SAMPLES_1M = p
    try:
        ts = datetime(2026, 9, 3, 14, 5, tzinfo=timezone.utc)
        pulse.append_bar(ts, "live", 2000.0, 2001.5, 1999.25, 2000.8)
        pulse.append_bar(ts.replace(minute=6), "live", 2000.8, 2002.0, 2000.5, 2001.9)
        with open(p, newline="") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == list(pulse.COLS)
        assert len(rows) == 3
        assert rows[1] == ["2026-09-03T14:05Z", "live", "2000.00", "2001.50",
                           "1999.25", "2000.80"]
        assert rows[2][0] == "2026-09-03T14:06Z"
    finally:
        pulse.SAMPLES_1M = old


def test_value_is_cash_plus_invested_plus_ppl():
    if pulse.t212 is None:
        print("   (skip: t212 did not import)")
        return
    d = tempfile.mkdtemp()
    st = os.path.join(d, "state.json")
    with open(st, "w") as fh:
        json.dump({"tracks": {"live": {"cash": 7.90}}}, fh)
    old_state, old_cash = pulse.STATE, pulse.t212.cash
    pulse.STATE = st
    pulse.t212.cash = lambda: {"invested": 1980.10, "ppl": 12.65}
    try:
        assert pulse.value() == round(7.90 + 1980.10 + 12.65, 2)
    finally:
        pulse.STATE, pulse.t212.cash = old_state, old_cash


def test_value_is_none_when_the_api_raises():
    if pulse.t212 is None:
        print("   (skip: t212 did not import)")
        return
    old_cash = pulse.t212.cash
    pulse.t212.cash = lambda: (_ for _ in ()).throw(RuntimeError("429"))
    try:
        assert pulse.value() is None
    finally:
        pulse.t212.cash = old_cash


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
