#!/usr/bin/env python3
# Usage: cfq_note.py plan <repo-root> <slug> <body-file>
#        cfq_note.py todo <repo-root> <slug> <body-file>
"""Writes a `plan/` or `todo/` queue entry: `<repo>/.claude/cfq/{plan,todo}/<today>-<slug>.md`.

Date, slug normalisation and target directory are convention, not judgement -- the caller
supplies only the title (raw, pre-normalisation) and the body text. Never appends or overwrites
an existing entry; the caller picks a different slug instead.
"""

import argparse
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402

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


def cmd_note(args, kind):
    slug = normalise_slug(args.slug)
    if not slug:
        errors.fail("INVALID_SLUG", detail=f"slug normalises to the empty string: '{args.slug}'")
        return

    body_file = pathlib.Path(args.body_file)
    if not body_file.is_file():
        errors.fail("NO_SUCH_FILE", detail=f"no such body file: {body_file}")
        return

    target_dir = pathlib.Path(TARGET_DIR[kind](args.repo))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{date.today().isoformat()}-{slug}.md"

    if target.exists():
        errors.fail("EXISTS", detail=str(target))
        return

    target.write_text(body_file.read_text())
    print(str(target))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    for kind in ("plan", "todo"):
        p = sub.add_parser(kind)
        p.add_argument("repo")
        p.add_argument("slug")
        p.add_argument("body_file")
        p.set_defaults(func=lambda args, kind=kind: cmd_note(args, kind))

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(f"usage: {PROG} plan|todo <repo-root> <slug> <body-file>")
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
