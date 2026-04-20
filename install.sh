#!/usr/bin/env bash
# claude-2x-statusline — interactive/non-interactive installer
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.claude/cc-2x-statusline"
SETTINGS="$HOME/.claude/settings.json"
CONFIG="$HOME/.claude/statusline-config.json"
SCHEDULE_URL_DEFAULT="https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json"
SCHEDULE_CACHE_HOURS_DEFAULT="3"
TELEMETRY_URL="https://statusline-telemetry.nadavf.workers.dev/ping"
TELEMETRY_ID_FILE="$HOME/.claude/.statusline-telemetry-id"

# shellcheck source=lib/resolve-runtime.sh
. "$SCRIPT_DIR/lib/resolve-runtime.sh"
# shellcheck source=lib/wire-json.sh
. "$SCRIPT_DIR/lib/wire-json.sh"

TIER_CLI=""
UPDATE_MODE=0
QUIET=0
SKIP_COPY=""
TIER=""
MODE=""
PY=""
NODE=""
PYTHON_39=0
DOCTOR_OK=0
DOCTOR_WARN=0
DOCTOR_FAIL=0
DOCTOR_FAILED_IDS=""
DOCTOR_AVAILABLE=0
SCHEDULE_URL="$SCHEDULE_URL_DEFAULT"
SCHEDULE_CACHE_HOURS="$SCHEDULE_CACHE_HOURS_DEFAULT"

echo ""
echo "  ╭──────────────────────────────────────────╮"
echo "  │     claude-2x-statusline installer       │"
echo "  │     github.com/Nadav-Fux                 │"
echo "  ╰──────────────────────────────────────────╯"
echo ""

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --tier)
                TIER_CLI="${2:-}"
                shift 2
                ;;
            --update)
                UPDATE_MODE=1
                shift
                ;;
            --quiet)
                QUIET=1
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
}

select_tier() {
    case "$1" in
        1|minimal)
            TIER="minimal"
            MODE="minimal"
            ;;
        2|standard)
            TIER="standard"
            MODE="minimal"
            ;;
        3|full|"")
            TIER="full"
            MODE="full"
            ;;
        *)
            return 1
            ;;
    esac
}

load_existing_config() {
    [ -f "$CONFIG" ] || return 1

    local config_tier config_mode config_schedule config_cache
    config_tier=$(json_get "$CONFIG" tier 2>/dev/null || true)
    config_mode=$(json_get "$CONFIG" mode 2>/dev/null || true)
    config_schedule=$(json_get "$CONFIG" schedule_url 2>/dev/null || true)
    config_cache=$(json_get "$CONFIG" schedule_cache_hours 2>/dev/null || true)

    if [ -n "$config_schedule" ]; then
        SCHEDULE_URL="$config_schedule"
    fi
    if [ -n "$config_cache" ]; then
        SCHEDULE_CACHE_HOURS="$config_cache"
    fi

    if [ -n "$config_tier" ]; then
        select_tier "$config_tier" || true
    fi
    if [ -n "$config_mode" ]; then
        MODE="$config_mode"
    fi

    [ -n "$TIER" ]
}

prompt_for_tier() {
    echo "  Choose your tier:"
    echo ""
    echo "    1) Minimal   — peak status + model + git + rate limits"
    echo "       OFF-PEAK ▸ Opus 4.6 ▸ CTX 40% ▸ main saved ▸ 15% 5H"
    echo ""
    echo "    2) Standard  — + cost + full context"
    echo "       OFF-PEAK ▸ Opus 4.6 ▸ 400K/1.0M 40% ▸ main saved ▸ \$0.42 ▸ ▰▰▱▱▱▱▱▱▱▱ 15%"
    echo ""
    echo "    3) Full      — + multiline timeline + rate limit dashboard (recommended)"
    echo "       OFF-PEAK ▸ Opus 4.6 ▸ 400K/1.0M 40% ▸ main saved ▸ \$0.42"
    echo "       │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━ │"
    echo "       │ ▸ 5h ▰▰▱▱▱▱▱▱▱▱  15% · weekly ▰▰▰▱▱▱▱▱▱▱  31% │"
    echo ""

    if [ "$QUIET" = "1" ]; then
        select_tier "full"
        return 0
    fi

    read -rp "  Pick a tier [1/2/3] (default: 3): " tier_choice
    select_tier "$tier_choice" || select_tier "full"
}

