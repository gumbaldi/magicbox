"""Shared batch-directory traversal for scripts that walk <repo>/.claude/cfq/impl/ -- the
second-caller module for cfq_scan.py and cfq_queue_overlap.py (both enumerate batch directories
and apply the same batch-name predicate). Directory enumeration, the batch-name predicate and
marker-file reading only -- no formatting, no ranking, no report logic; those stay in the callers.
Marker files read here: `.priority`, `.dependsOn`, `.batch-context.md`, `.review` (the review-gate
snapshot, see `read_review`/`review_snapshot`).
"""

import hashlib
import json
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


def read_section_full(batch_dir, heading, sep=" "):
    """The batch's whole `## <heading>` section body from `.batch-context.md`, its non-empty
    lines (a leading `- ` bullet marker stripped, if present) joined by `sep` -- unwrapped and
    untruncated. None if the file is absent, has no matching heading, or the section is empty.
    `read_goal_full` below is a thin `sep=" "` call over this; a `## Decisions` caller instead
    passes `sep=" · "` so the wrapped output keeps each bullet visibly separated rather than
    running every dash-stripped line together into one sentence."""
    f = batch_dir / ".batch-context.md"
    if not f.is_file():
        return None
    lines = []
    in_section = False
    marker = f"## {heading}"
    for line in f.read_text().splitlines():
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip():
            text = line.strip()
            if text.startswith("- "):
                text = text[2:]
            lines.append(text)
    body = sep.join(lines)
    return body if body else None


def read_section_lines(batch_dir, heading):
    """The raw lines of `.batch-context.md`'s `## <heading>` section (heading line excluded, stops
    at the next `## `), leading and trailing blank lines stripped -- bullets and paragraph breaks
    intact, unlike `read_section_full`'s flattened join. None if the file, the heading or any
    non-blank content is missing."""
    f = batch_dir / ".batch-context.md"
    if not f.is_file():
        return None
    lines = []
    in_section = False
    marker = f"## {heading}"
    for line in f.read_text().splitlines():
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            lines.append(line.rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or None


def read_goal_full(batch_dir):
    """The batch's whole `## Goal` section body from `.batch-context.md`, its non-empty lines
    joined by single spaces -- unwrapped and untruncated, unlike `read_goal` below. None if the
    file is absent, has no `## Goal` heading, or the section is empty. Thin call over
    `read_section_full`, its generalisation to an arbitrary heading."""
    return read_section_full(batch_dir, "Goal")


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


def review_snapshot(batch_dir):
    """`{name: sha256-hex}` for every open `[0-9][0-9]-*.md` directly in the batch directory plus
    `.batch-context.md` when it exists -- the content the review gate has shown the user."""
    names = sorted(p.name for p in batch_dir.glob("[0-9][0-9]-*.md") if p.is_file())
    if (batch_dir / ".batch-context.md").is_file():
        names.append(".batch-context.md")
    return {n: hashlib.sha256((batch_dir / n).read_bytes()).hexdigest() for n in names}


def read_review(batch_dir):
    """The parsed `.review` marker JSON, or None when the file is missing or not valid JSON."""
    f = batch_dir / ".review"
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
