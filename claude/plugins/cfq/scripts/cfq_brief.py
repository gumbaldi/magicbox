#!/usr/bin/env python3
# Usage: cfq_brief.py <batch-dir> [--phase <NN> [--classic-fallback]|--with-done|--overview|--review [--phases NN,...|--changed]]
"""Prints the flat batch listing the dashboard's next-batch expansion shows (default mode), or (with
--phase <NN>) a single-phase announcement block (title, goal, files, the first 10 numbered
`## Changes` steps at two lines each, check command), or (with --with-done) the same flat listing
with done phases listed first, ticked, and skipped ones after them, or (with --overview) the aligned-monospace batch-overview
block (header, phase count/done/error/skipped line, the untruncated labelled `.batch-context.md` block, the
phase table interleaved with each phase's own `## Context` excerpt and a `-> <file>` pointer, and
closing `Plans` and (report portal on) `Portal` lines) shown at `ifq`'s start gate, or (with --review [--phases NN,...]) the untruncated Plan-Mode digest: the whole batch
context, and per phase its whole `## Context`, files, top-level `## Changes` steps, verification
command and phase-file path; --review --changed prints only what changed since the `.review`
snapshot `cfq batch review` took (read-only, never refreshes it). Batch mode (default and --with-done) prints an optional
`goal:` line right after the header, read from `.batch-context.md`'s `## Goal`; --phase mode never
does, since it is the per-phase announcement. Read-only except for its own exit code: --phase
refuses (MODE_MISMATCH, exit 2) when the owning repo has orchestratorMode on, unless
--classic-fallback is passed -- the deterministic half of the classic/orchestrator mode gate, see
references/orchestrator.md section 6.

Ported from cfq-brief.sh -- a port, not a redesign: the CLI contract (argument order, text
output, exit codes) is the invariant this file preserves. The output is read by an agent, so
every blank line and indent is part of the contract.
"""

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import paths as cfq_paths  # noqa: E402
from cfq_lib import phase_state  # noqa: E402
from cfq_lib import proc as cfq_proc  # noqa: E402
from cfq_lib import queue as cfq_queue  # noqa: E402
from cfq_lib import text as cfq_text  # noqa: E402

PROG = "cfq_brief.py"

TITLE_PREFIX_RE = re.compile(r"^# +")


def parse_phase_body(text, fallback_title=None):
    """Pulls the first `# ` heading (title), the token on the first non-empty line after `##
    Size`, the lower-cased first token after an optional `## Model` (same capture rule as `##
    Size`, `None` when absent or empty), the first two non-empty lines after `## Context` (raw, untruncated), the last path
    segment of each `- \\`...\\`` bullet under `## Affected Files`, and the first non-empty line
    inside the first fenced code block under `## Verification`. Both the `## Size` token capture
    and the `## Context` capture (up to two non-empty lines) stop at the next `## ` heading,
    whichever comes first -- a `## Size` with no
    token before the next heading leaves `size` as `None` (callers already render that as `M`),
    and a `## Context` with fewer than two non-empty lines before the next heading leaves
    `context` covering only what it actually captured. `summary` is the non-empty lines of `##
    Summary` (each stripped, joined with single spaces), `""` when the section is missing or empty.

    A hand-edited phase file that lost its `# ` heading (or never had one) returns `title:
    fallback_title` instead of `title: None` -- callers pass the phase file's own stem (`NN-slug`)
    so a missing title degrades to something legible rather than crashing a downstream renderer.
    `title` stays `None` only when both the heading and `fallback_title` are missing, for the rare
    caller that doesn't pass one."""
    title = None
    size = None
    model = None
    m = False
    g = False
    context_lines = []
    k = False
    af = False
    vf = False
    incode = False
    check = None
    files = []

    for line in text.split("\n"):
        non_empty = bool(line.strip())

        if title is None and line.startswith("# "):
            title = TITLE_PREFIX_RE.sub("", line, count=1)
            continue
        if line.startswith("## "):
            g = False
            k = False
            m = False
        if line.startswith("## Model"):
            m = True
            continue
        if m and non_empty:
            model = line.split()[0].lower()
            m = False
            continue
        if line.startswith("## Size"):
            g = True
            continue
        if g and non_empty:
            size = line.split()[0]
            g = False
            continue
        if line.startswith("## Context"):
            k = True
            continue
        if k and non_empty:
            context_lines.append(line)
            if len(context_lines) >= 2:
                k = False
            continue
        if line.startswith("## Affected Files"):
            af = True
            continue
        if line.startswith("## Verification"):
            af = False
            vf = True
            continue
        if line.startswith("## "):
            af = False
            vf = False
            continue
        if af and line.startswith("- `"):
            p = line[3:].split("`", 1)[0]
            files.append(p.split("/")[-1])
            continue
        if vf and line.startswith("```"):
            incode = not incode
            continue
        if vf and incode and non_empty and check is None:
            check = line

    context = "".join(f"{line} " for line in context_lines)
    return {
        "title": title or fallback_title, "size": size, "model": model, "context": context, "files": files,
        "check": check, "steps": changes_steps(text),
        "summary": " ".join(l.strip() for l in _section_lines(text, "Summary") if l.strip()),
    }


