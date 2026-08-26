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

## The two books

A switch at the top of the dashboard flips everything between them.

- **Paper** — the strategy simulated on assumed fills. It runs whatever else
  happens and is never touched by the broker.
- **Trading 212** — what the broker actually holds, once a key is set.

Keeping both is the point: the gap between them is your execution — slippage,
currency fees, an order placed late or skipped. With only one number you cannot
tell a bad month from a badly executed one.

`MOMENTUM_TRACK` (the "Trading" setting) decides which book the bot plans orders
from. Switch it to live only once **Compare with broker** shows the live book
matching Trading 212, or the bot will tell you to buy things you already own.

## Where the numbers come from

| Shown | Source |
|---|---|
| Account, holdings, ranking | `bot/latest.json`, rewritten on every bot run |
| The curves | `bot/history.csv`, one row per day per funded track |
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

## Files

| File | What it is |
|---|---|
| `app.py` | Routes, login, config writes, the action runner |
| `data.py` | Reads the bot's files. Tolerates every one of them being missing |
| `config.py` | Allowlist, validation, the atomic 600 write |
| `charts.py` | Server-rendered SVG. No chart library, no CDN |
| `templates/`, `static/` | The page itself |
| `auth.json` | Password hash and session secret, mode 600, gitignored |
