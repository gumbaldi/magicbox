#!/usr/bin/env python3
# Usage: cfq_note.py plan <repo-root> <slug> <body-file> [--framework]
#        cfq_note.py todo <repo-root> <slug> <body-file>
#        cfq_note.py merge-todo <repo-root> <branch>
#        cfq_note.py import <repo-root>
#        cfq_note.py list <repo-root> [--text]
#        cfq_note.py sweep <repo-root> [--apply] [--text] [--stale-days N] [--timeout S]
#                           [--close <filename>]...
"""Writes a `plan/` or `todo/` queue entry: `<repo>/.claude/cfq/{plan,todo}/<today>-<slug>.md`.

Date, slug normalisation and target directory are convention, not judgement -- the caller
supplies only the title (raw, pre-normalisation) and the body text. Never appends or overwrites
an existing entry; the caller picks a different slug instead.

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
the inbox's other half: it consumes the entry `list` showed.

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
from cfq_lib import proc as cfq_lib_proc  # noqa: E402
from cfq_lib.env import home_dir  # noqa: E402

PROG = "cfq_note.py"

TARGET_DIR = {
    "plan": cfq_lib_paths.plan_dir,
    "todo": cfq_lib_paths.todo_dir,
}


def normalise_slug(raw):
    s = raw.lower().encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


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
    """Shared tail for every `note` subcommand that lands a file in `plan/` or `todo/`: resolve
    the target directory, build `<today>-<slug>.md`, refuse an existing target, write, print the
    path. One place decides where a card lands -- callers never reimplement this."""
    slug = normalise_slug(raw_slug)
    if not slug:
        errors.fail("INVALID_SLUG", detail=f"slug normalises to the empty string: '{raw_slug}'")
        return

    target_dir = pathlib.Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{date.today().isoformat()}-{slug}.md"

    if target.exists():
        errors.fail("EXISTS", detail=str(target))
        return

    target.write_text(body_text)
    print(str(target))


def cmd_note(args, kind):
    body_file = pathlib.Path(args.body_file)
    if not body_file.is_file():
        errors.fail("NO_SUCH_FILE", detail=f"no such body file: {body_file}")
        return

    if kind == "plan" and getattr(args, "framework", False):
        framework_repo = _resolve_framework_repo()
        if _is_framework_repo(args.repo, framework_repo):
            target_dir = TARGET_DIR[kind](args.repo)
        else:
            target_dir = _inbox_dir()
    else:
        target_dir = TARGET_DIR[kind](args.repo)

    _write_entry(target_dir, args.slug, body_file.read_text())


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

    merge_todo_p = sub.add_parser("merge-todo")
    merge_todo_p.add_argument("repo")
    merge_todo_p.add_argument("branch")
    merge_todo_p.set_defaults(func=cmd_merge_todo)

    import_p = sub.add_parser("import")
    import_p.add_argument("repo")
    import_p.set_defaults(func=cmd_import)

    list_p = sub.add_parser("list")
    list_p.add_argument("repo")
    list_p.add_argument("--text", action="store_true")
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
            f"usage: {PROG} plan|todo <repo-root> <slug> <body-file> [--framework] | "
            f"merge-todo <repo-root> <branch> | import <repo-root> | "
            f"list <repo-root> [--text] | "
            f"sweep <repo-root> [--apply] [--text] [--stale-days N] [--timeout S] "
            f"[--close <filename>]..."
        )
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
