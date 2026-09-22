#!/usr/bin/env python3
# Usage: cfq_report.py security <batch-dir> <security-json>
#        cfq_report.py set-commit <batch-dir> <phase-slug> <sha>
#        cfq_report.py skills <batch-dir>
#        cfq_report.py last-failure <batch-dir> <phase-slug>
#        cfq_report.py summary <batch-dir>
#        cfq_report.py html <batch-dir>
#        cfq_report.py index [--repo <substr>] [--batch <substr>] [--any <substr>] [--limit <n>] [--text]
#        cfq_report.py detail <batch-dir>
"""Implementation reports per batch. The report lives in the batch directory and travels with it.

Ported from cfq-report.sh -- a port, not a redesign: the CLI contract (verbs, argument order,
JSON shapes, text output, exit codes, error objects) is the invariant this file preserves.
`html.escape()`-equivalent output (`html_escape_jq`) is applied everywhere the shell version's
`@html` jq filter ran, matching jq's exact five-character escape table rather than Python's own
`html.escape` (which spells the apostrophe differently).
"""

import argparse
import json
import math
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_brief import parse_phase_body  # noqa: E402
from cfq_lib import errors, render  # noqa: E402
from cfq_lib.proc import cfq_argv  # noqa: E402

PROG = "cfq_report.py"

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent

# Shared by html's per-batch report and its collected index.html -- one visual language, not two.
# Every colour is a custom property defined on bare :root; the dark-mode and print @media blocks
# only ever redefine tokens that already exist there (tests/test_report.py asserts this
# structurally) -- no colour gets its only definition inside a media query.
REPORT_STYLE_CSS = """:root{
  --bg:#ffffff;--surface:#f7f8fa;--surface-2:#eceff4;
  --fg:#16181d;--fg-muted:#545c6b;--fg-faint:#767e8c;
  --border:#d5dae2;--border-strong:#aeb6c2;
  --ok:#1a7f45;--ok-bg:#e4f3ea;--bad:#b32d1f;--bad-bg:#fae9e6;
  --warn:#8a5b00;--warn-bg:#fbf1d6;--accent:#2f5fd0;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --r:8px;--gap:1rem;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#14161a;--surface:#1b1e24;--surface-2:#232830;
  --fg:#e7eaf0;--fg-muted:#a3abba;--fg-faint:#848d9c;
  --border:#2e343e;--border-strong:#454d5a;
  --ok:#5cc98b;--ok-bg:#16301f;--bad:#f0857a;--bad-bg:#331b18;
  --warn:#e0b45a;--warn-bg:#2e2512;--accent:#8fb0ff;
}}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);max-width:64rem;margin:0 auto;
  padding:2rem 1rem;line-height:1.55}
h1{font-size:1.6rem;margin:0}
h2{font-size:1.2rem}
h3{font-size:1.05rem}
h4{font-size:.9rem;text-transform:uppercase;letter-spacing:.05em;color:var(--fg-faint)}
code{background:var(--surface-2);font-family:var(--mono);font-size:0.875em;padding:0.1rem 0.3rem;
  border-radius:0.2rem}
header.batch{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:1.25rem}
header.batch .ident{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;margin-bottom:.75rem}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));gap:.4rem 1.5rem}
.meta dt{color:var(--fg-faint);text-transform:uppercase;font-size:.72rem}
.meta dd{margin:0}
.badge{display:inline-flex;align-items:center;gap:.35rem;padding:.15rem .6rem;border-radius:999px;
  font-size:.78rem;font-weight:600;letter-spacing:.03em;border:1px solid}
.badge.green{color:var(--ok);background:var(--ok-bg);border-color:var(--ok)}
.badge.red{color:var(--bad);background:var(--bad-bg);border-color:var(--bad)}
.badge.mixed{color:var(--warn);background:var(--warn-bg);border-color:var(--warn)}
section.phase{background:var(--surface);border:1px solid var(--border);
  border-left:4px solid var(--border-strong);border-radius:var(--r);padding:1rem 1.25rem;
  margin:1.25rem 0}
section.phase.green{border-left-color:var(--ok)}
section.phase.red{border-left-color:var(--bad)}
section.phase .num{color:var(--fg-faint);margin-right:.25rem}
section.phase .slug{color:var(--fg-faint);font-size:.78rem;margin:.15rem 0 .6rem}
.phase ul{margin:.2rem 0 .8rem;padding-left:1.1rem}
.phase li{margin:.15rem 0}
.phase li code{font-size:.8rem;background:none;padding:0;color:var(--fg-muted)}
.goal{color:var(--fg-muted);font-style:italic;border-left:2px solid var(--border);
  padding-left:.75rem}
.tele{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.4rem 1.5rem;
  font-size:.82rem;background:var(--surface-2);border-radius:var(--r);padding:.6rem .8rem;
  margin:.75rem 0}
.tele dt{color:var(--fg-faint);text-transform:uppercase;font-size:.68rem}
.tele dd{margin:0}
section.overview{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:1.25rem;margin:1.25rem 0}
.overview h3{font-size:.9rem;text-transform:uppercase;letter-spacing:.05em;color:var(--fg-faint)}
.overview ul{margin:.3rem 0 .9rem;padding-left:1.1rem}
.overview li{margin:.2rem 0}
.overview p{margin:.3rem 0 .9rem}
.overview li strong{color:var(--fg)}
section.security{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:1.25rem;margin:1.25rem 0}
.muted{color:var(--fg-muted)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.tscroll{overflow-x:auto}
.phase-table table,.repo table{border-collapse:collapse;width:100%;font-size:.85rem}
.phase-table th,.phase-table td,.repo th,.repo td{padding:.4rem .6rem;
  border-bottom:1px solid var(--border);text-align:left;white-space:nowrap}
.phase-table thead th,.repo thead th{color:var(--fg-faint);font-weight:600;font-size:.72rem;
  text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--border-strong)}
.phase-table td.n,.phase-table th.n,.repo td.n,.repo th.n{text-align:right;
  font-variant-numeric:tabular-nums;font-family:var(--mono)}
.phase-table td.c,.phase-table th.c,.repo td.c,.repo th.c{text-align:center}
.phase-table tbody tr:hover,.repo tbody tr:hover{background:var(--surface-2)}
.phase-table tfoot td,.phase-table tfoot th{border-top:1px solid var(--border-strong);
  border-bottom:none;color:var(--fg-muted);font-weight:600}
.phase-table td a,.repo td a{color:var(--accent);text-decoration:none}
.phase-table td a:hover,.repo td a:hover{text-decoration:underline}
.verification code{display:block;white-space:pre-wrap;overflow-wrap:anywhere}
section.repo{margin:1.5rem 0}
.repo h2 .count{font-weight:400;font-size:.8rem;color:var(--fg-faint);margin-left:.5rem}
@media (max-width:30rem){.meta,.tele{grid-template-columns:1fr}}
@media print{
  :root{--bg:#fff;--surface:#fff;--surface-2:#f2f2f2;--fg:#000;--fg-muted:#333;--border:#999;}
  body{max-width:none;padding:0;font-size:10pt}
  section.phase{break-inside:avoid}
  a{text-decoration:none;color:inherit}
}"""

PHASE_ID_RE = re.compile(r"^[0-9]{2}-.+$")


# ---- jq-semantics helpers -----------------------------------------------------------------

def jq_round(x):
    """Mirrors jq's `round` (round-half-away-from-zero), not Python's round-half-to-even."""
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&apos;", '"': "&quot;"}


def html_escape_jq(s):
    return "".join(_HTML_ESCAPES.get(ch, ch) for ch in s)


def esc(value):
    """Mirrors the shell script's `def esc: (. // "") | tostring | @html;`."""
    return html_escape_jq(render.tostring(render.jq_alt(value, "")))


# ---- shared path/settings helpers ----------------------------------------------------------