MAX_ANNOUNCED_STEPS = 10


def render_phase(num, fields, model_applies=True):
    head = f"PHASE {num} · {fields['title']} · Size {fields['size'] or 'M'}"
    if fields.get("model"):
        head += f" · Model {fields['model']}"
        if not model_applies:
            head += " (not applied: classic mode)"
    lines = [head]
    summary = fields.get("summary")
    goal_lines = cfq_text.wrap(summary or fields["context"], width=68, max_lines=6 if summary else 4)
    for i, line in enumerate(goal_lines):
        prefix = "  Goal     " if i == 0 else " " * 11
        lines.append(f"{prefix}{line}")
    if fields["files"]:
        lines.append(f"  Files    {', '.join(fields['files'])}")
    steps = fields["steps"]
    for i, step in enumerate(steps[:MAX_ANNOUNCED_STEPS], 1):
        prefix = f"{i}. "
        wrapped = cfq_text.wrap(step["lead"], width=62, max_lines=2) or [""]
        for j, w in enumerate(wrapped):
            if j == 0:
                head = "  Steps    " if i == 1 else " " * 11
                lines.append(f"{head}{prefix}{w}")
            else:
                lines.append(" " * 14 + w)
    extra = len(steps) - MAX_ANNOUNCED_STEPS
    if extra > 0:
        lines.append(f"           … +{extra} more step{'s' if extra != 1 else ''}")
    if fields["check"]:
        lines.append(f"  Check    {fields['check']}")
    return "\n".join(lines)


def render_brief(num, fields):
    goal = (fields.get("summary") or fields["context"])[:220]
    return f"{num}  {fields['title']}  [{fields['size'] or 'M'}]  {goal}"


def phase_num(path):
    name = path.name
    return name[:2] if len(name) >= 3 and name[2] == "-" and name[:2].isdigit() else None


def _phase_groups(d):
    """The batch's phases that have a plan file, from status.json (never from where a file lies),
    as `(done, skipped, pending)` lists of phase_state records, each ascending by number. Exits 1
    with the status error when status.json is missing or unreadable."""
    try:
        records = phase_state.phases(d)
    except phase_state.PhaseStateError as e:
        print(f"{PROG}: {e.message}", file=sys.stderr)
        sys.exit(1)
    records = [r for r in records if r["path"] is not None]
    return (
        [r for r in records if r["status"] == "done"],
        [r for r in records if r["status"] == "skipped"],
        [r for r in records if r["status"] in phase_state.PENDING],
    )


def _overview_header(d):
    """`BATCH <number> · <date> · <slug>` for a numbered batch, `BATCH <slug>` alone for a
    legacy unnumbered one -- never a literal `None` in either case. The numeric prefix is read
    straight off the directory name rather than re-formatted from `parse_batch_name`'s `int`, so
    a leading zero survives without this module reimplementing `cfq_batch_id.py`'s
    `numbered_width`."""
    parsed = cfq_text.parse_batch_name(d.name)
    if parsed["number"] is None:
        return f"BATCH {parsed['slug']}"
    number = d.name.split("-", 1)[0]
    return f"BATCH {number} · {parsed['date']} · {parsed['slug']}"


