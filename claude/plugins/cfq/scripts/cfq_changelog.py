#!/usr/bin/env python3
# Usage: cfq_changelog.py init            <repo-root> <branch> <base> <batch>
#        cfq_changelog.py finish          <repo-root> <branch> <batch-dir>
#        cfq_changelog.py reserve         <repo-root> <batchNumber> <batch>
#        cfq_changelog.py rename-batch    <repo-root> <old-batch> <new-batch>
#        cfq_changelog.py branch-for      <repo-root> <batch>
#        cfq_changelog.py commit-message  <repo-root> <batch> <phase> <status> <message-file>
#        cfq_changelog.py commit          <repo-root> <message>
#        cfq_changelog.py ensure          <repo-root>
#        cfq_changelog.py max-batch-number <repo-root>
#        cfq_changelog.py normalize       <repo-root>
"""Prepends/completes entries in <repo-root>/<changelogFile>, one block per batch.

File order is newest first: every new block goes on top (below any leading comment lines), and
every writing verb first runs `normalize_file`, an idempotent reorder of a file written in the old
oldest-first order (numbered blocks descending, then unnumbered ones by date descending) that also
strips the obsolete `  legacy:` lines.

Ported from cfq-changelog.sh -- a port, not a redesign: the CLI contract (verbs, argument order,
file format, exit codes) is the invariant this file preserves. No YAML library is used on purpose:
a general parser would round-trip the file through its own emitter and destroy comments, field
order and layout, all of which this format relies on (batchNumber is always immediately followed
by batch, read positionally by cfq_batch_id-style tooling). Line-oriented parsing with `re`/plain
string ops is what preserves the file untouched outside the lines actually being written.

Version-free schema: no batch ever carries a version/appVersion/cfqVersion field, and no block
carries a `legacy` field either -- an unnumbered batch is recognisable by `batchNumber: null`.
"""

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors, render  # noqa: E402
from cfq_lib import text as cfq_text  # noqa: E402
from cfq_lib.proc import git as proc_git  # noqa: E402
from cfq_lib.proc import is_git_repo, settings_get  # noqa: E402

PROG = "cfq_changelog.py"


# ---- changelog file location -------------------------------------------------------------

def changelog_file(repo):
    """<repo>/<changelogFile>, or None when changelogFile is disabled (empty). Honours the repo
    tier -- changelogFile is scoped ["global", "repo"], and a per-repo override must win."""
    rel = settings_get(repo, "changelogFile")
    if not rel:
        return None
    return f"{repo}/{rel}"


# ---- report.json -> phases: yaml block ----------------------------------------------------

