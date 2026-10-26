#!/usr/bin/env python3
# Usage: cfq_report.py security <batch-dir> <security-json>
#        cfq_report.py set-commit <batch-dir> <phase-slug> <sha>
#        cfq_report.py skills <batch-dir>
#        cfq_report.py last-failure <batch-dir> <phase-slug>
#        cfq_report.py summary <batch-dir>
"""Implementation reports per batch. The report lives in the batch directory and travels with it.

Ported from cfq-report.sh -- a port, not a redesign: the CLI contract (verbs, argument order,
JSON shapes, text output, exit codes, error objects) is the invariant this file preserves.
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

from cfq_lib import errors, phase_state, render, text  # noqa: E402
from cfq_lib.proc import cfq_argv  # noqa: E402

PROG = "cfq_report.py"

PHASE_ID_RE = re.compile(r"^[0-9]{2}-.+$")


# ---- jq-semantics helpers -----------------------------------------------------------------

def jq_round(x):
    """Mirrors jq's `round` (round-half-away-from-zero), not Python's round-half-to-even."""
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


# ---- shared report helpers -----------------------------------------------------------------

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


def is_skip_entry(p):
    """A `skipped` ledger entry (written by `phase skip`); it is no attempt at the phase."""
    return isinstance(p, dict) and p.get("status") == "skipped"


def skipped_count(batch_dir):
    """Phases currently skipped, read from the batch's status.json; 0 without a readable one."""
    try:
        return phase_state.counts(pathlib.Path(batch_dir))["skipped"]
    except phase_state.PhaseStateError:
        return 0


def outcome(phases):
    """GREEN if no phase ever went red; RED if any phase's most recent attempt is still red;
    MIXED if every phase that ever went red now shows green as its latest attempt. Skip entries
    are no attempt and are ignored."""
    if not isinstance(phases, list):
        phases = []
    phases = [p for p in phases if not is_skip_entry(p)]
    if not any(isinstance(p, dict) and p.get("status") == "red" for p in phases):
        return "GREEN"
    latest = {}
    for p in phases:
        if isinstance(p, dict):
            latest[p.get("phase", "")] = p.get("status")
    return "RED" if any(v == "red" for v in latest.values()) else "MIXED"


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
    obs = phase_obj.get("observations")
    if "observations" in phase_obj and not (
            isinstance(obs, list) and all(isinstance(o, str) for o in obs)):
        errors.die(f"{PROG} append: observations must be a list of strings, got {obs!r}")

    f = os.path.join(dir_, "report.json")
    ensure_report(dir_)
    data = json.loads(pathlib.Path(f).read_text())
    # The close time is stamped here, by the script: the telemetry record's own wallclock ends
    # when the session's transcript does, which in orchestrator mode is when the worker spawns.
    # `phase_cost_entry()` measures the phase's duration up to this stamp.
    if "finished" not in phase_obj:
        phase_obj["finished"] = render.now_iso()
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


def set_commit(dir_, phase_slug, sha, diffstat=None):
    """Backfills the `commit` field of `phase_slug`'s most recent report.json entry -- factored
    out so `cfq_phase.py commit` can call it directly as part of its own transaction instead of
    shelling back out to this script. A non-None `diffstat` lands in the same write."""
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
    if diffstat is not None:
        phases[matches[-1]]["diffstat"] = diffstat
    render.write_json(f, data)


def cmd_set_commit(args):
    set_commit(args.dir, args.phase_slug, args.sha)


def cmd_skills(args):
    """Used skills per batch, from report.json's telemetry.by_skill (references/ifq-batch-end.md's
    Skills Used)."""
    dir_ = args.dir
    f = os.path.join(dir_, "report.json")
    data = json.loads(pathlib.Path(f).read_text()) if os.path.isfile(f) else {}
    phases = data.get("phases", []) if isinstance(data, dict) else []

    used = set()
    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        if not isinstance(tel, dict):
            continue
        by_skill = render.jq_alt(tel.get("by_skill"), {})
        if isinstance(by_skill, dict):
            used.update(k for k in by_skill.keys() if k != "-")

    print(render.dump_json({"used": sorted(used)}))


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


LAYER_NAMES = ("main", "main_explore", "worker", "worker_explore")


