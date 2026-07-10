"""External CLI usage providers for the statusline.

Every public provider reader returns a normalized record and never raises.
"""
import json
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import threading
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
# A Codex plan the owner stopped using ages out of the surfaced list naturally:
# only plans whose newest snapshot is at most this old appear in ``all_plans``.
CODEX_PLAN_MAX_AGE_SECONDS = 7 * 86400
GLM_CACHE_TTL = 60
# A live `codex app-server` rate-limit snapshot stays authoritative this long
# before the detached refresher is asked to pull a fresh one. Matches the GLM
# background-refresh cadence (get path is cache-only for the live record).
CODEX_LIVE_TTL = 120
# Hard ceiling on the whole app-server exchange (spawn -> initialize ->
# account/rateLimits/read). The child is always killed when this elapses.
CODEX_APP_SERVER_TIMEOUT = 10.0
# The two-pool Antigravity quota-summary cache is refreshed in the background on
# this cadence (mirrors the GLM detached-refresh pattern).
ANTIGRAVITY_CACHE_TTL = 120
# A stale quota-summary (5h + weekly per pool) still beats the CLI's 5h-only
# view; only past this horizon does the render drop to the CLI fallback.
ANTIGRAVITY_SUMMARY_MAX_AGE = 6 * 3600
# Hard overall wall-clock budget for one quota-summary refresh (local + cloud).
ANTIGRAVITY_REFRESH_BUDGET = 8.0
ANTIGRAVITY_LOCAL_RPC_PATH = (
    "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
)
ANTIGRAVITY_CLOUD_URL = (
    "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
)
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

    # Codex surfaces EVERY detected plan (free + paid). When the record carries an
    # ``all_plans`` list, render one row per plan — each formatted exactly like a
    # single Codex row (label, plan chip, windows/bars, reset, stale marker) — via
    # the same sub_rows seam the engines already iterate. Absent/empty all_plans
    # falls back to the single record below, so old caches keep rendering one line.
    all_plans = record.get("all_plans")
    if isinstance(all_plans, list) and all_plans:
        sub_rows = []
        for plan_record in all_plans:
            sub = format_provider_row_parts(
                plan_record, now_sec, label_width, format_duration, format_clock
            )
            if sub is None:
                continue
            nested = sub.get("sub_rows")
            if isinstance(nested, list) and nested:
                sub_rows.extend(nested)
            else:
                sub_rows.append(sub)
        if len(sub_rows) == 1:
            return sub_rows[0]
        if sub_rows:
            multi = {
                "label": label,
                "display": "codex_multi",
                "parts": parts,
                "sub_rows": sub_rows,
                "stale": stale,
                "stale_text": " ·stale" if stale else "",
            }
            multi["text"] = "\n".join(sub["text"] for sub in sub_rows)
            return multi

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
    # A resumed/idle session can have a fresher mtime than the last real turn
    # and end on a tokens-only event (no rate-limit windows). Per plan, keep the
    # newest WINDOWED snapshot; a window-less one is only a placeholder that a
    # later (older) windowed file for the same plan upgrades in place.
    def _has_windows(record):
        return bool(record.get("five_hour") or record.get("weekly"))

    ordered = []
    by_plan = {}
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
        idx = by_plan.get(plan_key)
        if idx is None:
            by_plan[plan_key] = len(ordered)
            ordered.append(record)
        elif _has_windows(record) and not _has_windows(ordered[idx]):
            ordered[idx] = record
        if len(by_plan) >= 2 and all(_has_windows(r) for r in ordered):
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


def _codex_show_all_plans(config):
    """The configured show_all_plans flag (external_providers.codex.show_all_plans).

    Accepts either the codex provider block ({"show_all_plans": true}) as passed
    by collect_external_usage, or a full config carrying external_providers.codex.
    Default is falsy: Codex renders a single row for the SELECTED plan.
    """
    if not isinstance(config, dict):
        return False
    flag = config.get("show_all_plans")
    if not flag:
        external = config.get("external_providers")
        if isinstance(external, dict) and isinstance(external.get("codex"), dict):
            flag = external["codex"].get("show_all_plans")
    return bool(flag)


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


def _codex_plan_is_fresh(record):
    """True when a plan snapshot is recent enough to surface (<= 7 days old)."""
    age = record.get("stale_seconds") if isinstance(record, dict) else None
    return age is None or _number_or_zero(age) <= CODEX_PLAN_MAX_AGE_SECONDS


