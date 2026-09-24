#!/usr/bin/env python3
# Usage: cfq_portal.py sync <repo-root> [--batch <name>]...
#        cfq_portal.py rebuild <repo-root>
"""Writes both halves of `<repo>/.claude/cfq/reports/index.html`: the fixed viewer shell
(`index.html`, `assets/viewer.js`, `assets/style.css`, copied in from the plugin's own `portal/`
source by `install_shell()` whenever `reports/.portal-version` differs from the running plugin's
own version) and the data layer it reads -- one `.js` file per batch's plan, one per batch's
implementation report, one per open `todo`/`plan` entry, plus `data/queue.js` for the repo overview
and `data/site.js` for the page title. Every data file registers a JSON payload on
`window.CFQ_DATA` rather than being fetched, since browsers block `fetch()` of a local JSON file
under `file://` but a `<script src>` tag still works:

    window.CFQ_DATA = window.CFQ_DATA || {}; window.CFQ_DATA["batch/<b>/plan"] = { ... };

Deterministic, at zero model-token cost: no timestamp is ever written beyond one already present
in the source data (`report.json`, a queue-entry filename), and every payload's object keys are
sorted, so a re-sync that changes nothing writes nothing. `sync <repo-root> [--batch <name>]...`
recomputes the shell (when its version stamp moved on), `queue.js`, `site.js`, the named batches'
own files (every batch when `--batch` is omitted) and every `todo`/`plan` entry file; it also
deletes a `batch/*.js`/`entry/*.js` file whose source batch or entry no longer exists. `rebuild
<repo-root>` is `sync` with no `--batch` filter, kept as its own verb for the migration off the old
per-batch `report.html` (a later phase) and for manual repair. Both print one JSON object:
`{"status", "written", "unchanged", "removed"}`.

Reuses rather than re-derives: `cfq_brief.parse_phase_body` for a phase file's title/size,
`cfq_report.read_batch_context` for `.batch-context.md`'s sections, `cfq_report.phase_layer_sums`
(batch 038 phase 05's four-layer cost split) for every cost total here, and `cfq_scan.scan_repo`
(the same per-repo record builder the dashboard uses) for batch status/open/done/blocked/planning
-- never a second scan of every `scanRoots` repo for what is always a single-repo sync.

When the `reportDir` setting resolves to a non-empty absolute path, `sync()` additionally mirrors
every data file it just wrote (repo-local) to `<reportDir>/<repo-name>[-<hash>]/data/...` --
`<repo-name>` is the repo directory's basename, suffixed with a short hash of the absolute repo
path only on a collision with a different repo already mirrored under that name, a mapping
recorded (and kept stable across syncs) in `<reportDir>/data/repos.js`. The fixed viewer shell is
installed once at `<reportDir>/` itself (not per repo), and `<reportDir>/data/site.js` carries
`{"mode": "global"}` so the viewer renders the cross-repo index instead of one repo's overview. A
mirror failure (permission denied, `reportDir` not creatable) never fails the repo-local sync --
the JSON result carries `"mirror": {"status": "ERROR", "detail": ...}` instead, with the
repo-local files written exactly as if `reportDir` were unset.
"""

import argparse
import hashlib
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
from cfq_lib.proc import settings_get  # noqa: E402

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


def plugin_root():
    """`scripts/` -> the plugin root, one level up -- the same relative layout in a checkout and
    in an installed plugin cache. Used to locate both the viewer's own source (`portal/`) and
    `.claude-plugin/plugin.json` for the version stamp below."""
    return pathlib.Path(__file__).resolve().parent.parent


