---
description: "Switch the narrator's output language (English / Hebrew / both)"
allowed-tools: ["Bash"]
argument-hint: "en | he | en,he"
---

Switch the narrator output language by printing the exact `STATUSLINE_NARRATOR_LANGS` export command for the user to apply.

## Steps

1. Validate `$ARGUMENTS` is one of: `en`, `he`, `en,he`, `he,en`.
   - If empty → show the current locale-auto-detected language (from `$LANG` / `$LC_ALL`) and explain how to set it explicitly.
   - If invalid → print the accepted values and exit.

2. Confirm the selection to the user:
   - `en` → "Narrator will emit English only. Effective on next prompt."
   - `he` → "ה-narrator ידבר עברית מעתה."
   - `en,he` or `he,en` → "Narrator will emit both English and Hebrew on each emission."

3. Print the exact export commands for the user to apply:

   ```
   To apply permanently, add this to your shell profile (~/.bashrc / ~/.zshrc / your env setup):
     export STATUSLINE_NARRATOR_LANGS=<value>

   Or for this session only, run:
     export STATUSLINE_NARRATOR_LANGS=<value>
   ```

4. Include a tip: locale auto-detect from `$LANG` still works if `STATUSLINE_NARRATOR_LANGS` is left unset
   (e.g. `LANG=he_IL.UTF-8` → Hebrew by default).

## Notes

- Accepted values: `en` (English only), `he` (Hebrew only), `en,he` or `he,en` (both).
- The narrator engine reads `STATUSLINE_NARRATOR_LANGS` at hook invocation time; no restart required once the var is in your shell env.
- This command does **not** write to any files — the user retains full control over their shell profile.