def _codex_all_plans(ordered, config):
    """Every detected plan to surface, newest-first within group.

    Order: paid plans first (by recency), then free/unknown (by recency) — the
    scan already yields one record per plan newest-first, so a stable partition
    preserves recency within each group. Plans older than
    ``CODEX_PLAN_MAX_AGE_SECONDS`` age out. A configured plan pin is an explicit
    filter: only that plan's record is returned.
    """
    fresh = [record for record in ordered if _codex_plan_is_fresh(record)]
    pin = _codex_plan_pin(config)
    if pin:
        return [r for r in fresh if str(r.get("plan") or "").strip().lower() == pin]

    def _is_paid(record):
        plan = str(record.get("plan") or "").strip().lower()
        return bool(plan) and plan != "free"

    paid = [r for r in fresh if _is_paid(r)]
    rest = [r for r in fresh if not _is_paid(r)]
    return paid + rest


def _heal_codex_window(window, now):
    """A codex window whose reset time has already passed is provably stale.

    Codex usage comes only from local rollout logs, so a snapshot freezes
    between sessions. Once ``resets_at`` is in the past, the window has
    demonstrably reset, and the absence of any newer rollout for this plan
    proves zero recorded usage since — so render 0%, not a frozen (often
    100%) reading, instead of misleading the owner into thinking the window
    is still hot.
    """
    if not isinstance(window, dict):
        return window
    resets_at = window.get("resets_at")
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return window
    if resets_at > now:
        return window
    healed = {"used_pct": 0.0, "resets_at": None}
    label = window.get("label")
    if label:
        healed["label"] = label
    return healed


def _heal_codex_record(record, now=None):
    """Self-heal any elapsed five_hour/weekly window on a single codex record.

    Applied to freshly-built records (before caching) AND to cache hits (after
    ``_read_cached_record`` returns), so a cached record read up to
    ``LOCAL_CACHE_TTL`` seconds later still renders healed. Also walks
    ``all_plans`` so every per-plan row gets the same treatment. Idempotent and
    cheap, so calling it twice on the same record is harmless.
    """
    if not isinstance(record, dict):
        return record
    now = time.time() if now is None else now
    healed = dict(record)
    for key in ("five_hour", "weekly"):
        if key in healed:
            healed[key] = _heal_codex_window(healed.get(key), now)
    all_plans = healed.get("all_plans")
    if isinstance(all_plans, list):
        healed["all_plans"] = [_heal_codex_record(r, now) for r in all_plans]
    return healed


def _codex_bin(config):
    """The codex binary to spawn (config override wins, else PATH ``codex``)."""
    if isinstance(config, dict):
        for key in ("bin", "codex_bin"):
            value = config.get(key)
            if value:
                return str(value)
    return "codex"


def _read_codex_live_cache():
    """The cached codex record + its age, but ONLY when it is a live app-server
    snapshot (``source == "app-server"``).

    The rollout fallback and the live refresher share one cache file; the
    ``source`` tag is how the render path tells a live snapshot apart from a
    frozen rollout snapshot. Returns ``(record, age_seconds)`` or ``(None, None)``.
    """
    path = _cache_path("codex")
    try:
        age = max(0, int(time.time() - path.stat().st_mtime))
    except Exception:
        return None, None
    data = _read_json(path)
    record = data.get("record") if isinstance(data, dict) else None
    if not isinstance(record, dict) or record.get("source") != "app-server":
        return None, None
    if record.get("available") is not True:
        return None, None
    return record, age


