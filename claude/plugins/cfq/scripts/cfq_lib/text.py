"""Shared terminal-rendering helpers: padding, wrapping, aligned columns and icon lookup — see
CLAUDE.md's `cfq_lib/` list. Stdlib only, no I/O; every function here is a pure transform over
strings and lists so it can be unit-tested without a filesystem or a subprocess.

The contract these helpers implement is fixed by `references/output-format.md`: icon, label
padded to `LABEL_WIDTH`, detail, `   └ ` sub-lines, plain-space padding only (never an HTML
entity). Callers compose lines out of these primitives rather than re-deriving the format.
"""

import re
import textwrap
import unicodedata

# The four semantic status glyphs `references/output-format.md` fixes. A single place to read
# them from -- no caller hardcodes a glyph afterwards.
ICONS = {
    "done": "✅",
    "warn": "⚠️",
    "fail": "❌",
    "skip": "➖",
}

# The padding width `references/output-format.md` documents.
LABEL_WIDTH = 16

# Numbered-batch-name grammar, copied verbatim from cfq_batch_id.py's NUMBERED_RE so the two
# never disagree about what a numbered batch name is -- see this phase's plan, section Reuse.
# cfq_batch_id.py keeps its own copy (and its own numbered_width/numbered_number) because its
# callers run in an allocation inner loop that stays a deliberate direct-call exception; this
# module's copy is the one every terminal-rendering caller reads instead.
_NUMBERED_RE = re.compile(r"^([0-9]{3,})-([0-9]{4}-[0-9]{2}-[0-9]{2})-([a-z0-9][a-z0-9-]*)$")


def status_line(icon, label, detail):
    """`<glyph> <label padded to LABEL_WIDTH><detail>`. `icon` accepts either an ICONS key or a
    literal glyph, so a caller that already holds a glyph does not have to reverse-map it. A
    label at or past LABEL_WIDTH is never truncated: it overflows, with a single space before
    detail instead of the padding column, since a silently cut label is worse than a ragged
    column."""
    glyph = ICONS.get(icon, icon)
    if len(label) >= LABEL_WIDTH:
        return f"{glyph} {label} {detail}"
    return f"{glyph} {label:<{LABEL_WIDTH}}{detail}"


def sub_line(text_):
    """The sub-information line form `references/output-format.md` fixes: indented, never used
    as the detail column itself."""
    return f"   └ {text_}"


def status_entry(label, icon, detail, sub=None):
    """One `statusLines` entry, the shape every read-only aggregator that pre-renders its own
    status lines (`cfq_ifq_preflight.py`, `cfq_pfq_preflight.py`, `cfq_finish.py`, `cfq_phase.py`)
    returns: `label`/`icon`/`detail`/`sub` are what a test asserts against without string-matching
    padding, `text` is the same line already run through `status_line`/`sub_line` -- what a caller
    prints verbatim, one sub-line per `sub` entry, never re-padded or re-worded. `sub` defaults to
    `[]`, never `None`, so a caller can always iterate it without a null check."""
    sub = list(sub or [])
    lines = [status_line(icon, label, detail)] + [sub_line(s) for s in sub]
    return {"label": label, "icon": icon, "detail": detail, "sub": sub, "text": "\n".join(lines)}


def wrap(text_, width, indent="", max_lines=None):
    """Collapses whitespace, wraps on word boundaries to `width`, and prefixes every resulting
    line with `indent`. When `max_lines` is given and the text would wrap past it, the output is
    cut to exactly `max_lines` lines with the last one ending in '…' at a word boundary rather
    than mid-word. Returns [] for text that collapses to nothing. Never raises and never loops on
    a single word longer than `width` -- `textwrap` breaks it rather than refusing to place it."""
    collapsed = " ".join(text_.split())
    if not collapsed:
        return []

    safe_width = max(1, width)
    lines = textwrap.wrap(collapsed, width=safe_width)

    if max_lines is not None and len(lines) > max_lines:
        kept = lines[:max_lines - 1]
        remaining = " ".join(lines[max_lines - 1:])
        # Leave room for the ellipsis character itself so the truncated line still fits width.
        avail = max(1, safe_width - 1)
        last_wrapped = textwrap.wrap(remaining, width=avail)
        last_line = (last_wrapped[0] if last_wrapped else "") + "…"
        lines = kept + [last_line]

    return [f"{indent}{line}" for line in lines]


def table(rows, headers=None, aligns=None, indent="  ", gap=2):
    """Aligned monospace columns as a list of lines. Column width is the widest cell in that
    column (header included), measured via `display_width` so icon glyphs and CJK text don't
    shift columns. `aligns` is a per-column "l"/"r" list, defaulting to all-left; missing entries
    default to "l". The last column is never padded, so no line carries trailing whitespace. A
    short row is padded with empty cells rather than raising. An empty `rows` list returns []
    even when `headers` is given -- a lone header with no data is never emitted."""
    if not rows:
        return []

    all_rows = ([headers] if headers else []) + list(rows)
    ncols = max(len(r) for r in all_rows)
    padded_rows = [list(r) + [""] * (ncols - len(r)) for r in all_rows]

    aligns = list(aligns or [])
    aligns = aligns + ["l"] * (ncols - len(aligns))

    widths = [
        max(display_width(row[c]) for row in padded_rows)
        for c in range(ncols)
    ]

    gap_str = " " * gap
    lines = []
    for row in padded_rows:
        cells = []
        for c, cell in enumerate(row):
            if c == ncols - 1:
                cells.append(cell)
                continue
            pad = " " * (widths[c] - display_width(cell))
            cells.append(pad + cell if aligns[c] == "r" else cell + pad)
        lines.append(indent + gap_str.join(cells))
    return lines


def display_width(s):
    """Terminal display width: `unicodedata.east_asian_width` "W"/"F" count as 2 columns,
    everything else as 1, so a status icon or a CJK character does not shift a table column."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def parse_batch_name(name):
    """`{"number", "date", "slug"}` for a numbered batch directory name (`<digits>-<YYYY-MM-DD>-
    <slug>`); `{"number": None, "date": None, "slug": name}` for a legacy unnumbered one or any
    name that does not satisfy the grammar."""
    m = _NUMBERED_RE.match(name)
    if not m:
        return {"number": None, "date": None, "slug": name}
    return {"number": int(m.group(1)), "date": m.group(2), "slug": m.group(3)}
