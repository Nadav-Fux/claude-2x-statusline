#!/usr/bin/env python3
"""Codex usage tracker for claude-2x-statusline.

Samples the Codex rate-limit % that the statusline already caches
(~/.claude/statusline-usage-codex.json) into a timestamped history at
~/.claude/codex-usage-history.jsonl, so you can see WHEN the number moves and
correlate the jumps with what actually ran (automations, ambient features, real
sessions).

It reads the EXISTING cache only — it never spawns Codex or calls the model, so
sampling costs zero tokens.

Commands:
  codex-usage-tracker.py log            append one sample (run this on a schedule)
  codex-usage-tracker.py show [N]       show the last N samples with deltas (default 50)
  codex-usage-tracker.py watch [N]      log one sample, then show (a quick one-shot check)
  codex-usage-tracker.py breakdown [D]  attribute usage over the last D days (default 7) from
                                        ~/.codex/sessions rollout logs — by day, project,
                                        and who launched it (you vs spawned subagents)
  codex-usage-tracker.py session <q>    drill into ONE run: what it did — task, subagents it
                                        spawned, files it touched, and its final message.
                                        <q> matches a subagent nickname, session-id, or path
                                        (or "top" for the biggest run in the last 7 days).
  codex-usage-tracker.py threads [H]    live model threads in the last H hours (default 24) from
                                        the app's own event log (~/.codex/logs_*.sqlite) — turns,
                                        streams, tool-calls per thread. Catches Desktop/cloud
                                        agent runs that DON'T write ~/.codex/sessions rollouts
                                        (the "I didn't touch it" usage).

When you `log`, the sample also records how many model TURNS ran since the previous
sample and which thread(s) drove them — so `show` can attribute a %-jump to the run
that caused it. Turn data comes from the app's local event log; still zero token cost.

Schedule continuous tracking (macOS/Linux), e.g. every 10 minutes via cron:
  */10 * * * * /usr/bin/python3 <this-path> log
"""
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

CACHE = Path.home() / ".claude" / "statusline-usage-codex.json"
HISTORY = Path.home() / ".claude" / "codex-usage-history.jsonl"
SESSIONS_DIR = Path.home() / ".codex" / "sessions"
CODEX_DIR = Path.home() / ".codex"


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _log_db():
    """Newest ~/.codex/logs_*.sqlite (the ChatGPT/Codex app's own event log).

    This is where the merged Desktop app records model turns, tool calls, and
    streaming responses for cloud/desktop agent runs that never write a
    ~/.codex/sessions rollout file — exactly the "I didn't touch it" usage.
    Returns None when no log DB exists.
    """
    try:
        dbs = [p for p in CODEX_DIR.glob("logs_*.sqlite") if p.suffix == ".sqlite"]
        return max(dbs, key=lambda p: p.stat().st_mtime) if dbs else None
    except Exception:
        return None


def _query_log(sql, params=()):
    """Run a read-only query against the app event log. Never raises, never
    writes, never touches the network — zero token cost. Returns [] on any
    problem (missing DB, lock, schema drift)."""
    db = _log_db()
    if db is None:
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    except Exception:
        return []


# Event-log target names for the model paths we attribute usage to.
_TURN_TARGET = "codex_core::session::turn"
_STREAM_TARGET = "codex_api::sse::responses"
_TOOL_TARGET = "codex_core::tools::parallel"


def _turns_since(since_ts):
    """(total model turns, [[short_thread_id, count], ...]) since since_ts."""
    rows = _query_log(
        "SELECT thread_id, COUNT(*) FROM logs "
        "WHERE ts >= ? AND target = ? AND thread_id IS NOT NULL "
        "GROUP BY thread_id ORDER BY COUNT(*) DESC",
        (int(since_ts), _TURN_TARGET),
    )
    threads = [[str(tid)[:13], int(n)] for tid, n in rows if tid]
    return sum(n for _, n in threads), threads


def _last_sample_ts():
    """Timestamp of the most recent history sample, or None."""
    if not HISTORY.exists():
        return None
    try:
        for line in reversed(HISTORY.read_text(encoding="utf-8").splitlines()):
            try:
                return json.loads(line).get("t")
            except Exception:
                continue
    except Exception:
        return None
    return None


def _total_tokens(rec):
    tokens = rec.get("tokens")
    if not isinstance(tokens, dict):
        return None
    for key in ("total_tokens", "total", "tokens"):
        val = tokens.get(key)
        if isinstance(val, (int, float)):
            return int(val)
    nums = [v for v in tokens.values() if isinstance(v, (int, float))]
    return int(sum(nums)) if nums else None


