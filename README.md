# Stock Momentum

One strategy, traded live, with the code that measured it and the machine that
runs it.

**Monthly cross-sectional momentum across 40 US mega-caps:** rank by six-month
return ending a month ago, hold the top eight equally weighted, re-rank on the
first trading day of each month. Sell what dropped out, buy what came in —
typically one to four changes.

A bot on a mini PC does the ranking every weeknight, runs the strategy on a
Trading 212 **demo** account automatically, and posts the **live** account's
orders to Discord for you to approve with a ✅. A local dashboard shows where
both accounts stand.

---

## Contents

- [The strategy](#the-strategy)
- [Results](#results)
- [The risk](#the-risk)
- [How it trades — the monthly routine](#how-it-trades--the-monthly-routine)
- [Running it: the bot](#running-it-the-bot)
- [Running it: the dashboard](#running-it-the-dashboard)
- [Trading 212 details](#trading-212-details)
- [Telling it about your money](#telling-it-about-your-money)
- [Commands](#commands)
- [Files the bot writes](#files-the-bot-writes)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Repo layout & house rules](#repo-layout--house-rules)
- [The TradingView indicator (optional)](#the-tradingview-indicator-optional)

---

## The strategy

Each month, rank 40 large US stocks by their **6-month return skipping the most
recent month** and hold the strongest **8**, equally weighted — an eighth of the
account in each, always fully invested. There is no stop and no target; the exit
is the ranking.

`UNIVERSE`, `LOOKBACK` (6 months), `SKIP` (1 month) and `HOLD` (8) are frozen at
the values that were validated. Changing them makes the measured results below
describe something other than what you are running.

Two behaviours that used to be settings and are now the only behaviour:

- **Drift, not full re-equalisation.** Only the names that changed get traded;
  survivors are left alone. Drift won seven of eight test windows and the full
  2005–2026 history with a *smaller* worst fall (55.1% vs 59.7%) while placing
  far fewer orders — which on a euro account paying ~0.15% per conversion is
  money too. Its cost is concentration: the largest position ran at a median
  17.6% vs a fixed 12.5%, peaking at 37.8%.
- **Fractional shares.** Trading 212 sells part-shares, so the strategy uses
  them. At €1,000 with whole shares only, six of eight names cost more than a
  slice and the account could not buy them.

---

## Results

Universe and parameters were fixed on 2005–2021. The test era was never
consulted during selection. 10bps turnover cost.

| Era | CAGR | maxDD | Sharpe | Random pick | Edge | SPY | SPY Sharpe |
|---|---|---|---|---|---|---|---|
| TRAIN 2005–2015 | 12.7% | 57.6% | 0.69 | 10.2% | **+2.5%** | 4.9% | 0.42 |
| VAL 2016–2021 | 25.8% | 28.2% | 1.30 | 14.3% | **+11.5%** | 14.4% | 0.99 |
| **TEST 2021–2026** | **25.5%** | **18.7%** | **1.15** | 14.1% | **+11.4%** | 11.9% | 0.79 |

It beat the index on **both return and Sharpe in all three eras**, and beat a
random monthly pick of 8 from the same 40 names at the **100th percentile of 20
draws** in validation and test (85th in training — the era containing the
2008–09 momentum crash).

**Random selection is the control that matters.** It shares the universe, the
concentration and the survivorship bias — so the difference between them is the
ranking and nothing else.

### Why the modest numbers are the credible ones

An earlier version run on all 500 stocks holding the top 2% produced a **52-point
annual edge**. That is not real: its holdings were CVNA, PLTR, SMCI, APP, HOOD —
names that 10–50×'d in 2023–26 and appear in the data *precisely because they are
S&P 500 members today*. In 2021 CVNA nearly went bankrupt. Picking momentum
winners from a list of companies already known to have succeeded is hindsight
with extra steps.

The 40-name mega-cap version reports **5–10 points a year**, which is what the
published momentum literature reports. That agreement is the reason to believe
it. An edge of 50 points would have been a bug — and twice in this research, it
was.

### 2026 year to date, on €3,000

| | Value | Return |
|---|---|---|
| **Strategy, rebalanced monthly** | **€4,222** | **+40.7%** |
| Bought January's 8 and held | €4,512 | +50.4% |
| Bought all 40 equally and held | €3,553 | +18.4% |
| Bought SPY and held | €3,353 | +11.8% |

It beat the index by €869 over eight months, and *lost* €290 against simply
holding January's picks — over this window the initial selection did the work
and the monthly churn diluted it slightly. One 8-month sample is not evidence
that rebalancing is wrong (over 21 years it is what generates the edge), but it
is worth seeing rather than being told about. FX is ignored: the stocks are USD
and the account is euro, so a real result also moves with EUR/USD.

---

## The risk

**Momentum crashes.** In 2008–09 this drew down **55.7%**, and in 2009 alone it
underperformed a random pick by **42 points** as beaten-down names exploded
upward. That is the documented failure mode of momentum, not a defect in this
implementation, and **no stop-loss fixes it** — the damage happens through the
monthly rebalance, not intraday. A stop sells the position and you still hold it
on paper until month-end.

Size accordingly. This is a concentrated equity portfolio, not a hedge.

### Survivorship bias, stated as a number

The 40 names were chosen in 2026, so the whole history knows which companies
survived. Absolute returns are flattered; the **edge over a random pick from the
same 40** is the trustworthy figure, since both arms carry the bias. Mega-caps
already large in 2005 distort far less than small names that later grew tenfold,
which is why the universe is defined by liquidity and data length rather than by
picking winners. The index is the only fully honest benchmark on the page.

---

## How it trades — the monthly routine

The nightly job runs the strategy on **both** Trading 212 accounts, `--env demo`
then `--env live`:

| Account | What happens |
|---|---|
| **demo** | Traded automatically. Fake money, nothing to approve — the batch is placed and settled in the same run and a record is posted to the demo Discord channel. It is a real-execution preview of what live will do. |
| **live** | An approval card with ✅ / ❌ is posted to Discord. **Nothing is sent** and the month is not marked done until you react. |

There is no "automatic trading" switch any more — `AUTOTRADE` is always on, and
live always goes through your ✅. The only thing that stops live trading is the
[kill switch](#the-kill-switch).

### Rebalance day

1. **21:00 Amsterdam**, first trading day of the month. The bot ranks the 40,
   takes the top 8, works out the orders (sells that left the basket, buys that
   entered, plus this month's contribution spread over the whole basket) and
   posts them. For live it is an approval card; for demo it is a record and the
   orders are already placed.
2. **You react on the live card.** ✅ places it, ❌ skips the month. Only your
   Discord user id counts — a checkmark from anyone else is ignored out loud.
3. **Within about a minute** the poller (`--poll`, the `momentum-smoke` timer)
   sees the reaction and sends the orders: **every sell first, then every buy**,
   because the sells pay for the buys. It posts back what went out.
4. **Only then** does the book move and the month count as rebalanced.

Ignore the card and it expires after six hours, having ordered nothing. React ❌
and the month is skipped and not offered again (`--force` if you change your
mind). The ✅/❌ prompt **deletes itself** once answered; the permanent
*placed / skipped / expired* record goes to a second channel
(`DISCORD_CONFIRM_CHANNEL_ID`; unset means both in one channel).

Names that stayed in the top 8 are **not** mentioned. Letting winners run is the
strategy — trimming them back to equal slices measured worse over 21 years.

### The one-hour window

The US close is 22:00 Amsterdam and the strategy was measured buying at that
close, so the useful window to approve is **21:00–22:00 on a weekday evening on
the first trading day of the month**. Miss it and live fills at a different price
than the one measured — not fatal once. If you are never free then, the strategy
will drift from the measured version; decide this before you fund it.

The nightly unit fires **twice**, 21:00 and 22:30 CE(S)T. Whichever run first
sees a daily bar dated in the new month records the rebalance; the other becomes
a no-op. The bot decides from the newest *daily bar* and its own state, never
the wall clock — so weekends, holidays, your timezone and a night the machine
was off all take care of themselves.

### If nothing changed

Some months the top 8 is the same as last month. Then there is nothing to sell
and nothing to buy except this month's contribution, spread across the eight you
already hold.

### The kill switch

**Settings → Kill switch → on** (the browser asks you to confirm), or `--kill`
on the box (always the live account). It sells every strategy position at market
immediately, drops the book to cash, and refuses to propose or place anything
until you press **Resume trading**. It runs whether or not it is a rebalance day
and is independent of everything else. Pies and holdings outside the 40 names are
never touched. The poller re-fires it within a minute if the first attempt
failed. A sell that fails is reported, not retried into a halt — close those by
hand. After you resume, the next rebalance opens fresh from the proceeds.

### What the automation refuses to do

- **Sell what you do not hold.** Before every sell it asks Trading 212 what is
  actually there and sells that. If the broker shows nothing, the sell is
  skipped rather than opening a short.
- **Send the same order twice.** Each order is written to disk as *sending*
  before the request goes out. Killed halfway through, the next run resumes at
  the order after the last confirmed one. If it died *during* an order (or the
  network failed, which looks the same), that order's fate is unknown, so the
  batch stops dead and waits for you. Never retried.
- **Carry on after a surprise.** Anything unexpected halts the whole batch,
  because the cash for the buys depends on the sells ahead of them.
  `--pending-status` shows what was sent; `--pending-resume` continues,
  `--pending-abandon` records what went through and closes the month there.
- **Trade the demo book against reality, or skip your ✅ on live.**

### Before you rely on it

Do the smoke test (`--smoke-offer`, then ✅ and ❌ in Discord) so you have seen a
real order placed and closed by reaction. Then watch a full live month go
through. The demo account running in parallel is the ongoing check that
execution still works.

---

## Running it: the bot

Runs on any machine awake once a day — a mini PC, a Raspberry Pi, a VPS.

### Install (Ubuntu, over SSH)

Modern Ubuntu refuses `pip install` outside a virtualenv, so make one:

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/Snevver/tv-indicators.git
cd tv-indicators/stock-momentum/bot
python3 -m venv .venv
.venv/bin/pip install -q yfinance pandas requests flask
```

### Secrets — `/etc/momentum-bot.env`

Put them in a root-owned mode-600 file, never in the crontab or a unit file
(both readable by every user on the box):

```bash
sudo install -m 600 -o "$USER" /dev/null /etc/momentum-bot.env
sudo tee /etc/momentum-bot.env >/dev/null <<'EOF'
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
DISCORD_OWNER_ID=...            # your user id — only this ✅ counts
# DISCORD_CONFIRM_CHANNEL_ID=...       # optional: live placed/skipped/expired records
# DISCORD_CONFIRM_CHANNEL_ID_DEMO=...  # optional: demo records; unset = live records channel
T212_API_KEY_DEMO=...     T212_API_SECRET_DEMO=...
T212_API_KEY_LIVE=...     T212_API_SECRET_LIVE=...
# MOMENTUM_WEB_HOST=127.0.0.1   # optional: keep the dashboard off the LAN
EOF
```

Practice and live are **separate Trading 212 keys with separate URLs**; each
nightly run picks its pair from `--env`. A plain `T212_API_KEY` / `T212_API_SECRET`
still works if you only have one account. The keys and the webhook are passwords
— if one leaks, revoke it in the app and generate another.

`T212_ENV` and `MOMENTUM_AUTOTRADE` lines are inert — the bot trades both
accounts every month, so there is no account to pick and nothing to switch off.

### Settings — the dashboard, or `~/.config/momentum/momentum.env`

Three editable settings, written by the Settings page at mode 600 (or by hand):

| Setting | Env var | Meaning |
|---|---|---|
| Starting amount | `MOMENTUM_START_BUDGET` | What the strategy opens with, drawn from Trading 212 free funds on the **first** rebalance. Applied once; after `deposited` is set, changing it does nothing — use `--deposit` for a later top-up. Default `0`. |
| Monthly contribution | `MOMENTUM_MONTHLY` | Added on **every rebalance after the first**, drawn from free funds and spread over the whole new basket. Default `0` (off). |
| Kill switch | `MOMENTUM_KILL` | `on` arms it (see above). A button, not a field. |

Both env files are read, `/etc/momentum-bot.env` first, then
`~/.config/momentum/momentum.env` — **the second wins**, matching how systemd
applies `EnvironmentFile`. The bot loads both itself, so no `set -a` is needed at
a shell. An exported variable still beats both files
(`T212_ENV=demo python3 momentum_bot.py --t212-probe` for a one-off).

The monthly €100 can come from a bank standing order landing a few days before
the 1st **or** from the balance you already hold — **not both**, or the extra
piles up untouched. If a standing order bounces the tail order trims itself to
what was really there; correct the rest with `--fill TICKER=-SHARES@PRICE` and
set Monthly to `0` until it is reliable.

`deposited` rises by the starting amount and each contribution, so growth is
`total ÷ deposited − 1` and your own money is never read as profit.

### systemd (preferred)

```bash
cd ~/tv-indicators/stock-momentum/bot/systemd
sudo cp momentum-{bot,smoke,tracker,pulse,live}.{service,timer} /etc/systemd/system/
sudo sed -i "s/CHANGEME/$USER/g" \
        /etc/systemd/system/momentum-{bot,smoke,tracker,pulse,live}.service
sudo systemctl daemon-reload
sudo systemctl enable --now \
        momentum-{bot,smoke,tracker,pulse,live}.timer
```

| Unit | Cadence | Job |
|---|---|---|
| `momentum-bot` | Mon–Fri 21:00 & 22:30 | The monthly rebalance, `--env demo` then `--env live`. A no-op on days with nothing to do. |
| `momentum-smoke` | every minute | `--poll --env live` — acts on your ✅ / ❌, and on the smoke test. Reads two small files and exits when nothing is pending. |
| `momentum-live` | every ~90s | `--refresh-live` for demo and live — a cheap `latest.json` refresh (Trading 212 read only, no price download) so the dashboard's header figure moves between nightly runs. |
| `momentum-tracker` | hourly | `tracker.py` — values each book (cash + shares × latest price, the strategy's slice, not the whole account) and the benchmark ETF (`MOMENTUM_BENCH_TICKER`, default `SXR8.DE`) into `hourly.csv`. yfinance only, no broker call. |
| `momentum-pulse` | every minute | `pulse.py` — samples the **live** account's open profit/loss (Trading 212 `ppl`, in euros) every ~10s and writes one 1-minute OHLC bar to `samples_1m.csv` for the candlestick chart. Live only. |

Edit the copies in `/etc`, not the checkout, or the next `git pull` conflicts.
The shipped `momentum-live.service` runs `--refresh-live --env demo` only — add
a second `ExecStart=` line with `--env live` so the live header stays fresh.

Inspect:

```bash
systemctl list-timers 'momentum-*'
sudo systemctl start momentum-bot.service     # run it now
journalctl -u momentum-bot.service -n 50
```

### cron (simpler alternative)

```cron
0 21 * * 1-5 cd ~/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python momentum_bot.py --env demo >> cron.log 2>&1 && .venv/bin/python momentum_bot.py --env live >> cron.log 2>&1
30 22 * * 1-5 cd ~/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python momentum_bot.py --env demo >> cron.log 2>&1 && .venv/bin/python momentum_bot.py --env live >> cron.log 2>&1
* * * * * cd ~/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python momentum_bot.py --poll --env live >> cron.log 2>&1
0 * * * * cd ~/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python tracker.py >> cron.log 2>&1
```

The first (cold-start) run has no history, so it treats the whole basket as new
buys and posts immediately whatever the date — that is your starting position.
After that it only speaks on the first trading day of each month.

---

## Running it: the dashboard

A single Vue page on the mini PC — holdings, curves, the candlestick chart, the
live ranking, and a Settings page so Trading 212 can be configured without SSH.
It reads the bot's files and shells out to the bot for anything live; it never
imports `momentum_bot` (that module reads its whole config at import, so a
long-lived process that imported it would serve stale settings forever).

### Install

```bash
cd ~/tv-indicators && git pull
cd stock-momentum/web
../bot/.venv/bin/python app.py --set-password        # at least 8 characters

mkdir -p ~/.config/momentum && chmod 700 ~/.config/momentum
sudo cp systemd/momentum-web.service /etc/systemd/system/
sudo sed -i "s/CHANGEME/$USER/g" /etc/systemd/system/momentum-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now momentum-web
```

Open **http://<mini-pc-ip>:6767**. To try it without systemd: `app.py` on its own.

The `mkdir` matters — the unit declares that directory writable and systemd
refuses to start a unit whose `ReadWritePaths` does not exist.

### After a git pull

```bash
sudo systemctl restart momentum-web
```

Templates and Python load once at startup, so a pull without a restart serves
the old page. **The built Vue bundle is committed** to `web/static/dist/`, so the
mini PC needs no Node — deploy is a pull and a restart. The bot needs no restart:
it is a fresh process on every timer run.

### Access & security

- **Plain HTTP.** The password and your holdings cross the LAN unencrypted —
  fine on a home network, bad anywhere else.
- **Do not forward port 6767 to the internet.** Reach it from outside with a VPN
  or SSH tunnel: `ssh -L 6767:localhost:6767 you@mini-pc`, then browse
  `http://localhost:6767`. Set `MOMENTUM_WEB_HOST=127.0.0.1` to keep it off the
  LAN entirely.
- Five wrong passwords from one address → 15-minute lockout, held in memory, so
  `sudo systemctl restart momentum-web` clears it (also how you rescue yourself).

### Settings page

Writes `~/.config/momentum/momentum.env` at mode 600, never `/etc`. **Secrets are
write-only** — a stored key shows as `stored · ···4f2a`; blank keeps it, a
"Remove it" checkbox deletes it. Changes apply to the next bot run; nothing needs
restarting.

### Simulate

`/simulate` runs the same rules over any past window against holding all 40 and
against the index. It reads `_data-export/data/` (ships in the repo); a cold
parse of that ~45MB export takes ~12s and is warmed in a background thread at
startup, so each run after is ~1s. `simulate.py` copies its constants and
ranking from `research/timelines.py` rather than re-deriving them.

### Where the dashboard's numbers come from

| Shown | Source |
|---|---|
| Account, holdings, ranking, header total | `bot/latest.json`, rewritten every bot run (and every ~90s by `--refresh-live`) |
| Daily curves | `bot/history.csv`, one row per day per funded track |
| "You vs the S&P 500" line context | `bot/hourly.csv`, one row per account per hour (`tracker.py`) |
| Candlestick chart (P/L) | `bot/samples_1m.csv` — 1-min OHLC bars of the live account's open profit/loss (`pulse.py`, ~10s samples), bucketed to the chosen timeframe. It is P/L not capital, so a monthly contribution doesn't put a step in it. No older data folded in: the chart starts where clean sampling started. |
| Rebalance log | `bot/rebalances.csv` |
| Everything else | `bot/state.json` |

Pages render from those files, so they load instantly. The curves start the day
you install this — nothing is backfilled.

---

## Trading 212 details

The bot works without Trading 212 and always will — leave the keys unset and
there are no calls, no warnings, no mention of it. With keys set, it reads your
real positions and cash instead of assuming its own fills.

### Why there is no pie

`/equity/portfolio` returns the **whole account**, so anything else you hold gets
read as if the strategy bought it (a test run once reported $2,334 against the
strategy's real $1,122). A pie cannot fence it off: **nothing can put money into
a pie** (the endpoints create/read/update/duplicate/delete; update sets target
weights and does not trade, and a pie cannot hold uninvested cash), and the
**pie API is deprecated**.

So the strategy trades in the ordinary portfolio and `positions()` scopes itself
with two filters: **non-pie quantity only** (a pie holding a universe name would
otherwise make the bot think it already owns it), and **universe members only**
(drops hand-bought positions in anything else). What it *cannot* separate is a
universe name bought by hand outside a pie — keep discretionary buys inside a
pie, or outside the 40 names.

### Instrument resolution

`--t212-instruments` resolves every universe ticker to the broker's instrument
code, from Trading 212's own ~16k-row list (cached a day in `instruments.json`;
delete it to refresh). It matches on `shortName`, holds candidates to type STOCK
priced in USD (what the backtest priced — European listings share the ISIN but
trade in another currency), and **refuses to choose when a name is ambiguous**
rather than guessing. `--t212-find TEXT` searches the same list.

**One override:** Trading 212 lists Booking Holdings under the old `PCLN_US_EQ`
(the PCLN → BKNG rename in Feb 2018; same ISIN `US09857L1089`). It is in
`RENAMES` in `t212.py` and printed with its ISIN rather than applied silently.
BKNG is top-eight in 98 of 252 backtested months — dropping it costs ~21% over
the full history.

### Keys & first check

Trading 212 app → Settings → API → Generate API key, with **portfolio, history
and Orders-Execute** permissions.

```bash
set -a; . /etc/momentum-bot.env; set +a
python momentum_bot.py --t212-probe    # does the key work, what comes back
python momentum_bot.py --t212-check    # broker vs the book, changes nothing
python momentum_bot.py --t212-sync     # adopt the broker's positions and cash
```

The field names in `t212.py` were written from public documentation, not against
a live account; `--t212-probe` is the step that settles them.

### What it will not do

- **Overwrite what you paid in.** The broker cannot tell a deposit from a
  profit, so `deposited` is only ever set by `--deposit` / `--withdraw`.
- **Erase the book because the broker said nothing.** Zero positions reported
  while the book holds eight is treated as a fault and refused — far more often a
  permissions or field-mapping problem than a portfolio you emptied. `--t212-sync
  --force` says you really did sell everything.

### If it fails

It falls back to the bot's own book and prints one line saying why. The rebalance
message still goes out. **401** — wrong key or the demo/live pair swapped.
**403** — the key lacks portfolio/history permission. **429** — rate limited; it
backs off and retries, so do not loop `--t212-probe`. **"none could be read"** —
the JSON field names differ from what the code expects; run `--t212-probe`.

---

## Telling it about your money

The bot keeps its own book. Fund it once:

```bash
python momentum_bot.py --deposit 1000
```

`--deposit` and `--withdraw` are how you tell it about money moving in or out, so
that adding €500 does not read as a €500 gain.

When it tells you to rebalance it assumes you filled at that day's closing price
and records the resulting share counts and cost basis; every later run marks that
book to the current market. **It is a model, not the truth.** If a fill differed:

```bash
python momentum_bot.py --fill JNJ=0.6@233.50      # bought 0.6 at 233.50
python momentum_bot.py --fill MU=-0.15@831.00     # a sale it does not know about
```

With live Trading 212 keys the bot reads real fills and `--fill` is rarely
needed. If you never bother, the numbers stay close and drift slowly — check them
against the broker every few months.

---

## Commands

```bash
python momentum_bot.py           # the daily run; posts only on a rebalance
```

| Command | What it does |
|---|---|
| `--status` | Holdings, weights, cash, profit and loss |
| `--report` | Post that snapshot to Discord |
| `--json` / `--refresh-live` | Rewrite `latest.json` for the dashboard (full / cheap) |
| `--deposit N` / `--withdraw N` | Record money paid in / taken out |
| `--fill TICKER=SHARES@PRICE` | Correct one assumed fill |
| `--dry` | Decide and print; saves nothing, posts nothing |
| `--test` | Post today's real ranking to Discord; saves nothing |
| `--force` | Rebalance now, ignoring the date — for recovering after an outage, not for trading more often |
| `--poll --env live` | Act on a Discord ✅ / ❌ (what `momentum-smoke` runs) |
| `--pending-status` | This month's orders and what happened to each |
| `--pending-resume` / `--pending-abandon` / `--pending-cancel` | Recover a half-executed or unwanted batch |
| `--kill` | Arm the kill switch (live) |
| `--t212-probe` / `--t212-check` / `--t212-sync` / `--t212-find` / `--t212-instruments` | Trading 212 introspection; only `--t212-sync` changes anything |
| `--smoke-offer` / `--smoke-poll` / `--smoke-status` | The end-to-end order test |

`--env demo|live` selects the account for any command; default is **live**.

---

## Files the bot writes

All in `stock-momentum/bot/`, all gitignored — this machine's, not the repo's.

| File | What it is |
|---|---|
| `state.json` | The basket, the month it was set, and the book per track: share counts, cost basis, cash, everything paid in, banked P&L. Deleting it starts over. **Back it up rather than deleting it.** |
| `rebalances.csv` | One row per rebalance per track (date, buys, sells, basket, account value, cash, paid in, P&L, track). Your audit trail. |
| `deposits.csv` | Dated cash-in events, per track. |
| `latest.json` | The dashboard's render cache: current holdings, ranking, header figures. |
| `history.csv` | One row per day per funded track — the daily curves. |
| `hourly.csv` | One row per account per hour — value + benchmark ETF (`tracker.py`). |
| `samples_1m.csv` | 1-minute OHLC bars of the live account's open P/L in euros (`pulse.py`), append-only, kept indefinitely — the candlestick chart. |
| `model.csv` | The frozen backtest run forward from the funding date, rewritten every `--json` run. |
| `instruments.json` | Cached Trading 212 instrument list (~16k rows), refreshed daily. |
| `pending.json` / `pending-demo.json` | The month's batch mid-flight — what was sent and what came back. |

---

## Troubleshooting

**Bot**

- **`only N usable tickers — aborting`** — the data download came back short. The
  script refuses to rank a broken universe. Re-run; if it persists, upgrade
  `yfinance`.
- **`discord rejected the post (401)`** — the webhook URL is wrong or was deleted.
- **Nothing arrives on the 1st** — check `journalctl -u momentum-bot.service` (or
  `cron.log`). A job with no `DISCORD_WEBHOOK` in its environment prints the
  message instead of posting it, which looks like success in the log.
- **`error: externally-managed-environment`** — you ran `pip` outside the venv.
  Use `.venv/bin/pip`.
- **Works by hand, silent from the timer** — almost always the environment.
  `sudo systemctl start momentum-bot.service` then read the journal; an
  `EnvironmentFile` that does not exist makes the unit fail before Python runs.
- **`--status` says $0.00 with positions** — you never ran `--deposit`, so every
  percentage is measured against zero.
- **The account figure disagrees with the broker by a lot** — usually an order
  you did not place, or one you placed twice. Small drift is expected (the bot
  assumes it filled at the close); correct it with `--fill`.
- **Ranks differ slightly from TradingView** — expected. TradingView and Yahoo
  adjust for dividends differently; the 8th and 9th name are close to a coin
  flip. Wholesale disagreement is not — investigate that.

**Dashboard**

- **"No password has been set yet"** — `app.py --set-password`.
- **Locked out** — `sudo systemctl restart momentum-web`.
- **Everything says "Nothing recorded yet"** — the bot has not run since the book
  was funded. Press **Dry run**; if that works, wait for the 21:00 timer.
- **An action returns a traceback** — that is the bot's real output. Commonest
  cause is a price download that timed out.
- **Actions fail with "no interpreter"** — rebuild the venv:
  `cd ../bot && python3 -m venv .venv && .venv/bin/pip install yfinance pandas requests flask`.
- **`ProtectSystem=strict` errors in the journal** — you cloned somewhere other
  than `~/tv-indicators`. Fix the `ReadWritePaths` lines in the installed unit.
- **Page looks unchanged after a pull** — restart the service.
- **"UI not built"** — `web/static/dist` is missing. Pull again, or build it
  (`cd web/ui && npm install && npm run build`).

---

## Tests

```bash
python stock-momentum/run_tests.py     # everything, bot/ and web/
python stock-momentum/bot/test_book.py # or one file on its own
```

Plain `assert` scripts, no framework, no network. They cover the money math
(`mark` / `apply_orders` / `plan`, and the identity `total == cash + positions`),
the ranking and `due()`, the `state.json` migration, batch-resume safety,
quantity truncation, the Discord embed shape, settings validation, the candle
bucketer and the paid-in series, and the dashboard's file readers. Run them
before pushing a change to any of that.

To change the dashboard UI you need Node 20+ locally:

```bash
cd stock-momentum/web/ui
npm install
npm run dev     # http://localhost:5173, needs the Flask app running for API calls
npm run build   # writes ../static/dist — commit the result
```

---

## Repo layout & house rules

| Folder | What it is |
|---|---|
| `stock-momentum/bot/` | The live bot, its systemd units, and `tracker.py` / `pulse.py`. |
| `stock-momentum/web/` | The dashboard (Flask + Vue). Built bundle committed. |
| `stock-momentum/research/` | The backtests behind every number quoted here. |
| `stock-momentum/indicators/` | The TradingView Pine version. The bot does not depend on it. |
| `_data-export/` | Daily OHLCV export the research scripts read — its own [README](_data-export/README.md). Claude's sandbox cannot reach market-data hosts, so you fetch and push, it pulls. |

**Measured results, or it does not ship.** A rule never backtested against costs
is a hypothesis. `research/` carries the code that produced every figure here, so
any claim can be re-run rather than taken on trust. Results quoted are
out-of-sample, from slices held back from the search.

**No secrets in git.** The Discord webhook, the Trading 212 keys and the
dashboard password live in mode-600 files on the machine that runs the bot.
`state.json`, `history.csv` and the rest of the local run state are gitignored
for the same reason.

**No large price data in git.** Daily CSVs are kept because the research needs
them; intraday bars run to hundreds of megabytes and are rebuildable from
`_data-export/export_for_claude.py`.

This repo used to hold four indicators. The other three — an ETF rotation, a
wickless-candle retest and a mean-reversion family — were removed once this one
was the only one being traded. They are in the git history if wanted back.

---

## The TradingView indicator (optional)

`stock-momentum/indicators/stock-momentum.pine` — put it on any of the 40 names
and it shows BUY/SELL labels on rebalance bars plus the live ranking table. It is
**not** what you are trading: the bot computes the ranking itself from the same
logic the backtest used, so the two cannot drift apart. Delete the indicator and
nothing about the live signal changes. It is also not parser-verified by
TradingView.

If you pay for TradingView you can get the Discord alerts from it instead of the
bot: add an alert on any chart with the indicator, condition **Any alert()
function call**, **Once Per Bar Close**, tick **Webhook URL** and paste your
Discord webhook, leave the message box **empty** (the script writes the JSON —
Discord rejects plain text). One alert covers all 40 names; it fires on the first
bar of each month and only when the basket changes. Webhooks are **paid-plan
only** — on the free tier the alert fires but does not POST. Running both the
bot and the TradingView alert is fine and gives you a cross-check.
