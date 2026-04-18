"""Rolling-window state for statusline metrics.

Stores a 60-minute ring of samples at ~/.claude/statusline-state.json.
Each sample: {"t": epoch_sec, "cost": float, "tokens_in": int,
              "tokens_out": int, "cache_read": int, "cache_creation": int}
"""

import json
import os
import time
from pathlib import Path

_STATE_PATH = Path.home() / ".claude" / "statusline-state.json"
_TMP_PATH = Path.home() / ".claude" / "statusline-state.json.tmp"
_MAX_AGE_SECS = 3600  # 60-minute ring


def _load() -> dict:
    """Load state from disk. Returns {"samples": []} on missing or corrupt file."""
    try:
        text = _STATE_PATH.read_text(encoding="utf-8")
        return json.loads(text)
    except FileNotFoundError:
        return {"samples": []}
    except json.JSONDecodeError:
        # Corrupt file — reset to empty
        return {"samples": []}


def _save(state: dict) -> None:
    """Atomically write state to disk."""
    text = json.dumps(state, separators=(",", ":"))
    try:
        _TMP_PATH.write_text(text, encoding="utf-8")
        os.replace(str(_TMP_PATH), str(_STATE_PATH))
    except OSError:
        # If we can't write, silently skip — statusline must not crash
        pass


def _window_samples(samples: list, window_min: int) -> list:
    """Return samples within the last window_min minutes, oldest-first."""
    cutoff = time.time() - window_min * 60
    return [s for s in samples if s["t"] >= cutoff]


def append_sample(
    cost: float,
    tokens_in: int,
    tokens_out: int,
    cache_read: int,
    cache_creation: int,
) -> None:
    """Append a new sample and evict entries older than 60 minutes."""
    state = _load()
    samples = state.get("samples", [])

    # Evict samples older than 60 minutes
    cutoff = time.time() - _MAX_AGE_SECS
    samples = [s for s in samples if s["t"] >= cutoff]

    samples.append({
        "t": time.time(),
        "cost": float(cost),
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "cache_read": int(cache_read),
        "cache_creation": int(cache_creation),
    })

    _save({"samples": samples})


def rolling_rate(window_min: int = 10) -> "float | None":
    """Return $/hr over last window_min minutes.

    Returns None if fewer than 2 samples exist in the window or the span
    is less than 1 minute (insufficient data).
    """
    state = _load()
    samples = _window_samples(state.get("samples", []), window_min)

    if len(samples) < 2:
        return None

    oldest = samples[0]
    latest = samples[-1]
    elapsed_secs = latest["t"] - oldest["t"]

    if elapsed_secs < 60:
        return None

    cost_delta = latest["cost"] - oldest["cost"]
    elapsed_hours = elapsed_secs / 3600
    return cost_delta / elapsed_hours if elapsed_hours > 0 else None


def rolling_tokens_out(window_min: int = 10) -> "int | None":
    """Return output-token delta over last window_min minutes.

    Returns None if fewer than 2 samples or span < 1 minute.
    """
    state = _load()
    samples = _window_samples(state.get("samples", []), window_min)

    if len(samples) < 2:
        return None

    oldest = samples[0]
    latest = samples[-1]
    elapsed_secs = latest["t"] - oldest["t"]

    if elapsed_secs < 60:
        return None

    return latest["tokens_out"] - oldest["tokens_out"]


def cache_delta(window_min: int = 5) -> "int | None":
    """Return cache_read delta over last window_min minutes.

    Returns None if fewer than 2 samples or span < 1 minute.
    """
    state = _load()
    samples = _window_samples(state.get("samples", []), window_min)

    if len(samples) < 2:
        return None

    oldest = samples[0]
    latest = samples[-1]
    elapsed_secs = latest["t"] - oldest["t"]

    if elapsed_secs < 60:
        return None

    return latest["cache_read"] - oldest["cache_read"]
