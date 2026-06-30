"""External CLI usage providers for the statusline.

Every public provider reader returns a normalized record and never raises.
"""
import json
import os
import re
import sqlite3
import subprocess
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
EXTERNAL_USAGE_CACHE_TTL = 15 * 60
GLM_ENDPOINT = "/api/monitor/usage/quota/limit"


def unavailable(provider):
    label, source = PROVIDERS[provider]
    return {
        "provider": provider,
        "label": label,
        "available": False,
        "five_hour": None,
        "weekly": None,
        "display": "bars",
        "metrics": None,
        "plan": None,
        "tokens": None,
        "source": source,
        "stale_seconds": None,
    }


def _usage_window(used_pct, resets_at, label=None):
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
    window = {"used_pct": pct, "resets_at": reset}
    clean_label = str(label).strip() if label is not None else ""
    if clean_label:
        window["label"] = clean_label
    return window


def _codex_window_label(window_minutes, fallback):
    try:
        mins = float(window_minutes)
    except (TypeError, ValueError):
        return fallback
    if mins <= 360:
        return "5h"
    if mins >= 10080:
        return "7d"
    hours = mins / 60.0
    return f"{int(hours) if hours.is_integer() else round(hours, 1)}h"


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


def _normalize_display_metric(metric, fallback_label=""):
    if not isinstance(metric, dict):
        return None
    label = str(metric.get("label") or fallback_label or "").strip()
    if not label:
        return None
    pct = max(0, min(100, int(round(_number_or_zero(metric.get("used_pct"))))))
    reset = None
    if metric.get("resets_at") is not None:
        try:
            reset = int(metric.get("resets_at"))
        except (TypeError, ValueError):
            reset = None
    return {"label": label, "used_pct": pct, "resets_at": reset}


def _compact_metrics_for_record(record):
    if isinstance(record.get("metrics"), list) and record.get("metrics"):
        raw_metrics = record.get("metrics")
    else:
        raw_metrics = []
        if isinstance(record.get("five_hour"), dict):
            raw_metrics.append(
                {
                    "label": record["five_hour"].get("label") or "5h",
                    "used_pct": record["five_hour"].get("used_pct"),
                    "resets_at": record["five_hour"].get("resets_at"),
                }
            )
        if isinstance(record.get("weekly"), dict):
            raw_metrics.append(
                {
                    "label": record["weekly"].get("label") or "7d",
                    "used_pct": record["weekly"].get("used_pct"),
                    "resets_at": record["weekly"].get("resets_at"),
                }
            )
    return [metric for metric in (_normalize_display_metric(item) for item in raw_metrics) if metric]


def _reset_style_for_label(label):
    # A 5-hour window shows a bare clock (12:00pm); anything longer shows a
    # date + clock (4/7 5:00am), mirroring the Claude rate-limit line.
    return "time" if "5h" in str(label or "") else "datetime"


def _reset_display(resets_at, label, now_sec, format_duration, format_clock):
    """Reset text for one window/metric.

    With a clock formatter the reset is an absolute end-time (⟳ 12:00pm /
    ⟳ 4/7 5:00am); otherwise it falls back to the legacy duration countdown
    (⟳ 3h 58m). A null/missing reset shows nothing (no ⟳).
    """
    if format_clock is not None:
        if resets_at is None:
            return ""
        try:
            clock = format_clock(resets_at, _reset_style_for_label(label))
        except Exception:
            clock = ""
        return f"⟳ {clock}" if clock else ""
    return _reset_countdown(resets_at, now_sec, format_duration)


def _soonest_reset_text(metrics, now_sec, format_duration, format_clock=None):
    now = _number_or_zero(now_sec)
    soonest = None
    soonest_at = None
    for metric in metrics:
        reset = metric.get("resets_at")
        if reset is None:
            continue
        reset_val = _number_or_zero(reset)
        # Legacy duration mode hides already-elapsed resets; clock mode keeps the
        # absolute end-time regardless.
        if format_clock is None and reset_val <= now:
            continue
        if soonest_at is None or reset_val < soonest_at:
            soonest_at = reset_val
            soonest = metric
    if soonest is None:
        return ""
    return _reset_display(soonest.get("resets_at"), soonest.get("label"), now_sec, format_duration, format_clock)


def _plain_usage_bar(pct, width=10):
    clean_pct = max(0, min(100, int(round(_number_or_zero(pct)))))
    filled = clean_pct * width // 100
    return "\u25b0" * filled + "\u25b1" * (width - filled)


