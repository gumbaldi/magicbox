#!/usr/bin/env python3
# Usage: cfq_portal.py sync <repo-root> [--batch <name>]...
#        cfq_portal.py rebuild <repo-root>
"""Writes the data layer behind `<repo>/.claude/cfq/reports/index.html` (the viewer itself is
phase 02): one `.js` file per batch's plan, one per batch's implementation report, one per open
`todo`/`plan` entry, plus `data/queue.js` for the repo overview. Every file registers a JSON
payload on `window.CFQ_DATA` rather than being fetched, since browsers block `fetch()` of a local
JSON file under `file://` but a `<script src>` tag still works:

    window.CFQ_DATA = window.CFQ_DATA || {}; window.CFQ_DATA["batch/<b>/plan"] = { ... };

Deterministic, at zero model-token cost: no timestamp is ever written beyond one already present
in the source data (`report.json`, a queue-entry filename), and every payload's object keys are
sorted, so a re-sync that changes nothing writes nothing. `sync <repo-root> [--batch <name>]...`
recomputes `queue.js`, the named batches' own files (every batch when `--batch` is omitted) and
every `todo`/`plan` entry file; it also deletes a `batch/*.js`/`entry/*.js` file whose source batch
or entry no longer exists. `rebuild <repo-root>` is `sync` with no `--batch` filter, kept as its
own verb for the migration off the old per-batch `report.html` (a later phase) and for manual
repair. Both print one JSON object: `{"status", "written", "unchanged", "removed"}`.

Reuses rather than re-derives: `cfq_brief.parse_phase_body` for a phase file's title/size,
`cfq_report.read_batch_context` for `.batch-context.md`'s sections, `cfq_report.phase_layer_sums`
(batch 038 phase 05's four-layer cost split) for every cost total here, and `cfq_scan.scan_repo`
(the same per-repo record builder the dashboard uses) for batch status/open/done/blocked/planning
-- never a second scan of every `scanRoots` repo for what is always a single-repo sync.
"""

import argparse
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_brief import parse_phase_body  # noqa: E402
from cfq_lib import markdown as cfq_lib_markdown  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import render  # noqa: E402

import cfq_report  # noqa: E402
import cfq_scan  # noqa: E402

PROG = "cfq_portal.py"

ENTRY_KINDS = ("plan", "todo")
ENTRY_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
CHECK_RE = re.compile(r"^check:\s*(.+)$")


# ---- layout ------------------------------------------------------------------------------------

def reports_dir(repo_root):
    return pathlib.Path(repo_root) / ".claude" / "cfq" / "reports"


def data_dir(repo_root):
    return reports_dir(repo_root) / "data"


def batch_directory(repo_root, batch_record):
    base = (
        cfq_lib_paths.impl_done_dir(repo_root)
        if batch_record.get("archived")
        else cfq_lib_paths.impl_dir(repo_root)
    )
    return pathlib.Path(base) / batch_record["name"]


# ---- write-if-changed ---------------------------------------------------------------------------

