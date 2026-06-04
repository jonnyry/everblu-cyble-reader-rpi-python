"""Tests for scripts/water_chart.py"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Load water_chart from scripts/ (not a package)
# --------------------------------------------------------------------------- #

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import water_chart as wc


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_entries(start: datetime, liters_per_day: list[int]) -> list[dict]:
    """Build daily reading entries from a start datetime and per-day deltas."""
    entries = []
    cumulative = 0
    entries.append({"timestamp": start.isoformat(), "liters": cumulative})
    for delta in liters_per_day:
        cumulative += delta
        start += timedelta(days=1)
        entries.append({"timestamp": start.isoformat(), "liters": cumulative})
    return entries


# --------------------------------------------------------------------------- #
# parse_log
# --------------------------------------------------------------------------- #

def test_parse_log_single_object(tmp_path):
    f = tmp_path / "log.json"
    f.write_text('{"timestamp": "2024-01-01T06:00:00", "liters": 1000}\n')
    entries = wc.parse_log(str(f))
    assert len(entries) == 1
    assert entries[0]["liters"] == 1000


def test_parse_log_multiple_objects(tmp_path):
    f = tmp_path / "log.json"
    f.write_text(
        '{"timestamp": "2024-01-01T06:00:00", "liters": 1000}\n'
        '{"timestamp": "2024-01-02T06:00:00", "liters": 1100}\n'
        '{"timestamp": "2024-01-03T06:00:00", "error": "timeout"}\n'
    )
    entries = wc.parse_log(str(f))
    assert len(entries) == 3
    assert entries[2].get("error") == "timeout"


def test_parse_log_pretty_printed(tmp_path):
    obj = {"timestamp": "2024-01-01T06:00:00", "liters": 999}
    f = tmp_path / "log.json"
    f.write_text(json.dumps(obj, indent=2))
    entries = wc.parse_log(str(f))
    assert entries[0]["liters"] == 999


# --------------------------------------------------------------------------- #
# compute_daily_usage
# --------------------------------------------------------------------------- #

def test_daily_usage_consecutive_readings():
    # 8 daily readings, 100 L/day each — no gaps so none are estimated.
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 7)
    result = wc.compute_daily_usage(entries, days=7)
    assert len(result) == 7
    for day in result:
        assert day["litres"] == pytest.approx(100)
        assert day["estimated"] is False


def test_daily_usage_window_dates():
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 7)
    result = wc.compute_daily_usage(entries, days=7)
    assert result[0]["date"] == date(2024, 1, 1)
    assert result[-1]["date"] == date(2024, 1, 7)


def test_daily_usage_gap_yields_estimated():
    # Single gap of 7 days — all days marked estimated.
    entries = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 0},
        {"timestamp": "2024-01-08T06:00:00", "liters": 700},
    ]
    result = wc.compute_daily_usage(entries, days=7)
    assert all(d["estimated"] for d in result)
    assert all(d["litres"] == pytest.approx(100) for d in result)


def test_daily_usage_error_entries_skipped():
    # Error entry (no "liters") must be ignored; the gap covers Jan 1 -> Jan 8.
    entries = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 0},
        {"timestamp": "2024-01-04T06:00:00", "error": "timeout"},
        {"timestamp": "2024-01-08T06:00:00", "liters": 700},
    ]
    result = wc.compute_daily_usage(entries, days=7)
    assert all(d["estimated"] for d in result)
    assert all(d["litres"] == pytest.approx(100) for d in result)


def test_daily_usage_missing_day_in_window():
    # Reading on Jan 1 and Jan 9; window is Jan 2-8 (days=7).
    # Jan 2-8 all get 100 L/day (estimated).
    entries = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 0},
        {"timestamp": "2024-01-09T06:00:00", "liters": 800},
    ]
    result = wc.compute_daily_usage(entries, days=7)
    assert result[0]["date"] == date(2024, 1, 2)
    assert result[-1]["date"] == date(2024, 1, 8)
    assert all(d["estimated"] for d in result)


def test_daily_usage_none_for_days_before_readings():
    # Readings only cover the last few days of the window.
    # Days before first reading have no data (None litres).
    entries = [
        {"timestamp": "2024-01-05T06:00:00", "liters": 0},
        {"timestamp": "2024-01-08T06:00:00", "liters": 300},
    ]
    result = wc.compute_daily_usage(entries, days=7)
    # end_date = Jan 7; start_date = Jan 1
    none_days = [d for d in result if d["litres"] is None]
    data_days = [d for d in result if d["litres"] is not None]
    assert len(none_days) > 0
    assert len(data_days) > 0


def test_daily_usage_too_few_readings_raises():
    with pytest.raises(ValueError, match="at least 2"):
        wc.compute_daily_usage([{"timestamp": "2024-01-01T06:00:00", "liters": 0}])


def test_daily_usage_no_valid_entries_raises():
    with pytest.raises(ValueError):
        wc.compute_daily_usage([{"timestamp": "2024-01-01T06:00:00", "error": "x"}])


def test_daily_usage_30_days():
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 30)
    result = wc.compute_daily_usage(entries, days=30)
    assert len(result) == 30


# --------------------------------------------------------------------------- #
# compute_monthly_usage
# --------------------------------------------------------------------------- #

def test_monthly_usage_single_full_month():
    # Gap covers Jan 2024: 31 days × 100 L/day = 3100 L.
    entries = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 0},
        {"timestamp": "2024-02-01T06:00:00", "liters": 3100},
    ]
    result = wc.compute_monthly_usage(entries)
    assert len(result) == 12
    jan = next(r for r in result if r["year"] == 2024 and r["month"] == 1)
    assert jan["litres"] == pytest.approx(3100)


def test_monthly_usage_no_data_months_are_none():
    entries = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 0},
        {"timestamp": "2024-02-01T06:00:00", "liters": 3100},
    ]
    result = wc.compute_monthly_usage(entries)
    # Months before Jan 2024 have no readings -> litres = None
    no_data = [r for r in result if r["year"] < 2024]
    assert all(r["litres"] is None for r in no_data)


def test_monthly_usage_always_returns_12_months():
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 365)
    result = wc.compute_monthly_usage(entries)
    assert len(result) == 12


def test_monthly_usage_months_in_order():
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 365)
    result = wc.compute_monthly_usage(entries)
    for i in range(len(result) - 1):
        y0, m0 = result[i]["year"], result[i]["month"]
        y1, m1 = result[i + 1]["year"], result[i + 1]["month"]
        assert (y0, m0) < (y1, m1)


def test_monthly_usage_too_few_readings_raises():
    with pytest.raises(ValueError):
        wc.compute_monthly_usage([{"timestamp": "2024-01-01T06:00:00", "liters": 0}])


# --------------------------------------------------------------------------- #
# _nice_ceiling
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("x, expected", [
    (0,    1),
    (0.0,  1),
    (1,    1),
    (3,    5),
    (10,   10),
    (11,   20),
    (25,   25),
    (99,   100),
    (100,  100),
    (101,  200),
    (250,  250),
    (999,  1000),
    (1000, 1000),
    (1001, 2000),
])
def test_nice_ceiling(x, expected):
    assert wc._nice_ceiling(x) == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# render_svg
# --------------------------------------------------------------------------- #

def _week_days(start: date = date(2024, 1, 1), n: int = 7, litres: int = 100) -> list[dict]:
    return [
        {"date": start + timedelta(days=i), "litres": litres, "estimated": False}
        for i in range(n)
    ]


def test_render_svg_is_valid_svg():
    svg = wc.render_svg(_week_days())
    assert svg.strip().startswith("<svg")
    assert "</svg>" in svg


def test_render_svg_contains_title():
    svg = wc.render_svg(_week_days(), title="My Chart")
    assert "My Chart" in svg


def test_render_svg_estimated_uses_hatch_pattern():
    days = [
        {"date": date(2024, 1, i + 1), "litres": 100, "estimated": True}
        for i in range(7)
    ]
    svg = wc.render_svg(days)
    assert "url(#hatch)" in svg
    assert 'id="hatch"' in svg


def test_render_svg_none_litres_shows_no_data_label():
    days = [{"date": date(2024, 1, 1), "litres": None, "estimated": False}] + _week_days(
        date(2024, 1, 2), 6
    )
    svg = wc.render_svg(days)
    assert "no data" in svg


def test_render_svg_30_days_uses_hyphen_for_missing():
    days = [{"date": date(2024, 1, i + 1), "litres": None if i == 0 else 100, "estimated": False}
            for i in range(30)]
    svg = wc.render_svg(days)
    # Dense chart: missing bar label is "-" not "no data"
    assert ">-<" in svg


def test_render_svg_all_zero_does_not_crash():
    days = [{"date": date(2024, 1, i + 1), "litres": 0, "estimated": False} for i in range(7)]
    svg = wc.render_svg(days)
    assert "</svg>" in svg


# --------------------------------------------------------------------------- #
# render_monthly_svg
# --------------------------------------------------------------------------- #

def _month_data(n: int = 12) -> list[dict]:
    months = []
    for i in range(n):
        m = (i % 12) + 1
        y = 2023 + (i // 12)
        months.append({"year": y, "month": m, "litres": 3000, "estimated": False})
    return months


def test_render_monthly_svg_is_valid_svg():
    svg = wc.render_monthly_svg(_month_data())
    assert svg.strip().startswith("<svg")
    assert "</svg>" in svg


def test_render_monthly_svg_contains_title():
    svg = wc.render_monthly_svg(_month_data(), title="Year Chart")
    assert "Year Chart" in svg


def test_render_monthly_svg_none_month_does_not_crash():
    data = _month_data()
    data[3]["litres"] = None
    svg = wc.render_monthly_svg(data)
    assert "</svg>" in svg


# --------------------------------------------------------------------------- #
# _point_in_drop
# --------------------------------------------------------------------------- #

def test_point_in_drop_center_circle_is_inside():
    size = 180
    cx = size // 2                   # 90
    cy = int(size * 0.62)            # 111
    assert wc._point_in_drop(cx, cy, size) is True


def test_point_in_drop_corner_is_outside():
    assert wc._point_in_drop(0, 0, 180) is False
    assert wc._point_in_drop(179, 179, 180) is False


def test_point_in_drop_tip_midpoint_is_inside():
    # Centre of drop at roughly (cx, top_y + half) — in the triangle region.
    size = 180
    cx = size // 2
    top_y = int(size * 0.11)
    cy_circle = int(size * 0.62)
    mid_y = (top_y + cy_circle) // 2
    assert wc._point_in_drop(cx, mid_y, size) is True


# --------------------------------------------------------------------------- #
# render_manifest
# --------------------------------------------------------------------------- #

def test_render_manifest_is_valid_json():
    manifest = wc.render_manifest()
    data = json.loads(manifest)
    assert data["name"] == "Water Meter Dashboard"
    assert any(icon["sizes"] == "192x192" for icon in data["icons"])
    assert any(icon["sizes"] == "512x512" for icon in data["icons"])


# --------------------------------------------------------------------------- #
# _last_n_readings
# --------------------------------------------------------------------------- #

def test_last_n_readings_filters_invalid():
    entries = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 1000},
        {"timestamp": "2024-01-02T06:00:00", "error": "timeout"},  # no liters
        {"timestamp": "2024-01-03T06:00:00", "liters": 1200},
    ]
    result = wc._last_n_readings(entries, n=7)
    assert len(result) == 2
    assert all("liters" in r for r in result)


def test_last_n_readings_returns_most_recent():
    entries = [{"timestamp": f"2024-01-{i+1:02d}T06:00:00", "liters": i * 100}
               for i in range(10)]
    result = wc._last_n_readings(entries, n=3)
    assert len(result) == 3
    assert result[-1]["liters"] == 900


def test_last_n_readings_sorted_by_timestamp():
    entries = [
        {"timestamp": "2024-01-03T06:00:00", "liters": 300},
        {"timestamp": "2024-01-01T06:00:00", "liters": 100},
        {"timestamp": "2024-01-02T06:00:00", "liters": 200},
    ]
    result = wc._last_n_readings(entries, n=7)
    timestamps = [r["timestamp"] for r in result]
    assert timestamps == sorted(timestamps)


# --------------------------------------------------------------------------- #
# _render_readings_table
# --------------------------------------------------------------------------- #

def test_render_readings_table_newest_first():
    readings = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 1000},
        {"timestamp": "2024-01-02T06:00:00", "liters": 1100},
        {"timestamp": "2024-01-03T06:00:00", "liters": 1250},
    ]
    html = wc._render_readings_table(readings)
    # Newest first: Jan 3, Jan 2, Jan 1
    idx3 = html.index("03 Jan")
    idx2 = html.index("02 Jan")
    idx1 = html.index("01 Jan")
    assert idx3 < idx2 < idx1


def test_render_readings_table_delta_computed_correctly():
    readings = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 1000},
        {"timestamp": "2024-01-02T06:00:00", "liters": 1150},
    ]
    html = wc._render_readings_table(readings)
    assert "150" in html


def test_render_readings_table_oldest_row_has_no_delta():
    readings = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 1000},
        {"timestamp": "2024-01-02T06:00:00", "liters": 1100},
    ]
    html = wc._render_readings_table(readings)
    assert "—" in html


def test_render_readings_table_skip_first():
    readings = [
        {"timestamp": "2024-01-01T06:00:00", "liters": 1000},
        {"timestamp": "2024-01-02T06:00:00", "liters": 1100},
        {"timestamp": "2024-01-03T06:00:00", "liters": 1250},
    ]
    html = wc._render_readings_table(readings, skip_first=True)
    # Jan 1 should not appear as a rendered row
    assert "01 Jan" not in html
    assert "02 Jan" in html
    assert "03 Jan" in html


# --------------------------------------------------------------------------- #
# render_html (smoke test)
# --------------------------------------------------------------------------- #

def test_render_html_contains_chart_images():
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 7)
    week_days = wc.compute_daily_usage(entries, days=7)
    html = wc.render_html(datetime(2024, 1, 8, 12, 0), week_days, entries)
    assert wc.WEEK_SVG in html
    assert wc.MONTH_SVG in html
    assert "Water meter dashboard" in html


def test_render_html_contains_generated_timestamp():
    entries = _make_entries(datetime(2024, 1, 1, 6), [100] * 7)
    week_days = wc.compute_daily_usage(entries, days=7)
    generated_at = datetime(2024, 1, 8, 14, 30)
    html = wc.render_html(generated_at, week_days, entries)
    assert "08-Jan-2024 14:30" in html