def _kill_codex_proc(proc):
    """Best-effort teardown of the app-server child and its process group.

    The child is spawned in its own session (``start_new_session``), so killing
    the group reaps any helper it forked. Never raises.
    """
    if proc is None:
        return
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception:
        pass
    try:
        if proc.poll() is None:
            killed = False
            if hasattr(os, "killpg") and proc.pid:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    killed = True
                except Exception:
                    killed = False
            if not killed:
                proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _codex_app_server_exchange(binary, timeout=CODEX_APP_SERVER_TIMEOUT):
    """Run the read-only ``codex app-server`` handshake and return
    ``(account_result, rate_limits_result)`` (each the full JSON-RPC ``result``
    object, or None).

    Protocol: newline-delimited JSON-RPC 2.0 over stdio — ``initialize`` request,
    ``initialized`` notification, then ``account/read`` and
    ``account/rateLimits/read`` reads. NEVER starts a thread/turn, so no model is
    ever invoked. Any server->client request (e.g. an approval ask) is
    auto-denied. The child is always killed via try/finally. Returns
    ``(None, None)`` on any failure or timeout.
    """
    proc = None
    try:
        proc = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except Exception:
        return None, None

    deadline = time.time() + max(1.0, float(timeout))
    results = {}
    lock = threading.Lock()

    def _reader():
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                mid = msg.get("id")
                if mid is not None and ("result" in msg or "error" in msg):
                    with lock:
                        results[mid] = msg
                elif mid is not None and msg.get("method"):
                    # Server -> client request (approval ask): auto-deny so the
                    # server never blocks on us. We never run a turn, so this is
                    # belt-and-suspenders.
                    try:
                        proc.stdin.write(
                            json.dumps({"jsonrpc": "2.0", "id": mid, "result": {"decision": "denied"}}) + "\n"
                        )
                        proc.stdin.flush()
                    except Exception:
                        pass
        except Exception:
            pass

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    def _send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def _wait(mid):
        while time.time() < deadline:
            with lock:
                if mid in results:
                    return results[mid]
            if proc.poll() is not None:
                # Child exited; drain whatever the reader captured.
                with lock:
                    return results.get(mid)
            time.sleep(0.02)
        return None

    try:
        _send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "claude-2x-statusline",
                    "title": "claude-2x-statusline",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "experimentalApi": False,
                    "requestAttestation": False,
                    "optOutNotificationMethods": [],
                },
            },
        })
        if _wait(1) is None:
            return None, None
        _send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _send({"jsonrpc": "2.0", "id": 2, "method": "account/read", "params": {}})
        _send({"jsonrpc": "2.0", "id": 3, "method": "account/rateLimits/read", "params": {}})
        account_msg = _wait(2)
        rate_msg = _wait(3)
        account = account_msg.get("result") if isinstance(account_msg, dict) else None
        rate = rate_msg.get("result") if isinstance(rate_msg, dict) else None
        return account, rate
    except Exception:
        return None, None
    finally:
        _kill_codex_proc(proc)


def normalize_codex_rate_limits(account_result, rate_result, stale_seconds=0):
    """Normalize an ``account/rateLimits/read`` result into the standard codex
    record (same shape the rollout path produces).

    ``primary`` -> five_hour, ``secondary`` -> weekly, both via ``_usage_window``
    + ``_codex_window_label`` (windowDurationMins gives the honest 5h/7d/30d
    label). ``planType`` comes from the account read when present (authoritative
    for the logged-in account), else from the rate-limit snapshot. Tags
    ``source: "app-server"`` so the render path can tell it apart from a rollout
    snapshot.
    """
    result = rate_result if isinstance(rate_result, dict) else {}
    snapshot = result.get("rateLimits") if isinstance(result.get("rateLimits"), dict) else None
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and isinstance(by_id.get("codex"), dict):
        snapshot = by_id.get("codex")
    if not isinstance(snapshot, dict):
        return unavailable("codex")

    primary = snapshot.get("primary") if isinstance(snapshot.get("primary"), dict) else {}
    secondary = snapshot.get("secondary") if isinstance(snapshot.get("secondary"), dict) else {}
    five_hour = _usage_window(
        primary.get("usedPercent"),
        primary.get("resetsAt"),
        _codex_window_label(primary.get("windowDurationMins"), "5h"),
    )
    weekly = _usage_window(
        secondary.get("usedPercent"),
        secondary.get("resetsAt"),
        _codex_window_label(secondary.get("windowDurationMins"), "7d"),
    )

    plan = snapshot.get("planType")
    account = account_result.get("account") if isinstance(account_result, dict) else None
    if isinstance(account, dict) and account.get("planType"):
        plan = account.get("planType")

    record = unavailable("codex")
    record.update(
        {
            "available": bool(five_hour or weekly),
            "five_hour": five_hour,
            "weekly": weekly,
            "plan": plan,
            "source": "app-server",
            "stale_seconds": stale_seconds,
        }
    )
    return record


