#!/usr/bin/env bash
# Shared JSON merge/query helpers for installers.

if ! command -v resolve_runtime >/dev/null 2>&1; then
    _wire_json_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck source=lib/resolve-runtime.sh
    . "$_wire_json_dir/resolve-runtime.sh"
else
    _wire_json_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

_WIRE_JSON_BACKEND=""
_WIRE_JSON_RUNTIME=""

_wire_json_select_backend() {
    if [ -n "$_WIRE_JSON_BACKEND" ]; then
        return 0
    fi

    local runtime
    runtime=$(resolve_runtime python 2>/dev/null || true)
    if [ -n "$runtime" ]; then
        _WIRE_JSON_BACKEND="python"
        _WIRE_JSON_RUNTIME="$runtime"
        return 0
    fi

    runtime=$(resolve_runtime node 2>/dev/null || true)
    if [ -n "$runtime" ]; then
        _WIRE_JSON_BACKEND="node"
        _WIRE_JSON_RUNTIME="$runtime"
        return 0
    fi

    if command -v jq >/dev/null 2>&1; then
        _WIRE_JSON_BACKEND="jq"
        _WIRE_JSON_RUNTIME="$(command -v jq)"
        return 0
    fi

    if command -v pwsh >/dev/null 2>&1; then
        _WIRE_JSON_BACKEND="pwsh"
        _WIRE_JSON_RUNTIME="$(command -v pwsh)"
        return 0
    fi

    if command -v powershell >/dev/null 2>&1; then
        _WIRE_JSON_BACKEND="powershell"
        _WIRE_JSON_RUNTIME="$(command -v powershell)"
        return 0
    fi

    _WIRE_JSON_BACKEND="none"
    _WIRE_JSON_RUNTIME=""
}

wire_json_backend() {
    _wire_json_select_backend
    printf '%s\n' "$_WIRE_JSON_BACKEND"
}

wire_json_runtime() {
    _wire_json_select_backend
    printf '%s\n' "$_WIRE_JSON_RUNTIME"
}

_wire_json_manual_patch_hint() {
    local target="$1"
    local merge_json="$2"
    printf 'Could not merge %s automatically: no JSON backend found.\n' "$target" >&2
    printf 'Install Python 3.9+, Node.js, jq, or PowerShell 5.1+, then re-run the installer.\n' >&2
    printf 'Manual JSON patch to apply:\n%s\n' "$merge_json" >&2
}

wire_json() {
    local target="$1"
    local merge_json="$2"

    _wire_json_select_backend
    mkdir -p "$(dirname "$target")"

    case "$_WIRE_JSON_BACKEND" in
        python)
            "$_WIRE_JSON_RUNTIME" - "$target" "$merge_json" <<'PY'
import json
import os
import sys
import tempfile


