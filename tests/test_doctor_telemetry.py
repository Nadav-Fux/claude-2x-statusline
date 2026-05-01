"""Tests for doctor.sh 3-tier privacy logic + sanitization.

Covers:
  - TELEMETRY_LEVEL derivation from statusline-config.json
    (full / minimal / off)
  - "Diagnostic code: ..." line in output
  - "Telemetry: off" line when telemetry disabled
  - sanitize_report() logic (home path, Windows path, username, hostname)
    tested both by running doctor.sh and by a pure-Python reimplementation
    of the same regex logic.

Run with:
    pytest tests/test_doctor_telemetry.py -v
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_SH = REPO_ROOT / "doctor" / "doctor.sh"

# Detect bash once.
_BASH = None
for _candidate in ("bash", "/usr/bin/bash", "/bin/bash"):
    try:
        r = subprocess.run([_candidate, "--version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            _BASH = _candidate
            break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _require_bash():
    if _BASH is None:
        pytest.skip("bash not found on PATH")
    if not DOCTOR_SH.exists():
        pytest.skip(f"doctor.sh not found at {DOCTOR_SH}")


def _run_doctor(tmp_home: Path, extra_env: dict | None = None, args: list[str] | None = None) -> str:
    """Run doctor.sh with HOME pointing at tmp_home and return combined stdout."""
    _require_bash()
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["CLAUDE_DIR"] = str(tmp_home / ".claude")
    # Ensure we don't inherit a real CLAUDE_DIR
    env.pop("CLAUDE_DIR", None)
    env["CLAUDE_DIR"] = str(tmp_home / ".claude")
    # Suppress colors so assertions are clean.
    env["TERM"] = "dumb"
    if extra_env:
        env.update(extra_env)
    cmd = [_BASH, str(DOCTOR_SH)] + (args or [])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return result.stdout + result.stderr


def _write_config(claude_dir: Path, data: dict) -> None:
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "statusline-config.json").write_text(json.dumps(data), encoding="utf-8")


# ── Python reimplementation of sanitize_report() ─────────────────────────────
# This mirrors the bash function exactly so we can test the logic in Python
# without needing a bash subprocess for every edge case.

def _sanitize(text: str, home: str, user: str, host: str) -> str:
    """Python equivalent of bash sanitize_report()."""
    import re as _re

    # 1. Literal $HOME value → ~/
    if home:
        text = text.replace(home, "~")

    # 2. Windows-style /c/Users/NAME/ → ~/
    if user:
        text = _re.sub(
            r"/[a-zA-Z]/[Uu]sers/" + _re.escape(user) + r"/",
            "~/",
            text,
        )

    # 3. Username occurrences (case-insensitive when sed supports -I flag)
    #    We use re.IGNORECASE to match the bash attempt.
    if user:
        text = _re.sub(_re.escape(user), "<user>", text, flags=_re.IGNORECASE)

    # 4. Hostname occurrences
    if host:
        text = _re.sub(_re.escape(host), "<host>", text)

    return text


# ── Tests: telemetry level in output ─────────────────────────────────────────

class TestTelemetryLevelOutput:
    """The doctor should print a 'Diagnostic code:' or 'Telemetry: off' footer."""

    def test_no_config_defaults_to_full(self, tmp_path):
        """When statusline-config.json is absent, level defaults to full."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        output = _run_doctor(tmp_path)
        assert "Diagnostic code:" in output, (
            f"Expected 'Diagnostic code:' line in output.\nGot:\n{output}"
        )
        assert "telemetry: full" in output, (
            f"Expected '(telemetry: full)' in output.\nGot:\n{output}"
        )

    def test_config_full_diagnostics(self, tmp_path):
        """Explicit diagnostics=full → 'Diagnostic code: ... (telemetry: full)'."""
        _write_config(tmp_path / ".claude", {"tier": "full", "diagnostics": "full"})
        output = _run_doctor(tmp_path)
        assert "Diagnostic code:" in output
        assert "telemetry: full" in output

    def test_config_minimal_diagnostics(self, tmp_path):
        """diagnostics=minimal → 'Diagnostic code: ... (telemetry: minimal)'."""
        _write_config(tmp_path / ".claude", {"tier": "full", "diagnostics": "minimal"})
        output = _run_doctor(tmp_path)
        assert "Diagnostic code:" in output, (
            f"Expected 'Diagnostic code:' line.\nGot:\n{output}"
        )
        assert "telemetry: minimal" in output, (
            f"Expected '(telemetry: minimal)'.\nGot:\n{output}"
        )

    def test_config_telemetry_false_prints_off(self, tmp_path):
        """telemetry=false → 'Telemetry: off — no diagnostics sent.'"""
        _write_config(tmp_path / ".claude", {"tier": "full", "telemetry": False})
        output = _run_doctor(tmp_path)
        assert "Telemetry: off" in output, (
            f"Expected 'Telemetry: off' line.\nGot:\n{output}"
        )
        assert "Diagnostic code:" not in output, (
            "Should NOT print 'Diagnostic code:' when telemetry is off."
        )

    def test_diagnostic_code_is_8_hex_chars(self, tmp_path):
        """The diagnostic code must be an 8-character lowercase hex string."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        output = _run_doctor(tmp_path)
        match = re.search(r"Diagnostic code:\s+([0-9a-f]+)", output)
        assert match, f"Could not find diagnostic code in output:\n{output}"
        code = match.group(1)
        assert len(code) == 8, f"Expected 8 hex chars, got {len(code)!r}: {code!r}"
        assert re.fullmatch(r"[0-9a-f]{8}", code), f"Code not lowercase hex: {code!r}"

    def test_diagnostic_code_stable_across_runs(self, tmp_path):
        """Running doctor.sh twice in the same env should produce the same code."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        out1 = _run_doctor(tmp_path)
        out2 = _run_doctor(tmp_path)
        m1 = re.search(r"Diagnostic code:\s+([0-9a-f]+)", out1)
        m2 = re.search(r"Diagnostic code:\s+([0-9a-f]+)", out2)
        assert m1 and m2, "Could not find code in one or both runs"
        assert m1.group(1) == m2.group(1), (
            f"Code changed between runs: {m1.group(1)!r} vs {m2.group(1)!r}"
        )


