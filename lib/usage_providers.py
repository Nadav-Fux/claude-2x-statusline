"""External CLI usage providers for the statusline.

Every public provider reader returns a normalized record and never raises.
"""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROVIDERS = {
    "codex": ("Codex", "local-jsonl"),
    "glm": ("GLM", "api"),
    "droid": ("Droid", "local-jsonl"),
    "antigravity": ("Antigravity", "api"),
    "copilot": ("Copilot", "api"),
}

LOCAL_CACHE_TTL = 45
CODEX_ROLLOUT_SCAN_LIMIT = 40
GLM_CACHE_TTL = 60
EXTERNAL_USAGE_CACHE_TTL = 15 * 60
GLM_ENDPOINT = "/api/monitor/usage/quota/limit"
COPILOT_CACHE_TTL = 300
COPILOT_DEFAULT_SKUS = ("Copilot AI Credits", "Copilot Premium Requests")
GLM_AUTH_RAW = "raw"
GLM_AUTH_BEARER = "bearer"
_GLM_LAST_AUTH_STYLE = None


class _GlmBodyParseError(Exception):
    def __init__(self, status):
        super().__init__("GLM response body was not JSON")
        self.status = status


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
    # Honest window label from the Codex rate-limit window size. Sub-day windows
    # read in hours ("5h"), day-or-longer windows in days ("7d", "30d"). This
    # keeps 300->"5h", 10080->"7d", 43200->"30d" (a 30-day window must never be
    # mislabelled "7d"). Half-up rounding matches the node twin's Math.round.
    if window_minutes is None:
        return fallback
    try:
        mins = float(window_minutes)
    except (TypeError, ValueError):
        return fallback
    if mins < 1440:
        hours = mins / 60.0
        return f"{int(hours) if hours.is_integer() else int(hours + 0.5)}h"
    days = mins / 1440.0
    return f"{int(days) if days.is_integer() else int(days + 0.5)}d"


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
        return True
    except Exception:
        return False


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


def read_cached_external_usage(config, only=None):
    """Read external-provider usage from local cache files only.

    This is intentionally synchronous and network-free for narrator use. Any
    malformed config/file/record returns [] instead of surfacing an exception.

    ``only`` — when an ordered list of provider names is supplied, read exactly
    those providers (in that order), bypassing the ``external_providers``
    enabled-flag iteration. This lets callers honor ``providers.selected``.
    Default (None) preserves the legacy enabled-flag behavior.
    """
    try:
        external = config.get("external_providers") if isinstance(config, dict) else None
        if not isinstance(external, dict):
            external = {}

        if only is not None:
            providers_iter = [p for p in only if p in PROVIDERS]
        else:
            if external.get("enabled") is not True:
                return []
            providers_iter = [
                p
                for p in ("codex", "glm", "droid", "antigravity", "copilot")
                if isinstance(external.get(p), dict) and external.get(p).get("enabled") is True
            ]

        records = []
        for provider in providers_iter:
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


def _codex_rollout_files():
    """All rollout-*.jsonl paths under ~/.codex/sessions, newest mtime first.

    A single glob + stat (mirrors the legacy _newest_codex_rollout mechanism) so
    the multi-account scan reuses one directory listing and never reads files it
    will not consider.
    """
    sessions = Path.home() / ".codex" / "sessions"
    try:
        paths = list(sessions.glob("*/*/*/rollout-*.jsonl"))
    except Exception:
        return []
    entries = []
    for path in paths:
        try:
            entries.append((path.stat().st_mtime, str(path), path))
        except Exception:
            continue
    entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return entries


def _newest_codex_rollout():
    entries = _codex_rollout_files()
    return entries[0][2] if entries else None


def _last_codex_token_count_event(path):
    last_event = None
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                if isinstance(payload, dict) and payload.get("type") == "token_count":
                    last_event = event
    except Exception:
        return None
    return last_event


