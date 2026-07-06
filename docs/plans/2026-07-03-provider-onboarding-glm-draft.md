# Provider Onboarding & Selection — Design Plan

> Drafted by GLM-5.2 (via droid) on 2026-07-03. Planning deliverable — not yet implemented.

I now have a complete picture of the codebase. Here is the design plan.

---

# DESIGN PLAN — Provider Onboarding & Selection for `claude-2x-statusline`

## 0. Grounding facts from the current code (so the plan is concrete)

These are the *real* current states I verified by reading the repo:

- **Providers implemented** in `lib/usage_providers.py` (`PROVIDERS` dict): `codex`, `glm`, `droid`, `antigravity`. **`copilot` is NOT implemented anywhere** (grep for `copilot|GITHUB_TOKEN|gh auth` returns nothing). I treat Copilot as *planned/forward-looking* throughout this plan and flag it in §F.
- **Auth today, per provider**:
  - **Claude** — OAuth. `seg_auth_mode` / `_get_oauth_token` read `CLAUDE_CODE_OAUTH_TOKEN` → `~/.claude/.credentials.json` → macOS keychain service `Claude Code-credentials` (with a duplicate-item fallback in `_keychain_claude_token`). Already auto-detected; **no onboarding auth needed**.
  - **Codex** — *no key*. `get_codex_usage` reads `~/.codex/sessions/*/*/rollout-*.jsonl`. Auth = "the Codex CLI is logged in and has produced a rollout".
  - **GLM** — `_glm_key` checks `ZAI_API_KEY`/`ZHIPU_API_KEY` env → `external_providers.glm.api_key` (config) → `~/.codex/providers.env`. **Plaintext in config today — a security smell to fix.**
  - **Droid** — *no key*. `get_droid_usage` reads `~/.factory/sessions/*/*.settings.json`. Auth = "Factory Droid is installed and has telemetry".
  - **Antigravity** — shelled out to `antigravity-usage quota --json --method auto`, which owns its own OAuth refresh. Auth = "the `antigravity-usage` binary exists and is logged in".
- **Tier system**: 4 tiers in `TIER_PRESETS` (`engines/python-engine.py`): `minimal`, `standard`, `full`, `multi-cli`. The render loop in `main()` computes `is_multi_cli = tier == "multi-cli"` and `is_full_tier = is_multi_cli or tier == "full" or mode == "full"`. External rows only draw when `ctx["is_multi_cli"] OR (is_full AND external_providers.enabled)`.
- **`_effective_external_usage_config`** already overrides `external_providers` per-tier: in multi-cli it forces `codex`+`glm` on and keeps `droid`+`antigravity` opt-in. This is the *one place* selection currently lives, and it is implicit.
- **Config shape today** (`~/.claude/statusline-config.json`, defaults in `DEFAULT_CONFIG`): a top-level `tier`, plus a top-level `external_providers` block with `{enabled, codex:{enabled}, glm:{enabled,base_url,api_key}, droid:{enabled}, antigravity:{enabled}}`.
- **Onboarding today**: `/statusline-onboarding` (`commands/statusline-onboarding.md` + `skills/onboarding/SKILL.md`) is a *post-install quickstart* — it tells you the 4 next commands. It does **no provider selection and no auth**.
- **The statusline is non-interactive**: it renders on every hook fire. Onboarding must be a separate entry point. Two realistic hosts: (a) the Claude Code agent via a slash command + `AskUserQuestion`, (b) `install.sh`'s `read -rp` bash prompt.

---

## A. CONFIG SCHEMA

### Design principle
Introduce a **single source of truth** — a top-level `providers` object that captures *selection* and *auth state* per provider. The legacy `external_providers` block is kept as a **read-only fallback** for backward compat and migrated lazily. The `tier` key is kept (it controls *density*/extra dashboard lines, not *which* providers appear).

### A.1 New config shape (target)