configure_tier() {
    if [ -n "$TIER_CLI" ]; then
        if ! select_tier "$TIER_CLI"; then
            echo "  ⚠ Unknown tier '$TIER_CLI' — falling back to full"
            select_tier "full"
        fi
        return 0
    fi

    if [ "$UPDATE_MODE" = "1" ] && load_existing_config; then
        return 0
    fi

    prompt_for_tier
}

detect_migration_update() {
    [ -d "$INSTALL_DIR" ] || return 0

    local missing=""
    [ ! -d "$INSTALL_DIR/narrator" ] && missing="$missing narrator"
    [ ! -d "$INSTALL_DIR/hooks" ] && missing="$missing hooks"
    [ ! -d "$INSTALL_DIR/lib" ] && missing="$missing lib"
    [ ! -d "$INSTALL_DIR/doctor" ] && missing="$missing doctor"
    if [ -n "$missing" ]; then
        UPDATE_MODE=1
        echo "  ℹ Upgrading existing install — adding:$missing"
    fi
}

same_dir_detection() {
    if [ "$SCRIPT_DIR" = "$INSTALL_DIR" ]; then
        SKIP_COPY=1
        echo "  ℹ Installing in-place (source == install dir). Skipping file copy."
    fi
}

python_supports_narrator() {
    [ -n "$PY" ] || return 1
    "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1
}

detect_runtime() {
    PY=$(resolve_runtime python 2>/dev/null || true)
    NODE=$(resolve_runtime node 2>/dev/null || true)
    PYTHON_39=0
    if python_supports_narrator; then
        PYTHON_39=1
    fi

    if [ -n "$PY" ] && [ "$PYTHON_39" = "1" ]; then
        echo "  ✓ Runtime: Python at $PY (full dashboard, narrator ready)"
    elif [ -n "$PY" ]; then
        echo "  ⚠ Runtime: Python at $PY (statusline works, narrator waits for Python 3.9+)"
    elif [ -n "$NODE" ]; then
        echo "  ⚠ Runtime: Node.js only ($NODE) — statusline works, narrator hooks will no-op until Python 3.9+ is installed"
    else
        echo "  ⚠ Runtime: no Python or Node found — bash-only minimal statusline"
        echo "    Install Python 3.9+ or Node.js for full features."
    fi
}

write_install_files() {
    echo "  Installing files..."
    mkdir -p "$INSTALL_DIR/engines" "$INSTALL_DIR/commands" "$INSTALL_DIR/skills" \
             "$INSTALL_DIR/.claude-plugin" "$INSTALL_DIR/lib" "$INSTALL_DIR/doctor" \
             "$INSTALL_DIR/hooks" "$INSTALL_DIR/narrator"

    if [ -z "$SKIP_COPY" ]; then
        cp "$SCRIPT_DIR/statusline.sh" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/statusline.ps1" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/install.sh" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/install.ps1" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/update.sh" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/update.ps1" "$INSTALL_DIR/" 2>/dev/null || true
        cp "$SCRIPT_DIR/package.json" "$INSTALL_DIR/" 2>/dev/null || true
        cp -R "$SCRIPT_DIR/engines/." "$INSTALL_DIR/engines/"
        cp -R "$SCRIPT_DIR/lib/." "$INSTALL_DIR/lib/"
        cp -R "$SCRIPT_DIR/doctor/." "$INSTALL_DIR/doctor/"
        cp "$SCRIPT_DIR/plugin.json" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/.claude-plugin/plugin.json" "$INSTALL_DIR/.claude-plugin/" 2>/dev/null || true
        cp -r "$SCRIPT_DIR/commands/"* "$INSTALL_DIR/commands/" 2>/dev/null || true
        cp -r "$SCRIPT_DIR/skills/"* "$INSTALL_DIR/skills/" 2>/dev/null || true
        cp -r "$SCRIPT_DIR/hooks/"* "$INSTALL_DIR/hooks/" 2>/dev/null || true
        cp -r "$SCRIPT_DIR/narrator/"* "$INSTALL_DIR/narrator/" 2>/dev/null || true
    fi

    chmod +x "$INSTALL_DIR/statusline.sh" "$INSTALL_DIR/install.sh" "$INSTALL_DIR/update.sh" \
             "$INSTALL_DIR/doctor/doctor.sh" "$INSTALL_DIR/doctor/fixes.sh" 2>/dev/null || true
    chmod +x "$INSTALL_DIR/hooks/narrator-session-start.sh" "$INSTALL_DIR/hooks/narrator-prompt-submit.sh" 2>/dev/null || true
    echo "  ✓ Installed to $INSTALL_DIR"
}

