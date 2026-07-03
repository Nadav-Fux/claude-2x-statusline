"""Stale-marker tests for the Claude 5h/weekly rate-limit row.

When the OAuth usage fetch fails, seg_rate_limits() silently falls back to the
last cached payload. Without a visible marker the 5h/weekly numbers can look
live for hours while actually being frozen. These tests lock in the '·stale'
indicator that build_rate_limits_line() now renders off ctx['usage_cache_age'].
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ENGINE_PATH = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_OK = True
except Exception as _exc:  # pragma: no cover - defensive
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)


def _require_engine():
    if not _IMPORT_OK:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    return _ANSI.sub("", s)


def _ctx(age):
    return {
        "usage_data": {
            "five_hour": {"utilization": 22.0, "resets_at": "2026-07-02T22:10:00+00:00"},
            "seven_day": {"utilization": 57.0, "resets_at": "2026-07-04T05:00:00+00:00"},
            "seven_day_sonnet": {"utilization": 0},
        },
        "usage_cache_age": age,
        "render_width": 200,
        "schedule": {"labels": {"five_hour": "5h interactive", "weekly": "weekly interactive"}},
        "stdin": {},
        "gateway": {},
    }


# ── _usage_stale_marker unit behavior ────────────────────────────────────────

@pytest.mark.parametrize("age", [None, 0, 60, 180, 599, 600])
def test_marker_absent_when_fresh_or_within_ttl(age):
    _require_engine()
    assert engine._usage_stale_marker({"usage_cache_age": age}) == ""


def test_marker_hours_format_includes_minutes():
    _require_engine()
    # 5h46m — the marker must preserve magnitude, not collapse to "5h".
    out = _strip(engine._usage_stale_marker({"usage_cache_age": 5.77 * 3600}))
    assert out.strip() == "·stale 5h 46m"


def test_marker_whole_hours_omit_minutes():
    _require_engine()
    out = _strip(engine._usage_stale_marker({"usage_cache_age": 6 * 3600}))
    assert out.strip() == "·stale 6h"


def test_marker_minutes_format():
    _require_engine()
    out = _strip(engine._usage_stale_marker({"usage_cache_age": 700}))
    assert out.strip() == "·stale 11m"


# ── integration through build_rate_limits_line ───────────────────────────────

def test_row_marks_stale_cache(monkeypatch):
    _require_engine()
    monkeypatch.setattr(engine, "_check_offloop_drain", lambda ctx, u: "")
    line = _strip(engine.build_rate_limits_line(_ctx(6 * 3600)))
    assert "·stale" in line
    # the marker rides inside the closing border, not past it
    assert line.rstrip().endswith("│")


def test_row_clean_when_fresh(monkeypatch):
    _require_engine()
    monkeypatch.setattr(engine, "_check_offloop_drain", lambda ctx, u: "")
    line = _strip(engine.build_rate_limits_line(_ctx(30)))
    assert "·stale" not in line
    assert "5h interactive" in line and "weekly interactive" in line


# ── keychain token selection (the actual freeze-fix path) ────────────────────

import json as _json
import types as _types


class _FakeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _claude_blob(token="tok-abc"):
    return _json.dumps({"claudeAiOauth": {"accessToken": token}})


_MCP_BLOB = _json.dumps({"mcpOAuth": {"sticklight": {"accessToken": ""}}})


def _install_fake_keychain(monkeypatch, *, first="", by_account=None, dump=""):
    """Route engine.subprocess.run for `security` calls to canned output.
    `first` = stdout for `find-generic-password -s SVC -w` (no -a).
    `by_account` = {acct: stdout} for `-a acct` reads. `dump` = dump-keychain."""
    by_account = by_account or {}

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["security", "find-generic-password"]:
            if "-a" in cmd:
                acct = cmd[cmd.index("-a") + 1]
                return _FakeProc(by_account.get(acct, ""))
            return _FakeProc(first)
        if cmd[:2] == ["security", "dump-keychain"]:
            return _FakeProc(dump)
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)


def test_token_from_json_helper():
    _require_engine()
    assert engine._claude_token_from_json(_claude_blob("x")) == "x"
    assert engine._claude_token_from_json(_MCP_BLOB) == ""       # MCP item → no claude token
    assert engine._claude_token_from_json("not json") == ""
    assert engine._claude_token_from_json("") == ""


def test_fast_path_first_match_has_token(monkeypatch):
    _require_engine()
    _install_fake_keychain(monkeypatch, first=_claude_blob("fast"))
    assert engine._keychain_claude_token() == "fast"


def test_empty_first_match_falls_back_to_username(monkeypatch):
    _require_engine()
    # First match is the empty MCP item; the real token lives under the OS user.
    monkeypatch.setattr("getpass.getuser", lambda: "nadavfux")
    _install_fake_keychain(
        monkeypatch, first=_MCP_BLOB, by_account={"nadavfux": _claude_blob("viauser")}
    )
    assert engine._keychain_claude_token() == "viauser"


def test_falls_back_to_dumpkeychain_when_username_differs(monkeypatch):
    _require_engine()
    monkeypatch.setattr("getpass.getuser", lambda: "someoneelse")
    dump = (
        'keychain: "login"\n'
        '    "acct"<blob>="unknown"\n'
        '    "svce"<blob>="Claude Code-credentials"\n'
        'keychain: "login"\n'
        '    "acct"<blob>="realacct"\n'
        '    "svce"<blob>="Claude Code-credentials"\n'
    )
    _install_fake_keychain(
        monkeypatch,
        first=_MCP_BLOB,
        by_account={"unknown": _MCP_BLOB, "realacct": _claude_blob("viadump")},
        dump=dump,
    )
    assert engine._keychain_claude_token() == "viadump"


def test_returns_empty_when_no_claude_item_anywhere(monkeypatch):
    _require_engine()
    monkeypatch.setattr("getpass.getuser", lambda: "nobody")
    dump = (
        'keychain: "login"\n'
        '    "acct"<blob>="unknown"\n'
        '    "svce"<blob>="Claude Code-credentials"\n'
    )
    _install_fake_keychain(monkeypatch, first=_MCP_BLOB, by_account={"unknown": _MCP_BLOB}, dump=dump)
    assert engine._keychain_claude_token() == ""


def test_accounts_parser_handles_hex_blob_and_scoping():
    _require_engine()
    dump = (
        'keychain: "login"\n'
        '    "acct"<blob>=0x6E61646176  "nadav"\n'            # hex "nadav" under our service
        '    "svce"<blob>="Claude Code-credentials"\n'
        'keychain: "login"\n'
        '    "acct"<blob>="someapp"\n'
        '    "svce"<blob>="Some Other Service"\n'             # different service → must be excluded
    )
    accts = engine._keychain_accounts_for_service(dump)
    assert accts == ["nadav"]