def _sample(since_ts=None):
    data = _read_json(CACHE)
    rec = data.get("record") if isinstance(data, dict) else None
    if not isinstance(rec, dict) or not rec.get("available"):
        return None
    # Codex puts its shown window in `five_hour` (labelled "7d" on team plans),
    # falling back to `weekly`.
    win = rec.get("five_hour") or rec.get("weekly") or {}
    if not isinstance(win, dict):
        win = {}
    cached_at = data.get("cached_at") if isinstance(data, dict) else None
    # Attribute the interval since the previous sample (default: last 15 min) to
    # the model turns that ran in it.
    if since_ts is None:
        since_ts = time.time() - 900
    turns, threads = _turns_since(since_ts)
    return {
        "t": round(time.time(), 1),
        "used_pct": win.get("used_pct"),
        "label": win.get("label"),
        "resets_at": win.get("resets_at"),
        "plan": rec.get("plan"),
        "source": rec.get("source"),
        "stale_seconds": rec.get("stale_seconds"),
        "total_tokens": _total_tokens(rec),
        "cache_age_s": round(time.time() - cached_at, 1) if isinstance(cached_at, (int, float)) else None,
        "turns_since": turns,
        "threads_since": threads[:3],
        "since_ts": round(since_ts, 1),
    }


def cmd_log():
    sample = _sample(_last_sample_ts())
    if sample is None:
        print("no available Codex cache to sample (is Codex logged in / the statusline running?)", file=sys.stderr)
        return 1
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample) + "\n")
    pct = sample["used_pct"]
    turns = sample.get("turns_since") or 0
    attribution = ""
    if turns:
        who = ", ".join(f"{tid}({n})" for tid, n in sample.get("threads_since", [])) or "?"
        attribution = f" · {turns} model turns since last [{who}]"
    print(f"logged {pct}% {sample.get('label')} (plan={sample.get('plan')}, source={sample.get('source')}){attribution} -> {HISTORY}")
    return 0


