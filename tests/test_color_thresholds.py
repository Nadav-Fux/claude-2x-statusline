"""Window-aware usage-bar color thresholds (owner-approved adoption item 1).

Windows longer than a day (weekly/monthly/token-quota) must warn earlier --
red >=75 / yellow >=45 -- than sub-day windows like the Claude 5h bucket,
which keep the tighter red >=80 / yellow >=50. See color_for_pct and
_is_long_window_label in engines/python-engine.py.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ENGINE = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

_strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)


@pytest.mark.parametrize("label,expected_long", [
    ("5h", False),
    ("1h", False),
    ("12h", False),
    ("7d", True),
    ("30d", True),
    ("weekly", True),
    ("wk", True),
    ("tok", True),
    ("", False),
    (None, False),
])
def test_is_long_window_label(label, expected_long):
    assert engine._is_long_window_label(label) is expected_long


@pytest.mark.parametrize("pct,expected", [
    (0, engine.GREEN),
    (49, engine.GREEN),
    (50, engine.YELLOW),
    (79, engine.YELLOW),
    (80, engine.RED),
    (100, engine.RED),
])
def test_color_for_pct_short_window_thresholds_unchanged(pct, expected):
    assert engine.color_for_pct(pct) == expected
    assert engine.color_for_pct(pct, long_window=False) == expected


@pytest.mark.parametrize("pct,expected", [
    (0, engine.GREEN),
    (44, engine.GREEN),
    (45, engine.YELLOW),
    (48, engine.YELLOW),  # short window would still be GREEN at 48%
    (74, engine.YELLOW),
    (75, engine.RED),
    (76, engine.RED),  # short window would still be YELLOW at 76%
    (100, engine.RED),
])
def test_color_for_pct_long_window_thresholds_are_earlier(pct, expected):
    assert engine.color_for_pct(pct, long_window=True) == expected


def test_build_usage_bar_colors_filled_segment_by_long_window():
    short_bar = engine.build_usage_bar(48, width=10)
    long_bar = engine.build_usage_bar(48, width=10, long_window=True)
    assert short_bar.startswith(engine.GREEN)
    assert long_bar.startswith(engine.YELLOW)


def _rate_limits_ctx(fh_pct, sd_pct, sds_pct=0):
    return {
        "usage_data": {
            "five_hour": {"utilization": fh_pct, "resets_at": ""},
            "seven_day": {"utilization": sd_pct, "resets_at": ""},
            "seven_day_sonnet": {"utilization": sds_pct},
        },
        "gateway": {"foreign": False},
        "schedule": {},
        "render_width": 0,
    }


def test_rate_limits_line_5h_stays_green_but_weekly_turns_yellow_at_48pct():
    out = _strip(engine.build_rate_limits_line(_rate_limits_ctx(48, 48)))
    # Line 1: "5h" bucket. Line 2: "weekly" bucket. Both show "48%" but only
    # the raw (pre-strip) rendering carries the color -- re-render unstripped
    # to inspect the ANSI prefix directly around each occurrence.
    raw = engine.build_rate_limits_line(_rate_limits_ctx(48, 48))
    assert f"{engine.GREEN}48%" in raw or f"{engine.GREEN} 48%" in raw
    assert f"{engine.YELLOW}48%" in raw or f"{engine.YELLOW} 48%" in raw
    assert "48%" in out


def test_rate_limits_line_sonnet_subrow_uses_long_window_thresholds():
    raw = engine.build_rate_limits_line(_rate_limits_ctx(10, 10, sds_pct=48))
    # The sonnet sub-row resets on the same weekly clock, so it must also use
    # the long-window (earlier) thresholds -- yellow at 48%, not green.
    assert f"{engine.YELLOW} 48%" in raw


def test_external_provider_row_colors_by_window_label():
    row_short = {
        "display": "bars",
        "parts": [{"kind": "window", "label": "5h", "pct": 48}],
    }
    row_long = {
        "display": "bars",
        "parts": [{"kind": "window", "label": "7d", "pct": 48}],
    }
    assert f"{engine.GREEN}▰" in engine._render_external_provider_parts(row_short)
    assert f"{engine.YELLOW}▰" in engine._render_external_provider_parts(row_long)


def test_external_provider_compact_metric_colors_by_window_label():
    row = {
        "display": "compact",
        "parts": [
            {"kind": "label", "label": "GLM"},
            {"kind": "metric", "label": "5h", "pct": 48},
            {"kind": "metric", "label": "tok", "pct": 48},
        ],
    }
    rendered = engine._render_external_provider_parts(row)
    assert f"{engine.GREEN}48%" in rendered
    assert f"{engine.YELLOW}48%" in rendered
