"""pulse.py: the 1-minute OHLC writer, the sample, and the latest.json patch.
`python test_pulse.py`. No network -- t212.cash is monkeypatched.
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


def test_sample_returns_ppl_and_cost_basis():
    if pulse.t212 is None:
        print("   (skip: t212 did not import)")
        return
    old_cash = pulse.t212.cash
    pulse.t212.cash = lambda: {"free": 25000.0, "invested": 1980.10,
                               "ppl": 12.65, "total": 26992.75}
    try:
        assert pulse.sample() == (12.65, 1980.10)   # profit + basis, free funds ignored
    finally:
        pulse.t212.cash = old_cash


def test_sample_is_none_when_the_api_raises():
    if pulse.t212 is None:
        print("   (skip: t212 did not import)")
        return
    old_cash = pulse.t212.cash
    pulse.t212.cash = lambda: (_ for _ in ()).throw(RuntimeError("429"))
    try:
        assert pulse.sample() == (None, None)
    finally:
        pulse.t212.cash = old_cash


def test_patch_latest_updates_only_the_live_money_fields():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "latest.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"generated": "old", "tracks": {
            "live": {"total": 1.0, "pnl": 1.0, "positions": {"MU": {"shares": 1}},
                     "basket": ["MU"]},
            "demo": {"total": 99.0}}}, fh)
    old = pulse.LATEST
    pulse.LATEST = p
    try:
        pulse.patch_latest(16.40, 1991.00)          # ppl, cost basis
        got = json.load(open(p, encoding="utf-8"))
        live = got["tracks"]["live"]
        assert live["total"] == round(1991.00 + 16.40, 2)
        assert live["pnl"] == 16.40 and live["cash"] == 0.0
        assert live["pnl_pct"] == round(16.40 / 1991.00 * 100, 2)
        assert live["positions"] == {"MU": {"shares": 1}}   # left alone
        assert got["tracks"]["demo"]["total"] == 99.0       # left alone
        assert got["generated"] != "old"
        # No file -> no-op, no raise.
        pulse.LATEST = os.path.join(d, "gone.json")
        pulse.patch_latest(5.0, 100.0)
    finally:
        pulse.LATEST = old


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