def _dump_json(obj):
    """Sorted-key, indented JSON -- deterministic across syncs so an unchanged payload never
    trips `write_if_changed`. `render.dump_json` (compact, insertion order) isn't used here on
    purpose: it doesn't sort keys, which this module's determinism contract requires."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def render_data_file(key, payload):
    return (
        "window.CFQ_DATA = window.CFQ_DATA || {};\n"
        f"window.CFQ_DATA[{json.dumps(key, ensure_ascii=False)}] = {_dump_json(payload)};\n"
    )


def write_if_changed(path, content):
    """True if `path` was written (didn't exist, or existed with different content), False if
    left untouched. Tmp file + `os.replace`, same pattern as `cfq_lib.render.write_json`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            if path.read_text() == content:
                return False
        except OSError:
            pass
    tmp = pathlib.Path(f"{path}.tmp")
    tmp.write_text(content)
    os.replace(str(tmp), str(path))
    return True


def cleanup_stale(out_dir, expected_rel):
    """Removes every `batch/*.js`/`entry/*.js` file not in `expected_rel` -- a closed entry or a
    deleted batch loses its data file. Never touches `queue.js` itself (always expected, always
    rewritten) or anything outside `batch/`/`entry/`."""
    removed = []
    for sub in ("batch", "entry"):
        d = out_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.js")):
            rel = f"{sub}/{f.name}"
            if rel not in expected_rel:
                f.unlink()
                removed.append(rel)
    return removed


# ---- cost totals: whole-batch totals plus the four layer sums ----------------------------------

def batch_cost_totals(data):
    """`{"total": {turns, output, billable_in}, "layers": {main, main_explore, worker,
    worker_explore: {turns, output, billable_in}}}`, summed across the planning record (if any)
    and every phase's telemetry record. Reads each record's layer split through
    `cfq_report.phase_layer_sums()` -- unchanged, including its schema-1 fallback -- never
    re-derives it. `data={}` (no report.json yet) yields an all-zero result, the same shape a
    batch with a report gets."""
    layer_totals = {name: {"turns": 0, "output": 0, "billable_in": 0} for name in cfq_report.LAYER_NAMES}
    phases = data.get("phases", []) if isinstance(data, dict) else []
    planning = data.get("planning") if isinstance(data, dict) else None
    records = [planning] if isinstance(planning, dict) else []
    records += [p.get("telemetry") for p in phases if isinstance(p, dict)]

    for tel in records:
        layers = cfq_report.phase_layer_sums(tel)
        for name in cfq_report.LAYER_NAMES:
            for field in ("turns", "output", "billable_in"):
                layer_totals[name][field] += cfq_report._totals_field(layers[name], field)

    total = {
        field: sum(layer_totals[name][field] for name in cfq_report.LAYER_NAMES)
        for field in ("turns", "output", "billable_in")
    }
    return {"total": total, "layers": layer_totals}


def count_deviations(data):
    total = 0
    for p in data.get("phases", []) if isinstance(data, dict) else []:
        d = p.get("deviations") if isinstance(p, dict) else None
        if isinstance(d, list):
            total += len(d)
    return total


def skills_summary(data):
    """`{"recommended": [...], "used": [...]}` -- the same aggregation `cfq_report.py`'s `skills`
    verb performs over `report.json`'s per-phase telemetry, read here directly since that verb
    only prints, it doesn't expose an importable accessor."""
    phases = data.get("phases", []) if isinstance(data, dict) else []
    recommended, used = set(), set()
    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        if not isinstance(tel, dict):
            continue
        rec = tel.get("skills_recommended")
        if isinstance(rec, list):
            recommended.update(rec)
        by_skill = tel.get("by_skill")
        if isinstance(by_skill, dict):
            used.update(k for k in by_skill.keys() if k != "-")
    return {"recommended": sorted(recommended), "used": sorted(used)}


# ---- queue.js ------------------------------------------------------------------------------------

def batch_status(b):
    """`planning`/`planned`/`blocked`/`in_progress`/`done`/`archived` -> the six values the
    viewer's queue overview is contracted to show (`.batch-context.md`'s Cross-Phase Contracts).
    Same precedence `cfq_scan.py`'s own `batch_status()` uses for the non-archived vocabulary
    (blocked > planning > inProgress > else) -- an archived batch never carries any of those three
    flags (`cfq_scan.archived_batch_record`), so checking it first never shadows a real one."""
    if b.get("archived"):
        return "done"
    if b.get("blocked"):
        return "blocked"
    if b.get("planning"):
        return "planning"
    if b.get("inProgress"):
        return "in_progress"
    return "planned"


def first_goal_line(batch_dir):
    sections = cfq_report.read_batch_context(str(batch_dir))
    for line in sections.get("goal", "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def load_report(batch_dir):
    f = batch_dir / "report.json"
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def build_queue_batch_row(repo_root, b):
    bd = batch_directory(repo_root, b)
    data = load_report(bd)
    return {
        "name": b["name"],
        "status": batch_status(b),
        "priority": b.get("priority", ""),
        "dependsOn": b.get("dependsOn", []),
        "open": b.get("open", 0),
        "done": b.get("done", 0),
        "goal": first_goal_line(bd),
        "cost": batch_cost_totals(data),
        "deviations": count_deviations(data),
    }


def build_queue_payload(repo_root, scan, entry_summaries):
    batches = sorted(
        (build_queue_batch_row(repo_root, b) for b in scan["batches"]),
        key=lambda r: r["name"],
    )
    entries = sorted(entry_summaries, key=lambda e: e["id"])
    return {"repo": repo_root, "batches": batches, "entries": entries}


# ---- batch/<b>.plan.js -----------------------------------------------------------------------

def batch_phase_files(batch_dir):
    """Every phase file, open and done, sorted by slug -- the `NN-` prefix is zero-padded so
    lexicographic order over the stem is numeric order too, matching every other `[0-9][0-9]-*.md`
    glob in this plugin."""
    files = list(batch_dir.glob("[0-9][0-9]-*.md")) + list((batch_dir / "done").glob("[0-9][0-9]-*.md"))
    return sorted(files, key=lambda p: p.stem)


def build_plan_payload(batch_dir, batch_record):
    sections_raw = cfq_report.read_batch_context(str(batch_dir))
    sections = {key: cfq_lib_markdown.md_min(body) for key, body in sections_raw.items()}

    phases = []
    for f in batch_phase_files(batch_dir):
        text = f.read_text()
        fields = parse_phase_body(text)
        phases.append({
            "slug": f.stem,
            "title": fields.get("title") or "",
            "size": fields.get("size") or "",
            "state": "done" if f.parent.name == "done" else "open",
            "bodyHtml": cfq_lib_markdown.md_min(text, keep_h1=True),
        })

    return {
        "batch": batch_dir.name,
        "priority": batch_record.get("priority", ""),
        "dependsOn": batch_record.get("dependsOn", []),
        "sections": sections,
        "phases": phases,
    }


# ---- batch/<b>.impl.js -----------------------------------------------------------------------

def phase_record_payload(p):
    p = p if isinstance(p, dict) else {}
    return {
        "phase": p.get("phase", ""),
        "status": p.get("status", ""),
        "summary": cfq_report.phase_summary(p),
        "commit": render.jq_alt(p.get("commit"), ""),
        "deviations": render.jq_alt(p.get("deviations"), []),
        "errors": render.jq_alt(p.get("errors"), []),
        "triggers": render.jq_alt(p.get("triggers"), []),
        "filesTouched": render.jq_alt(p.get("filesTouched"), []),
        "parkedPlanEntries": render.jq_alt(p.get("parkedPlanEntries"), []),
        "verification": render.jq_alt(p.get("verification"), ""),
        "finished": cfq_report.phase_finished(p),
        "telemetry": p.get("telemetry") if isinstance(p.get("telemetry"), dict) else None,
    }


def build_impl_payload(batch_dir):
    data = load_report(batch_dir)
    phases = data.get("phases", []) if isinstance(data, dict) else []
    security_entries = data.get("security") if isinstance(data, dict) else None
    security = security_entries[-1] if isinstance(security_entries, list) and security_entries else None

    return {
        "batch": data.get("batch", batch_dir.name),
        "repo": data.get("repo", ""),
        "started": data.get("started", ""),
        "finished": cfq_report.batch_finished(data),
        "outcome": cfq_report.outcome(phases),
        "phases": [phase_record_payload(p) for p in phases if isinstance(p, dict)],
        "skills": skills_summary(data),
        "security": security,
        "cost": batch_cost_totals(data),
    }


# ---- entry/<todo|plan>-<stem>.js ---------------------------------------------------------------

def entry_dir(repo_root, kind):
    return pathlib.Path(cfq_lib_paths.plan_dir(repo_root) if kind == "plan" else cfq_lib_paths.todo_dir(repo_root))


def entry_files(repo_root, kind):
    d = entry_dir(repo_root, kind)
    return sorted(d.glob("*.md")) if d.is_dir() else []


def entry_title(text):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def build_entry_payload(kind, path):
    text = path.read_text()
    m = ENTRY_FILENAME_RE.match(path.name)
    entry_date = m.group(1) if m else ""
    has_check = any(CHECK_RE.match(line.strip()) for line in text.splitlines())
    return {
        "id": f"{kind}-{path.stem}",
        "kind": kind,
        "date": entry_date,
        "title": entry_title(text),
        "check": has_check,
        "origin": kind,
        "bodyHtml": cfq_lib_markdown.md_min(text, keep_h1=True),
    }


def entry_summary(full):
    return {k: v for k, v in full.items() if k != "bodyHtml"}


# ---- sync / rebuild -------------------------------------------------------------------------

def sync(repo_root, batch_names=None):
    repo_root = str(pathlib.Path(repo_root).resolve())
    scan = cfq_scan.scan_repo(repo_root)
    if scan is None:
        return {"status": "NO_REPO", "written": [], "unchanged": 0, "removed": []}

    out_dir = data_dir(repo_root)
    written = []
    unchanged = 0

    def write(rel, key, payload):
        nonlocal unchanged
        if write_if_changed(out_dir / rel, render_data_file(key, payload)):
            written.append(rel)
        else:
            unchanged += 1

    entry_fulls = []
    for kind in ENTRY_KINDS:
        for f in entry_files(repo_root, kind):
            entry_fulls.append(build_entry_payload(kind, f))
    entry_summaries = [entry_summary(e) for e in entry_fulls]

    write("queue.js", "queue", build_queue_payload(repo_root, scan, entry_summaries))

    all_names = {b["name"] for b in scan["batches"]}
    target_names = all_names if batch_names is None else (all_names & set(batch_names))
    for b in scan["batches"]:
        if b["name"] not in target_names:
            continue
        bd = batch_directory(repo_root, b)
        write(f"batch/{b['name']}.plan.js", f"batch/{b['name']}/plan", build_plan_payload(bd, b))
        if (bd / "report.json").is_file():
            write(f"batch/{b['name']}.impl.js", f"batch/{b['name']}/impl", build_impl_payload(bd))

    for e in entry_fulls:
        write(f"entry/{e['id']}.js", f"entry/{e['id']}", e)

    expected = {f"batch/{b['name']}.plan.js" for b in scan["batches"]}
    expected |= {
        f"batch/{b['name']}.impl.js"
        for b in scan["batches"]
        if (batch_directory(repo_root, b) / "report.json").is_file()
    }
    expected |= {f"entry/{e['id']}.js" for e in entry_fulls}
    removed = cleanup_stale(out_dir, expected)

    return {
        "status": "OK",
        "written": sorted(written),
        "unchanged": unchanged,
        "removed": sorted(removed),
    }


def cmd_sync(args):
    print(render.dump_json(sync(args.repo_root, args.batch or None)))


def cmd_rebuild(args):
    print(render.dump_json(sync(args.repo_root, None)))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("sync")
    p.add_argument("repo_root")
    p.add_argument("--batch", action="append", default=[])
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("rebuild")
    p.add_argument("repo_root")
    p.set_defaults(func=cmd_rebuild)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        print(f"usage: {PROG} sync <repo-root> [--batch <name>]... | rebuild <repo-root>", file=sys.stderr)
        sys.exit(1)
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
