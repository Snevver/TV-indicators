#!/usr/bin/env python3
"""The momentum dashboard. Serves on the LAN, behind a password.

    .venv/bin/pip install flask
    .venv/bin/python app.py --set-password
    .venv/bin/python app.py                      # http://0.0.0.0:6767

SECURITY POSTURE, STATED PLAINLY
This is plain HTTP on a home network. The password crosses your LAN
unencrypted, and so does everything the page shows. That is an accepted trade
for a machine on your own network; it is NOT acceptable if this port is ever
forwarded to the internet, and it must not be. There is no rate limit that makes
a forwarded port safe.

The Trading 212 key is never sent to the browser — the settings page shows only
whether one is stored and its last four characters.
"""
from __future__ import annotations

import argparse
import functools
import getpass
import hashlib
import hmac
import json
import os
import secrets
import stat
import time

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, session, url_for)

import charts
import config
import data

HERE = os.path.dirname(os.path.abspath(__file__))
AUTH = os.path.join(HERE, "auth.json")

# Login throttling. In memory, so it resets on restart — enough to make guessing
# impractical on a LAN, and not pretending to be more than that.
FAILS: dict[str, list] = {}
MAX_FAILS, LOCKOUT = 5, 900


# ------------------------------------------------------------------ auth ---

def _load_auth() -> dict:
    try:
        with open(AUTH, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_auth(d: dict) -> None:
    tmp = AUTH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, AUTH)


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt,
                          n=16384, r=8, p=1, dklen=32).hex()


def set_password() -> int:
    pw = getpass.getpass("New dashboard password: ")
    if len(pw) < 8:
        print("Too short — use at least 8 characters.")
        return 1
    if pw != getpass.getpass("Again: "):
        print("They did not match.")
        return 1
    d = _load_auth()
    salt = secrets.token_bytes(16)
    d.update({"salt": salt.hex(), "hash": _hash(pw, salt)})
    d.setdefault("secret", secrets.token_hex(32))
    _save_auth(d)
    print(f"Saved to {AUTH} (mode 600).")
    return 0


def check_password(pw: str) -> bool:
    d = _load_auth()
    if not d.get("hash") or not d.get("salt"):
        return False
    try:
        salt = bytes.fromhex(d["salt"])
    except ValueError:
        return False
    return hmac.compare_digest(_hash(pw, salt), d["hash"])


def locked(ip: str) -> int:
    hits = [t for t in FAILS.get(ip, []) if time.time() - t < LOCKOUT]
    FAILS[ip] = hits
    if len(hits) < MAX_FAILS:
        return 0
    return int(LOCKOUT - (time.time() - hits[0]))


# ------------------------------------------------------------------- app ---

app = Flask(__name__)
_auth = _load_auth()
app.secret_key = _auth.get("secret") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=64 * 1024)


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not logged in"}), 401
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def csrf_ok() -> bool:
    return hmac.compare_digest(str(request.form.get("csrf", "")),
                               str(session.get("csrf", "")))


@app.before_request
def make_nonce():
    # A fresh nonce per request lets the holdings bars ship their widths as a
    # real <style> block. Inline style attributes would need 'unsafe-inline',
    # which is a much bigger hole than one server-generated rule set.
    g.nonce = secrets.token_urlsafe(16)


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    nonce = getattr(g, "nonce", "")
    # Fonts are fetched by the viewer's browser, not by this machine, so they
    # work even when the mini PC itself is offline. Everything has a system
    # fallback if the browser cannot reach them either.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; form-action 'self'; frame-ancestors 'none'")
    return resp


@app.context_processor
def inject():
    return {"csrf": session.get("csrf", ""), "TRACK_LABEL": data.TRACK_LABEL,
            "nonce": getattr(g, "nonce", "")}


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _load_auth().get("hash"):
        return render_template("login.html", setup=True), 503
    ip = request.remote_addr or "?"
    if request.method == "POST":
        wait = locked(ip)
        if wait:
            return render_template("login.html",
                                   error=f"Too many attempts. Try again in "
                                         f"{wait // 60 + 1} minutes."), 429
        if check_password(request.form.get("password", "")):
            FAILS.pop(ip, None)
            session.clear()
            session["in"] = True
            session["csrf"] = secrets.token_hex(16)
            session.permanent = False
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and "//" not in nxt else "/")
        FAILS.setdefault(ip, []).append(time.time())
        return render_template("login.html", error="Wrong password."), 401
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    if not csrf_ok():
        abort(400)
    session.clear()
    return redirect(url_for("login"))


def _track() -> str:
    t = request.args.get("track", "")
    if t in data.TRACKS:
        return t
    return data.health().get("track") or "paper"


@app.route("/")
@login_required
def dashboard():
    track = _track()
    s = data.summary(track)
    c = data.curve(track)
    h = data.health()
    sym = data.latest().get("symbol") or "$"
    other = data.summary("live" if track == "paper" else "paper")
    # Sorted here rather than in the template: Jinja's dictsort would compare the
    # position dicts themselves, not their values.
    held = sorted((s.get("positions") or {}).items(),
                  key=lambda kv: -(kv[1].get("value") or 0))
    return render_template(
        "dashboard.html", track=track, s=s, c=c, h=h, sym=sym, other=other,
        held=held, rebalances=data.rebalances()[:14],
        spark=charts.sparkline(c["total"]),
        weight_css=charts.weight_rules(s.get("positions") or {}),
        chart_equity=charts.equity(c["dates"], c["total"], c["deposited"], sym),
        chart_dd=charts.drawdown(c["dates"], c["drawdown"]),
        chart_monthly=charts.monthly(c["monthly"]),
        chart_alloc=charts.allocation(s.get("positions") or {}))


@app.route("/strategy")
@login_required
def strategy():
    return render_template("strategy.html", h=data.health())


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    errors, saved = {}, False
    if request.method == "POST":
        if not csrf_ok():
            abort(400)
        values, errors = config.apply(request.form)
        if not errors:
            try:
                config.write(values)
                saved = True
            except OSError as exc:
                errors["_"] = f"Could not write {config.CONFIG}: {exc}"
    return render_template("settings.html", rows=config.for_display(),
                           errors=errors, saved=saved,
                           config_path=config.CONFIG, etc_path=config.ETC,
                           h=data.health())


@app.route("/api/summary")
@login_required
def api_summary():
    track = _track()
    return jsonify({"track": track, "summary": data.summary(track),
                    "health": data.health()})


@app.route("/api/history")
@login_required
def api_history():
    return jsonify({t: data.curve(t) for t in data.TRACKS})


@app.route("/api/action", methods=["POST"])
@login_required
def api_action():
    if not csrf_ok():
        return jsonify({"error": "stale form, reload the page"}), 400
    action = (request.form.get("action") or request.json.get("action")
              if request.is_json else request.form.get("action"))
    if action not in data.ACTIONS:
        return jsonify({"error": "unknown action"}), 400
    return jsonify(data.run_bot(action))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--set-password", action="store_true",
                   help="set or change the dashboard password, then exit")
    p.add_argument("--host", default=os.environ.get("MOMENTUM_WEB_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("MOMENTUM_WEB_PORT", "6767")))
    args = p.parse_args()
    if args.set_password:
        return set_password()
    if not _load_auth().get("hash"):
        print("No password set yet. Run:  python app.py --set-password")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
