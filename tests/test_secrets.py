"""Secret-store backend tests.

Covers the file-fallback backend (store/read/delete, 0600 mode, and the
never-raise contract on an unwritable location) and the macOS keychain backend
via a mocked ``subprocess.run`` (same monkeypatch style as test_usage_stale.py).

No real-looking secret material appears anywhere here — the values are obvious
placeholders.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

from lib import secrets


# ── File-fallback backend ─────────────────────────────────────────────────────

def _force_file_backend(monkeypatch, home):
    monkeypatch.setattr(secrets, "_select_backend", lambda: "file")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))


def test_file_backend_store_read_delete_and_0600_mode(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _force_file_backend(monkeypatch, home)

    # Absent → "".
    assert secrets.secret_read("claude-statusline-glm", "glm") == ""

    assert secrets.secret_store("claude-statusline-glm", "glm", "TOKEN-PLACEHOLDER") is True
    assert secrets.secret_read("claude-statusline-glm", "glm") == "TOKEN-PLACEHOLDER"

    path = home / ".claude" / "statusline-secrets.json"
    assert path.exists()
    # 0600 (owner rw only).
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Flat "service/account" map.
    assert json.loads(path.read_text(encoding="utf-8")) == {"claude-statusline-glm/glm": "TOKEN-PLACEHOLDER"}

    assert secrets.secret_delete("claude-statusline-glm", "glm") is True
    assert secrets.secret_read("claude-statusline-glm", "glm") == ""


def test_file_backend_multiple_entries_are_independent(tmp_path, monkeypatch):
    _force_file_backend(monkeypatch, tmp_path / "home")

    assert secrets.secret_store("claude-statusline-glm", "glm", "A-PLACEHOLDER") is True
    assert secrets.secret_store("claude-statusline-copilot", "copilot", "B-PLACEHOLDER") is True

    assert secrets.secret_read("claude-statusline-glm", "glm") == "A-PLACEHOLDER"
    assert secrets.secret_read("claude-statusline-copilot", "copilot") == "B-PLACEHOLDER"

    # Deleting one leaves the other intact.
    assert secrets.secret_delete("claude-statusline-glm", "glm") is True
    assert secrets.secret_read("claude-statusline-glm", "glm") == ""
    assert secrets.secret_read("claude-statusline-copilot", "copilot") == "B-PLACEHOLDER"


def test_file_backend_delete_absent_is_success(tmp_path, monkeypatch):
    _force_file_backend(monkeypatch, tmp_path / "home")
    # Nothing stored yet — delete is a no-op that reports success.
    assert secrets.secret_delete("claude-statusline-glm", "glm") is True


def test_file_backend_unwritable_location_never_raises(tmp_path, monkeypatch):
    # Point home at a regular file so ~/.claude/... can never be created.
    blocker = tmp_path / "home_is_a_file"
    blocker.write_text("x", encoding="utf-8")
    _force_file_backend(monkeypatch, blocker)

    assert secrets.secret_store("claude-statusline-glm", "glm", "TOKEN-PLACEHOLDER") is False
    assert secrets.secret_read("claude-statusline-glm", "glm") == ""
    # Must not raise.
    secrets.secret_delete("claude-statusline-glm", "glm")


def test_public_api_rejects_empty_args(tmp_path, monkeypatch):
    _force_file_backend(monkeypatch, tmp_path / "home")
    assert secrets.secret_store("", "glm", "x") is False
    assert secrets.secret_store("svc", "", "x") is False
    assert secrets.secret_store("svc", "glm", None) is False
    assert secrets.secret_read("", "glm") == ""
    assert secrets.secret_delete("svc", "") is False


# ── macOS keychain backend (mocked `security`) ────────────────────────────────

class _FakeProc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class _FakeKeychain:
    """Emulates the `security` generic-password CLI over an in-memory store."""

    def __init__(self):
        self.store = {}

    def run(self, cmd, *a, **k):
        def opt(flag):
            return cmd[cmd.index(flag) + 1] if flag in cmd else None

        if cmd[:2] == ["security", "add-generic-password"]:
            self.store[(opt("-s"), opt("-a"))] = opt("-w")
            return _FakeProc(returncode=0)
        if cmd[:2] == ["security", "find-generic-password"]:
            value = self.store.get((opt("-s"), opt("-a")))
            if value is None:
                return _FakeProc(returncode=44)  # item not found
            return _FakeProc(stdout=value + "\n", returncode=0)
        if cmd[:2] == ["security", "delete-generic-password"]:
            existed = self.store.pop((opt("-s"), opt("-a")), None)
            return _FakeProc(returncode=0 if existed is not None else 44)
        raise AssertionError(f"unexpected cmd: {cmd}")


def test_macos_keychain_roundtrip(monkeypatch):
    kc = _FakeKeychain()
    monkeypatch.setattr(secrets, "_select_backend", lambda: "macos")
    monkeypatch.setattr(secrets.subprocess, "run", kc.run)

    assert secrets.secret_read("claude-statusline-glm", "glm") == ""
    assert secrets.secret_store("claude-statusline-glm", "glm", "KC-PLACEHOLDER") is True
    # The keychain strips the trailing newline `security -w` appends.
    assert secrets.secret_read("claude-statusline-glm", "glm") == "KC-PLACEHOLDER"
    assert secrets.secret_delete("claude-statusline-glm", "glm") is True
    assert secrets.secret_read("claude-statusline-glm", "glm") == ""


def test_macos_keychain_subprocess_failure_never_raises(monkeypatch):
    monkeypatch.setattr(secrets, "_select_backend", lambda: "macos")

    def boom(cmd, *a, **k):
        raise TimeoutError("security timed out")

    monkeypatch.setattr(secrets.subprocess, "run", boom)
    assert secrets.secret_store("claude-statusline-glm", "glm", "x") is False
    assert secrets.secret_read("claude-statusline-glm", "glm") == ""
    assert secrets.secret_delete("claude-statusline-glm", "glm") is False
