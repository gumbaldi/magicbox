"""Pure move-and-record logic for `cfq trash` -- the only sanctioned delete under
`<repo>/.claude/cfq/`. No CLI, no printing, so `cfq_trash.py` and any future importer (phase 03's
recover path, phase 06's guard deny message) can use it without pulling in argument parsing.

`.claude/cfq/` is git-excluded, so a plain `rm` there is gone for good -- no commit, no reflog, no
recovery. `put` moves the target into `.trash/<id>/` instead of removing it; `restore` moves it
back. Deletion is `shutil.move` throughout -- nothing here ever calls `shutil.rmtree`/`os.unlink`
on a payload, and there is no retention window (deliberate, see `.batch-context.md`'s Decisions).
"""

import json
import pathlib
import shutil
from datetime import datetime, timezone

from . import paths as cfq_lib_paths


class TrashError(Exception):
    code = "TRASH_ERROR"


class OutOfScope(TrashError):
    code = "OUT_OF_SCOPE"


class NoSuchEntry(TrashError):
    code = "NO_SUCH_ENTRY"


class Occupied(TrashError):
    code = "OCCUPIED"


def trash_root(repo):
    return f"{cfq_lib_paths.cfq_repo_dir(repo)}/.trash"


def _check_in_scope(repo, path):
    repo_dir = pathlib.Path(cfq_lib_paths.cfq_repo_dir(repo)).resolve()
    resolved = pathlib.Path(path).resolve()
    try:
        resolved.relative_to(repo_dir)
    except ValueError:
        raise OutOfScope(f"{path} is not inside {repo_dir}")
    return resolved


def _reserve_entry_dir(root):
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    n = 0
    while True:
        candidate = root / f"{stamp}-{n:02d}"
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            n += 1


def put(repo, path, reason=""):
    resolved = _check_in_scope(repo, path)
    entry_dir = _reserve_entry_dir(pathlib.Path(trash_root(repo)))
    kind = "dir" if resolved.is_dir() else "file"
    shutil.move(str(resolved), str(entry_dir / resolved.name))
    entry = {
        "originalPath": str(resolved),
        "movedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reason": reason,
        "kind": kind,
    }
    (entry_dir / "entry.json").write_text(json.dumps(entry, indent=2) + "\n")
    return entry_dir.name


def entries(repo):
    root = pathlib.Path(trash_root(repo))
    if not root.is_dir():
        return []
    result = []
    for entry_dir in root.iterdir():
        info_file = entry_dir / "entry.json"
        if not info_file.is_file():
            continue
        data = json.loads(info_file.read_text())
        result.append({
            "id": entry_dir.name,
            "originalPath": data.get("originalPath"),
            "movedAt": data.get("movedAt"),
            "reason": data.get("reason", ""),
            "kind": data.get("kind"),
        })
    result.sort(key=lambda e: e["id"], reverse=True)
    return result


def restore(repo, entry_id, force=False):
    entry_dir = pathlib.Path(trash_root(repo)) / entry_id
    info_file = entry_dir / "entry.json"
    if not info_file.is_file():
        raise NoSuchEntry(f"no such trash entry: {entry_id}")

    data = json.loads(info_file.read_text())
    original_path = pathlib.Path(data["originalPath"])
    payload = next(p for p in entry_dir.iterdir() if p.name != "entry.json")

    if original_path.exists() or original_path.is_symlink():
        if not force:
            raise Occupied(f"restore target occupied: {original_path}")
        put(repo, str(original_path), reason=f"occupant of restore {entry_id}")

    original_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(payload), str(original_path))
    shutil.rmtree(entry_dir)
    return str(original_path)
