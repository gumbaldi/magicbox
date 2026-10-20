"""The one owner of a batch's `status.json` and the `done/` + `skipped/` mirror directories.

`status.json` (`{"schema": 1, "phases": {<slug>: {"status", "at", ...}}}`) is the authority for
per-phase state; a phase's plan file lies where its status says (`done` -> `done/`, `skipped` ->
`skipped/`, `open`/`error` -> the batch root). Every script reads phase state through here and
never globs phase files to decide a state; `status.json` is written only here, through
`render.write_json`. CLI-less library: no printing, no `sys.exit` -- a failure raises
`PhaseStateError` carrying a `code` the calling verb maps to its own error shape.
"""

import json
import pathlib
import shutil

from . import render

STATUS_FILE = "status.json"
SCHEMA = 1
STATUSES = ("open", "done", "error", "skipped")
PENDING = ("open", "error")
SUBDIR = {"done": "done", "skipped": "skipped"}
PHASE_GLOB = "[0-9][0-9]-*.md"

# (from, to) pairs transition() accepts. error -> error is a retried phase going red again;
# leaving `skipped` is unskip()'s job alone.
TRANSITIONS = {
    ("open", "done"), ("open", "error"), ("open", "skipped"),
    ("error", "done"), ("error", "error"), ("error", "skipped"),
    ("done", "open"),
}


