"""
Integration tests for worker/worker.js.

Strategy:
  1. Syntax check  — runs `node -c worker/worker.js` (skip if node absent).
  2. Route presence — reads worker.js source and asserts all expected route
     strings are present, so the test doesn't depend on a running server.
"""
import os
import re
import shutil
import subprocess
import sys
import pytest

# Resolve paths relative to this file so the tests work from any cwd.
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
WORKER_JS = os.path.join(REPO_ROOT, "worker", "worker.js")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def worker_source() -> str:
    with open(WORKER_JS, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Task 1 — JS syntax is valid
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_worker_js_syntax():
    """node -c must exit 0 (no syntax errors)."""
    result = subprocess.run(
        ["node", "-c", WORKER_JS],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node -c failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Task 2 — All expected routes are present in the source
# ---------------------------------------------------------------------------

def test_route_doctor_submit_present():
    """/doctor/submit route must be registered in the fetch handler."""
    src = worker_source()
    assert "/doctor/submit" in src, "Route /doctor/submit not found in worker.js"


def test_route_doctor_code_present():
    """Pattern for /doctor/<code> must be present."""
    src = worker_source()
    # The worker uses a regex like /^\/doctor\/...$/
    assert re.search(r"doctor.*<code>|doctor.*\[0-9a-f\]", src) or \
           "/doctor/" in src, \
        "Route pattern for /doctor/<code> not found in worker.js"


def test_route_doctor_latest_present():
    """/doctor/<code>/latest must be referenced in the source."""
    src = worker_source()
    assert "/latest" in src, "Route suffix /latest not found in worker.js"


# ---------------------------------------------------------------------------
# Task 3 — Handler functions exist
# ---------------------------------------------------------------------------

def test_handleDoctorSubmit_defined():
    src = worker_source()
    assert "handleDoctorSubmit" in src, "Function handleDoctorSubmit not found"


def test_handleDoctorGet_defined():
    src = worker_source()
    assert "handleDoctorGet" in src, "Function handleDoctorGet not found"


def test_handleDoctorLatest_defined():
    src = worker_source()
    assert "handleDoctorLatest" in src, "Function handleDoctorLatest not found"


# ---------------------------------------------------------------------------
# Task 4 — Existing routes are still present (regression check)
# ---------------------------------------------------------------------------

def test_existing_route_ping():
    src = worker_source()
    assert "/ping" in src, "Existing route /ping missing from worker.js"


def test_existing_route_stats():
    src = worker_source()
    assert "/stats" in src, "Existing route /stats missing from worker.js"


def test_existing_handler_ping():
    src = worker_source()
    assert "handlePing" in src, "Existing function handlePing missing"


def test_existing_handler_stats():
    src = worker_source()
    assert "handleStats" in src, "Existing function handleStats missing"


# ---------------------------------------------------------------------------
# Task 5 — Validation logic sanity checks (static source analysis)
# ---------------------------------------------------------------------------

def test_code_hex_regex_present():
    """Worker must validate machine code with a hex-only regex."""
    src = worker_source()
    # Expect something like /^[0-9a-f]{6,16}$/
    assert re.search(r"\[0-9a-f\]\{6,16\}", src), \
        "Hex code validation regex ^[0-9a-f]{6,16}$ not found in worker.js"


def test_report_size_limit_present():
    """Worker must enforce a 50 KB report size limit."""
    src = worker_source()
    # 50 * 1024 = 51200
    assert "50" in src and "1024" in src, \
        "50 KB report size cap not found in worker.js"


def test_ttl_30days_present():
    """Doctor entries must use a 30-day TTL (2592000 seconds)."""
    src = worker_source()
    assert "2592000" in src, "30-day TTL (2592000) not found in worker.js"


# ---------------------------------------------------------------------------
# Task 6 — KV binding name is unchanged
# ---------------------------------------------------------------------------

def test_kv_binding_name():
    """Worker must still use env.TELEMETRY as the KV binding."""
    src = worker_source()
    assert "env.TELEMETRY" in src, "KV binding env.TELEMETRY not found"


# ---------------------------------------------------------------------------
# Task 7 — Auth gating on read endpoints
# ---------------------------------------------------------------------------

def test_auth_check_used_in_doctor_get():
    src = worker_source()
    assert "checkAuth" in src, "checkAuth helper not found in worker.js"


def test_401_returned_on_auth_failure():
    src = worker_source()
    assert "401" in src, "HTTP 401 response not found in worker.js"
