#!/usr/bin/env python3
# Usage: cfq_pfq_preflight.py <repo-root>
"""Single read-only preflight aggregator for plan-for-queue's Step 1: batches every
cfq_settings.py/cfq_scan.py/cfq_registry.py/cfq_maintenance.py call the skill used to issue
separately (Steps 1, 3, 5, 7, 9a, 11) into one JSON object, one process invocation of
cfq_settings.py covering every policy/language key at once. Security (Step 8) stays a separate
call on purpose -- this only reports capability (a security backend reachable at all), never live
finding counts, which need a network round-trip.

Ported from cfq-pfq-preflight.sh -- a port, not a redesign: every output key is frozen -- an
addition (batch 037 phase 03's `inbox` object) is not a break of that rule, only a removal or
rename would be.
"""

import argparse
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import render, text  # noqa: E402
from cfq_lib.proc import cfq_run, git  # noqa: E402

PROG = "cfq_pfq_preflight.py"

INBOX_HEADER_RE = re.compile(r"^INBOX\s+(\d+) entries")


def inbox_count_from_overview(overview_text):
    """Derives the entry count from `note list --overview`'s own first line (`INBOX  <n>
    entries[ · <k> framework not imported]` or `INBOX  empty`) instead of a second `note list`
    JSON call -- one subprocess call covers both the printable block and the count, and `plan/`
    is never parsed twice in the same preflight run."""
    first_line = overview_text.splitlines()[0] if overview_text else ""
    if first_line == "INBOX  empty":
        return 0
    m = INBOX_HEADER_RE.match(first_line)
    return int(m.group(1)) if m else 0


def model_check_line(allow_any_model):
    """The `Model Check` status line's deterministic half -- mirrors `cfq_ifq_preflight.py`'s
    `model_gate_line`. The actual substring match against the running model's name stays with the
    skill (`references/interview-depth.md`'s **Model Gate**), since only the session itself knows
    its own model, from its own system prompt."""
    if allow_any_model:
        return text.status_entry("Model Check", "skip", "skipped · allowAnyModel")
    return text.status_entry("Model Check", "done", "checked against planModels")


def plugin_boundaries_line(blocked):
    if not blocked:
        return text.status_entry("Plugin Boundaries", "skip", "none blocked")
    return text.status_entry(
        "Plugin Boundaries", "done", f"{len(blocked)} blocked: {', '.join(blocked)}",
    )


def inbox_line(count, imported):
    icon = "skip" if count == 0 else "done"
    detail = f"{count} entries waiting"
    if imported:
        detail += f" · {imported} imported"
    return text.status_entry("Inbox", icon, detail)


def cmd_preflight(args):
    repo = args.repo_root

    resolved = git(repo, "rev-parse", "--show-toplevel")
    if resolved.returncode != 0:
        print(render.dump_json({"status": "NO_REPO", "repo": {"root": repo, "known": False}}))
        return
    repo = resolved.stdout.strip()

    settings = json.loads(cfq_run("settings", "list", "--repo", repo).stdout)

    known = False
    registry = cfq_run("registry", "list").stdout
    if repo in registry.splitlines():
        known = True

    scan_data = json.loads(cfq_run("scan").stdout)
    batches = []
    for r in scan_data.get("repos", []):
        if r.get("path") != repo:
            continue
        for b in r.get("batches", []):
            if not b.get("archived") and b.get("open", 0) > 0:
                batches.append({
                    "name": b["name"], "priority": b["priority"], "open": b["open"],
                    "dependsOn": b["dependsOn"],
                })

    maint_raw = cfq_run("maintenance", "due", repo).stdout.split()
    maint_status = maint_raw[0] if maint_raw else ""
    maint_n = int(maint_raw[1]) if len(maint_raw) > 1 else None

    sec_available = bool(shutil.which("gh") or shutil.which("tea"))

    import_result = json.loads(cfq_run("note", "import", repo).stdout)
    imported_n = len(import_result.get("imported", []))
    inbox_overview = cfq_run("note", "list", repo, "--overview").stdout.rstrip("\n")
    inbox_n = inbox_count_from_overview(inbox_overview)

    print(render.dump_json({
        "status": "OK",
        "repo": {"root": repo, "known": known},
        "planningPolicy": {
            "planModels": settings["planModels"],
            "allowAnyModel": settings["allowAnyModel"],
            "planExploreModel": settings["planExploreModel"],
            "planExploreModelComplex": settings["planExploreModelComplex"],
            "planBlockedPlugins": settings["planBlockedPlugins"],
            "grillMode": settings["grillMode"],
            "useMattpocockGrilling": settings["useMattpocockGrilling"],
            "usePonytailAudit": settings["usePonytailAudit"],
        },
        "language": {
            "codeLanguage": settings["codeLanguage"],
            "docLanguages": settings["docLanguages"],
            "docLevel": settings["docLevel"],
        },
        "queue": {"openBatches": batches},
        "maintenance": {"status": maint_status, "n": maint_n},
        "security": {"available": sec_available},
        "reporting": {"reportDir": settings["reportDir"], "htmlReport": settings["htmlReport"]},
        "inbox": {"count": inbox_n, "imported": imported_n, "overview": inbox_overview},
        "statusLines": [
            model_check_line(settings["allowAnyModel"]),
            inbox_line(inbox_n, imported_n),
            plugin_boundaries_line(settings["planBlockedPlugins"]),
        ],
    }))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    parser.add_argument("repo_root")
    parser.set_defaults(func=cmd_preflight)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
