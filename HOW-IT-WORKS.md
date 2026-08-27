# How to trade with the bot, step by step

Plain order of events. What the bot does, what you do, and when.

**By default the bot never places an order.** It reads your account and tells you
what to trade; you place every trade in the Trading 212 app. That is how it
arrives, and how it stays until you change one setting.

**Turning that setting on does not make it trade on its own either.** With
_Place approved orders_ set to `on`, the bot posts the month's orders to Discord
with a ✅ and then stops. Nothing is sent to Trading 212 until you react — and
only your reaction counts. No reaction, no orders: the batch expires after six
hours and the month stays open.

So two things have to line up before a single euro moves:

| | What it decides |
|---|---|
| _Automatic trading_ = `on` | an approved batch is sent to the broker, and orders are worked out from what you really hold |
| your ✅ in Discord | that this particular batch is approved |

Miss either and the bot goes on telling you what to trade and leaving the trading
to you.

---

## Before the first month — one-time setup

Do these once, in this order.

**1. Money in the account**
Your euros sit in Trading 212 **free funds**. Not in a pie. A pie cannot be
funded through the API and cannot hold uninvested cash, so the strategy trades in
your ordinary portfolio instead.

**2. A standing order, if you want to add monthly**
Set it to land **a few days before the 1st**, so the money is there when the bot
sizes the orders. Then put the same number in Settings → *Monthly contribution*.
Both are needed: the bank moves the money, the setting tells the bot to expect it.

**3. Check the settings page**

| Setting | Value |
|---|---|
| Account | `demo` for the trial month, then `live` |
| Monthly contribution | `100`, or `0` for none |
| Automatic trading | `off` until the trial has run |

Everything else — the Trading 212 keys, the Discord webhook and bot token, the
channel and your user id — is set once over SSH in `/etc/momentum-bot.env`; the
settings page just shows whether each is present.

**4. Keep your other investments out of the way**
The bot ignores anything held in a **pie**, and anything outside its forty names.
So your existing pie is invisible to it. What it cannot tell apart is one of its
forty names bought by hand outside a pie — so keep discretionary buys either in a
pie, or in something other than those forty.

---

## The first month

### A few days before the 1st
- **You:** make sure the money has landed in **free funds** — the uninvested
  balance Trading 212 shows at the top of the app. Money sitting in a pie, or a
  bank transfer that has not settled, is not free funds, and an order against it
  is rejected. `--t212-check` prints the figure the broker reports.

### First trading day of the month, 21:00 Amsterdam
- **Bot:** ranks the forty names, takes the top 8, works out the orders, and
  posts them to Discord.
- Nothing has been bought. The message is a list of instructions.

### Between 21:00 and 22:00 — the same evening
This is the window. The US market closes at 22:00 Amsterdam, and the strategy
was measured buying at that close.

- **You:** open Trading 212 and place the 8 buys exactly as listed.
- Buy by **amount in euros**, not share count — the message gives you euro
  amounts, and fractional shares mean any amount works.
- If you miss the window, place them next morning. You will fill at a different
  price than the one measured. Not fatal, once.

### After you have traded
- **You:** run this to check the bot's assumptions against what you actually
  hold:
  ```
  cd ~/tv-indicators/stock-momentum/bot
  python3 momentum_bot.py --t212-check
  ```
- If it lists differences, the bot's book has drifted from reality. Correct it:
  ```
  python3 momentum_bot.py --fill AAPL=0.55@201.30
  ```
  one for each name that filled differently.

### The rest of the month
- **Bot:** runs every weeknight, updates prices, posts nothing.
- **You:** nothing. Look at the dashboard if you want.

---

## Every month after that

Same thing, one difference: there are now positions to sell.

### A few days before the 1st
- **You:** check the standing order landed.

### First trading day, 21:00
- **Bot:** re-ranks, and posts a message with two parts:
  - **SELL** — names that dropped out of the top 8.
  - **BUY** — names that entered it, plus where this month's new money goes.
