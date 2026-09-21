"""The one place a result becomes either JSON or human-readable text — see CLAUDE.md's "No
duplicate renderers" invariant. Every port that emits both forms of the same value goes through
here rather than growing a second, drifting formatter — plus the small `write_json`/`now_iso`
helpers scripts otherwise duplicate.
"""

import json
import os
from datetime import datetime


def dump_json(obj):
    """Compact JSON, matching `jq -c`'s formatting: no extra whitespace, unicode kept raw."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def dump_json_pretty(obj):
    """2-space indented JSON, matching jq's default (non `-c`) pretty-print byte-for-byte."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


def jq_alt(*values):
    """Mirrors jq's `//`: the first value that is neither null nor false."""
    for v in values:
        if v is not None and v is not False:
            return v
    return None


def tostring(value):
    """Mirrors jq's `tostring` filter: a string passes through unquoted, everything else
    becomes its compact JSON form (numbers, bools and null included)."""
    if isinstance(value, str):
        return value
    return dump_json(value)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
