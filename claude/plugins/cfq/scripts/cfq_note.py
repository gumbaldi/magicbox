#!/usr/bin/env python3
# Usage: cfq_note.py plan <repo-root> <slug> <body-file|-> [--framework]
#        cfq_note.py todo <repo-root> <slug> <body-file|->
#        cfq_note.py close <repo-root> <entry>... --reason <text>
#        cfq_note.py merge-todo <repo-root> <branch>
#        cfq_note.py import <repo-root>
#        cfq_note.py list <repo-root> [--text | --overview]
#        cfq_note.py sweep <repo-root> [--apply] [--text] [--stale-days N] [--timeout S]
#                           [--close <filename>]...
"""Writes a `plan/` or `todo/` queue entry: `<repo>/.claude/cfq/{plan,todo}/<today>-<slug>.md`.

Date, slug normalisation and target directory are convention, not judgement -- the caller
supplies only the title (raw, pre-normalisation) and the body text. Never appends or overwrites
an existing entry; the caller picks a different slug instead. `<body-file>` may be `-`, in which
case the body is read from stdin instead -- the documented default (see references/queue-entries.md),
since a body written to a temp file first can be blocked by a write-guard hook that only allows
writes under `.claude/cfq/`. An empty stdin body fails with `EMPTY_BODY`; the file form is
unchanged.

`_write_entry()` (shared by `plan`, `todo` and `merge-todo`) also repairs two writer defects:
a slug carrying a leading `YYYY-MM-DD-` prefix (repeated, too -- e.g. copied from another entry's
filename) has it stripped before normalising, and a body whose first non-empty line doesn't open
with `# ` gets a `# <Title>` derived from the slug prepended, with a stderr warning naming it --
never rejected.

`close <repo-root> <entry>... --reason <text>` is the `plan/` inbox's other close path, for an
entry whose fix landed incidentally rather than through `park --from-plan`: `<entry>` (repeatable,
one call closes several with the same reason) is a filename or path inside
`<repo-root>/.claude/cfq/plan/` -- anything outside `plan/` fails `INVALID_PATH`, a missing entry
fails `NOT_FOUND`. It appends a `## Closed` section (date + reason) to the entry and moves it into
`plan/done/`, creating that directory if absent. Never touches `todo/` -- `note sweep --close`
stays the only todo closer.

`plan --framework` is for findings about cfq itself rather than the repo under work: it always
writes into the global framework inbox (`$HOME/.claude/cfq/framework-inbox/`) unless
the target repo is `frameworkRepo` itself, in which case it writes the ordinary `plan/` entry --
no session ever writes into a second repo. `import <repo-root>` is the inverse, run inside the
framework repo: it moves every inbox entry into that repo's own `plan/`, and is a no-op unless
`<repo-root>` is `frameworkRepo`.

`merge-todo <repo-root> <branch>` composes a deterministic `todo/` merge card itself -- title,
ready-to-run merge command and a `check:` line that resolves `origin/main` first and falls back to
local `main` -- so the check line can never be left out the way a model-composed card leaves it
out. It reuses the same write path as `todo` (target directory, date prefix, slug normalisation,
`EXISTS` refusal); only the body text and the slug source (the branch name, `/` translated to `-`
before normalisation) differ.

`list <repo-root>` renders the `plan/` inbox without consuming it -- one record per
`plan/*.md` (non-recursive, so `plan/done/` is never listed), sorted by filename ascending, which
is already oldest-first given the `<YYYY-MM-DD>-<slug>.md` naming. `--from-plan` on `cfq park` is
the inbox's other half: it consumes the entry `list` showed. `--overview` (mutually exclusive with
`--text`) is the one-line-per-topic block `pfq`/`ifq` print verbatim at session start: date + title
only, no excerpt. In `frameworkRepo` it additionally lists the global framework inbox's still-unimported
entries, tagged `framework` and counted separately in the header -- elsewhere those entries are
never written into `plan/` in the first place, so there is nothing extra to show. Read-only either
way: it never imports and never moves anything.

`sweep <repo-root>` runs every `todo/*.md` card's `check:` line (first match wins; further
`check:` lines are counted into `extraChecks` and never executed) and classifies each card
`green`/`red`/`unresolvable`/`manual` -- a bare call only reports, `--apply` additionally moves the
`green` cards into `todo/done/`, re-running the checks rather than trusting an earlier report
(same read/write split as `batch verify`/`batch recover`). Exit `127` is `unresolvable` rather than
`red`; a `red`/`unresolvable` card older than `--stale-days` (default 30, from the filename's
`YYYY-MM-DD` prefix) is additionally marked `stale`. `--close <filename>` (repeatable) moves a
named card regardless of its state -- the sanctioned explicit path for a card with no `check:`
line, replacing a hand-`mv`. Never touches `plan/`.
"""

