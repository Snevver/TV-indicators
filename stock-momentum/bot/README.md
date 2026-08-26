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

## Setup (Ubuntu server, over SSH)

Modern Ubuntu refuses `pip install` outside a virtualenv (`error:
externally-managed-environment`), so make one:

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/Snevver/tv-indicators.git
cd tv-indicators/stock-momentum/bot
python3 -m venv .venv
.venv/bin/pip install -q yfinance pandas requests
```

Put the webhook in a root-owned file rather than in the crontab or a unit file —
both of those are readable by every user on the box:

```bash
sudo install -m 600 -o "$USER" /dev/null /etc/momentum-bot.env
sudo tee /etc/momentum-bot.env >/dev/null <<'EOF'
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
MOMENTUM_CURRENCY=EUR
EOF
```

`MOMENTUM_CURRENCY` is the label on every figure. It does not convert anything.

`MOMENTUM_MIN_ORDER` (default `1`) is optional: don't generate an order below
this, so a rebalance doesn't ask you to trade forty cents of something.

`MOMENTUM_TRACK` (default `paper`) picks which book the bot trades. See
**The two books** in `../web/README.md`.

### Two settings that used to be here

`MOMENTUM_MODE` and `MOMENTUM_FRACTIONAL` are gone. Both were settled by
measurement and are now the only behaviour:

- **Drift**, not full re-equalisation. Only the names that changed get traded;
  survivors are left alone. Drift won seven of eight test windows and won the
  full 2005–2026 history with a *smaller* worst fall (55.1% against 59.7%),
  while placing far fewer orders — which on a euro account paying 0.15% per
  conversion is money as well. Its cost is concentration: the largest position
  ran at a median 17.6% against a fixed 12.5%, peaking at 37.8%.
- **Fractional shares.** Never a performance setting — it described whether the
  broker sells part of a share, and Trading 212 does. At €1,000 with whole
  shares only, six of eight names cost more than a slice and the account could
  not buy them at all.

Leftover lines for either in an env file are inert. **If your broker ever stops
selling part shares**, the unbuyable check that used to warn about this is gone
and would have to come back — nothing flags it now.

## Telling it about your money

The bot has no connection to your broker, so it keeps its own book. Fund it once:

```bash
python momentum_bot.py --deposit 1000
```

From then on every message carries live numbers — what each position is worth,
what it cost, what is still in cash, and the profit or loss on everything you
have paid in. `--deposit` and `--withdraw` are how you tell it about money moving
in or out, so that adding £500 does not read as a £500 gain.

### How it knows what you own

When it tells you to rebalance, it assumes you filled at that day's closing
price and records the resulting share counts and cost basis. Every later run
marks that book to the current market. You do nothing.

**It is a model, not the truth.** If a fill differed, correct it:

```bash
python momentum_bot.py --fill JNJ=0.6@233.50      # you bought 0.6 at 233.50
python momentum_bot.py --fill MU=-0.15@831.00     # a sale it does not know about
```

Repeatable, and the P&L follows. If you never bother, the numbers stay close and
drift slowly. Check them against the broker every few months.

## Trading 212 (optional, off until you turn it on)

The bot works without this and always will. Leave `T212_API_KEY` unset and
nothing below happens — no calls, no warnings, no mention of it in any message.

When you do switch it on, the bot reads your real positions and cash instead of
assuming its own fills, so `--fill` becomes unnecessary and the figures stop
being an estimate.

### Make a pie first

Do this before generating a key. `/equity/portfolio` returns the **whole
account**, so anything else you hold on Trading 212 gets read as if the strategy
had bought it. With an unrelated ETF sitting in the account, a test run reported
$2,334 against the strategy's real $1,122.

Put the eight names in their own pie, then set `T212_PIE_ID`. The bot sees that
pie and nothing else, and its profit and loss measures this strategy alone.

Find the id with `--t212-probe` — it lists your pies with their ids.

### Turning it on

Trading 212 app → Settings → API → Generate API key, with portfolio and history
permissions. Practice and live are **separate keys with separate URLs**; generate
the one for the account you are actually running.

```bash
sudo nano /etc/momentum-bot.env
```
```
T212_API_KEY=...
T212_ENV=demo          # or: live
T212_PIE_ID=9911
```

The key is a password, exactly like the webhook. That file is mode 600 and is
the only place it belongs — never the repo, never a crontab, never a chat
message. If it leaks, revoke it in the app and generate another.

```bash
set -a; . /etc/momentum-bot.env; set +a
python momentum_bot.py --t212-probe    # does the key work, what comes back
python momentum_bot.py --t212-check    # broker against the book, changes nothing
python momentum_bot.py --t212-sync     # adopt the broker's numbers
```

Once it answers, every normal run refreshes from the broker first.

### What it will not do

**Place orders.** Trading 212's public API only accepts orders in practice mode,
and this code never sends one in either environment. You place trades yourself,
which is also the last point at which you get to look at the numbers before
committing to them.

**Overwrite what you paid in.** The broker cannot tell a deposit from a profit,
so `deposited` is only ever set by `--deposit` and `--withdraw`.

**Erase the book because the broker said nothing.** If Trading 212 reports zero
positions while the book holds eight, that is treated as a fault and refused —
an empty or unreadable response is far more often a permissions or field-mapping
problem than a portfolio you emptied by hand. `--t212-sync --force` is how you
say you really did sell everything.

### If it fails

It falls back to the bot's own book and prints one line saying why. A rebalance
message always goes out. Common causes:

- **401** — wrong key, or a live key with `T212_ENV=demo` (or the reverse).
- **403** — the key lacks portfolio or history permission. Re-generate it.
- **429** — rate limited. It backs off and retries; the API is strict, so do not
  loop `--t212-probe`.
- **"none could be read"** — the JSON field names differ from what this code
  expects. Run `--t212-probe` and the mapping can be corrected against the real
  response. Nothing is changed in the meantime.

The field names in `t212.py` were written from public documentation, not against
a live account. `--t212-probe` is the step that settles them.

## Running it on a schedule

Two options. Use one.

### systemd timer (preferred on a server)

Logs land in the journal, a missed run catches up on boot, and the secret stays
in a 600 file.

```bash
sudo cp systemd/momentum-bot.service systemd/momentum-bot.timer /etc/systemd/system/
sudo sed -i "s/CHANGEME/$USER/g" /etc/systemd/system/momentum-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now momentum-bot.timer
```

Substitute in `/etc`, not in the checkout — editing the tracked file makes the
next `git pull` conflict. Adjust the paths in the installed copy by hand if you
cloned somewhere other than `~/tv-indicators`.

Verify and inspect:

```bash
systemctl list-timers momentum-bot.timer     # when does it next fire
sudo systemctl start momentum-bot.service    # run it right now
journalctl -u momentum-bot.service -n 50     # what did it say
```

### cron (simpler)

```bash
crontab -e
```

```cron
0 21 * * 1-5 cd /home/YOU/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python momentum_bot.py >> cron.log 2>&1
30 22 * * 1-5 cd /home/YOU/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python momentum_bot.py >> cron.log 2>&1
```

The timer runs twice a weeknight, at 21:00 and 22:30 CE(S)T.

That is not redundancy for its own sake. The backtest buys at the **close** of
the first trading day of the month, so you want the basket before that close —
21:00 CEST is 15:00 in New York, an hour ahead of it. The 22:30 run is the
fallback for the case where the earlier one has not yet seen a daily bar dated in
the new month. Whichever fires first records the rebalance; the second becomes a
no-op, because the script decides from the newest *daily bar* and its own state,
never the wall clock. That same property means weekends, market holidays, your
timezone and a night the machine was off all take care of themselves.

On a day with nothing to do it prints one line and sends nothing.

The first run has no history, so it treats the whole basket as new buys and posts
immediately, whatever the date. That is your starting position. After that it
only speaks on the first trading day of each month.

## Commands

| Command | What it does |
|---|---|
| `python momentum_bot.py` | The daily run. Posts only on a rebalance. |
| `python momentum_bot.py --status` | Holdings, weights, cash, profit and loss. |
| `python momentum_bot.py --report` | Post that snapshot to Discord. |
| `python momentum_bot.py --deposit 1000` | Record money paid in. |
| `python momentum_bot.py --withdraw 200` | Record money taken out. |
| `python momentum_bot.py --fill MU=0.15@829.50` | Correct an assumed fill. |
| `python momentum_bot.py --t212-probe` | What does Trading 212 return? Read-only. |
| `python momentum_bot.py --t212-check` | Broker against the book. Changes nothing. |
| `python momentum_bot.py --t212-sync` | Adopt the broker's positions and cash. |
| `python momentum_bot.py --dry` | Decide and print. Posts nothing, saves nothing. |
| `python momentum_bot.py --test` | Post today's real ranking to Discord. Saves nothing. |
| `python momentum_bot.py --force` | Rebalance now, ignoring the date. |

`--force` is for recovering after an outage, not for trading more often. Monthly
rebalancing is part of what was tested; rebalancing on impulse is not.

## Files it writes

- `state.json` — the basket, the month it was set, and the book: share counts,
  cost basis, cash, everything paid in, and profit already banked. Deleting it
  starts over — the next run treats every position as a fresh buy and the P&L
  history is gone. Back it up rather than deleting it.
- `rebalances.csv` — one row per rebalance: date, buys, sells, resulting basket,
  account value, cash, paid in, profit and loss. This is your audit trail. Keep
  it — it is how you will later tell whether live results match the backtest.

Both are gitignored.

## When it fails

- **`only N usable tickers — aborting`** — the data download came back short.
  The script refuses to rank a broken universe rather than post a wrong basket.
  Re-run; if it persists, `yfinance` likely needs upgrading.
- **`discord rejected the post (401)`** — webhook URL is wrong or was deleted.
- **Nothing arrives on the 1st** — check `journalctl -u momentum-bot.service`
  (or `cron.log`). A job with no `DISCORD_WEBHOOK` in its environment prints the
  message instead of posting it, which looks like success in the log.
- **`error: externally-managed-environment`** — you ran `pip` outside the venv.
  Use `.venv/bin/pip`, not `pip`.
- **Works by hand, silent from the timer** — almost always the environment.
  `sudo systemctl start momentum-bot.service` then read the journal; an
  `EnvironmentFile` that does not exist makes the unit fail before Python runs.
- **`--status` says $0.00 with positions on the book** — you never ran
  `--deposit`, so the bot has no idea what you paid in and every percentage is
  measured against zero.
- **The account figure disagrees with the broker** — expected to drift, since
  the bot assumes it filled at the close. Correct the difference with `--fill`.
  A large gap usually means an order you did not place, or one you placed twice.
- **Message arrives as plain text, not a coloured card** — you are running an
  older copy. `git pull` and restart nothing; the next run picks it up.
- **Message arrives but the ranks differ from TradingView** — expected, slightly.
  TradingView and Yahoo adjust for dividends differently. Order changes of one
  or two places near the cutoff are normal; the eighth and ninth name are close
  to a coin flip either way. Wholesale disagreement is not — investigate that.

## Editing the universe

Don't. `UNIVERSE`, `LOOKBACK`, `SKIP` and `HOLD` are frozen at the values that
were validated. Changing them makes the measured results in `../README.md`
describe something other than what you are running.
