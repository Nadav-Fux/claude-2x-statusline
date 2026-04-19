"""narrator — plain-language session insight narrator for claude-2x-statusline.

Public API
----------
run(mode: str) -> str | None
    mode is "session_start" or "prompt_submit".
    Returns the narrator text to emit (1-2 lines), or None if nothing should
    emit (throttled, disabled, no data).

Hooks call this directly::

    from narrator import run
    text = run("prompt_submit")
    if text:
        print(text)
"""

from narrator.engine import run

__all__ = ["run"]
