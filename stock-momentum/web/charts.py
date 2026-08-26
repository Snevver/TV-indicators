"""Inline SVG, rendered on the server. No chart library, no CDN.

Everything is a string of SVG built from the numbers and styled entirely through
CSS custom properties, so it follows the viewer's theme and needs nothing at
render time. Gradients and clip paths get per-chart ids because a page carries
several of these at once.
"""
from __future__ import annotations

import html


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _empty(msg, h=200, note=""):
    body = (f'<text x="450" y="{h // 2 - 4}" text-anchor="middle" class="empty">'
            f'{esc(msg)}</text>')
    if note:
        body += (f'<text x="450" y="{h // 2 + 16}" text-anchor="middle" '
                 f'class="empty sub">{esc(note)}</text>')
    return (f'<svg class="chart" viewBox="0 0 900 {h}" role="img" '
            f'aria-label="{esc(msg)}">{body}</svg>')


def _nice(lo, hi):
    """A rounded axis range and step, so gridlines land on readable numbers."""
    if hi <= lo:
        hi = lo + max(abs(lo) * 0.01, 1)
    span = hi - lo
    step = 10 ** (len(str(int(abs(span)))) - 1) if span >= 1 else 0.1
    for m in (step / 10, step / 5, step / 4, step / 2, step, step * 2, step * 2.5,
              step * 5, step * 10):
        if m > 0 and span / m <= 6:
            step = m
            break
    lo = (int(lo / step) - (1 if lo % step else 0)) * step
    hi = (int(hi / step) + (1 if hi % step else 0)) * step
    return lo, hi, step


def sparkline(values, uid="spark", h=64, w=900):
    """The strip under the hero number. No axes — shape only."""
    n = len(values)
    if n < 2:
        return ""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        hi = lo + 1

    def X(i):
        return w * i / (n - 1)

    def Y(v):
        return 6 + (h - 12) * (1 - (v - lo) / (hi - lo))

    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(values))
    rising = values[-1] >= values[0]
    cls = "up" if rising else "down"
    return (f'<svg class="spark {cls}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'aria-hidden="true">'
            f'<defs><linearGradient id="{uid}-g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" class="g0"/><stop offset="100%" class="g1"/>'
            f'</linearGradient></defs>'
            f'<polygon points="0,{h} {pts} {w},{h}" fill="url(#{uid}-g)"/>'
            f'<polyline points="{pts}" class="sparkline"/>'
            f'<circle cx="{X(n - 1):.1f}" cy="{Y(values[-1]):.1f}" r="3" class="sparkdot"/>'
            f'</svg>')


def equity(dates, total, deposited, sym="$", h=320, uid="eq"):
    """The account against what was paid into it, with a hover crosshair."""
    n = len(dates)
    if n < 2:
        return _empty("The curve starts once the bot has run twice", h,
                      "one point a day, from the first rebalance")

    W, ML, MR, MT, MB = 900, 66, 18, 18, 34
    series = [v for v in total + deposited if v is not None]
    lo, hi, step = _nice(min(series), max(series))
    PW, PH = W - ML - MR, h - MT - MB

    def X(i):
        return ML + PW * i / (n - 1)

    def Y(v):
        return MT + PH * (1 - (v - lo) / (hi - lo))

    o = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" '
         f'aria-label="Account value over time" data-chart="equity">',
         f'<defs><linearGradient id="{uid}-fill" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0%" class="g0"/><stop offset="100%" class="g1"/>'
         f'</linearGradient></defs>']

    v = lo
    while v <= hi + step * 0.01:
        o.append(f'<line class="grid" x1="{ML}" x2="{W - MR}" y1="{Y(v):.1f}" '
                 f'y2="{Y(v):.1f}"/>')
        o.append(f'<text class="ax" x="{ML - 10}" y="{Y(v) + 3.5:.1f}" '
                 f'text-anchor="end">{sym}{v:,.0f}</text>')
        v += step

    seen = ""
    for i, d in enumerate(dates):
        if d[:7] == seen:
            continue
        seen = d[:7]
        if i:
            o.append(f'<line class="grid vert" x1="{X(i):.1f}" x2="{X(i):.1f}" '
                     f'y1="{MT}" y2="{h - MB}"/>')
        o.append(f'<text class="ax" x="{X(i):.1f}" y="{h - 12}" '
                 f'text-anchor="middle">{esc(d[5:7])}·{esc(d[2:4])}</text>')

    area = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(total))
    o.append(f'<polygon points="{ML},{Y(lo):.1f} {area} {X(n - 1):.1f},{Y(lo):.1f}" '
             f'fill="url(#{uid}-fill)"/>')
    dep = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(deposited))
    o.append(f'<polyline class="line paid" points="{dep}"/>')
    o.append(f'<polyline class="line strat" points="{area}"/>')
    o.append(f'<circle class="dot strat pulse" cx="{X(n - 1):.1f}" '
             f'cy="{Y(total[-1]):.1f}" r="4"/>')

    o.append(f'<g class="cross" data-x0="{ML}" data-x1="{W - MR}">'
             f'<line class="crossline" y1="{MT}" y2="{h - MB}"/>'
             f'<circle class="crossdot" r="4.5"/></g>')
    o.append('<g class="hit">')
    band = PW / max(n - 1, 1)
    for i, d in enumerate(dates):
        o.append(f'<rect x="{X(i) - band / 2:.1f}" y="{MT}" width="{band:.1f}" '
                 f'height="{PH}" data-i="{i}" data-x="{X(i):.1f}" '
                 f'data-y="{Y(total[i]):.1f}" data-d="{esc(d)}" '
                 f'data-v="{sym}{total[i]:,.2f}" '
                 f'data-p="{(total[i] / deposited[i] - 1) * 100 if deposited[i] else 0:+.2f}%"/>')
    o.append('</g></svg>')
    return "".join(o)