def cmd_show(count=50):
    if not HISTORY.exists():
        print("no history yet — run 'log' (ideally on a schedule) to start collecting.")
        return 0
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines()[-count:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    if not rows:
        print("history file is empty.")
        return 0

    print(f"{'when':<17}{'used':>7}{'delta':>7}{'turns':>6}   what drove it")
    print("-" * 62)
    prev_pct = None
    prev_t = None
    for row in rows:
        when = datetime.fromtimestamp(row["t"]).strftime("%m-%d %H:%M:%S")
        pct = row.get("used_pct")
        pct_s = f"{pct:g}%" if isinstance(pct, (int, float)) else "-"
        if prev_pct is not None and isinstance(pct, (int, float)):
            diff = pct - prev_pct
            delta_s = f"{diff:+g}" if diff else "·"
        else:
            delta_s = ""
        turns = row.get("turns_since")
        turns_s = str(turns) if isinstance(turns, int) else "-"
        who = ", ".join(f"{tid}({n})" for tid, n in row.get("threads_since", []) if isinstance(tid, str))
        note = ""
        if isinstance(pct, (int, float)) and prev_pct is not None and pct - prev_pct >= 1:
            gap_min = (row["t"] - prev_t) / 60 if prev_t else 0
            note = f"<== +{pct - prev_pct:g}% over {gap_min:.0f}m"
        detail = who or note
        if who and note:
            detail = f"{note}  {who}"
        print(f"{when:<17}{pct_s:>7}{delta_s:>7}{turns_s:>6}   {detail}")
        if isinstance(pct, (int, float)):
            prev_pct = pct
            prev_t = row["t"]

    first, last = rows[0], rows[-1]
    span_h = (last["t"] - first["t"]) / 3600 if len(rows) > 1 else 0
    if isinstance(first.get("used_pct"), (int, float)) and isinstance(last.get("used_pct"), (int, float)) and span_h:
        net = last["used_pct"] - first["used_pct"]
        print("-" * 60)
        print(f"net {net:+g}% over {span_h:.1f}h  ({net / span_h:+.2f}%/h)  ·  {len(rows)} samples")
    return 0


def _session_summary(path):
    """(cwd, launcher, token totals) for one rollout file — reads the session
    meta and the LAST token_count event (Codex reports running cumulative
    totals, so the last event is the session's final figure). Returns None when
    the file carries no token data."""
    meta = None
    last_usage = None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if meta is None and '"session_meta"' in line:
                    try:
                        meta = json.loads(line).get("payload", {})
                    except Exception:
                        pass
                elif '"token_count"' in line and "total_token_usage" in line:
                    try:
                        usage = json.loads(line).get("payload", {}).get("info", {}).get("total_token_usage")
                        if isinstance(usage, dict):
                            last_usage = usage
                    except Exception:
                        pass
    except Exception:
        return None
    if not isinstance(last_usage, dict):
        return None
    meta = meta if isinstance(meta, dict) else {}
    src = meta.get("source")
    if isinstance(src, dict) and "subagent" in src:
        launcher = f"subagent:{meta.get('agent_nickname', '?')}"
    elif isinstance(src, str):
        launcher = src
    else:
        launcher = str(meta.get("thread_source", "?"))
    home = str(Path.home())
    return {
        "cwd": str(meta.get("cwd", "?")).replace(home, "~"),
        "launcher": launcher,
        "originator": meta.get("originator", "?"),
        "total": int(last_usage.get("total_tokens", 0) or 0),
        "cached": int(last_usage.get("cached_input_tokens", 0) or 0),
        "out": int(last_usage.get("output_tokens", 0) or 0),
    }


def cmd_breakdown(days=7):
    cutoff = time.time() - days * 86400
    try:
        paths = list(SESSIONS_DIR.glob("*/*/*/rollout-*.jsonl"))
    except Exception:
        paths = []
    rows = []
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        summary = _session_summary(path)
        if summary:
            summary["mt"] = mtime
            rows.append(summary)
    if not rows:
        print(f"no Codex sessions with token data in the last {days} days under {SESSIONS_DIR}")
        return 0

    from collections import defaultdict

    grand = sum(r["total"] for r in rows)
    cached = sum(r["cached"] for r in rows)
    out = sum(r["out"] for r in rows)
    print(f"=== Codex usage reconstructed from local rollout logs — last {days} days ===")
    print(f"{len(rows)} sessions · {grand:,} total tokens "
          f"({cached:,} cached-input re-counted, {out:,} output)")
    print("note: totals are cumulative per turn (cached context is re-counted each turn), so")
    print("      they overstate raw usage; OpenAI's rate-limit % weights these differently.")
    print("      Use the SHARE between rows, not the absolute number, to see where it went.\n")

    def dump(title, key, top=None, timefmt=None):
        agg = defaultdict(lambda: [0, 0])
        for r in rows:
            k = key(r)
            agg[k][0] += r["total"]
            agg[k][1] += 1
        items = sorted(agg.items(), key=lambda x: -x[1][0])
        if top:
            items = items[:top]
        print(title)
        for k, (tot, n) in items:
            pct = (100.0 * tot / grand) if grand else 0
            print(f"  {tot:>15,} tok  {pct:4.0f}%  ({n:>2} sess)  {k}")
        print()

    dump("BY DAY:", lambda r: datetime.fromtimestamp(r["mt"]).strftime("%a %d/%m"))
    dump("BY PROJECT (cwd):", lambda r: r["cwd"], top=10)
    dump("BY LAUNCHER (you vs spawned subagents):", lambda r: r["launcher"], top=15)

    print("TOP 10 SESSIONS:")
    for r in sorted(rows, key=lambda x: -x["total"])[:10]:
        when = datetime.fromtimestamp(r["mt"]).strftime("%d/%m %H:%M")
        print(f"  {r['total']:>13,} tok  {when}  {r['launcher']:<20} {r['cwd']}")
    return 0


def _clean_text(text):
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cmd_session(query, days=7):
    """Print a readable 'what did this run do' report for one rollout."""
    query = (query or "top").strip()
    match_path = Path(query)
    target = None
    if match_path.is_file():
        target = match_path
    else:
        cutoff = time.time() - days * 86400
        candidates = []
        try:
            paths = list(SESSIONS_DIR.glob("*/*/*/rollout-*.jsonl"))
        except Exception:
            paths = []
        for path in paths:
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            summary = _session_summary(path)
            if not summary:
                continue
            q = query.lower()
            hit = q in ("top", "") or q in path.name.lower() or q in summary["launcher"].lower()
            if not hit:
                # fall back to a content scan for a nickname / session-id
                try:
                    hit = q in path.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
                except Exception:
                    hit = False
            if hit:
                candidates.append((summary["total"], path))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            target = candidates[0][1]
    if target is None:
        print(f"no run matched {query!r} in the last {days} days.")
        return 1

    import collections
    meta = None
    first_user = None
    last_agent = None
    files = collections.Counter()
    subs = collections.Counter()
    calls = patches = total = 0
    first_ts = last_ts = None
    try:
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}
                ptype = payload.get("type")
                ts = event.get("timestamp")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = ts
                if event.get("type") == "session_meta" and meta is None:
                    meta = payload
                if ptype == "message" and payload.get("role") == "user" and first_user is None:
                    text = _clean_text(" ".join(c.get("text", "") for c in (payload.get("content") or []) if isinstance(c, dict)))
                    if text and "recommended_plugins" not in text[:40]:
                        first_user = text
                if ptype in ("agent_message", "message") and payload.get("role") in (None, "assistant"):
                    body = payload.get("content")
                    text = _clean_text(" ".join(c.get("text", "") for c in body if isinstance(c, dict)) if isinstance(body, list) else str(payload.get("message") or payload.get("text") or ""))
                    if text:
                        last_agent = text
                if ptype == "patch_apply_end":
                    patches += 1
                    for fpath in (payload.get("changes") or {}):
                        files[str(fpath).replace(str(Path.home()), "~")] += 1
                if ptype == "sub_agent_activity" and payload.get("kind") == "started":
                    subs[payload.get("agent_path", "?")] += 1
                if ptype in ("custom_tool_call", "function_call"):
                    calls += 1
                if ptype == "token_count":
                    usage = payload.get("info", {}).get("total_token_usage") or {}
                    if usage.get("total_tokens"):
                        total = usage["total_tokens"]
    except Exception as exc:
        print(f"could not read {target}: {exc}")
        return 1

    meta = meta if isinstance(meta, dict) else {}
    src = meta.get("source")
    launcher = f"subagent:{meta.get('agent_nickname')}" if isinstance(src, dict) and "subagent" in src else (src if isinstance(src, str) else meta.get("thread_source", "?"))
    home = str(Path.home())
    print(f"file       : {str(target).replace(home, '~')}")
    print(f"project    : {str(meta.get('cwd', '?')).replace(home, '~')}")
    print(f"launched by: {launcher}   originator: {meta.get('originator', '?')}")
    print(f"span       : {first_ts} -> {last_ts}")
    print(f"tokens     : {total:,}   patches: {patches}   tool-calls: {calls}   subagents-spawned: {sum(subs.values())}")
    if first_user:
        print(f"\nTASK (first instruction):\n  {first_user[:600]}")
    if subs:
        print("\nSUBAGENTS IT SPAWNED (agent_path = their job):")
        for name, count in subs.most_common(20):
            print(f"  {count}x  {name}")
    if files:
        print(f"\nFILES IT TOUCHED (top 15 of {len(files)}):")
        for name, count in files.most_common(15):
            print(f"  {count}x  {name}")
    if last_agent:
        print(f"\nLAST THING IT SAID:\n  {last_agent[:500]}")
    return 0