def _overview_rows(d):
    """Table rows, each phase's own `## Context` excerpt and file pointer (`<name>`,
    `done/<name>` or `skipped/<name>`) as parallel lists in the same order, plus the
    done/skipped/error counts feeding the count line. Done phases sort first, then skipped ones,
    then pending ones, each group ascending by number. The status column is the phase's own
    status.json state: `done`, `skipped`, `error` or `open`."""
    done, skipped, pending = _phase_groups(d)

    rows = []
    contexts = []
    pointers = []
    for r in done + skipped + pending:
        f = r["path"]
        fields = parse_phase_body(f.read_text(), fallback_title=f.stem)
        size = fields["size"] or "M"
        if fields["model"]:
            size = f"{size} · {fields['model']}"
        rows.append([r["num"], fields["title"], size, r["status"]])
        contexts.append(fields["context"])
        pointers.append(str(f.relative_to(d)))

    error_n = sum(1 for r in pending if r["status"] == "error")
    return rows, contexts, len(done), len(skipped), error_n, pointers


def _count_line(done_n, skipped_n, error_n, total_n):
    line = f"{total_n} phases planned · {done_n} done"
    if error_n:
        line += f" · {error_n} error"
    if skipped_n:
        line += f" · {skipped_n} skipped"
    return line


def render_overview(d):
    rows, contexts, done_n, skipped_n, error_n, pointers = _overview_rows(d)
    lines = [_overview_header(d), _count_line(done_n, skipped_n, error_n, len(rows))]

    ctx = render_context_block(d)
    if ctx:
        lines.append("")
        lines.extend(ctx)
        lines.append("")

    table_lines = cfq_text.table(
        rows, headers=["#", "Phase", "Size", "Status"], aligns=["l", "l", "l", "l"],
    )
    if table_lines:
        lines.append(table_lines[0])
        for line, excerpt, pointer in zip(table_lines[1:], contexts, pointers):
            lines.append(line)
            lines.extend(cfq_text.wrap(excerpt, width=66, indent="      ", max_lines=2))
            lines.append(f"      → {pointer}")

    lines.append("")
    lines.append(f"  Plans    {d.resolve()}")
    portal = _portal_line(d)
    if portal is not None:
        lines.append(portal)

    return "\n".join(lines)


def _repo_root_from_batch_dir(batch_dir):
    """Walks up from <repo>/.claude/cfq/impl/<batch> until a parent whose own path ends in
    cfq_lib.paths.QUEUE_DIR_COMPONENTS (i.e. the parent itself is <repo>/.claude/cfq) is found,
    then strips those same components back off to return <repo>. None when no such parent exists
    (batch_dir isn't under a recognisable queue layout) -- callers treat that as "no gate", never
    a failure."""
    resolved = batch_dir.resolve()
    n = len(cfq_paths.QUEUE_DIR_COMPONENTS)
    for ancestor in resolved.parents:
        if ancestor.parts[-n:] == cfq_paths.QUEUE_DIR_COMPONENTS:
            return pathlib.Path(*ancestor.parts[:-n])
    return None


STEP_RE = re.compile(r"^\d+\. +")
BULLET_RE = re.compile(r"^[-*] +")
NESTED_ITEM_RE = re.compile(r"^\s+([-*]|\d+\.) ")


def _section_lines(text, heading):
    """Raw lines under `## <heading>` up to the next `## ` heading ([] when absent)."""
    out = []
    inside = False
    for line in text.split("\n"):
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip() == f"## {heading}"
            continue
        if inside:
            out.append(line)
    return out


def _is_fence(line):
    return line.lstrip().startswith("```")


def has_numbered_steps(text):
    """True when `## Changes` holds at least one column-0 `N. ` line outside a fence; the
    bullet fallback of `changes_steps` does not count."""
    fenced = False
    for line in _section_lines(text, "Changes"):
        if _is_fence(line):
            fenced = not fenced
            continue
        if not fenced and STEP_RE.match(line):
            return True
    return False


