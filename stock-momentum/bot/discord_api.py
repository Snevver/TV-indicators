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
OWNER_ID = os.environ.get("DISCORD_OWNER_ID", "").strip()
TIMEOUT = float(os.environ.get("DISCORD_TIMEOUT", "20") or 20)

TICK = "✅"                      # the reaction that means yes
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
            raise DiscordError("401 — the bot token was rejected. It was probably "
                               "reset; copy the current one into Settings.")
        if r.status_code == 403:
            raise DiscordError(f"403 — the bot lacks a permission for {path}. It "
                               f"needs View Channels, Send Messages, Read Message "
                               f"History and Add Reactions in that channel.")
        if r.status_code == 404:
            raise DiscordError(f"404 — {path} does not exist, or the bot cannot "
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
        raise DiscordError(f"{path}: HTTP {r.status_code} — {r.text[:200]}")
    raise DiscordError(f"{path}: gave up after {tries} attempts ({last})")


def me() -> dict:
    """Who this token belongs to."""
    return _req("GET", "/users/@me")


def channel() -> dict:
    """The channel the bot will post into."""
    return _req("GET", f"/channels/{CHANNEL_ID}")


def post(content: str = "", embeds=None) -> str:
    """Post a message and return its id, which is the handle for the answer."""
    body = {}
    if content:
        body["content"] = content[:1900]
    if embeds:
        body["embeds"] = embeds
    d = _req("POST", f"/channels/{CHANNEL_ID}/messages", body)
    mid = (d or {}).get("id")
    if not mid:
        raise DiscordError(f"posted, but no message id came back: {str(d)[:200]}")
    return str(mid)


def offer_tick(message_id: str) -> None:
    """Pre-add the checkmark so approving is one click rather than a search."""
    _req("PUT", f"/channels/{CHANNEL_ID}/messages/{message_id}"
                f"/reactions/{TICK_URL}/@me")


def reactors(message_id: str) -> list:
    """User ids that ticked the message. The bot's own tick is excluded."""
    d = _req("GET", f"/channels/{CHANNEL_ID}/messages/{message_id}"
                    f"/reactions/{TICK_URL}?limit=100")
    if not isinstance(d, list):
        raise DiscordError(f"expected a list of users, got {type(d).__name__}")
    out = []
    for u in d:
        if isinstance(u, dict) and u.get("id") and not u.get("bot"):
            out.append(str(u["id"]))
    return out


def approved_by_owner(message_id: str) -> bool:
    """True only if the configured owner ticked it. Never raises."""
    try:
        return OWNER_ID in reactors(message_id)
    except Exception as exc:                          # noqa: BLE001
        print(f"  ! Discord: {exc}")
        return False
