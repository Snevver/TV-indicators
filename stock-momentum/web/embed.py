#!/usr/bin/env python3
"""The public P/L chart. Nothing else.

This is the ONLY thing meant to ever face the internet. app.py explicitly must
not be (see its module docstring) -- it has a login, but also buttons that place
real trades and a kill switch, over plain HTTP. This process knows how to do
exactly two things: serve the chart page, and answer /candles with read-only
JSON. It never imports config, simulate, or anything that can write or run the
bot -- there is no route to add later that would make this unsafe, because the
capability to do anything else isn't here.

    .venv/bin/pip install flask
    .venv/bin/python embed.py                    # http://0.0.0.0:6768

Point a Cloudflare Tunnel (or similar) at this port and only this port. Embed
with:
    <iframe src="https://chart.snev.dev" style="border:0;width:100%;height:420px"></iframe>
"""
from __future__ import annotations

import json

from flask import Flask, jsonify, request

import data

app = Flask(__name__)


@app.after_request
def _headers(resp):
    # Let any site iframe this (it's the whole point) but nothing here has a
    # session or a form for a CSRF-y trick to abuse.
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/candles")
def candles():
    tf = request.args.get("tf", "1d")
    if tf not in data.TFS:
        return jsonify({"error": f"unknown tf {tf!r}"}), 400
    return jsonify({"tf": tf, "bars": data.candles(tf)})


@app.route("/")
def index():
    # Ordered oldest-timeframe-first for the button row; TFS itself is a set.
    tfs = [tf for tf in ("1m", "5m", "15m", "30m", "60m", "4h", "1d", "1M") if tf in data.TFS]
    return PAGE.replace("__TFS__", json.dumps(tfs))


# One file, inline. This page has no other assets and isn't worth a build step.
PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Momentum</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@5.0.7/dist/lightweight-charts.standalone.production.js"></script>
<style>
  html,body{margin:0;height:100%;background:#04070D;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  #wrap{display:flex;flex-direction:column;height:100%}
  #tfs{display:flex;gap:4px;padding:6px 8px;flex:none}
  #tfs button{
    background:transparent;border:1px solid rgba(140,175,215,.2);border-radius:4px;
    color:#7789A3;font:inherit;font-size:.72rem;padding:3px 8px;cursor:pointer;
  }
  #tfs button.on{color:#00F0FF;border-color:#00F0FF}
  #host{flex:1;min-height:0}
  #err{color:#7789A3;font-size:.8rem;padding:10px;display:none}
</style>
</head>
<body>
<div id="wrap">
  <div id="tfs"></div>
  <div id="host"></div>
  <div id="err">no data yet</div>
</div>
<script>
const TFS = __TFS__;
let tf = TFS.includes("1d") ? "1d" : TFS[0];

const tfBar = document.getElementById("tfs");
for (const t of TFS) {
  const b = document.createElement("button");
  b.textContent = t;
  b.onclick = () => { tf = t; render(); load(); };
  tfBar.appendChild(b);
}
function render() {
  for (const b of tfBar.children) b.classList.toggle("on", b.textContent === tf);
}
render();

const host = document.getElementById("host");
const chart = LightweightCharts.createChart(host, {
  width: host.clientWidth, height: host.clientHeight,
  layout: { background: { color: "transparent" }, textColor: "#7789A3" },
  grid: { vertLines: { color: "rgba(140,175,215,.06)" },
          horzLines: { color: "rgba(140,175,215,.08)" } },
  rightPriceScale: { borderColor: "rgba(140,175,215,.12)" },
  timeScale: { borderColor: "rgba(140,175,215,.12)", timeVisible: true, secondsVisible: false },
});
const series = chart.addSeries(LightweightCharts.CandlestickSeries, {
  upColor: "#6EFF7B", downColor: "#FF4D6D",
  borderUpColor: "#6EFF7B", borderDownColor: "#FF4D6D",
  wickUpColor: "#6EFF7B", wickDownColor: "#FF4D6D",
});
new ResizeObserver(() => chart.resize(host.clientWidth, host.clientHeight)).observe(host);

async function load() {
  try {
    const r = await fetch("/candles?tf=" + encodeURIComponent(tf));
    const { bars } = await r.json();
    document.getElementById("err").style.display = bars.length ? "none" : "block";
    if (bars.length) series.setData(bars);
  } catch (e) {
    document.getElementById("err").style.display = "block";
  }
}
load();
setInterval(load, 60000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6768)