def phases_yaml(report_path):
    try:
        data = json.loads(pathlib.Path(report_path).read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    phases = data.get("phases") if isinstance(data, dict) else None
    if not isinstance(phases, list):
        return ""

    def val(p, key):
        v = p.get(key) if isinstance(p, dict) else None
        return "" if v is None or v is False else v

    blocks = []
    for p in phases:
        if isinstance(p, dict) and p.get("unskipped"):
            continue  # a skip that was taken back is no longer a ledger fact
        # implemented (current worker schema) then summary (classic-mode / pre-orchestrator
        # records) -- same fallback order as cfq_report.phase_summary().
        summary = val(p, "implemented") or val(p, "summary")
        blocks.append(
            "    - phase: " + json.dumps(val(p, "phase"), ensure_ascii=False) + "\n"
            "      status: " + json.dumps(val(p, "status"), ensure_ascii=False) + "\n"
            "      summary: " + json.dumps(summary, ensure_ascii=False)
        )
    return "\n".join(blocks)


# ---- batch identity -------------------------------------------------------------------------

def parse_batch_number(batch):
    """New-format batch directory names are <digits>-<YYYY-MM-DD>-<slug> (the number precedes
    the date); legacy names start directly with the date. Returns the plain int on a match, None
    on no match -- never guesses from a version tag or branch name."""
    return cfq_text.parse_batch_name(batch)["number"]


# ---- block rendering --------------------------------------------------------------------------

def render_block(number, batch, branch, base, started, status, finished, phases):
    """Renders one changelog block as text, no trailing newline (the caller adds exactly one when
    writing/appending -- mirrors cfq-changelog.sh's command-substitution + `printf '%s\\n'` shape)."""
    lines = [f"- batchNumber: {number}", f"  batch: {batch}"]
    if branch:
        lines.append(f"  branch: {branch}")
    if base:
        lines.append(f"  base: {base}")
    if started:
        lines.append(f"  started: {started}")
    lines.append(f"  status: {status}")
    if finished:
        lines.append(f"  finished: {finished}")
    if phases:
        lines.append("  phases:")
        lines.append(phases)
    return "\n".join(lines)


# ---- line-oriented block parsing ------------------------------------------------------------
# Read by scanning lines into blocks delimited by column-0 "- " list items, so an untouched entry
# can be written back exactly as it was read. Write by replacing only the lines that changed,
# never by re-emitting the whole document from a data structure.

def read_lines(path):
    return pathlib.Path(path).read_text().splitlines(keepends=True)


def block_starts(lines):
    return [i + 1 for i, l in enumerate(lines) if l.startswith("- ")]


def block_end_line(lines, start):
    """Exclusive end line of the block starting at `start` (next block start - 1, or EOF)."""
    for i in range(start, len(lines)):
        if lines[i].startswith("- "):
            return i
    return len(lines)


def block_text(lines, start):
    return "".join(lines[start - 1:block_end_line(lines, start)])


def block_field(block, prefix):
    """First line in `block` starting with `prefix`, with `prefix` and any following spaces
    stripped -- None when no line matches (distinct from a line matching with an empty value)."""
    for line in block.split("\n"):
        if line.startswith(prefix):
            return line[len(prefix):].lstrip(" ")
    return None


def find_block_start(file, field, value, want_status=None):
    """First matching block's start line (1-indexed, i.e. the newest), None on no match."""
    lines = read_lines(file)
    for start in block_starts(lines):
        block = block_text(lines, start)
        if (block_field(block, field) or "") != value:
            continue
        if want_status is not None and (block_field(block, "  status:") or "") != want_status:
            continue
        return start
    return None


def prepend_block(target, block):
    """New block goes on top, below any leading comment preamble (lines before the first
    column-0 '- ' item). A missing or empty file just becomes the block."""
    lines = read_lines(target) if os.path.isfile(target) else []
    starts = block_starts(lines)
    split = starts[0] - 1 if starts else len(lines)
    preamble = "".join(lines[:split])
    if preamble and not preamble.endswith("\n"):
        preamble += "\n"
    render.write_text_atomic(target, preamble + block + "\n" + "".join(lines[split:]))


def replace_block(target, start, new_block):
    lines = read_lines(target)
    end = block_end_line(lines, start)
    render.write_text_atomic(target, "".join(lines[:start - 1]) + new_block + "\n" + "".join(lines[end:]))


DATE_PREFIX_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}")


def normalize_text(text):
    """Pure str -> str: comment preamble first, then numbered blocks by number descending, then
    unnumbered blocks (batchNumber: null, `- version:`) by batch date descending; ties keep their
    current order. Only `  legacy:` lines are ever removed from a block."""
    lines = text.splitlines(keepends=True)
    starts = block_starts(lines)
    if not starts:
        return text
    preamble = "".join(lines[:starts[0] - 1])
    blocks = []
    for start in starts:
        body = "".join(l for l in lines[start - 1:block_end_line(lines, start)]
                       if not l.startswith("  legacy:"))
        blocks.append(body if body.endswith("\n") else body + "\n")

    def key(block):
        num = block_field(block, "- batchNumber:")
        if num is not None and re.fullmatch(r"[0-9]+", num):
            return (1, int(num), "")
        for field in ("  batch:", "  started:"):
            m = DATE_PREFIX_RE.match(block_field(block, field) or "")
            if m:
                return (0, 0, m.group(0))
        return (0, 0, "")

    return preamble + "".join(sorted(blocks, key=key, reverse=True))


def normalize_file(target):
    """Normalizes `target` in place; writes only when the result differs. True if it wrote."""
    text = pathlib.Path(target).read_text()
    new = normalize_text(text)
    if new == text:
        return False
    render.write_text_atomic(target, new)
    return True


def normalize_if_exists(target):
    if os.path.isfile(target):
        normalize_file(target)


