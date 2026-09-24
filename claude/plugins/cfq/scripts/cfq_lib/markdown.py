"""A small Markdown subset renderer, shared by `cfq_report.py`'s Overview section and
`cfq_portal.py`'s pre-rendered phase-file / plan-inbox / todo-card bodies -- the one renderer
both callers use rather than growing a second, drifting one (see CLAUDE.md's "No duplicate
renderers" invariant).

Not a general Markdown renderer: headings, one level of bullets, one level of ordered items,
paragraphs, fenced code blocks, `**bold**` and `` `code` `` only. Everything else (blockquotes,
tables, links, nested lists) falls through to paragraph text on purpose, since neither caller's
own source format (`.batch-context.md`, a phase plan file, a `plan/`/`todo/` queue entry) ever
uses them.

`esc`/`html_escape_jq` moved here alongside `md_min`/`md_inline` (not named in the phase plan's
own move, but required by both -- there is nowhere else for it to live without a circular import,
since `cfq_report.py` imports from here, not the other way round). `cfq_report.py` imports all
four names back and keeps calling them unqualified, so every existing call site there is
unchanged.
"""

import re

from . import render

_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&apos;", '"': "&quot;"}


def html_escape_jq(s):
    return "".join(_HTML_ESCAPES.get(ch, ch) for ch in s)


def esc(value):
    """Mirrors the shell script's `def esc: (. // "") | tostring | @html;`."""
    return html_escape_jq(render.tostring(render.jq_alt(value, "")))


_INLINE_RE = re.compile(r"`([^`]*)`|\*\*([^*]*?)\*\*")


def md_inline(escaped_text):
    """Operates on text that has already been through `esc`/`html_escape_jq`. One pass, one
    regex: inline code and bold are matched as alternatives at each position so a `**` inside a
    backtick span is consumed as part of the code match and never seen by the bold alternative --
    doing this as two sequential substitutions would let a later bold pass reach back inside an
    already-emitted `<code>` span."""
    def repl(m):
        if m.group(1) is not None:
            return f"<code>{m.group(1)}</code>"
        return f"<strong>{m.group(2)}</strong>"
    return _INLINE_RE.sub(repl, escaped_text)


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_MD_ORDERED_RE = re.compile(r"^\d+\.\s+(.*)$")
_MD_FENCE_RE = re.compile(r"^```")


def md_min(text, keep_h1=False):
    """A line-driven state machine over `text.splitlines()`. No nesting, no look-ahead -- nested
    bullets are deliberately flattened to one level, matching every source format this renders.
    Every emitted text value goes through `md_inline(esc(value))`, never raw, with one exception:
    a fenced code block's content is escaped but never inline-formatted (a `**`/backtick inside a
    code fence is literal, not Markdown).

    `keep_h1=False` (the default, used for a `.batch-context.md` section body, which never
    contains one) drops a level-1 heading entirely, unchanged from before this renderer grew a
    second caller. `keep_h1=True` (used by `cfq_portal.py` for a whole phase file or queue entry,
    both of which open with `# Title`) renders it as `<h1>` instead."""
    parts = []
    in_list = False
    list_kind = None
    list_items = []
    para_lines = []
    in_code = False
    code_lines = []

    def flush_para():
        if para_lines:
            parts.append(f"<p>{md_inline(esc(' '.join(para_lines)))}</p>")
            para_lines.clear()

    def close_list():
        nonlocal in_list, list_kind
        if in_list:
            lis = "".join(f"<li>{it}</li>" for it in list_items)
            parts.append(f"<{list_kind}>{lis}</{list_kind}>")
            in_list = False
            list_kind = None
            list_items.clear()

    def open_list(kind):
        nonlocal in_list, list_kind
        if not in_list or list_kind != kind:
            close_list()
        in_list = True
        list_kind = kind

    for raw in text.splitlines():
        if in_code:
            if _MD_FENCE_RE.match(raw):
                parts.append(f"<pre><code>{chr(10).join(code_lines)}</code></pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(esc(raw))
            continue

        if _MD_FENCE_RE.match(raw):
            close_list()
            flush_para()
            in_code = True
            code_lines = []
            continue

        if raw.strip() == "":
            close_list()
            flush_para()
            continue
        m = _MD_HEADING_RE.match(raw)
        if m:
            close_list()
            flush_para()
            level = len(m.group(1))
            if level == 1:
                if keep_h1:
                    parts.append(f"<h1>{md_inline(esc(m.group(2).strip()))}</h1>")
                continue  # the document title, not content -- dropped unless keep_h1
            tag = "h3" if level == 2 else "h4"
            parts.append(f"<{tag}>{md_inline(esc(m.group(2).strip()))}</{tag}>")
            continue
        m = _MD_BULLET_RE.match(raw)
        if m:
            flush_para()
            open_list("ul")
            list_items.append(md_inline(esc(m.group(1).strip())))
            continue
        m = _MD_ORDERED_RE.match(raw)
        if m:
            flush_para()
            open_list("ol")
            list_items.append(md_inline(esc(m.group(1).strip())))
            continue
        if in_list and list_items and raw[:1] in (" ", "\t"):
            list_items[-1] += " " + md_inline(esc(raw.strip()))
            continue
        para_lines.append(raw.strip())

    if in_code:
        # An unterminated fence still renders what it collected -- content is never dropped for
        # a source file that forgot its closing ``` .
        parts.append(f"<pre><code>{chr(10).join(code_lines)}</code></pre>")
    close_list()
    flush_para()
    return "".join(parts)
