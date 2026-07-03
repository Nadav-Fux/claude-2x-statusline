"""Context-window resolution: a [1m] session must not read as ~full at ~19%.

Claude Code can report context_window_size=200000 on stdin even for a 1M
session; trusting it mis-scales the % ~5x and fires false "context full"
pressure (and Haiku-narrator "CF" messages). _resolve_ctx_window() overrides
the wrong stdin size using the window encoded in the model id/display name.
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


def _ctx(display, mid, size, used):
    return {
        "stdin": {
            "model": {"display_name": display, "id": mid},
            "context_window": {
                "context_window_size": size,
                "current_usage": {"input_tokens": used},
            },
        },
        "config": {"tier": "full"},
    }


@pytest.mark.parametrize("display,mid", [
    ("Opus 4.8", "claude-opus-4-8[1m]"),          # marker only in id
    ("Opus 4.8 (1M context)", "claude-opus-4-8"),  # marker only in display
])
def test_1m_overrides_wrong_stdin_size(display, mid):
    # stdin lies with 200000; real window is 1M.
    assert engine._resolve_ctx_window(_ctx(display, mid, 200000, 190000)) == 1_000_000
    out = _strip(engine.seg_context(_ctx(display, mid, 200000, 190000)))
    assert "1.0M" in out and "19%" in out and "95%" not in out


def test_plain_200k_model_unchanged():
    ctx = _ctx("Sonnet 4.6", "claude-sonnet-4-6", 200000, 100000)
    assert engine._resolve_ctx_window(ctx) == 200000
    assert "50%" in _strip(engine.seg_context(ctx))


def test_500k_context_marker():
    assert engine._model_window_from_name("Some Model (500k context)") == 500_000


def test_version_numbers_never_false_match():
    # '4-8' / 'claude-sonnet-4-6' must not be read as a window.
    assert engine._model_window_from_name("Opus 4.8") == 0
    assert engine._model_window_from_name("claude-sonnet-4-6") == 0