def _format_provider_row_text(row):
    parts = row.get("parts") if isinstance(row.get("parts"), list) else []
    label_part = next((part for part in parts if isinstance(part, dict) and part.get("kind") == "label"), {})
    label_plan = str(label_part.get("plan") or "")
    label_text = f"{label_part.get('label', '')}{' ' + label_plan if label_plan else ''}"
    if row.get("display") == "compact":
        sep = " \u00b7 "
        metrics = [
            f"{part.get('label')} {part.get('pct')}%"
            for part in parts
            if isinstance(part, dict) and part.get("kind") == "metric"
        ]
        reset = f" {row.get('reset_text')}" if row.get("reset_text") else ""
        return f"{label_text}  {sep.join(metrics)}{reset}{row.get('stale_text') or ''}"

    chunks = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind")
        if kind == "label":
            plan = str(part.get("plan") or "")
            chunks.append(f"{part.get('label', '')}{' ' + plan if plan else ''}")
        elif kind == "window":
            reset = f" {part.get('reset_text')}" if part.get("reset_text") else ""
            pct = int(part.get("pct") or 0)
            chunks.append(f"{part.get('label')} {_plain_usage_bar(pct)} {pct:3d}%{reset}")
        elif kind == "tokens":
            chunks.append(f"tokens {int(part.get('total') or 0)}")
    return f"{'  '.join(chunks)}{row.get('stale_text') or ''}"


def _antigravity_dual_rows(record, label, now_sec, format_duration, format_clock, stale):
    """Two compact rows (5h + weekly) for an Antigravity per-model record.

    Returns None when the record has no metrics_5h / metrics_weekly lists, so
    callers fall through to the normal compact/bars rendering.
    """
    metrics_5h = record.get("metrics_5h")
    metrics_weekly = record.get("metrics_weekly")
    if not isinstance(metrics_5h, list) and not isinstance(metrics_weekly, list):
        return None

    sub_rows = []
    for window_label, raw_metrics in (("5h", metrics_5h), ("7d", metrics_weekly)):
        if not isinstance(raw_metrics, list):
            continue
        norm = [metric for metric in (_normalize_display_metric(item) for item in raw_metrics) if metric]
        if not norm:
            continue
        sub_label = f"{label} {window_label}"
        sub_parts = [{"kind": "label", "label": sub_label, "raw_label": sub_label, "plan": ""}]
        for metric in norm:
            sub_parts.append(
                {"kind": "metric", "label": metric["label"], "pct": metric["used_pct"], "resets_at": metric.get("resets_at")}
            )
        resets = [metric.get("resets_at") for metric in norm if metric.get("resets_at") is not None]
        soonest_reset = min(resets) if resets else None
        sub = {
            "label": sub_label,
            "display": "compact",
            "parts": sub_parts,
            "reset_text": _reset_display(soonest_reset, window_label, now_sec, format_duration, format_clock),
            "stale": stale,
            "stale_text": " ·stale" if stale else "",
        }
        sub["text"] = _format_provider_row_text(sub)
        sub_rows.append(sub)

    if not sub_rows:
        return None
    row = {
        "label": label,
        "display": "agy_dual",
        "parts": [{"kind": "label", "label": label, "raw_label": label, "plan": ""}],
        "sub_rows": sub_rows,
        "stale": stale,
        "stale_text": " ·stale" if stale else "",
    }
    row["text"] = "\n".join(sub["text"] for sub in sub_rows)
    return row