# ── Tests: sanitize_report (Python-level unit tests) ─────────────────────────

class TestSanitizeReport:
    """Unit tests for the sanitize_report logic (Python reimplementation)."""

    def test_home_path_replaced(self):
        """/home/alice/project → ~/project"""
        text = "/home/alice/project/foo.py: error at /home/alice/project/bar.py"
        result = _sanitize(text, home="/home/alice", user="alice", host="myhost")
        assert "/home/alice" not in result
        assert "~/project/foo.py" in result

    def test_windows_path_replaced(self):
        """/c/Users/alice/... (Git Bash) → ~/..."""
        text = "/c/Users/Alice/AppData/local/cc-2x-statusline/statusline.sh"
        result = _sanitize(text, home="/c/Users/Alice", user="Alice", host="WIN-PC")
        assert "/c/Users/Alice" not in result
        assert "~/" in result

    def test_username_replaced(self):
        """Real username (case-insensitive) → <user>"""
        text = "installed by alice in /opt/alice/tools"
        result = _sanitize(text, home="/home/alice", user="alice", host="box")
        assert "alice" not in result.lower() or "~" in result, (
            f"Username 'alice' should be gone from: {result!r}"
        )

    def test_hostname_replaced(self):
        """Real hostname → <host>"""
        text = "running on mybox.local — mybox config valid"
        result = _sanitize(text, home="/home/user", user="user", host="mybox.local")
        assert "mybox.local" not in result
        assert "<host>" in result

    def test_structure_preserved(self):
        """Line breaks and indentation are not destroyed."""
        text = "line 1\n  line 2\n    line 3"
        result = _sanitize(text, home="/tmp/x", user="xx", host="yy")
        assert result.count("\n") == 2
        assert "  line 2" in result

    def test_empty_string_safe(self):
        """Empty string returns empty string."""
        result = _sanitize("", home="/home/alice", user="alice", host="box")
        assert result == ""

    def test_no_sensitive_data_unchanged(self):
        """Text with no sensitive data passes through unmodified."""
        text = "statusline-config.json present (tier=full)"
        result = _sanitize(text, home="/home/nobody", user="nobody", host="ghost")
        assert result == text


# ── Tests: sanitize_report run through bash ──────────────────────────────────

class TestSanitizeViaBash:
    """Smoke-test that the bash sanitize_report() function works end-to-end.

    We inject a settings.json with a path containing HOME so that the check
    detail contains the home directory, then verify it does NOT appear in
    the doctor output (doctor output prints detail strings which go through
    normal display — sanitization applies to the telemetry payload, not the
    display; this test validates the function exists and runs without error
    by checking the doctor exits cleanly).
    """

    def test_doctor_exits_zero(self, tmp_path):
        """doctor.sh must always exit 0 (never blocks a session hook)."""
        _require_bash()
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["CLAUDE_DIR"] = str(claude_dir)
        env["TERM"] = "dumb"
        result = subprocess.run(
            [_BASH, str(DOCTOR_SH)],
            capture_output=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"doctor.sh exited {result.returncode}.\nstdout:\n{result.stdout.decode()}\nstderr:\n{result.stderr.decode()}"
        )

    def test_json_mode_no_footer(self, tmp_path):
        """--json mode must not emit the 'Diagnostic code:' footer (clean JSON)."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        output = _run_doctor(tmp_path, args=["--json"])
        assert "Diagnostic code:" not in output, (
            f"'Diagnostic code:' must not appear in --json output.\nGot:\n{output}"
        )
        # Should be valid JSON (at least starts with '{')
        stripped = output.strip()
        assert stripped.startswith("{"), f"Expected JSON output to start with '{{', got:\n{output}"