write_config() {
    local config_merge config_result
    config_merge=$(printf '{"tier":"%s","mode":"%s","schedule_url":"%s","schedule_cache_hours":%s}' \
        "$TIER" "$MODE" "$SCHEDULE_URL" "$SCHEDULE_CACHE_HOURS")

    config_result=0
    wire_json "$CONFIG" "$config_merge" || config_result=$?

    if [ "$config_result" -eq 0 ]; then
        echo "  ✓ Config saved to $CONFIG"
    else
        echo "  ⚠ Could not update statusline-config.json automatically"
    fi
}

wire_settings() {
    local statusline_cmd settings_merge settings_result settings_existed hook_merge hook_result hook_ss hook_ps
    statusline_cmd="bash $INSTALL_DIR/statusline.sh"
    settings_merge=$(printf '{"statusLine":{"type":"command","command":"%s"}}' "$statusline_cmd")
    settings_result=0
    settings_existed=0
    [ -f "$SETTINGS" ] && settings_existed=1

    wire_json "$SETTINGS" "$settings_merge" || settings_result=$?
    if [ "$settings_result" -eq 0 ]; then
        if [ "$settings_existed" = "1" ]; then
            echo "  ✓ Updated settings.json"
        else
            echo "  ✓ Created settings.json"
        fi
    else
        echo "  ⚠ Could not auto-update settings.json"
    fi

    hook_ss="$INSTALL_DIR/hooks/narrator-session-start.sh"
    hook_ps="$INSTALL_DIR/hooks/narrator-prompt-submit.sh"

    # Migration: clean up narrator entries from older installers that wrote
    # the flat {type, command} form directly into event arrays (invalid —
    # Claude Code expects {hooks:[{type,command}]} wrappers). Without this,
    # re-running install leaves the broken entry alongside the new correct one.
    if [ -n "$PY" ] && [ -f "$SETTINGS" ]; then
        "$PY" - "$SETTINGS" << 'PY' >/dev/null 2>&1 || true
import json, os, sys, tempfile

path = sys.argv[1]
NARRATOR_BASENAMES = ("narrator-session-start.sh", "narrator-prompt-submit.sh")

def is_legacy_narrator_entry(e):
    if not isinstance(e, dict):
        return False
    if "hooks" in e:
        return False
    cmd = e.get("command", "")
    if not isinstance(cmd, str):
        return False
    return any(b in cmd for b in NARRATOR_BASENAMES)

try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    sys.exit(0)

hooks = data.get("hooks")
if not isinstance(hooks, dict):
    sys.exit(0)

changed = False
for event in ("SessionStart", "UserPromptSubmit"):
    arr = hooks.get(event)
    if not isinstance(arr, list):
        continue
    cleaned = [e for e in arr if not is_legacy_narrator_entry(e)]
    if len(cleaned) != len(arr):
        hooks[event] = cleaned
        changed = True

if not changed:
    sys.exit(0)

target_dir = os.path.dirname(path) or "."
fd, temp = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(temp, path)
except Exception:
    try: os.unlink(temp)
    except OSError: pass
    raise
PY
        echo "  ✓ Legacy narrator hook entries cleaned (if any)"
    fi

    hook_merge=$(printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"%s"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"%s"}]}]}}' \
        "$hook_ss" "$hook_ps")

    hook_result=0
    wire_json "$SETTINGS" "$hook_merge" || hook_result=$?
    if [ "$hook_result" -eq 0 ]; then
        echo "  ✓ Narrator hooks wired in settings.json"
    else
        echo "  ⚠ Could not wire narrator hooks automatically"
    fi

    if [ "$PYTHON_39" = "1" ]; then
        echo "  ℹ Narrator: rules-mode ON by default. Set ANTHROPIC_API_KEY + STATUSLINE_NARRATOR_HAIKU=1 for the Haiku layer."
    else
        echo "  ℹ Narrator hooks are installed. They will activate automatically once Python 3.9+ is available."
    fi
}