def refresh_codex_cache(config=None):
    """Refresh the Codex usage cache from a LIVE ``codex app-server`` snapshot.

    Spawns ``codex app-server``, performs the read-only initialize +
    account/rateLimits/read handshake (never a model turn), normalizes the live
    rate limits into the standard codex record, and writes it via the standard
    cache writer. Never-clobber: a missing binary, a broken protocol, an offline
    machine, or a logged-out account all return False and leave the last good
    cache untouched. Meant to run ONLY in the detached background refresher,
    never on the render path.
    """
    try:
        binary = _codex_bin(config)
        account, rate = _codex_app_server_exchange(binary, CODEX_APP_SERVER_TIMEOUT)
        if rate is None:
            return False
        record = normalize_codex_rate_limits(account, rate, stale_seconds=0)
        if not (isinstance(record, dict) and record.get("available")):
            return False
        record = _heal_codex_record(record)
        _write_cached_record("codex", record)
        return True
    except Exception:
        return False


def get_codex_usage(config=None):
    """Codex usage — prefer a fresh live app-server snapshot, fall back to the
    rollout scan.

    The live snapshot (``source: "app-server"``, written by the detached
    ``refresh_codex_cache``) describes only the CURRENTLY AUTHENTICATED account.
    It is preferred when the config wants that account's plan; a ``plan`` pin
    that selects a DIFFERENT plan than the live account, or ``show_all_plans``
    (which needs every plan the rollouts have seen), falls back to the rollout
    scan exactly as today. The elapsed-window self-heal stays on both paths.
    """
    try:
        live, live_age = _read_codex_live_cache()
        pin = _codex_plan_pin(config)
        show_all = _codex_show_all_plans(config)
        live_plan = str(live.get("plan") or "").strip().lower() if isinstance(live, dict) else ""
        # The pin is satisfied by live data only when it matches the live
        # account's plan (or there is no pin at all).
        pin_matches_live = (not pin) or (bool(live_plan) and pin == live_plan)
        want_live = not show_all

        if want_live:
            if live is None:
                # No live snapshot yet (cold start / codex offline / logged out):
                # warm the cache in the background and render from rollouts now.
                _spawn_provider_refresh("codex", config)
            elif pin_matches_live:
                if live_age is not None and live_age >= CODEX_LIVE_TTL:
                    _spawn_provider_refresh("codex", config)
                record = dict(live)
                record["stale_seconds"] = live_age
                return _heal_codex_record(record)
            # else: live account's plan != the pinned plan — keep the (still
            # valid) live snapshot untouched and answer the pin from rollouts.

        # ── Rollout fallback (self-healing, exactly as today) ─────────────────
        cached = _read_cached_record("codex", LOCAL_CACHE_TTL)
        # A live snapshot in the shared cache is not a rollout answer: never let
        # it satisfy the fallback (e.g. a pin/show_all render that needs rollout
        # data), or it would render the wrong account/plan.
        if cached and cached.get("source") != "app-server":
            return _heal_codex_record(cached)

        ordered = _codex_rollout_snapshots()
        # A plan the owner abandoned >7 days ago no longer competes for selection
        # (it has aged out); when every plan is stale, keep the legacy behavior of
        # still surfacing the best of them rather than vanishing.
        fresh = [record for record in ordered if _codex_plan_is_fresh(record)]
        record = _select_codex_snapshot(fresh or ordered, config)
        if record is None:
            return unavailable("codex")
        record = dict(record)
        # Opt-in: only attach all_plans (and thus render one row per plan) when
        # the owner explicitly asks for it. Default renders a single row for the
        # SELECTED plan (pin > newest paid > newest overall), matching one Codex
        # subscription per row.
        if show_all:
            record["all_plans"] = _codex_all_plans(ordered, config)
        record = _heal_codex_record(record)
        # Never clobber a still-fresh live snapshot with a rollout record: when a
        # pin selects a different plan than the live account (or show_all_plans
        # wants every plan) we render from rollouts, but the live cache must
        # survive so the next render keeps comparing against the real account.
        if live is None or (live_age is not None and live_age >= CODEX_LIVE_TTL):
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


_ANTIGRAVITY_POOL_ORDER = {"Gemini": 0, "Claude+GPT": 1}


def _antigravity_pool(model):
    """Classify one `antigravity-usage` models[] entry into Antigravity's real
    quota pool.

    Antigravity's actual quota structure is TWO pools that each share a single
    5-hour + weekly limit: "Gemini Models" and "Claude and GPT models" (Opus,
    Sonnet, and GPT all share ONE pool — they are not independent). Detection is
    by label/modelId keyword: "gemini", "flash", or "pro" land in the Gemini
    pool (the flash/pro terms keep old bare-label lineups, e.g. a bare "Flash"
    or "Pro" label with no "Gemini" prefix, in the right pool); everything else
    falls into the Claude+GPT pool.
    """
    label = str((model or {}).get("label") or "").strip()
    model_id = str((model or {}).get("modelId") or "").strip()
    hint = f"{label} {model_id}".lower()
    if "gemini" in hint or "flash" in hint or "pro" in hint:
        return "Gemini"
    return "Claude+GPT"


