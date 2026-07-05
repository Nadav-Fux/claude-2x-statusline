"""Cross-platform secret storage for statusline provider credentials.

Public API (all three NEVER raise and NEVER print/log a secret value):

  * ``secret_store(service, account, value) -> bool``
  * ``secret_read(service, account) -> str``   ("" when absent/failed)
  * ``secret_delete(service, account) -> bool``

Backends, selected by platform:

  * macOS  — the ``security`` keychain CLI (``add-generic-password -U`` /
    ``find-generic-password -w`` / ``delete-generic-password``), 3s timeouts.
  * Windows — PowerShell ``CredentialManager`` module when it is installed,
    otherwise the file fallback below.
  * Linux / anything else / Windows-without-CredentialManager — a ``0600``
    JSON file at ``~/.claude/statusline-secrets.json`` holding a flat map of
    ``"service/account" -> value``.

Service names follow the convention ``claude-statusline-<provider>`` (e.g.
``claude-statusline-glm``); this module does not enforce it, but callers should.

Nothing here is on the statusline render path — it is only touched by
onboarding, the GLM reader's key lookup, and doctor.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_TIMEOUT = 3
_SECRETS_FILENAME = "statusline-secrets.json"

# Cached PowerShell CredentialManager availability (None = not probed yet).
_WIN_CREDMAN = None


# ── Backend selection ─────────────────────────────────────────────────────────

def _select_backend():
    """Return 'macos' | 'windows' | 'file'. Windows downgrades to 'file' when
    the CredentialManager PowerShell module is unavailable. Overridable in
    tests by monkeypatching this function."""
    platform = sys.platform
    if platform == "darwin":
        return "macos"
    if platform.startswith("win"):
        return "windows" if _windows_has_credential_manager() else "file"
    return "file"


def _windows_has_credential_manager():
    global _WIN_CREDMAN
    if _WIN_CREDMAN is not None:
        return _WIN_CREDMAN
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "if (Get-Module -ListAvailable -Name CredentialManager) { 'yes' } else { 'no' }",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        _WIN_CREDMAN = (proc.stdout or "").strip().lower() == "yes"
    except Exception:
        _WIN_CREDMAN = False
    return _WIN_CREDMAN


# ── Public API ────────────────────────────────────────────────────────────────

def secret_store(service, account, value):
    """Store ``value`` under (service, account). Returns True on success."""
    if not service or not account or value is None:
        return False
    value = str(value)
    try:
        backend = _select_backend()
        if backend == "macos":
            return _macos_store(service, account, value)
        if backend == "windows":
            return _windows_store(service, account, value)
        return _file_store(service, account, value)
    except Exception:
        return False


def secret_read(service, account):
    """Return the stored secret for (service, account), or "" if absent."""
    if not service or not account:
        return ""
    try:
        backend = _select_backend()
        if backend == "macos":
            return _macos_read(service, account)
        if backend == "windows":
            return _windows_read(service, account)
        return _file_read(service, account)
    except Exception:
        return ""


def secret_delete(service, account):
    """Delete the secret for (service, account). Returns True when it is gone
    afterwards (including when nothing was stored)."""
    if not service or not account:
        return False
    try:
        backend = _select_backend()
        if backend == "macos":
            return _macos_delete(service, account)
        if backend == "windows":
            return _windows_delete(service, account)
        return _file_delete(service, account)
    except Exception:
        return False


# ── macOS keychain backend ────────────────────────────────────────────────────

def _macos_store(service, account, value):
    # -U updates an existing item in place instead of erroring on duplicates.
    proc = subprocess.run(
        [
            "security", "add-generic-password",
            "-U", "-s", service, "-a", account, "-w", value,
        ],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    return proc.returncode == 0


def _macos_read(service, account):
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _macos_delete(service, account):
    proc = subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    # returncode 44 == item not found; treat "already gone" as success.
    return proc.returncode in (0, 44)


# ── Windows PowerShell CredentialManager backend ──────────────────────────────

def _windows_target(service, account):
    return f"{service}/{account}"


def _windows_store(service, account, value):
    target = _windows_target(service, account)
    # Read the value from an env var so the plaintext never appears in argv /
    # the process list.
    env = dict(os.environ)
    env["STATUSLINE_SECRET_VALUE"] = value
    script = (
        "$ErrorActionPreference='Stop';"
        "$p=ConvertTo-SecureString $env:STATUSLINE_SECRET_VALUE -AsPlainText -Force;"
        f"New-StoredCredential -Target '{target}' -UserName '{account}' "
        "-SecurePassword $p -Persist LocalMachine | Out-Null; 'ok'"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=_TIMEOUT, env=env,
    )
    return proc.returncode == 0 and "ok" in (proc.stdout or "")


def _windows_read(service, account):
    target = _windows_target(service, account)
    script = (
        "$ErrorActionPreference='Stop';"
        f"$c=Get-StoredCredential -Target '{target}';"
        "if ($c) { $c.GetNetworkCredential().Password }"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _windows_delete(service, account):
    target = _windows_target(service, account)
    script = (
        f"Remove-StoredCredential -Target '{target}' -ErrorAction SilentlyContinue; 'ok'"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    return proc.returncode == 0


# ── File fallback backend (Linux + last resort) ───────────────────────────────

def _secrets_path():
    return Path.home() / ".claude" / _SECRETS_FILENAME


def _file_key(service, account):
    return f"{service}/{account}"


def _file_load():
    try:
        data = json.loads(_secrets_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _file_save(data):
    path = _secrets_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(str(tmp), str(path))
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _file_store(service, account, value):
    data = _file_load()
    data[_file_key(service, account)] = value
    return _file_save(data)


def _file_read(service, account):
    data = _file_load()
    value = data.get(_file_key(service, account))
    return str(value) if isinstance(value, str) else ""


def _file_delete(service, account):
    data = _file_load()
    key = _file_key(service, account)
    if key not in data:
        return True
    del data[key]
    return _file_save(data)
