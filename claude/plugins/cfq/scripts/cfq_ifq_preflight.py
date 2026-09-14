#!/usr/bin/env python3
# Usage: cfq_ifq_preflight.py <repo-root> [--select <batch>]
"""Single read-only preflight aggregator for implement-for-queue's Steps 1-2 (model/plugin policy),
3a (batch selection), 3b's read-only half (briefing) and 4a/4b (failed-attempt lookup, context
gate) -- batches every cfq_settings.py/cfq_scan.py/cfq_brief.py/cfq_resume.py/cfq_report.py
last-failure/ctx_usage.py gate call the skill used to issue separately into one JSON object.
Mutations (cfq_lock.py acquire, git checkout, cfq_changelog.py init, and cfq_branch.py plan's
post-checkout re-confirm on new-mode) stay explicit skill-level steps, never hidden in here -- the
`branch` field below comes from cfq_resume.py's own internal cfq_branch.py call (one process
invocation total on the continue/off path), not a second direct call.

Ported from cfq-ifq-preflight.sh -- a port, not a redesign: every output key is frozen.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import queue as cfq_queue, render  # noqa: E402
from cfq_lib.proc import cfq_run, git  # noqa: E402

PROG = "cfq_ifq_preflight.py"

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent

GATE_LINE_RE = re.compile(
    r"^USED=(?P<used>[^ ]+) SIZE=(?P<size>[A-Z]) LIMIT=(?P<limit>-?[0-9]+) "
    r"(?P<verdict>START|WARN|HANDOFF) REASON=(?P<reason>[a-zA-Z]+) \((?P<note>.*)\)$"
)

EMPTY_SELECTION_TEMPLATE = {
    "batch": None, "nextPhase": None, "branch": None, "resume": None, "contextGate": None,
}


def project(batch, keys):
    return {k: batch[k] for k in keys}


def cmd_preflight(args):
    repo = args.repo_root
    select_batch = args.select or ""

    resolved = git(repo, "rev-parse", "--show-toplevel")
    if resolved.returncode != 0:
        print(render.dump_json({"status": "NO_REPO", "repo": {"root": repo}}))
        return
    repo = resolved.stdout.strip()

    settings = json.loads(cfq_run("settings", "list", "--repo", repo).stdout)
    policy = project(settings, [
        "implModels", "allowAnyModel", "implBlockedPlugins", "onePhasePerSession",
        "implExploreModel", "implExploreModelComplex", "orchestratorMode", "orchestratorModels",
    ])
    if not policy["orchestratorModels"]:
        policy["orchestratorModels"] = policy["implModels"]
    reporting = project(settings, ["reportDir", "htmlReport"])

    scan_data = json.loads(cfq_run("scan").stdout)
    candidates = []
    for r in scan_data.get("repos", []):
        if r.get("path") == repo:
            candidates = [
                b for b in r.get("batches", [])
                if not b["archived"] and (b["open"] > 0 or b["done"] > 0)
            ]
            break

    next_scan = json.loads(cfq_run("scan", "--format=next").stdout)
    next_entry = {"next": None, "reason": None, "blocked": [], "planning": []}
    for r in next_scan.get("repos", []):
        if r.get("path") == repo:
            next_entry = r
            break

    planning_names = next_entry["planning"]
    blocked_names = next_entry["blocked"]
    blocked_json = [
        project(b, ["name", "dependsOn", "unknownDeps"])
        for b in candidates if b["name"] in blocked_names
    ]
    eligible = [b for b in candidates if b["name"] not in blocked_names and b["name"] not in planning_names]

    inprogress_names = [b["name"] for b in eligible if b["inProgress"]]
    inprogress_count = len(inprogress_names)

    def empty_result(status, selectable, inprog, multi):
        return render.dump_json({
            "status": status, "repo": {"root": repo}, "policy": policy, "reporting": reporting,
            "selection": {
                "selectable": selectable, "blocked": blocked_json, "planning": planning_names,
                "inProgress": inprog, "multipleInProgress": multi,
            },
            **EMPTY_SELECTION_TEMPLATE,
        })

    if next_entry["reason"] == "multipleInProgress":
        print(empty_result("MULTIPLE_IN_PROGRESS", [], None, inprogress_names))
        return

    qdir = pathlib.Path(repo) / ".claude" / "cfq" / "impl"

    def project_selectable(b):
        entry = project(b, ["name", "priority", "open", "done", "consistency"])
        entry["goal"] = cfq_queue.read_goal(qdir / b["name"], 120)
        return entry

    if inprogress_count == 1:
        inprogress_name = inprogress_names[0]
        selectable = [project_selectable(b) for b in eligible if b["name"] != inprogress_name]
    else:
        inprogress_name = ""
        selectable = sorted(
            (project_selectable(b) for b in eligible),
            key=lambda b: (0 if b["priority"] == "high" else 1, b["name"]),
        )

    if select_batch and not any(b["name"] == select_batch for b in eligible):
        print(empty_result("SELECT_UNAVAILABLE", selectable, None, []))
        return

    chosen = ""
    if select_batch:
        chosen = select_batch
    elif inprogress_name:
        chosen = inprogress_name
    elif selectable:
        chosen = selectable[0]["name"]

    if not chosen:
        status = "OK"
        if not selectable:
            status = "BLOCKED" if blocked_json else "NO_BATCH"
        print(empty_result(status, selectable, None, []))
        return

    batch_dir = qdir / chosen
    brief_text = cfq_run("brief", str(batch_dir), "--with-done").stdout.rstrip("\n")
    cand = next(b for b in candidates if b["name"] == chosen)

    resume_json = json.loads(cfq_run("resume", repo, str(batch_dir)).stdout)
    branch_json = resume_json["branch"]
    resume_only = {k: v for k, v in resume_json.items() if k != "branch"}

    phases_open = resume_json.get("phasesOpen") or []
    next_phase = phases_open[0] if phases_open else None
    if next_phase is not None:
        next_slug = next_phase["slug"]
        next_size = next_phase["size"]
        failed = json.loads(cfq_run("report", "last-failure", str(batch_dir), next_slug).stdout)
        next_phase_json = {**next_phase, "failedAttempt": failed}

        gate_proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "ctx_usage.py"), "gate", next_size],
            capture_output=True, text=True,
        )
        gate_line = gate_proc.stdout.strip()
        m = GATE_LINE_RE.match(gate_line)
        if m is None:
            print(render.dump_json({
                "status": "GATE_PARSE_FAILED", "detail": gate_line,
                "action": "ctx_usage.py emitted a gate line that does not match the expected "
                          "USED/SIZE/LIMIT/verdict/REASON grammar; check ctx_usage.py and "
                          "cfq_ifq_preflight.py for drift",
            }))
            sys.exit(1)
        used = None if m.group("used") == "?" else int(m.group("used"))
        gate_json = {
            "used": used, "size": m.group("size"), "limit": int(m.group("limit")),
            "verdict": m.group("verdict"), "reason": m.group("reason"), "note": m.group("note"),
        }
    else:
        next_phase_json = None
        gate_json = None

    print(render.dump_json({
        "status": "OK",
        "repo": {"root": repo},
        "policy": policy,
        "reporting": reporting,
        "selection": {
            "selectable": selectable, "blocked": blocked_json, "planning": planning_names,
            "inProgress": inprogress_name or None, "multipleInProgress": [],
        },
        "batch": {
            "name": cand["name"], "priority": cand["priority"], "phaseCount": cand["open"],
            "dependsOn": cand["dependsOn"], "briefText": brief_text,
            "consistency": cand.get("consistency"),
        },
        "nextPhase": next_phase_json,
        "branch": branch_json,
        "resume": resume_only,
        "contextGate": gate_json,
    }))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    parser.add_argument("repo_root")
    parser.add_argument("--select")
    parser.set_defaults(func=cmd_preflight)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
