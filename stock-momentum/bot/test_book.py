"""The money math: mark, apply_orders, plan. `python test_book.py`.

These functions take explicit dicts and touch no network, so they test in
isolation. The one identity worth remembering: after ANY sequence of deposit /
buy / sell / price move,

    total == cash + sum(position values)      and      pnl == total - deposited

If a change breaks that, it breaks the account figure on the dashboard.
"""
import sys
sys.argv = ["x"]                      # no --env; TRACK defaults to live
import momentum_bot as bot            # noqa: E402

EQ = 1e-6


def _book(cash=0.0, deposited=0.0):
    b = bot._blank()
    b["cash"] = float(cash)
    b["deposited"] = float(deposited)
    return b


def _identity(bk, prices):
    m = bot.mark(bk, prices)
    pv = sum(sh * prices[t] for t, sh in bk["positions"].items() if t in prices)
    assert abs(m["total"] - (bk["cash"] + pv)) < EQ, m
    assert abs(m["pnl"] - (m["total"] - m["deposited"])) < EQ, m
    return m


# --------------------------------------------------------------------- mark

def test_empty_book_marks_to_zero():
    m = bot.mark(_book(), {})
    assert m["total"] == 0 and m["invested"] == 0 and m["cash"] == 0
    assert m["pnl"] == 0 and m["pnl_pct"] == 0        # no divide-by-zero


def test_deposit_only_is_all_cash():
    m = bot.mark(_book(cash=1000, deposited=1000), {})
    assert m["total"] == 1000 and m["cash"] == 1000
    assert m["invested"] == 0 and m["pnl"] == 0 and m["realised"] == 0


def test_mark_values_positions_and_pnl():
    b = _book(cash=0, deposited=100)
    b["positions"]["AAA"] = 2.0
    b["book"]["AAA"] = 100.0                          # cost basis, total not per-share
    m = bot.mark(b, {"AAA": 80.0})                    # price up 20/share => value 160
    assert abs(m["invested"] - 160.0) < EQ
    assert abs(m["unrealised"] - 60.0) < EQ
    assert abs(m["pnl"] - 60.0) < EQ                  # realised 0 + unrealised 60
    assert abs(m["total"] - 160.0) < EQ


def test_mark_ignores_unpriced_and_zero_positions():
    b = _book(cash=50, deposited=50)
    b["positions"] = {"AAA": 1.0, "BBB": 0.0}
    b["book"] = {"AAA": 10.0, "BBB": 5.0}
    m = bot.mark(b, {})                               # no prices at all
    assert m["rows"] == {} and m["invested"] == 0
    assert m["total"] == 50                           # just the cash


# ---------------------------------------------------------------- apply_orders

def test_buy_moves_cash_not_deposited():
    b = _book(cash=1000, deposited=1000)
    bot.apply_orders(b, [("AAA", 4.0, -400.0)], {"AAA": 100.0})
    assert abs(b["cash"] - 600.0) < EQ
    assert b["positions"]["AAA"] == 4.0 and b["book"]["AAA"] == 400.0
    assert b["deposited"] == 1000.0
    _identity(b, {"AAA": 100.0})


def test_sell_at_a_profit_banks_the_gain():
    b = _book(cash=0, deposited=100)
    bot.apply_orders(b, [("AAA", 1.0, -100.0)], {"AAA": 100.0})     # buy 1 @ 100
    bot.apply_orders(b, [("AAA", -1.0, 150.0)], {"AAA": 150.0})     # sell 1 @ 150
    m = bot.mark(b, {"AAA": 150.0})
    assert abs(m["realised"] - 50.0) < EQ
    assert abs(m["deposited"] - 100.0) < EQ                         # untouched
    assert abs(m["total"] - 150.0) < EQ
    assert "AAA" not in b["positions"]                              # closed cleanly


def test_sell_at_a_loss_is_symmetric():
    b = _book(cash=0, deposited=100)
    bot.apply_orders(b, [("AAA", 1.0, -100.0)], {"AAA": 100.0})
    bot.apply_orders(b, [("AAA", -1.0, 70.0)], {"AAA": 70.0})
    m = bot.mark(b, {"AAA": 70.0})
    assert abs(m["realised"] + 30.0) < EQ
    assert abs(m["total"] - 70.0) < EQ


def test_partial_sell_moves_cost_basis_proportionally():
    b = _book(cash=0, deposited=200)
    bot.apply_orders(b, [("AAA", 4.0, -200.0)], {"AAA": 50.0})      # 4 @ 50, cost 200
    bot.apply_orders(b, [("AAA", -2.0, 140.0)], {"AAA": 70.0})      # sell half @ 70
    assert abs(b["book"]["AAA"] - 100.0) < EQ                       # half the cost left
    assert abs(b["positions"]["AAA"] - 2.0) < EQ
    m = bot.mark(b, {"AAA": 70.0})
    assert abs(m["realised"] - 40.0) < EQ                           # 140 - 100
    assert abs(m["unrealised"] - 40.0) < EQ                         # 2*70 - 100
    _identity(b, {"AAA": 70.0})


# ----------------------------------------------------------------------- plan

def _prices(n=8, px=100.0):
    return {f"T{i}": px for i in range(n)}


