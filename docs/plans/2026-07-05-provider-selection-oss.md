# Master Plan — Provider Selection, Onboarding & Open-Source Release

> Date: 2026-07-05. Written for an implementing agent (Opus/Sonnet). Companion doc:
> `2026-07-03-provider-onboarding-glm-draft.md` (GLM-5.2's config/onboarding design — adopted
> below with amendments). Everything here was verified against the repo AND the live install
> at `~/.claude/cc-2x-statusline/` on 2026-07-05.

## Product goal (maintainer's words, paraphrased)

Open-source statusline where a user **chooses which AI CLIs to monitor**:
- **Primary trio (the headline UX): Claude, Codex, Antigravity (AGY).** A user picks any 1–3.
- **Optional extras: Copilot, GLM, Droid** — off by default, addable by choice.
- **Smart onboarding** that handles per-provider authentication.
- **VS Code parity**: the cockpit (not just Claude) visible in VS Code like the terminal.

---

## 0. Ground truth (read before coding)

### 0.1 Repo ⇄ live-install drift — MUST reconcile first

The live install at `~/.claude/cc-2x-statusline/` is **ahead of the repo** on Copilot and
**behind** on comments/schedule. Verified diff on 2026-07-05:

| File | Direction | What |
|---|---|---|
| `lib/usage_providers.py` | **live ahead (+41 lines)** | Full `get_copilot_usage()` (cache reader + background refresh spawn), `copilot` in `PROVIDERS`, in both iteration loops |
| `engines/python-engine.py` | live ahead (1 line) | `copilot` added to the opt-in tuple in `_effective_external_usage_config` (live line 1699) |
| `~/.claude/copilot-credits-refresh.sh` | **live only, not in repo at all** | Queries `gh api /organizations/<ORG>/settings/billing/usage`, sums `sku == "Copilot AI Credits"`, writes `~/.claude/statusline-usage-copilot.json` |
| `narrator/scoring.py`, `narrator/memory.py`, `engines/python-engine.py` comments | repo ahead | Docstring/comment text only — functional code matches |
| `schedule.json` | repo ahead (v6 vs v5) | Live bundled copy stale but harmless — runtime uses the remote-fetched `~/.claude/statusline-schedule.json` cache (verified v6) |

**Phase 0 must port the Copilot code INTO the repo** (generalized — see Phase 3) and then
re-deploy so live == repo. Never sync repo→live blindly: that would delete Copilot.

### 0.2 What each provider reader does today (repo `lib/usage_providers.py`)

| Provider | Source | Auth | Failure mode |
|---|---|---|---|
| Claude | engine-internal: `GET api.anthropic.com/api/oauth/usage` (engine `:1224`) | OAuth: env → `~/.claude/.credentials.json` → macOS keychain (dup-item-safe) | stale cache + `·stale` marker |
| Codex | newest `~/.codex/sessions/**/rollout-*.jsonl`, last `token_count` event (`:530-565`) | none (CLI-owned) | silent `unavailable` |
| Antigravity | subprocess `antigravity-usage quota --json --method auto`, 5s timeout (`:1118-1141`) | CLI-owned OAuth | caches misses too (good) |
| GLM | `GET {base_url}/api/monitor/usage/quota/limit`, raw key header, 1.5s timeout (`:664-678`) | `ZAI_API_KEY`/`ZHIPU_API_KEY` env → `config.api_key` → `~/.codex/providers.env` (`:640-648`) | **silent swallow — row just vanishes** |
| Droid | `~/.factory/` sessions/telemetry files (`:770-820`) | none | silent `unavailable` |
| Copilot | **repo: absent.** live: cache file written by personal script | `gh` CLI auth | silent |

Display gating today: tier-based (`multi-cli` forces codex+glm on; droid/antigravity/copilot
opt-in) via `_effective_external_usage_config` (engine `:1679-1712`). **No user-facing
selection exists** — that's the core feature gap.

### 0.3 Verified live facts that contradict assumptions

- **GLM fetch WORKS** (probed 2026-07-05: `ZAI_API_KEY` + raw `Authorization` header against
  `api.z.ai/api/monitor/usage/quota/limit` returns plan `lite`, quota data). The "GLM is
  broken" perception is NOT a 401: suspects are (a) env var not present in the statusline's
  process env (hooks don't source the user's shell rc), (b) quota product mismatch — the
  coding-plan quota may not reflect droid/z.ai-coding usage, (c) silent-swallow hides
  whichever it is. Phase 4 adds diagnostics before changing the fetch.
- **The real GitHub Copilot CLI is not installed** on the dev machine — `copilot` on PATH is
  VS Code's launcher stub. The live Copilot row comes entirely from the `gh` billing API
  script, not from a Copilot CLI.