def changes_steps(text):
    """The top-level steps of `## Changes` as `[{"lead": str, "details": int}, ...]` -- a step
    is a column-0 `N. ` line outside a fence (column-0 `- `/`* ` lines when the section has no
    numbered line at all); its lead is that line's text plus directly following indented
    continuation lines, its details the nested list items and fenced blocks up to the next step.
    [] when no step exists."""
    lines = _section_lines(text, "Changes")
    marker = STEP_RE if has_numbered_steps(text) else BULLET_RE
    steps = []
    fenced = False
    in_lead = False
    for line in lines:
        opener = _is_fence(line)
        if fenced or opener:
            if opener:
                fenced = not fenced
                if fenced and steps:
                    steps[-1]["details"] += 1
            in_lead = False
            continue
        m = marker.match(line)
        if m:
            steps.append({"lead": line[m.end():].strip(), "details": 0})
            in_lead = True
            continue
        if not steps:
            continue
        if in_lead and line.strip() and line[0] in " \t" and not NESTED_ITEM_RE.match(line):
            steps[-1]["lead"] += " " + line.strip()
            continue
        in_lead = False
        if NESTED_ITEM_RE.match(line):
            steps[-1]["details"] += 1
    return steps


def changes_fallback(text):
    """First paragraph of `## Changes` joined by spaces, "" when empty or absent."""
    para = []
    for line in _section_lines(text, "Changes"):
        if line.strip():
            para.append(line.strip())
        elif para:
            break
    return " ".join(para)


def _render_md_blocks(lines, indent, para_gap):
    """Raw Markdown lines as wrapped blocks: a column-0 `- ` line plus its indented continuation
    is one bullet (continuation lines at `indent` + 2 spaces), consecutive other non-blank lines
    one paragraph. Never truncates; width stays within 72 columns."""
    blocks = []
    cur = None
    for line in lines:
        if not line.strip():
            cur = None
            continue
        if line.startswith("- "):
            cur = ["bullet", [line[2:].strip()]]
            blocks.append(cur)
        elif cur is not None and cur[0] == "bullet" and line[0] in " \t":
            cur[1].append(line.strip())
        elif cur is not None and cur[0] == "para":
            cur[1].append(line.strip())
        else:
            cur = ["para", [line.strip()]]
            blocks.append(cur)
    out = []
    for kind, parts in blocks:
        if para_gap and out:
            out.append("")
        text = " ".join(parts)
        if kind == "bullet":
            wrapped = cfq_text.wrap(text, width=72 - len(indent) - 2)
            for i, w in enumerate(wrapped):
                out.append(f"{indent}- {w}" if i == 0 else f"{indent}  {w}")
        else:
            out.extend(cfq_text.wrap(text, width=72 - len(indent), indent=indent))
    return out


REVIEW_SECTIONS = ("Goal", "Decisions", "Invariants", "Cross-Phase Contracts", "Non-Goals")


def render_context_block(d):
    out = []
    for heading in REVIEW_SECTIONS:
        lines = cfq_queue.read_section_lines(d, heading)
        if lines:
            out.append(f"  {heading}")
            out.extend(_render_md_blocks(lines, "    ", para_gap=False))
    return out


def parse_phase_review(text, fallback_title):
    fields = parse_phase_body(text, fallback_title=fallback_title)
    context_lines = _section_lines(text, "Context")
    while context_lines and not context_lines[0].strip():
        context_lines.pop(0)
    while context_lines and not context_lines[-1].strip():
        context_lines.pop()
    summary_lines = _section_lines(text, "Summary")
    while summary_lines and not summary_lines[0].strip():
        summary_lines.pop(0)
    while summary_lines and not summary_lines[-1].strip():
        summary_lines.pop()
    files = []
    for line in _section_lines(text, "Affected Files"):
        if line.startswith("- `"):
            path, _, rest = line[3:].partition("`")
            files.append((path, rest.strip()))
    return {
        "title": fields["title"], "size": fields["size"], "check": fields["check"],
        "context_lines": context_lines, "summary_lines": summary_lines, "files": files,
        "steps": changes_steps(text), "fallback": changes_fallback(text),
    }


def _display_path(path, repo_root):
    p = pathlib.Path(path)
    if repo_root is not None:
        try:
            return str(p.relative_to(repo_root))
        except ValueError:
            pass
    return str(path)