- Names that stayed in the top 8 are **not** mentioned. That is deliberate:
  letting winners run is the strategy, and trimming them back to equal slices
  measured worse over twenty-one years.

### Between 21:00 and 22:00
- **You, in this order:**
  1. **Sell first.** The proceeds land in free funds.
  2. **Then buy.** The buys are paid from those proceeds plus your new €100.

  Order matters — buy first and you may not have the cash.

### After trading
- **You:** `--t212-check` again, and `--fill` anything that differed.

### If nothing changed
Some months the top 8 is the same as last month. Then there is nothing to sell
and nothing to buy except this month's contribution, spread across the eight you
already hold.

---

## What each command is for

| Command | What it does |
|---|---|
| `--status` | What you hold and what it is worth |
| `--t212-check` | Broker versus the bot's book. Changes nothing |
| `--t212-sync` | Makes the bot's book match the broker |
| `--fill TICKER=SHARES@PRICE` | Correct one assumed fill |
| `--deposit 500` | Tell the bot you paid money in by hand |
| `--dry` | Show what it would do, save nothing |
| `--pending-status` | This month's orders and what happened to each one |
| `--pending-cancel` | Drop an outstanding proposal without placing anything |

---

## Things that will bite you

**The one-hour window.** 21:00 to 22:00 Amsterdam, on a weekday evening, on the
first trading day of the month. If you are never free then, the strategy will
drift from the measured version. Decide this before you fund it.

**Never press "Rebalance" on a pie.** It resets everything to equal weights,
which is exactly the behaviour that measured worse.

**The paper book is a model.** It assumes you filled at the closing price. If you
do not correct real fills with `--fill`, its numbers slowly stop being true.

**Free cash earns interest.** You have around €21,000 earning roughly €2 a day.
Moving money into this strategy gives that up, in exchange for something
validated in backtest with a few months of paper trading behind it. How much goes
in is a real decision.

---

## Automatic trading

Off by default. To turn it on: **Settings → Automatic trading → on**. That one
switch also makes the bot plan from your real Trading 212 holdings rather than
the simulated book — there is no separate "which book" setting to get wrong.

### What happens then, on rebalance day

1. **21:00.** The bot ranks the forty, works out the orders, and posts them to
   Discord with a ✅ and a ❌. **Nothing has been sent.** The month is not marked
   done, and the book has not moved — because none of it is true yet.
2. **You react.** ✅ places them, ❌ skips the month. Only your user id counts;
   a checkmark from anyone else is ignored and said so out loud.
3. **Within about a minute** the poller sees the reaction and sends the orders:
   every sell first, then every buy, because the sells are what pays for the
   buys. It posts back what went out.
4. **Only then** does the book move and the month count as rebalanced.

Ignore the message and it expires after six hours, having ordered nothing. React
❌ and the month is skipped and not offered again — `--force` if you change your
mind.

### What it refuses to do

- **Sell what you do not hold.** Before every sell it asks Trading 212 what is
  actually there and sells that, not what the book assumed. If the broker shows
  nothing, the sell is skipped rather than opening a short.
- **Send the same order twice.** Each order is written to disk as _sending_
  before the request goes out. If the process is killed halfway through, the next
  run resumes at the order after the last confirmed one. If it died *during* an
  order — or the network failed, which looks the same from here — that order's
  fate is unknown, so the batch stops dead and waits for you. It is never
  retried.
- **Carry on after a surprise.** Anything unexpected halts the whole batch,
  because the cash that pays for the buys depends on the sells ahead of them
  having gone through. `--pending-status` shows exactly what was sent and what
  was not; `--pending-resume` carries on, `--pending-abandon` records what did
  go through and closes the month there.
- **Trade on the paper track.** Paper is a model of the strategy. It never
  touches the broker, whatever the settings say.

### Before you switch it on

Do the smoke test (`--smoke-offer`, then ✅ and ❌ in Discord) so you have seen a
real order placed and closed by reaction. Then one full month by hand, so we know
the instructions are executable. Then turn it on and watch the first run live.