import argparse
import os
import pathlib
import re
import subprocess
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors, render  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import portal_hook  # noqa: E402
from cfq_lib import proc as cfq_lib_proc  # noqa: E402
from cfq_lib import text as cfq_lib_text  # noqa: E402
from cfq_lib.env import home_dir  # noqa: E402

PROG = "cfq_note.py"

TARGET_DIR = {
    "plan": cfq_lib_paths.plan_dir,
    "todo": cfq_lib_paths.todo_dir,
}


DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def normalise_slug(raw):
    s = raw.lower().encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _strip_date_prefixes(raw_slug):
    """Strips a leading `YYYY-MM-DD-` from the slug, repeated -- a caller may pass an
    already-dated slug (e.g. copied from another entry's filename) more than once, which would
    otherwise double up in the written filename."""
    s = raw_slug
    while DATE_PREFIX_RE.match(s):
        s = DATE_PREFIX_RE.sub("", s, count=1)
    return s


def _derive_title(slug):
    """Hyphens -> spaces, first letter upper-cased -- the fallback title for a body with no `# `
    heading, derived from the already-normalised slug so it matches the written filename."""
    title = slug.replace("-", " ")
    return title[:1].upper() + title[1:] if title else title


def _ensure_title(body_text, slug):
    """A body whose first non-empty line doesn't open with `# ` gets a derived title prepended,
    with a stderr warning naming it -- never rejected. Fix for the malformed inbox entry
    `2026-09-23-2026-09-23-notification-dialog-focus-not-restored-on-close.md`, whose body had no
    `# ` title and showed "## Finding" as its inbox title instead."""
    first_nonempty = ""
    for line in body_text.splitlines():
        if line.strip():
            first_nonempty = line.strip()
            break
    if first_nonempty.startswith("# "):
        return body_text

    title = _derive_title(slug)
    print(
        f"warning: note body has no `# ` title -- derived '# {title}' from the slug",
        file=sys.stderr,
    )
    return f"# {title}\n\n{body_text}"


def _inbox_dir():
    # Not a repo-local path -- outside every repo, next to repos.json/settings.json/state.json --
    # so it does not belong in cfq_lib/paths.py (repo-local path helpers only).
    return home_dir() / ".claude" / "cfq" / "framework-inbox"


def _resolve_framework_repo():
    """Reads `frameworkRepo` through the ordinary settings chain (global tier + env override).
    Empty means no framework repo is configured."""
    val = cfq_lib_proc.cfq_run("settings", "get", "frameworkRepo").stdout.strip()
    return val or None


def _is_framework_repo(repo, framework_repo):
    if not framework_repo:
        return False
    return os.path.realpath(repo) == os.path.realpath(framework_repo)