def _map_antigravity_snapshot(snapshot):
    """Map an `antigravity-usage quota --json` snapshot into Antigravity's two
    real quota pools (models[].remainingPercentage is a 0..1 fraction).

    models[].remainingPercentage measures only the 5-hour dimension of each
    pool (the CLI's raw quotaInfo carries just remainingFraction + resetTime,
    and every resetTime observed is a ~5h boundary); weekly data is not
    obtainable from this CLI, so these metrics stay 5h-only and no weekly
    figure is fabricated.

    Within a pool, used_pct is the MAX used_pct across member models (the
    worst case — equivalent to the pool's min remaining, matching the CLI's
    own --all pooling behavior); resets_at is that member's resetTime, or the
    earliest one among members tied on used_pct. Order: Gemini first, then
    Claude+GPT.
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
        pool = _antigravity_pool(m)
        used_pct = max(0, min(100, round((1 - frac) * 100)))
        reset = _parse_iso_seconds(m.get("resetTime"))
        reset = int(reset) if reset else None
        existing = groups.get(pool)
        if existing is None or used_pct > existing["used_pct"] or (
            used_pct == existing["used_pct"]
            and reset is not None
            and (existing["resets_at"] is None or reset < existing["resets_at"])
        ):
            groups[pool] = {"label": pool, "used_pct": used_pct, "resets_at": reset}
    if not groups:
        return None
    ordered = sorted(groups, key=lambda name: _ANTIGRAVITY_POOL_ORDER.get(name, 99))
    return [groups[name] for name in ordered]


# ── Antigravity quota-summary (RetrieveUserQuotaSummary RPC) ──────────────────
# The richer of Antigravity's two data sources: TWO pools ("gemini" and
# "claude+gpt", internally "3p") that EACH expose a 5-hour AND a weekly bucket,
# with independent reset times. Bucket ids are matched exactly. remainingFraction
# is 0..1 where 1 == full, so used% = round((1-fraction)*100).
_ANTIGRAVITY_QUOTA_POOLS = (
    # (plan label, 5h bucket id, weekly bucket id)
    ("gemini", "gemini-5h", "gemini-weekly"),
    ("claude+gpt", "3p-5h", "3p-weekly"),
)


def _antigravity_bucket_used_pct(fraction):
    number = _finite_number(fraction)
    if number is None:
        return None
    return max(0, min(100, int(round((1.0 - number) * 100))))


def _antigravity_quota_buckets(summary):
    """Flatten a RetrieveUserQuotaSummary response into {bucketId: {used_pct,
    resets_at}}. Accepts the local route's wrapped ``{"response": {"groups": ...}}``
    form and the cloud route's bare ``{"groups": ...}`` form."""
    if not isinstance(summary, dict):
        return {}
    root = summary.get("response") if isinstance(summary.get("response"), dict) else summary
    groups = root.get("groups") if isinstance(root, dict) else None
    if not isinstance(groups, list):
        return {}
    buckets = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        entries = group.get("buckets")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            bucket_id = entry.get("bucketId") or entry.get("bucket_id")
            if not bucket_id:
                continue
            used_pct = _antigravity_bucket_used_pct(
                entry.get("remainingFraction", entry.get("remaining_fraction"))
            )
            if used_pct is None:
                continue
            reset = _parse_iso_seconds(entry.get("resetTime") or entry.get("reset_time"))
            buckets[str(bucket_id)] = {
                "used_pct": used_pct,
                "resets_at": int(reset) if reset else None,
            }
    return buckets


def _map_antigravity_quota_summary(summary):
    """Map a RetrieveUserQuotaSummary response into Antigravity's two pool
    sub-records, each carrying a 5-hour and a weekly window (display "bars").

    Returns the ordered list [gemini, claude+gpt] of pool records that carry at
    least one window, or None when no known bucket is present.
    """
    buckets = _antigravity_quota_buckets(summary)
    if not buckets:
        return None
    pool_records = []
    for plan, five_id, weekly_id in _ANTIGRAVITY_QUOTA_POOLS:
        five = buckets.get(five_id)
        weekly = buckets.get(weekly_id)
        five_window = _usage_window(five["used_pct"], five["resets_at"], "5h") if five else None
        weekly_window = _usage_window(weekly["used_pct"], weekly["resets_at"], "wk") if weekly else None
        if five_window is None and weekly_window is None:
            continue
        record = unavailable("antigravity")
        record.update(
            {
                "available": True,
                "label": "AGY",
                "plan": plan,
                "display": "bars",
                "five_hour": five_window,
                "weekly": weekly_window,
                "source": "quota-summary",
                "stale_seconds": 0,
            }
        )
        pool_records.append(record)
    return pool_records or None