def plugin_version():
    try:
        data = json.loads((plugin_root() / ".claude-plugin" / "plugin.json").read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return data.get("version", "") if isinstance(data, dict) else ""


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


# ---- install: the fixed viewer shell, copied in only when the plugin version moved on ----------

PORTAL_SHELL_FILES = (
    ("index.html", "index.html"),
    ("viewer.js", "assets/viewer.js"),
    ("style.css", "assets/style.css"),
)


def install_shell(out_dir):
    """Copies the fixed viewer shell (`index.html`, `assets/viewer.js`, `assets/style.css`) from
    the plugin's own `portal/` source into `out_dir` (a repo's `.claude/cfq/reports/`, or a
    `reportDir` root for the global mirror) whenever the installed stamp
    (`<out_dir>/.portal-version`) differs from the running plugin's own version -- an unchanged
    version copies nothing, so a sync never rewrites the tree on every call. Returns the list of
    paths (relative to `out_dir`) actually written."""
    stamp_path = out_dir / ".portal-version"
    version = plugin_version()
    try:
        current = stamp_path.read_text().strip()
    except OSError:
        current = None
    if current == version:
        return []

    written = []
    for src_name, rel in PORTAL_SHELL_FILES:
        src = plugin_root() / "portal" / src_name
        try:
            content = src.read_text()
        except OSError:
            continue
        if write_if_changed(out_dir / rel, content):
            written.append(rel)
    write_if_changed(stamp_path, version)
    return written


# ---- reportDir mirror: an additional copy of every repo's portal, plus a cross-repo index ------

DATA_FILE_RE = re.compile(
    r"^window\.CFQ_DATA = window\.CFQ_DATA \|\| \{\};\n"
    r"window\.CFQ_DATA\[.*?\] = (?P<payload>.*);\n\Z",
    re.S,
)


def report_dir_setting(repo_root):
    """`""`/`"null"` both mean "mirroring is off" -- same two-value check `cfq_report.py`'s own
    `resolve_html_path()` uses for this same setting's other (legacy, unrelated) consumer."""
    value = settings_get(repo_root, "reportDir")
    return value if value not in ("", "null") else ""


def read_data_payload(path):
    """Parses a `window.CFQ_DATA[...] = <payload>;` data file back into its JSON payload -- the
    one place `repos.js` (this module's only data file ever read back, not just written) needs
    reading. Missing file, unreadable file or unexpected shape all degrade to `None` rather than
    raising, since a first sync into a fresh `reportDir` has no `repos.js` yet."""
    try:
        content = path.read_text()
    except OSError:
        return None
    m = DATA_FILE_RE.match(content)
    if not m:
        return None
    try:
        return json.loads(m.group("payload"))
    except json.JSONDecodeError:
        return None


def repos_js_path(report_dir):
    return pathlib.Path(report_dir) / "data" / "repos.js"


def resolve_mirror_name(existing_repos, repo_root):
    """The mirror directory name for `repo_root` under `reportDir`: stable once recorded --
    a repo already listed in `repos.js` (matched by its absolute `source` path, not by name) keeps
    its existing `mirror` value forever, even if a *third* repo later collides with its basename.
    A repo seen for the first time gets its own basename, unless another *different* repo already
    claimed that exact mirror name, in which case it gets a `-<short hash of its own absolute
    path>` suffix -- deterministic (the same repo always hashes to the same suffix) and stable
    (recorded here, in `repos.js`, the moment it's chosen)."""
    for r in existing_repos:
        if isinstance(r, dict) and r.get("source") == repo_root:
            return r.get("mirror") or pathlib.Path(repo_root).name
    base = pathlib.Path(repo_root).name
    used = {r.get("mirror") for r in existing_repos if isinstance(r, dict)}
    if base not in used:
        return base
    digest = hashlib.sha1(repo_root.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def repo_counts(queue_payload):
    """`{"batches": {"inProgress", "planned", "done"}, "todos", "planEntries"}` -- the same
    grouping the viewer's own `groupBatches()` applies (in_progress / done / everything else),
    computed here so the cross-repo index can render a repo's card without loading and grouping
    that repo's full `queue.js` itself."""
    groups = {"inProgress": 0, "planned": 0, "done": 0}
    for b in queue_payload.get("batches", []):
        status = b.get("status")
        if status == "in_progress":
            groups["inProgress"] += 1
        elif status == "done":
            groups["done"] += 1
        else:
            groups["planned"] += 1
    entries = queue_payload.get("entries", [])
    todos = sum(1 for e in entries if e.get("kind") == "todo")
    plan_entries = sum(1 for e in entries if e.get("kind") == "plan")
    return {"batches": groups, "todos": todos, "planEntries": plan_entries}


def update_repos_list(existing_repos, repo_root, mirror_name, counts):
    """Read-modify-write over the parsed `repos.js` list: only the row for `repo_root` changes
    (updated in place if present, appended otherwise) -- every other repo's row, including its
    position, is left untouched, so two repos syncing independently never race on each other's
    data."""
    name = pathlib.Path(repo_root).name
    row = {"name": name, "mirror": mirror_name, "source": repo_root, "counts": counts}
    rows, replaced = [], False
    for r in existing_repos:
        if isinstance(r, dict) and r.get("source") == repo_root:
            rows.append(row)
            replaced = True
        else:
            rows.append(r)
    if not replaced:
        rows.append(row)
    return rows


def mirror_sync(report_dir, repo_root, queue_payload, docs):
    """Mirrors `docs` (the `(rel, key, payload)` triples `sync()` just wrote repo-locally) into
    `<report_dir>/<mirror-name>/data/...`, installs the global shell once at `<report_dir>/`
    itself, and updates the cross-repo `<report_dir>/data/{site,repos}.js`. Raises on any
    filesystem failure -- the caller isolates it, since a mirror failure must never fail the
    repo-local sync it rides along with."""
    report_root = pathlib.Path(report_dir)
    written = list(install_shell(report_root))
    unchanged = 0

    if write_if_changed(report_root / "data" / "site.js", render_data_file("site", {"mode": "global"})):
        written.append("data/site.js")
    else:
        unchanged += 1

    existing_repos = read_data_payload(repos_js_path(report_dir))
    if not isinstance(existing_repos, list):
        existing_repos = []
    mirror_name = resolve_mirror_name(existing_repos, repo_root)
    new_repos = update_repos_list(existing_repos, repo_root, mirror_name, repo_counts(queue_payload))
    if write_if_changed(repos_js_path(report_dir), render_data_file("repos", new_repos)):
        written.append("data/repos.js")
    else:
        unchanged += 1

    out_dir = report_root / mirror_name / "data"
    expected = set()
    for rel, key, payload in docs:
        expected.add(rel)
        if write_if_changed(out_dir / rel, render_data_file(key, payload)):
            written.append(f"{mirror_name}/data/{rel}")
        else:
            unchanged += 1
    removed = [f"{mirror_name}/data/{rel}" for rel in cleanup_stale(out_dir, expected)]

    return {"status": "OK", "written": sorted(written), "unchanged": unchanged, "removed": sorted(removed)}


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
        "unknownDeps": b.get("unknownDeps", []),
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
    written = list(install_shell(reports_dir(repo_root)))
    unchanged = 0
    docs = []  # every (rel, key, payload) triple actually considered this sync -- mirrored as-is

    def write(rel, key, payload):
        nonlocal unchanged
        docs.append((rel, key, payload))
        if write_if_changed(out_dir / rel, render_data_file(key, payload)):
            written.append(rel)
        else:
            unchanged += 1

    write("site.js", "site", {"mode": "repo", "repo": pathlib.Path(repo_root).name})

    entry_fulls = []
    for kind in ENTRY_KINDS:
        for f in entry_files(repo_root, kind):
            entry_fulls.append(build_entry_payload(kind, f))
    entry_summaries = [entry_summary(e) for e in entry_fulls]

    queue_payload = build_queue_payload(repo_root, scan, entry_summaries)
    write("queue.js", "queue", queue_payload)

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

    result = {
        "status": "OK",
        "written": sorted(written),
        "unchanged": unchanged,
        "removed": sorted(removed),
    }

    report_dir = report_dir_setting(repo_root)
    if report_dir:
        try:
            result["mirror"] = mirror_sync(report_dir, repo_root, queue_payload, docs)
        except Exception as e:  # noqa: BLE001 -- a mirror failure must never fail the repo-local sync
            result["mirror"] = {"status": "ERROR", "detail": str(e)}
    else:
        result["mirror"] = None

    return result


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