def drawdown(dates, dd, h=180, uid="dd"):
    n = len(dates)
    if n < 2:
        return _empty("Nothing to draw yet", h)
    W, ML, MR, MT, MB = 900, 66, 18, 14, 28
    lo = min(-4.0, min(dd) * 1.18)
    PH = h - MT - MB

    def X(i):
        return ML + (W - ML - MR) * i / (n - 1)

    def Y(v):
        return MT + PH * (1 - (v - lo) / (0 - lo))

    o = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" '
         f'aria-label="Drawdown from the high-water mark">',
         f'<defs><linearGradient id="{uid}-fill" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0%" class="d0"/><stop offset="100%" class="d1"/>'
         f'</linearGradient></defs>']
    for k in range(5):
        v = lo * k / 4
        o.append(f'<line class="grid{" base" if k == 0 else ""}" x1="{ML}" '
                 f'x2="{W - MR}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        o.append(f'<text class="ax" x="{ML - 10}" y="{Y(v) + 3.5:.1f}" '
                 f'text-anchor="end">{v:.0f}%</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(dd))
    o.append(f'<polygon points="{ML},{Y(0):.1f} {pts} {X(n - 1):.1f},{Y(0):.1f}" '
             f'fill="url(#{uid}-fill)"/>')
    o.append(f'<polyline class="line down" points="{pts}"/>')
    worst = min(range(n), key=lambda i: dd[i])
    if dd[worst] < -0.4:
        o.append(f'<circle class="dot down" cx="{X(worst):.1f}" '
                 f'cy="{Y(dd[worst]):.1f}" r="4"><title>worst so far '
                 f'{dd[worst]:.1f}% on {esc(dates[worst])}</title></circle>')
    o.append("</svg>")
    return "".join(o)


def monthly(rows, h=190):
    if not rows:
        return _empty("One bar will appear per month", h)
    W, ML, MR, MT, MB = 900, 58, 18, 18, 32
    vals = [r["pct"] for r in rows]
    top = max(4.0, max(abs(v) for v in vals) * 1.3)
    n = len(rows)
    slot = (W - ML - MR) / n
    bw = min(52, slot * 0.58)

    def Y(v):
        return MT + (h - MT - MB) * (1 - (v + top) / (2 * top))

    o = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" '
         f'aria-label="Return by month">']
    for k in (-top, -top / 2, 0, top / 2, top):
        o.append(f'<line class="grid{" base" if k == 0 else ""}" x1="{ML}" '
                 f'x2="{W - MR}" y1="{Y(k):.1f}" y2="{Y(k):.1f}"/>')
        o.append(f'<text class="ax" x="{ML - 10}" y="{Y(k) + 3.5:.1f}" '
                 f'text-anchor="end">{k:+.0f}%</text>')
    for i, r in enumerate(rows):
        cx = ML + slot * (i + 0.5)
        y0, y1 = Y(0), Y(r["pct"])
        o.append(f'<rect class="bar {"up" if r["pct"] >= 0 else "down"}" '
                 f'x="{cx - bw / 2:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" '
                 f'height="{max(abs(y1 - y0), 2):.1f}" rx="3">'
                 f'<title>{esc(r["month"])}  {r["pct"]:+.2f}%</title></rect>')
        o.append(f'<text class="ax" x="{cx:.1f}" y="{h - 11}" '
                 f'text-anchor="middle">{esc(r["month"][5:7])}</text>')
    o.append("</svg>")
    return "".join(o)


def allocation(positions, h=118):
    """A donut: what the account is made of. Reads faster than a stacked bar
    when the weights are close, which for an equal-weight basket they are."""
    rows = sorted(positions.items(), key=lambda kv: -kv[1].get("value", 0))
    total = sum(p.get("value", 0) for _, p in rows)
    if not rows or total <= 0:
        return _empty("Nothing held", h)
    R, SW, cx, cy = 44.0, 13.0, 60.0, 59.0
    circ = 2 * 3.141592653589793 * R
    o = [f'<svg class="chart donut" viewBox="0 0 120 {h}" role="img" '
         f'aria-label="Portfolio weights">']
    off = 0.0
    for i, (tk, p) in enumerate(rows):
        frac = p.get("value", 0) / total
        dash = max(frac * circ - 1.6, 0.6)
        o.append(f'<circle class="arc s{i % 8}" cx="{cx}" cy="{cy}" r="{R}" '
                 f'fill="none" stroke-width="{SW}" '
                 f'stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
                 f'stroke-dashoffset="{-off:.2f}" '
                 f'transform="rotate(-90 {cx} {cy})">'
                 f'<title>{esc(tk)}  {p.get("weight_pct", 0):.1f}%</title></circle>')
        off += frac * circ
    o.append(f'<text class="donutnum" x="{cx}" y="{cy - 2}" text-anchor="middle">'
             f'{len(rows)}</text>')
    o.append(f'<text class="donutlab" x="{cx}" y="{cy + 14}" text-anchor="middle">'
             f'names</text>')
    o.append("</svg>")
    return "".join(o)


def weight_rules(positions, nonce_class="wb"):
    """Per-row width rules for the holdings bars.

    Emitted as a real stylesheet with a nonce rather than inline style
    attributes, so the page keeps a strict style-src.
    """
    rows = sorted(positions.items(), key=lambda kv: -kv[1].get("value", 0))
    biggest = max((p.get("weight_pct", 0) for _, p in rows), default=0) or 1
    out = []
    for tk, p in rows:
        pct = p.get("weight_pct", 0) / biggest * 100
        out.append(f".{nonce_class}-{tk.lower()}{{--bar:{pct:.1f}%}}")
    return "\n".join(out)