def format_provider_row_parts(record, now_sec=None, label_width=0, format_duration=None, format_clock=None):
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
    display = "compact" if record.get("display") == "compact" else "bars"
    stale_seconds = record.get("stale_seconds")
    stale = stale_seconds is not None and _number_or_zero(stale_seconds) > 600

    # Antigravity per-model two-row layout: when the record carries metrics_5h /
    # metrics_weekly lists (Opus/Pro/Flash), emit two compact rows \u2014 a 5-hour row
    # and a weekly row \u2014 instead of a single line.
    dual = _antigravity_dual_rows(record, label, now_sec, format_duration, format_clock, stale)
    if dual is not None:
        return dual

    if display == "compact":
        metrics = _compact_metrics_for_record(record)
        for metric in metrics:
            parts.append(
                {
                    "kind": "metric",
                    "label": metric["label"],
                    "pct": metric["used_pct"],
                    "resets_at": metric.get("resets_at"),
                }
            )
        if len(parts) <= 1:
            return None
        row = {
            "label": label,
            "display": display,
            "parts": parts,
            "reset_text": _soonest_reset_text(metrics, now_sec, format_duration, format_clock),
            "stale": stale,
            "stale_text": " \u00b7stale" if stale else "",
        }
        row["text"] = _format_provider_row_text(row)
        return row

    for fallback_label, window in (("5h", record.get("five_hour")), ("7d", record.get("weekly"))):
        if not isinstance(window, dict):
            continue
        window_label = str(window.get("label") or "").strip() or fallback_label
        pct = max(0, min(100, int(round(_number_or_zero(window.get("used_pct"))))))
        parts.append(
            {
                "kind": "window",
                "label": window_label,
                "pct": pct,
                "reset_text": _reset_display(window.get("resets_at"), window_label, now_sec, format_duration, format_clock),
            }
        )

    has_window = any(part.get("kind") == "window" for part in parts)
    token_total = _provider_token_total(record.get("tokens"))
    if not has_window and token_total > 0:
        parts.append({"kind": "tokens", "total": token_total})
    if len(parts) <= 1:
        return None

    row = {"label": label, "display": display, "parts": parts, "stale": stale, "stale_text": " \u00b7stale" if stale else ""}
    row["text"] = _format_provider_row_text(row)
    return row


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


def _is_available_record(record):
    return isinstance(record, dict) and record.get("available") is True


def _read_fresh_cache(provider, ttl=EXTERNAL_USAGE_CACHE_TTL):
    try:
        path = _cache_path(provider)
        age = time.time() - path.stat().st_mtime
        if age > ttl:
            return None, None
        return _read_json(path), max(0, int(age))
    except Exception:
        return None, None


