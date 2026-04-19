"""Tests for first-run install ping logic in engines/python-engine.py.

These tests verify:
  1. When INSTALL_MARKER is absent, maybe_heartbeat fires an install ping
     followed by a heartbeat ping (two Popen calls).
  2. When INSTALL_MARKER already exists, only the heartbeat ping fires.
  3. When telemetry is disabled, no pings fire at all.
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# ── Load engine module ────────────────────────────────────────────────────────
_ENGINE_PATH = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_OK = True
except Exception as _exc:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)


def _require_engine():
    if not _IMPORT_OK:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_telemetry_paths(tmp_path, monkeypatch):
    """Redirect HEARTBEAT_PATH and INSTALL_MARKER to a temp directory
    and monkeypatch Path.home() to the same temp home.

    Returns (fake_home, heartbeat_path, install_marker_path).
    """
    _require_engine()

    fake_home = tmp_path / "home"
    fake_claude = fake_home / ".claude"
    fake_claude.mkdir(parents=True, exist_ok=True)

    fake_heartbeat = fake_claude / ".statusline-heartbeat"
    fake_marker = fake_claude / ".statusline-install-done"

    # Patch the module-level path constants directly so the function reads them
    monkeypatch.setattr(engine, "HEARTBEAT_PATH", fake_heartbeat)
    monkeypatch.setattr(engine, "INSTALL_MARKER", fake_marker)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    yield fake_home, fake_heartbeat, fake_marker


def _parse_payload(popen_call_args):
    """Extract and parse the JSON payload from a subprocess.Popen call.

    The curl invocation built by maybe_heartbeat uses:
        ["curl", ..., "-d", <json>, <url>]
    so the payload is the element immediately after "-d".
    """
    args_list = popen_call_args[0][0]  # positional first arg = list of cmd args
    d_index = args_list.index("-d")
    return json.loads(args_list[d_index + 1])


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_install_marker_missing_fires_install_event(tmp_telemetry_paths):
    """With no INSTALL_MARKER, expect two Popen calls: install then heartbeat."""
    _require_engine()
    _, fake_heartbeat, fake_marker = tmp_telemetry_paths

    assert not fake_marker.exists(), "precondition: marker must be absent"

    mock_popen = MagicMock()
    with patch("subprocess.Popen", mock_popen):
        engine.maybe_heartbeat({})

    assert mock_popen.call_count == 2, (
        f"Expected 2 Popen calls (install + heartbeat), got {mock_popen.call_count}"
    )

    first_payload = _parse_payload(mock_popen.call_args_list[0])
    second_payload = _parse_payload(mock_popen.call_args_list[1])

    assert first_payload["event"] == "install", (
        f"First call should be install ping, got event={first_payload['event']!r}"
    )
    assert first_payload["engine"] == "python"
    assert first_payload["v"] == "2.1"
    assert "id" in first_payload

    assert second_payload["event"] == "heartbeat", (
        f"Second call should be heartbeat ping, got event={second_payload['event']!r}"
    )
    assert second_payload["engine"] == "python"

    # Marker file must have been created
    assert fake_marker.exists(), "INSTALL_MARKER should be written after install ping"
    # Heartbeat file must also have been created
    assert fake_heartbeat.exists(), "HEARTBEAT_PATH should be written after heartbeat"


def test_install_marker_present_skips_install_event(tmp_telemetry_paths):
    """With INSTALL_MARKER already present, only the heartbeat ping fires."""
    _require_engine()
    _, fake_heartbeat, fake_marker = tmp_telemetry_paths

    # Pre-create the marker (simulates a machine that already ran install once)
    fake_marker.write_text("2026-01-01")

    mock_popen = MagicMock()
    with patch("subprocess.Popen", mock_popen):
        engine.maybe_heartbeat({})

    assert mock_popen.call_count == 1, (
        f"Expected exactly 1 Popen call (heartbeat only), got {mock_popen.call_count}"
    )

    only_payload = _parse_payload(mock_popen.call_args_list[0])
    assert only_payload["event"] == "heartbeat", (
        f"The single call should be heartbeat, got event={only_payload['event']!r}"
    )

    # Marker must remain (not be touched or removed)
    assert fake_marker.exists()


def test_telemetry_disabled_skips_both(tmp_telemetry_paths):
    """With telemetry=False, no Popen calls and no marker/heartbeat files created."""
    _require_engine()
    _, fake_heartbeat, fake_marker = tmp_telemetry_paths

    assert not fake_marker.exists(), "precondition: marker absent"
    assert not fake_heartbeat.exists(), "precondition: heartbeat absent"

    mock_popen = MagicMock()
    with patch("subprocess.Popen", mock_popen):
        engine.maybe_heartbeat({"telemetry": False})

    assert mock_popen.call_count == 0, (
        f"Expected 0 Popen calls when telemetry disabled, got {mock_popen.call_count}"
    )
    assert not fake_marker.exists(), "INSTALL_MARKER must NOT be created when telemetry disabled"
    assert not fake_heartbeat.exists(), "HEARTBEAT_PATH must NOT be created when telemetry disabled"