# ---- git trailer scanning (ensure's one-time bootstrap) --------------------------------------

def scan_trailer_max(repo):
    """Highest CFQ-Batch-Number trailer reachable in repo history; 0 if none. Uses Git's own
    trailer-aware formatting, never free-text grep, so a stray "CFQ-Batch-Number" in a commit
    body/subject can't be mistaken for a real trailer."""
    out = proc_git(
        repo, "log", "--all", "--no-color",
        "--pretty=format:%(trailers:key=CFQ-Batch-Number,valueonly)",
    )
    m = 0
    for line in out.stdout.split("\n"):
        if re.fullmatch(r"[0-9]+", line):
            v = int(line)
            if v > m:
                m = v
    return m


def scan_trailer_batch_for_max(repo, max_number):
    """Human-readable CFQ-Batch trailer of the (first, newest-first) commit that carries the
    given max CFQ-Batch-Number. Each lookup is scoped to one commit at a time (-1 <hash>), never
    combined with --all -- a history-wide scan must always key off CFQ-Batch-Number, never off
    the human-readable CFQ-Batch trailer."""
    hashes = proc_git(repo, "log", "--all", "--format=%H").stdout.split()
    for h in hashes:
        val = proc_git(
            repo, "log", "-1", "--format=%(trailers:key=CFQ-Batch-Number,valueonly)", h,
        ).stdout.strip()
        if val == str(max_number):
            return proc_git(
                repo, "log", "-1", "--format=%(trailers:key=CFQ-Batch,valueonly)", h,
            ).stdout.strip()
    return ""


# ---- verbs ------------------------------------------------------------------------------------

def cmd_init(args):
    repo, branch, base, batch = args.repo, args.branch, args.base, args.batch
    target = changelog_file(repo)
    if target is None:
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    normalize_if_exists(target)

    number = parse_batch_number(batch)
    number_str = str(number) if number is not None else "null"

    started = date.today().isoformat()
    reserved_start = None
    if os.path.isfile(target):
        reserved_start = find_block_start(target, "  batch:", batch, want_status="parked")

    new_block = render_block(number_str, batch, branch, base, started, "in-progress", "", "")
    if reserved_start is not None:
        replace_block(target, reserved_start, new_block)
    else:
        prepend_block(target, new_block)


def cmd_finish(args):
    repo, branch, batch_dir = args.repo, args.branch, args.batch_dir
    target = changelog_file(repo)
    if target is None:
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    normalize_if_exists(target)
    batch = os.path.basename(os.path.normpath(batch_dir))
    report = os.path.join(batch_dir, "report.json")
    finished = date.today().isoformat()
    phases = phases_yaml(report)

    matched_start = None
    if os.path.isfile(target):
        matched_start = find_block_start(target, "  branch:", branch, want_status="in-progress")

    if matched_start is not None:
        lines = read_lines(target)
        block = block_text(lines, matched_start)
        number = block_field(block, "- batchNumber:") or "null"
        batchname = block_field(block, "  batch:")
        if batchname:
            batch = batchname
        base = block_field(block, "  base:") or ""
        started = block_field(block, "  started:") or ""
        new_block = render_block(number, batch, branch, base, started, "done", finished, phases)
        replace_block(target, matched_start, new_block)
    else:
        # No matching in-progress block (different branch last, malformed file, missing file, or
        # an init that never ran): prepend a new done entry -- a stray extra entry beats one that
        # silently drops phases.
        number = parse_batch_number(batch)
        number_str = str(number) if number is not None else "null"
        started = ""
        if os.path.isfile(report):
            try:
                data = json.loads(pathlib.Path(report).read_text())
                s = data.get("started") if isinstance(data, dict) else None
                started = (s if isinstance(s, str) else "")[:10]
            except (OSError, json.JSONDecodeError):
                started = ""
        new_block = render_block(number_str, batch, branch, "", started, "done", finished, phases)
        prepend_block(target, new_block)