def _codex_rollout_snapshots(scan_limit=CODEX_ROLLOUT_SCAN_LIMIT):
    """Newest available rate_limits snapshot per plan_type, newest first.

    Two Codex apps (e.g. Desktop on a free account + CLI on a paid team account)
    write into the same sessions tree, so the newest file globally can belong to
    either. This walks the newest rollouts (bounded by scan_limit) and keeps the
    newest available snapshot for each distinct plan_type, stopping early once
    >=2 plan_types are captured. Each record's stale_seconds is the age of the
    file that snapshot came from, so selection can honor the SELECTED snapshot's
    age rather than the newest file's.
    """
    ordered = []
    seen_plans = set()
    now = time.time()
    for mtime, _, path in _codex_rollout_files()[:scan_limit]:
        event = _last_codex_token_count_event(path)
        if event is None:
            continue
        stale = max(0, int(now - mtime))
        record = normalize_codex_token_count_event(event, stale_seconds=stale)
        if not record.get("available"):
            continue
        plan_key = record.get("plan")
        if plan_key in seen_plans:
            continue
        seen_plans.add(plan_key)
        ordered.append(record)
        if len(seen_plans) >= 2:
            break
    return ordered


def _codex_plan_pin(config):
    """The configured plan pin (external_providers.codex.plan), lowercased.

    Accepts either the codex provider block ({"plan": "team"}) as passed by
    collect_external_usage, or a full config carrying external_providers.codex.
    """
    if not isinstance(config, dict):
        return ""
    plan = config.get("plan")
    if not plan:
        external = config.get("external_providers")
        if isinstance(external, dict) and isinstance(external.get("codex"), dict):
            plan = external["codex"].get("plan")
    return str(plan).strip().lower() if plan else ""


def _select_codex_snapshot(ordered, config):
    """Pick one snapshot from the per-plan scan.

    a) a configured plan pin wins (its newest snapshot; else newest overall),
    b) otherwise the newest PAID snapshot (plan present and != "free"),
    c) otherwise the newest overall.
    """
    if not ordered:
        return None
    pin = _codex_plan_pin(config)
    if pin:
        for record in ordered:
            if str(record.get("plan") or "").strip().lower() == pin:
                return record
        return ordered[0]
    for record in ordered:
        plan = str(record.get("plan") or "").strip().lower()
        if plan and plan != "free":
            return record
    return ordered[0]


def get_codex_usage(config=None):
    try:
        cached = _read_cached_record("codex", LOCAL_CACHE_TTL)
        if cached:
            return cached

        record = _select_codex_snapshot(_codex_rollout_snapshots(), config)
        if record is None:
            return unavailable("codex")
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


def _read_provider_env_key_with_source():
    env_path = Path.home() / ".codex" / "providers.env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:export\s+)?(ZAI_API_KEY|ZHIPU_API_KEY)\s*=\s*(.+?)\s*$", line)
            if not match:
                continue
            value = match.group(2).strip().strip("'\"")
            if value:
                return "providers.env", value
    except Exception:
        pass
    return "none", ""


def _read_provider_env_key():
    return _read_provider_env_key_with_source()[1]


def _keychain_glm_key():
    """Read the GLM key from the OS secret store (keychain / file fallback).

    Guarded end-to-end: a missing secret_store module, a legacy shadowed module
    (no ``secret_read`` attr), or any backend failure all collapse to "" so the
    reader falls through to the env/config/providers.env chain. Never raises,
    never logs the value."""
    try:
        try:
            from . import secret_store as _secrets  # package import (lib.usage_providers)
        except Exception:
            import secret_store as _secrets  # lib/ on sys.path (standalone import)
        reader = getattr(_secrets, "secret_read", None)
        if reader is None:
            return ""
        return reader("claude-statusline-glm", "glm") or ""
    except Exception:
        return ""


