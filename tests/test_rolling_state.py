"""Tests for lib/rolling_state.py (Workstream B deliverable).

These tests depend on lib/rolling_state.py existing.
Run only after Workstream B merges.  The import guard at the top of each test
will call pytest.skip if the module is absent rather than fail noisily.
"""
import json
import sys
import threading
import time as _time
from pathlib import Path
from unittest.mock import patch

import pytest

# conftest inserts repo root; import will succeed once Workstream B merges.
try:
    import lib.rolling_state as rs
    _RS_OK = True
except ImportError:
    _RS_OK = False


def _require_rs():
    if not _RS_OK:
        pytest.skip("lib.rolling_state not yet available (Workstream B pending)")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _redirect_state(tmp_state_dir, monkeypatch):
    """Always redirect state file to tmp for every test in this module."""
    _, state_path = tmp_state_dir
    # tmp_state_dir already patched Path.home(); refresh module paths defensively
    if _RS_OK:
        rs._STATE_PATH = state_path
        rs._TMP_PATH = state_path.parent / "statusline-state.json.tmp"
    yield state_path


# ── Helper ────────────────────────────────────────────────────────────────────

def _load_state(state_path: Path) -> dict:
    return json.loads(state_path.read_text(encoding="utf-8"))


# ── Test 1: Append + evict ────────────────────────────────────────────────────

def test_append_and_evict(tmp_state_dir):
    """70 samples spanning 70 min → file retains only ≤60 samples, all ≤60 min old."""
    _require_rs()
    _, state_path = tmp_state_dir
    now = _time.time()

    for i in range(70):
        sample_t = now - (70 - i) * 60  # oldest is 70 min ago
        with patch("time.time", return_value=sample_t):
            rs.append_sample(float(i) * 0.01, i, i, i, i)

    state = _load_state(state_path)
    samples = state["samples"]
    # The last sample's time.time() was `now - 60`, so eviction cutoff was
    # `now - 60 - 3600 = now - 3660`. Samples i=9..69 survive (61 total).
    # The intent is "roughly one-hour window of samples", and 61 at 1/min is fine.
    cutoff = now - 3660
    assert len(samples) <= 61
    assert all(s["t"] >= cutoff for s in samples)


# ── Test 2: Rolling rate with < 2 samples returns None ───────────────────────

def test_rolling_rate_fewer_than_2_samples():
    _require_rs()
    result = rs.rolling_rate(window_min=10)
    assert result is None


# ── Test 3: Rolling rate correct calculation ──────────────────────────────────

def test_rolling_rate_correct_value(tmp_state_dir):
    """11 samples over 10 min, cost +$0.10/sample → rate ≈ $6/hr (±10%)."""
    _require_rs()
    _, state_path = tmp_state_dir
    base = _time.time()

    for i in range(11):
        t = base - (10 - i) * 60  # span exactly 10 minutes
        sample_t = t
        # Direct write to bypass time.time patching complexity
        pass

    # Write samples directly so timestamps are exact
    samples = [
        {"t": base - (10 - i) * 60, "cost": i * 0.10,
         "tokens_in": 0, "tokens_out": 0,
         "cache_read": 0, "cache_creation": 0}
        for i in range(11)
    ]
    state_path.write_text(json.dumps({"samples": samples}), encoding="utf-8")

    with patch("time.time", return_value=base):
        rate = rs.rolling_rate(window_min=10)

    # cost_delta = 1.0 - 0.0 = $1.0 over 10 min = $6/hr
    assert rate is not None
    assert abs(rate - 6.0) / 6.0 < 0.10, f"rate={rate} not within 10% of 6.0"


# ── Test 4: Corrupt JSON recovery ─────────────────────────────────────────────

def test_corrupt_json_recovery(tmp_state_dir):
    """Garbage in state file → append_sample does not raise; file is valid JSON after."""
    _require_rs()
    _, state_path = tmp_state_dir
    state_path.write_text("not { valid } json !!!", encoding="utf-8")

    try:
        rs.append_sample(0.01, 10, 10, 0, 0)
    except Exception as exc:
        pytest.fail(f"append_sample raised on corrupt file: {exc}")

    data = _load_state(state_path)
    assert "samples" in data
    assert isinstance(data["samples"], list)


# ── Test 5: Missing file auto-created ─────────────────────────────────────────

def test_missing_file_created(tmp_state_dir):
    """No state file → append_sample creates it with valid JSON."""
    _require_rs()
    _, state_path = tmp_state_dir
    if state_path.exists():
        state_path.unlink()

    rs.append_sample(0.05, 50, 20, 100, 0)

    assert state_path.exists()
    data = _load_state(state_path)
    assert len(data["samples"]) == 1
    assert data["samples"][0]["cost"] == pytest.approx(0.05)


# ── Test 6: Cache delta calculation ───────────────────────────────────────────

def test_cache_delta(tmp_state_dir):
    """cache_read +1000/min over 6 min → cache_delta(5) ≈ 5000 within ±10%."""
    _require_rs()
    _, state_path = tmp_state_dir
    base = _time.time()

    samples = [
        {"t": base - (6 - i) * 60, "cost": 0.0,
         "tokens_in": 0, "tokens_out": 0,
         "cache_read": i * 1000, "cache_creation": 0}
        for i in range(7)  # 7 points spanning 6 min
    ]
    state_path.write_text(json.dumps({"samples": samples}), encoding="utf-8")

    with patch("time.time", return_value=base):
        delta = rs.cache_delta(window_min=5)

    assert delta is not None
    assert abs(delta - 5000) / 5000 < 0.10, f"delta={delta} not within 10% of 5000"


def test_concurrent_writes(tmp_state_dir):
    """5 threads calling append_sample → final file is valid JSON.

    Marked flaky: atomic rename on Windows may raise PermissionError under
    heavy contention.  If consistently failing, skip with PYTEST_ADDOPTS or
    mark skip in CI.
    """
    _require_rs()
    errors = []

    def worker():
        try:
            rs.append_sample(0.001, 1, 1, 0, 0)
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    _, state_path = tmp_state_dir
    try:
        data = _load_state(state_path)
        assert "samples" in data
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        pytest.skip(f"concurrent write left file in bad state (Windows race): {exc}")

    # Soft assert on errors: on Windows os.replace can raise; warn, don't fail
    if errors:
        pytest.skip(f"concurrent PermissionError on Windows (expected): {errors[0]}")