def _write_entry(target_dir, raw_slug, body_text):
    """Shared tail for every `note` subcommand that lands a file in `plan/` or `todo/`: strip a
    repeated date prefix off the slug, normalise it, build `<today>-<slug>.md`, refuse an existing
    target, ensure the body carries a `# ` title, write, print the path. One place decides where a
    card lands -- callers never reimplement this."""
    slug = normalise_slug(_strip_date_prefixes(raw_slug))
    if not slug:
        errors.fail("INVALID_SLUG", detail=f"slug normalises to the empty string: '{raw_slug}'")
        return

    target_dir = pathlib.Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{date.today().isoformat()}-{slug}.md"

    if target.exists():
        errors.fail("EXISTS", detail=str(target))
        return

    target.write_text(_ensure_title(body_text, slug))
    print(str(target))


def _read_body(body_file_arg):
    """Reads the body from stdin when `body_file_arg == "-"`, otherwise from the named file.
    Returns `None` after already calling `errors.fail()` (and exiting) on failure -- the `None`
    return is unreachable in practice, kept only so the caller's `if body_text is None: return`
    guard reads the same as every other early-exit in this file."""
    if body_file_arg == "-":
        body_text = sys.stdin.read()
        if not body_text:
            errors.fail("EMPTY_BODY", detail="stdin body was empty")
            return None
        return body_text

    body_file = pathlib.Path(body_file_arg)
    if not body_file.is_file():
        errors.fail("NO_SUCH_FILE", detail=f"no such body file: {body_file}")
        return None
    return body_file.read_text()


def cmd_note(args, kind):
    body_text = _read_body(args.body_file)
    if body_text is None:
        return

    # False only for `plan --framework` writing into the global framework inbox -- an entry that
    # never lands in this repo's own queue, so there is nothing here for that repo's portal to
    # resync over.
    wrote_to_repo = True
    if kind == "plan" and getattr(args, "framework", False):
        framework_repo = _resolve_framework_repo()
        if _is_framework_repo(args.repo, framework_repo):
            target_dir = TARGET_DIR[kind](args.repo)
        else:
            target_dir = _inbox_dir()
            wrote_to_repo = False
    else:
        target_dir = TARGET_DIR[kind](args.repo)

    if kind == "todo":
        # Same detector, same line.strip() treatment, that _sweep_card later applies -- so the
        # warning fires on exactly the lines sweep would execute, never a second regex that drifts.
        if not any(CHECK_RE.match(line.strip()) for line in body_text.splitlines()):
            print(
                "warning: no `check:` line -- `cfq note sweep` can never close this card "
                "automatically (see references/queue-entries.md)",
                file=sys.stderr,
            )

    _write_entry(target_dir, args.slug, body_text)

    if wrote_to_repo:
        portal_hook.sync(args.repo)


def _plan_entry_path(repo, entry):
    """Resolves `<entry>` against `<repo>/.claude/cfq/plan/` -- an absolute path is taken as
    given, anything else (a bare filename or a relative path) is joined onto `plan/` -- and
    requires the result to land under `plan/` itself. Returns the resolved path, or `None` when it
    falls outside `plan/`.

    (verbatim in spirit) containment check duplicated from `cfq_park.py`'s `_consume_plan_entry()`
    -- duplicated rather than imported, since scripts call each other through `bin/cfq <noun>`,
    never by a direct cross-script import (CLAUDE.md's Commands section), and `cfq_park.py` is
    outside this phase's Affected Files."""
    plan_root = pathlib.Path(cfq_lib_paths.plan_dir(repo)).resolve(strict=False)
    raw = pathlib.Path(entry)
    candidate = (raw if raw.is_absolute() else plan_root / raw).resolve(strict=False)
    try:
        candidate.relative_to(plan_root)
    except ValueError:
        return None
    return candidate


