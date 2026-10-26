"""Session reasoning-effort comparison for the `/pfq` and `/ifq` preflights.

Claude Code sets `CLAUDE_EFFORT` for every command a session runs through its shell tool, to the
level in effect at that moment; the preflights read it and call `check()` against the configured
minimum. A warning only -- nothing here ever blocks. A missing or unknown level yields no warning.
"""

ORDER = ("low", "medium", "high", "xhigh", "max")


def _known(level):
    """The lower-cased level when it is one of `ORDER`, else None."""
    word = (level or "").strip().lower()
    return word if word in ORDER else None


def check(current, required, key):
    """The warning text when `current` ranks below `required`, else None. `required` `off`, an
    empty or unknown `current` and an unknown `required` all return None."""
    cur = _known(current)
    req = _known(required)
    if cur is None or req is None or ORDER.index(cur) >= ORDER.index(req):
        return None
    return f"⚠️ effort {cur} is below {key} {required} — raise it with /effort {required}"


def status(current, required):
    """The top-level `effort` object of a preflight result."""
    return {"current": _known(current), "required": required, "ok": check(current, required, "") is None}