---

## Phase 0 — Reconciliation & repo hygiene (prerequisite, ~½ day)

1. **Port Copilot from live → repo**: copy the live `usage_providers.py` copilot block +
   engine tuple change into the repo (generalization happens in Phase 3; port as-is first,
   gated `enabled: false` by default).
2. Add `scripts/copilot-credits-refresh.sh` to the repo as a **template** — parameterize
   `ORG`, `CAP`, `POOL` via config/env; the live copy hardcodes the maintainer's org and a
   personal 3000-credit self-cap. Do not ship those defaults.
3. Sync live install from repo after merge (`install.sh --update` path).
4. Hygiene (all trivial, do in one commit):
   - `.gitignore`: add `__pycache__/`, `.pytest_cache/`, `.DS_Store` — all three are
     currently COMMITTED in the repo; `git rm -r --cached` them.
   - Delete dead Antigravity sqlite reader (`_antigravity_db_path`,
     `parse_antigravity_item_table`, unused `import sqlite3`) or mark it as the documented
     fallback; fix the stale `"sqlite"` source label in `PROVIDERS` (`:21` vs actual `"api"` `:1147`).
   - Fix docstring path leak `lib/workflows.py:22-23` (Windows user path).
   - Update stale `UNINSTALL-GAPS.md` (installer now copies ALL `commands/*.md`).
   - README: rewrite the obsolete "Peak Hours" section (peak removed 2026-05-06; schedule v6).

## Phase 1 — Selection model (`providers.selected`) (~1-2 days)

Adopt GLM draft §A/§A.3/§D verbatim, with these amendments:

- **Ordering/grouping**: onboarding presents **Claude, Codex, Antigravity first** (the trio),
  then "More providers…" reveals Copilot, GLM, Droid. `providers.selected` stays a flat
  ordered array = render order.
- **Default for fresh installs**: `["claude"]`. Default for migration: `["claude"]` + any
  provider currently `enabled: true` in `external_providers` (preserves existing cockpits).
- **Kill the implicit force-on**: once `providers.selected` exists, `multi-cli` tier no longer
  forces codex+glm (`_effective_external_usage_config` becomes a legacy fallback only).
- Tier stays = density; auto-set `multi-cli` when `len(selected) >= 2`, `full` otherwise
  (user-overridable).
- Mirror into `external_providers` on every write so node/bash engines keep working (GLM
  draft §A.3 step 3); teach node engine to read `providers.selected` in Phase 5 of the draft.
- Store volatile auth state (`status`, `checked_at`) in a separate
  `~/.claude/statusline-provider-state.json`, NOT in the config file (GLM draft open question
  7 — decided: separate file).

## Phase 2 — Onboarding wizard + auth (~3-4 days)

Adopt GLM draft §B (two entry points sharing `lib/onboarding.py`) and §C (auth matrix) with:

- Screen 1 wording reflects the trio-first grouping above.
- Secrets: keychain on macOS/Windows, `0600` file fallback on Linux (`lib/secrets.py`);
  migrate any plaintext `glm.api_key` out of config on first run.
- Validation-before-save per provider; failure → retry/skip, never abort the wizard.
- Re-runnable: `/statusline-onboarding` becomes THE add/remove/re-auth command.
- **Degraded rows** (GLM draft §D.3): a selected-but-broken provider renders
  `│ ▸ Codex  auth expired — /statusline-onboarding │` instead of vanishing. This is the #1
  supportability fix — today every provider failure is invisible.
- `doctor.sh`: new `check_providers_auth` (cached probe, 1h TTL).

## Phase 3 — Copilot done properly (~2-3 days, after Phase 1)

