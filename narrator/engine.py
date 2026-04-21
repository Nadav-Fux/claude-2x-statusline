"""narrator.engine — orchestrator for the narrator pipeline.

Public entry point: run(mode: str) -> str | None

Flow
----
1.  Check STATUSLINE_NARRATOR_ENABLED (default "1"). Return None if "0".
2.  Load memory file.
3.  Detect session ID rotation (CLAUDE_SESSION_ID env var).
4.  Read rolling state / stdin for live metrics.
5.  Check throttle for "prompt_submit" mode.
6.  Build Observation.
7.  Run scoring.pick() → up to 2 Insight objects.
8.  Decide whether to call Haiku.
9.  If Haiku fires, append as 2nd line.
10. Persist updated memory atomically.
11. Return narrator text (with directive header for Claude).
"""

from __future__ import annotations

import os
import time
from typing import Optional

import narrator.memory as _mem
from narrator.observations import build as _build_obs
from narrator.scoring import pick as _pick


# ---------------------------------------------------------------------------
# Env-var helpers
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name, "")
    if val == "":
        return default
    return val.strip() not in ("0", "false", "False", "no", "No")


def _languages() -> list:
    """Pick narrator output languages.

    Priority:
      1. STATUSLINE_NARRATOR_LANGS env var (explicit override, wins always).
      2. LC_ALL / LC_MESSAGES / LANG env vars — if first letters match 'he',
         default to Hebrew.
      3. Fallback: English.
    """
    raw = os.environ.get("STATUSLINE_NARRATOR_LANGS")
    if raw:
        langs = [s.strip() for s in raw.split(",") if s.strip() in ("en", "he")]
        return langs or ["en"]

    # Locale sniff — check the usual POSIX env vars in priority order.
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val.lower().startswith("he"):
            return ["he"]
    return ["en"]


def _directive_prefix(langs: list[str]) -> str:
    """Return a user-facing directive prefix in the primary output language."""
    primary = langs[0] if langs else "en"
    if primary == "he":
        return "הערת סטטוס"
    return "Statusline note"


def _frame_line(text: str) -> str:
    """Wrap surfaced narrator output so it is visually distinct from normal text."""
    return f"//// {text} ////"


def _format_lines(parts: list[str]) -> list[str]:
    """Render each surfaced note on its own line for better bidi stability."""
    return [_frame_line(f"-> {part}") for part in parts if part]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(mode: str) -> Optional[str]:
    """Run the narrator pipeline and return text to emit, or None.

    Parameters
    ----------
    mode : str
        "session_start" or "prompt_submit"
    """
    try:
        return _run_inner(mode)
    except Exception:
        # Narrator must never crash the calling hook.
        return None


