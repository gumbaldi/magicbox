"""The `requiredTools` check -- see `docs/configuration.md`. A repo lists tool **names**; this
module only looks them up and never runs one, so a versioned settings file in a freshly cloned
repository cannot execute code at preflight.

- `py:<module>` (module matches `^[A-Za-z_][A-Za-z0-9_]*$`, no dots): present when
  `importlib.util.find_spec` finds it in the interpreter running cfq.
- any other entry matching `^[A-Za-z0-9._+-]+$`: present when `shutil.which` finds it.
- an entry matching neither pattern counts as missing and is never run.
"""

import importlib.util
import re
import shutil

from cfq_lib import text

MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
LABEL = "Required Tools"


def _present(entry):
    try:
        if entry.startswith("py:"):
            module = entry[3:]
            return bool(MODULE_RE.match(module)) and importlib.util.find_spec(module) is not None
        return bool(NAME_RE.match(entry)) and shutil.which(entry) is not None
    except Exception:
        return False


def check(entries):
    """`{"entries": [...], "missing": [...]}`: entries stripped (empty ones dropped), order kept,
    never raising."""
    cleaned = [e.strip() for e in (entries or []) if isinstance(e, str) and e.strip()]
    return {"entries": cleaned, "missing": [e for e in cleaned if not _present(e)]}


def status_entry(result, blocking):
    """The `Required Tools` status line; `None` when no tool is declared. `blocking` is true for
    `/ifq` (missing -> `fail`) and false for `/pfq` (missing -> `warn`)."""
    if not result["entries"]:
        return None
    missing = result["missing"]
    if not missing:
        return text.status_entry(LABEL, "done", f"{len(result['entries'])} present")
    names = ", ".join(missing)
    if blocking:
        return text.status_entry(LABEL, "fail", f"missing: {names} · install them, then re-run /ifq")
    return text.status_entry(LABEL, "warn", f"missing: {names} · /ifq stops until they are installed")