def cmd_close(args):
    plan_root = pathlib.Path(cfq_lib_paths.plan_dir(args.repo)).resolve(strict=False)
    done_dir = plan_root / "done"

    closed = []
    for raw_entry in args.entries:
        target = _plan_entry_path(args.repo, raw_entry)
        if target is None:
            errors.fail("INVALID_PATH", detail=f"not inside plan/: {raw_entry}")
            return
        if not target.is_file():
            errors.fail("NOT_FOUND", detail=f"no such plan entry: {target}")
            return

        body = target.read_text()
        if not body.endswith("\n"):
            body += "\n"
        body += f"\n## Closed\n\n{date.today().isoformat()} -- {args.reason}\n"
        target.write_text(body)

        done_dir.mkdir(parents=True, exist_ok=True)
        dest = done_dir / target.name
        if dest.exists():
            errors.fail("EXISTS", detail=f"{target} -> {dest}")
            return
        os.replace(str(target), str(dest))
        closed.append(str(dest))

    portal_hook.sync(args.repo)
    print(render.dump_json({"status": "OK", "closed": closed}))


def cmd_merge_todo(args):
    branch = args.branch
    check = (
        f"git merge-base --is-ancestor {branch} origin/main 2>/dev/null "
        f"|| git merge-base --is-ancestor {branch} main"
    )
    body = (
        f"# Merge branch `{branch}` into main\n"
        "\n"
        "Batch finished -- merge the branch and delete it once the merge is in.\n"
        "\n"
        f"    git checkout main && git merge --ff-only {branch}\n"
        "\n"
        f"check: {check}\n"
    )
    slug = "merge-" + branch.replace("/", "-")
    _write_entry(TARGET_DIR["todo"](args.repo), slug, body)
    portal_hook.sync(args.repo)


def cmd_import(args):
    repo = args.repo
    framework_repo = _resolve_framework_repo()
    if not _is_framework_repo(repo, framework_repo):
        print(render.dump_json({"status": "OK", "imported": [], "skipped": "not frameworkRepo"}))
        return

    inbox = _inbox_dir()
    entries = sorted(inbox.glob("*.md")) if inbox.is_dir() else []

    imported = []
    import_errors = []
    if entries:
        target_dir = pathlib.Path(cfq_lib_paths.plan_dir(repo))
        target_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            target = target_dir / entry.name
            if target.exists():
                import_errors.append(str(target))
                continue
            os.replace(str(entry), str(target))
            imported.append(str(target))

    result = {"status": "OK", "imported": imported}
    if import_errors:
        result["errors"] = import_errors
    if imported:
        portal_hook.sync(repo)
    print(render.dump_json(result))


FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
EXCERPT_MAX = 200


def _truncate(text, max_len):
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0].rstrip(" .,;:-") + "…"


def _parse_plan_entry(path):
    """One inbox record: absolute path, filename, date/slug parsed from the filename, the title
    (first `# ` heading, falling back to the first non-empty line) and a short excerpt (the next
    two non-empty body lines after the title, truncated to ~200 chars with an ellipsis)."""
    m = FILENAME_RE.match(path.name)
    entry_date, slug = (m.group(1), m.group(2)) if m else ("", path.stem)

    lines = path.read_text().splitlines()

    title = ""
    title_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            title_idx = i
            break
    if title_idx == -1:
        for i, line in enumerate(lines):
            if line.strip():
                title = line.strip()
                title_idx = i
                break

    body_lines = []
    for line in lines[title_idx + 1:]:
        if line.strip():
            body_lines.append(line.strip())
            if len(body_lines) == 2:
                break

    return {
        "path": str(path),
        "filename": path.name,
        "date": entry_date,
        "slug": slug,
        "title": title,
        "excerpt": _truncate(" ".join(body_lines), EXCERPT_MAX),
    }


def cmd_list(args):
    plan_dir = pathlib.Path(TARGET_DIR["plan"](args.repo))
    entries = (
        [_parse_plan_entry(f) for f in sorted(plan_dir.glob("*.md"))]
        if plan_dir.is_dir()
        else []
    )

    if args.overview:
        _print_overview(args, entries)
        return

    if not args.text:
        print(render.dump_json(entries))
        return

    if not entries:
        print("No planning requests waiting in the queue.")
        return

    for entry in entries:
        parts = [entry["date"], entry["title"]]
        if entry["excerpt"]:
            parts.append(entry["excerpt"])
        print("  ".join(parts))


