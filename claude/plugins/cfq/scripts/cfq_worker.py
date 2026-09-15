#!/usr/bin/env python3
# Usage: cfq_worker.py brief <batch-dir> --phase <NN>
#        cfq_worker.py verdict <batch-dir>
"""The deterministic spine of orchestrator mode: composing the briefing a phase worker is spawned
with (`brief`), and deciding what the worker's returned report means for the stop rule
(`verdict`). Both are pure functions of data already on disk plus, for `verdict`, the worker's own
JSON report on stdin -- see `.batch-context.md` and `references/ifq-phase.md`'s `## Stop Rule` for
why this must be a script rather than skill prose.

`verdict`'s stdin contract: `{"status": "green"|"red"|"question", "triggers": [...], "question":
"..."}`. `triggers` is the worker's own classification against the post-018 stop rule -- whether a
green phase omitted a planned change or introduced an unnamed dependency is a judgment call the
same as it is in classic mode's Step 8 prose, just made once by the worker instead of raised as an
immediate question it has no channel to ask. `verdict` only translates that self-report into
CONTINUE/ASK/STOP; it never re-derives the classification from `deviations` text, which stays a
plain string list (the existing `report.json` contract `cfq_resume.py`/`cfq_report.py` already
read) and is not inspected here.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_brief import parse_phase_body  # noqa: E402
from cfq_lib import errors, render  # noqa: E402
from cfq_lib.proc import cfq_run  # noqa: E402

PROG = "cfq_worker.py"

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent

HEADING_RE = re.compile(r"^## ")
RECOMMENDED_HEADING_RE = re.compile(r"^## Recommended skills", re.IGNORECASE)
RECOMMENDED_ITEM_RE = re.compile(r"^- ([A-Za-z0-9:._-]+)")

GREEN_TRIGGERS = ("omitted", "dependency")
VALID_STATUSES = ("green", "red", "question")


def find_phase_file(batch_dir, phase_num):
    matches = sorted(batch_dir.glob(f"{phase_num}-*.md")) + sorted(
        (batch_dir / "done").glob(f"{phase_num}-*.md")
    )
    return matches[0] if matches else None


def extract_recommended_skills(text, blocked_plugins):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if RECOMMENDED_HEADING_RE.match(line):
            start = i
            break
    if start is None:
        return []
    block = [lines[start]]
    for line in lines[start + 1:]:
        if HEADING_RE.match(line):
            break
        block.append(line)
    blocked = set(blocked_plugins or [])
    recommended = []
    for line in block:
        m = RECOMMENDED_ITEM_RE.match(line)
        if not m:
            continue
        item = m.group(1)
        if item in blocked or item.split(":", 1)[0] in blocked:
            continue
        recommended.append(item)
    return recommended


def repo_root_of(batch_dir):
    proc = subprocess.run(
        ["git", "-C", str(batch_dir), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else str(batch_dir.parents[3])


def build_commands(plugin_root, repo_root, batch_dir):
    return {
        "phaseCommit": (
            f"{plugin_root}/bin/cfq phase commit {batch_dir} <phase-json-file> <message-file>"
        ),
        "phaseRecordRed": f"{plugin_root}/bin/cfq phase record {batch_dir} <phase-json-file>",
        "notePlan": f"{plugin_root}/bin/cfq note plan {repo_root} <slug> <body-file>",
    }


def cmd_brief(args):
    batch_dir = pathlib.Path(str(args.batch_dir).rstrip("/"))
    if not batch_dir.is_dir():
        print(render.dump_json({
            "status": "NO_BATCH", "batch": batch_dir.name, "batchDir": str(batch_dir),
        }))
        return

    phase_file = find_phase_file(batch_dir, args.phase)
    if phase_file is None:
        print(render.dump_json({
            "status": "NO_BATCH", "batch": batch_dir.name, "batchDir": str(batch_dir.resolve()),
            "phase": args.phase,
        }))
        return

    phase_file = phase_file.resolve()
    batch_dir = batch_dir.resolve()
    phase_slug = phase_file.stem
    text = phase_file.read_text()
    fields = parse_phase_body(text)
    size = fields["size"] or "M"

    ctx_path = batch_dir / ".batch-context.md"
    batch_context = str(ctx_path) if ctx_path.is_file() else None

    repo_root = repo_root_of(batch_dir)

    settings = json.loads(cfq_run("settings", "list", "--repo", repo_root).stdout)
    blocked_plugins = settings.get("implBlockedPlugins", [])
    language = {
        "codeLanguage": settings.get("codeLanguage"),
        "docLanguages": settings.get("docLanguages"),
        "docLevel": settings.get("docLevel"),
    }
    explore_models = {
        "implExploreModel": settings.get("implExploreModel"),
        "implExploreModelComplex": settings.get("implExploreModelComplex"),
    }

    resume_json = json.loads(cfq_run("resume", repo_root, str(batch_dir)).stdout)
    branch = (resume_json.get("branch") or {}).get("branch")
    prior_deviations = resume_json.get("deviations", [])

    failed_attempt = json.loads(
        cfq_run("report", "last-failure", str(batch_dir), phase_slug).stdout
    )

    recommended_skills = extract_recommended_skills(text, blocked_plugins)

    commands = build_commands(str(PLUGIN_ROOT), repo_root, batch_dir)

    print(render.dump_json({
        "status": "OK",
        "batch": batch_dir.name,
        "batchDir": str(batch_dir),
        "phase": phase_slug,
        "phaseFile": str(phase_file),
        "size": size,
        "batchContext": batch_context,
        "branch": branch,
        "language": language,
        "blockedPlugins": blocked_plugins,
        "exploreModels": explore_models,
        "recommendedSkills": recommended_skills,
        "failedAttempt": failed_attempt,
        "priorDeviations": prior_deviations,
        "commands": commands,
    }))


def cmd_verdict(args):
    raw = sys.stdin.read()
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.fail("MALFORMED_REPORT", detail=f"invalid JSON on stdin: {e}")
        return

    status = report.get("status") if isinstance(report, dict) else None
    if status not in VALID_STATUSES:
        errors.fail("MALFORMED_REPORT", detail=f"status must be one of {VALID_STATUSES}, got {status!r}")
        return

    if status == "red":
        print(render.dump_json({"status": "OK", "verdict": "STOP", "triggers": ["red"], "question": None}))
        return

    if status == "question":
        print(render.dump_json({
            "status": "OK", "verdict": "ASK", "triggers": [],
            "question": report.get("question", ""),
        }))
        return

    raw_triggers = report.get("triggers") or []
    triggers = [t for t in raw_triggers if t in GREEN_TRIGGERS]
    verdict = "ASK" if triggers else "CONTINUE"
    print(render.dump_json({"status": "OK", "verdict": verdict, "triggers": triggers, "question": None}))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("brief")
    p.add_argument("batch_dir")
    p.add_argument("--phase", required=True)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("verdict")
    p.add_argument("batch_dir")
    p.set_defaults(func=cmd_verdict)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(f"usage: {PROG} brief <batch-dir> --phase <NN> | verdict <batch-dir>")
        return
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