def _compose_antigravity_quota_record(pool_records):
    """Compose the cached codex-style antigravity record from pool sub-records:
    the top-level mirrors the WORST pool (highest max used across its windows)
    for backward compat, and ``all_plans`` fans out one row per pool via the same
    seam codex multi-plan rows use."""
    if not pool_records:
        return None

    def pool_max_used(record):
        values = [
            window.get("used_pct")
            for window in (record.get("five_hour"), record.get("weekly"))
            if isinstance(window, dict)
        ]
        return max(values) if values else 0

    worst = max(pool_records, key=pool_max_used)
    record = unavailable("antigravity")
    record.update(
        {
            "available": True,
            "label": "AGY",
            "plan": worst.get("plan"),
            "display": "bars",
            "five_hour": worst.get("five_hour"),
            "weekly": worst.get("weekly"),
            "source": "quota-summary",
            "stale_seconds": 0,
            "all_plans": pool_records,
        }
    )
    return record


def _antigravity_extract_arg(cmdline, name):
    """Pull a ``--flag=value`` / ``--flag value`` argument out of a process
    command line, stripping any surrounding quotes (mirrors the CLI parser)."""
    escaped = re.escape(name)
    for pattern in (
        rf"{escaped}=([^\s\"']+|\"[^\"]*\"|'[^']*')",
        rf"{escaped}\s+([^\s\"']+|\"[^\"]*\"|'[^']*')",
    ):
        match = re.search(pattern, cmdline)
        if match:
            return match.group(1).strip("\"'")
    return None


def _antigravity_local_process(timeout=3.0):
    """Scan ``ps aux`` for the running Antigravity language server. Returns
    ``(pid, csrf_token, extension_server_port)``. The CSRF token lives in memory
    only — it is never logged, cached, or passed via argv."""
    try:
        proc = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None, None, None
    for line in (proc.stdout or "").splitlines():
        lower = line.lower()
        if "antigravity" not in lower or "server installation script" in lower:
            continue
        if not any(
            signal in line
            for signal in (
                "language-server",
                "lsp",
                "--csrf_token",
                "--extension_server_port",
                "exa.language_server_pb",
            )
        ):
            continue
        parts = line.split()
        if len(parts) < 11:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        cmdline = " ".join(parts[10:])
        return (
            pid,
            _antigravity_extract_arg(cmdline, "--csrf_token"),
            _antigravity_extract_arg(cmdline, "--extension_server_port"),
        )
    return None, None, None


def _antigravity_listen_ports(pid, timeout=3.0):
    ports = []
    try:
        proc = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", str(pid)],
            capture_output=True, text=True, timeout=timeout,
        )
        for line in (proc.stdout or "").splitlines():
            match = re.search(r":(\d+)\s+\(LISTEN\)", line)
            if match:
                port = int(match.group(1))
                if port not in ports:
                    ports.append(port)
    except Exception:
        pass
    return ports


def _antigravity_local_summary(deadline):
    """Fetch RetrieveUserQuotaSummary from the local Antigravity language server
    (preferred while the IDE runs). Self-signed TLS is accepted only for
    127.0.0.1. Returns mapped pool records or None."""

    def remaining():
        return deadline - time.time()

    pid, csrf, ext_port = _antigravity_local_process(max(0.2, min(3.0, remaining())))
    if pid is None:
        return None
    ports = _antigravity_listen_ports(pid, max(0.2, min(3.0, remaining())))
    if not ports and ext_port:
        try:
            ports = [int(ext_port)]
        except (TypeError, ValueError):
            ports = []
    if not ports:
        return None

    body = json.dumps(
        {"metadata": {"ideName": "antigravity", "extensionName": "antigravity", "locale": "en"}}
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connect-Protocol-Version": "1",
    }
    if csrf:
        headers["X-Codeium-Csrf-Token"] = csrf

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for port in ports:
        for scheme in ("https", "http"):
            if remaining() <= 0:
                return None
            url = f"{scheme}://127.0.0.1:{port}{ANTIGRAVITY_LOCAL_RPC_PATH}"
            try:
                request = urllib.request.Request(url, data=body, headers=headers, method="POST")
                kwargs = {"timeout": max(0.2, min(2.5, remaining()))}
                if scheme == "https":
                    kwargs["context"] = ctx
                with urllib.request.urlopen(request, **kwargs) as resp:
                    data = json.loads(resp.read())
            except Exception:
                continue
            summary = _map_antigravity_quota_summary(data)
            if summary:
                return summary
    return None