def _run_inner(mode: str) -> Optional[str]:
    # ── 1. Enabled gate ───────────────────────────────────────────────────────
    if not _env_bool("STATUSLINE_NARRATOR_ENABLED", True):
        return None

    # ── 2. Load memory ────────────────────────────────────────────────────────
    data = _mem.load()

    # ── 3. Session rotation ───────────────────────────────────────────────────
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    current_session_id = data.get("current", {}).get("session_id", "")
    if session_id and current_session_id and session_id != current_session_id:
        data = _mem.rotate_session(data, session_id)
    elif session_id and not current_session_id:
        # First time seeing a session ID — set it
        data.setdefault("current", {})["session_id"] = session_id
        if not data["current"].get("started_at"):
            data["current"]["started_at"] = time.time()

    # ── 4. Throttle check (prompt_submit only) ────────────────────────────────
    now = time.time()
    if mode == "prompt_submit":
        throttle_min = _env_float("STATUSLINE_NARRATOR_THROTTLE_MIN", 5.0)
        last_emit = data.get("current", {}).get("last_emit_at", 0.0)
        if last_emit and (now - last_emit) < throttle_min * 60:
            return None

    # ── 5. Build Observation ──────────────────────────────────────────────────
    obs = _build_obs(data)

    # Increment prompt count for this call
    current = data.setdefault("current", _mem._default_current())
    current["prompt_count"] = current.get("prompt_count", 0) + 1
    obs.prompt_count = current["prompt_count"]
    obs.cost_milestones_hit = current.get("cost_milestones_hit", [])

    # ── 6. Scoring ────────────────────────────────────────────────────────────
    insights = _pick(obs, data)

    if not insights:
        # Nothing to say — still update prompt count and save
        _mem.save(data)
        return None

    langs = _languages()
    rules_text = [i.text for i in insights]

    # Build Hebrew line if requested
    he_parts = [i.text_he for i in insights if i.text_he]
    rules_text_he = he_parts

    # ── 7. Haiku gate ─────────────────────────────────────────────────────────
    haiku_text: Optional[str] = None
    haiku_enabled = _should_call_haiku(data, now)
    if haiku_enabled:
        try:
            from narrator.haiku import generate_with_rules_context
            haiku_text = generate_with_rules_context(obs, data, rules_text)
        except Exception:
            haiku_text = None

    # ── 8. Build output ───────────────────────────────────────────────────────
    # Assemble narrator line(s) respecting language selection
    lines: list[str] = []
    if "en" in langs:
        lines.extend(_format_lines(rules_text))
    if "he" in langs and rules_text_he:
        lines.extend(_format_lines(rules_text_he))
    # If only "he" selected but no Hebrew text available, fall back to English
    if not lines:
        lines.extend(_format_lines(rules_text))

    if haiku_text:
        lines.extend(_format_lines([haiku_text]))

    directive = f"{_frame_line(_directive_prefix(langs))}\n" + "\n".join(lines)

    # ── 9. Update memory ──────────────────────────────────────────────────────
    current["last_emit_at"] = now
    if haiku_text:
        current["last_haiku_at"] = now

    # Record delivered narratives
    for insight in insights:
        _mem.append_narrative(data, {
            "text": insight.text,
            "template_key": insight.template_key,
            "ts": now,
        })

    # Track cost milestones
    _update_cost_milestones(data, obs)

    # Append observation snapshot to rolling_observations
    obs_snapshot = {
        "ts": now,
        "cost_usd": obs.cost_usd,
        "ctx_pct": obs.ctx_pct,
        "burn_10m": obs.burn_10m,
        "cache_pct": obs.cache_pct,
        "session_duration_min": obs.session_duration_min,
    }
    _mem.append_observation(data, obs_snapshot)
    _mem.evict_old_observations(data)

    _mem.save(data)

    return directive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_call_haiku(data: dict, now: float) -> bool:
    """Return True if the Haiku gate passes."""
    # Check env override
    haiku_env = os.environ.get("STATUSLINE_NARRATOR_HAIKU", "").strip()
    if haiku_env == "0":
        return False
    if haiku_env == "":
        # Auto: only if API key is set
        if not os.environ.get("ANTHROPIC_API_KEY", ""):
            return False
    elif haiku_env != "1":
        return False

    current = data.get("current", {})
    prompt_count = current.get("prompt_count", 0)
    last_haiku_at = current.get("last_haiku_at", 0.0)
    interval_min = _env_float("STATUSLINE_NARRATOR_HAIKU_INTERVAL_MIN", 15.0)

    if prompt_count % 5 == 0:
        return True
    if last_haiku_at and (now - last_haiku_at) > interval_min * 60:
        return True
    return False


def _update_cost_milestones(data: dict, obs) -> None:
    """Record newly crossed cost milestones in memory."""
    from narrator.scoring import _COST_MILESTONES
    current = data.setdefault("current", {})
    hit = set(current.get("cost_milestones_hit", []))
    for m in _COST_MILESTONES:
        if obs.cost_usd >= m:
            hit.add(m)
    current["cost_milestones_hit"] = sorted(hit)
    obs.cost_milestones_hit = current["cost_milestones_hit"]
