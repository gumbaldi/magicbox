"""User-owned trust store for the repo-supplied phase commit hook command.

`<home>/.claude/cfq/trusted-hooks.json` maps a repository's realpath to the sha256 of the one
command string the user approved for it: `{"<realpath>": "<sha256 hex>"}`, nothing else. The key is
never the plugin version and the file never lives inside the plugin directory, so a plugin update
cannot reset it; a changed command hashes differently and is untrusted again. A missing or
unreadable file means nothing is trusted.
"""

import hashlib
import json
import os
import tempfile

from .env import home_dir


def store_path():
    return home_dir() / ".claude" / "cfq" / "trusted-hooks.json"


def command_hash(command):
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _key(repo_root):
    return os.path.realpath(str(repo_root))


def _read():
    try:
        with open(store_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _write(data):
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".trusted-hooks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def status(repo_root, command):
    """`"unset"` for an empty command, else `"trusted"` or `"untrusted"`."""
    if not command:
        return "unset"
    if _read().get(_key(repo_root)) == command_hash(command):
        return "trusted"
    return "untrusted"


def control_characters(command):
    """The control characters in `command` as `U+XXXX` strings, in order of first appearance and
    without duplicates: code points below 0x20 except tab, 0x7f and 0x80-0x9f. Empty = clean."""
    found = []
    for char in command:
        code = ord(char)
        if (code < 0x20 and char != "\t") or 0x7F <= code <= 0x9F:
            label = f"U+{code:04X}"
            if label not in found:
                found.append(label)
    return found


def trust(repo_root, command):
    data = _read()
    data[_key(repo_root)] = command_hash(command)
    _write(data)


def revoke(repo_root):
    """Removes the repository's entry; returns whether there was one."""
    data = _read()
    if data.pop(_key(repo_root), None) is None:
        return False
    _write(data)
    return True
