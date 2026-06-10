"""Remote schedule banner rendering tests."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

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


def _ctx(local_date: str, schedule: dict) -> dict:
    return {"local_time": datetime.fromisoformat(local_date), "schedule": schedule}


def test_python_banner_array_honors_expiry_dates():
    _require_engine()
    schedule = {
        "banners": [
            {"text": "SDK credit cutover Jun 15", "expires": "2026-06-15", "color": "red"},
            {"text": "Weekly +50% promo ends Jul 13", "expires": "2026-07-13", "color": "yellow"},
        ],
        "release": {},
    }

    both = engine.seg_banner(_ctx("2026-06-10T12:00:00", schedule))
    assert "SDK credit cutover Jun 15" in both
    assert "Weekly +50% promo ends Jul 13" in both

    weekly_only = engine.seg_banner(_ctx("2026-06-16T12:00:00", schedule))
    assert "SDK credit cutover Jun 15" not in weekly_only
    assert "Weekly +50% promo ends Jul 13" in weekly_only

    none = engine.seg_banner(_ctx("2026-07-14T12:00:00", schedule))
    assert "SDK credit cutover Jun 15" not in none
    assert "Weekly +50% promo ends Jul 13" not in none


def test_python_single_banner_format_still_works():
    _require_engine()
    rendered = engine.seg_banner(
        _ctx(
            "2026-06-10T12:00:00",
            {"banner": {"text": "test", "color": "green"}, "release": {}},
        )
    )
    assert "test" in rendered


def test_node_banner_array_renders_from_cached_schedule(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "statusline-config.json").write_text(
        json.dumps({"tier": "minimal", "schedule_url": "", "schedule_cache_hours": 999}),
        encoding="utf-8",
    )
    (claude_dir / "statusline-schedule.json").write_text(
        json.dumps(
            {
                "v": 5,
                "mode": "normal",
                "banner": {"text": "", "expires": "", "color": "yellow"},
                "banners": [
                    {"text": "Node SDK banner", "expires": "2099-01-01", "color": "red"},
                    {"text": "Node promo banner", "expires": "2099-01-01", "color": "yellow"},
                ],
                "release": {},
                "features": {"show_peak_segment": True, "show_rate_limits": True, "show_timeline": True},
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    proc = subprocess.run(
        [node, "engines/node-engine.js", "--tier=minimal"],
        input=json.dumps(
            {
                "context_window": {
                    "context_window_size": 200000,
                    "current_usage": {"input_tokens": 1},
                }
            }
        ),
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        timeout=10,
        check=True,
    )

    assert "Node SDK banner" in proc.stdout
    assert "Node promo banner" in proc.stdout
