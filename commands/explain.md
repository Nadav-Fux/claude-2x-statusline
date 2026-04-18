---
description: "Explain what a statusline segment means"
allowed-tools: ["Bash"]
argument-hint: "[segment]"
---

Explain what a statusline segment means. With no argument, prints a table of
all segments with one-line descriptions. With a segment name (e.g. `burn_rate`,
`cache_hit`, `context_depletion`, `peak_hours`), prints a detailed explanation
including format, computation, colors, and when the segment hides.

## Steps

1. Locate the doctor script. Prefer the installed copy, fall back to the repo:
   - `~/.claude/cc-2x-statusline/doctor/doctor.sh`
   - `~/Github/claude-2x-statusline/doctor/doctor.sh` (fallback)
2. Run with `--explain $ARGUMENTS` — pass the argument verbatim.
   - No argument → print the segment table.
   - Segment name → print detailed block.
3. Show the output verbatim. Do not paraphrase.