install_commands() {
    mkdir -p "$HOME/.claude/commands"
    if cp "$SCRIPT_DIR/commands/"*.md "$HOME/.claude/commands/" 2>/dev/null; then
        echo "  ✓ Slash commands installed (/statusline-*, /explain, /narrate, /narrator-lang)"
    else
        echo "  ⚠ Could not install slash commands"
    fi
}

fetch_schedule() {
    echo "  Fetching peak hours schedule..."
    local schedule_cache="$HOME/.claude/statusline-schedule.json"
    if command -v curl >/dev/null 2>&1; then
        curl -s --max-time 5 "$SCHEDULE_URL" -o "$schedule_cache" 2>/dev/null && \
            echo "  ✓ Schedule downloaded (auto-updates every ${SCHEDULE_CACHE_HOURS} hours)" || \
            echo "  ⚠ Could not fetch schedule (will use defaults)"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=5 "$SCHEDULE_URL" -O "$schedule_cache" 2>/dev/null && \
            echo "  ✓ Schedule downloaded (auto-updates every ${SCHEDULE_CACHE_HOURS} hours)" || \
            echo "  ⚠ Could not fetch schedule (will use defaults)"
    else
        echo "  ⚠ No curl/wget — schedule will be fetched on first run"
    fi
}

install_editor_extension() {
    local editors_found=""
    local editor_cmd name

    for editor_cmd in code cursor windsurf agy; do
        if command -v "$editor_cmd" >/dev/null 2>&1; then
            editors_found="$editors_found $editor_cmd"
        fi
    done

    if [ -n "$editors_found" ] && command -v npm >/dev/null 2>&1; then
        echo ""
        echo "  Detected editors:$editors_found"
        echo "  Building statusline extension..."
        local vscode_dir="$INSTALL_DIR/vscode"
        local vsix_built=false
        local vsce_bin=""
        mkdir -p "$vscode_dir"
        cp "$SCRIPT_DIR/vscode/extension.ts" "$vscode_dir/"
        cp "$SCRIPT_DIR/vscode/package.json" "$vscode_dir/"
        cp "$SCRIPT_DIR/vscode/package-lock.json" "$vscode_dir/" 2>/dev/null || true
        cp "$SCRIPT_DIR/vscode/tsconfig.json" "$vscode_dir/"
        cp "$SCRIPT_DIR/vscode/icon.png" "$vscode_dir/"
        cp "$SCRIPT_DIR/vscode/LICENSE" "$vscode_dir/"

        vsce_bin="$vscode_dir/node_modules/.bin/vsce"
        rm -f "$vscode_dir/claude-statusline.vsix"
        (cd "$vscode_dir" && npm install --silent 2>/dev/null && npm run compile --silent 2>/dev/null && \
            [ -x "$vsce_bin" ] && "$vsce_bin" package --allow-missing-repository --out claude-statusline.vsix >/dev/null 2>&1 && \
            [ -f claude-statusline.vsix ]) && vsix_built=true

        if [ "$vsix_built" = true ]; then
            for editor_cmd in $editors_found; do
                case "$editor_cmd" in
                    code) name="VS Code" ;;
                    cursor) name="Cursor" ;;
                    windsurf) name="Windsurf" ;;
                    agy) name="Antigravity" ;;
                    *) name="$editor_cmd" ;;
                esac
                if "$editor_cmd" --install-extension "$vscode_dir/claude-statusline.vsix" --force 2>/dev/null; then
                    echo "  ✓ Installed in $name!"
                else
                    echo "  ⚠ Could not install in $name (install manually via VSIX)."
                fi
            done
        else
            echo "  ⚠ Extension build failed (optional). Install manually from vscode/ folder."
        fi
    else
        echo ""
        echo "  No supported editors detected (VS Code, Cursor, Windsurf, Antigravity)."
        echo "  To install later: build from the vscode/ folder."
    fi
}

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

