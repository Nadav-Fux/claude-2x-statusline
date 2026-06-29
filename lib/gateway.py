"""Gateway/provider detection helpers for the statusline engines."""

from __future__ import annotations

import os
from urllib.parse import urlparse


def parse_gateway_host(base_url: str | None) -> str:
    raw = str(base_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        return (parsed.hostname or "").strip().lower()
    except Exception:
        try:
            return raw.split("/", 1)[0].split("@")[-1].split(":", 1)[0].strip().lower()
        except Exception:
            return ""


def provider_label_for_host(host: str | None) -> str:
    h = str(host or "").lower()
    if not h:
        return ""
    if "z.ai" in h or "bigmodel.cn" in h:
        return "GLM"
    if "openrouter" in h:
        return "OpenRouter"
    if "moonshot" in h or "kimi" in h:
        return "Kimi"
    if "deepseek" in h:
        return "DeepSeek"
    return h


def display_host_for_host(host: str | None) -> str:
    h = str(host or "").lower()
    if not h:
        return ""
    if "z.ai" in h:
        return "z.ai"
    if "bigmodel.cn" in h:
        return "bigmodel.cn"
    if h.startswith("api."):
        return h[4:]
    return h


def gateway_info(env=None, settings=None, config=None) -> dict:
    if env is None:
        env = os.environ
    settings = settings if isinstance(settings, dict) else {}
    config = config if isinstance(config, dict) else {}
    settings_env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    base_url = str(env.get("ANTHROPIC_BASE_URL") or settings_env.get("ANTHROPIC_BASE_URL") or "").strip()
    auth_token = str(env.get("ANTHROPIC_AUTH_TOKEN") or settings_env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    host = parse_gateway_host(base_url)
    awareness = config.get("gateway_awareness") is not False
    foreign = bool(awareness and host and host != "api.anthropic.com")
    label = provider_label_for_host(host)
    display_host = display_host_for_host(host)
    return {
        "base_url": base_url,
        "auth_token_present": bool(auth_token),
        "host": host,
        "display_host": display_host,
        "label": label,
        "foreign": foreign,
    }


def is_foreign_gateway(base_url: str | None) -> bool:
    return gateway_info(env={"ANTHROPIC_BASE_URL": base_url})["foreign"]


def gateway_badge_text(info: dict | None) -> str:
    if not isinstance(info, dict) or not info.get("foreign"):
        return ""
    host = info.get("display_host") or info.get("host") or ""
    label = info.get("label") or host
    if not host:
        return ""
    if label and label != host:
        return f"via {host} ({label})"
    return f"via {host}"


def gateway_note_label(info: dict | None) -> str:
    if not isinstance(info, dict) or not info.get("foreign"):
        return ""
    return info.get("label") or info.get("display_host") or info.get("host") or ""