def repo_root_of(d):
    """Batch dir -> containing repo root, stripping the known queue suffixes. Empty string if
    it isn't nested under either suffix."""
    d = d.rstrip("/")
    try:
        abs_path = str(pathlib.Path(d).resolve()) if os.path.isdir(d) else d
    except OSError:
        abs_path = d
    idx = abs_path.rfind("/.claude/cfq/impl/done/")
    if idx != -1:
        return abs_path[:idx]
    idx = abs_path.rfind("/.claude/cfq/impl/")
    if idx != -1:
        return abs_path[:idx]
    return ""


def settings_get(repo_root, key):
    """Stays local, not `cfq_lib.proc.settings_get`: `repo_root` here is optional (falsy skips
    `--repo` for a global-only read), which the shared helper doesn't support."""
    cmd = cfq_argv("settings", "get")
    if repo_root:
        cmd += ["--repo", repo_root]
    cmd.append(key)
    out = subprocess.run(cmd, capture_output=True, text=True)
    return out.stdout.strip()


def resolve_html_path(dir_):
    """Path report.html lives (or would live) at for a batch directory, honoring the reportDir
    setting when configured -- same resolution `html`, `index --text`'s file:// lines and
    `regenerate_index()` all need. Read-only: a caller that's about to write creates the directory
    itself. Three branches: an explicit absolute `reportDir` keeps the shared cross-repo layout
    unchanged; an empty/`"null"` `reportDir` with a derivable repo root now lands under that
    repo's own `.claude/cfq/reports/`, flat, one file per batch; a batch directory that isn't
    nested under a `.claude/cfq/impl(/done)/` at all (repo root not derivable -- true only for
    synthetic fixtures, never a real batch) falls back to the historical per-batch-directory
    path so that case degrades exactly as it always has."""
    dir_ = dir_.rstrip("/")
    repo_root = repo_root_of(dir_)
    report_dir = settings_get(repo_root, "reportDir")
    if report_dir not in ("", "null"):
        return f"{report_dir}/{os.path.basename(repo_root)}/{os.path.basename(dir_)}.html"
    if repo_root:
        return f"{repo_root}/.claude/cfq/reports/{os.path.basename(dir_)}.html"
    return f"{dir_}/report.html"


