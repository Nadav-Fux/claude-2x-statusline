# claude-2x-statusline — Changelog

Release posts covering feature areas, bug fixes, and infrastructure changes.

All posts are **bilingual (English + Hebrew)** — English first, Hebrew below in each file.

---

## 2026-04-20

- [2026-04-20 — Bilingual narrator — Hebrew auto-detect and full translation coverage](2026-04-20-bilingual-narrator.md) — Locale auto-detect from `$LANG`/`$LC_ALL`; all 18 insight templates now carry `text_he`; three output modes (`en`, `he`, `en,he`); structural test enforces bilingual contract on new templates.

---

## 2026-04-19

- [2026-04-19 — Rolling-window metrics — spending & cache, not lifetime averages](2026-04-19-rolling-window-metrics.md) — Burn rate now uses a 10-minute rolling window with severity labels; cache segment shows reuse %, delta, and state word; spike guards prevent $800/hr absurdities.

- [2026-04-19 — Narrator hook — a co-pilot above the prompt](2026-04-19-narrator-hook.md) — Hook-injected narrative fires above your next prompt via SessionStart; two-tier system (rules engine always-on + optional Haiku layer); session memory with cross-session continuity.

- [2026-04-19 — `/explain` + doctor — know your statusline](2026-04-19-explain-and-doctor.md) — `/explain <segment>` gives detailed per-segment breakdowns; `/explain` alone prints a 20-row table; `/statusline-doctor --fix` repairs 8 common issues interactively.

- [2026-04-19 — Bug fixes — Saturday peak spillover + numeric spike cleanup](2026-04-19-bug-fixes-spillover-and-spikes.md) — Saturday UTC peak was invisible to UTC+3 users on local Sunday; four separate numeric overflow bugs ($1.2M/hr, $55B projected, 29M%, $813/hr) all fixed with guards and caps.

- [2026-04-19 — Install telemetry — what we send, why, and how to opt out](2026-04-19-install-telemetry-transparency.md) — Full transparency post: exact JSON payload, what is and isn't collected, Cloudflare KV storage, public `/stats` endpoint, and a working opt-out flag.

- [2026-04-19 — Windows-specific hardening — WindowsApps stubs, cygpath, UTF-8](2026-04-19-windows-support.md) — Rejects Microsoft Store stub binaries from PATH; probes portable install locations; converts Git Bash paths via cygpath; forces UTF-8 to prevent cp1252 crashes; patches embeddable Python `_pth`.

---

*Posts are added when a feature area is complete enough to document. Dates reflect the release/merge date, not the authoring date.*
