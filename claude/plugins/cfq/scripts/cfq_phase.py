#!/usr/bin/env python3
# Usage: cfq_phase.py record <batch-dir> <phase-json-file> [--no-telemetry]
#        cfq_phase.py commit <batch-dir> <phase-json-file> <message-file>
#        cfq_phase.py reopen <batch-dir> <phase-slug>
#        cfq_phase.py skip <batch-dir> <phase> [--reason <text>]
#        cfq_phase.py unskip <batch-dir> <phase>
"""Closing (and reopening) a phase as one transaction, not several agent-issued operations in the
wrong order with a `mkdir -p` improvised in between -- that gap is where an accidental `rm -rf`
on a batch's `done/` directory originated (see `.batch-context.md`).

`record` either moves the phase's `.md` file into `done/` and appends its ledger entry, or does
neither -- the red-phase path, and `commit`'s own last resort once its own commit has already
succeeded (see `cmd_commit`). `commit` is the green-phase path: it commits whatever is staged,
then records, backfills the commit SHA, pushes and registers the repo, all from one call, and
reports the phase's cost (a `Cost` status line) alongside the commit result, so a
green phase costs one `bin/cfq` invocation instead of the five or six it used to (`phase record`,
`changelog commit-message`, `git commit`, `git push`, `git rev-parse HEAD`, `report set-commit`,
`registry add`). `reopen` is `record`'s inverse: it moves a phase back out of `done/` and marks the
ledger entry `reopened`, never erasing `status`/`commit` -- that history is what `/rfq` and `ifq`
Step 5's failed-attempt detection read. `skip` takes an `open` or `error` phase out of the way
without implementing it (file into `skipped/`, a `skipped` ledger entry), `unskip` brings it back
to the status it held before.

Every verb changes the phase through `cfq_lib/phase_state.py`, so `status.json` -- the authority
for a phase's state -- and the `done/` / `skipped/` mirror directories move together; a batch
directory without a readable `status.json` is refused with `STATUS_FILE_MISSING` /
`STATUS_FILE_INVALID` before anything is touched.
"""

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cfq_changelog  # noqa: E402
import cfq_registry  # noqa: E402
import cfq_report  # noqa: E402
from cfq_lib import errors, phase_state, portal_hook, render, text  # noqa: E402

PROG = "cfq_phase.py"


def commit_status_line(result):
    """`references/ifq-phase.md`'s **Commit Result Rendering** branch table (`OK`/`NOTHING_STAGED`/
    `COMMIT_FAILED`/`RECORD_FAILED`), rendered here instead of re-derived by the skill every
    session -- the branch condition (`result["status"]`) already lives right where the result
    itself is built."""
    status = result.get("status")
    if status == "OK":
        detail = result["branch"] + (" · pushed" if result["pushed"] else " · not pushed")
        icon = "done" if result["pushed"] else "warn"
        sub = [result["pushError"]] if result.get("pushError") else []
        return text.status_entry("Commit", icon, detail, sub=sub)
    if status == "NOTHING_STAGED":
        return text.status_entry("Commit", "warn", "nothing staged")
    if status in ("COMMIT_FAILED", "RECORD_FAILED"):
        return text.status_entry("Commit", "fail", result.get("detail") or status)
    return text.status_entry("Commit", "fail", status or "unknown")


def _state_fail(batch_dir, e):
    """Maps a `PhaseStateError` onto the structured error shape. The two status.json codes name
    the batch directory only -- there is no migration hint in the framework."""
    if e.code in ("STATUS_FILE_MISSING", "STATUS_FILE_INVALID"):
        errors.fail(e.code, detail=str(batch_dir))
    errors.fail(e.code, detail=e.message)


def _statuses(batch_dir):
    """slug -> status over the batch's status.json; refuses a missing or unreadable file."""
    try:
        return {s: v["status"] for s, v in phase_state.load(batch_dir)["phases"].items()}
    except phase_state.PhaseStateError as e:
        _state_fail(batch_dir, e)