def _print_overview(args, entries):
    """The one-line-per-topic block `pfq`/`ifq` print verbatim at session start: date + title
    only, no excerpt. Read-only -- never imports, never moves anything. `frameworkRepo` is
    resolved only here, never on the plain `list`/`--text` paths, so those gain no extra
    `settings get` subprocess."""
    framework_entries = []
    if _is_framework_repo(args.repo, _resolve_framework_repo()):
        inbox = _inbox_dir()
        if inbox.is_dir():
            framework_entries = [_parse_plan_entry(f) for f in sorted(inbox.glob("*.md"))]

    total = len(entries) + len(framework_entries)
    if total == 0:
        print("INBOX  empty")
        return

    header = f"INBOX  {total} entries"
    if framework_entries:
        header += f" · {len(framework_entries)} framework not imported"
    print(header)

    rows = [[e["date"], e["title"]] for e in entries]
    rows += [[e["date"], e["title"], "framework"] for e in framework_entries]
    for line in cfq_lib_text.table(rows):
        print(line)


CHECK_RE = re.compile(r"^check:\s*(.+)$")
DEFAULT_STALE_DAYS = 30
DEFAULT_TIMEOUT = 30
CARD_STATES = ("green", "red", "unresolvable", "manual")


def _card_age_days(entry_date, path):
    """Days since the card's filename date prefix; falls back to the file's mtime when the
    filename carries no parseable `YYYY-MM-DD` prefix."""
    d = None
    if entry_date:
        try:
            d = date.fromisoformat(entry_date)
        except ValueError:
            d = None
    if d is None:
        d = date.fromtimestamp(path.stat().st_mtime)
    return (date.today() - d).days