def render_review_phase(num, fields, phase_path, repo_root, state=""):
    head = f"PHASE {num} · {fields['title']} · Size {fields['size'] or 'M'}"
    lines = [head + (f" · {state}" if state else "")]

    summary = _render_md_blocks(fields["summary_lines"], "    ", para_gap=True)
    if summary:
        lines.append("  Summary")
        lines.extend(summary)
    else:
        ctx = _render_md_blocks(fields["context_lines"], "    ", para_gap=True)
        if ctx:
            lines.append("  Context")
            lines.extend(ctx)

    if fields["files"]:
        lines.append("  Files")
        for path, marker in fields["files"]:
            shown = _display_path(path, repo_root)
            lines.append(f"    {shown} {marker}" if marker else f"    {shown}")

    if fields["steps"]:
        lines.append("  Changes")
        for i, step in enumerate(fields["steps"], 1):
            prefix = f"    {i}. "
            wrapped = cfq_text.wrap(step["lead"], width=64, max_lines=3) or [""]
            n = step["details"]
            if n:
                wrapped[-1] = (wrapped[-1] + f" (+{n} detail{'s' if n != 1 else ''})").lstrip()
            for j, w in enumerate(wrapped):
                lines.append(prefix + w if j == 0 else " " * len(prefix) + w)
    elif fields["fallback"]:
        lines.append("  Changes")
        lines.extend(cfq_text.wrap(fields["fallback"], width=68, indent="    ", max_lines=6))

    if fields["check"]:
        lines.append(f"  Verify   {fields['check']}")
    lines.append(f"  Edit     {_display_path(phase_path.resolve(), repo_root)}")
    return lines


def _portal_line(d):
    """`  Portal   <url>` when the batch sits in a queue layout and `htmlReport` is on, else None."""
    repo = _repo_root_from_batch_dir(d)
    if repo is None or cfq_proc.settings_get(repo, "htmlReport") != "true":
        return None
    return f"  Portal   {cfq_paths.portal_batch_url(repo, d.name)}"


def render_review(d, only=None):
    repo_root = _repo_root_from_batch_dir(d)
    done, skipped, pending = _phase_groups(d)
    entries = [
        (r["path"], "" if r["status"] in phase_state.PENDING else r["status"])
        for r in done + skipped + pending
    ]

    if only is not None:
        known = {phase_num(f) for f, _ in entries}
        for n in only:
            if n not in known:
                print(f"{PROG}: no phase {n} in {d}", file=sys.stderr)
                sys.exit(1)
        entries = [(f, state) for f, state in entries if phase_num(f) in only]

    blocks = []
    for f, state in entries:
        fields = parse_phase_review(f.read_text(), f.stem)
        blocks.append(render_review_phase(phase_num(f), fields, f, repo_root, state))
    if only is not None:
        return "\n\n".join("\n".join(b) for b in blocks)

    rows, _, done_n, skipped_n, error_n, _ = _overview_rows(d)
    sections = [[_overview_header(d), _count_line(done_n, skipped_n, error_n, len(rows))]]
    ctx = render_context_block(d)
    if ctx:
        sections.append(ctx)
    sections.extend(blocks)
    footer = [f"  Plans    {d.resolve()}"]
    if (d / ".batch-context.md").is_file():
        footer.append(f"  Context  {d.resolve()}/.batch-context.md")
    portal = _portal_line(d)
    if portal is not None:
        footer.append(portal)
    sections.append(footer)
    return "\n\n".join("\n".join(s) for s in sections)


def render_review_changed(d):
    """The part of the digest that changed since `cfq batch review` last snapshotted the batch:
    phase files whose hash differs or that are new, `.batch-context.md` when it changed, and a
    `Removed` line per file the snapshot knew that is gone. Read-only."""
    marker = cfq_queue.read_review(d)
    if marker is None:
        print(f"{PROG}: no review snapshot in {d} -- run 'cfq batch review' first", file=sys.stderr)
        sys.exit(1)
    old = marker.get("files") if isinstance(marker.get("files"), dict) else {}
    new = cfq_queue.review_snapshot(d)
    changed = sorted(n for n in new if old.get(n) != new[n])
    removed = sorted(n for n in old if n not in new)
    if not changed and not removed:
        return "no changes since last review"

    repo_root = _repo_root_from_batch_dir(d)
    phase_names = [n for n in changed if n != ".batch-context.md"]
    sections = [[_overview_header(d), f"{len(phase_names) + len(removed)} changed since last review"]]
    if ".batch-context.md" in changed:
        ctx = render_context_block(d)
        if ctx:
            sections.append(ctx)
    for name in phase_names:
        f = d / name
        fields = parse_phase_review(f.read_text(), f.stem)
        sections.append(render_review_phase(phase_num(f), fields, f, repo_root))
    if removed:
        sections.append([f"  Removed  {n}" for n in removed])
    return "\n\n".join("\n".join(sec) for sec in sections)


