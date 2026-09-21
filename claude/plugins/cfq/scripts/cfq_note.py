#!/usr/bin/env python3
# Usage: cfq_note.py plan <repo-root> <slug> <body-file> [--framework]
#        cfq_note.py todo <repo-root> <slug> <body-file>
#        cfq_note.py merge-todo <repo-root> <branch>
#        cfq_note.py import <repo-root>
#        cfq_note.py list <repo-root> [--text]
"""Writes a `plan/` or `todo/` queue entry: `<repo>/.claude/cfq/{plan,todo}/<today>-<slug>.md`.

Date, slug normalisation and target directory are convention, not judgement -- the caller
supplies only the title (raw, pre-normalisation) and the body text. Never appends or overwrites
an existing entry; the caller picks a different slug instead.

`plan --framework` is for findings about cfq itself rather than the repo under work: it always
writes into the global framework inbox (`$HOME/.claude/code-for-queue/framework-inbox/`) unless
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
"""

import argparse
import os
import pathlib
import re
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
    return home_dir() / ".claude" / "code-for-queue" / "framework-inbox"


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

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} plan|todo <repo-root> <slug> <body-file> [--framework] | "
            f"merge-todo <repo-root> <branch> | import <repo-root> | "
            f"list <repo-root> [--text]"
        )
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
