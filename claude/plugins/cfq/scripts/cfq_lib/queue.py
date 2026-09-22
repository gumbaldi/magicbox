"""Shared batch-directory traversal for scripts that walk <repo>/.claude/cfq/impl/ -- the
second-caller module for cfq_scan.py and cfq_queue_overlap.py (both enumerate batch directories
and apply the same batch-name predicate). Directory enumeration, the batch-name predicate and
marker-file reading only -- no formatting, no ranking, no report logic; those stay in the callers.
Marker files read here: `.priority`, `.dependsOn`, `.batch-context.md`.
"""

import re

BATCH_NAME_RE = re.compile(r"^([0-9]+-)?[0-9]{4}-[0-9]{2}-[0-9]{2}-.+")


def is_batch_name(name):
    return bool(BATCH_NAME_RE.match(name))


def list_batch_dirs(impl_dir):
    """Sorted immediate subdirectories of impl_dir whose name matches the batch-name pattern."""
    if not impl_dir.is_dir():
        return []
    return sorted(
        (p for p in impl_dir.iterdir() if p.is_dir() and is_batch_name(p.name)),
        key=lambda p: p.name,
    )


def read_priority(batch_dir):
    """"high" if .priority contains exactly that (after trimming), "" otherwise -- including a
    stale pre-priority-refactor value, a missing file, or no file at all."""
    f = batch_dir / ".priority"
    if not f.is_file():
        return ""
    return "high" if f.read_text().strip() == "high" else ""


def read_goal_full(batch_dir):
    """The batch's whole `## Goal` section body from `.batch-context.md`, its non-empty lines
    joined by single spaces -- unwrapped and untruncated, unlike `read_goal` below. None if the
    file is absent, has no `## Goal` heading, or the section is empty."""
    f = batch_dir / ".batch-context.md"
    if not f.is_file():
        return None
    lines = []
    in_goal = False
    for line in f.read_text().splitlines():
        if line.strip() == "## Goal":
            in_goal = True
            continue
        if in_goal and line.startswith("## "):
            break
        if in_goal and line.strip():
            lines.append(line.strip())
    goal = " ".join(lines)
    return goal if goal else None


def read_goal(batch_dir, max_len):
    """The batch's `## Goal` from `.batch-context.md`, cut to max_len at the last word boundary
    with a trailing '…'. None if the file is absent, has no `## Goal` heading, or the section is
    empty -- see `read_goal_full` for the same read without the cut."""
    goal = read_goal_full(batch_dir)
    if goal is None:
        return None
    if len(goal) > max_len:
        goal = goal[:max_len].rsplit(" ", 1)[0].rstrip(" .,;:-") + "…"
    return goal


def read_depends(batch_dir):
    """Dependency batch names from .dependsOn: one per line, '#' starts a trailing comment,
    blank lines dropped. [] if the file is absent."""
    f = batch_dir / ".dependsOn"
    if not f.is_file():
        return []
    deps = []
    for line in f.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            deps.append(line)
    return deps