def _check_orchestrator_gate(batch_dir):
    """The classic-mode phase announcement (`brief --phase`) refuses to run while orchestratorMode
    is on for the owning repo -- the one deterministic point where a session that skipped the
    prose branch in implement-for-queue/SKILL.md's Batch Briefing can still be caught before any code is
    written. Fail-open, same spirit as cfq_guard.py: an unresolvable repo root, a non-zero
    `settings get` exit, or unparsable output all mean "no gate", never a crash."""
    repo = _repo_root_from_batch_dir(batch_dir)
    if repo is None:
        return
    result = cfq_proc.cfq_run("settings", "get", "--repo", str(repo), "orchestratorMode")
    if result.returncode != 0:
        return
    if result.stdout.strip() != "true":
        return
    print(
        f"{PROG}: MODE_MISMATCH orchestrator mode is on for {repo} — spawn a cfq-phase-worker via "
        "'bin/cfq worker brief', or pass --classic-fallback for the documented spawn-failure "
        "fallback.",
        file=sys.stderr,
    )
    sys.exit(2)


def cmd_brief(args):
    d = pathlib.Path(str(args.batch_dir).rstrip("/"))
    if not d.is_dir():
        print(f"{PROG}: no such batch directory: {d}", file=sys.stderr)
        sys.exit(1)

    if args.phase is not None and not args.classic_fallback:
        _check_orchestrator_gate(d)

    if args.phase is not None:
        try:
            f = phase_state.locate(d, phase_state.resolve_slug(d, args.phase))
        except phase_state.PhaseStateError as e:
            f = None
            if e.code != "UNKNOWN_PHASE":
                print(f"{PROG}: {e.message}", file=sys.stderr)
                sys.exit(1)
        if f is None:
            print(f"{PROG}: no phase {args.phase} in {d}", file=sys.stderr)
            sys.exit(1)
        fields = parse_phase_body(f.read_text(), fallback_title=f.stem)
        print(render_phase(phase_num(f), fields, model_applies=False))
        return

    if args.overview:
        print(render_overview(d))
        return

    if args.review and args.changed:
        print(render_review_changed(d))
        return

    if args.review:
        only = [n.strip() for n in args.phases.split(",") if n.strip()] if args.phases else None
        print(render_review(d, only))
        return

    name = d.name
    priority_file = d / ".priority"
    priority = priority_file.read_text().strip() if priority_file.is_file() else ""

    done, skipped, pending = _phase_groups(d)
    files = [r["path"] for r in pending]
    if priority == "high":
        print(f"{name}  priority=high  phases={len(files)}")
    else:
        print(f"{name}  phases={len(files)}")

    goal = cfq_queue.read_goal(d, 300)
    if goal is not None:
        print(f"goal: {goal}")

    depends_file = d / ".dependsOn"
    if depends_file.is_file():
        for dep in depends_file.read_text().splitlines():
            if dep:
                print(f"dependsOn: {dep}")

    if args.with_done:
        for prefix, group in (("✔", done), ("➖", skipped)):
            for r in group:
                f = r["path"]
                print(f"{prefix} {render_brief(phase_num(f), parse_phase_body(f.read_text(), fallback_title=f.stem))}")

    for f in files:
        print(render_brief(phase_num(f), parse_phase_body(f.read_text(), fallback_title=f.stem)))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    parser.add_argument("batch_dir")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--phase")
    group.add_argument("--with-done", action="store_true")
    group.add_argument("--overview", action="store_true")
    group.add_argument("--review", action="store_true")
    parser.add_argument("--phases")
    parser.add_argument("--changed", action="store_true")
    parser.add_argument("--classic-fallback", action="store_true")
    parser.set_defaults(func=cmd_brief)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.phases is not None and not args.review:
        parser.error("--phases requires --review")
    if args.changed and not args.review:
        parser.error("--changed requires --review")
    if args.changed and args.phases is not None:
        parser.error("--changed cannot be combined with --phases")
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
