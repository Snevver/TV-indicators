"""Inline SVG, rendered on the server. No chart library, no CDN.

The mini PC may have no outbound internet when a page is served, and a chart
that silently fails to draw is worse than a plain table. Everything here is a
string of SVG built from the numbers, styled entirely by CSS custom properties
so it follows the page's light or dark theme.

Colours match the published report: teal for the strategy, ochre for the money
you paid in, red for drawdown.
"""
from __future__ import annotations

import html


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _empty(msg, h=200):
    return (f'<svg class="chart" viewBox="0 0 900 {h}" role="img" '
            f'aria-label="{esc(msg)}"><text x="450" y="{h // 2}" '
            f'text-anchor="middle" class="empty">{esc(msg)}</text></svg>')


def _nice(lo, hi):
    """A rounded axis range and a step, so gridlines land on readable numbers."""
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    mag = 10 ** len(str(int(abs(span)))) if span >= 1 else 1
    for m in (mag / 20, mag / 10, mag / 5, mag / 2, mag, mag * 2, mag * 5):
        if m > 0 and span / m <= 6:
            step = m
            break
    else:
        step = span / 5
    lo = (int(lo / step) - 1) * step if lo else 0
    hi = (int(hi / step) + 1) * step
    return lo, hi, step


def equity(dates, total, deposited, sym="$", h=300):
    """The account against what was paid into it."""
    n = len(dates)
    if n < 2:
        return _empty("The curve starts once the bot has run twice", h)

    W, ML, MR, MT, MB = 900, 62, 16, 14, 30
    series = [v for v in total + deposited if v is not None]
    lo, hi, step = _nice(min(series), max(series))

    def X(i):
        return ML + (W - ML - MR) * i / (n - 1)

    def Y(v):
        return MT + (h - MT - MB) * (1 - (v - lo) / (hi - lo))

    out = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" '
           f'aria-label="Account value over time">']

    v = lo
    while v <= hi + 1e-9:
        out.append(f'<line class="grid" x1="{ML}" x2="{W - MR}" '
                   f'y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        out.append(f'<text class="ax" x="{ML - 8}" y="{Y(v) + 3.5:.1f}" '
                   f'text-anchor="end">{sym}{v:,.0f}</text>')
        v += step

    seen = ""
    for i, d in enumerate(dates):
        if d[:7] == seen:
            continue
        seen = d[:7]
        out.append(f'<text class="ax" x="{X(i):.1f}" y="{h - 9}" '
                   f'text-anchor="middle">{esc(d[5:7])}/{esc(d[2:4])}</text>')

    area = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(total))
    out.append(f'<polygon class="fill" points="{ML},{Y(lo):.1f} {area} '
               f'{X(n - 1):.1f},{Y(lo):.1f}"/>')
    dep = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(deposited))
    out.append(f'<polyline class="line paid" points="{dep}"/>')
    ln = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(total))
    out.append(f'<polyline class="line strat" points="{ln}"/>')
    out.append(f'<circle class="dot strat" cx="{X(n - 1):.1f}" '
               f'cy="{Y(total[-1]):.1f}" r="3.5"/>')

    out.append('<g class="hover">')
    for i, d in enumerate(dates):
        wdt = (W - ML - MR) / max(n - 1, 1)
        out.append(f'<rect x="{X(i) - wdt / 2:.1f}" y="{MT}" width="{wdt:.1f}" '
                   f'height="{h - MT - MB}" fill="transparent">'
                   f'<title>{esc(d)}  {sym}{total[i]:,.2f}</title></rect>')
    out.append('</g></svg>')
    return "".join(out)