def phase_layer_sums(tel):
    """The four cost layers (`main`, `main_explore`, `worker`, `worker_explore`) for one phase's
    (or planning's) telemetry record, each a plain totals dict callers read with `_totals_field`
    exactly like `tel["totals"]` already was. Reads `layers` when present (schema 2, phase 04's
    `build_layers()`) -- used as-is, never re-derived, so a schema-2 record's own numbers are
    authoritative even where an older sibling key (`totals`/`subagent`) would disagree. A record
    with no `layers` key (schema 1) derives the same four sums from the fields it does carry:
    `main` = `totals`, `worker` = `subagent_worker` (falling back to the legacy collapsed
    `subagent` only when `subagent_worker` is entirely absent -- the same shim `cmd_summary`
    applied before this helper existed), `main_explore` = `subagent_explore`, `worker_explore` =
    empty (no such split existed before schema 2). This is the one place both `cmd_summary` and
    `cfq_portal.py`'s own cost aggregation read a phase's layer split from -- no subtraction
    anywhere downstream, since every layer here is already its own disjoint pool."""
    tel = tel if isinstance(tel, dict) else {}
    layers = tel.get("layers")
    if isinstance(layers, dict):
        return {name: layers.get(name) if isinstance(layers.get(name), dict) else {} for name in LAYER_NAMES}
    worker = tel.get("subagent_worker")
    if worker is None:
        worker = tel.get("subagent")
    return {
        "main": tel.get("totals") if isinstance(tel.get("totals"), dict) else {},
        "main_explore": tel.get("subagent_explore") if isinstance(tel.get("subagent_explore"), dict) else {},
        "worker": worker if isinstance(worker, dict) else {},
        "worker_explore": {},
    }


_LAYER_LABELS = (
    ("main", "session"), ("main_explore", "explore"),
    ("worker", "worker"), ("worker_explore", "worker explore"),
)


def _cost_tokens(n):
    """The plain integer below 1000, otherwise `fmt_tokens()` (`12k`, `4.6M`)."""
    if isinstance(n, (int, float)) and not isinstance(n, bool) and 0 < n < 1000:
        return str(int(n))
    return fmt_tokens(n)


def _cost_num(layer, key):
    v = layer.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _cost_duration(entry, tel):
    start, end = parse_ts(tel.get("from")), parse_ts(entry.get("finished"))
    if start and end:
        seconds = int((end - start).total_seconds())
        if seconds > 0:
            return fmt_duration(seconds)
    wall = tel.get("wallclock_s")
    if isinstance(wall, (int, float)) and not isinstance(wall, bool) and wall > 0:
        return fmt_duration(wall)
    return ""


def phase_cost_entry(dir_, phase_slug):
    """The `Cost` status line for `phase_slug`'s most recent ledger entry in `dir_`'s report.json:
    turns, tokens, duration (the record's `from` up to the entry's script-stamped `finished`),
    the layer split, the models and the commit's diffstat. Renders what the record holds right
    now -- the commit-time state, never corrected later. Returns None when there is no usable
    telemetry; never raises."""
    try:
        data = json.loads(pathlib.Path(dir_, "report.json").read_text())
        entries = [p for p in data.get("phases", []) if isinstance(p, dict) and p.get("phase") == phase_slug]
        if not entries:
            return None
        entry = entries[-1]
        tel = entry.get("telemetry")
        if not isinstance(tel, dict):
            return None
        layers = phase_layer_sums(tel)
        total = {k: sum(_cost_num(layers[n], k) for n in LAYER_NAMES)
                 for k in ("turns", "output", "billable_in", "cache_read")}
        if not any(total.values()):
            return None
        parts = [
            f"{int(total['turns'])} turns", f"{_cost_tokens(total['output'])} out",
            f"{_cost_tokens(total['billable_in'])} in", f"{_cost_tokens(total['cache_read'])} cached",
        ]
        duration = _cost_duration(entry, tel)
        if duration:
            parts.append(duration)
        sub = []
        with_turns = [(label, layers[n]) for n, label in _LAYER_LABELS if _cost_num(layers[n], "turns") > 0]
        if len(with_turns) >= 2:
            sub.append(" · ".join(
                f"{label} {int(_cost_num(l, 'turns'))} turns · {_cost_tokens(_cost_num(l, 'output'))} out"
                for label, l in with_turns))
        if isinstance(tel.get("layers"), dict):
            models = {m for n in LAYER_NAMES for m in (layers[n].get("models") or []) if isinstance(m, str)}
        else:
            by_model = tel.get("by_model")
            models = {m for m in by_model if isinstance(m, str)} if isinstance(by_model, dict) else set()
        if models:
            sub.append("models " + " · ".join(sorted(models)))
        stat = entry.get("diffstat")
        files = stat.get("files") if isinstance(stat, dict) else None
        if isinstance(files, int) and not isinstance(files, bool):
            noun = "file" if files == 1 else "files"
            sub.append(f"diff {files} {noun} · +{stat.get('insertions') or 0} -{stat.get('deletions') or 0}")
        return text.status_entry("Cost", "done", " · ".join(parts), sub=sub)
    except Exception:  # noqa: BLE001 -- a cost line must never cost the phase its close
        return None


