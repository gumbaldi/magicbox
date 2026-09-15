#!/usr/bin/env python3
# Usage: cfq_trash.py put <repo-root> <path> [--reason <text>]
#        cfq_trash.py list <repo-root> [--json]
#        cfq_trash.py restore <repo-root> <entry-id> [--force]
"""Thin CLI over `cfq_lib/trash.py` -- the only sanctioned delete under `<repo>/.claude/cfq/`.

`.claude/cfq/` is git-excluded, so a plain `rm` there is gone for good. `trash put` moves the
target into `.claude/cfq/.trash/<id>/` instead, recorded and restorable via `trash restore`.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors  # noqa: E402
from cfq_lib import render  # noqa: E402
from cfq_lib import trash  # noqa: E402

PROG = "cfq_trash.py"


def cmd_put(args):
    try:
        entry_id = trash.put(args.repo, args.path, reason=args.reason or "")
    except trash.TrashError as e:
        errors.fail(e.code, detail=str(e))
        return
    print(entry_id)


def cmd_list(args):
    listing = trash.entries(args.repo)
    if args.json:
        print(render.dump_json(listing))
        return
    for e in listing:
        print(f"{e['id']}  {e['movedAt']}  {e['originalPath']}")


def cmd_restore(args):
    try:
        path = trash.restore(args.repo, args.entry_id, force=args.force)
    except trash.TrashError as e:
        errors.fail(e.code, detail=str(e))
        return
    print(path)


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("put")
    p.add_argument("repo")
    p.add_argument("path")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_put)

    p = sub.add_parser("list")
    p.add_argument("repo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("restore")
    p.add_argument("repo")
    p.add_argument("entry_id")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_restore)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} put <repo-root> <path> [--reason <text>] | "
            f"list <repo-root> [--json] | restore <repo-root> <entry-id> [--force]"
        )
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