def cmd_reserve(args):
    repo, number, batch = args.repo, args.number, args.batch
    if not re.fullmatch(r"[0-9]+", number or ""):
        errors.die(f"{PROG}: reserve: batchNumber must be a positive integer, got '{number}'")
    target = changelog_file(repo)
    if target is None:
        errors.die(f"{PROG}: reserve: changelogFile is disabled, cannot reserve a numbered batch")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    normalize_if_exists(target)
    if os.path.isfile(target):
        existing_lines = set(pathlib.Path(target).read_text().split("\n"))
        if f"- batchNumber: {number}" in existing_lines or f"  batch: {batch}" in existing_lines:
            errors.die(f"{PROG}: reserve: duplicate batchNumber/batch identity: {number}/{batch}")
    block = "\n".join([f"- batchNumber: {number}", f"  batch: {batch}", "  status: parked"])
    prepend_block(target, block)


def cmd_rename_batch(args):
    """Narrow width-migration helper: rewrites only the `batch:` field of the block currently
    matching <old-batch>. A no-op when the changelog is disabled, missing, or no block matches --
    the caller re-derives its rewrite set from current state, so an already-renamed entry
    harmlessly matching nothing here is expected, not an error."""
    repo, old, new = args.repo, args.old, args.new
    target = changelog_file(repo)
    if target is None or not os.path.isfile(target):
        return
    normalize_file(target)
    start = find_block_start(target, "  batch:", old)
    if start is None:
        return
    lines = read_lines(target)
    block = block_text(lines, start)
    new_lines = [f"  batch: {new}" if line.startswith("  batch: ") else line for line in block.split("\n")]
    replace_block(target, start, "\n".join(new_lines))


def cmd_branch_for(args):
    """Read-only: the branch persisted for <batch> in the ledger (any status), no output on no
    match, missing file or disabled changelog. Authoritative source for cfq_branch.py's
    continue-mode check -- more precise than re-deriving a branch from a slug suffix match."""
    repo, batch = args.repo, args.batch
    target = changelog_file(repo)
    if target is None or not os.path.isfile(target):
        return
    start = find_block_start(target, "  batch:", batch)
    if start is None:
        return
    lines = read_lines(target)
    block = block_text(lines, start)
    val = block_field(block, "  branch:")
    if val is not None:
        print(val)


def compose_commit_message(repo, batch, phase, status, message_file):
    """Appends the standard CFQ-* trailer block to a numbered batch's phase-commit message via
    git interpret-trailers, so the trailers land in the same trailing block as any existing
    trailer (e.g. Co-Authored-By) rather than a second machine section. Legacy (unnumbered)
    batches pass the message through unchanged -- no number is ever invented for them. Returns the
    composed text; factored out of `cmd_commit_message` so `cfq_phase.py commit` can call it
    directly instead of shelling back out to this script."""
    if status != "green":
        errors.die(f"{PROG}: commit-message: status must be 'green', got '{status}'")
    number = parse_batch_number(batch)
    if number is not None:
        result = proc_git(
            repo, "interpret-trailers", "--trim-empty",
            "--trailer", f"CFQ-Batch-Number={number}",
            "--trailer", f"CFQ-Batch={batch}",
            "--trailer", f"CFQ-Phase={phase}",
            "--trailer", f"CFQ-Phase-Status={status}",
            message_file,
            check=True,
        )
        return result.stdout
    return pathlib.Path(message_file).read_text()


def cmd_commit_message(args):
    text = compose_commit_message(args.repo, args.batch, args.phase, args.status, args.message_file)
    sys.stdout.write(text)


def cmd_commit(args):
    """Commits only the changelog file, scoped by pathspec so an unrelated staged file is never
    swept in -- `git commit -- <file>` leaves everything else staged exactly as it was. Prints
    `off|forced|committed|clean`. `forced` means the repo's own ignore rule covered the (untracked)
    file and it was `git add -f`-ed anyway; once tracked the ignore rule no longer applies, so later
    calls take the normal path. No push -- the caller's own next `git push` carries it."""
    repo, message = args.repo, args.message
    target = changelog_file(repo)
    if target is None:
        print("off")
        return
    rel = os.path.relpath(target, repo)
    # check-ignore exits 0 only for an untracked, ignored path (a tracked file reports not-ignored).
    ignored = proc_git(repo, "check-ignore", "-q", "--", rel).returncode == 0
    if ignored:
        if not os.path.isfile(target):
            print("clean")
            return
    else:
        status = proc_git(repo, "status", "--porcelain", "--", rel).stdout
        if not status.strip():
            print("clean")
            return
    add_args = ["add"] + (["-f"] if ignored else []) + ["--", rel]
    add = proc_git(repo, *add_args)
    if add.returncode != 0:
        errors.die(add.stderr, add.returncode or 1)
    commit = proc_git(repo, "commit", "-q", "-m", message, "--", rel)
    if commit.returncode != 0:
        errors.die(commit.stderr, commit.returncode or 1)
    print("forced" if ignored else "committed")


