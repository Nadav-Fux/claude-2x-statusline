"""narrator.haiku — optional Anthropic Haiku API call for richer narrative.

Returns None if:
- `anthropic` package is not installed
- ANTHROPIC_API_KEY env var is missing
- Any error occurs (timeout, rate limit, parse failure)
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from narrator.observations import Observation

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 80
_TIMEOUT_SECS = 5.0

_SYSTEM_PROMPT = (
    "You are a brief, direct narrator for a developer's coding session. "
    "Given the state below, write 25-35 words of insight covering "
    "(a) what changed since your last report and "
    "(b) the bigger session picture. "
    "Be specific and actionable. Do not restate numbers the user already sees. "
    "Never repeat an insight listed in recent_narratives. "
    "If you write in Hebrew, use plain natural Hebrew and avoid unclear or literal terms such as "
    "'נרטור', 'ריקבון', or 'ריקבון הקשר'."
)


def _build_payload(
    obs: "Observation",
    memory: dict,
    rules_pick_text: Optional[str],
) -> dict:
    """Build the model payload shared by both public entry points."""
    current = memory.get("current", {})
    prior_sessions = memory.get("prior_sessions", [])

    prior_summaries = []
    for ps in prior_sessions[:3]:
        narratives = ps.get("narratives", [])
        last_text = narratives[-1].get("text", "") if narratives else ""
        prior_summaries.append({
            "session_id": ps.get("session_id", ""),
            "ended_at": ps.get("ended_at", 0),
            "summary": last_text,
        })

    recent_narratives = [
        n.get("text", n) if isinstance(n, dict) else str(n)
        for n in current.get("delivered_narratives", [])[-5:]
    ]

    return {
        "current_state": {
            "cost_usd": obs.cost_usd,
            "burn_10m_per_hr": obs.burn_10m,
            "burn_session_per_hr": obs.burn_session,
            "ctx_pct": round(obs.ctx_pct, 1),
            "ctx_mins_left": obs.ctx_mins_left,
            "cache_pct": round(obs.cache_pct, 1),
            "cache_delta_5m_tokens": obs.cache_delta_5m,
            "session_duration_min": round(obs.session_duration_min, 1),
            "prompt_count": obs.prompt_count,
            "is_peak": obs.is_peak,
            "rate_limit_5h_pct": obs.rate_limit_5h_pct,
            "rate_limit_7d_pct": obs.rate_limit_7d_pct,
        },
        "recent_trends": {
            "cost_delta_5m": obs.cost_delta_5m,
            "cost_delta_20m": obs.cost_delta_20m,
            "ctx_delta_5m": obs.ctx_delta_5m,
        },
        "recent_narratives": recent_narratives,
        "rules_engine_pick": rules_pick_text,
        "prior_sessions_summary": prior_summaries,
    }


def _generate_from_payload(user_payload: dict) -> Optional[str]:
    """Call claude-haiku with a prepared payload and return text or None."""
    # Guard: API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    # Guard: anthropic package available
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return None

    user_message = json.dumps(user_payload, indent=2)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            timeout=_TIMEOUT_SECS,
        )
        text = response.content[0].text if response.content else ""
        return text.strip() or None
    except Exception:
        return None


def generate(obs: "Observation", memory: dict) -> Optional[str]:
    """Call claude-haiku and return a 25-35 word insight string, or None."""
    return _generate_from_payload(_build_payload(obs, memory, None))


def generate_with_rules_context(
    obs: "Observation",
    memory: dict,
    rules_pick_text: Optional[str],
) -> Optional[str]:
    """Variant that injects the rules engine's pick into the payload."""
    return _generate_from_payload(_build_payload(obs, memory, rules_pick_text))
