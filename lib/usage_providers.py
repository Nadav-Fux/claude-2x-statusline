"""External CLI usage providers for the statusline.

Every public provider reader returns a normalized record and never raises.
"""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path


PROVIDERS = {
    "codex": ("Codex", "local-jsonl"),
    "glm": ("GLM", "api"),
    "droid": ("Droid", "local-jsonl"),
    "antigravity": ("Antigravity", "sqlite"),
}

LOCAL_CACHE_TTL = 45
GLM_CACHE_TTL = 60
GLM_ENDPOINT = "/api/monitor/usage/quota/limit"


def unavailable(provider):
    label, source = PROVIDERS[provider]
    return {
        "provider": provider,
        "label": label,
        "available": False,
        "five_hour": None,
        "weekly": None,
        "plan": None,
        "tokens": None,
        "source": source,
        "stale_seconds": None,
    }


def _usage_window(used_pct, resets_at):
    try:
        pct = max(0.0, min(100.0, float(used_pct)))
    except (TypeError, ValueError):
        return None
    reset = None
    if resets_at is not None:
        try:
            reset = int(resets_at)
        except (TypeError, ValueError):
            reset = None
    return {"used_pct": pct, "resets_at": reset}


def _number_or_zero(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and number not in (float("inf"), float("-inf")) else 0.0


def _default_format_duration(total_mins):
    total_mins = max(0, int(_number_or_zero(total_mins)))
    h, m = divmod(total_mins, 60)
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def _provider_token_total(tokens):
    if not isinstance(tokens, dict):
        return 0
    for key in ("total", "total_tokens", "totalTokens"):
        value = _number_or_zero(tokens.get(key))
        if value > 0:
            return value
    return (
        _number_or_zero(tokens.get("input"))
        + _number_or_zero(tokens.get("output"))
        + _number_or_zero(tokens.get("input_tokens"))
        + _number_or_zero(tokens.get("output_tokens"))
        + _number_or_zero(tokens.get("cache_read"))
        + _number_or_zero(tokens.get("cache_creation"))
        + _number_or_zero(tokens.get("cached_input_tokens"))
        + _number_or_zero(tokens.get("reasoning_output_tokens"))
        + _number_or_zero(tokens.get("thinking"))
    )


def _reset_countdown(resets_at, now_sec, format_duration):
    reset = _number_or_zero(resets_at)
    now = _number_or_zero(now_sec)
    if reset <= now:
        return ""
    mins = int((reset - now) // 60)
    return f"\u27f3 {format_duration(mins)}"


def format_provider_row_parts(record, now_sec=None, label_width=0, format_duration=None):
    if not isinstance(record, dict) or not record.get("available"):
        return None
    if now_sec is None:
        now_sec = time.time()
    if format_duration is None:
        format_duration = _default_format_duration

    label = str(record.get("label") or record.get("provider") or "").strip() or "provider"
    width = max(0, int(_number_or_zero(label_width)))
    padded_label = label + (" " * max(0, width - len(label)))
    parts = [
        {
            "kind": "label",
            "label": padded_label,
            "raw_label": label,
            "plan": str(record.get("plan")) if record.get("plan") else "",
        }
    ]

    for window_label, window in (("5h", record.get("five_hour")), ("7d", record.get("weekly"))):
        if not isinstance(window, dict):
            continue
        pct = max(0, min(100, int(round(_number_or_zero(window.get("used_pct"))))))
        parts.append(
            {
                "kind": "window",
                "label": window_label,
                "pct": pct,
                "reset_text": _reset_countdown(window.get("resets_at"), now_sec, format_duration),
            }
        )

    has_window = any(part.get("kind") == "window" for part in parts)
    token_total = _provider_token_total(record.get("tokens"))
    if not has_window and token_total > 0:
        parts.append({"kind": "tokens", "total": token_total})
    if len(parts) <= 1:
        return None

    stale_seconds = record.get("stale_seconds")
    stale = stale_seconds is not None and _number_or_zero(stale_seconds) > 600
    return {"label": label, "parts": parts, "stale": stale, "stale_text": " \u00b7stale" if stale else ""}


def _parse_iso_seconds(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _cache_path(provider):
    return Path.home() / ".claude" / f"statusline-usage-{provider}.json"


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path, value):
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value), encoding="utf-8")
        os.replace(str(tmp), str(path))
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def _read_cached_record(provider, ttl):
    path = _cache_path(provider)
    try:
        age = time.time() - path.stat().st_mtime
        if age >= ttl:
            return None
        data = _read_json(path)
        record = data.get("record") if isinstance(data, dict) else None
        return record if isinstance(record, dict) else None
    except Exception:
        return None


def _write_cached_record(provider, record):
    if record and record.get("available"):
        _write_json(_cache_path(provider), {"cached_at": time.time(), "record": record})


