"""Reading and writing the bot's settings from the browser.

A FEW EDITABLE SETTINGS, THE REST READ-ONLY
The browser owns MOMENTUM_START_BUDGET, MOMENTUM_MONTHLY and MOMENTUM_KILL. It
writes them to ~/.config/momentum/momentum.env, which both the web unit and the
bot unit load after /etc/momentum-bot.env, so a change here wins.

Everything else -- the Trading 212 key pairs, the Discord webhook and bot token,
the channel and user ids -- is set once over SSH in /etc/momentum-bot.env and
only reported present/absent by credentials(). The web app never writes /etc:
it is root-owned, so a process running as you can overwrite the file but cannot
create a temp file beside it for an atomic replace, and a half-written env file
is a bot that will not start. Keeping credentials out of the browser form also
means one source of truth for them rather than two that can drift.
"""
from __future__ import annotations

import os
import stat
import tempfile

HOME = os.path.expanduser("~")
CONFIG_DIR = os.environ.get("MOMENTUM_CONFIG_DIR") or os.path.join(
    HOME, ".config", "momentum")
CONFIG = os.path.join(CONFIG_DIR, "momentum.env")
ETC = "/etc/momentum-bot.env"

# Set over SSH in /etc/momentum-bot.env, shown read-only by credentials(). Not
# fields: a browser copy would be a second place they could drift from the file
# the bot reads.
SECRET = ("T212_API_KEY_DEMO", "T212_API_SECRET_DEMO", "T212_API_KEY_LIVE",
          "T212_API_SECRET_LIVE", "T212_API_KEY", "T212_API_SECRET",
          "DISCORD_WEBHOOK", "DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID",
          "DISCORD_OWNER_ID", "DISCORD_CONFIRM_CHANNEL_ID",
          "DISCORD_CONFIRM_CHANNEL_ID_DEMO")

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
    # Hung on the function so the page can render a dropdown from the same list
    # that validates the answer. It used to be a second dict keyed by field name,
    # which meant a new choice field silently rendered as a free-text box until
    # somebody noticed.
    check.choices = list(allowed)
    return check


# The credential validators (_api_key, _webhook, _snowflake, _bot_token) were
# removed with the credential fields. Those values are set over SSH in
# /etc/momentum-bot.env now and only shown, never validated here -- see
# credentials().


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
#
# A SHORT LIST, DELIBERATELY. Credentials, channel/user ids and the Trading 212
# key pairs are set once over SSH in /etc/momentum-bot.env and shown read-only by
# credentials() below -- they do not belong in a browser form that can drift from
# the file the bot actually reads.
#
# T212_ENV and MOMENTUM_AUTOTRADE used to live here. Both are gone: the bot now
# runs the strategy on both accounts every month (demo automatically, live after
# a Discord reaction), so there is no account to pick and nothing to switch off.
# MOMENTUM_TRACK and MOMENTUM_CURRENCY were removed earlier for similar reasons.
FIELDS = {
    "MOMENTUM_START_BUDGET": (_amount, "Starting amount",
                              "How much of your Trading 212 free funds the "
                              "strategy begins with. The first rebalance sizes "
                              "the opening eight positions to this and draws it "
                              "from free funds when you approve. Applied once: "
                              "after the strategy has started, growth and the "
                              "monthly contribution carry it and changing this "
                              "does nothing. Use the bot's --deposit for a later "
                              "top-up."),
    "MOMENTUM_MONTHLY": (_amount, "Monthly contribution",
                         "Added to what the strategy invests on every rebalance "
                         "after the first, drawn from your Trading 212 free funds "
                         "(a bank standing order, or just the balance you already "
                         "hold) and spread over the new basket. 0 turns it off. "
                         "Do not also run a bank standing order into the account "
                         "on top of this; the bot only deploys this amount, and "
                         "anything extra piles up untouched."),
    "MOMENTUM_KILL": (_choice("off", "on"), "Kill switch",
                      "Sells every strategy position at market right now and "
                      "freezes all trading until you press it again. Your pies "
                      "and anything outside the 40 names are untouched. The "
                      "browser asks you to confirm first."),
}

# Rendered as a red arm/disarm button rather than a form field.
BUTTON_FIELDS = {"MOMENTUM_KILL"}

UPPER = set()          # nothing stored in a different case any more


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
    """One row per editable setting. No secrets here any more -- those are in
    credentials(), read-only."""
    live = effective()
    ours = parse_env(CONFIG)
    rows = []
    for name, (_, label, help_text) in FIELDS.items():
        raw = live.get(name, "")
        rows.append({
            "name": name, "label": label, "help": help_text,
            "secret": False,
            "set": bool(raw),
            "value": raw,
            "from_browser": name in ours,
            "choices": getattr(FIELDS[name][0], "choices", None),
            # A plain field, or the kill switch's arm/disarm button.
            "kind": "button" if name in BUTTON_FIELDS else "field",
            "armed": name in BUTTON_FIELDS and str(raw).strip().lower() == "on",
        })
    return rows


def credentials() -> list:
    """The values set once over SSH in /etc/momentum-bot.env, reported present or
    not -- never their content. The dashboard shows this so you can see the bot
    has what it needs without opening the file."""
    e = effective()

    def has(*names):
        return any(e.get(n, "").strip() for n in names)

    return [
        {"label": "Trading 212, demo key",
         "set": has("T212_API_KEY_DEMO", "T212_API_KEY"),
         "note": "T212_API_KEY_DEMO / T212_API_SECRET_DEMO"},
        {"label": "Trading 212, live key",
         "set": has("T212_API_KEY_LIVE", "T212_API_KEY"),
         "note": "T212_API_KEY_LIVE / T212_API_SECRET_LIVE"},
        {"label": "Discord webhook (monthly message)",
         "set": has("DISCORD_WEBHOOK"),
         "note": "DISCORD_WEBHOOK"},
        {"label": "Discord approvals (react to place orders)",
         "set": has("DISCORD_BOT_TOKEN") and has("DISCORD_CHANNEL_ID")
         and has("DISCORD_OWNER_ID"),
         "note": "DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID + DISCORD_OWNER_ID"},
        {"label": "Discord confirmations channel (optional)",
         "set": has("DISCORD_CONFIRM_CHANNEL_ID"),
         "note": "DISCORD_CONFIRM_CHANNEL_ID; live records go here, unset = the "
                 "approvals channel"},
        {"label": "Discord demo records channel (optional)",
         "set": has("DISCORD_CONFIRM_CHANNEL_ID_DEMO"),
         "note": "DISCORD_CONFIRM_CHANNEL_ID_DEMO; the demo account's rebalance "
                 "records go here, unset = the live confirmations channel"},
    ]


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