The live implementation is a personal hack (maintainer's org + self-cap). Generalize:

1. **Auth**: require `gh` CLI (`gh auth status`); no PAT storage in v1.
2. **Two data modes**, chosen at onboarding:
   - *Individual* (most users): `gh api /users/{login}/settings/billing/usage` → premium
     request SKUs (quantity vs included quota).
   - *Org pool*: `gh api /organizations/{org}/settings/billing/usage` + configurable
     `cap`/`pool` (what the live script does today; org name asked at onboarding, requires
     org billing scope — detect 403 and explain).
3. **In-process fetch** with the standard cache-TTL pattern (kill the external
   `copilot-credits-refresh.sh` spawn; it's an artifact of prototyping). Respect the render
   budget: fetch in background thread/stale-while-revalidate like the Claude path.
4. Row format: keep the live one — `▸ Copilot business  2152 left ▰▰▱ 28% ⟳ 1/8 3:00am`.
5. Verify billing API SKU names against current GitHub docs at build time — the enhanced
   billing platform is new-ish and SKU strings ("Copilot AI Credits" vs "Copilot Premium
   Requests") have changed once already.

## Phase 4 — GLM hardening (~1 day)

1. **Diagnose before changing**: add `doctor.sh` GLM probe printing HTTP status + which key
   source resolved (never the key itself). This distinguishes env-missing vs 401 vs
   product-mismatch — currently indistinguishable.
2. Key sources: add `~/.claude/statusline-secrets`/keychain (Phase 2) ahead of the fragile
   `~/.codex/providers.env` coupling; document the env-var path (hooks don't source shell rc
   — recommend keychain).
3. Try `Bearer <key>` on 401 retry (one-shot, cached result) — cheap compat with both header
   styles.
4. Move the 1.5s blocking fetch off the render path (background refresh + stale cache, same
   pattern as Copilot Phase 3.3).

## Phase 5 — VS Code cockpit (~2-3 days)

Current extension (`vscode/extension.ts`) is Claude-only and recomputes usage itself. The
multi-CLI data it needs **already lands on disk** — `~/.claude/statusline-usage-<provider>.json`
caches, written by the terminal engine (a network-free reader exists:
`read_cached_external_usage`, `usage_providers.py:437-472`).

1. New status bar item (or one consolidated "cockpit" item with rich tooltip) per selected
   provider, reading those cache files; gate on `providers.selected` from
   `statusline-config.json`. Antigravity renders its 3-model split in the tooltip.
2. Stop re-fetching Claude usage in the extension — read the engine's context payload
   (`$TMPDIR/claude/statusline-context.json` already carries `five_hour_pct`/`seven_day_pct`)
   with the API fetch as fallback only when the payload is stale (>10 min).
3. Fix the timezone bug: `getSourceOffset` (`extension.ts:686-697`) only knows US zones,
   silently falls back to Pacific for e.g. `Asia/Jerusalem` — use `Intl.DateTimeFormat`
   with `timeZone` instead of the hardcoded offset table.
4. Packaging: currently built+sideloaded by `install.sh`. Keep that, plus publish a `.vsix`
   as a GitHub release asset. Marketplace publishing optional later (publisher account
   `nvision-digital` exists in package.json).
5. Caveat: cache freshness in VS Code depends on the terminal engine rendering somewhere.
   Add a tiny staleness marker (reuse the `·stale` concept) instead of showing frozen numbers.

## Phase 6 — Open-source release checklist (~1 day)

- **Telemetry**: endpoint is the maintainer's Cloudflare worker
  (`statusline-telemetry.nadavf.workers.dev`), ON by default in installer + engine + vscode.
  For OSS: make it **opt-in at install** (one yes/no in the wizard), prominent README
  disclosure, keep `STATUSLINE_DISABLE_TELEMETRY=1`.
- `worker/wrangler.toml` ships the maintainer's real `account_id` + KV namespace id — replace
  with placeholders + README note for self-hosters.
- Author-pinned URLs (`Nadav-Fux/claude-2x-statusline` in `install.sh:9`, `update.sh:5-6`,
  `config.example.json:21`, engine `:102-103`, `skills/setup`) → single `REPO_SLUG` variable /
  config key so forks work.
- Prune personal artifacts from the public tree: `.factory/`, `CODEX-SPEC-*.md`,
  `docs/superpowers/`, `droid-wiki/he/` (decide: keep bilingual wiki or move to GitHub wiki).
- Verify `LICENSE`/`COPYRIGHT.md` consistency; add CONTRIBUTING with the engine-parity rule
  (python is source of truth; node/bash follow; narrator is python-only).

## Already fixed while planning (2026-07-05, commit `c05d860`)

- **Duplicate narrator hooks**: installer quoting change (`ec0b9bc`) + verbatim-string array
  dedup in `wire_json` caused every post-update install to append a second (quoted) hook
  entry per event → double narrator notes per prompt, racing past the per-note cooldown.
  Fixed: quote-insensitive dedup markers in all 4 backends (python/node/jq/ps1) + a healing
  migration in `install.sh` that collapses existing quote-variant duplicates. The dev
  machine's `settings.json` was healed manually.

## Suggested build order & effort

Phase 0 → 1 → 2 → 3 → 5 → 4 → 6. Roughly 10-14 agent-days total. Phases 3/4/5 are
independent after Phase 1 and can run in parallel worktrees. Each phase must end with:
`python3.12 -m pytest tests/` green (one pre-existing known failure:
`test_providers_gracefully_unavailable_without_home_data`), plus a live render smoke test
(`bash statusline.sh < tests/fixtures/stdin_minimal.json`).