def _ledger_entry_index(phases, slug, pred=lambda p: True):
    """Index of the last ledger entry for `slug` that satisfies `pred` -- the same last-match
    rule as cfq_report.py's set-commit: with two entries for one slug, the later attempt wins."""
    matches = [
        i for i, p in enumerate(phases)
        if isinstance(p, dict) and p.get("phase") == slug and pred(p)
    ]
    return matches[-1] if matches else None


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
    # Same slug pattern `append_phase` enforces, imported rather than re-declared -- checked
    # here too, before any file is touched, so a bare phase number never moves anything.
    if not isinstance(phase_id, str) or not cfq_report.PHASE_ID_RE.match(phase_id):
        errors.die(
            f"{PROG} record: phase must be the full phase slug (NN-slug), got '{phase_id}'"
        )

    status = phase_obj.get("status") if isinstance(phase_obj, dict) else None
    if status not in ("green", "red"):
        errors.die(f"{PROG} record: status must be 'green' or 'red', got '{status}'")

    batch_dir = pathlib.Path(dir_)
    current = _statuses(batch_dir).get(phase_id)
    if current is None:
        _state_fail(batch_dir, phase_state.PhaseStateError(
            "UNKNOWN_PHASE", f"no phase '{phase_id}' in {batch_dir.name}"))
    if current == "done":
        errors.fail("ALREADY_RECORDED", detail=f"{phase_id} is already in done/")
    if phase_state.locate(batch_dir, phase_id) is None:
        errors.die(f"{PROG} record: no such phase file {batch_dir / (phase_id + '.md')}")

    snap = phase_state.snapshot(batch_dir, phase_id)
    try:
        new_path = phase_state.transition(
            batch_dir, phase_id, "done" if status == "green" else "error")
    except phase_state.PhaseStateError as e:
        _state_fail(batch_dir, e)
    except OSError as e:
        errors.die(f"{PROG} record: could not move {phase_id}.md: {e}")

    try:
        cfq_report.append_phase(dir_, phase_json, record_telemetry=not args.no_telemetry)
    except (SystemExit, OSError):
        phase_state.restore(batch_dir, phase_id, snap)
        raise

    portal_hook.sync(portal_hook.repo_root_from_batch_dir(dir_), batches=[batch_dir.name])

    print(str(new_path))


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


QUEUE_PREFIX = ".claude/cfq/"


def commit_diffstat(repo_root, sha):
    """The commit's changed files with added/deleted line counts, straight from `git show
    --numstat` (renames split into a deletion and an addition, queue files left out). A binary
    file carries `None` counts and is not summed. Returns None when git fails -- the diffstat is a
    nicety that must never stop a phase from closing."""
    proc = _git(repo_root, "show", "--numstat", "--no-renames", "--format=", sha)
    if proc.returncode != 0:
        return None
    paths = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or parts[2].startswith(QUEUE_PREFIX):
            continue
        added, deleted, path = parts
        paths.append({
            "path": path,
            "added": None if added == "-" else int(added),
            "deleted": None if deleted == "-" else int(deleted),
        })
    paths.sort(key=lambda p: p["path"])
    return {
        "files": len(paths),
        "insertions": sum(p["added"] or 0 for p in paths),
        "deletions": sum(p["deleted"] or 0 for p in paths),
        "paths": paths,
    }