telemetry_id() {
    local id

    mkdir -p "$HOME/.claude" >/dev/null 2>&1 || true
    if [ -f "$TELEMETRY_ID_FILE" ]; then
        id=$(tr -d '\r\n' < "$TELEMETRY_ID_FILE" | tr '[:upper:]' '[:lower:]')
        if printf '%s' "$id" | grep -Eq '^[0-9a-f]{16}$'; then
            printf '%s' "$id"
            return 0
        fi
    fi

    if [ -n "$PY" ]; then
        id=$("$PY" - <<'PY'
import secrets

print(secrets.token_hex(8))
PY
)
    elif [ -n "$NODE" ]; then
        id=$("$NODE" -e "const crypto=require('crypto'); process.stdout.write(crypto.randomBytes(8).toString('hex'));" 2>/dev/null || true)
    elif command -v openssl >/dev/null 2>&1; then
        id=$(openssl rand -hex 8 2>/dev/null | tr -d '\r\n')
    elif [ -r /dev/urandom ]; then
        id=$(od -An -N8 -tx1 /dev/urandom 2>/dev/null | tr -d ' \r\n')
    else
        id=""
    fi

    if printf '%s' "$id" | grep -Eq '^[0-9a-f]{16}$'; then
        umask 177
        printf '%s' "$id" > "$TELEMETRY_ID_FILE"
        chmod 600 "$TELEMETRY_ID_FILE" 2>/dev/null || true
        printf '%s' "$id"
        return 0
    fi

    return 1
}

post_telemetry() {
    local payload="$1"
    if [ "${STATUSLINE_DISABLE_TELEMETRY:-0}" = "1" ]; then
        return 0
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -sS --max-time 3 -X POST -H "Content-Type: application/json" -d "$payload" "$TELEMETRY_URL" >/dev/null 2>&1 &
        return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -q --timeout=3 --header="Content-Type: application/json" --post-data="$payload" "$TELEMETRY_URL" -O /dev/null 2>/dev/null &
        return 0
    fi
    if [ -n "$PY" ]; then
        "$PY" -c "import urllib.request; payload = b'''$payload'''; req = urllib.request.Request('$TELEMETRY_URL', data=payload, method='POST', headers={'Content-Type': 'application/json'});\
try: urllib.request.urlopen(req, timeout=3).read()\
except Exception: pass" >/dev/null 2>&1 &
        return 0
    fi
    if [ -n "$NODE" ]; then
        "$NODE" -e "const https=require('https'); const data=process.argv[1]; const req=https.request('$TELEMETRY_URL',{method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}},res=>res.resume()); req.on('error',()=>{}); req.end(data);" "$payload" >/dev/null 2>&1 &
        return 0
    fi
    return 1
}