def ensure_report(dir_):
    """report.json is created by whoever writes to it first -- planning-time security snapshot
    or the first phase. Same shape in both cases."""
    path = os.path.join(dir_, "report.json")
    if os.path.isfile(path):
        return
    repo = subprocess.run(
        ["git", "-C", dir_, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    ).stdout.strip()
    started = subprocess.run(["date", "-Iseconds"], capture_output=True, text=True).stdout.strip()
    render.write_json(path, {"repo": repo, "batch": os.path.basename(dir_), "started": started, "phases": []})


def outcome(phases):
    """GREEN if no phase ever went red; RED if any phase's most recent attempt is still red;
    MIXED if every phase that ever went red now shows green as its latest attempt."""
    if not isinstance(phases, list):
        phases = []
    if not any(isinstance(p, dict) and p.get("status") == "red" for p in phases):
        return "GREEN"
    latest = {}
    for p in phases:
        if isinstance(p, dict):
            latest[p.get("phase", "")] = p.get("status")
    return "RED" if any(v == "red" for v in latest.values()) else "MIXED"


def bound_lines(value, n=5):
    s = render.jq_alt(value, "")
    if not isinstance(s, str):
        s = render.tostring(s)
    lines = s.split("\n")
    if len(lines) <= 2 * n:
        return s
    return "\n".join(lines[:n] + ["…"] + lines[-n:])


# ---- verbs: append / security / set-commit / last-failure / summary ------------------------

def append_phase(dir_, phase_json, record_telemetry=True):
    """Validates and appends one phase entry to report.json -- the one place this logic lives,
    called by `cfq_phase.py record` and `cfq_phase.py commit` as their single ledger-write step
    instead of reimplementing it. No longer reachable as a CLI verb (`report append` was removed
    once every skill-facing caller moved to `phase record`/`phase commit`); other tooling and
    tests import this function directly. Returns the validated phase_id. `record_telemetry=False`
    lets a caller that runs its own accounting (e.g. `cfq_phase.py record`'s `--no-telemetry`) skip
    the subprocess call."""
    if not os.path.isdir(dir_):
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    # The phase field is the plan file's slug (NN-slug) -- the same value that later goes to
    # set-commit, last-failure and `changelog commit-message`'s CFQ-Phase trailer. A bare number
    # or an empty value breaks every one of those lookups without an error, so it is refused
    # here, at the only point that sees the value before it is persisted.
    try:
        phase_obj = json.loads(phase_json)
    except json.JSONDecodeError:
        phase_obj = None
    phase_id = ""
    if isinstance(phase_obj, dict):
        v = phase_obj.get("phase")
        if isinstance(v, str):
            phase_id = v
    if not PHASE_ID_RE.match(phase_id):
        errors.die(f"{PROG} append: phase must be the full phase slug (NN-slug), got '{phase_id}'")

    f = os.path.join(dir_, "report.json")
    ensure_report(dir_)
    data = json.loads(pathlib.Path(f).read_text())
    data.setdefault("phases", []).append(phase_obj)
    render.write_json(f, data)
    # Telemetry attaches to the entry just written. Never fatal: a missing transcript must not
    # cost the phase its report.
    if record_telemetry:
        subprocess.run(cfq_argv("telemetry", "record", dir_, "phase", phase_id))
    return phase_id


def cmd_security(args):
    dir_ = args.dir
    if not os.path.isdir(dir_):
        errors.die(f"{PROG}: no such batch directory: {dir_}")
    try:
        snap_obj = json.loads(args.snap)
    except json.JSONDecodeError as e:
        errors.die(f"{PROG}: security: invalid JSON: {e}", code=2)

    f = os.path.join(dir_, "report.json")
    ensure_report(dir_)
    data = json.loads(pathlib.Path(f).read_text())
    at = subprocess.run(["date", "-Iseconds"], capture_output=True, text=True).stdout.strip()
    entry = dict(snap_obj) if isinstance(snap_obj, dict) else snap_obj
    if isinstance(entry, dict):
        entry["at"] = at
    data["security"] = render.jq_alt(data.get("security"), []) + [entry]
    render.write_json(f, data)


def set_commit(dir_, phase_slug, sha):
    """Backfills the `commit` field of `phase_slug`'s most recent report.json entry -- factored
    out so `cfq_phase.py commit` can call it directly as part of its own transaction instead of
    shelling back out to this script."""
    if not os.path.isdir(dir_):
        errors.die(f"{PROG}: no such batch directory: {dir_}")
    f = os.path.join(dir_, "report.json")
    if not os.path.isfile(f):
        errors.die(f"{PROG}: no report.json in {dir_}")
    data = json.loads(pathlib.Path(f).read_text())
    phases = data.get("phases", [])
    matches = [i for i, p in enumerate(phases) if isinstance(p, dict) and p.get("phase") == phase_slug]
    if not matches:
        errors.die(
            f"{PROG} set-commit: no phase entry '{phase_slug}' in {f} — the phase field carries "
            "the full phase slug (NN-slug), not the bare number"
        )
    phases[matches[-1]]["commit"] = sha
    render.write_json(f, data)


def cmd_set_commit(args):
    set_commit(args.dir, args.phase_slug, args.sha)


def cmd_skills(args):
    """Replaces the retired `jq -c '{recommended: ..., used: ...}'` filter over
    report.json's telemetry.skills_recommended / telemetry.by_skill (references/ifq-batch-end.md's
    Skills Recommended vs. Used)."""
    dir_ = args.dir
    f = os.path.join(dir_, "report.json")
    data = json.loads(pathlib.Path(f).read_text()) if os.path.isfile(f) else {}
    phases = data.get("phases", []) if isinstance(data, dict) else []

    recommended, used = set(), set()
    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        if not isinstance(tel, dict):
            continue
        rec = render.jq_alt(tel.get("skills_recommended"), [])
        if isinstance(rec, list):
            recommended.update(rec)
        by_skill = render.jq_alt(tel.get("by_skill"), {})
        if isinstance(by_skill, dict):
            used.update(k for k in by_skill.keys() if k != "-")

    print(render.dump_json({"recommended": sorted(recommended), "used": sorted(used)}))


def cmd_last_failure(args):
    dir_, phase_slug = args.dir, args.phase_slug
    f = os.path.join(dir_, "report.json")
    if not os.path.isfile(f):
        print(render.dump_json({"found": False}))
        return
    data = json.loads(pathlib.Path(f).read_text())
    candidates = [
        p for p in data.get("phases", [])
        if isinstance(p, dict) and p.get("phase") == phase_slug and p.get("status") == "red"
    ]
    if not candidates:
        print(render.dump_json({"found": False}))
        return
    e = candidates[-1]
    print(render.dump_json({
        "found": True,
        "phase": e.get("phase"),
        "note": render.jq_alt(e.get("summary"), ""),
        "at": render.jq_alt(e.get("finished"), ""),
    }))


def _totals_field(totals, key):
    return render.jq_alt(totals.get(key) if isinstance(totals, dict) else None, 0)


def cmd_summary(args):
    dir_ = args.dir
    f = os.path.join(dir_, "report.json")
    if not os.path.isfile(f):
        sys.exit(1)
    data = json.loads(pathlib.Path(f).read_text())
    phases = data.get("phases", [])
    batch = data.get("batch")
    total = len(phases)
    green = sum(1 for p in phases if isinstance(p, dict) and p.get("status") == "green")
    red = sum(1 for p in phases if isinstance(p, dict) and p.get("status") == "red")
    deviations = 0
    for p in phases:
        d = render.jq_alt(p.get("deviations") if isinstance(p, dict) else None, [])
        if isinstance(d, list):
            deviations += len(d)

    date = batch_finished(data)

    planning = data.get("planning") if isinstance(data.get("planning"), dict) else None
    planning_totals = planning.get("totals") if isinstance(planning, dict) else None
    planning_output = _totals_field(planning_totals, "output")
    planning_turns = _totals_field(planning_totals, "turns")
    planning_billable_in = _totals_field(planning_totals, "billable_in")

    phase_outputs, phase_turns = [], []
    model_keys, effort_keys = [], []
    worker_output, worker_turns = 0, 0
    total_billable_in = 0
    explore_turns, explore_output = 0, 0
    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        totals = tel.get("totals") if isinstance(tel, dict) else None
        phase_outputs.append(_totals_field(totals, "output"))
        phase_turns.append(_totals_field(totals, "turns"))
        total_billable_in += _totals_field(totals, "billable_in")
        by_model = render.jq_alt(tel.get("by_model") if isinstance(tel, dict) else None, {})
        by_effort = render.jq_alt(tel.get("by_effort") if isinstance(tel, dict) else None, {})
        if isinstance(by_model, dict):
            model_keys.extend(by_model.keys())
        if isinstance(by_effort, dict):
            effort_keys.extend(by_effort.keys())
        # subagent_worker is the corrected, worker-only split; a report written before this
        # change carries no such key at all (None here), and only then do we fall back to the
        # old collapsed `subagent` value -- a compatibility shim for data already on disk, never
        # for code. A record that *does* carry `subagent_worker` (even an all-zero one, e.g. a
        # phase that only ran Explore agents) is used as-is, no fallback.
        subagent_worker = tel.get("subagent_worker") if isinstance(tel, dict) else None
        if subagent_worker is None:
            subagent_worker = tel.get("subagent") if isinstance(tel, dict) else None
        worker_output += _totals_field(subagent_worker, "output")
        worker_turns += _totals_field(subagent_worker, "turns")
        subagent_explore = tel.get("subagent_explore") if isinstance(tel, dict) else None
        explore_turns += _totals_field(subagent_explore, "turns")
        explore_output += _totals_field(subagent_explore, "output")

    planning_by_model = render.jq_alt(planning.get("by_model") if isinstance(planning, dict) else None, {})
    planning_by_effort = render.jq_alt(planning.get("by_effort") if isinstance(planning, dict) else None, {})
    if isinstance(planning_by_model, dict):
        model_keys = list(planning_by_model.keys()) + model_keys
    if isinstance(planning_by_effort, dict):
        effort_keys = list(planning_by_effort.keys()) + effort_keys

    total_output = planning_output + sum(phase_outputs)
    total_turns = planning_turns + sum(phase_turns)
    models = ",".join(sorted(set(model_keys)))
    efforts = ",".join(sorted(set(effort_keys)))

    row = [batch, total, green, red, deviations, date, total_output, planning_output, total_turns, models, efforts]
    # Additive fields 12-15: only when a worker (subagent/orchestrator-mode phase) actually ran --
    # an old or classic-mode report with no subagent turns/output must render byte-identical to the
    # row above, not grow a meaningless zero split. Sourced from subagent_worker (with the
    # subagent fallback above), never the collapsed subagent, so a phase that only ran Explore
    # agents no longer counts as a worker here (the mislabelling this phase fixes).
    if worker_output > 0 or worker_turns > 0:
        row += [total_turns - worker_turns, total_output - worker_output, worker_turns, worker_output]
    # Additive fields, always appended after the optional 12-15 block above: total_billable_in,
    # planning_turns, planning_billable_in, explore_turns, explore_output.
    row += [total_billable_in, planning_turns, planning_billable_in, explore_turns, explore_output]
    print("\t".join(_tsv_field(v) for v in row))


def _tsv_field(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


# ---- report derivations: status glyph, summary, timestamps, formatting, topic, row ---------
#
# Everything phases 02-07 render is derived here, once, from a phase dict -- pure functions, no
# I/O, so they're testable without a batch directory or a subprocess (see tests/test_report.py's
# TestDerivations).

# The cfq icon set from references/output-format.md -- shape-coded, not colour-coded, so the
# status survives a colourblind reader and a monochrome print alike.
STATUS_GLYPH = {"green": "✅", "red": "❌", "mixed": "⚠️"}


def status_glyph(status):
    """`STATUS_GLYPH[status.lower()]`, or "" for an unknown/missing status -- never raises,
    because `outcome()` returns upper-case ("GREEN") while a raw `phase["status"]` is lower-case
    ("green"), and both call sites exist."""
    if not isinstance(status, str):
        return ""
    return STATUS_GLYPH.get(status.lower(), "")


def phase_summary(phase):
    """The one-clause "what was built": `implemented` (current worker schema) then `summary`
    (classic-mode / pre-orchestrator records) -- two generations of the same field, both still on
    disk. "" (not "None") for a record that carries neither."""
    phase = phase if isinstance(phase, dict) else {}
    return render.jq_alt(phase.get("implemented"), phase.get("summary"), "")


def phase_finished(phase):
    """A single phase record's own finish timestamp: `finished` (old records) falling back to
    `telemetry.until` (current records), or "" when neither is present."""
    phase = phase if isinstance(phase, dict) else {}
    tel = phase.get("telemetry") if isinstance(phase.get("telemetry"), dict) else {}
    return render.jq_alt(phase.get("finished"), tel.get("until"), "")


def batch_finished(data):
    """The batch's own finish timestamp: the **maximum** `phase_finished` over every phase --
    never `phases[-1]`, because a red phase re-run appends a later record for an earlier phase
    number, so the array is in write order, not time order. Falls back to `data["started"]` when
    no phase has a timestamp, and to "" when that is missing too."""
    phases = data.get("phases", []) if isinstance(data, dict) else []
    candidates = [phase_finished(p) for p in phases if isinstance(p, dict)]
    candidates = [t for t in candidates if t]
    parsed = [(parse_ts(t), t) for t in candidates]
    parsed = [(dt, t) for dt, t in parsed if dt is not None]
    if parsed:
        return max(parsed, key=lambda pair: pair[0])[1]
    if candidates:
        return max(candidates)
    return render.jq_alt(data.get("started") if isinstance(data, dict) else None, "")


_FRACTIONAL_SECONDS_RE = re.compile(r"\.\d+")


def parse_ts(iso):
    """`2026-09-21T13:16:49.329Z` / `...+02:00` -> an aware datetime in local time, or None.
    Python 3.8's fromisoformat rejects a `Z` suffix and is picky about fractional digits, so
    both are normalised away before parsing. Any failure returns None -- a malformed timestamp
    must degrade to an empty cell, never take the report down."""
    if not isinstance(iso, str) or not iso:
        return None
    s = _FRACTIONAL_SECONDS_RE.sub("", iso)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def fmt_datetime(iso):
    """`"2026-09-21T13:16:49.329Z"` -> `"2026-09-21 15:16"` (local time) -- the HTML report's
    format. "" when `parse_ts` fails."""
    dt = parse_ts(iso)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def fmt_short(iso):
    """Same source as `fmt_datetime`, the terminal table's compact format: `"21.09 15:16"`."""
    dt = parse_ts(iso)
    return dt.strftime("%d.%m %H:%M") if dt else ""


def fmt_duration(seconds):
    """`"0:46"`, `"1:13"`, `"1:02:03"` -- `m:ss` under an hour, `h:mm:ss` at or above.
    `0`/`None`/a non-numeric value -> "–" (en dash), the same placeholder `cmd_index` already
    uses for a missing cost."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not seconds:
        return "–"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_int(n):
    """`1582736` -> `"1,582,736"` -- English grouping, since `codeLanguage` is `en` and the
    report's labels are English. `None`/non-numeric -> "–"."""
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return "–"
    return f"{int(n):,}"


def fmt_tokens(n):
    """`jq_round`'s `k` rounding, stepped up to one decimal place of `M` above 1,000k (`12.4M`) --
    the one formatter the index table's `Out` cell and its group header's summed total both call,
    so the two numbers can never disagree. `0`/negative/non-numeric -> "–", same placeholder the
    `k`-only rounding already used for a zero cost."""
    if isinstance(n, bool) or not isinstance(n, (int, float)) or n <= 0:
        return "–"
    k = n / 1000.0
    if k < 1000:
        return f"{jq_round(k)}k"
    return f"{k / 1000.0:.1f}M"


_LEADING_NUMBER_RE = re.compile(r"^\d+-")
_LEADING_DIGITS_RE = re.compile(r"^(\d+)")


def phase_topic(phase_id):
    """`"01-note-sweep-verb"` -> `"Note sweep verb"`. Strips a leading `NN-`, replaces `-` with
    spaces, uppercases the first character only -- deliberately not title case, so `"cfq"` and
    `"rfq"` stay lowercase mid-sentence. An id with no leading number is used as-is after the
    hyphen replacement."""
    if not isinstance(phase_id, str):
        return ""
    rest = _LEADING_NUMBER_RE.sub("", phase_id, count=1)
    words = rest.replace("-", " ")
    if not words:
        return ""
    return words[0].upper() + words[1:]


def phase_row(phase):
    """The single row object phases 04 and 06 both build their tables from. Every numeric field
    goes through `_totals_field` (or its `render.jq_alt` equivalent) so a phase without telemetry
    yields zeros rather than None, exactly as `build_index_rows` already treats them."""
    phase = phase if isinstance(phase, dict) else {}
    phase_id = render.jq_alt(phase.get("phase"), "")
    status = render.jq_alt(phase.get("status"), "")
    m = _LEADING_DIGITS_RE.match(phase_id) if isinstance(phase_id, str) else None
    nr = m.group(1) if m else ""
    tel = phase.get("telemetry") if isinstance(phase.get("telemetry"), dict) else {}
    totals = tel.get("totals") if isinstance(tel.get("totals"), dict) else {}
    finished = phase_finished(phase)
    duration_s = int(render.jq_alt(tel.get("wallclock_s"), 0))
    return {
        "slug": phase_id,
        "nr": nr,
        "topic": phase_topic(phase_id),
        "status": status,
        "glyph": status_glyph(status),
        "finished": finished,
        "finished_disp": fmt_datetime(finished),
        "duration_s": duration_s,
        "duration_disp": fmt_duration(duration_s),
        "turns": _totals_field(totals, "turns"),
        "out": _totals_field(totals, "output"),
        "billable_in": _totals_field(totals, "billable_in"),
        "cache_read": _totals_field(totals, "cache_read"),
        "commit": render.jq_alt(phase.get("commit"), ""),
    }


def truncate_words(text, limit):
    """Cut at the last space at or before `limit` and append a horizontal ellipsis. Text that
    already fits is returned unchanged, without an ellipsis. A `limit`-length prefix with no
    space in it falls back to a hard cut at `limit` plus the ellipsis, so a long unbroken token
    cannot return an empty string."""
    text = text or ""
    if len(text) <= limit:
        return text
    idx = text.rfind(" ", 0, limit)
    cut = idx if idx != -1 else limit
    return text[:cut] + "…"


# ---- markdown subset: .batch-context.md -> the report's Overview section -------------------
#
# Not a general Markdown renderer (see the batch's Non-Goals) -- headings, one level of bullets,
# paragraphs, `**bold**` and `` `code` `` only. Everything else (blockquotes, tables, links,
# nested lists) falls through to paragraph text on purpose, since `.batch-context.md`'s own format
# never uses them.

_INLINE_RE = re.compile(r"`([^`]*)`|\*\*([^*]*?)\*\*")


def md_inline(escaped_text):
    """Operates on text that has already been through `esc`/`html_escape_jq`. One pass, one
    regex: inline code and bold are matched as alternatives at each position so a `**` inside a
    backtick span is consumed as part of the code match and never seen by the bold alternative --
    doing this as two sequential substitutions would let a later bold pass reach back inside an
    already-emitted `<code>` span."""
    def repl(m):
        if m.group(1) is not None:
            return f"<code>{m.group(1)}</code>"
        return f"<strong>{m.group(2)}</strong>"
    return _INLINE_RE.sub(repl, escaped_text)


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


def md_min(text):
    """A line-driven state machine over `text.splitlines()`. No nesting, no look-ahead -- nested
    bullets are deliberately flattened to one level, since `.batch-context.md`'s format has none.
    Every emitted text value goes through `md_inline(esc(value))`, never raw."""
    parts = []
    in_list = False
    list_items = []
    para_lines = []

    def flush_para():
        if para_lines:
            parts.append(f"<p>{md_inline(esc(' '.join(para_lines)))}</p>")
            para_lines.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            lis = "".join(f"<li>{it}</li>" for it in list_items)
            parts.append(f"<ul>{lis}</ul>")
            in_list = False
            list_items.clear()

    for raw in text.splitlines():
        if raw.strip() == "":
            close_list()
            flush_para()
            continue
        m = _MD_HEADING_RE.match(raw)
        if m:
            close_list()
            flush_para()
            level = len(m.group(1))
            if level == 1:
                continue  # the document title, not content
            tag = "h3" if level == 2 else "h4"
            parts.append(f"<{tag}>{md_inline(esc(m.group(2).strip()))}</{tag}>")
            continue
        m = _MD_BULLET_RE.match(raw)
        if m:
            flush_para()
            in_list = True
            list_items.append(md_inline(esc(m.group(1).strip())))
            continue
        if in_list and list_items and raw[:1] in (" ", "\t"):
            list_items[-1] += " " + md_inline(esc(raw.strip()))
            continue
        para_lines.append(raw.strip())

    close_list()
    flush_para()
    return "".join(parts)


_MD_SECTION_RE = re.compile(r"^##\s+(.*)$", re.M)


def read_batch_context(dir_):
    """`<dir_>/.batch-context.md` -> `{heading_lowercased: body_text}`, split on `^## ` headings.
    Missing file or unreadable -> `{}`. Text before the first `## ` heading (the `# Batch Context`
    title) is discarded. Heading lookup is case-insensitive and whitespace-stripped."""
    try:
        text = pathlib.Path(dir_, ".batch-context.md").read_text()
    except OSError:
        return {}
    matches = list(_MD_SECTION_RE.finditer(text))
    sections = {}
    for i, m in enumerate(matches):
        heading = m.group(1).strip().lower()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[heading] = text[m.end():end].strip("\n")
    return sections


OVERVIEW_SECTIONS = [("goal", "Goal"), ("decisions", "Decisions"), ("non-goals", "Non-Goals")]


def overview_html(dir_):
    """`## Invariants` and `## Cross-Phase Contracts` are deliberately excluded -- they are
    instructions to the implementer, and the report is read after the implementation is done.
    Returns "" when the file is missing or none of the three sections has content, so a batch
    predating `.batch-context.md` gets no overview section at all, not an empty box."""
    sections = read_batch_context(dir_)
    body_parts = []
    for key, label in OVERVIEW_SECTIONS:
        body = sections.get(key, "")
        if not body:
            continue
        body_parts.append(f"<h3>{label}</h3>{md_min(body)}")
    if not body_parts:
        return ""
    return '<section class="overview"><h2>Overview</h2>' + "".join(body_parts) + "</section>"


# ---- phase 04: the phase table -- one row per report.json phase record ----------------------
#
# `phases` is an append log, not a set: a phase that went red and was re-run appends a second
# record for the same phase number (`append_phase`, `outcome()`). Every attempt gets its own row,
# in record order, so a red attempt followed by a green one is visible rather than overwritten.

def phase_table_html(phases):
    """A table over every phase record's `phase_row()` -- full token balance, one row per
    attempt. Returns "" for an empty phase list (a batch whose only report.json content is the
    planning security snapshot gets no empty table)."""
    rows = [phase_row(p) for p in phases if isinstance(p, dict)]
    if not rows:
        return ""

    body_rows = []
    tot_duration = tot_turns = tot_out = tot_in = tot_cache = 0
    for row in rows:
        tot_duration += row["duration_s"]
        tot_turns += row["turns"]
        tot_out += row["out"]
        tot_in += row["billable_in"]
        tot_cache += row["cache_read"]
        finished_disp = row["finished_disp"] or "–"
        body_rows.append(
            f'<tr class="{esc(row["status"])}">'
            f'<td class="c">{esc(row["glyph"])}</td><td class="c">{esc(row["nr"])}</td>'
            f'<td><a href="#p-{esc(row["slug"])}">{esc(row["topic"])}</a></td>'
            f'<td>{esc(finished_disp)}</td>'
            f'<td class="n">{esc(row["duration_disp"])}</td>'
            f'<td class="n">{esc(fmt_int(row["turns"]))}</td>'
            f'<td class="n">{esc(fmt_int(row["out"]))}</td>'
            f'<td class="n">{esc(fmt_int(row["billable_in"]))}</td>'
            f'<td class="n">{esc(fmt_int(row["cache_read"]))}</td>'
            '</tr>'
        )

    tfoot = (
        '<tfoot><tr>'
        '<td class="c"></td><td class="c"></td><th scope="row">Total</th><td></td>'
        f'<td class="n">{esc(fmt_duration(tot_duration))}</td>'
        f'<td class="n">{esc(fmt_int(tot_turns))}</td>'
        f'<td class="n">{esc(fmt_int(tot_out))}</td>'
        f'<td class="n">{esc(fmt_int(tot_in))}</td>'
        f'<td class="n">{esc(fmt_int(tot_cache))}</td>'
        '</tr></tfoot>'
    )

    return (
        '<section class="phase-table"><h2>Phases</h2><div class="tscroll"><table>'
        '<thead><tr>'
        '<th class="c"><span class="sr">Status</span>·</th><th class="c">#</th><th>Topic</th>'
        '<th>Finished</th><th class="n">Duration</th><th class="n">Turns</th>'
        '<th class="n">Out</th><th class="n">In</th><th class="n">Cache</th>'
        '</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        f'{tfoot}'
        '</table></div></section>'
    )


# ---- verb: html -----------------------------------------------------------------------------

def extract_goal(planfile):
    """First two non-empty lines after a `## Context` heading, word-truncated to 320 chars --
    same extraction as cfq_brief.py's `parse_phase_body`. Budget raised from 220 (which cut
    mid-sentence with no ellipsis) so two full sentences of context fit."""
    try:
        text = pathlib.Path(planfile).read_text()
    except OSError:
        return ""
    return truncate_words(parse_phase_body(text)["context"], 320)


def extract_goals(dir_, data):
    phase_ids = sorted({
        p.get("phase") for p in data.get("phases", [])
        if isinstance(p, dict) and p.get("phase")
    })
    goals = {}
    for p in phase_ids:
        planfile = os.path.join(dir_, "done", f"{p}.md")
        if not os.path.isfile(planfile):
            planfile = os.path.join(dir_, f"{p}.md")
        if not os.path.isfile(planfile):
            continue
        goal = extract_goal(planfile)
        if goal:
            goals[p] = goal
    return goals


def section_list(items, title):
    items = render.jq_alt(items, [])
    if not isinstance(items, list) or len(items) == 0:
        return ""
    lis = "".join(f"<li>{esc(x)}</li>" for x in items)
    return f"<h4>{title}</h4><ul>{lis}</ul>"


def section_list_code(items, title):
    """section_list for entries that are paths or identifiers -- same empty-list contract, each
    item wrapped in <code>."""
    items = render.jq_alt(items, [])
    if not isinstance(items, list) or len(items) == 0:
        return ""
    lis = "".join(f"<li><code>{esc(x)}</code></li>" for x in items)
    return f"<h4>{title}</h4><ul>{lis}</ul>"


# ---- phase 05: the Security section -- the planning-time snapshot `report security` writes,
# rendered once at batch level between the phase table and the phase list.

def _finding_html(finding):
    """A finding renders from the keys it actually has: `severity` and `title` first (joined with
    a space), everything else folded into a muted trailing clause. A bare string renders as
    itself -- both shapes `/pfq`'s Security Check snapshot can carry."""
    if isinstance(finding, str):
        return f"<li>{esc(finding)}</li>"
    if not isinstance(finding, dict):
        return ""
    head = " ".join(esc(finding[k]) for k in ("severity", "title") if finding.get(k) not in (None, ""))
    rest_keys = sorted(k for k in finding.keys() if k not in ("severity", "title"))
    rest = ", ".join(f"{esc(k)}: {esc(finding[k])}" for k in rest_keys)
    if head and rest:
        return f'<li>{head} <span class="muted">({rest})</span></li>'
    if head:
        return f"<li>{head}</li>"
    if rest:
        return f'<li><span class="muted">{rest}</span></li>'
    return "<li></li>"


_SEVERITY_ORDER = ["critical", "high", "moderate", "low"]


def security_html(data):
    """The **last** snapshot in `data["security"]` -- a batch can accumulate more than one, from
    planning time onward. Missing key or empty list -> "", no section (same empty-section rule as
    `section_list`). `available: false`, or `available: true` with nothing in `counts` or
    `findings`, both render as one muted line; `available: true` with something to show renders
    `counts` as the header's `<dl class="meta">` grid, then `findings` as a list (or one muted
    "No findings." line when the list itself is empty but counts are not)."""
    entries = render.jq_alt(data.get("security") if isinstance(data, dict) else None, [])
    if not isinstance(entries, list) or not entries:
        return ""
    entry = entries[-1]
    if not isinstance(entry, dict):
        return ""
    counts = entry.get("counts") if isinstance(entry.get("counts"), dict) else {}
    findings = entry.get("findings") if isinstance(entry.get("findings"), list) else []
    available = bool(entry.get("available"))

    if not available or (not counts and not findings):
        hint = render.jq_alt(entry.get("hint"), "")
        at = fmt_datetime(entry.get("at"))
        when = f" ({at})" if at else ""
        return (
            '<section class="security"><h2>Security</h2>'
            f'<p class="muted">Not available{when} — {esc(hint)}</p></section>'
        )

    keys = [k for k in _SEVERITY_ORDER if k in counts] + sorted(k for k in counts if k not in _SEVERITY_ORDER)
    counts_html = "".join(
        f"<div><dt>{esc(k.capitalize())}</dt><dd>{esc(fmt_int(counts[k]))}</dd></div>" for k in keys
    )
    grid = f'<dl class="meta">{counts_html}</dl>' if counts_html else ""
    if findings:
        body = f'<ul>{"".join(_finding_html(f) for f in findings)}</ul>'
    else:
        body = '<p class="muted">No findings.</p>'
    return f'<section class="security"><h2>Security</h2>{grid}{body}</section>'


def skills_str(t):
    by_skill = t.get("by_skill") if isinstance(t, dict) else None
    if not isinstance(by_skill, dict):
        return "-"
    return ", ".join(sorted(k for k in by_skill.keys() if k != "-"))


def _tele_pair(label, value):
    """One `<dl class="tele">`/`<dl class="meta">` row, or "" when `value` is empty/the `-`
    sentinel -- the one rule both the header and the per-phase telemetry grid share: a pair with
    nothing to say is not rendered, never shown as an empty `<dd>`."""
    if value in ("", "-"):
        return ""
    return f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>"


def telemetry_html(phase):
    t = phase.get("telemetry")
    if not isinstance(t, dict):
        return ""
    totals = t.get("totals") if isinstance(t.get("totals"), dict) else {}
    by_model = t.get("by_model") if isinstance(t.get("by_model"), dict) else {}
    by_effort = t.get("by_effort") if isinstance(t.get("by_effort"), dict) else {}
    pairs = [
        ("Turns", fmt_int(_totals_field(totals, "turns"))),
        ("Duration", fmt_duration(render.jq_alt(t.get("wallclock_s"), 0))),
        ("Out", fmt_int(_totals_field(totals, "output"))),
        ("In", fmt_int(_totals_field(totals, "billable_in"))),
        ("Cache read", fmt_int(_totals_field(totals, "cache_read"))),
        ("Model", ", ".join(sorted(by_model.keys()))),
        ("Effort", ", ".join(sorted(by_effort.keys()))),
    ]
    # Additive, same rule as `report summary`'s fields 12-15: a record with no `mode` (every one
    # written before phase 02) must render exactly as it did before -- no empty "Mode" column, no
    # "None". `mode` can be "" for a planning-only record, which stays omitted too.
    mode = render.jq_alt(t.get("mode"), "")
    if mode:
        pairs.append(("Mode", mode))
    pairs.append(("Skills", skills_str(t)))
    subagent = t.get("subagent") if isinstance(t.get("subagent"), dict) else {}
    sub_turns = render.jq_alt(subagent.get("turns"), 0)
    sub_output = render.jq_alt(subagent.get("output"), 0)
    if sub_turns or sub_output:
        orch_turns = render.jq_alt(totals.get("turns"), 0) - sub_turns
        orch_output = render.jq_alt(totals.get("output"), 0) - sub_output
        pairs.append((
            "Orchestrator / worker",
            f"{fmt_int(orch_turns)}/{fmt_int(sub_turns)} turns · "
            f"{fmt_int(orch_output)}/{fmt_int(sub_output)} out",
        ))
    rows = "".join(_tele_pair(label, value) for label, value in pairs)
    if not rows:
        return ""
    return f'<dl class="tele">{rows}</dl>'


def phase_html(phase, goals):
    status = phase.get("status") or ""
    phase_id = phase.get("phase")
    glyph = status_glyph(status)
    m = _LEADING_DIGITS_RE.match(phase_id) if isinstance(phase_id, str) else None
    nr = m.group(1) if m else ""
    topic = phase_topic(phase_id)
    goal = goals.get(phase_id or "", "")
    parts = [
        f'<section class="phase {status}" id="p-{esc(phase_id)}">',
        f'<h3><span class="badge {status}">{esc(glyph)} {html_escape_jq(status.upper())}</span> '
        f'<span class="num">{esc(nr)}</span> {esc(topic)}</h3>',
        f'<p class="slug">{esc(phase_id)}</p>',
    ]
    if goal:
        parts.append(f'<p class="goal">{esc(goal)}</p>')
    summary = phase_summary(phase)
    if summary:
        parts.append(f'<p>{esc(summary)}</p>')
    parts.append(telemetry_html(phase))
    parts.append(section_list(phase.get("triggers"), "Triggers"))
    parts.append(section_list(phase.get("deviations"), "Deviations"))
    parts.append(section_list(phase.get("errors"), "Errors"))
    parts.append(section_list_code(phase.get("filesTouched"), "Files touched"))
    parts.append(section_list_code(phase.get("parkedPlanEntries"), "Parked plan entries"))
    verification = render.jq_alt(phase.get("verification"), "")
    if verification != "":
        parts.append(f'<p class="verification"><code>{esc(phase.get("verification"))}</code></p>')
    commit = render.jq_alt(phase.get("commit"), "")
    if commit != "":
        parts.append(f'<p class="commit">Commit: <code>{esc(phase.get("commit"))}</code></p>')
    parts.append("</section>")
    return "".join(parts)


def render_report_html(data, goals, dir_):
    batch = data.get("batch")
    phases = data.get("phases", [])
    green_n = sum(1 for p in phases if isinstance(p, dict) and p.get("status") == "green")
    red_n = sum(1 for p in phases if isinstance(p, dict) and p.get("status") == "red")

    status = outcome(phases)
    header_badge = (
        f'<span class="badge {status.lower()}">{esc(status_glyph(status))} '
        f'{html_escape_jq(status)}</span>'
    )

    repo = render.jq_alt(data.get("repo"), "")
    repo_base = os.path.basename(repo.rstrip("/")) if repo else ""
    started = fmt_datetime(data.get("started"))
    finished = fmt_datetime(batch_finished(data))

    meta_rows = [f'<div><dt>Repo</dt><dd title="{esc(repo)}">{esc(repo_base)}</dd></div>']
    meta_rows.append(_tele_pair("Started", started))
    meta_rows.append(_tele_pair("Finished", finished))
    meta_rows.append(_tele_pair("Phases", f"{len(phases)} · {green_n} green · {red_n} red"))

    planning = data.get("planning")
    if planning is not None:
        totals = planning.get("totals") if isinstance(planning, dict) else None
        by_model = planning.get("by_model") if isinstance(planning, dict) else None
        model_join = ", ".join(sorted(by_model.keys())) if isinstance(by_model, dict) else ""
        planning_val = (
            f"{fmt_int(_totals_field(totals, 'output'))} out · "
            f"{fmt_int(_totals_field(totals, 'turns'))} turns"
        )
        if model_join:
            planning_val += f" · {model_join}"
        meta_rows.append(_tele_pair("Planning", planning_val))

    impl_outputs, impl_turns, impl_models = [], [], set()
    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        totals = tel.get("totals") if isinstance(tel, dict) else None
        impl_outputs.append(_totals_field(totals, "output"))
        impl_turns.append(_totals_field(totals, "turns"))
        by_model = render.jq_alt(tel.get("by_model") if isinstance(tel, dict) else None, {})
        if isinstance(by_model, dict):
            impl_models.update(by_model.keys())
    impl_out_total, impl_turns_total = sum(impl_outputs), sum(impl_turns)
    if impl_out_total or impl_turns_total or impl_models:
        impl_val = f"{fmt_int(impl_out_total)} out · {fmt_int(impl_turns_total)} turns"
        if impl_models:
            impl_val += f" · {', '.join(sorted(impl_models))}"
        meta_rows.append(_tele_pair("Implementation", impl_val))

    header = (
        '<header class="batch"><div class="ident">'
        f'<h1>{esc(batch)}</h1> {header_badge}</div>'
        f'<dl class="meta">{"".join(meta_rows)}</dl></header>'
    )

    body = "".join(phase_html(p, goals) for p in phases if isinstance(p, dict))

    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>' + esc(batch) + ' report</title>'
        '<style>' + REPORT_STYLE_CSS + '</style></head><body>'
        + header
        + overview_html(dir_)
        + phase_table_html(phases)
        + security_html(data)
        + '<main>' + body + '</main>'
        + '</body></html>'
    )


def cmd_html(args):
    dir_ = args.dir.rstrip("/")
    f = os.path.join(dir_, "report.json")
    if not os.path.isfile(f):
        errors.die(f"{PROG}: no report.json in {dir_}")
    data = json.loads(pathlib.Path(f).read_text())

    repo_root = repo_root_of(dir_)
    report_dir = settings_get(repo_root, "reportDir")
    out = resolve_html_path(dir_)
    # Unconditional: resolve_html_path() alone decides *where*, this only ensures it exists --
    # the repo-local default (change 1) points at a directory that may not exist yet on the
    # first render, same as the collected-tree case always did.
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
    except OSError:
        errors.die(f"{PROG}: cannot create {os.path.dirname(out)}")

    goals = extract_goals(dir_, data)
    html_doc = render_report_html(data, goals, dir_)
    tmp = f"{out}.tmp"
    pathlib.Path(tmp).write_text(html_doc + "\n")
    os.replace(tmp, out)
    print(out)

    # Collected-tree mode regenerates the cross-repo index; the repo-local default regenerates
    # its own repo-scoped index into the same reports/ directory, once a repo root exists to
    # scope it to (a batch with no derivable repo root has no reports/ dir to index into).
    if report_dir not in ("", "null"):
        regenerate_index(report_dir)
    elif repo_root:
        regenerate_index(f"{repo_root}/.claude/cfq/reports", repo_root_filter=repo_root)


# ---- verbs: index / detail -------------------------------------------------------------------

def run_scan():
    # Direct sibling call, not the dispatcher: cfq_report.py resolves cfq_scan.py relative to
    # its own real location, which would bypass a test double that shadows cfq_scan.py in a copy
    # of this script's directory (see tests/test_report.py's index/scan-count test).
    out = subprocess.run([sys.executable, str(SCRIPT_DIR / "cfq_scan.py")], capture_output=True, text=True)
    return json.loads(out.stdout)


def build_index_rows(repo_filter="", batch_filter="", any_filter=""):
    scan = run_scan()
    meta = []
    rf, bf, af = repo_filter.lower(), batch_filter.lower(), any_filter.lower()
    for r in scan.get("repos", []):
        rpath = r.get("path", "")
        for b in r.get("batches", []):
            if not b.get("report"):
                continue
            name = b.get("name", "")
            if rf and rf not in rpath.lower():
                continue
            if bf and bf not in name.lower():
                continue
            if af and af not in rpath.lower() and af not in name.lower():
                continue
            sub = "impl/done" if b.get("archived") else "impl"
            meta.append({
                "repo": rpath, "name": name,
                "path": f"{rpath}/.claude/cfq/{sub}/{name}/report.json",
            })

    rows = []
    for m in meta:
        try:
            data = json.loads(pathlib.Path(m["path"]).read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        phases = data.get("phases", []) if isinstance(data, dict) else []
        deviations = 0
        for p in phases:
            d = render.jq_alt(p.get("deviations") if isinstance(p, dict) else None, [])
            if isinstance(d, list):
                deviations += len(d)
        date = batch_finished(data)
        status = outcome(phases)

        planning = data.get("planning") if isinstance(data, dict) else None
        planning_totals = planning.get("totals") if isinstance(planning, dict) else None
        planning_output = _totals_field(planning_totals, "output")
        planning_turns = _totals_field(planning_totals, "turns")
        planning_billable_in = _totals_field(planning_totals, "billable_in")
        phase_outputs, phase_turns, phase_billable_in = [], [], []
        for p in phases:
            tel = p.get("telemetry") if isinstance(p, dict) else None
            totals = tel.get("totals") if isinstance(tel, dict) else None
            phase_outputs.append(_totals_field(totals, "output"))
            phase_turns.append(_totals_field(totals, "turns"))
            phase_billable_in.append(_totals_field(totals, "billable_in"))

        # `rendered`/`href` used to be computed a second time, independently, inside
        # regenerate_index() -- both call sites now share this one `resolve_html_path()` answer
        # instead of two copies of the same formula. `href` is the resolved absolute path (or ""
        # when nothing has been rendered yet); regenerate_index() derives its own report-relative
        # link from it rather than re-resolving the layout itself.
        resolved = resolve_html_path(os.path.dirname(m["path"]))
        rendered = os.path.isfile(resolved)

        rows.append({
            "batch": m["name"],
            "repo": m["repo"],
            "date": date,
            "status": status,
            "glyph": status_glyph(status),
            "deviations": deviations,
            "rendered": rendered,
            "href": resolved if rendered else "",
            "cost": {
                "outputTokens": planning_output + sum(phase_outputs),
                "turns": planning_turns + sum(phase_turns),
                # Mirrors outputTokens/turns above (planning's own share folded in, not kept
                # apart) -- a report predating phase 06 has no `billable_in` anywhere, so this
                # sums to 0 via `_totals_field`'s own default, and `fmt_tokens(0)` already
                # renders that as "-", the same placeholder a genuine zero would get. No separate
                # "unavailable" tracking is needed: zero and unknown render identically here, by
                # the same convention `outputTokens` already relies on.
                "inputTokens": planning_billable_in + sum(phase_billable_in),
            },
        })

    rows.sort(key=lambda r: r["date"])
    rows.reverse()
    return rows, meta


def _index_group_lines(repo_key, group_rows, limit):
    """One repo's `### heading` + table + optional "… n more" hint, each block ending in a blank
    line -- the fix for the pasted defect (a Markdown table row followed by a non-blank line
    renders as a further row). `limit <= 0` means no truncation at all."""
    total_out = sum(r["cost"]["outputTokens"] for r in group_rows)
    shown = group_rows if limit <= 0 else group_rows[:limit]
    lines = [f"### {repo_key} · {len(group_rows)} batches · {fmt_tokens(total_out)} out", ""]
    lines.append("| Batch | · | Devs | Date | Out | Turns | In | 📄 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in shown:
        devs_disp = "" if not r["deviations"] else str(r["deviations"])
        date_disp = fmt_short(r["date"]) or "–"
        out_disp = fmt_tokens(r["cost"]["outputTokens"])
        turns_disp = fmt_int(r["cost"]["turns"])
        # `fmt_tokens` -- same rounding as `out_disp` above, and the same "0/negative -> -"
        # convention already covers a report predating phase 06 (no `billable_in` anywhere sums
        # to 0 in build_index_rows), so a missing figure and a genuine zero render identically,
        # exactly as `Out` already does.
        in_disp = fmt_tokens(r["cost"]["inputTokens"])
        rendered_disp = "✓" if r["rendered"] else ""
        lines.append(
            "| " + " | ".join(
                [r["batch"], r["glyph"], devs_disp, date_disp, out_disp, turns_disp, in_disp, rendered_disp]
            ) + " |"
        )
    lines.append("")
    remaining = len(group_rows) - len(shown)
    if remaining > 0:
        lines.append(f"… {remaining} more · --limit 0 shows all")
        lines.append("")
    return lines


def cmd_index(args):
    rows, _meta = build_index_rows(args.repo, args.batch, args.any_filter)
    if not args.text:
        print(render.dump_json(rows))
        return
    if not rows:
        print("No batch has a report yet — reports have existed only since v0.2, so older batches never got one.")
        return

    # One group per repo, newest-group-first without a second sort: `rows` already arrives sorted
    # newest-first across every repo (build_index_rows), so the first row encountered for a given
    # repo is necessarily that repo's own newest -- and since the whole list is date-descending,
    # the order groups are first encountered in is already newest-group-first too.
    groups = {}
    order = []
    for row in rows:
        key = os.path.basename(row["repo"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    out_lines = []
    for key in order:
        out_lines.extend(_index_group_lines(key, groups[key], args.limit))
    print("\n".join(out_lines).rstrip("\n"))


def cmd_detail(args):
    dir_ = args.dir.rstrip("/")
    f = os.path.join(dir_, "report.json")
    if not os.path.isfile(f):
        print(render.dump_json({"found": False}))
        return
    data = json.loads(pathlib.Path(f).read_text())

    repo_root = repo_root_of(dir_)
    todos = []
    if repo_root:
        todo_dir = pathlib.Path(repo_root) / ".claude" / "cfq" / "todo"
        if todo_dir.is_dir():
            for t in sorted(todo_dir.glob("*.md")):
                lines = t.read_text().splitlines()
                title = re.sub(r"^#+\s*", "", lines[0]) if lines else ""
                todos.append({"file": t.name, "title": title})

    phases = data.get("phases", [])
    deviations_total = 0
    for p in phases:
        d = render.jq_alt(p.get("deviations") if isinstance(p, dict) else None, [])
        if isinstance(d, list):
            deviations_total += len(d)

    planning = data.get("planning") if isinstance(data, dict) else None
    planning_totals = planning.get("totals") if isinstance(planning, dict) else None
    planning_output = _totals_field(planning_totals, "output")
    planning_turns = _totals_field(planning_totals, "turns")
    phase_outputs, phase_turns, out_phases = [], [], []
    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        totals = tel.get("totals") if isinstance(tel, dict) else None
        phase_outputs.append(_totals_field(totals, "output"))
        phase_turns.append(_totals_field(totals, "turns"))
        out_phases.append({
            "phase": p.get("phase"),
            "status": p.get("status"),
            "summary": phase_summary(p),
            "deviations": render.jq_alt(p.get("deviations"), []),
            "errors": render.jq_alt(p.get("errors"), []),
            "verification": bound_lines(p.get("verification"), 5),
            "commit": render.jq_alt(p.get("commit"), ""),
            "telemetry": render.jq_alt(p.get("telemetry"), None),
        })

    print(render.dump_json({
        "found": True,
        "batch": data.get("batch"),
        "repo": data.get("repo"),
        "started": data.get("started"),
        "status": outcome(phases),
        "deviationsTotal": deviations_total,
        "cost": {
            "outputTokens": planning_output + sum(phase_outputs),
            "turns": planning_turns + sum(phase_turns),
        },
        "phases": out_phases,
        "todos": todos,
    }))


# ---- collected index.html (reportDir mode) ---------------------------------------------------

def row_html(row):
    """One `<tr>` in a repo's index table. A batch with no HTML rendered yet keeps its row and
    loses only the link (`README.md`: "still listed, just without a link")."""
    status = row.get("status") or ""
    if row.get("rendered"):
        batch_html = f'<a href="{esc(row["href"])}">{esc(row["batch"])}</a>'
    else:
        batch_html = esc(row["batch"])
    out_tokens = render.jq_alt(row.get("cost", {}).get("outputTokens"), 0)
    turns = render.jq_alt(row.get("cost", {}).get("turns"), 0)
    deviations = row.get("deviations")
    devs_disp = fmt_int(deviations) if isinstance(deviations, (int, float)) and deviations > 0 else ""
    return (
        f'<tr class="{esc(status.lower())}"><td class="c">{esc(status_glyph(status))}</td>'
        f'<td>{batch_html}</td>'
        f'<td>{esc(fmt_datetime(row.get("date")))}</td>'
        f'<td class="n">{esc(devs_disp)}</td>'
        f'<td class="n">{esc(fmt_int(out_tokens))}</td>'
        f'<td class="n">{esc(fmt_int(turns))}</td></tr>'
    )


def repo_section_html(repo_base, items):
    """One `<section class="repo">` per repo, the same table shape as phase 04's phase table
    (`.phase-table table,.repo table` share their declarations) so the two pages read as one
    system."""
    total_out = sum(render.jq_alt(it.get("cost", {}).get("outputTokens"), 0) for it in items)
    rows = "".join(row_html(it) for it in items)
    return (
        f'<section class="repo"><h2>{esc(repo_base)} '
        f'<span class="count">{esc(fmt_int(len(items)))} batches · {esc(fmt_tokens(total_out))} out'
        '</span></h2><div class="tscroll"><table><thead><tr>'
        '<th class="c"><span class="sr">Status</span>·</th><th>Batch</th>'
        '<th>Date</th><th class="n">Devs</th><th class="n">Out</th><th class="n">Turns</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div></section>'
    )


def regenerate_index(report_dir, repo_root_filter=None):
    """Writes `<report_dir>/index.html`. `repo_root_filter` scopes the listing to one repo's own
    batches -- used by the repo-local default (change 1), where `report_dir` is that repo's own
    `.claude/cfq/reports/` and cross-repo entries have no business being listed there; omitted
    (`None`) for the shared-`reportDir` collected-tree mode, which lists every repo on purpose.
    `rendered` and the resolved absolute path both come from `build_index_rows()` now -- the one
    place that calls `resolve_html_path()`, the one place that decides the on-disk layout -- this
    function only turns that absolute path into one relative to `report_dir`, rather than
    re-resolving the layout itself a second time."""
    rows, _meta = build_index_rows()
    if repo_root_filter:
        norm = repo_root_filter.rstrip("/")
        rows = [r for r in rows if r["repo"].rstrip("/") == norm]

    groups = {}
    for row in rows:
        rendered = row["rendered"]
        href = os.path.relpath(row["href"], report_dir) if rendered else ""
        repo_base = os.path.basename(row["repo"])
        enriched = {**row, "rendered": rendered, "href": href}
        groups.setdefault(repo_base, []).append(enriched)

    sections = [repo_section_html(key, groups[key]) for key in sorted(groups.keys())]
    body = "".join(sections) if sections else '<p class="meta">No reports yet.</p>'
    total_out = sum(render.jq_alt(r.get("cost", {}).get("outputTokens"), 0) for r in rows)
    header = (
        '<header class="batch"><div class="ident"><h1>cfq reports</h1></div>'
        '<dl class="meta">'
        f'<div><dt>Repos</dt><dd>{esc(fmt_int(len(groups)))}</dd></div>'
        f'<div><dt>Batches</dt><dd>{esc(fmt_int(len(rows)))}</dd></div>'
        f'<div><dt>Output tokens</dt><dd>{esc(fmt_int(total_out))}</dd></div>'
        f'<div><dt>Generated</dt><dd>{esc(datetime.now().strftime("%Y-%m-%d %H:%M"))}</dd></div>'
        '</dl></header>'
    )
    doc = (
        '<!doctype html><html><head><meta charset="utf-8"><title>cfq reports</title>'
        '<style>' + REPORT_STYLE_CSS + '</style></head><body>'
        + header + body + '</body></html>'
    )
    idx_out = os.path.join(report_dir, "index.html")
    tmp = f"{idx_out}.tmp"
    pathlib.Path(tmp).write_text(doc + "\n")
    os.replace(tmp, idx_out)


# ---- argument parsing ------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("security")
    p.add_argument("dir")
    p.add_argument("snap")
    p.set_defaults(func=cmd_security)

    p = sub.add_parser("set-commit")
    p.add_argument("dir")
    p.add_argument("phase_slug")
    p.add_argument("sha")
    p.set_defaults(func=cmd_set_commit)

    p = sub.add_parser("skills")
    p.add_argument("dir")
    p.set_defaults(func=cmd_skills)

    p = sub.add_parser("last-failure")
    p.add_argument("dir")
    p.add_argument("phase_slug")
    p.set_defaults(func=cmd_last_failure)

    p = sub.add_parser("summary")
    p.add_argument("dir")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("html")
    p.add_argument("dir")
    p.set_defaults(func=cmd_html)

    p = sub.add_parser("index")
    p.add_argument("--repo", default="")
    p.add_argument("--batch", default="")
    p.add_argument("--any", dest="any_filter", default="")
    p.add_argument(
        "--limit", type=int, default=10,
        help="rows per repo group in --text mode, 0 for no limit; ignored in JSON mode, "
             "which is never truncated",
    )
    p.add_argument("--text", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("detail")
    p.add_argument("dir")
    p.set_defaults(func=cmd_detail)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(
            f"usage: {PROG} security <batch-dir> <security-json> | "
            f"set-commit <batch-dir> <phase-slug> <sha> | "
            f"skills <batch-dir> | "
            f"last-failure <batch-dir> <phase-slug> | "
            f"summary <batch-dir> | html <batch-dir> | "
            f"index [--repo <substr>] [--batch <substr>] [--any <substr>] [--limit <n>] [--text] | "
            f"detail <batch-dir>"
        )
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