def merge(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            if key in merged:
                merged[key] = merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if isinstance(base, list) and isinstance(patch, list):
        merged = list(base)
        seen = {_marker(item) for item in base}
        for item in patch:
            marker = _marker(item)
            if marker not in seen:
                merged.append(item)
                seen.add(marker)
        return merged
    return patch


def _norm_cmd(cmd):
    # "bash '/x/y.sh'", "'/x/y.sh'" and "/x/y.sh" are the same hook; installer
    # quoting changed across versions, so compare commands quote-insensitively
    # or every update appends a duplicate hook entry.
    c = cmd.strip()
    if c.startswith("bash "):
        c = c[5:].strip()
    if len(c) >= 2 and c[0] == c[-1] and c[0] in ("'", '"'):
        c = c[1:-1]
    return c


def _norm(value):
    if isinstance(value, dict):
        return {
            k: (_norm_cmd(v) if k == "command" and isinstance(v, str) else _norm(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def _marker(item):
    return json.dumps(_norm(item), sort_keys=True, ensure_ascii=False)


target_path = sys.argv[1]
patch = json.loads(sys.argv[2])
base = {}
if os.path.exists(target_path):
    with open(target_path, encoding='utf-8') as handle:
        base = json.load(handle)

result = merge(base, patch)
target_dir = os.path.dirname(target_path) or '.'
fd, temp_path = tempfile.mkstemp(dir=target_dir, suffix='.tmp')
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    os.replace(temp_path, target_path)
except Exception:
    try:
        os.unlink(temp_path)
    except OSError:
        pass
    raise
PY
            ;;
        node)
            "$_WIRE_JSON_RUNTIME" - "$target" "$merge_json" <<'NODE'
const fs = require('fs');
const path = require('path');

function merge(base, patch) {
  if (Array.isArray(base) && Array.isArray(patch)) {
    const merged = [...base];
    const seen = new Set(base.map(item => marker(item)));
    for (const item of patch) {
      const m = marker(item);
      if (!seen.has(m)) {
        merged.push(item);
        seen.add(m);
      }
    }
    return merged;
  }

  if (isObject(base) && isObject(patch)) {
    const merged = { ...base };
    for (const [key, value] of Object.entries(patch)) {
      merged[key] = key in merged ? merge(merged[key], value) : value;
    }
    return merged;
  }

  return patch;
}

function isObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

// "bash '/x/y.sh'", "'/x/y.sh'" and "/x/y.sh" are the same hook; installer
// quoting changed across versions, so compare commands quote-insensitively
// or every update appends a duplicate hook entry.
function normCmd(cmd) {
  let c = cmd.trim();
  if (c.startsWith('bash ')) c = c.slice(5).trim();
  if (c.length >= 2 && c[0] === c[c.length - 1] && (c[0] === "'" || c[0] === '"')) {
    c = c.slice(1, -1);
  }
  return c;
}

function norm(value) {
  if (Array.isArray(value)) return value.map(norm);
  if (isObject(value)) {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = k === 'command' && typeof v === 'string' ? normCmd(v) : norm(v);
    }
    return out;
  }
  return value;
}

function marker(item) {
  return JSON.stringify(norm(item));
}

const targetPath = process.argv[2];
const patch = JSON.parse(process.argv[3]);
let base = {};
if (fs.existsSync(targetPath)) {
  base = JSON.parse(fs.readFileSync(targetPath, 'utf8'));
}

const result = merge(base, patch);
const dir = path.dirname(targetPath);
fs.mkdirSync(dir, { recursive: true });
const tempPath = path.join(dir, `.wire-json-${process.pid}-${Date.now()}.tmp`);
fs.writeFileSync(tempPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
fs.renameSync(tempPath, targetPath);
NODE
            ;;
        jq)
            local base_json
            base_json='{}'
            if [ -f "$target" ]; then
                base_json=$(cat "$target") || return 20
            fi
            printf '%s' "$base_json" | "$_WIRE_JSON_RUNTIME" --argjson patch "$merge_json" '
def normcmd:
  gsub("^\\s+|\\s+$"; "")
  | (if startswith("bash ") then .[5:] | gsub("^\\s+|\\s+$"; "") else . end)
  | (if (length >= 2) and ((startswith("'\''") and endswith("'\''")) or (startswith("\"") and endswith("\"")))
     then .[1:length-1] else . end);
def norm:
  if type == "object" then
    with_entries(
      if .key == "command" and (.value | type) == "string"
      then .value |= normcmd
      else .value |= norm end
    )
  elif type == "array" then map(norm)
  else . end;
def rmerge($base; $patch):
  if (($base | type) == "object") and (($patch | type) == "object") then
    reduce ($patch | keys_unsorted[]) as $key ($base;
      .[$key] = if has($key) then rmerge(.[$key]; $patch[$key]) else $patch[$key] end
    )
  elif (($base | type) == "array") and (($patch | type) == "array") then
    reduce $patch[] as $item ($base;
      if any(.[]; (. | norm) == ($item | norm)) then . else . + [$item] end
    )
  else
    $patch
  end;
rmerge(. // {}; $patch)
' > "$target.tmp" || {
                rm -f "$target.tmp"
                return 20
            }
            mv "$target.tmp" "$target" || {
                rm -f "$target.tmp"
                return 30
            }
            ;;
        pwsh|powershell)
            "$_WIRE_JSON_RUNTIME" -NoProfile -ExecutionPolicy Bypass -File "$_wire_json_dir/Wire-Json.ps1" -Path "$target" -MergeJson "$merge_json"
            ;;
        none)
            if [ -f "$target" ]; then
                _wire_json_manual_patch_hint "$target" "$merge_json"
                return 10
            fi
            printf '%s\n' "$merge_json" > "$target" || return 30
            ;;
    esac
}