def cmd_threads(hours=24):
    """List model threads active in the last <hours>, from the app event log.

    This is the complement to `breakdown`/`session` (which read rollout files):
    it surfaces Desktop/cloud agent runs that never write a rollout — the usage
    that climbs while you think you're 'not touching it'.
    """
    if _log_db() is None:
        print(f"no app event log found under {CODEX_DIR} (logs_*.sqlite).")
        return 1
    since = int(time.time() - hours * 3600)
    turn_rows = _query_log(
        "SELECT thread_id, COUNT(*), MIN(ts), MAX(ts) FROM logs "
        "WHERE ts >= ? AND target = ? AND thread_id IS NOT NULL "
        "GROUP BY thread_id ORDER BY MAX(ts) DESC",
        (since, _TURN_TARGET),
    )
    if not turn_rows:
        print(f"no model turns in the last {hours}h — nothing spent Codex quota in that window.")
        return 0

    def per_thread(target):
        return {str(tid): int(n) for tid, n in _query_log(
            "SELECT thread_id, COUNT(*) FROM logs WHERE ts >= ? AND target = ? "
            "AND thread_id IS NOT NULL GROUP BY thread_id", (since, target))}

    streams = per_thread(_STREAM_TARGET)
    tools = per_thread(_TOOL_TARGET)
    total_turns = sum(int(n) for _, n, _, _ in turn_rows)
    print(f"=== Codex model threads in the last {hours}h  ({len(turn_rows)} threads, {total_turns} turns) ===")
    print(f"source: {_log_db().name}   (agent runs; plain tool-free chat isn't here)\n")
    print(f"{'first':<15}{'last':<15}{'turns':>6}{'streams':>8}{'tools':>6}   thread")
    print("-" * 64)
    for tid, turns, mn, mx in turn_rows:
        first = datetime.fromtimestamp(mn).strftime("%m-%d %H:%M")
        last = datetime.fromtimestamp(mx).strftime("%m-%d %H:%M")
        sid = str(tid)
        print(f"{first:<15}{last:<15}{int(turns):>6}{streams.get(sid, 0):>8}{tools.get(sid, 0):>6}   {sid[:18]}")
    print("\ntip: match these times to your ChatGPT/Codex app history to see what each thread was.")
    print("     tool-calls > 0 means it ran agentically (that's what hits the Codex meter).")
    return 0


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "show"
    n = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    if cmd == "log":
        return cmd_log()
    if cmd == "watch":
        cmd_log()
        print()
        return cmd_show(n or 50)
    if cmd == "show":
        return cmd_show(n or 50)
    if cmd == "breakdown":
        return cmd_breakdown(n or 7)
    if cmd == "session":
        return cmd_session(args[1] if len(args) > 1 else "top")
    if cmd == "threads":
        return cmd_threads(n or 24)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