def read_cached_external_usage(config):
    """Read external-provider usage from local cache files only.

    This is intentionally synchronous and network-free for narrator use. Any
    malformed config/file/record returns [] instead of surfacing an exception.
    """
    try:
        external = config.get("external_providers") if isinstance(config, dict) else None
        if not isinstance(external, dict) or external.get("enabled") is not True:
            return []

        records = []
        for provider in ("codex", "glm", "droid", "antigravity"):
            provider_config = external.get(provider)
            if not isinstance(provider_config, dict) or provider_config.get("enabled") is not True:
                continue

            data, stale = _read_fresh_cache(provider)
            if not isinstance(data, dict):
                continue

            record = None
            if provider == "glm":
                response = data.get("response")
                if isinstance(response, dict):
                    record = parse_glm_quota_response(response, stale_seconds=stale)
            else:
                cached_record = data.get("record")
                if isinstance(cached_record, dict):
                    record = cached_record

            if _is_available_record(record):
                records.append(record)
        return records
    except Exception:
        return []


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
    five_hour = _usage_window(
        primary.get("used_percent"),
        primary.get("resets_at"),
        _codex_window_label(primary.get("window_minutes"), "5h"),
    )
    weekly = _usage_window(
        secondary.get("used_percent"),
        secondary.get("resets_at"),
        _codex_window_label(secondary.get("window_minutes"), "7d"),
    )

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
        if item.get("type") == "TIME_LIMIT":
            five_hour = _usage_window(item.get("percentage"), reset, "5h")
        elif item.get("type") == "TOKENS_LIMIT":
            weekly = _usage_window(item.get("percentage"), reset, "tok")

    record = unavailable("glm")
    record.update(
        {
            "available": bool(five_hour or weekly),
            "five_hour": five_hour,
            "weekly": weekly,
            "display": "compact",
            "metrics": [
                metric
                for metric in (
                    {"label": "5h", "used_pct": five_hour["used_pct"], "resets_at": five_hour["resets_at"]}
                    if five_hour
                    else None,
                    {"label": "tok", "used_pct": weekly["used_pct"], "resets_at": weekly["resets_at"]}
                    if weekly
                    else None,
                )
                if metric
            ],
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


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _decode_antigravity_value(value):
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return json.loads(text)
        if isinstance(value, (dict, list)):
            return value
    except Exception:
        pass
    return None


def _normalize_antigravity_reset(value):
    if value is None or value == "":
        return None
    number = _finite_number(value)
    if number is not None:
        seconds = number / 1000.0 if number > 100_000_000_000 else number
        return int(seconds)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def _find_antigravity_reset(obj):
    if not isinstance(obj, dict):
        return None
    for key in ("resetsAt", "resets_at", "resetAt", "nextResetTime", "nextResetAt", "nextReset", "resetTime"):
        reset = _normalize_antigravity_reset(obj.get(key))
        if reset is not None:
            return reset
    return None


def _antigravity_pct(obj):
    if not isinstance(obj, dict):
        return None
    for key in ("usedPercent", "used_percent", "percentage", "percent", "pct", "usedPercentage", "usedPct"):
        pct = _finite_number(obj.get(key))
        if pct is not None:
            return pct
    used = _finite_number(obj.get("used"))
    remaining = _finite_number(obj.get("remaining"))
    limit = _finite_number(obj.get("limit"))
    if used is not None and limit is not None and limit > 0:
        return (used / limit) * 100.0
    if remaining is not None and limit is not None and limit > 0:
        return ((limit - remaining) / limit) * 100.0
    if used is not None and 0 <= used <= 100:
        return used
    return None


def _classify_antigravity_model(path_parts, obj):
    hints = [str(part or "") for part in path_parts]
    if isinstance(obj, dict):
        for key in ("key", "name", "label", "model", "modelName", "displayName", "id", "type"):
            if obj.get(key) is not None:
                hints.append(str(obj.get(key)))
    text = " ".join(hints).lower()
    if "flash" in text:
        return "Flash"
    if "opus" in text or "claude" in text or "sonnet" in text:
        return "Opus"
    if re.search(r"(^|[^a-z])pro([^a-z]|$)", text):
        return "Pro"
    return None


def _collect_antigravity_model_metrics(value, path_parts, found):
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _collect_antigravity_model_metrics(item, [*path_parts, str(idx)], found)
        return
    if not isinstance(value, dict):
        return

    pct = _antigravity_pct(value)
    label = _classify_antigravity_model(path_parts, value) if pct is not None else None
    if label and label not in found:
        metric = _usage_window(pct, _find_antigravity_reset(value), label)
        if metric:
            found[label] = metric

    for key, child_value in value.items():
        if isinstance(child_value, (dict, list)):
            _collect_antigravity_model_metrics(child_value, [*path_parts, key], found)


def parse_antigravity_models(raw):
    try:
        if not isinstance(raw, (dict, list)):
            return None
        found = {}
        _collect_antigravity_model_metrics(raw, [], found)
        metrics = [found[label] for label in ("Flash", "Pro", "Opus") if label in found]
        return metrics or None
    except Exception:
        return None


def _classify_antigravity_window(path_parts, obj):
    hints = [str(part or "") for part in path_parts]
    if isinstance(obj, dict):
        for key in ("type", "window", "period", "scope", "name", "limitType"):
            if obj.get(key) is not None:
                hints.append(str(obj.get(key)))
    text = " ".join(hints).lower()
    if "weekly" in text or re.search(r"\b(week|seven|7d|wk)\b", text):
        return "weekly"
    if (
        "sprint" in text
        or "five_hour" in text
        or "five-hour" in text
        or "five hour" in text
        or "fivehour" in text
        or "time_limit" in text
        or "time-limit" in text
        or "time limit" in text
        or re.search(r"\b5h\b", text)
    ):
        return "five_hour"
    return None


def _find_antigravity_windows(value, path_parts=None):
    if path_parts is None:
        path_parts = []
    found = {"five_hour": None, "weekly": None}
    if isinstance(value, list):
        for item in value:
            child = _find_antigravity_windows(item, path_parts)
            if found["five_hour"] is None and child.get("five_hour"):
                found["five_hour"] = child["five_hour"]
            if found["weekly"] is None and child.get("weekly"):
                found["weekly"] = child["weekly"]
        return found
    if not isinstance(value, dict):
        return found

    pct = _antigravity_pct(value)
    kind = _classify_antigravity_window(path_parts, value) if pct is not None else None
    if kind:
        found[kind] = _usage_window(pct, _find_antigravity_reset(value), "wk" if kind == "weekly" else "5h")

    for key, child_value in value.items():
        if not isinstance(child_value, (dict, list)):
            continue
        child = _find_antigravity_windows(child_value, [*path_parts, key])
        if found["five_hour"] is None and child.get("five_hour"):
            found["five_hour"] = child["five_hour"]
        if found["weekly"] is None and child.get("weekly"):
            found["weekly"] = child["weekly"]
    return found


def parse_antigravity_item_table(rows):
    try:
        if not isinstance(rows, (list, tuple)):
            return unavailable("antigravity")
        five_hour = None
        weekly = None
        model_metrics = []
        for row in rows:
            if isinstance(row, dict):
                key = row.get("key")
                raw_value = row.get("value")
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                key, raw_value = row[0], row[1]
            else:
                continue
            value = _decode_antigravity_value(raw_value)
            if value is None:
                continue
            metrics = parse_antigravity_models(value)
            if metrics:
                for metric in metrics:
                    if not any(existing.get("label") == metric.get("label") for existing in model_metrics):
                        model_metrics.append(metric)
            found = _find_antigravity_windows(value, [key])
            if five_hour is None and found.get("five_hour"):
                five_hour = found["five_hour"]
            if weekly is None and found.get("weekly"):
                weekly = found["weekly"]
        if model_metrics:
            order = {"Flash": 0, "Pro": 1, "Opus": 2}
            model_metrics.sort(key=lambda metric: order.get(metric.get("label"), 99))
            record = unavailable("antigravity")
            record.update(
                {
                    "label": "AGY",
                    "available": True,
                    "five_hour": five_hour,
                    "weekly": weekly,
                    "display": "compact",
                    "metrics": [
                        {
                            "label": metric.get("label"),
                            "used_pct": metric.get("used_pct"),
                            "resets_at": metric.get("resets_at") if metric.get("resets_at") is not None else None,
                        }
                        for metric in model_metrics
                    ],
                }
            )
            return record
        if five_hour is None and weekly is None:
            return unavailable("antigravity")
        record = unavailable("antigravity")
        record.update({"available": True, "five_hour": five_hour, "weekly": weekly})
        return record
    except Exception:
        return unavailable("antigravity")


def _antigravity_db_path():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
    return Path.home() / ".config" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"


def _map_antigravity_snapshot(snapshot):
    """Map an `antigravity-usage quota --json` snapshot (models[].remainingPercentage
    is a 0..1 fraction) into Opus/Pro/Flash compact metrics."""
    if not isinstance(snapshot, dict):
        return None
    models = snapshot.get("models") if isinstance(snapshot.get("models"), list) else []
    pick = {"Opus": None, "Pro": None, "Flash": None}
    for m in models:
        if not isinstance(m, dict) or m.get("isAutocompleteOnly"):
            continue
        ident = f"{m.get('label', '')} {m.get('modelId', '')}".lower()
        if "opus" in ident or "claude" in ident or "sonnet" in ident:
            group = "Opus"
        elif "pro" in ident:
            group = "Pro"
        elif "flash" in ident:
            group = "Flash"
        else:
            continue
        if pick[group] is not None:
            continue
        try:
            frac = float(m.get("remainingPercentage"))
        except (TypeError, ValueError):
            continue
        reset = _parse_iso_seconds(m.get("resetTime"))
        pick[group] = {
            "label": group,
            "used_pct": max(0, min(100, round((1 - frac) * 100))),
            "resets_at": int(reset) if reset else None,
        }
    metrics = [pick[g] for g in ("Opus", "Pro", "Flash") if pick[g]]
    return metrics or None


def get_antigravity_usage(config=None):
    """Antigravity quota via the `antigravity-usage` CLI (owns OAuth refresh +
    local-IDE/cloud fallback). Caches BOTH hits and misses so a logged-out machine
    never re-spawns the CLI on every render."""
    try:
        config = config if isinstance(config, dict) else {}
        cached = _read_cached_record("antigravity", GLM_CACHE_TTL)
        if cached:
            return cached
        bin_path = str(config.get("bin") or "antigravity-usage")
        out = ""
        try:
            proc = subprocess.run(
                [bin_path, "quota", "--json", "--method", "auto"],
                capture_output=True, text=True, timeout=5,
            )
            out = proc.stdout or ""
        except Exception:
            out = ""
        try:
            snapshot = json.loads(out)
        except Exception:
            snapshot = None
        metrics = _map_antigravity_snapshot(snapshot)
        if metrics:
            record = unavailable("antigravity")
            record.update({
                "available": True, "label": "AGY", "display": "compact", "metrics": metrics,
                "plan": snapshot.get("planType") if isinstance(snapshot, dict) else None,
                "source": "api", "stale_seconds": 0,
            })
        else:
            record = unavailable("antigravity")
        _write_json(_cache_path("antigravity"), {"cached_at": time.time(), "record": record})
        return record
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