run_doctor() {
    local doctor_script="$INSTALL_DIR/doctor/doctor.sh"
    local doctor_json="$HOME/.claude/.statusline-install-doctor.json"

    echo ""
    echo "  Running post-install diagnostics..."

    if [ ! -f "$doctor_script" ]; then
        DOCTOR_WARN=1
        DOCTOR_FAIL=0
        DOCTOR_FAILED_IDS="doctor_unavailable"
        echo "  ⚠ Doctor script missing — install marked as degraded"
        return 0
    fi

    if bash "$doctor_script" --json > "$doctor_json" 2>/dev/null; then
        DOCTOR_AVAILABLE=1
        DOCTOR_OK=$(json_get "$doctor_json" ok 2>/dev/null || echo 0)
        DOCTOR_WARN=$(json_get "$doctor_json" warn 2>/dev/null || echo 0)
        DOCTOR_FAIL=$(json_get "$doctor_json" fail 2>/dev/null || echo 0)
        DOCTOR_FAILED_IDS=$(json_fail_ids "$doctor_json" 2>/dev/null || true)
    else
        DOCTOR_WARN=1
        DOCTOR_FAIL=0
        DOCTOR_FAILED_IDS="doctor_unavailable"
        echo "  ⚠ Doctor could not run — install marked as degraded"
    fi

    rm -f "$doctor_json"

    if [ "${DOCTOR_FAIL:-0}" -gt 0 ] || [ "${DOCTOR_WARN:-0}" -gt 0 ]; then
        echo "  ⚠ ${DOCTOR_FAIL:-0} fail, ${DOCTOR_WARN:-0} warn — run: bash $INSTALL_DIR/doctor/doctor.sh --fix"
    else
        echo "  ✓ All checks passed"
    fi
}

send_install_telemetry() {
    local uid os_name payload failed_ids escaped_failed_ids event_name has_python has_node
    uid=$(telemetry_id 2>/dev/null || true)
    [ -n "$uid" ] || return 0

    os_name="$(uname -s 2>/dev/null | tr A-Z a-z)"
    has_python=false
    has_node=false
    [ -n "$PY" ] && has_python=true
    [ -n "$NODE" ] && has_node=true
    escaped_failed_ids=$(json_escape "$DOCTOR_FAILED_IDS")

    if [ "$UPDATE_MODE" = "1" ]; then
        event_name="update"
    else
        payload=$(printf '{"id":"%s","v":"2.2","engine":"installer","tier":"%s","os":"%s","event":"install"}' \
            "$uid" "$TIER" "$os_name")
        post_telemetry "$payload" || true
        event_name="install_result"
    fi

    payload=$(printf '{"id":"%s","v":"2.2","engine":"installer","tier":"%s","os":"%s","event":"%s","ok":%s,"warn":%s,"fail":%s,"failed_ids":"%s","has_python":%s,"has_node":%s,"ps1_only":false}' \
        "$uid" "$TIER" "$os_name" "$event_name" "${DOCTOR_OK:-0}" "${DOCTOR_WARN:-0}" "${DOCTOR_FAIL:-0}" "$escaped_failed_ids" "$has_python" "$has_node")
    post_telemetry "$payload" || true
}

print_done() {
    echo ""
    echo "  ╭──────────────────────────────────────────╮"
    echo "  │  ✓ Installed! Restart Claude Code.       │"
    echo "  │                                          │"
    echo "  │  First-run quickstart:                   │"
    echo "  │    /statusline-onboarding                │"
    echo "  │                                          │"
    echo "  │  To update later:                        │"
    echo "  │    bash ~/.claude/cc-2x-statusline/update.sh │"
    echo "  │                                          │"
    echo "  │  To change tier:                         │"
    echo "  │    /statusline-minimal                   │"
    echo "  │    /statusline-standard                  │"
    echo "  │    /statusline-full                      │"
    echo "  ╰──────────────────────────────────────────╯"
    echo ""
}

parse_args "$@"
detect_migration_update
same_dir_detection
configure_tier

echo "  ✓ Selected: $TIER"
echo ""

write_install_files
detect_runtime
write_config
wire_settings
install_commands
fetch_schedule
install_editor_extension
run_doctor
send_install_telemetry
print_done