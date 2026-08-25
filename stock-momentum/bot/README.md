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
EOF
```

Mode 600 owned by you: you and root can read it, nobody else. Owning it matters
only so you can source it by hand to test — systemd reads `EnvironmentFile` as
root before it drops to `User=`, so the timer works either way. If you created
the file root-owned and `. /etc/momentum-bot.env` gives *Permission denied*,
`sudo chown "$USER" /etc/momentum-bot.env` fixes it without loosening the mode.

**The webhook URL is a password.** Anyone who has it can post to your channel.
Keep it out of the repo, out of screenshots, and out of chat. If it leaks, delete
the webhook in Discord and make a new one — that instantly invalidates the old
URL.

Check the whole thing works before automating it:

```bash
set -a; . /etc/momentum-bot.env; set +a
.venv/bin/python momentum_bot.py --dry
```

`--dry` ranks, prints, and posts nothing. If the top 12 resembles the
indicator's table on TradingView, you are wired up correctly.

## Running it on a schedule

Two options. Use one.

### systemd timer (preferred on a server)

Logs land in the journal, a missed run catches up on boot, and the secret stays
in a 600 file.

```bash
cd systemd
sed -i "s/CHANGEME/$USER/g" momentum-bot.service     # fix paths if you cloned elsewhere
sudo cp momentum-bot.service momentum-bot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now momentum-bot.timer
```

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
30 22 * * 1-5 cd /home/YOU/tv-indicators/stock-momentum/bot && set -a && . /etc/momentum-bot.env && set +a && .venv/bin/python momentum_bot.py >> cron.log 2>&1
```

Weeknights after the US close. Any evening hour works; the script decides whether
a rebalance is due from the newest *daily bar*, not the wall clock, so weekends,
market holidays, your timezone and a night the machine was off all take care of
themselves. On a day with nothing to do it prints one line and sends nothing.

The first run has no history, so it treats the whole basket as new buys and posts
immediately, whatever the date. That is your starting position. After that it
only speaks on the first trading day of each month.

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
- **Nothing arrives on the 1st** — check `journalctl -u momentum-bot.service`
  (or `cron.log`). A job with no `DISCORD_WEBHOOK` in its environment prints the
  message instead of posting it, which looks like success in the log.
- **`error: externally-managed-environment`** — you ran `pip` outside the venv.
  Use `.venv/bin/pip`, not `pip`.
- **Works by hand, silent from the timer** — almost always the environment.
  `sudo systemctl start momentum-bot.service` then read the journal; an
  `EnvironmentFile` that does not exist makes the unit fail before Python runs.
- **Message arrives but the ranks differ from TradingView** — expected, slightly.
  TradingView and Yahoo adjust for dividends differently. Order changes of one
  or two places near the cutoff are normal; the eighth and ninth name are close
  to a coin flip either way. Wholesale disagreement is not — investigate that.

## Editing the universe

Don't. `UNIVERSE`, `LOOKBACK`, `SKIP` and `HOLD` are frozen at the values that
were validated. Changing them makes the measured results in `../README.md`
describe something other than what you are running.
