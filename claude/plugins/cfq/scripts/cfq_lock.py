#!/usr/bin/env python3
# Usage: cfq_lock.py acquire <repo-root> <batch>
#        cfq_lock.py release <repo-root> [--batch <batch>]
#        cfq_lock.py status <repo-root>
"""One lock per repo: only one implement-for-queue session may work a repo at a time. Liveness
comes from the holder's transcript mtime, not from a fixed expiry.

Ported from cfq-lock.sh -- a port, not a redesign: the CLI contract (verbs, argument order, text
output, exit codes) is the invariant this file preserves.
"""

import argparse
from contextlib import contextmanager
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import portal_hook  # noqa: E402
from cfq_lib import render  # noqa: E402
from cfq_lib.paths import mtime  # noqa: E402
from cfq_lib.proc import cfq_run, settings_get  # noqa: E402

PROG = "cfq_lock.py"


def current_session():
    return cfq_run("runtime", "session-id").stdout.strip()


@contextmanager
def guard(lock_path):
    """Serialize the read/check/write transaction across local harness processes."""
    path = str(lock_path) + ".guard"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_lock(f):
    try:
        return json.loads(pathlib.Path(f).read_text())
    except (OSError, ValueError):
        return {}


def liveness(data, fallback_epoch, stale_s):
    now = int(time.time())
    t = data.get("transcript") or ""
    if t and os.path.isfile(t):
        age = now - mtime(t)
    else:
        age = now - int(fallback_epoch or 0)
    return "alive" if age < int(stale_s) else "dead"


def cmd_acquire(args):
    repo, batch = args.repo, args.batch
    sid = current_session()
    if not sid or sid == "unknown":
        errors.die(f"{PROG}: RUNTIME_UNBOUND: no harness session id; check CFQ hook trust")
    cfq_run("layout", "ensure", repo)
    stale_s = settings_get(repo, "sessionStaleSeconds")
    f = cfq_lib_paths.lockfile(repo)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tpath = cfq_run("runtime", "transcript-path", "--repo", repo, "--exact").stdout.strip()
    with guard(f):
        if os.path.isfile(f):
            data = read_lock(f)
            holder = data.get("session_id", "")
            hbatch = data.get("batch", "")
            hepoch = data.get("epoch", 0)
            if holder == sid:
                print(f"OK {hbatch} (already held by this session)")
                return
            state = liveness(data, hepoch, stale_s)
            if state == "alive":
                print(f"LOCKED {holder} {hbatch} {data.get('at', '?')}", file=sys.stderr)
                sys.exit(1)
            print(f"TAKEOVER {holder} {hbatch} (stale)", file=sys.stderr)

        payload = {"session_id": sid, "batch": batch, "transcript": tpath,
                   "harness": os.environ.get("CFQ_HARNESS") or "claude",
                   "at": render.now_iso(), "epoch": int(time.time())}
        render.write_text_atomic(f, json.dumps(payload))
    portal_hook.sync(repo, batches=[batch])
    print(f"OK {batch}")


def cmd_release(args):
    repo = args.repo
    f = cfq_lib_paths.lockfile(repo)
    if not os.path.isfile(f):
        print("FREE")
        return
    sid = current_session()
    if not sid or sid == "unknown":
        errors.die(f"{PROG}: RUNTIME_UNBOUND: no harness session id; check CFQ hook trust")
    with guard(f):
        if not os.path.isfile(f):
            print("FREE")
            return
        data = read_lock(f)
        holder = data.get("session_id", "")
        if holder != sid:
            stale_s = settings_get(repo, "sessionStaleSeconds")
            stale = liveness(data, data.get("epoch", 0), stale_s) == "dead"
            if args.batch and data.get("batch") == args.batch and stale:
                print(f"{PROG}: releasing stale lock for batch {args.batch} held by {holder}", file=sys.stderr)
            else:
                suffix = f" (lock batch {data.get('batch')}, given {args.batch})" if args.batch else ""
                errors.die(f"{PROG}: lock held by {holder}, not releasing{suffix}")
        os.remove(f)
    print("FREE")


def cmd_status(args):
    repo = args.repo
    f = cfq_lib_paths.lockfile(repo)
    if not os.path.isfile(f):
        print("FREE")
        return
    stale_s = settings_get(repo, "sessionStaleSeconds")
    data = read_lock(f)
    hepoch = data.get("epoch", 0)
    state = liveness(data, hepoch, stale_s)
    print(f"{state.upper()} {data.get('session_id', '')} {data.get('batch', '')} {data.get('at', '')}")


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("acquire")
    p.add_argument("repo")
    p.add_argument("batch")
    p.set_defaults(func=cmd_acquire)

    p = sub.add_parser("release")
    p.add_argument("repo")
    p.add_argument("--batch", default=None)
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("status")
    p.add_argument("repo")
    p.set_defaults(func=cmd_status)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} acquire <repo-root> <batch> | "
            f"release <repo-root> [--batch <batch>] | status <repo-root>"
        )
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
