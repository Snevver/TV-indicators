"""Settings validation and rendering. `python test_config.py`.

apply() is the gate between a browser form and the env file the bot reads. A
regression here writes a bad value the bot then chokes on, or silently drops a
setting. for_display() drives the form; the kill switch must come back tagged as
a button, not a field.
"""
import os
import sys
import tempfile

import config


def _isolate(tmpdir):
    """Point config at empty files so nothing on this machine leaks in."""
    config.CONFIG = os.path.join(tmpdir, "momentum.env")
    config.ETC = os.path.join(tmpdir, "etc.env")


# -------------------------------------------------------------------- parse_env

def test_parse_env_skips_comments_and_strips_quotes():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.env")
        with open(p, "w") as fh:
            fh.write("# a comment\n\nFOO=bar\nBAZ=\"quoted value\"\nNOEQ\n")
        got = config.parse_env(p)
        assert got == {"FOO": "bar", "BAZ": "quoted value"}


def test_parse_env_missing_file_is_empty():
    assert config.parse_env("/no/such/file.env") == {}


# ------------------------------------------------------------------- validators

def test_amount_accepts_non_negative_numbers():
    assert config._amount("1000") == "1000"
    assert config._amount(" 0 ") == "0"
    for bad in ("-5", "abc", ""):
        try:
            config._amount(bad)
            assert False, f"{bad!r} should be rejected"
        except config.Invalid:
            pass


def test_choice_normalises_and_rejects():
    check = config._choice("off", "on")
    assert check("ON") == "on"
    assert check(" off ") == "off"
    assert check.choices == ["off", "on"]
    try:
        check("maybe")
        assert False
    except config.Invalid:
        pass


# ------------------------------------------------------------------------ apply

def test_apply_writes_valid_values_and_reports_bad_ones():
    with tempfile.TemporaryDirectory() as d:
        _isolate(d)
        new, errors = config.apply({"MOMENTUM_START_BUDGET": "1000",
                                    "MOMENTUM_MONTHLY": "-3"})
        assert new["MOMENTUM_START_BUDGET"] == "1000"
        assert "MOMENTUM_MONTHLY" in errors
        assert "MOMENTUM_MONTHLY" not in new


def test_apply_clears_a_blank_plain_field():
    with tempfile.TemporaryDirectory() as d:
        _isolate(d)
        with open(config.CONFIG, "w") as fh:
            fh.write("MOMENTUM_MONTHLY=100\n")
        new, errors = config.apply({"MOMENTUM_MONTHLY": ""})
        assert not errors and "MOMENTUM_MONTHLY" not in new


def test_apply_ignores_fields_not_in_the_form():
    with tempfile.TemporaryDirectory() as d:
        _isolate(d)
        with open(config.CONFIG, "w") as fh:
            fh.write("MOMENTUM_START_BUDGET=500\n")
        new, errors = config.apply({"MOMENTUM_MONTHLY": "50"})
        assert new["MOMENTUM_START_BUDGET"] == "500"      # untouched
        assert new["MOMENTUM_MONTHLY"] == "50"


def test_removed_settings_are_gone():
    assert "T212_ENV" not in config.FIELDS
    assert "MOMENTUM_AUTOTRADE" not in config.FIELDS
    _, errors = config.apply({"T212_ENV": "live"})        # ignored, not an error
    assert errors == {}


# ------------------------------------------------------------------ for_display

def test_kill_switch_renders_as_a_button():
    with tempfile.TemporaryDirectory() as d:
        _isolate(d)
        rows = {r["name"]: r for r in config.for_display()}
        assert rows["MOMENTUM_KILL"]["kind"] == "button"
        assert rows["MOMENTUM_START_BUDGET"]["kind"] == "field"


def test_for_display_reports_armed_state():
    with tempfile.TemporaryDirectory() as d:
        _isolate(d)
        with open(config.CONFIG, "w") as fh:
            fh.write("MOMENTUM_KILL=on\n")
        rows = {r["name"]: r for r in config.for_display()}
        assert rows["MOMENTUM_KILL"]["armed"] is True
        with open(config.CONFIG, "w") as fh:
            fh.write("MOMENTUM_KILL=off\n")
        rows = {r["name"]: r for r in config.for_display()}
        assert rows["MOMENTUM_KILL"]["armed"] is False


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
