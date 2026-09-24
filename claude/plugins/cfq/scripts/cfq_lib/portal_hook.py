"""Fires `bin/cfq portal sync` as a side effect of a queue mutation, at zero model-token cost --
see `.batch-context.md`'s Decisions: "Triggers live inside existing mutating verbs; the model
never calls `portal sync` itself." `sync(repo_root, batches=())` is the one call every mutating
verb makes, once, after its own mutation has already succeeded: `cfq_park.py` (park), `cfq_batch_id.py`
(`ready`), `cfq_lock.py` (`acquire`), `cfq_phase.py` (`record`/`commit`/`reopen`), `cfq_finish.py`,
`cfq_note.py`'s mutating verbs, `cfq_trash.py` (`put`/`restore`), and `cfq_dash.py` (`render`, to
catch a change made outside cfq, e.g. a merge).

Two off switches, both checked before any subprocess runs: `CFQ_PORTAL_SYNC=0` in the environment
(the test suite's own isolation -- see `tests/cfq_testlib.py`), and `htmlReport` resolving to
anything other than `"true"`, read through the same `settings get --repo` chain `cfq_finish.py`
already uses for this same setting. Never raises and never touches the calling verb's own exit
code or stdout -- a `portal sync` subprocess failure is swallowed to one stderr line instead.

`repo_root_from_batch_dir()` is the one thing this module exports besides `sync()` itself: a
handful of call sites (`cfq_batch_id.py ready`, `cfq_phase.py record`/`reopen`) only ever see a
batch directory, never the repo root `sync()` needs. It derives it with `git -C <batch-dir>
rev-parse --show-toplevel` -- the same lookup `cfq_phase.py`'s own `cmd_commit` already performs
for its own `repo_root` -- rather than assuming a fixed number of parent directories, which would
break for an archived batch under `impl/done/`.
"""

import os
import sys

from .proc import cfq_run, git, settings_get


def repo_root_from_batch_dir(batch_dir):
    proc = git(batch_dir, "rev-parse", "--show-toplevel")
    return proc.stdout.strip() if proc.returncode == 0 else None


def sync(repo_root, batches=()):
    if not repo_root:
        return
    if os.environ.get("CFQ_PORTAL_SYNC") == "0":
        return
    if settings_get(repo_root, "htmlReport") != "true":
        return

    args = ["portal", "sync", str(repo_root)]
    for b in batches:
        args += ["--batch", b]
    proc = cfq_run(*args)
    if proc.returncode != 0:
        lines = [line for line in proc.stderr.splitlines() if line.strip()]
        last = lines[-1] if lines else proc.stderr.strip()
        print(f"portal sync failed (non-fatal): {last}", file=sys.stderr)