```json
{
  "tier": "full",
  "mode": "full",

  "providers": {
    "schema_version": 1,
    "selected": ["claude", "codex", "glm"],
    "auth": {
      "claude":      { "method": "auto",     "status": "ok",       "checked_at": 1780000000 },
      "codex":       { "method": "cli",      "status": "ok",       "checked_at": 1780000000 },
      "glm":         { "method": "keychain", "status": "ok",       "checked_at": 1780000000, "base_url": "https://api.z.ai" },
      "droid":       { "method": "cli",      "status": "missing",  "checked_at": 1780000000 },
      "antigravity": { "method": "cli",      "status": "unauth",   "checked_at": 1780000000, "bin": "antigravity-usage" },
      "copilot":     { "method": "gh",       "status": "unauth",   "checked_at": 0 }
    }
  },

  "external_providers": {
    "enabled": true,
    "codex":       { "enabled": true },
    "glm":         { "enabled": true, "base_url": "https://api.z.ai" },
    "droid":       { "enabled": false },
    "antigravity": { "enabled": false }
  },

  "schedule_url": "...",
  "schedule_cache_hours": 3
}
```

Key points:
- `providers.selected` is an **ordered array**. Order = top-to-bottom render order in the cockpit. `claude` is always implicitly first if present (it owns the rate-limit dashboard line, not an external row).
- `providers.auth.<provider>` carries **only non-secret metadata** + the storage method. Secrets never live in this file. `status` ∈ `ok | missing | unauth | invalid | unknown`. `checked_at` is an epoch timestamp so the engine can decide whether to re-validate.
- `method` declares where the secret lives so the engine and onboarding agree:
  - `auto` — Claude OAuth, nothing to store.
  - `cli` — provider's own CLI owns auth (Codex rollout files, Droid telemetry, Antigravity `antigravity-usage`). No secret stored by us.
  - `keychain` — secret in OS keychain under a statusline-owned service name (GLM today; Copilot token if we choose keychain over `gh`).
  - `env` — secret read from an env var the user exported themselves (legacy escape hatch).
  - `gh` — Copilot via `gh auth` (preferred) or a `GITHUB_TOKEN`.
- `external_providers` is **kept and kept in sync** by the onboarding writer, so the *existing* engine path (`collect_external_usage` → `get_provider_usage`) works unchanged in Phase 1. It becomes a derived/mirrored view; later phases can have the engine read `providers.selected` directly.

### A.2 Before / after for a real existing install

