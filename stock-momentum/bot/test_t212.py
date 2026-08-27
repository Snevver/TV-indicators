"""Pure helpers in t212.py. `python test_t212.py`.

_trunc / _round_qty decide the quantity that actually goes to the broker. They
must truncate TOWARD ZERO: a buy rounded up overspends, a sell rounded up sheds
more than is held. Trading 212 rejected 0.006404 and 6.8878 for over-precision
early on, which is why this exists.

symbol() maps the broker's instrument codes back to tickers; getting BRK_B wrong
would relabel a class B holding as class A.
"""
import sys
import t212


def test_trunc_rounds_toward_zero_both_signs():
    assert t212._trunc(6.8878, 3) == 6.887          # not 6.888
    assert t212._trunc(0.006404, 3) == 0.006        # not 0.007
    assert t212._trunc(-6.8878, 3) == -6.887        # toward zero, not -6.888
    assert t212._trunc(5.0, 3) == 5.0
    assert t212._trunc(1.2345, 0) == 1.0


def test_round_qty_uses_the_configured_precision():
    assert t212._round_qty(1.23456789) == t212._trunc(1.23456789, t212.QTY_DECIMALS)
    # A buy quantity never grows.
    assert t212._round_qty(2.9999) <= 2.9999


def test_symbol_strips_the_suffix():
    assert t212.symbol("AAPL_US_EQ") == "AAPL"
    assert t212.symbol("MSFT_US_EQ") == "MSFT"
    assert t212.symbol("TSLA_EQ") == "TSLA"


def test_symbol_keeps_the_share_class():
    # The remaining underscore is a class, not padding: BRK_B is NOT BRK.
    assert t212.symbol("BRK_B_US_EQ") == "BRK.B"


def test_pick_takes_the_first_present_non_null_key():
    d = {"total": None, "totalValue": 1234.5, "equity": 999}
    assert t212._pick(d, "total", "totalValue", "equity") == 1234.5
    assert t212._pick(d, "missing", default=0.0) == 0.0
    assert t212._pick({}, "a", "b", default=None) is None
    assert t212._pick("not a dict", "a", default="x") == "x"


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