json_get() {
    local target="$1"
    local query_path="$2"

    if [ ! -f "$target" ]; then
        return 1
    fi

    _wire_json_select_backend

    case "$_WIRE_JSON_BACKEND" in
        python)
            "$_WIRE_JSON_RUNTIME" - "$target" "$query_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    data = json.load(handle)

value = data
for part in [segment for segment in sys.argv[2].split('.') if segment]:
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        raise SystemExit(1)

if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is True:
    print('true')
elif value is False:
    print('false')
elif value is None:
    raise SystemExit(1)
else:
    print(value)
PY
            ;;
        node)
            "$_WIRE_JSON_RUNTIME" - "$target" "$query_path" <<'NODE'
const fs = require('fs');

const targetPath = process.argv[2];
const queryPath = process.argv[3];
const data = JSON.parse(fs.readFileSync(targetPath, 'utf8'));
let value = data;
for (const part of queryPath.split('.').filter(Boolean)) {
  if (value && typeof value === 'object' && part in value) {
    value = value[part];
  } else {
    process.exit(1);
  }
}

if (value === undefined || value === null) {
  process.exit(1);
}

if (typeof value === 'object') {
  process.stdout.write(JSON.stringify(value));
} else {
  process.stdout.write(String(value));
}
NODE
            ;;
        jq)
            "$_WIRE_JSON_RUNTIME" -r --arg path "$query_path" '
reduce ($path | split("."))[] as $part (.;
  if . == null then null else .[$part] end
) | if . == null then empty elif (type == "object" or type == "array") then @json else tostring end
' "$target"
            ;;
        pwsh|powershell)
            "$_WIRE_JSON_RUNTIME" -NoProfile -ExecutionPolicy Bypass -File "$_wire_json_dir/Wire-Json.ps1" -Path "$target" -GetPath "$query_path"
            ;;
        none)
            return 10
            ;;
    esac
}

json_fail_ids() {
    local target="$1"

    if [ ! -f "$target" ]; then
        return 1
    fi

    _wire_json_select_backend

    case "$_WIRE_JSON_BACKEND" in
        python)
            "$_WIRE_JSON_RUNTIME" - "$target" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    data = json.load(handle)

failed = []
for check in data.get('checks', []):
    if isinstance(check, dict) and check.get('status') == 'fail' and check.get('id'):
        failed.append(str(check['id']))

print(' '.join(failed))
PY
            ;;
        node)
            "$_WIRE_JSON_RUNTIME" - "$target" <<'NODE'
const fs = require('fs');

const targetPath = process.argv[2];
const data = JSON.parse(fs.readFileSync(targetPath, 'utf8'));
const failed = [];
for (const check of data.checks || []) {
  if (check && check.status === 'fail' && check.id) {
    failed.push(String(check.id));
  }
}
process.stdout.write(failed.join(' '));
NODE
            ;;
        jq)
            "$_WIRE_JSON_RUNTIME" -r '[.checks[]? | select(.status == "fail" and .id) | .id] | join(" ")' "$target"
            ;;
        pwsh|powershell)
            "$_WIRE_JSON_RUNTIME" -NoProfile -ExecutionPolicy Bypass -Command "
              $data = Get-Content -Raw -Encoding UTF8 '$target' | ConvertFrom-Json;
              $ids = @();
              foreach ($check in $data.checks) {
                if ($check.status -eq 'fail' -and $check.id) { $ids += [string]$check.id }
              }
              Write-Output ($ids -join ' ')
            "
            ;;
        none)
            return 10
            ;;
    esac
}