def _glm_key_with_source(config):
    # Keychain / secret store first (the migrated-off-plaintext home for the key).
    key = _keychain_glm_key()
    if key:
        return "keychain", key
    key = os.environ.get("ZAI_API_KEY")
    if key:
        return "env:ZAI_API_KEY", key
    key = os.environ.get("ZHIPU_API_KEY")
    if key:
        return "env:ZHIPU_API_KEY", key
    if isinstance(config, dict):
        key = str(config.get("api_key") or "").strip()
        if key:
            return "config", key
    return _read_provider_env_key_with_source()


def _glm_key(config):
    return _glm_key_with_source(config)[1]


def _glm_provider_config(config, include_api_key=True):
    if not isinstance(config, dict):
        return {}
    external = config.get("external_providers")
    if isinstance(external, dict) and isinstance(external.get("glm"), dict):
        glm = dict(external.get("glm") or {})
    else:
        glm = dict(config)
    if not include_api_key:
        glm.pop("api_key", None)
    return glm


def _normalize_glm_auth_style(value):
    value = str(value or "").strip().lower()
    if value == GLM_AUTH_BEARER:
        return GLM_AUTH_BEARER
    if value == GLM_AUTH_RAW:
        return GLM_AUTH_RAW
    return None


def _glm_auth_header(key, auth_style):
    if auth_style == GLM_AUTH_BEARER:
        return f"Bearer {key}"
    return key


