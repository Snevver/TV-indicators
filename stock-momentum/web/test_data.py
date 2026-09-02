"""The dashboard's file readers. `python test_data.py`.

Every reader here has to return something usable when the file is missing, half
written, or from an older schema -- a dashboard that 500s because the bot has not
run yet is worse than one that says "no data". These pin that, plus the shapes
the charts depend on.
"""
import os
import sys
import tempfile

import data


def _write(path, text):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(text)


# ----------------------------------------------------------------- _f / _maybe

def test_f_falls_back_maybe_returns_none():
    assert data._f("12.5") == 12.5
    assert data._f("", 0.0) == 0.0 and data._f(None) == 0.0
    assert data._maybe("3") == 3.0
    assert data._maybe("") is None and data._maybe(None) is None
    assert data._maybe("nope") is None


# --------------------------------------------------------------------- missing

def test_missing_files_give_empty_results():
    with tempfile.TemporaryDirectory() as d:
        data.HOURLY = os.path.join(d, "nope.csv")
        data.HISTORY = os.path.join(d, "nope2.csv")
        data.REBALANCES = os.path.join(d, "nope3.csv")
        assert data.hourly("live") == []
        assert data.history("live") == []
        assert data.rebalances("live") == []
        assert data.curve("live")["dates"] == []


# ---------------------------------------------------------------------- hourly

def test_hourly_filters_by_series_and_sorts():
    with tempfile.TemporaryDirectory() as d:
        data.HOURLY = os.path.join(d, "hourly.csv")
        _write(data.HOURLY,
               "time,series,total,bench\n"
               "2026-08-27T12:00Z,live,1008.00,1002.00\n"
               "2026-08-27T11:00Z,live,1005.00,\n"          # bench not priced
               "2026-08-27T12:00Z,demo,1012.00,1003.00\n")
        rows = data.hourly("live")
        assert [r["time"] for r in rows] == \
            ["2026-08-27T11:00Z", "2026-08-27T12:00Z"]      # sorted
        assert rows[0]["bench"] is None                     # blank -> None
        assert rows[1]["total"] == 1008.0


# ---------------------------------------------------------------------- model

def test_model_filters_by_track_sorts_and_tolerates_blanks():
    with tempfile.TemporaryDirectory() as d:
        data.MODEL = os.path.join(d, "model.csv")
        _write(data.MODEL,
               "date,track,value\n"
               "2026-08-28,demo,1001.10\n"
               "2026-08-27,demo,1000.00\n"
               "2026-08-28,live,999.00\n"
               "2026-08-29,demo,\n")                    # blank -> dropped
        rows = data.model("demo")
        assert [r["time"] for r in rows] == ["2026-08-27", "2026-08-28"]
        assert rows[1]["value"] == 1001.10


def test_model_missing_file_is_empty():
    with tempfile.TemporaryDirectory() as d:
        data.MODEL = os.path.join(d, "nope.csv")
        assert data.model("demo") == []


# --------------------------------------------------------------------- history

def test_history_reads_only_its_track():
    with tempfile.TemporaryDirectory() as d:
        data.HISTORY = os.path.join(d, "history.csv")
        _write(data.HISTORY,
               "date,track,total,invested,cash,deposited,pnl,realised,"
               "unrealised,positions\n"
               "2026-08-02,live,1000,900,100,1000,0,0,0,8\n"
               "2026-08-02,demo,500,450,50,500,0,0,0,8\n")
        rows = data.history("demo")
        assert len(rows) == 1 and rows[0]["total"] == 500.0
        assert rows[0]["positions"] == 8


# ----------------------------------------------------------------------- curve

def test_curve_derives_drawdown_from_history():
    with tempfile.TemporaryDirectory() as d:
        data.HISTORY = os.path.join(d, "history.csv")
        _write(data.HISTORY,
               "date,track,total,invested,cash,deposited,pnl,realised,"
               "unrealised,positions\n"
               "2026-08-01,live,100,0,100,100,0,0,0,0\n"
               "2026-09-01,live,120,0,120,100,20,0,0,0\n"
               "2026-10-01,live,90,0,90,100,-10,0,0,0\n")
        c = data.curve("live")
        assert c["total"] == [100.0, 120.0, 90.0]
        assert c["peak"] == 120.0
        assert abs(c["maxdd"] - (-25.0)) < 1e-9             # 90 is 25% below 120
        assert [m["month"] for m in c["monthly"]] == \
            ["2026-08", "2026-09", "2026-10"]


# ------------------------------------------------------------------ rebalances

def test_rebalances_splits_lists_and_sorts_newest_first():
    with tempfile.TemporaryDirectory() as d:
        data.REBALANCES = os.path.join(d, "rebalances.csv")
        _write(data.REBALANCES,
               "date,buys,sells,basket,account,cash,deposited,pnl,track\n"
               "2026-08-01,AAA BBB,,AAA BBB,1000,10,1000,0,\n"        # legacy blank -> live
               "2026-09-01,CCC,AAA,BBB CCC,1100,5,1100,100,live\n"
               "2026-09-01,ZZZ,,ZZZ,50,1,50,0,demo\n")               # other track, filtered out
        rows = data.rebalances("live")
        assert [r["date"] for r in rows] == ["2026-09-01", "2026-08-01"]   # newest first, demo dropped
        assert rows[0]["buys"] == ["CCC"] and rows[0]["sells"] == ["AAA"]
        assert rows[1]["buys"] == ["AAA", "BBB"]
        assert rows[0]["account"] == 1100.0
        assert [r["buys"] for r in data.rebalances("demo")] == [["ZZZ"]]


# -------------------------------------------------------------------- run_bot

def test_run_bot_rejects_an_unknown_action():
    r = data.run_bot("definitely-not-real")
    assert r["ok"] is False and "unknown action" in r["err"]


def test_every_action_is_a_flag_list():
    for name, argv in data.ACTIONS.items():
        assert isinstance(argv, list) and argv
        assert all(a.startswith("--") for a in argv), (name, argv)


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