def cmd_summary(args):
    dir_ = args.dir
    f = os.path.join(dir_, "report.json")
    if not os.path.isfile(f):
        sys.exit(1)
    data = json.loads(pathlib.Path(f).read_text())
    phases = data.get("phases", [])
    batch = data.get("batch")
    total = sum(1 for p in phases if not is_skip_entry(p))
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

    model_keys, effort_keys = [], []

    # Whole-batch layer sums, planning included -- the fix for the negative orchestrator_turns/
    # orchestrator_output bug: main/main_explore/worker/worker_explore are four disjoint pools
    # read straight from phase_layer_sums(), summed across every record, never subtracted from
    # each other. total_turns/total_output/total_billable_in are the sum of all four; fields
    # 12-15 read `main`/`worker` directly; the tail fields read `main_explore`/`worker_explore`.
    main_turns = main_output = 0
    worker_turns = worker_output = 0
    explore_turns = explore_output = 0
    worker_explore_turns = worker_explore_output = 0
    total_billable_in = 0

    def accumulate(tel):
        nonlocal main_turns, main_output, worker_turns, worker_output
        nonlocal explore_turns, explore_output, worker_explore_turns, worker_explore_output
        nonlocal total_billable_in
        layers = phase_layer_sums(tel)
        main_turns += _totals_field(layers["main"], "turns")
        main_output += _totals_field(layers["main"], "output")
        worker_turns += _totals_field(layers["worker"], "turns")
        worker_output += _totals_field(layers["worker"], "output")
        explore_turns += _totals_field(layers["main_explore"], "turns")
        explore_output += _totals_field(layers["main_explore"], "output")
        worker_explore_turns += _totals_field(layers["worker_explore"], "turns")
        worker_explore_output += _totals_field(layers["worker_explore"], "output")
        for name in LAYER_NAMES:
            total_billable_in += _totals_field(layers[name], "billable_in")

    if planning is not None:
        accumulate(planning)

    for p in phases:
        tel = p.get("telemetry") if isinstance(p, dict) else None
        accumulate(tel)
        by_model = render.jq_alt(tel.get("by_model") if isinstance(tel, dict) else None, {})
        by_effort = render.jq_alt(tel.get("by_effort") if isinstance(tel, dict) else None, {})
        if isinstance(by_model, dict):
            model_keys.extend(by_model.keys())
        if isinstance(by_effort, dict):
            effort_keys.extend(by_effort.keys())

    planning_by_model = render.jq_alt(planning.get("by_model") if isinstance(planning, dict) else None, {})
    planning_by_effort = render.jq_alt(planning.get("by_effort") if isinstance(planning, dict) else None, {})
    if isinstance(planning_by_model, dict):
        model_keys = list(planning_by_model.keys()) + model_keys
    if isinstance(planning_by_effort, dict):
        effort_keys = list(planning_by_effort.keys()) + effort_keys

    total_output = main_output + explore_output + worker_output + worker_explore_output
    total_turns = main_turns + explore_turns + worker_turns + worker_explore_turns
    models = ",".join(sorted(set(model_keys)))
    efforts = ",".join(sorted(set(effort_keys)))

    row = [batch, total, green, red, deviations, date, total_output, planning_output, total_turns, models, efforts]
    # Additive fields 12-15: only when a worker (subagent/orchestrator-mode phase) actually ran --
    # an old or classic-mode report with no worker turns/output must render byte-identical to the
    # row above, not grow a meaningless zero split. 12/13 are the `main` layer's own turns/output,
    # 14/15 the `worker` layer's -- both read straight off phase_layer_sums(), never by
    # subtracting one pool from another, so neither can go negative.
    if worker_output > 0 or worker_turns > 0:
        row += [main_turns, main_output, worker_turns, worker_output]
    # Additive fields, always appended after the optional 12-15 block above: total_billable_in,
    # planning_turns, planning_billable_in, explore_turns, explore_output, worker_explore_turns,
    # worker_explore_output.
    row += [
        total_billable_in, planning_turns, planning_billable_in, explore_turns, explore_output,
        worker_explore_turns, worker_explore_output,
    ]
    # Always the last field: phases currently skipped (status.json), 0 without a status.json.
    row.append(skipped_count(dir_))
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


# ---- report derivations: summary, timestamps, formatting ----------------------------------
#
# Pure functions over a phase dict, no I/O, feeding `report summary` and `cfq_portal.py` (see
# tests/test_report.py's TestDerivations).

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


def fmt_duration(seconds):
    """`"0:46"`, `"1:13"`, `"1:02:03"` -- `m:ss` under an hour, `h:mm:ss` at or above.
    `0`/`None`/a non-numeric value -> "–" (en dash), the placeholder for a missing figure."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not seconds:
        return "–"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_tokens(n):
    """`jq_round`'s `k` rounding, stepped up to one decimal place of `M` above 1,000k (`12.4M`) --
    the one token formatter `phase_cost_entry` uses. `0`/negative/non-numeric -> "–", same placeholder the
    `k`-only rounding already used for a zero cost."""
    if isinstance(n, bool) or not isinstance(n, (int, float)) or n <= 0:
        return "–"
    k = n / 1000.0
    if k < 1000:
        return f"{jq_round(k)}k"
    return f"{k / 1000.0:.1f}M"


# ---- .batch-context.md -> {heading: body}, read by cfq_portal.py -----------------------------

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
            f"summary <batch-dir>"
        )
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