def normalize_codex_token_count_event(event, stale_seconds=None, now=None):
    payload = event.get("payload") if isinstance(event, dict) else None
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return unavailable("codex")

    rate_limits = payload.get("rate_limits") or {}
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}
    five_hour = _usage_window(primary.get("used_percent"), primary.get("resets_at"))
    weekly = _usage_window(secondary.get("used_percent"), secondary.get("resets_at"))

    info = payload.get("info") or {}
    tokens = info.get("total_token_usage")
    if not isinstance(tokens, dict):
        tokens = None

    if stale_seconds is None:
        ts = _parse_iso_seconds(event.get("timestamp"))
        if ts is not None:
            stale_seconds = max(0, int((now or time.time()) - ts))

    record = unavailable("codex")
    record.update(
        {
            "available": bool(five_hour or weekly or tokens),
            "five_hour": five_hour,
            "weekly": weekly,
            "plan": rate_limits.get("plan_type"),
            "tokens": tokens,
            "stale_seconds": stale_seconds,
        }
    )
    return record


def parse_codex_token_count_line(line, stale_seconds=None, now=None):
    try:
        return normalize_codex_token_count_event(json.loads(line), stale_seconds, now)
    except Exception:
        return unavailable("codex")


def _newest_codex_rollout():
    sessions = Path.home() / ".codex" / "sessions"
    try:
        files = list(sessions.glob("*/*/*/rollout-*.jsonl"))
    except Exception:
        return None
    if not files:
        return None
    try:
        return max(files, key=lambda p: (p.stat().st_mtime, str(p)))
    except Exception:
        return None


def get_codex_usage(config=None):
    try:
        cached = _read_cached_record("codex", LOCAL_CACHE_TTL)
        if cached:
            return cached

        rollout = _newest_codex_rollout()
        if rollout is None:
            return unavailable("codex")

        last_event = None
        with rollout.open(encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                if isinstance(payload, dict) and payload.get("type") == "token_count":
                    last_event = event
        if last_event is None:
            return unavailable("codex")

        stale = max(0, int(time.time() - rollout.stat().st_mtime))
        record = normalize_codex_token_count_event(last_event, stale_seconds=stale)
        _write_cached_record("codex", record)
        return record
    except Exception:
        return unavailable("codex")


def parse_glm_quota_response(data, stale_seconds=None):
    try:
        body = data if isinstance(data, dict) else json.loads(data)
    except Exception:
        return unavailable("glm")

    data_obj = body.get("data") if isinstance(body.get("data"), dict) else {}
    limits = data_obj.get("limits") if isinstance(data_obj.get("limits"), list) else []
    five_hour = None
    weekly = None
    for item in limits:
        if not isinstance(item, dict):
            continue
        reset = None
        if item.get("nextResetTime") is not None:
            try:
                reset = int(round(float(item.get("nextResetTime")) / 1000.0))
            except (TypeError, ValueError):
                reset = None
        window = _usage_window(item.get("percentage"), reset)
        if item.get("type") == "TIME_LIMIT":
            five_hour = window
        elif item.get("type") == "TOKENS_LIMIT":
            weekly = window

    record = unavailable("glm")
    record.update(
        {
            "available": bool(five_hour or weekly),
            "five_hour": five_hour,
            "weekly": weekly,
            "plan": data_obj.get("level") or body.get("level"),
            "stale_seconds": stale_seconds,
        }
    )
    return record


def _read_provider_env_key():
    env_path = Path.home() / ".codex" / "providers.env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:export\s+)?(ZAI_API_KEY|ZHIPU_API_KEY)\s*=\s*(.+?)\s*$", line)
            if not match:
                continue
            value = match.group(2).strip().strip("'\"")
            if value:
                return value
    except Exception:
        pass
    return ""


def _glm_key(config):
    key = os.environ.get("ZAI_API_KEY") or os.environ.get("ZHIPU_API_KEY")
    if key:
        return key
    if isinstance(config, dict):
        key = str(config.get("api_key") or "").strip()
        if key:
            return key
    return _read_provider_env_key()


def _read_glm_cache():
    path = _cache_path("glm")
    try:
        data = _read_json(path)
        response = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response, dict):
            return None, None
        stale = max(0, int(time.time() - path.stat().st_mtime))
        return response, stale
    except Exception:
        return None, None


def _fetch_glm_response(config, key):
    base_url = "https://api.z.ai"
    if isinstance(config, dict) and config.get("base_url"):
        base_url = str(config.get("base_url")).rstrip("/")
    url = f"{base_url}{GLM_ENDPOINT}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": key,
            "Accept-Language": "en-US,en",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=1.5) as resp:
        return json.loads(resp.read())


def get_glm_usage(config=None):
    try:
        key = _glm_key(config)
        if not key:
            return unavailable("glm")

        cached_response, stale = _read_glm_cache()
        if cached_response is not None and stale is not None and stale < GLM_CACHE_TTL:
            return parse_glm_quota_response(cached_response, stale_seconds=stale)

        try:
            response = _fetch_glm_response(config, key)
            _write_json(_cache_path("glm"), {"cached_at": time.time(), "response": response})
            return parse_glm_quota_response(response, stale_seconds=0)
        except Exception:
            if cached_response is not None:
                return parse_glm_quota_response(cached_response, stale_seconds=stale)
            return unavailable("glm")
    except Exception:
        return unavailable("glm")


