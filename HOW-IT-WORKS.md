# How to trade with the bot, step by step

Plain order of events. What the bot does, what you do, and when.

**The bot never places an order and never moves money.** It reads your account
and tells you what to trade. Every trade is placed by you, in the Trading 212
app. That is true no matter what any setting says.

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
| Which account | `live` |
| Which book to follow | `paper` — leave it here for now |
| Currency | `EUR` |
| Monthly contribution | `100`, or `0` for none |

**4. Keep your other investments out of the way**
The bot ignores anything held in a **pie**, and anything outside its forty names.
So your existing pie is invisible to it. What it cannot tell apart is one of its
forty names bought by hand outside a pie — so keep discretionary buys either in a
pie, or in something other than those forty.

---

## The first month

### A few days before the 1st
- **You:** make sure the money has landed in free funds.

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

## Later: approving orders from Discord

Approval by reaction already works — the bot posts, you tick, it reads the tick,
and it checks the tick came from **your** user id specifically.

What does not exist yet is the part that submits orders to Trading 212. Until
that is written and tested, every trade is placed by hand.

Before that gets switched on: one full month done manually, so we know the
instructions are actually executable, and a first automated run watched live.
