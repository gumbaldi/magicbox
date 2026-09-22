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

from cfq_lib import queue as cfq_queue, render, text  # noqa: E402
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


def render_queue_text(selectable, blocked, planning, in_progress, chosen):
    """The `QUEUE · <n> open` block the ifq start gate (a later phase) prints: one row per open
    batch across `selectable` (already sorted flagged-first-then-name, per its own caller),
    `blocked` and `planning`, the latter two appended after in name order. Status resolution is
    first-match-wins: in progress, then planning, then blocked (with its wait list and any
    unknown dependency folded into the same cell), then selected, then plain ready -- a `high`
    priority entry gets that whole cell prefixed with `high · `. Empty input -> "" (never a bare
    header) -- see references/ifq-batch-start.md for the field this rides on."""
    blocked_by_name = {b["name"]: b for b in blocked}
    planning_set = set(planning)
    combined = (
        list(selectable)
        + sorted(blocked, key=lambda b: b["name"])
        + [{"name": n} for n in sorted(planning)]
    )
    if not combined:
        return ""

    rows = []
    for entry in combined:
        name = entry["name"]
        if name == in_progress:
            status = "in progress"
        elif name in planning_set:
            status = "planning"
        elif name in blocked_by_name:
            dep = blocked_by_name[name]
            status = f"blocked → waits on {', '.join(dep.get('dependsOn') or [])}"
            unknown = dep.get("unknownDeps") or []
            if unknown:
                status += f" ⚠️ unknown: {', '.join(unknown)}"
        elif name == chosen:
            status = "ready · selected"
        else:
            status = "ready"
        if entry.get("priority") == "high":
            status = f"high · {status}"

        parsed = text.parse_batch_name(name)
        number = name.split("-", 1)[0] if parsed["number"] is not None else name
        rows.append([number, parsed["date"] or "", parsed["slug"], status])

    lines = [f"QUEUE · {len(rows)} open"]
    lines += text.table(rows, headers=["#", "Date", "Topic", "Status"])
    return "\n".join(lines)


def model_gate_line(policy):
    """The `Model Gate` status line's deterministic half -- which list the running model will be
    checked against. The actual substring match against the running model's name (only known to
    the session itself, from its own system prompt -- see `references/ifq-batch-start.md`'s
    **Model Gate Stop**) stays with the skill; this line is printed either way, before that check
    runs."""
    if policy["allowAnyModel"]:
        return text.status_entry("Model Gate", "skip", "skipped · allowAnyModel")
    list_name = "orchestratorModels" if policy["orchestratorMode"] else "implModels"
    return text.status_entry("Model Gate", "done", f"checked against {list_name}")


def plugin_boundaries_line(policy):
    blocked = policy["implBlockedPlugins"]
    if not blocked:
        return text.status_entry("Plugin Boundaries", "skip", "none blocked")
    return text.status_entry(
        "Plugin Boundaries", "done", f"{len(blocked)} blocked: {', '.join(blocked)}",
    )


def batch_line(*, select_batch, inprogress_name, selectable, chosen, cand, resume_only, orchestrator_mode):
    """The four `Batch` phrasings `references/ifq-batch-start.md` used to spell out by hand --
    the distinguishing condition (`--select` given, in-progress set, `selectable` length) already
    lives right here, so the branch and the wording move together."""
    flagged = cand["priority"] == "high"
    divergent = cand.get("consistency") == "divergent"
    prefix = "high · " if flagged else ""
    suffix = " ⚠️ divergent" if divergent else ""
    mode = "orchestrator" if orchestrator_mode else "classic"
    n_open = cand["open"]
    if select_batch and chosen == select_batch:
        detail = f"{prefix}{cand['name']} · selected by argument · {n_open} phases · mode={mode}{suffix}"
    elif inprogress_name and chosen == inprogress_name:
        done_n = len(resume_only.get("phasesDone") or [])
        open_n = len(resume_only.get("phasesOpen") or [])
        detail = (
            f"{prefix}resumed {cand['name']} · {done_n}/{done_n + open_n} phases done · "
            f"mode={mode}{suffix}"
        )
    elif len(selectable) == 1:
        detail = f"{prefix}{cand['name']} · only open batch · {n_open} phases · mode={mode}{suffix}"
    else:
        detail = f"{prefix}{cand['name']} · next in order · {n_open} phases · mode={mode}{suffix}"
    return text.status_entry("Batch", "done", detail)


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

    qdir = pathlib.Path(repo) / ".claude" / "cfq" / "impl"

    def project_selectable(b):
        entry = project(b, ["name", "priority", "open", "done", "consistency"])
        entry["goal"] = cfq_queue.read_goal(qdir / b["name"], 120)
        return entry

    # Every open, non-blocked, non-planning batch -- the in-progress one included -- projected
    # and sorted flagged-first-then-name. Feeds render_queue_text's `selectable` argument on
    # every return path below, independent of `selection.selectable` itself (which still excludes
    # a lone in-progress batch, unchanged from before this phase) so the queue block always shows
    # that row too, marked `in progress` rather than dropped.
    queue_rows = sorted(
        (project_selectable(b) for b in eligible),
        key=lambda b: (0 if b["priority"] == "high" else 1, b["name"]),
    )

    inprogress_names = [b["name"] for b in eligible if b["inProgress"]]
    inprogress_count = len(inprogress_names)

    def empty_result(status, selectable, inprog, multi):
        return render.dump_json({
            "status": status, "repo": {"root": repo}, "policy": policy, "reporting": reporting,
            "selection": {
                "selectable": selectable, "blocked": blocked_json, "planning": planning_names,
                "inProgress": inprog, "multipleInProgress": multi,
                "queueText": render_queue_text(queue_rows, blocked_json, planning_names, inprog or "", "") or None,
            },
            "statusLines": [model_gate_line(policy), plugin_boundaries_line(policy)],
            **EMPTY_SELECTION_TEMPLATE,
        })

    if next_entry["reason"] == "multipleInProgress":
        print(empty_result("MULTIPLE_IN_PROGRESS", [], None, inprogress_names))
        return

    if inprogress_count == 1:
        inprogress_name = inprogress_names[0]
        selectable = [b for b in queue_rows if b["name"] != inprogress_name]
    else:
        inprogress_name = ""
        selectable = queue_rows

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
            "queueText": render_queue_text(queue_rows, blocked_json, planning_names, inprogress_name, chosen) or None,
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
        "statusLines": [
            model_gate_line(policy), plugin_boundaries_line(policy),
            batch_line(
                select_batch=select_batch, inprogress_name=inprogress_name, selectable=selectable,
                chosen=chosen, cand=cand, resume_only=resume_only,
                orchestrator_mode=policy["orchestratorMode"],
            ),
        ],
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
