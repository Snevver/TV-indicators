# The dashboard

A single page on the mini PC showing where the account stands, how it has moved,
and what the strategy is doing — plus a settings page so Trading 212 can be
configured without SSH.

It reads the bot's files and shells out to the bot for anything live. It never
imports `momentum_bot`, because that module reads its whole configuration at
import time; a long-lived process that imported it would serve stale settings
forever after you changed one.

## Install

```bash
cd ~/tv-indicators && git pull
cd stock-momentum/bot && .venv/bin/pip install flask

cd ../web
../bot/.venv/bin/python app.py --set-password        # at least 8 characters
```

Then run it under systemd so it comes back after a reboot:

```bash
mkdir -p ~/.config/momentum && chmod 700 ~/.config/momentum
sudo cp systemd/momentum-web.service /etc/systemd/system/
sudo sed -i "s/CHANGEME/$USER/g" /etc/systemd/system/momentum-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now momentum-web
systemctl status momentum-web --no-pager
```

The `mkdir` matters: the service declares that directory writable, and systemd
refuses to start a unit whose `ReadWritePaths` does not exist. The unit marks it
optional so a missing one is survivable, but creating it up front avoids the
whole question.

Open **http://192.168.2.37:6767**.

To try it without systemd first: `../bot/.venv/bin/python app.py`.

## The interface

The dashboard is a Vue 3 app built with Vite, using TradingView's
`lightweight-charts` for every time series. **The built bundle is committed** to
`static/dist/`, so the mini PC needs no Node and deployment stays a pull and a
restart.

Only the login page is still server-rendered. That is deliberate: the password
form should not live inside a JavaScript bundle, and an unauthenticated visitor
never downloads the app at all.

To change the interface you need Node 20+ locally:

```bash
cd stock-momentum/web/ui
npm install
npm run dev            # http://localhost:5173, proxied API calls need the Flask app running
npm run build          # writes ../static/dist — commit the result
```

## After a git pull

```bash
sudo systemctl restart momentum-web
```

Templates and Python are loaded once at startup — outside debug mode Flask does
not watch them — so a pull without a restart leaves the old page being served.
The bot needs no restart: it is a fresh process on every timer run.

## Read this before you expose it

**This is plain HTTP.** The password, your holdings and everything else cross
your LAN unencrypted. That is a reasonable trade on a home network and a bad one
anywhere else.

**Do not forward port 6767 to the internet.** Not with a stronger password, not
"just for a minute". If you need it from outside, use a VPN or an SSH tunnel:

```bash
ssh -L 6767:localhost:6767 snevver@192.168.2.37
```

then browse to `http://localhost:6767` on your laptop.

To keep it off the LAN entirely, set `MOMENTUM_WEB_HOST=127.0.0.1` in
`/etc/momentum-bot.env` and reach it only through that tunnel.

Five wrong passwords from one address locks it out for fifteen minutes. The
lockout lives in memory, so restarting the service clears it — which is also how
you rescue yourself if you lock yourself out.

## Settings, and where they are written

The page writes `~/.config/momentum/momentum.env` at mode 600. It never writes
`/etc/momentum-bot.env`: `/etc` is root-owned, so a process running as you can
overwrite that file but cannot create a temp file beside it, and a half-written
env file is a bot that will not start.

Both files are read by the bot and by this service, `/etc` first, so **anything
set in the browser wins** over what you set over SSH.

**Secrets are write-only.** The API key and webhook are never sent back to the
page. A stored one shows as `stored · ···4f2a`; leaving the field blank keeps it,
and a "Remove it" checkbox deletes it. Verified: the key appears in zero rendered
pages.

Changes apply to the next bot run. Nothing needs restarting — the dashboard runs
the bot as a fresh process every time, so it picks up whatever the files say.

## Simulate

`/simulate` runs the same rules over any past window and charts it against
holding all forty and against the index. Pick a start, an end and a budget, or
use a preset.

The engine in `simulate.py` copies its constants and its ranking from
`research/timelines.py` rather than re-deriving them — a re-derivation that
drifted by a day would quietly make the page lie. Checked against the published
figures: 2026 year to date returns +40.86% with a 12.68% worst fall, and the
full history returns $36,074 from $1,000 with a 59.7% drawdown, both matching
the report.

It reads `_data-export/data/`, which ships in the repo. A cold parse of that
45MB export takes about twelve seconds, so it is warmed in a background thread
at startup and every simulation after that takes about a second.

## The two accounts

A switch at the top of the dashboard flips the account-specific panels between
them; the **Money over time** chart shows both.

- **Demo** — the practice account. The bot trades it automatically every month
  (fake money, no approval), so it is a real-execution preview of live.
- **Live** — the real account. The bot places the same orders only after you
  approve them in Discord.

Keeping both is the point: the gap between the two curves is your execution —
slippage, currency fees, an order placed late or skipped.

The **Money over time** chart draws each book's value (cash plus holdings, not
the whole Trading 212 account) against what the same deposits would be worth in a
broad-market ETF, from `bot/hourly.csv` (written hourly by `bot/tracker.py`).

## Where the numbers come from

| Shown | Source |
|---|---|
| Account, holdings, ranking | `bot/latest.json`, rewritten on every bot run |
| The daily curves | `bot/history.csv`, one row per day per funded track |
| Money over time | `bot/hourly.csv`, one row per account per hour (`tracker.py`) |
| Candlestick / detailed line | `bot/samples_1m.csv`, one 1-min OHLC bar for the live account (`pulse.py` samples every ~10s); bucketed up to the chosen timeframe on read |
| Rebalances | `bot/rebalances.csv` |
| Everything else | `bot/state.json` |

Pages render from those files, so they load instantly and never wait on a price
download. **Refresh prices** runs the bot with `--json` to update them.

The curves start the day you install this — nothing is backfilled. The bot only
recorded value at monthly rebalances before, so the first few weeks will be
sparse.

## When it misbehaves

- **"No password has been set yet"** — run `app.py --set-password`.
- **Locked out** — `sudo systemctl restart momentum-web` clears the lockout.
- **Everything says "Nothing recorded yet"** — the bot has not run since the book
  was funded. Press **Dry run**; if that works, wait for the 21:00 timer.
- **An action returns a traceback** — that is the bot's real output, not the
  dashboard failing. The commonest cause is a price download that timed out.
- **Actions fail with "no interpreter"** — the venv is missing. Rebuild it:
  `cd ../bot && python3 -m venv .venv && .venv/bin/pip install yfinance pandas requests flask`.
- **`ProtectSystem=strict` errors in the journal** — you cloned somewhere other
  than `~/tv-indicators`. Fix the `ReadWritePaths` lines in the installed unit.
- **The page looks unchanged after a pull** — restart the service; see above.
- **Fonts look generic** — the page asks the *browser* for Chakra Petch and
  JetBrains Mono, so it needs internet on the device you are viewing from, not on
  the mini PC. Without it everything falls back to the system stack and the
  layout is unaffected.
- **"UI not built"** — `static/dist` is missing. Pull again, or build it with
  `cd ui && npm install && npm run build`.

## Files

| File | What it is |
|---|---|
| `app.py` | Routes, login, config writes, the action runner |
| `data.py` | Reads the bot's files. Tolerates every one of them being missing |
| `simulate.py` | The backtest behind `/simulate`, reading the repo's price export |
| `config.py` | Allowlist, validation, the atomic 600 write |
| `ui/` | Vue source. Only needed to change the interface |
| `static/dist/` | The built bundle, committed so no Node is needed to deploy |
| `templates/login.html` | The one server-rendered page |
| `auth.json` | Password hash and session secret, mode 600, gitignored |