def _read_glm_cache_payload():
    try:
        data = _read_json(_cache_path("glm"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_glm_auth_style():
    return _normalize_glm_auth_style(_read_glm_cache_payload().get("auth_style"))


def _read_glm_cache():
    path = _cache_path("glm")
    try:
        data = _read_glm_cache_payload()
        response = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response, dict):
            return None, None
        stale = max(0, int(time.time() - path.stat().st_mtime))
        return response, stale
    except Exception:
        return None, None


def _write_glm_cache(response, auth_style=None):
    style = _normalize_glm_auth_style(auth_style) or _normalize_glm_auth_style(_GLM_LAST_AUTH_STYLE) or _read_glm_auth_style()
    payload = {"cached_at": time.time(), "response": response}
    if style:
        payload["auth_style"] = style
    return _write_json(_cache_path("glm"), payload)


def _fetch_glm_response_with_meta(config, key, timeout=1.5):
    global _GLM_LAST_AUTH_STYLE
    base_url = "https://api.z.ai"
    if isinstance(config, dict) and config.get("base_url"):
        base_url = str(config.get("base_url")).rstrip("/")
    url = f"{base_url}{GLM_ENDPOINT}"
    first_style = _read_glm_auth_style() or GLM_AUTH_RAW
    styles = [first_style]
    if first_style == GLM_AUTH_RAW:
        styles.append(GLM_AUTH_BEARER)

    last_error = None
    for style in styles:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": _glm_auth_header(key, style),
                "Accept-Language": "en-US,en",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = int(getattr(resp, "status", getattr(resp, "code", 200)) or 200)
                try:
                    data = json.loads(resp.read())
                except Exception as exc:
                    raise _GlmBodyParseError(status) from exc
                _GLM_LAST_AUTH_STYLE = style
                return data, status, style
        except urllib.error.HTTPError as exc:
            last_error = exc
            if style == GLM_AUTH_RAW and getattr(exc, "code", None) in (401, 403):
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("GLM request did not run")


def _fetch_glm_response(config, key):
    return _fetch_glm_response_with_meta(config, key)[0]


def refresh_glm_cache(config=None):
    """Refresh the GLM quota cache.

    This may do network and keychain work, so callers on the render path should
    run it only via the detached provider refresher.
    """
    try:
        config = _glm_provider_config(config)
        key = _glm_key(config)
        if not key:
            return False
        response, _status, auth_style = _fetch_glm_response_with_meta(config, key)
        record = parse_glm_quota_response(response)
        if not (isinstance(record, dict) and record.get("available")):
            return False
        return _write_glm_cache(response, auth_style=auth_style) is True
    except Exception:
        return False


def probe_glm_quota(config=None, timeout=3.0):
    """Read-only GLM diagnostics for doctor/onboarding.

    Returns only redaction-safe metadata: key source, HTTP status, whether the
    parsed quota record is usable, and a coarse failure class.
    """
    result = {"key_source": "none", "http_status": "none", "usable": False, "failure": "no_key"}
    try:
        config = _glm_provider_config(config)
        source, key = _glm_key_with_source(config)
        result["key_source"] = source
        if not key:
            return result
        try:
            response, status, _auth_style = _fetch_glm_response_with_meta(config, key, timeout=timeout)
            result["http_status"] = str(status)
            record = parse_glm_quota_response(response)
            if isinstance(record, dict) and record.get("available"):
                result["usable"] = True
                result["failure"] = "ok"
            else:
                result["failure"] = "parse_fail"
            return result
        except _GlmBodyParseError as exc:
            result["http_status"] = str(getattr(exc, "status", "unknown") or "unknown")
            result["failure"] = "parse_fail"
            return result
        except urllib.error.HTTPError as exc:
            status = getattr(exc, "code", None)
            result["http_status"] = str(status or "unknown")
            result["failure"] = "unauth" if status in (401, 403) else "http"
            return result
        except TimeoutError:
            result["http_status"] = "timeout"
            result["failure"] = "timeout"
            return result
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                result["http_status"] = "timeout"
                result["failure"] = "timeout"
            else:
                result["http_status"] = "network"
                result["failure"] = "network"
            return result
        except Exception as exc:
            if "timed out" in str(exc).lower():
                result["http_status"] = "timeout"
                result["failure"] = "timeout"
            else:
                result["http_status"] = "network"
                result["failure"] = "network"
            return result
    except Exception:
        result["failure"] = "unknown"
        return result


def get_glm_usage(config=None):
    """GLM quota usage.

    Render path is cache-only. Stale or missing cache kicks off a detached
    refresh and immediately returns the stale record (or unavailable when no
    cache exists yet).
    """
    cached_response, stale = _read_glm_cache()
    if stale is None or stale >= GLM_CACHE_TTL:
        _spawn_provider_refresh("glm", config)
    if cached_response is None:
        return unavailable("glm")
    try:
        return parse_glm_quota_response(cached_response, stale_seconds=stale)
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


_ANTIGRAVITY_FAMILY_ORDER = {"Gemini": 0, "Opus": 1, "Sonnet": 2, "GPT": 3}


def _antigravity_model_family(model):
    """Classify one `antigravity-usage` models[] entry into a display family.

    Known families (Gemini/Opus/Sonnet/GPT) are detected from the label/modelId
    text; anything else falls back to the label's first word (capitalized) so a
    future Antigravity lineup change is grouped instead of silently dropped.
    This also keeps old lineups (bare "Flash"/"Pro" labels) working: they don't
    match a known keyword, so they fall back to their own first word.
    """
    label = str((model or {}).get("label") or "").strip()
    model_id = str((model or {}).get("modelId") or "").strip()
    hint = f"{label} {model_id}".lower()
    if "gemini" in hint:
        return "Gemini"
    if "opus" in hint:
        return "Opus"
    if "sonnet" in hint:
        return "Sonnet"
    if "gpt" in hint:
        return "GPT"
    basis = label or model_id
    words = basis.split()
    return words[0].capitalize() if words else "Model"


def _antigravity_credits_metric(credits):
    """Monthly prompt-credits pool from `antigravity-usage` (local method only).

    Credits are the binding constraint: every model can read 100% free while
    the credit pool runs dry, so this renders first. The payload carries no
    reset timestamp for the pool, so resets_at stays None.
    """
    if not isinstance(credits, dict):
        return None
    used = credits.get("usedPercentage")
    if used is None and credits.get("remainingPercentage") is not None:
        try:
            used = 1.0 - float(credits.get("remainingPercentage"))
        except (TypeError, ValueError):
            return None
    try:
        used = float(used)
    except (TypeError, ValueError):
        return None
    return {"label": "cr", "used_pct": max(0, min(100, round(used * 100))), "resets_at": None}


def _map_antigravity_snapshot(snapshot):
    """Map an `antigravity-usage quota --json` snapshot into per-model-family
    compact metrics (models[].remainingPercentage is a 0..1 fraction).

    Models are grouped dynamically by family (Gemini/Opus/Sonnet/GPT/...) rather
    than a hardcoded whitelist, so lineup changes (e.g. GPT-OSS, Claude Sonnet)
    are never dropped. Within a group, used_pct is the MAX used_pct across member
    models (the most-constrained variant); resets_at is that member's resetTime,
    or the earliest one among members tied on used_pct.
    """
    if not isinstance(snapshot, dict):
        return None
    models = snapshot.get("models") if isinstance(snapshot.get("models"), list) else []
    groups = {}
    for m in models:
        if not isinstance(m, dict) or m.get("isAutocompleteOnly"):
            continue
        try:
            frac = float(m.get("remainingPercentage"))
        except (TypeError, ValueError):
            continue
        family = _antigravity_model_family(m)
        used_pct = max(0, min(100, round((1 - frac) * 100)))
        reset = _parse_iso_seconds(m.get("resetTime"))
        reset = int(reset) if reset else None
        existing = groups.get(family)
        if existing is None or used_pct > existing["used_pct"] or (
            used_pct == existing["used_pct"]
            and reset is not None
            and (existing["resets_at"] is None or reset < existing["resets_at"])
        ):
            groups[family] = {"label": family, "used_pct": used_pct, "resets_at": reset}
    credits = _antigravity_credits_metric(snapshot.get("promptCredits"))
    if not groups:
        return [credits] if credits else None
    ordered = sorted(groups, key=lambda name: (_ANTIGRAVITY_FAMILY_ORDER.get(name, 99), name))
    metrics = [groups[name] for name in ordered]
    if credits:
        metrics.insert(0, credits)
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


def _copilot_provider_config(config):
    if not isinstance(config, dict):
        return {}
    external = config.get("external_providers")
    if isinstance(external, dict) and isinstance(external.get("copilot"), dict):
        return dict(external.get("copilot") or {})
    return dict(config)


def _copilot_mode(config):
    mode = str(config.get("mode") or "individual").strip().lower()
    return "org" if mode == "org" else "individual"


def _copilot_skus(config):
    raw = config.get("skus")
    values = []
    if isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw]
    elif isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    values = [item for item in values if item]
    return values or list(COPILOT_DEFAULT_SKUS)


