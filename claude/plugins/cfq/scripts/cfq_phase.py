#!/usr/bin/env python3
# Usage: cfq_phase.py record <batch-dir> <phase-json-file> [--no-telemetry]
#        cfq_phase.py reopen <batch-dir> <phase-slug>
"""Closing (and reopening) a phase as one transaction, not two agent-issued operations in the
wrong order with a `mkdir -p` improvised in between -- that gap is where an accidental `rm -rf`
on a batch's `done/` directory originated (see `.batch-context.md`).

`record` either moves the phase's `.md` file into `done/` and appends its ledger entry, or does
neither. `reopen` is the inverse: it moves a phase back out of `done/` and marks the ledger entry
`reopened`, never erasing `status`/`commit` -- that history is what `/rfq` and `ifq` Step 5's
failed-attempt detection read.
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cfq_report  # noqa: E402
from cfq_lib import errors  # noqa: E402

PROG = "cfq_phase.py"


def cmd_record(args):
    dir_ = args.dir
    if not pathlib.Path(dir_).is_dir():
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    try:
        phase_json = pathlib.Path(args.phase_file).read_text()
    except OSError as e:
        errors.die(f"{PROG} record: cannot read {args.phase_file}: {e}")

    try:
        phase_obj = json.loads(phase_json)
    except json.JSONDecodeError as e:
        errors.die(f"{PROG} record: invalid JSON in {args.phase_file}: {e}")

    phase_id = phase_obj.get("phase") if isinstance(phase_obj, dict) else None
    # Same slug pattern `report append` enforces, imported rather than re-declared -- checked
    # here too, before any file is touched, so a bare phase number never moves anything.
    if not isinstance(phase_id, str) or not cfq_report.PHASE_ID_RE.match(phase_id):
        errors.die(
            f"{PROG} record: phase must be the full phase slug (NN-slug), got '{phase_id}'"
        )

    status = phase_obj.get("status") if isinstance(phase_obj, dict) else None
    if status not in ("green", "red"):
        errors.die(f"{PROG} record: status must be 'green' or 'red', got '{status}'")

    root_path = pathlib.Path(dir_) / f"{phase_id}.md"
    done_path = pathlib.Path(dir_) / "done" / f"{phase_id}.md"

    if not root_path.is_file():
        if done_path.is_file():
            errors.fail("ALREADY_RECORDED", detail=f"{phase_id} is already in done/")
        errors.die(f"{PROG} record: no such phase file {root_path}")

    moved = False
    if status == "green":
        try:
            done_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root_path), str(done_path))
            moved = True
        except OSError as e:
            errors.die(f"{PROG} record: could not move {root_path} to done/: {e}")

    try:
        cfq_report.append_phase(dir_, phase_json, record_telemetry=not args.no_telemetry)
    except SystemExit:
        if moved:
            shutil.move(str(done_path), str(root_path))
        raise

    print(str(done_path) if moved else str(root_path))


def cmd_reopen(args):
    dir_, phase_slug = args.dir, args.phase_slug
    if not pathlib.Path(dir_).is_dir():
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    done_path = pathlib.Path(dir_) / "done" / f"{phase_slug}.md"
    root_path = pathlib.Path(dir_) / f"{phase_slug}.md"
    if not done_path.is_file():
        errors.fail("NOT_DONE", detail=f"no {phase_slug}.md in done/")

    f = pathlib.Path(dir_) / "report.json"
    if not f.is_file():
        errors.die(f"{PROG}: no report.json in {dir_}")
    data = json.loads(f.read_text())
    phases = data.get("phases", [])
    # Same last-match rule as cfq_report.py's set-commit: with two entries for the same slug,
    # the later attempt is the one that gets marked.
    matches = [i for i, p in enumerate(phases) if isinstance(p, dict) and p.get("phase") == phase_slug]
    if not matches:
        errors.die(f"{PROG} reopen: no phase entry '{phase_slug}' in {f}")

    shutil.move(str(done_path), str(root_path))
    try:
        at = subprocess.run(["date", "-Iseconds"], capture_output=True, text=True).stdout.strip()
        phases[matches[-1]]["reopened"] = at
        cfq_report.write_json(str(f), data)
    except OSError:
        shutil.move(str(root_path), str(done_path))
        raise

    print(str(root_path))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("record")
    p.add_argument("dir")
    p.add_argument("phase_file")
    p.add_argument("--no-telemetry", action="store_true")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("reopen")
    p.add_argument("dir")
    p.add_argument("phase_slug")
    p.set_defaults(func=cmd_reopen)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} record <batch-dir> <phase-json-file> [--no-telemetry] | "
            f"reopen <batch-dir> <phase-slug>"
        )
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
