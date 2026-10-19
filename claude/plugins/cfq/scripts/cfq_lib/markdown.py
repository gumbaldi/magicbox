"""A small Markdown subset renderer, shared by `cfq_report.py`'s Overview section and
`cfq_portal.py`'s pre-rendered phase-file / plan-inbox / todo-card bodies -- the one renderer
both callers use rather than growing a second, drifting one (see CLAUDE.md's "No duplicate
renderers" invariant).

Not a general Markdown renderer. Supported: headings (`##` -> h3, `###` -> h4, deeper -> h5),
bullet and ordered lists nested up to three levels (a deeper level is folded into the third),
paragraphs, fenced code blocks (a language tag is ignored), indented code blocks, block quotes,
pipe tables with a separator row, horizontal rules (`---`), a `check: <command>` line, and the
inline forms `**bold**`, `*emphasis*` and `` `code` ``. Not supported, on purpose: links and
autolinks (no queue file uses them), images, HTML pass-through (all of it is escaped), setext
headings, reference definitions, task lists. Anything unsupported falls through to paragraph text.

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


_INLINE_RE = re.compile(
    r"`([^`]*)`"
    r"|\*\*([^*]*?)\*\*"
    # emphasis: the opening * is not followed by whitespace, the closing one not preceded by it,
    # neither touches a word character (so `2*3*4` and `*.md and *.js` stay literal), and the
    # span never crosses a backtick (a code span inside is not split)
    r"|(?<![\w*])\*(?![\s*])([^*`]*?[^\s*`])\*(?![\w*])"
)


def md_inline(escaped_text):
    """Operates on text that has already been through `esc`/`html_escape_jq`. One pass, one
    regex: inline code, bold and emphasis are matched as alternatives at each position so a `**`
    or `*` inside a backtick span is consumed as part of the code match and never seen by the
    other alternatives -- doing this as sequential substitutions would let a later pass reach back
    inside an already-emitted `<code>` span."""
    def repl(m):
        if m.group(1) is not None:
            return f"<code>{m.group(1)}</code>"
        if m.group(2) is not None:
            return f"<strong>{m.group(2)}</strong>"
        return f"<em>{m.group(3)}</em>"
    return _INLINE_RE.sub(repl, escaped_text)


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_ITEM_RE = re.compile(r"^(?:([-*])|(\d+\.))\s+(.*)$")
_MD_FENCE_RE = re.compile(r"^```")
_MD_HR_RE = re.compile(r"^-{3,}\s*$")
_MD_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_MD_CHECK_RE = re.compile(r"^check:\s*(.+)$")
_MD_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")
_MD_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_MAX_LIST_DEPTH = 3


def _split_indent(raw):
    """(indent in columns, rest of the line); a tab counts as four columns."""
    cols = 0
    for pos, ch in enumerate(raw):
        if ch == " ":
            cols += 1
        elif ch == "\t":
            cols += 4
        else:
            return cols, raw[pos:]
    return cols, ""


def _table_cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in _MD_CELL_SPLIT_RE.split(s)]


def _is_table_sep(line, columns):
    s = line.strip()
    return "|" in s and bool(_MD_TABLE_SEP_RE.match(s)) and len(_table_cells(s)) == columns


def _render_list(lst):
    tag = lst["kind"]
    items = "".join(
        f"<li>{it['text']}{''.join(_render_list(sub) for sub in it['sub'])}</li>"
        for it in lst["items"]
    )
    return f"<{tag}>{items}</{tag}>"


def md_min(text, keep_h1=False):
    """A line-driven state machine over `text.splitlines()`, with one line of look-ahead for a
    table's separator row. Lists nest by indentation (a deeper indent opens a child list inside
    the last item, up to three levels; tabs count as four spaces). Every emitted text value goes
    through `md_inline(esc(value))`, never raw, with two exceptions: a fenced or indented code
    block's content and a `check:` command are escaped but never inline-formatted (a
    `**`/backtick inside them is literal, not Markdown).

    `keep_h1=False` (the default, used for a `.batch-context.md` section body, which never
    contains one) drops a level-1 heading entirely, unchanged from before this renderer grew a
    second caller. `keep_h1=True` (used by `cfq_portal.py` for a whole phase file or queue entry,
    both of which open with `# Title`) renders it as `<h1>` instead."""
    lines = text.splitlines()
    parts = []
    stack = []  # open lists, outermost first: {"kind", "indent", "items": [{"text", "sub"}]}
    para_lines = []
    quote_paras = []  # finished paragraphs of the open block quote
    quote_lines = []
    in_code = False
    code_lines = []
    icode_lines = []  # an open indented code block (already escaped)
    icode_blanks = 0

    def flush_para():
        if para_lines:
            parts.append(f"<p>{md_inline(esc(' '.join(para_lines)))}</p>")
            para_lines.clear()

    def pop_list():
        lst = stack.pop()
        if not stack:
            parts.append(_render_list(lst))

    def close_list():
        while stack:
            pop_list()

    def flush_quote():
        nonlocal quote_paras
        if quote_lines:
            quote_paras.append(" ".join(quote_lines))
            quote_lines.clear()
        if quote_paras:
            inner = "".join(f"<p>{md_inline(esc(p))}</p>" for p in quote_paras)
            parts.append(f"<blockquote>{inner}</blockquote>")
            quote_paras = []

    def flush_icode():
        nonlocal icode_blanks
        if icode_lines:
            parts.append(f"<pre><code>{chr(10).join(icode_lines)}</code></pre>")
            icode_lines.clear()
        icode_blanks = 0

    def end_blocks():
        close_list()
        flush_para()
        flush_quote()
        flush_icode()

    def add_item(indent, kind, item_text):
        popped = False
        while stack and indent < stack[-1]["indent"]:
            pop_list()
            popped = True
        item = {"text": md_inline(esc(item_text.strip())), "sub": []}
        if stack and indent > stack[-1]["indent"] and not popped and len(stack) < _MAX_LIST_DEPTH:
            lst = {"kind": kind, "indent": indent, "items": [item]}
            stack[-1]["items"][-1]["sub"].append(lst)
            stack.append(lst)
            return
        if stack and (indent > stack[-1]["indent"] or stack[-1]["kind"] == kind):
            # same level (or folded in from a level deeper than the third)
            stack[-1]["items"].append(item)
            return
        if stack:
            pop_list()  # same indent, other kind: a sibling list of the other kind
        lst = {"kind": kind, "indent": indent, "items": [item]}
        if stack:
            stack[-1]["items"][-1]["sub"].append(lst)
        stack.append(lst)

    prev_blank = True
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if in_code:
            prev_blank = False
            if _MD_FENCE_RE.match(raw):
                parts.append(f"<pre><code>{chr(10).join(code_lines)}</code></pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(esc(raw))
            continue

        if _MD_FENCE_RE.match(raw):
            end_blocks()
            prev_blank = False
            in_code = True
            code_lines = []
            continue

        if raw.strip() == "":
            if icode_lines:
                icode_blanks += 1  # kept only if the code block goes on
            else:
                end_blocks()
            prev_blank = True
            continue
        after_blank = prev_blank
        prev_blank = False

        indent, body = _split_indent(raw)
        body = body.rstrip()

        if icode_lines:
            if indent >= 4:
                icode_lines.extend([""] * icode_blanks)
                icode_blanks = 0
                icode_lines.append(esc(" " * (indent - 4) + body))
                continue
            flush_icode()
        if (indent >= 4 and after_blank and not stack and not para_lines
                and not quote_lines and not quote_paras):
            icode_lines.append(esc(" " * (indent - 4) + body))
            continue

        top = indent == 0 or not stack  # a line that can start a new block
        m = _MD_HEADING_RE.match(raw) if indent == 0 else None
        if m:
            end_blocks()
            level = len(m.group(1))
            if level == 1:
                if keep_h1:
                    parts.append(f"<h1>{md_inline(esc(m.group(2).strip()))}</h1>")
                continue  # the document title, not content -- dropped unless keep_h1
            tag = {2: "h3", 3: "h4"}.get(level, "h5")
            parts.append(f"<{tag}>{md_inline(esc(m.group(2).strip()))}</{tag}>")
            continue
        if top and indent < 4 and _MD_HR_RE.match(body):
            end_blocks()
            parts.append("<hr>")
            continue
        m = _MD_QUOTE_RE.match(body) if top and indent < 4 else None
        if m:
            close_list()
            flush_para()
            if m.group(1).strip():
                quote_lines.append(m.group(1).strip())
            elif quote_lines:  # an empty `>` line separates paragraphs inside the quote
                quote_paras.append(" ".join(quote_lines))
                quote_lines.clear()
            continue
        if top and indent < 4 and "|" in body and i < len(lines):
            header = _table_cells(body)
            if _is_table_sep(lines[i], len(header)):
                end_blocks()
                i += 1
                rows = []
                while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                    cells = _table_cells(lines[i])[:len(header)]
                    rows.append(cells + [""] * (len(header) - len(cells)))
                    i += 1
                thead = "".join(f"<th>{md_inline(esc(c))}</th>" for c in header)
                html = f"<table><thead><tr>{thead}</tr></thead>"
                if rows:
                    trs = "".join(
                        "<tr>" + "".join(f"<td>{md_inline(esc(c))}</td>" for c in row) + "</tr>"
                        for row in rows
                    )
                    html += f"<tbody>{trs}</tbody>"
                parts.append(html + "</table>")
                continue
        m = _MD_ITEM_RE.match(body)
        if m:
            flush_para()
            flush_quote()
            add_item(indent, "ul" if m.group(1) else "ol", m.group(3))
            continue
        if stack and indent > 0:
            # an indented continuation line joins the last item of the innermost open list
            item = stack[-1]["items"][-1]
            item["text"] += " " + md_inline(esc(body.strip()))
            continue
        close_list()
        flush_quote()
        m = _MD_CHECK_RE.match(body)
        if m and indent == 0:
            flush_para()
            cmd = esc(m.group(1).strip())
            parts.append(f'<p class="check"><span>check</span><code>{cmd}</code></p>')
            continue
        para_lines.append(body.strip())

    if in_code:
        # An unterminated fence still renders what it collected -- content is never dropped for
        # a source file that forgot its closing ``` .
        parts.append(f"<pre><code>{chr(10).join(code_lines)}</code></pre>")
    end_blocks()
    return "".join(parts)
