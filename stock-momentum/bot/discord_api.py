#!/usr/bin/env python3
"""Discord as an approval channel. Read and write, but only ever to Discord.

WHY THERE IS NO GATEWAY CONNECTION
Reading a reaction looks like it needs a bot that stays connected to Discord's
websocket forever, listening for events. It does not:

    GET /channels/{channel}/messages/{message}/reactions/{emoji}

returns the users who reacted, on demand, with nothing but a bot token. So the
rebalance run posts a message and the next run reads the answer. No always-on
service to crash at 3am, no privileged intents, and the confirmation window is
just a span of time rather than a process that has to survive it.

The bot needs only: View Channels, Send Messages, Read Message History and Add
Reactions.

WHAT A REACTION IS WORTH
Less than a password. Anyone who can see the channel can add a checkmark, so the
reaction alone is not authorisation -- DISCORD_OWNER_ID is, and only a reaction
from that exact user id counts. A checkmark from anyone else is ignored, and
said so out loud rather than silently.

The token is a password of the same weight as the broker key: anything holding
it can act as this bot. It lives in the env files, mode 600, never in the repo.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse

API = "https://discord.com/api/v10"
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
# Where the permanent records go -- "rebalance placed", "skipped", "expired".
# The ✅/❌ approval prompts stay in CHANNEL_ID and delete themselves once
# answered. Unset means both in the one channel, which is the old behaviour.
CONFIRM_CHANNEL_ID = os.environ.get("DISCORD_CONFIRM_CHANNEL_ID", "").strip() or CHANNEL_ID
OWNER_ID = os.environ.get("DISCORD_OWNER_ID", "").strip()
TIMEOUT = float(os.environ.get("DISCORD_TIMEOUT", "20") or 20)

TICK = "✅"                      # yes
CROSS = "❌"                     # no, or undo
TICK_URL = urllib.parse.quote(TICK)


class DiscordError(Exception):
    """Anything that went wrong talking to Discord. Always caught by callers."""


def configured() -> bool:
    return bool(TOKEN and CHANNEL_ID and OWNER_ID)


def why_not() -> str:
    missing = [n for n, v in (("DISCORD_BOT_TOKEN", TOKEN),
                              ("DISCORD_CHANNEL_ID", CHANNEL_ID),
                              ("DISCORD_OWNER_ID", OWNER_ID)) if not v]
    return ("not set: " + ", ".join(missing)) if missing else ""


def _req(method: str, path: str, body=None, tries: int = 3):
    """One authenticated call. Raises DiscordError on anything unexpected."""
    import requests
    url = f"{API}{path}"
    headers = {"Authorization": f"Bot {TOKEN}",
               "Content-Type": "application/json",
               "User-Agent": "momentum-bot (self-hosted, +https://localhost)"}
    last = ""
    for attempt in range(tries):
        try:
            r = requests.request(method, url, headers=headers,
                                 data=json.dumps(body) if body is not None else None,
                                 timeout=TIMEOUT)
        except Exception as exc:                      # network, DNS, TLS, timeout
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 429:
            # Discord tells you exactly how long to wait; obey it rather than guess.
            wait = 5.0
            try:
                wait = float(r.json().get("retry_after", wait))
            except Exception:                         # noqa: BLE001
                pass
            last = f"429 rate limited, retry after {wait}s"
            time.sleep(min(wait + 0.5, 30))
            continue
        if r.status_code == 401:
            raise DiscordError("401 - the bot token was rejected. It was probably "
                               "reset; copy the current one into Settings.")
        if r.status_code == 403:
            raise DiscordError(f"403 - the bot lacks a permission for {path}. It "
                               f"needs View Channels, Send Messages, Read Message "
                               f"History, Add Reactions and Manage Messages in "
                               f"that channel.")
        if r.status_code == 404:
            raise DiscordError(f"404 - {path} does not exist, or the bot cannot "
                               f"see it. Check DISCORD_CHANNEL_ID and that the bot "
                               f"was invited to the server.")
        if r.status_code in (200, 201, 204):
            if r.status_code == 204 or not r.content:
                return None
            try:
                return r.json()
            except ValueError:
                raise DiscordError(f"{path}: {r.status_code} but the body was not "
                                   f"JSON: {r.text[:200]}")
        raise DiscordError(f"{path}: HTTP {r.status_code} - {r.text[:200]}")
    raise DiscordError(f"{path}: gave up after {tries} attempts ({last})")


def me() -> dict:
    """Who this token belongs to."""
    return _req("GET", "/users/@me")


def channel() -> dict:
    """The channel the bot will post into."""
    return _req("GET", f"/channels/{CHANNEL_ID}")


def post(content: str = "", embeds=None, channel: str = "") -> str:
    """Post a message and return its id. `channel` defaults to CHANNEL_ID; pass
    CONFIRM_CHANNEL_ID for a record that should stay put."""
    body = {}
    if content:
        # Discord's cap is 2000 characters. Truncating silently is how the
        # instruction at the bottom of a long message ("react to approve")
        # disappears while the message still looks complete, so it says so.
        if len(content) > 1900:
            print(f"  ! Discord message trimmed from {len(content)} characters "
                  f"to 1900 - the end of it was cut off.")
        body["content"] = content[:1900]
    if embeds:
        body["embeds"] = embeds
    d = _req("POST", f"/channels/{channel or CHANNEL_ID}/messages", body)
    mid = (d or {}).get("id")
    if not mid:
        raise DiscordError(f"posted, but no message id came back: {str(d)[:200]}")
    return str(mid)


def delete_message(message_id: str, channel: str = "") -> None:
    """Remove a message. Best-effort: a message left in place is untidy, not a
    failure, so this never raises."""
    if not message_id:
        return
    try:
        _req("DELETE", f"/channels/{channel or CHANNEL_ID}/messages/{message_id}",
             tries=2)
    except Exception as exc:                          # noqa: BLE001
        print(f"  ! Discord: could not delete message {message_id} ({exc})")


def offer_tick(message_id: str, emoji: str = TICK) -> None:
    """Pre-add a reaction so answering is one click rather than a search."""
    _req("PUT", f"/channels/{CHANNEL_ID}/messages/{message_id}"
                f"/reactions/{urllib.parse.quote(emoji)}/@me")


def reactors(message_id: str, emoji: str = TICK) -> list:
    """User ids that reacted with `emoji`. The bot's own reaction is excluded.

    Discord answers per emoji: there is no combined list, so a message offering
    two choices takes two calls.
    """
    d = _req("GET", f"/channels/{CHANNEL_ID}/messages/{message_id}"
                    f"/reactions/{urllib.parse.quote(emoji)}?limit=100")
    if not isinstance(d, list):
        raise DiscordError(f"expected a list of users, got {type(d).__name__}")
    out = []
    for u in d:
        if isinstance(u, dict) and u.get("id") and not u.get("bot"):
            out.append(str(u["id"]))
    return out


def approved_by_owner(message_id: str, emoji: str = TICK) -> bool:
    """True only if the configured owner reacted with `emoji`. Never raises."""
    try:
        return OWNER_ID in reactors(message_id, emoji)
    except Exception as exc:                          # noqa: BLE001
        print(f"  ! Discord: {exc}")
        return False


def owner_choice(message_id: str):
    """Which of the two the owner picked: 'yes', 'no', or None.

    Read as a pair rather than two independent questions, so reacting to both --
    by accident, or by changing your mind without removing the first -- is a
    stalemate that does nothing, instead of whichever happened to be checked
    first. Never raises.
    """
    try:
        yes = OWNER_ID in reactors(message_id, TICK)
        no = OWNER_ID in reactors(message_id, CROSS)
    except Exception as exc:                          # noqa: BLE001
        print(f"  ! Discord: {exc}")
        return None
    if yes and no:
        print(f"  ! both {TICK} and {CROSS} are set. Remove one; doing nothing.")
        return None
    return "yes" if yes else ("no" if no else None)
