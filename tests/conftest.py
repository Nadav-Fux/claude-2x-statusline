"""
Shared pytest fixtures for claude-2x-statusline tests.

sys.path manipulation: both `lib/` and `engines/` live two directories above
this file (at repo root).  We insert the repo root so that:
  - `import lib.rolling_state` resolves to  <repo>/lib/rolling_state.py
  - importlib can load <repo>/engines/python-engine.py directly
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# ── sys.path ─────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Fixed "now" fixtures ──────────────────────────────────────────────────────
# 2026-04-19 14:00:00 UTC  (a Sunday)
FIXED_UTC_EPOCH = 1776254400  # 2026-04-19 14:00:00 UTC
FIXED_UTC_DT = datetime(2026, 4, 19, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_now():
    """Monkeypatch datetime.now and time.time to a fixed instant.

    Both lib.rolling_state and the engine call time.time() / datetime.now().
    Patching at the module level after import keeps everything consistent.
    """
    with (
        patch("time.time", return_value=float(FIXED_UTC_EPOCH)),
        patch("datetime.datetime", wraps=datetime) as mock_dt,
    ):
        # Keep all datetime class methods working; only override now()
        mock_dt.now.return_value = FIXED_UTC_DT
        mock_dt.now.side_effect = lambda tz=None: (
            FIXED_UTC_DT.astimezone(tz) if tz else FIXED_UTC_DT
        )
        yield FIXED_UTC_EPOCH, FIXED_UTC_DT


# ── Temporary state-file fixture ─────────────────────────────────────────────

@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    """Redirect ~/.claude/statusline-state.json to a temp directory.

    Strategy: monkeypatch Path.home() so that every ``Path.home() / ...``
    call inside lib.rolling_state resolves under tmp_path instead.
    Also re-derives the module-level _STATE_PATH, _TMP_PATH, and _LOCK_PATH
    after the patch so calls within the same test see the right paths.
    """
    fake_home = tmp_path / "home"
    fake_claude = fake_home / ".claude"
    fake_claude.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    # If rolling_state is already imported, refresh its module-level paths
    if "lib.rolling_state" in sys.modules:
        rs = sys.modules["lib.rolling_state"]
        rs._STATE_PATH = fake_home / ".claude" / "statusline-state.json"
        rs._TMP_PATH = fake_home / ".claude" / "statusline-state.json.tmp"
        rs._LOCK_PATH = fake_home / ".claude" / "statusline-state.json.lock"

    yield fake_home, fake_claude / "statusline-state.json"


# ── Convenience helpers exposed to tests ─────────────────────────────────────

def write_state(state_path: Path, samples: list) -> None:
    """Write a pre-built sample list to the state file."""
    state_path.write_text(
        json.dumps({"samples": samples}), encoding="utf-8"
    )


def make_sample(t: float, cost: float = 0.0, tokens_in: int = 0,
                tokens_out: int = 0, cache_read: int = 0,
                cache_creation: int = 0) -> dict:
    """Build a single sample dict."""
    return {
        "t": t,
        "cost": cost,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
    }