def _last_stderr_line(stderr):
    lines = [line for line in stderr.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("error:") or line.startswith("fatal:"):
            return line
    return lines[-1] if lines else stderr.strip()


def cmd_commit(args):
    """The green-phase path: commit whatever the model already staged, then record, backfill the
    SHA, push and register the repo -- one call in place of the six a green phase used to issue
    one at a time. Staging stays with the model; this never runs `git add`. Every stop after a
    successful commit reports the SHA rather than undoing it -- `bin/cfq batch verify` is what
    reconciles a commit whose record/push tail didn't finish, not a revert here."""
    dir_ = args.dir
    if not pathlib.Path(dir_).is_dir():
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    try:
        phase_json = pathlib.Path(args.phase_file).read_text()
    except OSError as e:
        errors.die(f"{PROG} commit: cannot read {args.phase_file}: {e}")

    try:
        phase_obj = json.loads(phase_json)
    except json.JSONDecodeError as e:
        errors.die(f"{PROG} commit: invalid JSON in {args.phase_file}: {e}")

    phase_id = phase_obj.get("phase") if isinstance(phase_obj, dict) else None
    if not isinstance(phase_id, str) or not cfq_report.PHASE_ID_RE.match(phase_id):
        errors.die(f"{PROG} commit: phase must be the full phase slug (NN-slug), got '{phase_id}'")

    status = phase_obj.get("status") if isinstance(phase_obj, dict) else None
    if status != "green":
        errors.die(
            f"{PROG} commit: status must be 'green' (red phases use 'phase record'), got '{status}'"
        )

    batch_dir = pathlib.Path(dir_)
    current = _statuses(batch_dir).get(phase_id)
    if current is None:
        _state_fail(batch_dir, phase_state.PhaseStateError(
            "UNKNOWN_PHASE", f"no phase '{phase_id}' in {batch_dir.name}"))
    if current not in phase_state.PENDING:
        _state_fail(batch_dir, phase_state.PhaseStateError(
            "INVALID_TRANSITION", f"{phase_id}: {current} -> done is not allowed"))
    root_path = batch_dir / f"{phase_id}.md"
    if not root_path.is_file():
        errors.die(f"{PROG} commit: no such phase file {root_path}")

    repo_root = _git(dir_, "rev-parse", "--show-toplevel").stdout.strip()
    if not repo_root:
        errors.die(f"{PROG} commit: {dir_} is not inside a git repository")

    if _git(repo_root, "diff", "--cached", "--quiet").returncode == 0:
        result = {"status": "NOTHING_STAGED"}
        result["statusLines"] = [commit_status_line(result)]
        print(render.dump_json(result))
        sys.exit(1)

    batch = pathlib.Path(dir_).name
    message = cfq_changelog.compose_commit_message(
        repo_root, batch, phase_id, "green", args.message_file
    )
    commit = subprocess.run(
        ["git", "-C", repo_root, "commit", "-F", "-"], input=message, capture_output=True, text=True,
    )
    if commit.returncode != 0:
        result = {"status": "COMMIT_FAILED", "detail": _last_stderr_line(commit.stderr)}
        result["statusLines"] = [commit_status_line(result)]
        print(render.dump_json(result))
        sys.exit(1)

    try:
        phase_state.transition(batch_dir, phase_id, "done")
        cfq_report.append_phase(dir_, phase_json, record_telemetry=True)
    except (OSError, SystemExit, phase_state.PhaseStateError) as e:
        sha = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
        result = {"status": "RECORD_FAILED", "sha": sha, "detail": str(e)}
        result["statusLines"] = [commit_status_line(result)]
        print(render.dump_json(result))
        sys.exit(1)

    sha = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    cfq_report.set_commit(dir_, phase_id, sha, diffstat=commit_diffstat(repo_root, sha))

    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    upstream = _git(repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    tracks_self = upstream.returncode == 0 and upstream.stdout.strip() == f"origin/{branch}"
    push = _git(repo_root, "push") if tracks_self else _git(repo_root, "push", "-u", "origin", branch)

    cfq_registry.add_repo(repo_root)
    portal_hook.sync(repo_root, batches=[pathlib.Path(dir_).name])

    result = {"status": "OK", "sha": sha, "pushed": push.returncode == 0, "branch": branch}
    if push.returncode != 0:
        result["pushError"] = _last_stderr_line(push.stderr)
    result["statusLines"] = [commit_status_line(result)]
    # The second entry, `Cost`, is rendered from the ledger entry just written -- see
    # `cfq_report.phase_cost_entry()`; absent without a telemetry record.
    cost = cfq_report.phase_cost_entry(dir_, phase_id)
    if cost is not None:
        result["statusLines"].append(cost)
    print(render.dump_json(result))


def cmd_reopen(args):
    dir_, phase_slug = args.dir, args.phase_slug
    if not pathlib.Path(dir_).is_dir():
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    batch_dir = pathlib.Path(dir_)
    if _statuses(batch_dir).get(phase_slug) != "done":
        errors.fail("NOT_DONE", detail=f"{phase_slug} is not done")

    f = batch_dir / "report.json"
    if not f.is_file():
        errors.die(f"{PROG}: no report.json in {dir_}")
    data = json.loads(f.read_text())
    phases = data.get("phases", [])
    idx = _ledger_entry_index(phases, phase_slug)
    if idx is None:
        errors.die(f"{PROG} reopen: no phase entry '{phase_slug}' in {f}")

    snap = phase_state.snapshot(batch_dir, phase_slug)
    try:
        root_path = phase_state.transition(batch_dir, phase_slug, "open")
    except phase_state.PhaseStateError as e:
        _state_fail(batch_dir, e)
    try:
        phases[idx]["reopened"] = render.now_iso()
        render.write_json(str(f), data)
    except OSError:
        phase_state.restore(batch_dir, phase_slug, snap)
        raise

    portal_hook.sync(portal_hook.repo_root_from_batch_dir(dir_), batches=[batch_dir.name])

    print(str(root_path))


def cmd_skip(args):
    """Takes an `open` or `error` phase out of the way: file into `skipped/`, status `skipped`
    (remembering the earlier status), one `skipped` ledger entry. Only ever user-initiated."""
    dir_ = args.dir
    batch_dir = pathlib.Path(dir_)
    if not batch_dir.is_dir():
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    try:
        slug = phase_state.resolve_slug(batch_dir, args.phase)
        snap = phase_state.snapshot(batch_dir, slug)
        previous = snap["entry"]["status"]
        path = phase_state.transition(batch_dir, slug, "skipped", reason=args.reason or None)
    except phase_state.PhaseStateError as e:
        _state_fail(batch_dir, e)

    reason = args.reason or ""
    entry = {
        "phase": slug, "status": "skipped", "summary": reason,
        "previous": previous, "finished": render.now_iso(),
    }
    try:
        cfq_report.append_phase(dir_, json.dumps(entry), record_telemetry=False)
    except (SystemExit, OSError):
        phase_state.restore(batch_dir, slug, snap)
        raise

    portal_hook.sync(portal_hook.repo_root_from_batch_dir(dir_), batches=[batch_dir.name])

    detail = f"{slug} · was {previous}" + (f" · {reason}" if reason else "")
    print(render.dump_json({
        "status": "OK", "phase": slug, "previous": previous, "reason": reason,
        "path": str(path) if path else None,
        "statusLines": [text.status_entry("Skip", "done", detail)],
    }))


def cmd_unskip(args):
    """Brings a skipped phase back to the status it held before the skip and marks the skip's
    ledger entry `unskipped`."""
    dir_ = args.dir
    batch_dir = pathlib.Path(dir_)
    if not batch_dir.is_dir():
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    try:
        slug = phase_state.resolve_slug(batch_dir, args.phase)
        snap = phase_state.snapshot(batch_dir, slug)
        path, restored = phase_state.unskip(batch_dir, slug)
    except phase_state.PhaseStateError as e:
        if e.code == "INVALID_TRANSITION":
            errors.fail("NOT_SKIPPED", detail=e.message)
        _state_fail(batch_dir, e)

    f = batch_dir / "report.json"
    try:
        if f.is_file():
            data = json.loads(f.read_text())
            phases = data.get("phases", [])
            idx = _ledger_entry_index(
                phases, slug, lambda p: p.get("status") == "skipped" and "unskipped" not in p)
            if idx is not None:
                phases[idx]["unskipped"] = render.now_iso()
                render.write_json(str(f), data)
    except (OSError, ValueError):
        phase_state.restore(batch_dir, slug, snap)
        raise

    portal_hook.sync(portal_hook.repo_root_from_batch_dir(dir_), batches=[batch_dir.name])

    print(render.dump_json({
        "status": "OK", "phase": slug, "previous": "skipped", "restored": restored,
        "reason": (snap["entry"] or {}).get("reason", ""),
        "path": str(path) if path else None,
        "statusLines": [text.status_entry("Unskip", "done", f"{slug} · back to {restored}")],
    }))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("record")
    p.add_argument("dir")
    p.add_argument("phase_file")
    p.add_argument("--no-telemetry", action="store_true")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("commit")
    p.add_argument("dir")
    p.add_argument("phase_file")
    p.add_argument("message_file")
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("reopen")
    p.add_argument("dir")
    p.add_argument("phase_slug")
    p.set_defaults(func=cmd_reopen)

    p = sub.add_parser("skip")
    p.add_argument("dir")
    p.add_argument("phase")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_skip)

    p = sub.add_parser("unskip")
    p.add_argument("dir")
    p.add_argument("phase")
    p.set_defaults(func=cmd_unskip)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} record <batch-dir> <phase-json-file> [--no-telemetry] | "
            f"commit <batch-dir> <phase-json-file> <message-file> | "
            f"reopen <batch-dir> <phase-slug> | "
            f"skip <batch-dir> <phase> [--reason <text>] | "
            f"unskip <batch-dir> <phase>"
        )
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