def _project_slug(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd or ""))


def _as_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _normalize_droid_tokens(raw):
    if not isinstance(raw, dict):
        return None
    mapping = {
        "input": ("inputTokens", "input_tokens", "input"),
        "output": ("outputTokens", "output_tokens", "output"),
        "cache_creation": ("cacheCreationTokens", "cache_creation_tokens"),
        "cache_read": ("cacheReadTokens", "cache_read_tokens"),
        "thinking": ("thinkingTokens", "reasoningTokens", "reasoning_output_tokens"),
        "factory_credits": ("factoryCredits", "factory_credits"),
    }
    tokens = {}
    for out_key, keys in mapping.items():
        for key in keys:
            number = _as_number(raw.get(key))
            if number is not None:
                tokens[out_key] = number
                break
    token_total = sum(v for k, v in tokens.items() if k != "factory_credits" and isinstance(v, (int, float)))
    if raw.get("totalTokens") is not None or raw.get("total_tokens") is not None or raw.get("total") is not None:
        for key in ("totalTokens", "total_tokens", "total"):
            number = _as_number(raw.get(key))
            if number is not None:
                token_total = number
                break
    if token_total <= 0 and not any(
        v for k, v in tokens.items() if k != "factory_credits" and isinstance(v, (int, float)) and v > 0
    ):
        return None
    tokens["total"] = token_total
    return tokens


def _find_token_dict(value):
    if isinstance(value, dict):
        direct = _normalize_droid_tokens(value)
        if direct:
            return direct
        for key in ("inclusiveTokenUsage", "tokenUsage", "usage", "tokens"):
            found = _normalize_droid_tokens(value.get(key))
            if found:
                return found
        for child in value.values():
            found = _find_token_dict(child)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_token_dict(item)
            if found:
                return found
    return None


def _droid_settings_candidates():
    factory = Path.home() / ".factory"
    index = _read_json(factory / "sessions-index.json")
    if isinstance(index, dict) and isinstance(index.get("entries"), list):
        entries = sorted(
            [e for e in index["entries"] if isinstance(e, dict)],
            key=lambda e: float(e.get("settingsMtime") or e.get("mtime") or 0),
            reverse=True,
        )
        for entry in entries[:20]:
            session_id = entry.get("sessionId")
            if not session_id:
                continue
            cwd = entry.get("cwd") or ""
            yield factory / "sessions" / _project_slug(cwd) / f"{session_id}.settings.json"

    sessions_dir = factory / "sessions"
    try:
        files = sorted(sessions_dir.glob("*/*.settings.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        files = []
    for path in files[:20]:
        yield path


def get_droid_usage(config=None):
    try:
        cached = _read_cached_record("droid", LOCAL_CACHE_TTL)
        if cached:
            return cached

        seen = set()
        for settings_path in _droid_settings_candidates():
            if settings_path in seen:
                continue
            seen.add(settings_path)
            data = _read_json(settings_path)
            tokens = _find_token_dict(data)
            if not tokens:
                continue
            record = unavailable("droid")
            record.update(
                {
                    "available": True,
                    "tokens": tokens,
                    "stale_seconds": max(0, int(time.time() - settings_path.stat().st_mtime)),
                }
            )
            _write_cached_record("droid", record)
            return record

        telemetry = Path.home() / ".factory" / "telemetry"
        try:
            files = sorted(telemetry.glob("*.json*"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            files = []
        for path in files[:10]:
            tokens = _find_token_dict(_read_json(path))
            if tokens:
                record = unavailable("droid")
                record.update(
                    {
                        "available": True,
                        "tokens": tokens,
                        "stale_seconds": max(0, int(time.time() - path.stat().st_mtime)),
                    }
                )
                _write_cached_record("droid", record)
                return record
        return unavailable("droid")
    except Exception:
        return unavailable("droid")


def _antigravity_db_path():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    return Path.home() / ".config" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"


def get_antigravity_usage(config=None):
    try:
        db_path = _antigravity_db_path()
        if not db_path.exists():
            return unavailable("antigravity")
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.5) as conn:
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        except Exception:
            pass
        return unavailable("antigravity")
    except Exception:
        return unavailable("antigravity")


def get_provider_usage(provider, config=None):
    try:
        if provider == "codex":
            return get_codex_usage(config)
        if provider == "glm":
            return get_glm_usage(config)
        if provider == "droid":
            return get_droid_usage(config)
        if provider == "antigravity":
            return get_antigravity_usage(config)
    except Exception:
        pass
    return unavailable(provider) if provider in PROVIDERS else None


def collect_external_usage(config):
    external = config.get("external_providers") if isinstance(config, dict) else None
    if not isinstance(external, dict) or external.get("enabled") is not True:
        return []

    records = []
    for provider in ("codex", "glm", "droid", "antigravity"):
        provider_config = external.get(provider)
        if not isinstance(provider_config, dict) or provider_config.get("enabled") is not True:
            continue
        record = get_provider_usage(provider, provider_config)
        if isinstance(record, dict):
            records.append(record)
    return records