def drawdown(dates, dd, h=170):
    """How far below the high-water mark, every day."""
    n = len(dates)
    if n < 2:
        return _empty("Nothing to draw yet", h)
    W, ML, MR, MT, MB = 900, 62, 16, 12, 26
    lo = min(-5.0, min(dd) * 1.15)

    def X(i):
        return ML + (W - ML - MR) * i / (n - 1)

    def Y(v):
        return MT + (h - MT - MB) * (1 - (v - lo) / (0 - lo))

    out = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" '
           f'aria-label="Drawdown from the high-water mark">']
    steps = 4
    for k in range(steps + 1):
        v = lo * k / steps
        cls = "grid base" if k == 0 else "grid"
        out.append(f'<line class="{cls}" x1="{ML}" x2="{W - MR}" '
                   f'y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        out.append(f'<text class="ax" x="{ML - 8}" y="{Y(v) + 3.5:.1f}" '
                   f'text-anchor="end">{v:.0f}%</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(dd))
    out.append(f'<polygon class="fill down" points="{ML},{Y(0):.1f} {pts} '
               f'{X(n - 1):.1f},{Y(0):.1f}"/>')
    out.append(f'<polyline class="line down" points="{pts}"/>')
    worst = min(range(n), key=lambda i: dd[i])
    if dd[worst] < -0.5:
        out.append(f'<circle class="dot down" cx="{X(worst):.1f}" '
                   f'cy="{Y(dd[worst]):.1f}" r="3.5"><title>worst so far: '
                   f'{dd[worst]:.1f}% on {esc(dates[worst])}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def monthly(rows, h=180):
    """One bar per calendar month."""
    if not rows:
        return _empty("One bar will appear per month", h)
    W, ML, MR, MT, MB = 900, 52, 16, 16, 30
    vals = [r["pct"] for r in rows]
    top = max(5.0, max(abs(v) for v in vals) * 1.25)
    n = len(rows)
    slot = (W - ML - MR) / n
    bw = min(46, slot * 0.6)

    def Y(v):
        return MT + (h - MT - MB) * (1 - (v + top) / (2 * top))

    out = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" '
           f'aria-label="Return by month">']
    for k in (-top, -top / 2, 0, top / 2, top):
        out.append(f'<line class="{"grid base" if k == 0 else "grid"}" x1="{ML}" '
                   f'x2="{W - MR}" y1="{Y(k):.1f}" y2="{Y(k):.1f}"/>')
        out.append(f'<text class="ax" x="{ML - 8}" y="{Y(k) + 3.5:.1f}" '
                   f'text-anchor="end">{k:+.0f}%</text>')
    for i, r in enumerate(rows):
        cx = ML + slot * (i + 0.5)
        y0, y1 = Y(0), Y(r["pct"])
        cls = "up" if r["pct"] >= 0 else "down"
        out.append(f'<rect class="bar {cls}" x="{cx - bw / 2:.1f}" '
                   f'y="{min(y0, y1):.1f}" width="{bw:.1f}" '
                   f'height="{max(abs(y1 - y0), 1.5):.1f}" rx="3">'
                   f'<title>{esc(r["month"])}  {r["pct"]:+.2f}%</title></rect>')
        out.append(f'<text class="ax" x="{cx:.1f}" y="{h - 9}" '
                   f'text-anchor="middle">{esc(r["month"][5:7])}</text>')
    out.append("</svg>")
    return "".join(out)


def weights(positions, h=None):
    """A stacked bar of what the account is made of, biggest slice first."""
    rows = sorted(positions.items(), key=lambda kv: -kv[1].get("value", 0))
    total = sum(p.get("value", 0) for _, p in rows)
    if not rows or total <= 0:
        return _empty("Nothing held", 90)
    W, H = 900, 54
    out = [f'<svg class="chart weights" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Portfolio weights">']
    x = 0.0
    for i, (tk, p) in enumerate(rows):
        w = (p.get("value", 0) / total) * W
        out.append(f'<rect class="slice s{i % 8}" x="{x:.1f}" y="6" '
                   f'width="{max(w - 2, 1):.1f}" height="26" rx="3">'
                   f'<title>{esc(tk)}  {p.get("weight_pct", 0):.1f}%</title></rect>')
        if w > 46:
            out.append(f'<text class="slab" x="{x + w / 2 - 1:.1f}" y="46" '
                       f'text-anchor="middle">{esc(tk)}</text>')
        x += w
    out.append("</svg>")
    return "".join(out)