def _run_check(cmd, repo_root, timeout):
    """Runs one `check:` command with cwd set to the repo root. Only the exit code matters --
    captured stdout/stderr is never part of the record. Returns (exit_code, state, reason)."""
    try:
        result = subprocess.run(
            ["bash", "-c", cmd], cwd=str(repo_root), capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "red", "timeout"
    if result.returncode == 0:
        return 0, "green", ""
    if result.returncode == 127:
        return 127, "unresolvable", ""
    return result.returncode, "red", f"exit {result.returncode}"


def _sweep_card(path, repo_root, timeout, stale_days):
    entry = _parse_plan_entry(path)  # (verbatim) title/date parsing, shared with `note list`

    checks = []
    for line in path.read_text().splitlines():
        m = CHECK_RE.match(line.strip())
        if m:
            checks.append(m.group(1))

    age_days = _card_age_days(entry["date"], path)
    record = {
        "file": entry["filename"],
        "title": entry["title"],
        "state": "manual",
        "check": checks[0] if checks else "",
        "exit": None,
        "reason": "",
        "ageDays": age_days,
        "stale": False,
        "moved": False,
        "extraChecks": max(0, len(checks) - 1),
        "error": "",
    }

    if checks:
        exit_code, state, reason = _run_check(checks[0], repo_root, timeout)
        record["exit"] = exit_code
        record["state"] = state
        record["reason"] = reason
        if state in ("red", "unresolvable") and age_days >= stale_days:
            record["stale"] = True

    return record


def _sweep_text(result):
    cards = [c for c in result["cards"] if c["state"] in CARD_STATES]
    if not cards:
        print("No todo cards waiting in the queue.")
        return

    order = {"green": 0, "unresolvable": 1, "red": 2, "manual": 3}

    def sort_key(c):
        bucket = order[c["state"]]
        # Red is sorted oldest-first within its own bucket -- the actionable end stays on top.
        return (bucket, -c["ageDays"] if c["state"] == "red" else 0)

    for c in sorted(cards, key=sort_key):
        parts = [c["state"], c["title"] or c["file"]]
        if c["stale"]:
            parts.append("stale?")
        print("  ".join(parts))


def cmd_sweep(args):
    repo_root = pathlib.Path(args.repo).resolve()
    todo_dir = pathlib.Path(cfq_lib_paths.todo_dir(str(repo_root)))
    done_dir = todo_dir / "done"

    card_paths = sorted(todo_dir.glob("*.md")) if todo_dir.is_dir() else []
    found_names = {p.name for p in card_paths}
    close_names = list(dict.fromkeys(args.close))

    counts = {"green": 0, "red": 0, "unresolvable": 0, "manual": 0, "moved": 0, "errors": 0}
    records = []

    for card_path in card_paths:
        record = _sweep_card(card_path, repo_root, args.timeout, args.stale_days)
        counts[record["state"]] += 1

        should_move = (
            card_path.name in close_names
            or (args.apply and record["state"] == "green")
        )
        if should_move:
            target = done_dir / card_path.name
            if target.exists():
                record["error"] = f"EXISTS: {target}"
                counts["errors"] += 1
            else:
                done_dir.mkdir(parents=True, exist_ok=True)
                os.replace(str(card_path), str(target))
                record["moved"] = True
                counts["moved"] += 1

        records.append(record)

    for name in close_names:
        if name not in found_names:
            counts["errors"] += 1
            records.append({
                "file": name, "title": "", "state": "", "check": "", "exit": None,
                "reason": "", "ageDays": None, "stale": False, "moved": False,
                "extraChecks": 0, "error": "NO_SUCH_FILE",
            })

    result = {
        "status": "OK",
        "repo": str(repo_root),
        "applied": bool(args.apply),
        "staleDays": args.stale_days,
        "cards": records,
        "counts": counts,
    }

    if counts["moved"]:
        portal_hook.sync(str(repo_root))

    if args.text:
        _sweep_text(result)
    else:
        print(render.dump_json(result))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    for kind in ("plan", "todo"):
        p = sub.add_parser(kind)
        p.add_argument("repo")
        p.add_argument("slug")
        p.add_argument("body_file")
        if kind == "plan":
            p.add_argument("--framework", action="store_true")
        p.set_defaults(func=lambda args, kind=kind: cmd_note(args, kind))

    close_p = sub.add_parser("close")
    close_p.add_argument("repo")
    close_p.add_argument("entries", nargs="+")
    close_p.add_argument("--reason", required=True)
    close_p.set_defaults(func=cmd_close)

    merge_todo_p = sub.add_parser("merge-todo")
    merge_todo_p.add_argument("repo")
    merge_todo_p.add_argument("branch")
    merge_todo_p.set_defaults(func=cmd_merge_todo)

    import_p = sub.add_parser("import")
    import_p.add_argument("repo")
    import_p.set_defaults(func=cmd_import)

    list_p = sub.add_parser("list")
    list_p.add_argument("repo")
    list_group = list_p.add_mutually_exclusive_group()
    list_group.add_argument("--text", action="store_true")
    list_group.add_argument("--overview", action="store_true")
    list_p.set_defaults(func=cmd_list)

    sweep_p = sub.add_parser("sweep")
    sweep_p.add_argument("repo")
    sweep_p.add_argument("--apply", action="store_true")
    sweep_p.add_argument("--text", action="store_true")
    sweep_p.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS, dest="stale_days")
    sweep_p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, dest="timeout")
    sweep_p.add_argument("--close", action="append", default=[], dest="close")
    sweep_p.set_defaults(func=cmd_sweep)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} plan|todo <repo-root> <slug> <body-file|-> [--framework] | "
            f"close <repo-root> <entry>... --reason <text> | "
            f"merge-todo <repo-root> <branch> | import <repo-root> | "
            f"list <repo-root> [--text | --overview] | "
            f"sweep <repo-root> [--apply] [--text] [--stale-days N] [--timeout S] "
            f"[--close <filename>]..."
        )
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
