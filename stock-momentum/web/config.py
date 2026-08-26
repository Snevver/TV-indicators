"""Reading and writing the bot's settings from the browser.

TWO FILES, ON PURPOSE
/etc/momentum-bot.env is where the setup instructions put your secrets, and it
stays authoritative for anything you set over SSH. The web app never writes it:
/etc is root-owned, so a process running as you can overwrite that file but
cannot create a temp file beside it, which makes an atomic replace impossible.
A half-written env file is a bot that will not start.

So the app owns a second file, ~/.config/momentum/momentum.env, and both the
web unit and the bot unit read both files. systemd applies EnvironmentFile
entries in order, so anything set here wins over /etc. That is the intended
precedence: what you last changed in the browser is what runs.

The bot's unit used to read only /etc, so settings saved here -- including
MOMENTUM_TRACK, which decides the book orders are planned from -- reached this
dashboard and never reached the bot. momentum_bot.py now also loads both files
itself, so a run started by hand resolves settings identically to one started by
systemd. If you add a file to that list, add it in both places.

SECRETS ARE WRITE-ONLY
A stored key is never sent back to the browser. The form shows whether one is
set and its last four characters, and an empty field means "leave it alone".
"""
from __future__ import annotations

import os
import re
import stat
import tempfile

HOME = os.path.expanduser("~")
CONFIG_DIR = os.environ.get("MOMENTUM_CONFIG_DIR") or os.path.join(
    HOME, ".config", "momentum")
CONFIG = os.path.join(CONFIG_DIR, "momentum.env")
ETC = "/etc/momentum-bot.env"

SECRET = {"T212_API_KEY", "T212_API_SECRET", "DISCORD_WEBHOOK",
          "DISCORD_BOT_TOKEN"}

# MOMENTUM_MODE and MOMENTUM_FRACTIONAL used to live here. Both were settled by
# measurement -- drift, fractional -- and hardcoded in the bot, so exposing them
# would only be a way to configure something it can no longer do. Any leftover
# lines in an env file are inert.


class Invalid(ValueError):
    """A setting the user typed that we will not write."""


def _choice(*allowed):
    def check(v):
        v = v.strip()
        if v.lower() not in allowed:
            raise Invalid(f"must be one of: {', '.join(allowed)}")
        return v.lower()
    return check


def _api_key(v):
    v = v.strip()
    if not v:
        raise Invalid("cannot be blank — leave the field empty to keep the current key")
    if re.search(r"\s", v):
        raise Invalid("contains a space or newline; copy it again without wrapping")
    if len(v) < 8:
        raise Invalid("looks too short to be a real key")
    return v


def _webhook(v):
    v = v.strip()
    if not v.startswith("https://discord.com/api/webhooks/"):
        raise Invalid("must start with https://discord.com/api/webhooks/")
    if re.search(r"\s", v):
        raise Invalid("contains a space or newline")
    return v


def _snowflake(v):
    """A Discord id: 17-20 digits. Copied with Developer Mode on."""
    v = v.strip()
    if v and not v.isdigit():
        raise Invalid("a Discord id is digits only — turn on Developer Mode, "
                      "then right-click and Copy ID")
    if v and not 15 <= len(v) <= 21:
        raise Invalid(f"that is {len(v)} digits; a Discord id is about 18")
    return v


def _bot_token(v):
    v = v.strip()
    if not v:
        raise Invalid("cannot be blank — leave the field empty to keep the current token")
    # Checked before the whitespace rule: "Bot xyz" contains a space, and
    # "copy it again without wrapping" would send you looking for the wrong thing.
    if v.lower().startswith("bot "):
        raise Invalid("drop the leading 'Bot ' — just the token itself")
    if re.search(r"\s", v):
        raise Invalid("contains a space or newline; copy it again without wrapping")
    if v.count(".") < 2:
        raise Invalid("a bot token has three dot-separated parts; this looks "
                      "truncated, or it may be a webhook URL")
    return v


def _amount(v):
    v = v.strip()
    try:
        n = float(v)
    except ValueError:
        # Invalid subclasses ValueError, so the conversion gets its own try —
        # otherwise "cannot be negative" below is caught here and mis-reported.
        raise Invalid("must be a number")
    if n < 0:
        raise Invalid("cannot be negative")
    return v


