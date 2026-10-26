#!/usr/bin/env python3
# Usage: cfq_worker.py brief <batch-dir> --phase <NN> [--model-override <name>] [--handover-file <path>]
#        cfq_worker.py verdict <batch-dir>
"""The deterministic spine of orchestrator mode: composing the briefing a phase worker is spawned
with (`brief`), and deciding what the worker's returned report means for the stop rule
(`verdict`). Both are pure functions of data already on disk plus, for `verdict`, the worker's own
JSON report on stdin -- see `.batch-context.md` and `references/ifq-phase.md`'s `## Stop Rule` for
why this must be a script rather than skill prose.

`brief` writes the full briefing object to `<batch-dir>/.worker-brief.json` (one file per batch,
replaced on every call) and prints a small object: `status`, `batch`, `batchDir`, `phase`,
`briefFile`, `prompt` (the one line that names the file, passed to the worker unchanged), the
`model` and `escalation` the orchestrator reads itself, and `announcement`. A batch or phase that
does not resolve prints `NO_BATCH` and writes no file; an unwritable file exits non-zero with one
line on standard error and nothing on standard output.

`verdict`'s stdin contract: `{"status": "green"|"red"|"question", "triggers": [...], "question":
"..."}`; `"escalate"` (with a `handover` object) is the fourth status and returns `ESCALATE`.
`triggers` is the worker's own classification against the post-018 stop rule -- whether a
green phase omitted a planned change or introduced an unnamed dependency is a judgment call the
same as it is in `references/ifq-classic.md`'s **Implementation** prose, just made once by the worker instead of raised as an
immediate question it has no channel to ask. `verdict` only translates that self-report into
CONTINUE/ASK/STOP (or ESCALATE); it never re-derives the classification from `deviations` text, which stays a
plain string list (the existing `report.json` contract `cfq_resume.py`/`cfq_report.py` already
read) and is not inspected here.

Every result also carries `statusLines`: for `green` and `red` the phase's `Cost` entry rendered
from its ledger entry in `<batch-dir>/report.json` (`cfq_report.phase_cost_line()`), a list of
one -- the `⚠️ Cost` warning entry when there is no usable telemetry or the report names no phase;
for `question` always `[]`. The orchestrator prints those lines verbatim, so the cost summary costs no call of
its own.
"""

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cfq_report  # noqa: E402
from cfq_brief import parse_phase_body, phase_num, render_phase  # noqa: E402
from cfq_lib import errors, phase_state, render  # noqa: E402
from cfq_lib.proc import cfq_run  # noqa: E402

PROG = "cfq_worker.py"

BRIEF_FILE = ".worker-brief.json"

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent

GREEN_TRIGGERS = ("omitted", "dependency")
VALID_STATUSES = ("green", "red", "question", "escalate")

# Capability order, weakest first. Used only to find the next stronger entry inside implModels
# when a worker escalates; a name missing here is never an escalation target.
MODEL_RANK = ("haiku", "sonnet", "opus", "fable")


def default_model(settings):
    """The model a phase runs on when its heading names none: the first orchestrator model, else
    the first implementation model."""
    for key in ("orchestratorModels", "implModels"):
        models = settings.get(key) or []
        if models:
            return models[0]
    return None


def resolve_model(phase_model, settings, failed_attempt_found):
    """(model, source) the worker is spawned on. A phase heading wins only when that model is in
    implModels and the phase has no recorded failed attempt."""
    default = default_model(settings)
    if not phase_model:
        return default, "default"
    if failed_attempt_found:
        return default, "default-after-failure"
    if phase_model not in (settings.get("implModels") or []):
        return default, "default-not-allowed"
    return phase_model, "phase"


def next_stronger(model, settings):
    """The lowest-ranked model above `model` among implModels plus the default, or None."""
    if model not in MODEL_RANK:
        return None
    pool = set(settings.get("implModels") or [])
    default = default_model(settings)
    if default:
        pool.add(default)
    above = [m for m in pool if m in MODEL_RANK and MODEL_RANK.index(m) > MODEL_RANK.index(model)]
    return min(above, key=MODEL_RANK.index) if above else None


def find_phase_file(batch_dir, phase_num):
    try:
        return phase_state.locate(batch_dir, phase_state.resolve_slug(batch_dir, phase_num))
    except phase_state.PhaseStateError:
        return None


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
        "notePlanFramework": (
            f"{plugin_root}/bin/cfq note plan --framework {repo_root} <slug> <body-file>"
        ),
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
    fields = parse_phase_body(text, fallback_title=phase_slug)
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

    model, model_source = resolve_model(fields.get("model"), settings, failed_attempt.get("found"))
    handover = None
    if args.model_override:
        allowed = set(settings.get("implModels") or []) | {default_model(settings)}
        if args.model_override not in allowed:
            errors.fail(
                "MODEL_OVERRIDE_NOT_ALLOWED",
                detail=f"{args.model_override!r} is neither in implModels nor the default model",
            )
            return
        model, model_source = args.model_override, "escalated"
    if args.handover_file:
        try:
            handover = json.loads(pathlib.Path(args.handover_file).read_text())
        except (OSError, ValueError) as e:
            errors.fail("HANDOVER_UNREADABLE", detail=f"{args.handover_file}: {e}")
            return

    commands = build_commands(str(PLUGIN_ROOT), repo_root, batch_dir)

    brief_file = batch_dir / BRIEF_FILE
    try:
        render.write_json(brief_file, {
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
            "failedAttempt": failed_attempt,
            "model": model,
            "modelSource": model_source,
            "escalation": {"next": next_stronger(model, settings)},
            "handover": handover,
            "priorDeviations": prior_deviations,
            "commands": commands,
        })
    except OSError as e:
        errors.die(f"cannot write the worker briefing {brief_file}: {e}")
        return

    print(render.dump_json({
        "status": "OK",
        "batch": batch_dir.name,
        "batchDir": str(batch_dir),
        "phase": phase_slug,
        "briefFile": str(brief_file),
        "prompt": f"Read your briefing at {brief_file} first, then implement that phase.",
        "model": model,
        "escalation": {"next": next_stronger(model, settings)},
        "announcement": render_phase(phase_num(phase_file), fields),
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

    status_lines = []
    if status in ("green", "red"):
        status_lines = [cfq_report.phase_cost_line(args.batch_dir, report.get("phase"))]

    if status == "red":
        print(render.dump_json({
            "status": "OK", "verdict": "STOP", "triggers": ["red"], "question": None,
            "statusLines": status_lines,
        }))
        return

    if status == "escalate":
        handover = report.get("handover")
        if not isinstance(handover, dict):
            errors.fail("MALFORMED_REPORT", detail="status escalate needs a handover object")
            return
        print(render.dump_json({
            "status": "OK", "verdict": "ESCALATE", "triggers": [], "question": None,
            "handover": handover,
        }))
        return

    if status == "question":
        print(render.dump_json({
            "status": "OK", "verdict": "ASK", "triggers": [],
            "question": report.get("question", ""), "statusLines": [],
        }))
        return

    raw_triggers = report.get("triggers") or []
    triggers = [t for t in raw_triggers if t in GREEN_TRIGGERS]
    verdict = "ASK" if triggers else "CONTINUE"
    print(render.dump_json({
        "status": "OK", "verdict": verdict, "triggers": triggers, "question": None,
        "statusLines": status_lines,
    }))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("brief")
    p.add_argument("batch_dir")
    p.add_argument("--phase", required=True)
    p.add_argument("--model-override")
    p.add_argument("--handover-file")
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