def _antigravity_config_dir():
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "antigravity-usage"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(base) / "antigravity-usage"
    base = os.environ.get("XDG_CONFIG_HOME") or str(home / ".config")
    return Path(base) / "antigravity-usage"


def _read_antigravity_oauth():
    """Read (read-only) the OAuth access token + expiry (ms epoch) the
    ``antigravity-usage`` CLI stores. The token is returned for in-memory use
    only; it is never logged, cached, or written anywhere."""
    try:
        config_dir = _antigravity_config_dir()
        tokens = None
        config = _read_json(config_dir / "config.json")
        email = config.get("activeAccount") if isinstance(config, dict) else None
        if email:
            safe = re.sub(r"[^a-zA-Z0-9@._-]", "_", str(email))
            tokens = _read_json(config_dir / "accounts" / safe / "tokens.json")
        if not isinstance(tokens, dict):
            tokens = _read_json(config_dir / "tokens.json")
        if not isinstance(tokens, dict):
            return None, None
        token = tokens.get("accessToken")
        if not token:
            return None, None
        expires_at = tokens.get("expiresAt")
        expires_at = float(expires_at) if isinstance(expires_at, (int, float)) else None
        return str(token), expires_at
    except Exception:
        return None, None


def _antigravity_cloud_summary(deadline):
    """Fetch retrieveUserQuotaSummary from the Google cloud route with the stored
    OAuth bearer (fallback when the IDE is closed). On an expired token or any
    auth error we give up gracefully for this cycle — no token refresh."""
    token, expires_at = _read_antigravity_oauth()
    if not token:
        return None
    if expires_at is not None and (time.time() * 1000.0) >= expires_at:
        return None
    body = json.dumps({}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "antigravity",
    }
    try:
        request = urllib.request.Request(
            ANTIGRAVITY_CLOUD_URL, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=max(0.2, min(5.0, deadline - time.time()))) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    return _map_antigravity_quota_summary(data)


def refresh_antigravity_cache(config=None):
    """Refresh the Antigravity two-pool quota-summary cache (5h + weekly per
    pool) from the RetrieveUserQuotaSummary RPC.

    Tries the local Antigravity language-server route first, then the cloud route
    with the stored OAuth bearer. Never clobbers a prior cache on failure (writes
    only on a mapped, available record). All CSRF/token material stays in memory
    only. Runs under a hard overall deadline. Meant to be called from the
    detached provider refresher, never on the render path.
    """
    deadline = time.time() + ANTIGRAVITY_REFRESH_BUDGET
    try:
        summary = _antigravity_local_summary(deadline)
        if summary is None:
            summary = _antigravity_cloud_summary(deadline)
        if not summary:
            return False
        record = _compose_antigravity_quota_record(summary)
        if not (isinstance(record, dict) and record.get("available")):
            return False
        return _write_json(
            _cache_path("antigravity"), {"cached_at": time.time(), "record": record}
        ) is True
    except Exception:
        return False


def _antigravity_cli_usage(config):
    """Antigravity quota via the ``antigravity-usage`` CLI (owns OAuth refresh +
    local-IDE/cloud fallback). This is the 5h-only compact fallback used when no
    fresh quota-summary cache is available. Caches BOTH hits and misses so a
    logged-out machine never re-spawns the CLI on every render."""
    config = config if isinstance(config, dict) else {}
    cached = _read_cached_record("antigravity-cli", GLM_CACHE_TTL)
    if cached is not None:
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
    # The CLI path owns its own cache file so it can NEVER clobber the richer
    # quota-summary record in the main cache (that clobber hid the two-pool rows).
    _write_json(_cache_path("antigravity-cli"), {"cached_at": time.time(), "record": record})
    # Keep the main cache populated for out-of-band readers (narrator, VS Code)
    # on machines where the quota-summary route never succeeds — but never
    # downgrade a usable summary record.
    try:
        main = _read_json(_cache_path("antigravity"))
        main_record = main.get("record") if isinstance(main, dict) else None
        main_age = time.time() - float(main.get("cached_at", 0)) if isinstance(main, dict) else None
        summary_alive = (
            isinstance(main_record, dict)
            and main_record.get("source") == "quota-summary"
            and main_age is not None
            and main_age < ANTIGRAVITY_SUMMARY_MAX_AGE
        )
        if not summary_alive:
            _write_json(_cache_path("antigravity"), {"cached_at": time.time(), "record": record})
    except Exception:
        pass
    return record


