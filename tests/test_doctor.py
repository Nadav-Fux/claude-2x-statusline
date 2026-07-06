import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_PATH = REPO_ROOT / "doctor" / "doctor.sh"


def _msys_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if len(resolved) >= 3 and resolved[1:3] == ":/":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def _write_fake_curl(bin_dir: Path) -> None:
    script = bin_dir / "curl"
    script.write_text(
        # Append, not overwrite: --report can fire more than one background
        # curl (e.g. /ping plus a failures rollup), which race to write this
        # single marker; with '>' the last writer clobbers /ping and the test
        # flakes under load. Appending keeps every call's payload.
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$STATUSLINE_TEST_CURL_MARKER\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def _wait_for_marker(marker: Path, timeout: float = 1.0, contains: str = "") -> bool:
    """Wait until the marker is non-empty (and, if given, contains `contains`).

    With `contains`, this waits for a SPECIFIC curl call to land — deterministic
    even when the doctor fires several background curls in some order.
    """
    def _ok() -> bool:
        if not marker.exists():
            return False
        text = marker.read_text(encoding="utf-8")
        return bool(text.strip()) and (contains in text if contains else True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ok():
            return True
        time.sleep(0.05)
    return _ok()


@pytest.fixture
def bash_exe() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    return bash


@pytest.fixture
def doctor_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "curl-marker.txt"
    _write_fake_curl(bin_dir)
    return home, bin_dir, marker


def _run_doctor_report(
    bash_exe: str,
    home: Path,
    bin_dir: Path,
    marker: Path,
    extra_env=None,
):
    command = " ; ".join(
        [
            f"export HOME={shlex.quote(_msys_path(home))}",
            f"export USERPROFILE={shlex.quote(_msys_path(home))}",
            f"export STATUSLINE_TEST_CURL_MARKER={shlex.quote(_msys_path(marker))}",
            f"export PATH={shlex.quote(_msys_path(bin_dir))}:$PATH",
            f"{shlex.quote(_msys_path(DOCTOR_PATH))} --report",
        ]
    )
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [bash_exe, "-lc", command],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _opt_in_to_telemetry(home: Path) -> None:
    """Telemetry is opt-in: write "telemetry": true so doctor.sh sends pings."""
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "statusline-config.json").write_text('{"telemetry": true}', encoding="utf-8")


def test_doctor_report_uses_curl_when_enabled(bash_exe: str, doctor_env) -> None:
    home, bin_dir, marker = doctor_env

    # Telemetry is opt-in: with no config at all, no ping is sent by default.
    result = _run_doctor_report(bash_exe, home, bin_dir, marker)
    assert result.returncode == 0, result.stderr or result.stdout
    assert not _wait_for_marker(marker, timeout=0.2), result.stdout

    # Once the user opts in ("telemetry": true), doctor.sh --report sends the ping.
    _opt_in_to_telemetry(home)
    result = _run_doctor_report(bash_exe, home, bin_dir, marker)

    assert result.returncode == 0, result.stderr or result.stdout
    assert _wait_for_marker(
        marker, contains="statusline-telemetry.nadavf.workers.dev/ping"
    ), result.stdout
    payload = marker.read_text(encoding="utf-8")
    assert "statusline-telemetry.nadavf.workers.dev/ping" in payload
    assert '"event":"doctor"' in payload


def test_doctor_report_respects_env_opt_out(bash_exe: str, doctor_env) -> None:
    home, bin_dir, marker = doctor_env
    # Opt in via config, then verify the hard kill switch still wins.
    _opt_in_to_telemetry(home)

    result = _run_doctor_report(
        bash_exe,
        home,
        bin_dir,
        marker,
        extra_env={"STATUSLINE_DISABLE_TELEMETRY": "1"},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert not _wait_for_marker(marker, timeout=0.2), result.stdout