def cmd_ensure(args):
    repo = args.repo
    target = changelog_file(repo)
    if target is None:
        print(render.dump_json({"source": "disabled", "max": 0, "path": None}))
        return
    if os.path.isfile(target):
        normalize_file(target)
        print(render.dump_json({"source": "exists", "max": None, "path": target}))
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)

    max_number = 0
    source = "empty"
    batchctx = ""
    if is_git_repo(repo):
        scanned = scan_trailer_max(repo)
        if scanned > 0:
            max_number = scanned
            source = "git-trailer"
            batchctx = scan_trailer_batch_for_max(repo, max_number)

    if source == "git-trailer":
        lines = [f"- batchNumber: {max_number}"]
        if batchctx:
            lines.append(f"  batch: {batchctx}")
        lines.append("  status: recovered")
        pathlib.Path(target).write_text("\n".join(lines) + "\n")
    else:
        pathlib.Path(target).write_text("")

    print(render.dump_json({"source": source, "max": max_number, "path": target}))


def cmd_normalize(args):
    target = changelog_file(args.repo)
    if target is None:
        print("off")
    elif not os.path.isfile(target):
        print("missing")
    else:
        print("normalized" if normalize_file(target) else "unchanged")


def cmd_max_batch_number(args):
    repo = args.repo
    target = changelog_file(repo)
    if target is None or not os.path.isfile(target):
        print(0)
        return
    m = 0
    prefix = "- batchNumber: "
    for line in pathlib.Path(target).read_text().split("\n"):
        if line.startswith(prefix):
            v = line[len(prefix):]
            if re.fullmatch(r"[0-9]+", v) and int(v) > m:
                m = int(v)
    print(m)


# ---- argument parsing ---------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("init")
    p.add_argument("repo")
    p.add_argument("branch")
    p.add_argument("base")
    p.add_argument("batch")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("finish")
    p.add_argument("repo")
    p.add_argument("branch")
    p.add_argument("batch_dir")
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("reserve")
    p.add_argument("repo")
    p.add_argument("number")
    p.add_argument("batch")
    p.set_defaults(func=cmd_reserve)

    p = sub.add_parser("rename-batch")
    p.add_argument("repo")
    p.add_argument("old")
    p.add_argument("new")
    p.set_defaults(func=cmd_rename_batch)

    p = sub.add_parser("branch-for")
    p.add_argument("repo")
    p.add_argument("batch")
    p.set_defaults(func=cmd_branch_for)

    p = sub.add_parser("commit-message")
    p.add_argument("repo")
    p.add_argument("batch")
    p.add_argument("phase")
    p.add_argument("status")
    p.add_argument("message_file")
    p.set_defaults(func=cmd_commit_message)

    p = sub.add_parser("commit")
    p.add_argument("repo")
    p.add_argument("message")
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("ensure")
    p.add_argument("repo")
    p.set_defaults(func=cmd_ensure)

    p = sub.add_parser("normalize")
    p.add_argument("repo")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("max-batch-number")
    p.add_argument("repo")
    p.set_defaults(func=cmd_max_batch_number)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} init <repo-root> <branch> <base> <batch> | "
            f"finish <repo-root> <branch> <batch-dir> | "
            f"reserve <repo-root> <batchNumber> <batch> | "
            f"rename-batch <repo-root> <old-batch> <new-batch> | "
            f"branch-for <repo-root> <batch> | "
            f"commit-message <repo-root> <batch> <phase> <status> <message-file> | "
            f"commit <repo-root> <message> | "
            f"ensure <repo-root> | max-batch-number <repo-root> | normalize <repo-root>"
        )
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
