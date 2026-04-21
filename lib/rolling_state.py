"""Rolling-window state for statusline metrics.

Stores a 60-minute ring of samples at ~/.claude/statusline-state.json.
Each sample: {"t": epoch_sec, "cost": float, "tokens_in": int,
              "tokens_out": int, "cache_read": int, "cache_creation": int}
"""

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

_STATE_PATH = Path.home() / ".claude" / "statusline-state.json"
_TMP_PATH = Path.home() / ".claude" / "statusline-state.json.tmp"
_LOCK_PATH = Path.home() / ".claude" / "statusline-state.json.lock"
_MAX_AGE_SECS = 3600  # 60-minute ring
_LOCK_TIMEOUT_SECS = 0.25
_LOCK_POLL_SECS = 0.01
_THREAD_LOCK = threading.Lock()


def _ensure_state_dir() -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass


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
        _ensure_state_dir()
        _TMP_PATH.write_text(text, encoding="utf-8")
        os.replace(str(_TMP_PATH), str(_STATE_PATH))
    except OSError:
        # If we can't write, silently skip — statusline must not crash
        pass


def _acquire_file_lock(lock_handle) -> bool:
    deadline = time.time() + _LOCK_TIMEOUT_SECS
    while True:
        try:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (BlockingIOError, OSError):
            if time.time() >= deadline:
                return False
            time.sleep(_LOCK_POLL_SECS)


def _release_file_lock(lock_handle) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def _state_write_lock():
    """Serialize read-modify-write cycles across threads and processes."""
    _ensure_state_dir()
    with _THREAD_LOCK:
        try:
            with _LOCK_PATH.open("a+b") as lock_handle:
                if _LOCK_PATH.stat().st_size == 0:
                    lock_handle.write(b"0")
                    lock_handle.flush()
                lock_handle.seek(0)

                if not _acquire_file_lock(lock_handle):
                    yield False
                    return

                try:
                    yield True
                finally:
                    _release_file_lock(lock_handle)
        except OSError:
            yield False


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
    with _state_write_lock() as locked:
        if not locked:
            return

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


# Minimum window span (seconds) before we trust a rolling rate.
# Too short → one expensive API call creates a spike like $800/hr.
_MIN_SPAN_SECS = 180  # 3 minutes

# Sanity cap: if computed rate exceeds this, treat as spike and return None
# (caller will fall back to lifetime session rate).
_MAX_PLAUSIBLE_RATE = 200.0  # $/hr


def rolling_rate(window_min: int = 10) -> "float | None":
    """Return $/hr over the last window_min minutes.

    Returns None if:
      - fewer than 2 samples in the window
      - the span is less than 3 minutes (not enough to smooth spikes)
      - the computed rate is above $200/hr (treated as a spike; caller
        should fall back to session lifetime rate)
    """
    state = _load()
    samples = _window_samples(state.get("samples", []), window_min)

    if len(samples) < 2:
        return None

    oldest = samples[0]
    latest = samples[-1]
    elapsed_secs = latest["t"] - oldest["t"]

    if elapsed_secs < _MIN_SPAN_SECS:
        return None

    cost_delta = latest["cost"] - oldest["cost"]
    if cost_delta < 0:
        # Cost went backwards — session reset or state corruption.
        return None

    elapsed_hours = elapsed_secs / 3600
    if elapsed_hours <= 0:
        return None

    rate = cost_delta / elapsed_hours
    if rate > _MAX_PLAUSIBLE_RATE:
        return None
    return rate


def rolling_tokens_out(window_min: int = 10) -> "int | None":
    """Return output-token delta over the last window_min minutes.

    Returns None if fewer than 2 samples or span < 3 minutes.
    """
    state = _load()
    samples = _window_samples(state.get("samples", []), window_min)

    if len(samples) < 2:
        return None

    oldest = samples[0]
    latest = samples[-1]
    elapsed_secs = latest["t"] - oldest["t"]

    if elapsed_secs < _MIN_SPAN_SECS:
        return None

    delta = latest["tokens_out"] - oldest["tokens_out"]
    return delta if delta >= 0 else None


def cache_delta(window_min: int = 5) -> "int | None":
    """Return cache_read delta over the last window_min minutes.

    Returns None if fewer than 2 samples, span < 1 minute, or delta is
    negative (session reset).
    """
    state = _load()
    samples = _window_samples(state.get("samples", []), window_min)

    if len(samples) < 2:
        return None

    oldest = samples[0]
    latest = samples[-1]
    elapsed_secs = latest["t"] - oldest["t"]

    # Cache delta uses a shorter 60s floor — it's a presence indicator,
    # not a rate, so short spans are fine.
    if elapsed_secs < 60:
        return None

    delta = latest["cache_read"] - oldest["cache_read"]
    return delta if delta >= 0 else None
