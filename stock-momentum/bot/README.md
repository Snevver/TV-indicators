# Discord alert bot

Posts the monthly rebalance to a Discord channel. Runs on any machine that is
awake once a day — a mini PC, a Raspberry Pi, a VPS.

## Why this rather than a TradingView alert

Both work. TradingView alerts need a paid plan (webhooks are not on Basic), and
they fire from the Pine indicator, which is a *reimplementation* of the backtest.
The two agree today — that was checked signal by signal on live charts — but they
are separate codebases and can drift apart.

This script ranks the universe with the same logic the backtest used, so what
you get alerted on is what was actually measured. It also costs nothing, keeps
its own log of every rebalance, and cannot silently stop because an alert expired
after 90 days.

If you already pay for TradingView and would rather not run anything, use the
alert instead — see `../HOW-TO-TRADE.md`. Running both is fine and gives you a
cross-check; you will just get two messages.

## Setup

```bash
pip install yfinance pandas requests

# In Discord: Server Settings -> Integrations -> Webhooks -> New Webhook,
# pick the channel, Copy Webhook URL.
export DISCORD_WEBHOOK='https://discord.com/api/webhooks/...'
```

Put the export in `~/.profile` (or the cron line, below) so it survives reboots.
**The webhook URL is a password** — anyone holding it can post to your channel.
Keep it out of the repo, out of screenshots, and out of chat messages.

Check it works:

```bash
python momentum_bot.py --dry      # ranks, prints, posts nothing, changes nothing
```

That prints the current top 12 and what it would buy and sell. If the numbers
look like the indicator's table, you are wired up correctly.

## Running it

```cron
30 22 * * 1-5 DISCORD_WEBHOOK='https://discord.com/api/webhooks/...' /usr/bin/python3 /path/to/bot/momentum_bot.py >> /path/to/bot/cron.log 2>&1
```

Weeknights after the US close. Any evening hour works; the script keys "is a
rebalance due" off the newest *daily bar*, not the wall clock, so weekends,
holidays, time zones and a missed night all take care of themselves. On a day
with nothing to do it prints one line and exits — no message is sent.

The first run has no history, so it treats the whole basket as new buys and
posts immediately, whatever the date. That is your starting position. After
that it only speaks on the first trading day of each month.

## Commands

| Command | What it does |
|---|---|
| `python momentum_bot.py` | The daily run. Posts only on a rebalance. |
| `python momentum_bot.py --status` | What am I holding, and since when. |
| `python momentum_bot.py --dry` | Decide and print. Posts nothing, saves nothing. |
| `python momentum_bot.py --force` | Rebalance now, ignoring the date. |

`--force` is for recovering after an outage, not for trading more often. Monthly
rebalancing is part of what was tested; rebalancing on impulse is not.

## Files it writes

- `state.json` — current basket and the month it was set. Delete it to start
  over; the next run then treats every position as a fresh buy.
- `rebalances.csv` — one row per rebalance: date, buys, sells, resulting basket.
  This is your audit trail. Keep it — it is how you will later tell whether live
  results match the backtest.

Both are gitignored.

## When it fails

- **`only N usable tickers — aborting`** — the data download came back short.
  The script refuses to rank a broken universe rather than post a wrong basket.
  Re-run; if it persists, `yfinance` likely needs upgrading.
- **`discord rejected the post (401)`** — webhook URL is wrong or was deleted.
- **Nothing arrives on the 1st** — check `cron.log`. A cron job with no
  `DISCORD_WEBHOOK` in its environment prints the message instead of posting it.
- **Message arrives but the ranks differ from TradingView** — expected, slightly.
  TradingView and Yahoo adjust for dividends differently. Order changes of one
  or two places near the cutoff are normal; the eighth and ninth name are close
  to a coin flip either way. Wholesale disagreement is not — investigate that.

## Editing the universe

Don't. `UNIVERSE`, `LOOKBACK`, `SKIP` and `HOLD` are frozen at the values that
were validated. Changing them makes the measured results in `../README.md`
describe something other than what you are running.
