"""seg_eff: efficiency dots (owner-approved adoption item 3).

A 5-dot scale derived from the cache-reuse ratio seg_cache_hit already
computes (stashed on ctx["cache_hit_pct"]), mapped 0-100% -> 0-5 filled
purple dots with round-half-up (so the 50% boundary rounds to 3 dots, not
2 -- plain round() in Python uses banker's rounding and would get this
wrong). No letters, no "grade" wording anywhere -- just dots.
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


@pytest.mark.parametrize("pct,dots", [
    (0, "○○○○○"),
    (10, "●○○○○"),
    (49, "●●○○○"),   # 49/100*5 = 2.45 -> rounds down to 2
    (50, "●●●○○"),   # 50/100*5 = 2.5  -> round-half-UP to 3, not banker's-round to 2
    (90, "●●●●●"),   # 90/100*5 = 4.5  -> rounds up to 5
    (100, "●●●●●"),
])
def test_eff_dots_mapping(pct, dots):
    out = _strip(engine.seg_eff({"cache_hit_pct": pct}))
    assert out == f"eff {dots}"


def test_eff_dots_are_purple():
    raw = engine.seg_eff({"cache_hit_pct": 50})
    assert engine.PURPLE in raw
    # No grade letters anywhere in the rendered segment.
    assert not re.search(r"\b[A-F][+-]?\b", _strip(raw))


def test_eff_hides_when_cache_hit_pct_is_absent():
    # Mirrors seg_cache_hit's own "not enough data" guard: no cache_hit_pct
    # on ctx means seg_cache_hit itself returned "" upstream, so eff must
    # follow suit rather than show a misleading score.
    assert engine.seg_eff({}) == ""


def test_build_metrics_line_wires_eff_after_cache_hit(monkeypatch):
    """build_metrics_line must run seg_cache_hit before seg_eff so eff can
    read the ratio the former stashes on ctx -- not recompute it."""
    ctx = {
        "stdin": {
            "cost": {},
            "context_window": {
                "current_usage": {
                    "cache_read_input_tokens": 5000,
                    "cache_creation_input_tokens": 5000,
                }
            },
        },
        "gateway": {},
        "render_width": 0,
    }
    line = engine.build_metrics_line(ctx)
    assert ctx.get("cache_hit_pct") == 50
    assert "eff ●●●○○" in _strip(line)
