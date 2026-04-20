"""Tests for heartbeat telemetry logic in engines/python-engine.py.

These tests verify:
    1. The first heartbeat creates a local anonymous telemetry id and sends one ping.
    2. Existing telemetry ids are reused across heartbeats.
    3. When telemetry is disabled, no ping is sent and no files are created.
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
    """Redirect HEARTBEAT_PATH and TELEMETRY_ID_PATH to a temp directory
    and monkeypatch Path.home() to the same temp home.

    Returns (fake_home, heartbeat_path, telemetry_id_path).
    """
    _require_engine()

    fake_home = tmp_path / "home"
    fake_claude = fake_home / ".claude"
    fake_claude.mkdir(parents=True, exist_ok=True)

    fake_heartbeat = fake_claude / ".statusline-heartbeat"
    fake_id = fake_claude / ".statusline-telemetry-id"

    # Patch the module-level path constants directly so the function reads them
    monkeypatch.setattr(engine, "HEARTBEAT_PATH", fake_heartbeat)
    monkeypatch.setattr(engine, "TELEMETRY_ID_PATH", fake_id)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    yield fake_home, fake_heartbeat, fake_id


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

def test_first_heartbeat_creates_telemetry_id_and_sends_once(tmp_telemetry_paths):
    """First heartbeat should persist an anonymous id and send exactly one ping."""
    _require_engine()
    _, fake_heartbeat, fake_id = tmp_telemetry_paths

    assert not fake_id.exists(), "precondition: telemetry id must be absent"

    mock_popen = MagicMock()
    with patch("subprocess.Popen", mock_popen):
        engine.maybe_heartbeat({})

    assert mock_popen.call_count == 1, (
        f"Expected 1 heartbeat ping, got {mock_popen.call_count}"
    )

    payload = _parse_payload(mock_popen.call_args_list[0])

    assert payload["event"] == "heartbeat"
    assert payload["engine"] == "python"
    assert payload["v"] == "2.1"
    assert "id" in payload
    assert len(payload["id"]) == 16

    assert fake_id.exists(), "TELEMETRY_ID_PATH should be written after the first heartbeat"
    assert fake_heartbeat.exists(), "HEARTBEAT_PATH should be written after heartbeat"


def test_existing_telemetry_id_is_reused(tmp_telemetry_paths):
    """Existing anonymous ids should be reused instead of regenerated."""
    _require_engine()
    _, _, fake_id = tmp_telemetry_paths

    fake_id.write_text("0123456789abcdef")

    mock_popen = MagicMock()
    with patch("subprocess.Popen", mock_popen):
        engine.maybe_heartbeat({})

    assert mock_popen.call_count == 1, (
        f"Expected exactly 1 heartbeat ping, got {mock_popen.call_count}"
    )

    only_payload = _parse_payload(mock_popen.call_args_list[0])
    assert only_payload["event"] == "heartbeat"
    assert only_payload["id"] == "0123456789abcdef"


def test_telemetry_disabled_skips_both(tmp_telemetry_paths):
    """With telemetry=False, no Popen calls and no telemetry files created."""
    _require_engine()
    _, fake_heartbeat, fake_id = tmp_telemetry_paths

    assert not fake_id.exists(), "precondition: telemetry id absent"
    assert not fake_heartbeat.exists(), "precondition: heartbeat absent"

    mock_popen = MagicMock()
    with patch("subprocess.Popen", mock_popen):
        engine.maybe_heartbeat({"telemetry": False})

    assert mock_popen.call_count == 0, (
        f"Expected 0 Popen calls when telemetry disabled, got {mock_popen.call_count}"
    )
    assert not fake_id.exists(), "TELEMETRY_ID_PATH must NOT be created when telemetry disabled"
    assert not fake_heartbeat.exists(), "HEARTBEAT_PATH must NOT be created when telemetry disabled"