**Before** (today's typical `~/.claude/statusline-config.json`):
```json
{ "tier": "full", "external_providers": { "enabled": false } }
```
**After migration (Phase 1, automatic)**:
```json
{
  "tier": "full",
  "providers": {
    "schema_version": 1,
    "selected": ["claude"],
    "auth": { "claude": { "method": "auto", "status": "ok", "checked_at": 0 } }
  },
  "external_providers": { "enabled": false }
}
```
Migration rule: **no `providers` key ⇒ `selected = ["claude"]`** (the always-on baseline). Nobody loses their current single-line statusline; nobody suddenly gets a 5-row cockpit.

### A.3 Migration path (concrete, in `load_config`)

Add a `migrate_providers(config)` step called right after `config.update(user)` in `load_config()` (`engines/python-engine.py`):

1. If `providers` missing or `providers.schema_version` absent → build it:
   - `selected = ["claude"]` + any provider in `external_providers` whose `enabled is True` (preserves a user who manually turned on GLM).
   - For each selected provider, run the **non-interactive** `detect_auth(provider)` (§C) and write the resulting `auth` entry with `checked_at = 0`.
2. If `providers` exists but `schema_version < 1` → upgrade in place (none needed yet; the version gate future-proofs).
3. **Never delete `external_providers`.** Instead, add a `_sync_external_from_providers(config)` that, when writing config from onboarding, mirrors `providers.selected` into `external_providers.<p>.enabled`. This keeps the Node/Bash engines (which read `external_providers`) consistent until they're taught about `providers`.

Migration is **idempotent and pure** — easy to unit-test (extend `tests/test_multi_cli_tier.py` style).

---

## B. ONBOARDING FLOW

### B.1 Where it lives
Two co-equal entry points, sharing one Python "decision engine" so behavior is identical:

1. **Primary: slash command `/statusline-onboarding`** (extend the existing `commands/statusline-onboarding.md` + `skills/onboarding/SKILL.md`). The Claude Code agent drives it with `AskUserQuestion`. This matches how the README tells users to install ("Ask Claude"). **Most users hit this path.**
2. **Secondary: `install.sh` interactive prompt** (extend `prompt_for_tier` region). Adds a `--providers` interactive mode for users who installed via the one-liner. Non-interactive (`--quiet`/`--tier`) skips it and writes `selected = ["claude"]`.

A dedicated Python module `lib/onboarding.py` holds the pure logic: `detect_all_auth()`, `plan_screens()`, `apply_selection()`. Both entry points shell/call into it. This avoids duplicating the flow in bash and in the skill prompt.

### B.2 The flow (exact screens / question wording)

The statusline is non-interactive, so this is a **one-shot wizard** that runs in the agent (or bash) and writes config + secrets, then the user restarts Claude Code.

**Screen 0 — Detect.** Before asking anything, run `detect_all_auth()` (§C). Determine, per provider, `present | absent | unauth`. Build the question text from results so already-authed providers are visibly skippable.

**Screen 1 — "Which providers do you use?"** (multi-select, the only mandatory question)
> **"Which AI providers do you want to see in your statusline?** Claude is always included. Use space/number keys to toggle."
>
> - [x] **Claude** *(already authenticated — detected)*
> - [ ] **Codex** (OpenAI) — *requires the `codex` CLI logged in*
> - [ ] **GLM** (z.ai) — *requires a z.ai API key*
> - [ ] **Antigravity** (Google) — *requires the `antigravity-usage` CLI*
> - [ ] **Copilot** (GitHub) — *requires `gh auth` or a GitHub token*  ← disabled with "(coming soon)" if not shipped yet
> - [ ] **Droid** (Factory) — *requires Droid installed*  ← off by default, shown last (it only shows a token count)

Exact wording rationale: every option names **what auth it needs** so the user can predict Screen 2.

**Screen 2 — Layout preview + confirm** (single-select, derived from Screen 1)
The wizard computes the layout from the selection and shows a literal ASCII mock, then asks to confirm or drop to a single-line tier:
> **"You selected Claude + Codex + GLM. Here's your statusline shape:**
> ```
> ▸ Sonnet 4.6 ▸ 360K/1.0M 36% ▸ $4.20 ▸ LOCAL ▸ main saved
> │ ▸ Claude 5h ▰▰▱▱▱ 20% · weekly ▰▰▰▱▱ 42% │
> │ ▸ Codex  5h ▰▱▱▱▱ 5%  · 7d   ▰▱▱▱▱ 11% │
> │ ▸ GLM    5h 3% · tok 9%                 │
> ```
> 1. Use this cockpit (multi-provider, 4 rows)
> 2. Single line — Claude only (switch selection back to just Claude, `tier=full`)

If selection = `{claude}` only, **skip Screen 2** entirely and just set `tier` per the existing tier question (Screen 2 collapses to today's `prompt_for_tier`). This preserves the current install UX for the majority who only want Claude.

**Screen 3 — Auth, per selected-but-unauthed provider** (loop, one card each)
For each provider in `selected` whose `detect_auth` returned `absent` or `unauth`, show a provider-specific card (see §C for exact prompts). Already-authed providers get a one-line "✓ Codex: detected" and are skipped.

**Screen 4 — Validate + write.** For each newly-credentialed provider, run `validate(provider)` (§C). On success, write `providers` + mirrored `external_providers` atomically, store secrets in keychain, print:
> "✓ Saved. Restart Claude Code to see your 3-provider cockpit. Re-run `/statusline-onboarding` anytime to add or remove a provider."

On validation failure: show the error, offer "retry key" / "skip provider for now" / "cancel".

### B.3 Re-runnability
`/statusline-onboarding` is **additive and re-runnable**: on a second run, Screen 1 pre-selects current `providers.selected`, and Screen 3 only cards providers whose `status != ok` or whose `checked_at` is older than 7 days. This makes it the *single* command for add/remove/re-auth — replacing the implicit "edit JSON" workflow.

---

## C. AUTH HANDLING

A single `lib/onboarding.py` table drives detection, prompting, storage, and validation. Format: `provider → (needs, detect, prompt, store, validate)`.

### C.1 Per-provider matrix

| Provider | Needs | Detect existing auth | Prompt wording | Storage | Validate (cheap probe) |
|---|---|---|---|---|---|
| **claude** | nothing (auto) | `_get_oauth_token()` non-empty (reuse existing fn) | *none — auto-skipped* | n/a | `GET api.anthropic.com/api/oauth/usage` 200 (reuse `seg_rate_limits` fetch, 5s timeout) |
| **codex** | Codex CLI logged in | `_newest_codex_rollout()` non-null **or** `~/.codex/auth.json` exists | "Run `codex login` in another terminal, then press Enter to continue. (Statusline reads Codex's own session files — no key to paste.)" | n/a (CLI-owned) | re-run `_newest_codex_rollout()`; if a `token_count` event exists in the last 7d → ok, else `unauth` |
| **glm** | z.ai API key | `_glm_key(config)` non-empty (env / config / `providers.env`) | "Paste your z.ai API key (find it at https://z.ai/…):" — input masked | **keychain** under service `claude-statusline-glm`, account `glm`; also strip any plaintext `api_key` from config during migration | `_fetch_glm_response(config, key)` (existing fn) returns parseable quota JSON → ok |
| **droid** | Droid installed | `_droid_settings_candidates()` yields a file with token data | "Install Factory Droid and start one session, then press Enter." | n/a (CLI-owned) | re-run `get_droid_usage`; `available==True` → ok |
| **antigravity** | `antigravity-usage` CLI logged in | `shutil.which("antigravity-usage")` and a non-empty quota JSON cache | "Run `antigravity-usage login` (or open the Antigravity app), then press Enter." | n/a (CLI-owned) | spawn `antigravity-usage quota --json --method auto` with 5s timeout; `_map_antigravity_snapshot` returns metrics → ok |
| **copilot** *(planned)* | `gh auth` OR `GITHUB_TOKEN` | `gh auth status` exit 0 **or** `GITHUB_TOKEN` env set | "Authenticate with `gh auth login` (recommended), or paste a GitHub PAT with `read:org` scope:" | prefer `gh`; if PAT given → keychain service `claude-statusline-copilot` | `gh api /user` 200 **or** `GET api.github.com/user` with the PAT → ok. **Probe gated behind Copilot being implemented in `usage_providers.py`.** |

### C.2 "Already authenticated → skip" logic
`detect_all_auth()` returns `{provider: AuthState}` where `AuthState.status` is one of `ok | missing | unauth | invalid | unknown`. The rule for Screen 3:
- `ok` → skip, print "✓ <Provider>: detected".
- `missing`/`unauth` → card the user.
- `invalid` (validate failed previously) → card with a warning: "⚠ last saved credential was rejected — re-enter?"
Detection is **read-only and side-effect-free**; it reuses the existing reader functions in `usage_providers.py` so there's exactly one truth source for "is this provider reachable".

### C.3 Secret storage decision (keychain vs file vs env)
- **Default = keychain** on macOS/Windows; on Linux, fall back to a `0600` file `~/.claude/statusline-secrets.json` (or `secret-tool` if available). This **fixes the current plaintext-`api_key`-in-config smell** for GLM.
- The engine's `_glm_key` is extended to consult keychain *first* (new helper `_keychain_get("claude-statusline-glm", "glm")`), then env, then config (for backward compat with existing plaintext keys — migration moves them to keychain on first onboarding run and blanks the config field).
- **Never print secret values** in chat/logs (per repo secret rules). Validation probes that echo a response must redact the `Authorization` header.
- The Claude OAuth token stays exactly where it is (keychain service `Claude Code-credentials`) — onboarding must **not** touch `ANTHROPIC_API_KEY` (repo rule: that key is `DO_NOT_TOUCH`).

### C.4 Validation before save
Every provider card runs `validate()` **before** persisting. Failure does not abort the whole wizard — it offers retry/skip. This prevents the classic "saved a typo'd key, statusline silently shows nothing" failure mode. The `checked_at` timestamp written on success lets the engine avoid re-probing on every render (probes are network calls; the statusline must stay sub-100ms).

---

## D. RENDER IMPACT

### D.1 How the engine decides which rows to draw
Add a thin shim `_selected_external_providers(config)` in `engines/python-engine.py` that returns the ordered list of external providers to render. Resolution order:
1. If `providers.selected` present → use it (minus `claude`, which is always the rate-limit line).
2. Else fall back to today's `_effective_external_usage_config` behavior.

`build_external_usage_lines` then iterates this list instead of the hardcoded `("codex","glm","droid","antigravity")` tuple in `collect_external_usage` (which gets a `only=` parameter). This is a ~10-line change and keeps the existing record-formatting code untouched.

### D.2 Do tiers survive, or does selection replace them?
**Tiers survive, but their meaning narrows to "density / extra dashboard lines":**
- `tier` still controls line-1 segments and whether the timeline/burn-rate/cache lines appear (the existing `TIER_PRESETS` + the multi-line block in `main()`).
- **Selection controls *which provider rows* appear**, not tiers.
- The `multi-cli` tier is redefined as **"auto-cockpit"**: when `len(providers.selected) >= 2`, onboarding sets `tier = "multi-cli"` (so line 1 stays clean and rows stack); when `selected == ["claude"]`, it sets `tier = "full"` (the recommended single-provider dashboard). Users can still override `tier` manually afterward.
- The implicit "force codex+glm on in multi-cli" logic in `_effective_external_usage_config` is **removed** once `providers.selected` is the source of truth — it was a workaround for the absence of selection.

### D.3 Graceful handling when a selected provider's auth later breaks
Today a broken provider silently returns `unavailable()` and renders nothing — the row just vanishes, which is confusing ("did I lose Codex?"). Changes:
- `collect_external_usage` returns records even when `available=False`, carrying `status` from `providers.auth` + `stale_seconds`.
- The renderer (`build_external_usage_lines`) draws a **degraded row** instead of dropping the line: e.g. `│ ▸ Codex  auth expired — /statusline-onboarding │` (yellow), reusing the existing `render_dashboard_line` border style so it visually belongs.
- A provider whose cache is older than its TTL *and* `validate()` last failed flips to a `·stale` marker (the `_usage_stale_marker` pattern already exists for Claude).
- `doctor.sh` gets a new check `check_providers_auth` that re-runs `detect_all_auth()` and warns on any `status != ok` for a selected provider, with the fix hint "run /statusline-onboarding".

---

## E. IMPLEMENTATION PHASES

Ordered so each phase ships independently and is verifiable.

### Phase 1 — Selection model + migration (the MVP)
**Goal:** a user can pick a subset of providers without JSON editing; no new auth UX yet.
**Files touched:**
- `engines/python-engine.py` — `migrate_providers()`, `_selected_external_providers()`, call both from `load_config()` / `build_external_usage_lines()`.
- `lib/usage_providers.py` — add `only=` param to `collect_external_usage`.
- `lib/onboarding.py` — **new** — `detect_all_auth()` (read-only) + `apply_selection(config, selected)`.
- `commands/statusline-onboarding.md` + `skills/onboarding/SKILL.md` — rewrite Screen 1 + Screen 2 (no auth cards yet; if a selected provider is unauth, print "run `<cmd>` to authenticate" and leave `status=unauth`).
- `tests/test_onboarding.py` — **new** — migration idempotence, `selected`→`external_providers` mirror, single-provider path unchanged.
**Risk/effort:** Low risk (pure additive config, full backward compat). ~1–2 days. Highest-value-per-effort.

### Phase 2 — Guided per-provider auth (the "proper onboarding")
**Goal:** Screen 3 cards; keychain storage; validation-before-save.
**Files touched:**
- `lib/onboarding.py` — full provider table (§C.1), keychain helpers (port `_keychain_*` from the engine into a shared `lib/secrets.py` so both onboarding and the GLM reader use them), `validate()` probes.
- `lib/usage_providers.py` — extend `_glm_key` to read keychain first; blank plaintext `api_key` on migration.
- `lib/secrets.py` — **new** — `secret_store(service, account, value)`, `secret_read(...)`, with macOS/Windows/Linux backends.
- `skills/onboarding/SKILL.md` — add the per-provider card prompts (exact wording in §C.1).
- `tests/test_onboarding.py` — mock keychain; assert plaintext-to-keychain migration; assert validate-failure → no save.
**Risk/effort:** Medium risk (keychain cross-platform, secret handling). ~3–4 days. Security-sensitive — needs the "never log secrets" review.

### Phase 3 — Installer integration + doctor check
**Goal:** `install.sh` / `install.ps1` offer the wizard; doctor surfaces broken auth.
**Files touched:**
- `install.sh` — new `prompt_for_providers()` after `prompt_for_tier()`, calling `python3 -m lib.onboarding --interactive` (or a bash re-implementation reading the same JSON). `--quiet` skips it.
- `install.ps1` — mirror.
- `doctor/doctor.sh` — `check_providers_auth` (calls `detect_all_auth`, warns on non-ok selected providers).
- `droid-wiki/reference/configuration.md` — document `providers` schema.
**Risk/effort:** Low-medium (two shell scripts; doctor is well-structured). ~1–2 days.

### Phase 4 — Render resilience + Copilot
**Goal:** degraded rows for broken auth; ship Copilot now that the framework is generic.
**Files touched:**
- `lib/usage_providers.py` — `get_copilot_usage()` (new) + register in `PROVIDERS`; `collect_external_usage` returns `available=False` records with `status`.
- `engines/python-engine.py` — `build_external_usage_lines` draws degraded rows.
- `engines/node-engine.js` + `engines/bash-engine.sh` — parity for the degraded-row rendering (or document as Python-only; Narrator is already Python-only, precedent exists).
- `tests/test_multi_cli_tier.py` — extend with degraded-row + copilot cases.
**Risk/effort:** Medium (new provider integration; engine parity). ~3–4 days. Copilot only lands here, not earlier, since `usage_providers.py` has no Copilot reader today.

### Phase 5 (optional) — Teach Node/Bash engines to read `providers` directly
Drop the `external_providers` mirror; both engines parse `providers.selected`. Backward-compat shim retained one release longer.
**Risk/effort:** Low, mostly mechanical. ~1 day. Defer until Phase 1–4 are stable in the field.

---

## F. OPEN QUESTIONS / DECISIONS for the maintainer

1. **Drop the `tier` system, or keep it?** This plan *keeps* tiers (redefined as density only) for backward compat and because `full`'s timeline/burn-rate lines are genuinely orthogonal to provider selection. **Alternative:** collapse `tier` into a `density: minimal|standard|full` and remove `multi-cli` entirely (auto-cockpit whenever `selected.length >= 2`). Recommend keeping tiers for v1; revisit after Phase 4.
2. **Copilot scope.** It is *not implemented* in `usage_providers.py` today. Does the maintainer want Copilot in Phase 4 (full implementation, including a `get_copilot_usage` reader against GitHub's Copilot usage API), or should the onboarding list it as "coming soon" and skip the card? The plan currently does the latter until Phase 4.
3. **Copilot auth source.** Prefer `gh auth` (zero secret handling on our side, but adds a `gh` dependency) vs. a stored PAT (works without `gh`, but we own a secret). Recommend `gh auth` first, PAT as fallback.
4. **GLM plaintext-key migration.** Migrating existing `external_providers.glm.api_key` to keychain is a one-way, silent change to users' files. Confirm we should do this automatically in Phase 2, or prompt first. (Repo security posture says: just do it, but flag in the changelog.)
5. **Droid's place.** Droid currently shows only a cumulative token count (the test explicitly notes it was demoted to opt-in for being "confusing"). Should onboarding even list it, or keep it as an undocumented power-user toggle? Recommend: list it last, off by default, with the honest label "shows cumulative token count only".
6. **Default selection for brand-new installs.** Should `selected` default to `["claude"]` (quietest, recommended) or to `["claude", "codex", "glm"]` (the current "busy cockpit" behavior)? This plan defaults to `["claude"]` and lets onboarding upsell — explicitly reversing today's "everyone gets everything" posture, which is the stated motivation for this feature. Confirm.
7. **Where to store `checked_at` truth.** Writing `checked_at`/`status` into `statusline-config.json` means the file gets rewritten by the engine, not just by onboarding. Cleaner alternative: a separate `~/.claude/statusline-provider-state.json` (matches the existing pattern of `statusline-state.json`, `statusline-sdk-ledger.json`). Recommend the separate file to keep config human-editable and stable.
8. **Validation probe cost.** GLM/Copilot/Claude validation are network calls. Onboarding is fine (interactive), but the doctor check should be cached/throttled to avoid hammering APIs on every `doctor.sh` run. Decide TTL (suggest 1 hour, matching `EXTERNAL_USAGE_CACHE_TTL`).
9. **Node/Bash engine parity.** Today they share `external_providers`. If Phase 1 makes `providers.selected` the source of truth, the Node/Bash engines keep working only because of the mirror. Confirm the mirror is acceptable for one release, or mandate Phase 5 lands together with Phase 1.

---

**Net effect:** Phase 1 alone delivers the headline ask (choose your subset, no more forced cockpit) with zero auth risk because it reuses existing readers. Each later phase adds depth (guided auth → installer/doctor integration → resilience + Copilot) without ever breaking a config file that exists today.
