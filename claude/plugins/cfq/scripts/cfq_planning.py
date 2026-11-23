#!/usr/bin/env python3
# Usage: cfq_planning.py open <repo-root> <YYYY-MM-DD> <slug>
#        cfq_planning.py close <batch-dir> --depth quick|thorough|docs
"""The two bundle commands of a `plan-for-queue` session: `open` runs the security check, the batch
allocation and the security snapshot, `close` runs lint, release, the planning telemetry and the
portal link -- each in a fixed order, each printing one JSON object with a `statusLines` array.

A per-call failure that does not invalidate the rest is recorded in `errors` and the sequence goes
on; the model-driven parts (the `plan/` security entry, what to do with a finding) stay in the
skill, the commands only report what they found. The single commands they run keep their own
behaviour.
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import host_paths, paths, render, text as cfq_text  # noqa: E402
from cfq_lib.proc import cfq_run, settings_get  # noqa: E402

BLOCKING_SEVERITIES = ("critical", "high")


def parse_object(text):
    """The JSON object in `text`, or None when it is not one."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def failure_text(proc):
    return (proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}").splitlines()[-1]


def emit(obj, code=0):
    print(render.dump_json(obj))
    sys.exit(code)


# ---- status lines (the wording is defined here once) -------------------------------------------

def security_line(security, entry_needed, entry_exists, failure=""):
    if security is None:
        return cfq_text.status_entry("Security", "warn", failure or "security call failed")
    if not security.get("available", False):
        return cfq_text.status_entry("Security", "warn", security.get("hint") or "no security source available")
    counts = security.get("counts") or {}
    if not counts:
        return cfq_text.status_entry("Security", "skip", "no findings")
    detail = ", ".join(f"{k}: {v}" for k, v in counts.items())
    if entry_needed and entry_exists:
        detail += " · plan/ entry exists"
    elif entry_needed:
        detail += " · plan/ entry to write"
    return cfq_text.status_entry("Security", "warn", detail)


def lint_line(warnings):
    if warnings:
        return cfq_text.status_entry("Lint", "warn", f"{len(warnings)} warning(s)", sub=warnings)
    return cfq_text.status_entry("Lint", "done", "clean")


def telemetry_line(sync_text, errors):
    if errors:
        return cfq_text.status_entry("Telemetry", "warn", "incomplete", sub=errors)
    return cfq_text.status_entry("Telemetry", "done", sync_text or "recorded")


def portal_line(url):
    if url is None:
        return cfq_text.status_entry("Portal", "skip", "off · htmlReport is not true")
    return cfq_text.status_entry("Portal", "done", url)


# ---- open ----------------------------------------------------------------------------------------

def cmd_open(args):
    repo = pathlib.Path(args.repo_root)
    errs = []

    sec_proc = cfq_run("security", str(repo))
    security = parse_object(sec_proc.stdout)  # the exit code is not read: stdout decides
    sec_failure = ""
    if security is None:
        sec_failure = f"security: {failure_text(sec_proc)}"
        errs.append(sec_failure)

    alloc_proc = cfq_run("batch", "allocate", str(repo), args.date, args.slug)
    alloc = parse_object(alloc_proc.stdout)
    if alloc is None:
        alloc = {"status": "ALLOCATE_FAILED", "detail": failure_text(alloc_proc)}
    if alloc.get("status") != "OK":
        alloc["step"] = "allocate"
        emit(alloc, 1)
    batch_name = alloc["batch"]
    batch_dir = pathlib.Path(paths.impl_dir(repo)) / batch_name

    if security is not None:
        snap = cfq_run("report", "security", str(batch_dir), render.dump_json(security))
        if snap.returncode != 0:
            errs.append(f"report security: {failure_text(snap)}")

    fixable = (security or {}).get("fixable") or {}
    needed = any((fixable.get(sev) or 0) > 0 for sev in BLOCKING_SEVERITIES)
    exists = any(pathlib.Path(paths.plan_dir(repo)).glob("*-security-findings.md"))

    emit({
        "status": "OK",
        "batch": batch_name,
        "batchDir": str(batch_dir),
        "security": security,
        "securityEntry": {"needed": needed, "exists": exists},
        "errors": errs,
        "statusLines": [security_line(security, needed, exists, sec_failure)],
    })


# ---- close ---------------------------------------------------------------------------------------

def cmd_close(args):
    batch_dir = pathlib.Path(args.batch_dir)
    # <repo>/.claude/cfq/impl/<batch>
    repo = batch_dir.resolve().parents[3]
    errs = []

    lint = cfq_run("lint", str(batch_dir))
    lint_lines = [ln for ln in (lint.stdout + lint.stderr).splitlines() if ln.strip()]
    warnings = [ln[len("warn: "):] for ln in lint_lines if ln.startswith("warn: ")]
    if lint.returncode != 0:
        findings = [ln for ln in lint_lines if not ln.startswith("warn: ")]
        emit({"status": "LINT_FAILED", "findings": findings}, 1)

    ready = cfq_run("batch", "ready", str(batch_dir))
    if ready.returncode != 0:
        emit({"status": "NOT_READY", "detail": failure_text(ready)}, 1)

    tel_errs = []
    sync_text = ""
    for step, call in (
        ("telemetry record", ("telemetry", "record", str(batch_dir), "planning", "--depth", args.depth)),
        ("telemetry sync", ("telemetry", "sync", str(repo))),
    ):
        proc = cfq_run(*call)
        # A zero exit with a stderr message is a skip (no transcript, no git repo to sync to).
        if proc.returncode != 0 or proc.stderr.strip():
            tel_errs.append(f"{step}: {failure_text(proc)}")
        elif step == "telemetry sync":
            sync_text = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    show = cfq_run("telemetry", "show", str(repo), "--session")
    cost = parse_object(show.stdout) if show.returncode == 0 else None
    if cost is None:
        tel_errs.append(f"telemetry show: {failure_text(show)}")
    errs.extend(tel_errs)

    portal = None
    if settings_get(str(repo), "htmlReport") == "true":
        portal = host_paths.portal_batch_url(str(repo), batch_dir.name)

    emit({
        "status": "OK",
        "batch": batch_dir.name,
        "warnings": warnings,
        "cost": cost,
        "portal": portal,
        "errors": errs,
        "statusLines": [
            lint_line(warnings),
            cfq_text.status_entry("Release", "done", "ready for /ifq"),
            telemetry_line(sync_text, tel_errs),
            portal_line(portal),
        ],
    })


def build_parser():
    parser = argparse.ArgumentParser(prog="cfq_planning.py")
    sub = parser.add_subparsers(dest="verb", required=True)
    p_open = sub.add_parser("open", help="security check, batch allocation, security snapshot")
    p_open.add_argument("repo_root")
    p_open.add_argument("date", metavar="YYYY-MM-DD")
    p_open.add_argument("slug")
    p_open.set_defaults(func=cmd_open)
    p_close = sub.add_parser("close", help="lint, release, planning telemetry, portal link")
    p_close.add_argument("batch_dir")
    p_close.add_argument("--depth", required=True, choices=("quick", "thorough", "docs"))
    p_close.set_defaults(func=cmd_close)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
