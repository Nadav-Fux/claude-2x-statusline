"""Git churn parser tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_ENGINE_PATH = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_ERR = None
except Exception as exc:  # pragma: no cover
    _IMPORT_ERR = exc


def _require_engine():
    if _IMPORT_ERR is not None:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


def test_parse_git_shortstat_empty_and_partial_outputs():
    _require_engine()

    assert engine.parse_git_shortstat("") == {"insertions": 0, "deletions": 0, "files": 0}
    assert engine.parse_git_shortstat(
        " 7 files changed, 420 insertions(+), 110 deletions(-)"
    ) == {"insertions": 420, "deletions": 110, "files": 7}
    assert engine.parse_git_shortstat(" 1 file changed, 3 insertions(+)") == {
        "insertions": 3,
        "deletions": 0,
        "files": 1,
    }
    assert engine.parse_git_shortstat(" 2 files changed, 9 deletions(-)") == {
        "insertions": 0,
        "deletions": 9,
        "files": 2,
    }