class PhaseStateError(Exception):
    """`code` is one of STATUS_FILE_MISSING, STATUS_FILE_INVALID, UNKNOWN_PHASE,
    INVALID_TRANSITION."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _path(batch_dir):
    return batch_dir / STATUS_FILE


def _dir_for(batch_dir, status):
    sub = SUBDIR.get(status)
    return batch_dir / sub if sub else batch_dir


# ---------------------------------------------------------------- read side

def exists(batch_dir):
    return _path(batch_dir).is_file()


def load(batch_dir):
    f = _path(batch_dir)
    if not f.is_file():
        raise PhaseStateError("STATUS_FILE_MISSING", f"{f} does not exist")
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        raise PhaseStateError("STATUS_FILE_INVALID", f"{f} is not readable JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("phases"), dict) or any(
        not isinstance(v, dict) or v.get("status") not in STATUSES
        for v in data["phases"].values()
    ):
        raise PhaseStateError("STATUS_FILE_INVALID", f"{f} does not have the status.json shape")
    return data


def phase_files(batch_dir):
    """slug -> plan-file path over the batch root, `done/` and `skipped/` (root wins a tie)."""
    found = {}
    for d in (batch_dir, batch_dir / "done", batch_dir / "skipped"):
        if d.is_dir():
            for p in sorted(d.glob(PHASE_GLOB)):
                found.setdefault(p.stem, p)
    return found


def locate(batch_dir, slug):
    return phase_files(batch_dir).get(slug)


def resolve_slug(batch_dir, ref):
    """`ref` is a full slug or its number (`3`, `03`); the slug must have a status entry."""
    ref = str(ref).strip()
    phases = load(batch_dir)["phases"]
    if ref in phases:
        return ref
    if ref.isdigit():
        num = ref.zfill(2)
        for slug in sorted(phases):
            if slug[:2] == num:
                return slug
    raise PhaseStateError("UNKNOWN_PHASE", f"no phase '{ref}' in {batch_dir.name}")


def phases(batch_dir):
    """Every entry sorted by slug: slug, num, status, path (None without a file), at, reason,
    previous, plus any annotated field."""
    files = phase_files(batch_dir)
    out = []
    for slug, entry in sorted(load(batch_dir)["phases"].items()):
        rec = {"at": None, "reason": None, "previous": None}
        rec.update(entry)
        rec.update(slug=slug, num=slug[:2], path=files.get(slug))
        out.append(rec)
    return out


def counts(batch_dir):
    c = {s: 0 for s in STATUSES}
    for p in load(batch_dir)["phases"].values():
        c[p["status"]] += 1
    return c


def next_pending(batch_dir):
    """The lowest-numbered phase that is `open` or `error` (an error phase blocks), or None."""
    for slug, entry in sorted(load(batch_dir)["phases"].items()):
        if entry["status"] in PENDING:
            return slug
    return None


def mismatches(batch_dir):
    """Where the mirror and status.json disagree: `location` (file lies in the wrong
    directory), `no_entry` (a file without an entry), `no_file` (an entry without a file)."""
    entries = load(batch_dir)["phases"]
    files = phase_files(batch_dir)
    out = []
    for slug in sorted(set(entries) | set(files)):
        entry, path = entries.get(slug), files.get(slug)
        if entry is None:
            out.append({"slug": slug, "kind": "no_entry", "path": str(path)})
        elif path is None:
            out.append({"slug": slug, "kind": "no_file", "status": entry["status"]})
        elif path.parent != _dir_for(batch_dir, entry["status"]):
            out.append({
                "slug": slug, "kind": "location", "status": entry["status"],
                "path": str(path), "expected": str(_dir_for(batch_dir, entry["status"]) / path.name),
            })
    return out


# --------------------------------------------------------------- write side

def _save(batch_dir, data):
    data["phases"] = {k: data["phases"][k] for k in sorted(data["phases"])}
    render.write_json(_path(batch_dir), data)


def _move(src, dst_dir):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src != dst:
        shutil.move(str(src), str(dst))
    return dst


def _entry(data, batch_dir, slug):
    if slug not in data["phases"]:
        raise PhaseStateError("UNKNOWN_PHASE", f"no phase '{slug}' in {batch_dir.name}")
    return data["phases"][slug]


def init(batch_dir):
    """Writes the empty file, only when it is missing."""
    if not exists(batch_dir):
        _save(batch_dir, {"schema": SCHEMA, "phases": {}})


def sync_files(batch_dir):
    """Adopts a plan file that has no entry by where it lies (root -> open, `done/` -> done,
    `skipped/` -> skipped with previous `open`) and drops an `open` entry whose file is gone.
    An existing entry is never changed otherwise."""
    data = load(batch_dir)
    files = phase_files(batch_dir)
    added, removed = [], []
    for slug, path in sorted(files.items()):
        if slug in data["phases"]:
            continue
        if path.parent.name == "done" and path.parent.parent == batch_dir:
            entry = {"status": "done", "at": render.now_iso()}
        elif path.parent.name == "skipped" and path.parent.parent == batch_dir:
            entry = {"status": "skipped", "at": render.now_iso(), "previous": "open"}
        else:
            entry = {"status": "open"}
        data["phases"][slug] = entry
        added.append(slug)
    for slug, entry in sorted(data["phases"].items()):
        if entry["status"] == "open" and slug not in files:
            del data["phases"][slug]
            removed.append(slug)
    if added or removed:
        _save(batch_dir, data)
    return {"added": added, "removed": removed}


def _apply(batch_dir, data, slug, entry, target_dir):
    """Move-then-write: the file goes to `target_dir`, then status.json; a failed write moves
    the file back and re-raises."""
    src = locate(batch_dir, slug)
    moved = _move(src, target_dir) if src is not None else None
    old = data["phases"][slug]
    data["phases"][slug] = entry
    try:
        _save(batch_dir, data)
    except BaseException:
        data["phases"][slug] = old
        if moved is not None and moved != src:
            _move(moved, src.parent)
        raise
    return moved


def transition(batch_dir, slug, status, reason=None):
    """Moves `slug` to `status` and returns the plan file's new path (None when the file is
    missing)."""
    data = load(batch_dir)
    old = _entry(data, batch_dir, slug)
    if status not in STATUSES or (old["status"], status) not in TRANSITIONS:
        raise PhaseStateError(
            "INVALID_TRANSITION", f"{slug}: {old['status']} -> {status} is not allowed"
        )
    entry = {k: v for k, v in old.items() if k not in ("reason", "previous")}
    entry.update(status=status, at=render.now_iso())
    if status == "skipped":
        entry["previous"] = old["status"]
        if reason:
            entry["reason"] = reason
    return _apply(batch_dir, data, slug, entry, _dir_for(batch_dir, status))


def unskip(batch_dir, slug):
    """Returns the file to the batch root and restores the status held before the skip.
    Returns (path, restored_status)."""
    data = load(batch_dir)
    old = _entry(data, batch_dir, slug)
    if old["status"] != "skipped":
        raise PhaseStateError("INVALID_TRANSITION", f"{slug} is {old['status']}, not skipped")
    restored = old.get("previous") if old.get("previous") in PENDING else "open"
    entry = {k: v for k, v in old.items() if k not in ("reason", "previous")}
    entry.update(status=restored, at=render.now_iso())
    return _apply(batch_dir, data, slug, entry, batch_dir), restored


def snapshot(batch_dir, slug):
    """The phase's entry and file path right now, for restore()."""
    entry = load(batch_dir)["phases"].get(slug)
    path = locate(batch_dir, slug)
    return {"entry": dict(entry) if entry is not None else None, "path": str(path) if path else None}


def restore(batch_dir, slug, snap):
    """Puts the entry and the file back as snapshot() saw them."""
    data = load(batch_dir)
    if snap["path"] is not None:
        wanted = pathlib.Path(snap["path"])
        current = locate(batch_dir, slug)
        if current is not None and current != wanted:
            _move(current, wanted.parent)
    if snap["entry"] is None:
        data["phases"].pop(slug, None)
    else:
        data["phases"][slug] = snap["entry"]
    _save(batch_dir, data)


def annotate(batch_dir, slug, **fields):
    """Adds or replaces extra fields on an entry; `status` and `at` are transition()'s."""
    if {"status", "at"} & set(fields):
        raise ValueError("annotate() never sets status or at")
    data = load(batch_dir)
    _entry(data, batch_dir, slug).update(fields)
    _save(batch_dir, data)
