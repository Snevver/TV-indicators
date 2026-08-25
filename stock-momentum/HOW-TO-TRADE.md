# How to trade this

One decision a month. Ten minutes.

## The routine

**On the first trading day of each month:**

1. Open any of the 40 stocks with the indicator on it.
2. Read the table. The top 8 rows are the new basket.
3. Sell anything you hold that is no longer in the top 8.
4. Buy anything in the top 8 that you do not hold, equal weight.
5. Close the laptop until next month.

Typically 1–4 changes. In the eight rebalances of 2026 so far: 8, 1, 2, 1, 2, 2, 2, 4.

## Reading the table correctly

Two rows at the bottom, and they mean different things:

| Row | What it means |
|---|---|
| `rank now` | Where this stock ranks **today**. Moves daily. |
| `position` | Whether you **own it**. Only changes at a rebalance. |

When they disagree the table says **"changes at rebalance"**. That is the state to
respect. A stock can be sold at rank 17 and be back at rank 5 two weeks later —
you still do not own it until the next month-start. Acting on `rank now` between
rebalances turns a monthly strategy into a daily one, which is not what was
tested.

## Position sizing

Equal weight, one eighth each, always fully invested. On €3,000 that is €375 per
name.

There is **no stop-loss and no take-profit**. The exit is the ranking. Adding a
stop was tested during development and made things worse: momentum's drawdowns
happen through the rebalance, not intraday, so a stop sells the position and you
still hold it on paper until month-end.

## Discord alerts

Two ways to get them, and you only need one.

**From TradingView** (below) — nothing to install, but it needs a **paid plan**;
webhooks are not available on the free tier.

**From your own machine** — `bot/momentum_bot.py`, run daily from cron on
anything that stays awake. Free, works on any TradingView plan, and it ranks the
stocks with the same code the backtest used rather than the Pine reimplementation
of it. See [`bot/README.md`](bot/README.md). If you have a box running 24/7, this
is the one to use.

The rest of this section is the TradingView route.

### 1. Get a webhook URL from Discord
Server Settings → Integrations → Webhooks → New Webhook → pick a channel → Copy
Webhook URL. It looks like `https://discord.com/api/webhooks/123.../abc...`.

Treat it as a password. Anyone with it can post to your channel.

### 2. Create the alert in TradingView
On any chart with the indicator:

- Right-click → **Add alert**
- **Condition**: `Stock Momentum` → **Any alert() function call**
- **Options**: Once Per Bar Close
- **Notifications** tab → tick **Webhook URL** → paste your Discord URL
- Leave the message box **empty** — the script writes it
- Name it something like "Momentum rebalance", save

That single alert covers all 40 stocks. It fires on the first bar of each month
and only when the basket actually changes.

### What arrives

```
Momentum rebalance 2026-08-03
BUY: UNH, GE
SELL: SLB, QCOM
Hold: MU, INTC, CAT, CSCO, UNH, JNJ, MRK, GE
```

### Why the message is JSON

Discord webhooks reject plain text — they need a JSON body with a `content`
field. The **"Format alerts as Discord JSON"** input (on by default) wraps the
message for you. Turn it off if you are pointing the webhook at something else,
such as your own server.

### If nothing arrives

- **Free plan?** Webhooks are paid-only. The alert will fire but not POST.
- **Message box not empty?** Whatever you typed replaces the script's JSON, and
  Discord rejects it. Clear the box.
- **Wrong condition?** It must be *Any alert() function call*, not the named
  "Enters the basket" condition — that one is per-symbol.
- **Nothing on a normal day?** Correct. It only fires at a month boundary, and
  only when the basket changes.

### Per-symbol alerts instead

If you would rather have one alert per stock, the named conditions **"Enters the
basket"** and **"Leaves the basket"** are there. They need one alert per chart —
40 alerts, which needs a Plus plan or higher.

## Paper trading first

Run it on paper for two or three rebalances before committing money. What you are
checking is not whether it makes money in three months — three months tells you
nothing — but whether the operational side works: alerts arriving, orders filling
near the open, the basket matching what the table said.

## What to expect

Backtested 2005–2026, this returned 12.7% / 25.8% / 25.5% a year across the three
eras against the index's 4.9% / 14.4% / 11.9%. It also drew down **57.6% in
2008–09** and underperformed a random pick by 42 points in 2009 alone.

Momentum crashes. When it does, the strategy holds exactly the stocks that fall
hardest, and no rule in this indicator prevents that. Position size for that
outcome, not for the good years.
