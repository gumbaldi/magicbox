#!/usr/bin/env python3
"""TEMPORARY, run-once script: gives every existing batch of one repo its `status.json`.

Usage: python3 <plugin-root>/tools/once_migrate_status.py <repo-root> [--dry-run]

Batches planned before `status.json` existed (open ones under `impl/` and finished ones under
`impl/done/`) have no such file. This script adopts each phase file by where it lies (root ->
`open`, `done/` -> `done`) and marks every root-level phase whose latest `report.json` entry is
`red` as `error`. A batch that already has the file is left alone, so a second run changes
nothing. `--dry-run` prints the names it would migrate and writes nothing.

It is deliberately not a `bin/cfq` verb, not documented as a command and has no test file: cfq
runs on two machines only, so the framework gets no code that exists only for this one-time
step. Run it once per repo with a queue on each machine; delete this file, the then empty
`tools/` directory and the "Upgrading" note in the README once both machines are migrated (a todo
card tracks that).
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from cfq_lib import paths, phase_state  # noqa: E402
from cfq_lib import queue as cfq_queue  # noqa: E402


def latest_red(batch_dir):
    """Slugs whose latest report.json entry is `red`; a missing or unparsable file is empty."""
    try:
        entries = json.loads((batch_dir / "report.json").read_text()).get("phases", [])
    except (OSError, ValueError, AttributeError):
        return set()
    latest = {}
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("phase"):
            latest[e["phase"]] = e.get("status")
    return {slug for slug, status in latest.items() if status == "red"}


def migrate(batch_dir):
    phase_state.init(batch_dir)
    phase_state.sync_files(batch_dir)
    red = latest_red(batch_dir)
    for p in phase_state.phases(batch_dir):
        if p["slug"] in red and p["status"] == "open" and p["path"] is not None \
                and p["path"].parent == batch_dir:
            phase_state.transition(batch_dir, p["slug"], "error")
    c = phase_state.counts(batch_dir)
    return f"{c['done']}/{c['error']}/{c['open']}"


def main(argv):
    dry = "--dry-run" in argv
    args = [a for a in argv if a != "--dry-run"]
    if len(args) != 1:
        sys.exit(f"usage: {sys.argv[0]} <repo-root> [--dry-run]")
    repo = args[0]
    count = 0
    for root in (paths.impl_dir(repo), paths.impl_done_dir(repo)):
        for batch_dir in cfq_queue.list_batch_dirs(pathlib.Path(root)):
            if phase_state.exists(batch_dir):
                continue
            count += 1
            print(batch_dir.name if dry else f"{batch_dir.name} {migrate(batch_dir)}")
    print(f"{count} batch(es) {'would be ' if dry else ''}migrated")


if __name__ == "__main__":
    main(sys.argv[1:])