def _copilot_number(value):
    number = _finite_number(value)
    if number is None:
        return None
    return int(number) if float(number).is_integer() else number


def _copilot_positive_number(value):
    number = _copilot_number(value)
    if number is None or number <= 0:
        return None
    return number


def _copilot_next_month_epoch(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        start = start.replace(year=start.year + 1, month=1)
    else:
        start = start.replace(month=start.month + 1)
    return int(start.timestamp())


def _copilot_match_item(item, skus):
    if not isinstance(item, dict):
        return False
    sku = str(item.get("sku") or "").lower()
    return bool(sku) and any(str(needle).lower() in sku for needle in skus)


def _copilot_usage_total(response, skus):
    items = response.get("usageItems") if isinstance(response, dict) else None
    if not isinstance(items, list):
        return 0.0
    total = 0.0
    for item in items:
        if not _copilot_match_item(item, skus):
            continue
        quantity = _finite_number(item.get("quantity")) if isinstance(item, dict) else None
        if quantity is not None:
            total += quantity
    return total


def _copilot_quota_candidates(value, path=None):
    if path is None:
        path = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = [*path, str(key)]
            yield from _copilot_quota_candidates(child, child_path)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _copilot_quota_candidates(child, [*path, str(idx)])
    else:
        number = _finite_number(value)
        if number is None or number <= 0:
            return
        path_text = ".".join(path).lower()
        include_terms = ("included", "free", "quota", "allowance", "limit", "cap")
        exclude_terms = ("used", "remaining", "consumed", "discount", "gross", "net", "price", "cost", "amount")
        if not any(term in path_text for term in include_terms):
            return
        if any(term in path_text for term in exclude_terms):
            return
        yield number


def _copilot_derived_cap(response):
    candidates = list(_copilot_quota_candidates(response))
    if not candidates:
        return None
    return _copilot_number(max(candidates))


def _copilot_record(mode, used, cap=None, pool=None, plan=None):
    cap = _copilot_positive_number(cap)
    pool = _copilot_number(pool) or 0
    used = float(used or 0.0)
    remaining = None
    used_pct = 0
    if cap is not None:
        remaining = max(0.0, float(cap) - used)
        used_pct = min(100, round(used / float(cap) * 100)) if cap else 0
        label = f"{remaining:.0f} left"
    else:
        label = f"{used:.0f} used"
    return {
        "provider": "copilot",
        "label": "Copilot",
        "available": True,
        "display": "bars",
        "five_hour": {"label": label, "used_pct": used_pct, "resets_at": _copilot_next_month_epoch()},
        "plan": str(plan or ("business" if mode == "org" else "individual")),
        "source": "gh-billing",
        "used": round(used, 2),
        "cap": cap or 0,
        "pool": pool,
        "remaining": None if remaining is None else round(remaining, 2),
    }


def _run_gh(args):
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    return proc.stdout or ""


def _gh_auth_ok():
    return _run_gh(["auth", "status"]) is not None


def _gh_api_json(endpoint):
    out = _run_gh(["api", endpoint])
    if not out:
        return None
    try:
        data = json.loads(out)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _gh_api_text(*args):
    out = _run_gh(["api", *args])
    return out.strip() if out is not None else ""


def refresh_copilot_cache(config=None):
    """Refresh the Copilot billing cache with the GitHub CLI.

    Returns True only after a successful API read and cache write. Auth errors,
    403s, timeouts, a missing gh binary, or incomplete org-mode config all return
    False and never clobber the previous cache.
    """
    try:
        config = _copilot_provider_config(config)
        mode = _copilot_mode(config)
        skus = _copilot_skus(config)
        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month
        org = ""
        org_cap = None
        if mode == "org":
            org = str(config.get("org") or "").strip()
            org_cap = _copilot_positive_number(config.get("cap"))
            if not org or org_cap is None:
                return False

        if not _gh_auth_ok():
            return False

        if mode == "org":
            response = _gh_api_json(f"/organizations/{org}/settings/billing/usage?year={year}&month={month}")
            if response is None:
                return False
            used = _copilot_usage_total(response, skus)
            record = _copilot_record(
                mode,
                used,
                cap=org_cap,
                pool=_copilot_number(config.get("pool")) or 0,
                plan=config.get("plan"),
            )
        else:
            login = _gh_api_text("user", "-q", ".login")
            if not login:
                return False
            response = _gh_api_json(f"/users/{login}/settings/billing/usage?year={year}&month={month}")
            if response is None:
                return False
            used = _copilot_usage_total(response, skus)
            cap = _copilot_derived_cap(response) or _copilot_positive_number(config.get("cap"))
            record = _copilot_record(
                mode,
                used,
                cap=cap,
                pool=_copilot_number(config.get("pool")) or 0,
                plan=config.get("plan"),
            )

        return _write_json(_cache_path("copilot"), {"cached_at": time.time(), "record": record}) is True
    except Exception:
        return False


def _provider_refresh_config(provider, config):
    if provider == "copilot":
        return _copilot_provider_config(config)
    if provider == "glm":
        return _glm_provider_config(config, include_api_key=False)
    return {}


def _spawn_provider_refresh(provider, config):
    if provider not in {"copilot", "glm"}:
        return
    try:
        env = dict(os.environ)
        try:
            env["HOME"] = str(Path.home())
        except Exception:
            pass
        env["CLAUDE_STATUSLINE_PROVIDER_LIB"] = str(Path(__file__).resolve().parent)
        env["CLAUDE_STATUSLINE_REFRESH_PROVIDER"] = provider
        env["CLAUDE_STATUSLINE_REFRESH_CONFIG"] = json.dumps(_provider_refresh_config(provider, config))
        if provider == "copilot":
            env["CLAUDE_STATUSLINE_COPILOT_CONFIG"] = env["CLAUDE_STATUSLINE_REFRESH_CONFIG"]
        code = (
            "import json, os, sys; "
            "sys.path.insert(0, os.environ.get('CLAUDE_STATUSLINE_PROVIDER_LIB', '')); "
            "import usage_providers; "
            "provider=os.environ.get('CLAUDE_STATUSLINE_REFRESH_PROVIDER', ''); "
            "cfg=json.loads(os.environ.get('CLAUDE_STATUSLINE_REFRESH_CONFIG', '{}')); "
            "usage_providers.refresh_copilot_cache(cfg) if provider == 'copilot' "
            "else usage_providers.refresh_glm_cache(cfg) if provider == 'glm' else None"
        )
        subprocess.Popen(
            ["python3", "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except Exception:
        pass


def _spawn_copilot_refresh(config):
    _spawn_provider_refresh("copilot", config)


def get_copilot_usage(config=None):
    """GitHub Copilot AI-credit usage.

    Reads statusline-usage-copilot.json synchronously. When the cache is missing
    or older than COPILOT_CACHE_TTL, it kicks off a detached in-process refresher
    and returns the stale record immediately so rendering never blocks on gh/API.
    """
    path = _cache_path("copilot")
    data = _read_json(path)
    try:
        age = time.time() - path.stat().st_mtime
    except Exception:
        age = None
    if age is None or age > COPILOT_CACHE_TTL:
        _spawn_provider_refresh("copilot", config)
    record = data.get("record") if isinstance(data, dict) else None
    if not _is_available_record(record):
        return unavailable("copilot")
    if age is not None and age > COPILOT_CACHE_TTL:
        record = dict(record)
        record["stale_seconds"] = max(0, int(age))
    return record


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
        if provider == "copilot":
            return get_copilot_usage(config)
    except Exception:
        pass
    return unavailable(provider) if provider in PROVIDERS else None


def collect_external_usage(config, only=None):
    """Fetch external-provider usage records.

    ``only`` — when an ordered list of provider names is supplied, fetch exactly
    those providers (in that order), treating the selection as authoritative
    (the ``external_providers.enabled`` / per-provider enabled flags are not
    consulted for gating; the per-provider config block is still read so each
    reader gets its ``base_url`` / ``api_key`` / ``bin``). Default (None)
    preserves the legacy enabled-flag iteration.
    """
    external = config.get("external_providers") if isinstance(config, dict) else None
    if not isinstance(external, dict):
        external = {}

    if only is not None:
        providers_iter = [p for p in only if p in PROVIDERS]
    else:
        if external.get("enabled") is not True:
            return []
        providers_iter = [
            p
            for p in ("codex", "glm", "droid", "antigravity", "copilot")
            if isinstance(external.get(p), dict) and external.get(p).get("enabled") is True
        ]

    records = []
    for provider in providers_iter:
        provider_config = external.get(provider)
        if not isinstance(provider_config, dict):
            provider_config = {}
        record = get_provider_usage(provider, provider_config)
        if isinstance(record, dict):
            records.append(record)
    return records
