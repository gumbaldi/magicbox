#!/usr/bin/env python3
# Usage: cfq_park.py <repo-root> <batch-dir-name> <high|normal> [<dependsOn-entry>...]
#                     [--from-plan <plan-entry-path>]
"""Parks a batch directory: creates it, writes .priority/.dependsOn, ensures the local git-exclude
entry, and registers the repo. Idempotent -- safe to re-run with the same arguments. Does not
write phase files; only the planning session that knows their content does that.

Ported from cfq-park.sh -- a port, not a redesign: the CLI contract (verbs, argument order, text
output, exit codes) is the invariant this file preserves.

`--from-plan <path>` is the plan-inbox consumption step: once everything above has run, the named
`plan/*.md` file (as shown by `cfq note list`) is moved into `plan/done/`, creating that directory
if needed -- so a failure in the move can never leave a half-parked batch behind. The move itself
stays idempotent the same way the rest of this script is: a path already under `plan/done/`, or
one that no longer exists, is a no-op rather than an error, since a `/pfq` session retrying Park
must not fail on the second attempt. A path outside `plan/` is rejected -- the flag consumes inbox
entries, not arbitrary files -- and a filename collision inside `plan/done/` is a real error,
naming both paths, since overwriting a previously parked entry is never the right move.
"""

import argparse
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import render  # noqa: E402
from cfq_lib.proc import cfq_argv  # noqa: E402

PROG = "cfq_park.py"


def _consume_plan_entry(repo, from_plan):
    plan_root = pathlib.Path(cfq_lib_paths.plan_dir(repo)).resolve(strict=False)
    plan_done = plan_root / "done"
    src = pathlib.Path(from_plan).resolve(strict=False)

    if not src.exists():
        return  # already gone -- idempotent no-op, matches a retried Park

    try:
        src.relative_to(plan_done)
        return  # already consumed -- idempotent no-op
    except ValueError:
        pass

    try:
        src.relative_to(plan_root)
    except ValueError:
        errors.fail("INVALID_PATH", detail=f"--from-plan is outside plan/: {src}")
        return

    plan_done.mkdir(parents=True, exist_ok=True)
    target = plan_done / src.name
    if target.exists():
        errors.fail("EXISTS", detail=f"{src} -> {target}")
        return
    os.replace(str(src), str(target))


def cmd_park(args):
    if args.priority not in ("high", "normal"):
        errors.die(f"{PROG}: priority must be high|normal, got '{args.priority}'")

    subprocess.run(cfq_argv("layout", "ensure", args.repo), stdout=subprocess.DEVNULL, check=True)

    d = pathlib.Path(cfq_lib_paths.impl_dir(args.repo)) / args.batch
    d.mkdir(parents=True, exist_ok=True)
    # .planning is written on creation, idempotent (a re-run during the same pfq session
    # refreshes the timestamp as a heartbeat), and removed by plan-for-queue's lint step once
    # the batch is complete -- this is what keeps ifq from picking up a batch pfq is still
    # writing.
    (d / ".planning").write_text(render.now_iso() + "\n")

    priority_file = d / ".priority"
    if args.priority == "high":
        priority_file.write_text("high\n")
    else:
        priority_file.unlink(missing_ok=True)

    depends_file = d / ".dependsOn"
    if args.depends:
        depends_file.write_text("\n".join(args.depends) + "\n")

    subprocess.run(cfq_argv("registry", "add", args.repo), stdout=subprocess.DEVNULL, check=True)

    print(str(d))

    if args.from_plan:
        _consume_plan_entry(args.repo, args.from_plan)


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    parser.add_argument("repo")
    parser.add_argument("batch")
    parser.add_argument("priority")
    parser.add_argument("depends", nargs="*")
    parser.add_argument("--from-plan", dest="from_plan", default=None)
    parser.set_defaults(func=cmd_park)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