def get_antigravity_usage(config=None):
    """Antigravity quota.

    Prefers the two-pool quota-summary cache (5h + weekly per pool, refreshed in
    a detached child like GLM), then falls back to the ``antigravity-usage`` CLI
    5h-only compact path, then to unavailable. The render path never blocks on
    the network: the quota-summary fetch happens in the background.
    """
    try:
        config = config if isinstance(config, dict) else {}
        path = _cache_path("antigravity")
        data = _read_json(path)
        try:
            age = int(time.time() - path.stat().st_mtime)
        except Exception:
            age = None
        record = data.get("record") if isinstance(data, dict) else None

        # Background quota-summary refresh (GLM pattern): spawn when missing/aging.
        if age is None or age >= ANTIGRAVITY_CACHE_TTL:
            _spawn_provider_refresh("antigravity", config)

        # 1) Two-pool quota-summary cache wins — even stale (up to the horizon),
        # because 5h+weekly per pool beats the CLI's 5h-only view. The TTL above
        # already triggered the background refresh; staleness stays honest via
        # stale_seconds.
        if (
            _is_available_record(record)
            and record.get("source") == "quota-summary"
            and age is not None
            and age < ANTIGRAVITY_SUMMARY_MAX_AGE
        ):
            out = dict(record)
            out["stale_seconds"] = max(0, age)
            return out

        # 2) Existing CLI 5h-only compact path.
        cli = _antigravity_cli_usage(config)
        if _is_available_record(cli):
            return cli

        # 3) Any still-available cached record (stale quota-summary), else unavailable.
        if _is_available_record(record):
            out = dict(record)
            out["stale_seconds"] = max(0, age or 0)
            return out
        return unavailable("antigravity")
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


def _codex_refresh_config(config):
    """Redaction-safe config for the detached codex refresher: just an optional
    binary override. Codex app-server carries its own on-disk auth, so no token
    ever crosses argv or the environment.
    """
    cfg = {}
    if isinstance(config, dict):
        block = config
        external = config.get("external_providers")
        if isinstance(external, dict) and isinstance(external.get("codex"), dict):
            block = external.get("codex")
        if isinstance(block, dict) and block.get("bin"):
            cfg["bin"] = str(block.get("bin"))
    return cfg


def _provider_refresh_config(provider, config):
    if provider == "copilot":
        return _copilot_provider_config(config)
    if provider == "glm":
        return _glm_provider_config(config, include_api_key=False)
    if provider == "codex":
        return _codex_refresh_config(config)
    # Antigravity discovers its own transport (process scan / OAuth storage); it
    # needs no secrets or per-provider config carried across the spawn boundary.
    return {}


def _codex_live_refresh_viable(config):
    """True only when a live app-server refresh can plausibly succeed: the codex
    binary is resolvable AND the account is logged in (``~/.codex/auth.json``
    exists). Gating here keeps the render path from spawning a doomed refresher
    for a missing/logged-out codex, and keeps the rollout-only tests hermetic (a
    temp HOME has no auth.json). Never-clobber: the rollout fallback stays in play.
    """
    if shutil.which(_codex_bin(_codex_refresh_config(config))) is None:
        return False
    try:
        return (Path.home() / ".codex" / "auth.json").is_file()
    except Exception:
        return False


def _spawn_provider_refresh(provider, config):
    if provider not in {"copilot", "glm", "codex", "antigravity"}:
        return
    if provider == "codex" and not _codex_live_refresh_viable(config):
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
            "else usage_providers.refresh_glm_cache(cfg) if provider == 'glm' "
            "else usage_providers.refresh_codex_cache(cfg) if provider == 'codex' "
            "else usage_providers.refresh_antigravity_cache(cfg) if provider == 'antigravity' "
            "else None"
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