def test_plan_equal_weights_the_opening_basket():
    prices = _prices()
    b = _book(cash=1000, deposited=1000)
    orders = bot.plan(b, prices, list(prices), 1000, reserve=bot.CASH_BUFFER)
    assert all(dsh > 0 for _, dsh, _ in orders)                     # all buys
    spend = sum(-dc for _, _, dc in orders)
    assert spend <= 1000 + EQ                                       # never overspends
    assert spend >= 1000 * (1 - bot.CASH_BUFFER) - 1                # deploys ~all of it
    each = [-dc for _, _, dc in orders]
    assert max(each) - min(each) < EQ                               # equal weight


def test_plan_sells_names_that_left_the_basket_and_keeps_survivors():
    prices = _prices()
    b = _book(cash=0, deposited=800)
    for t in ("T0", "T1"):
        b["positions"][t] = 1.0
        b["book"][t] = 100.0
    new_basket = ["T0", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
    prices["T8"] = 100.0
    orders = bot.plan(b, prices, new_basket, 200.0)
    sells = [o for o in orders if o[1] < 0]
    assert [s[0] for s in sells] == ["T1"]                          # only the dropout
    assert all(o[0] != "T0" for o in orders if o[1] > 0)            # survivor untouched


def test_plan_spreads_the_contribution_over_the_whole_basket():
    prices = _prices()
    b = _book(cash=100, deposited=100)                              # 100 is new money
    for t in ("T0", "T1"):
        b["positions"][t] = 1.0
        b["book"][t] = 100.0
    basket = ["T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7"]
    orders = bot.plan(b, prices, basket, 300.0, contribution=100.0)
    bought = {o[0] for o in orders if o[1] > 0}
    assert "T0" in bought and "T1" in bought                        # survivors get a slice


def test_plan_reserve_holds_money_back():
    prices = _prices()
    b = _book(cash=1000, deposited=1000)
    full = sum(-dc for _, _, dc in bot.plan(b, prices, list(prices), 1000))
    held = sum(-dc for _, _, dc in
               bot.plan(b, prices, list(prices), 1000, reserve=0.05))
    assert held < full and held <= 1000 * 0.95 + EQ


# --------------------------------------------------------- round-trip identity

def test_trading_creates_no_value():
    prices = _prices()
    b = _book(cash=1000, deposited=1000)
    orders = bot.plan(b, prices, list(prices), 1000, reserve=bot.CASH_BUFFER)
    bot.apply_orders(b, orders, prices)
    m = _identity(b, prices)                                        # same prices
    assert abs(m["total"] - 1000) < 1e-3                            # value conserved
    assert abs(m["pnl"]) < 1e-3


# ------------------------------------------------------------------- reconcile
#
# adopt=True takes the broker's share counts AND its own cost basis, then
# re-squares cash. The basis must not depend on an exchange rate we fetched
# ourselves -- that was drifting the dashboard P&L by ~0.5% an hour.

def _snap(positions, invested):
    """A minimal t212.snapshot() shape."""
    return {"positions": {tk: {"shares": sh, "cost": cost}
                          for tk, (sh, cost) in positions.items()},
            "account_cash": {"invested": invested}}


def test_reconcile_basis_comes_from_the_brokers_invested_figure():
    b = _book(cash=4.97, deposited=1000.0)
    b["positions"] = {"AAA": 1.0, "BBB": 1.0}
    b["book"] = {"AAA": 500.0, "BBB": 500.0}               # stale, planned-price
    # Broker: same shares, USD cost split 60/40, real EUR basis 989.87.
    snap = _snap({"AAA": (1.0, 600.0), "BBB": (1.0, 400.0)}, 989.87)
    bot.reconcile(b, snap, adopt=True)
    assert abs(sum(b["book"].values()) - 989.87) < 1e-6   # sums to the broker's
    assert abs(b["book"]["AAA"] - 989.87 * 0.6) < 1e-4     # by USD cost weight
    assert abs(b["book"]["BBB"] - 989.87 * 0.4) < 1e-4


def test_reconcile_re_squares_cash_to_deposited_minus_basis():
    b = _book(cash=4.97, deposited=1000.0)                 # bot thinks it spent 995
    b["positions"] = {"AAA": 1.0}
    b["book"] = {"AAA": 995.03}
    snap = _snap({"AAA": (1.0, 1000.0)}, 989.87)           # fills were cheaper
    bot.reconcile(b, snap, adopt=True)
    assert abs(b["cash"] - (1000.0 - 989.87)) < 1e-6       # the ~5 comes back
    _identity(b, {"AAA": 989.87})                          # total == cash + value


def test_reconcile_without_a_cash_endpoint_falls_back_to_fx():
    bot._FX.clear()
    bot._FX.update(rate=0.5, ccy="EUR", sym="€", err="")
    b = _book(cash=0.0, deposited=100.0)
    snap = {"positions": {"AAA": {"shares": 1.0, "cost": 100.0}},
            "account_cash": None}
    bot.reconcile(b, snap, adopt=True)
    assert abs(b["book"]["AAA"] - 50.0) < 1e-6             # 100 USD * 0.5
    bot._FX.clear()


def test_reconcile_adopt_false_changes_nothing():
    b = _book(cash=4.97, deposited=1000.0)
    b["positions"] = {"AAA": 1.0}
    b["book"] = {"AAA": 500.0}
    before = (dict(b["positions"]), dict(b["book"]), b["cash"])
    diffs = bot.reconcile(b, _snap({"AAA": (2.0, 900.0)}, 900.0), adopt=False)
    assert (dict(b["positions"]), dict(b["book"]), b["cash"]) == before
    assert diffs == [("AAA", 1.0, 2.0)]                    # still reports the gap


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