# name -> (validator, human label, help text)
FIELDS = {
    "T212_API_KEY": (_api_key, "Trading 212 API key",
                     "From the app: Settings, API, Generate. It hands you a key "
                     "AND a secret — this is the first of the two. Practice and "
                     "live have separate pairs."),
    "T212_API_SECRET": (_api_key, "Trading 212 secret key",
                        "The second value shown when the key was generated. Both "
                        "halves are required: the key on its own is rejected. It "
                        "is only shown once, so regenerate the pair if it was "
                        "not saved."),
    "T212_ENV": (_choice("demo", "live"), "Which account",
                 "demo is the practice account, live is real money."),
    "DISCORD_WEBHOOK": (_webhook, "Discord webhook",
                        "Where the monthly rebalance is posted."),
    "DISCORD_BOT_TOKEN": (_bot_token, "Discord bot token",
                          "Only needed to approve orders by reaction. From the "
                          "Discord developer portal, Bot tab. A password: anything "
                          "holding it can act as your bot."),
    "DISCORD_CHANNEL_ID": (_snowflake, "Discord channel id",
                           "The channel the bot posts orders into. Developer Mode "
                           "on, right-click the channel, Copy Channel ID."),
    "DISCORD_OWNER_ID": (_snowflake, "Your Discord user id",
                         "Only a checkmark from THIS user approves an order. "
                         "Right-click your own name, Copy User ID."),
    "MOMENTUM_TRACK": (_choice("paper", "live"), "Which book to follow",
                       "Which numbers the monthly instructions are worked out "
                       "from. 'paper' keeps its own book from assumed fills; "
                       "'live' uses what Trading 212 actually holds. Switching "
                       "does not by itself place an order — but the bot can now "
                       "place orders you approve, so this is not the safety "
                       "catch it once was. Switch once --t212-check agrees with "
                       "the broker."),
    "MOMENTUM_CURRENCY": (_choice("usd", "eur", "gbp"), "Currency",
                          "A LABEL ONLY — it converts nothing. The book values US "
                          "stocks at their dollar prices, so the figures are "
                          "dollars whatever this says. On a euro account the two "
                          "drift apart as EUR/USD moves, and by the 0.15% "
                          "Trading 212 charges on each conversion. Set it to "
                          "whatever you would rather read; it changes no maths."),
    "MOMENTUM_MONTHLY": (_amount, "Monthly contribution",
                         "What you pay in each month by standing order. Added "
                         "to the paper book on rebalance day and spread over "
                         "all eight holdings. 0 turns it off. The live track "
                         "takes its cash from Trading 212 instead."),
}

UPPER = {"MOMENTUM_CURRENCY"}          # stored uppercase, chosen lowercase


def parse_env(path: str) -> dict:
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out[k.strip()] = v
    except (FileNotFoundError, OSError):
        pass
    return out


def effective() -> dict:
    """What the bot will actually see: /etc first, our file on top."""
    merged = parse_env(ETC)
    merged.update(parse_env(CONFIG))
    return merged


def for_display() -> list:
    """One row per setting, with secrets reduced to a hint."""
    live = effective()
    ours = parse_env(CONFIG)
    rows = []
    for name, (_, label, help_text) in FIELDS.items():
        raw = live.get(name, "")
        rows.append({
            "name": name, "label": label, "help": help_text,
            "secret": name in SECRET,
            "set": bool(raw),
            "hint": ("···" + raw[-4:]) if (name in SECRET and len(raw) >= 4) else "",
            "value": "" if name in SECRET else raw,
            "from_browser": name in ours,
            "choices": _choices_for(name),
        })
    return rows


def _choices_for(name):
    return {"T212_ENV": ["demo", "live"],
            "MOMENTUM_TRACK": ["paper", "live"],
            "MOMENTUM_CURRENCY": ["usd", "eur", "gbp"]}.get(name)


def apply(form) -> tuple[dict, dict]:
    """Validate a submitted form against the stored file.

    Returns (new_values, errors). A blank secret means "keep what is stored";
    a ticked clear box removes the key entirely.
    """
    current = parse_env(CONFIG)
    new, errors = dict(current), {}

    for name, (check, label, _) in FIELDS.items():
        if form.get(f"clear__{name}"):
            new.pop(name, None)
            continue
        raw = form.get(name)
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            if name in SECRET:
                continue                      # empty means unchanged
            new.pop(name, None)               # a cleared plain field
            continue
        try:
            value = check(raw)
        except Invalid as exc:
            errors[name] = f"{label}: {exc}"
            continue
        new[name] = value.upper() if name in UPPER else value
    return new, errors


def write(values: dict) -> None:
    """Atomically replace the config file, mode 600."""
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    body = ["# Written by the momentum dashboard. Safe to edit by hand.",
            "# systemd reads /etc/momentum-bot.env first, then this file, so",
            "# anything set here wins.", ""]
    for k in FIELDS:
        if k in values:
            body.append(f"{k}={values[k]}")
    text = "\n".join(body) + "\n"

    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".momentum.env.")
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)      # 600 before it is visible
        os.replace(tmp, CONFIG)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
