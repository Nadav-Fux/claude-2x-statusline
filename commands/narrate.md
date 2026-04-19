---
description: "Run the narrator manually and print its current observation"
allowed-tools: ["Bash"]
argument-hint: "[--haiku] [--force]"
---

Manually run the narrator. Default uses rules only; --haiku calls the LLM if available; --force bypasses the throttle.

## Steps

1. Locate the narrator via: `~/Github/claude-2x-statusline/hooks/narrator-prompt-submit.sh`
2. Run with env: `STATUSLINE_NARRATOR_THROTTLE_MIN=0 bash <path> $ARGUMENTS`
3. Print stdout verbatim (no paraphrasing).
