"""
Water meter weekly usage chart generator.

Reads a log of JSON entries (one object per entry, possibly pretty-printed
across multiple lines) and produces an SVG bar chart of litres used per day
for the most recent 7-day window.

Notes on interpretation:
- Readings are cumulative meter values, taken Mon-Fri at 07:00.
- Daily usage = today's reading - previous valid reading.
- The Monday reading covers Sat + Sun + Mon usage. We split this evenly
  across those 3 days and shade them to indicate the value is estimated.
- Error entries (no `liters` field) are skipped. The next valid reading's
  delta is computed against the last valid cumulative reading, so usage
  is still attributable - we just can't break it down per day across the
  gap, so those days are shown as estimated/averaged too.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path


def parse_log(path: str) -> list[dict]:
    """Parse a file containing concatenated JSON objects (pretty-printed)."""
    text = Path(path).read_text()
    # Find each top-level {...} block. The objects are pretty-printed but
    # don't contain nested braces, so a simple brace-matching scan works.
    entries = []
    decoder = json.JSONDecoder()
    i = 0
    while i < len(text):
        # Skip whitespace between objects
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i >= len(text):
            break
        obj, end = decoder.raw_decode(text, i)
        entries.append(obj)
        i = end
    return entries


def compute_daily_usage(entries: list[dict], days: int = 7) -> list[dict]:
    """
    Return a list of {date, litres, estimated} dicts for the last `days`
    calendar days ending on the most recent reading date.
    """
    # Keep only valid readings, sorted by timestamp
    valid = []
    for e in entries:
        if "liters" in e and "timestamp" in e:
            ts = datetime.fromisoformat(e["timestamp"])
            valid.append((ts, e["liters"]))
    valid.sort(key=lambda x: x[0])

    if len(valid) < 2:
        raise ValueError("Need at least 2 valid readings to compute usage")

    # Window: 7 days ending on the day before the most recent reading
    # (a reading at Tue 7am covers Mon 7am - Tue 7am, so represents Mon's usage)
    end_date = valid[-1][0].date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)

    # Walk through consecutive valid readings and attribute the delta
    # across the days in between.
    # A reading on day D represents usage during day D-1 (and any
    # preceding skipped days). So we attribute the delta to the days
    # from d_prev .. d_curr - 1 inclusive.
    # day_usage[date] = (litres, estimated_flag)
    day_usage: dict = {}
    for (ts_prev, l_prev), (ts_curr, l_curr) in zip(valid, valid[1:]):
        delta = l_curr - l_prev
        d_prev = ts_prev.date()
        d_curr = ts_curr.date()
        gap_days = (d_curr - d_prev).days
        if gap_days <= 0:
            continue
        per_day = delta / gap_days
        estimated = gap_days > 1  # split = estimate
        # Attribute to each day from d_prev .. d_curr - 1
        for i in range(gap_days):
            d = d_prev + timedelta(days=i)
            day_usage[d] = (per_day, estimated)

    # Build the 7-day window result
    result = []
    d = start_date
    while d <= end_date:
        litres, estimated = day_usage.get(d, (None, False))
        result.append({
            "date": d,
            "litres": litres,
            "estimated": estimated,
        })
        d += timedelta(days=1)
    return result


def render_svg(days: list[dict], width: int = 720, height: int = 360,
               title: str = "Water usage (litres)") -> str:
    """Render the daily usage as an SVG bar chart."""
    margin = {"top": 40, "right": 24, "bottom": 60, "left": 64}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    values = [d["litres"] or 0 for d in days]
    max_val = max(values) if any(values) else 1
    # Round max up to a nice number for the y-axis
    nice_max = _nice_ceiling(max_val)

    n = len(days)
    # Tighten the gap when there are lots of bars
    bar_gap = 12 if n <= 10 else (6 if n <= 20 else 3)
    bar_w = (plot_w - bar_gap * (n - 1)) / n
    # For dense charts, only label every Nth bar's date and skip per-bar value labels
    label_every = 1 if n <= 10 else (2 if n <= 20 else 4)
    show_value_labels = n <= 10

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">',
        # Hatched pattern for estimated bars
        '<defs>',
        '<pattern id="hatch" patternUnits="userSpaceOnUse" width="6" height="6" '
        'patternTransform="rotate(45)">',
        '<rect width="6" height="6" fill="#7ab8e0"/>',
        '<line x1="0" y1="0" x2="0" y2="6" stroke="#ffffff" stroke-width="2"/>',
        '</pattern>',
        '</defs>',
        # Title
        f'<text x="{width/2}" y="22" text-anchor="middle" font-size="16" '
        f'font-weight="600" fill="#222">{title}</text>',
    ]

    # Y-axis gridlines + labels (5 steps)
    steps = 5
    for i in range(steps + 1):
        y_val = nice_max * i / steps
        y_px = margin["top"] + plot_h - (y_val / nice_max) * plot_h
        parts.append(
            f'<line x1="{margin["left"]}" y1="{y_px}" '
            f'x2="{margin["left"] + plot_w}" y2="{y_px}" '
            f'stroke="#e5e5e5" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{margin["left"] - 8}" y="{y_px + 4}" '
            f'text-anchor="end" fill="#666">{int(y_val)}</text>'
        )

    # Bars + x-axis labels
    for i, day in enumerate(days):
        x = margin["left"] + i * (bar_w + bar_gap)
        litres = day["litres"]
        if litres is None:
            # No data - draw a thin hollow placeholder
            parts.append(
                f'<rect x="{x}" y="{margin["top"] + plot_h - 4}" '
                f'width="{bar_w}" height="4" fill="none" '
                f'stroke="#bbb" stroke-dasharray="3,3"/>'
            )
            # On sparse (week) charts there's room for "no data";
            # on dense (month) charts a hyphen avoids overlap
            label_value = "no data" if n <= 10 else "-"
        else:
            h = (litres / nice_max) * plot_h
            y = margin["top"] + plot_h - h
            fill = "url(#hatch)" if day["estimated"] else "#2b8acb"
            parts.append(
                f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" '
                f'fill="{fill}" rx="2"/>'
            )
            # Value label on top of bar (only for sparse charts)
            if show_value_labels:
                parts.append(
                    f'<text x="{x + bar_w/2}" y="{y - 6}" text-anchor="middle" '
                    f'fill="#333" font-size="11">{int(round(litres))}</text>'
                )
            label_value = ""

        # Day label - skip some when dense
        if i % label_every == 0:
            date_obj = day["date"]
            if n <= 10:
                dow = date_obj.strftime("%a")
                dm = date_obj.strftime("%d %b")
                ly = margin["top"] + plot_h + 18
                parts.append(
                    f'<text x="{x + bar_w/2}" y="{ly}" text-anchor="middle" '
                    f'fill="#444" font-weight="500">{dow}</text>'
                )
                parts.append(
                    f'<text x="{x + bar_w/2}" y="{ly + 16}" text-anchor="middle" '
                    f'fill="#888" font-size="11">{dm}</text>'
                )
            else:
                # Compact: just day-of-month, with month if it's the 1st or first label
                dm = date_obj.strftime("%d")
                ly = margin["top"] + plot_h + 16
                parts.append(
                    f'<text x="{x + bar_w/2}" y="{ly}" text-anchor="middle" '
                    f'fill="#666" font-size="10">{dm}</text>'
                )
                if date_obj.day == 1 or i == 0:
                    parts.append(
                        f'<text x="{x + bar_w/2}" y="{ly + 14}" text-anchor="middle" '
                        f'fill="#888" font-size="10">{date_obj.strftime("%b")}</text>'
                    )
        if label_value:
            parts.append(
                f'<text x="{x + bar_w/2}" y="{margin["top"] + plot_h - 6}" '
                f'text-anchor="middle" fill="#999" font-size="11" '
                f'font-style="italic">{label_value}</text>'
            )

    # Axes
    parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"] + plot_h}" '
        f'x2="{margin["left"] + plot_w}" y2="{margin["top"] + plot_h}" '
        f'stroke="#444" stroke-width="1"/>'
    )

    # Legend
    lx = margin["left"]
    ly = height - 12
    parts.append(f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="#2b8acb" rx="2"/>')
    parts.append(f'<text x="{lx + 18}" y="{ly}" fill="#444">Measured</text>')
    parts.append(f'<rect x="{lx + 110}" y="{ly - 10}" width="12" height="12" fill="url(#hatch)" rx="2"/>')
    parts.append(f'<text x="{lx + 128}" y="{ly}" fill="#444">Estimated (averaged across gap)</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _nice_ceiling(x: float) -> float:
    """Round x up to a nice round number for axis scaling."""
    if x <= 0:
        return 1
    import math
    exp = math.floor(math.log10(x))
    base = 10 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if x <= m * base:
            return m * base
    return 10 * base


if __name__ == "__main__":
    import sys
    log_path = sys.argv[1] if len(sys.argv) > 1 else "meter.log"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = parse_log(log_path)

    # Week view
    week_days = compute_daily_usage(entries, days=7)
    week_svg = render_svg(
        week_days,
        width=720,
        height=360,
        title="Water usage - last 7 days (litres)",
    )
    (out_dir / "water_usage_week.svg").write_text(week_svg)

    # Month view (last 30 days)
    month_days = compute_daily_usage(entries, days=30)
    month_svg = render_svg(
        month_days,
        width=1000,
        height=380,
        title="Water usage - last 30 days (litres)",
    )
    (out_dir / "water_usage_month.svg").write_text(month_svg)

    # HTML page
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Water meter dashboard</title>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 24px; color: #222; background: #fafafa; }
  h1 { margin: 0 0 8px; font-size: 22px; }
  p.sub { margin: 0 0 24px; color: #666; }
  section { background: #fff; border: 1px solid #e5e5e5; border-radius: 8px;
            padding: 16px; margin-bottom: 24px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
  img { display: block; max-width: 100%; height: auto; }
</style>
</head>
<body>
  <h1>Water meter dashboard</h1>
  <section>
    <img src="water_usage_week.svg" alt="Water usage, last 7 days">
  </section>
  <section>
    <img src="water_usage_month.svg" alt="Water usage, last 30 days">
  </section>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html)

    print(f"Wrote files to {out_dir}/")
    print("Week view:")
    for d in week_days:
        l = d["litres"]
        marker = " (est)" if d["estimated"] else ""
        val = f"{int(round(l))} L" if l is not None else "no data"
        print(f"  {d['date']} {d['date'].strftime('%a')}: {val}{marker}")