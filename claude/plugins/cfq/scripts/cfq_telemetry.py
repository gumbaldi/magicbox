#!/usr/bin/env python3
# Usage: cfq_telemetry.py record <batch-dir> planning|phase [<phase-slug>]
#        cfq_telemetry.py record <batch-dir> bootstrap <skill-name> <callCount> <durationMs>
#        cfq_telemetry.py sync [<repo-root>]
#        cfq_telemetry.py show <repo-root> [--session]
"""Telemetry for cfq. Aggregates the running session's transcript into the batch report and a
repo-local JSONL. Numbers, timestamps and names only -- never prompt text, never tool arguments.

Ported from cfq-telemetry.sh -- a port, not a redesign: the CLI contract (verbs, argument order,
JSON shapes, text output, exit codes) is the invariant this file preserves.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import render  # noqa: E402
from cfq_lib.proc import cfq_run  # noqa: E402

PROG = "cfq_telemetry.py"

USAGE = (
    f"usage: {PROG} record <batch-dir> planning|phase [<phase-slug>] | sync [<repo-root>] | "
    "show <repo-root> [--session]"
)

# The phase worker's plugin-namespaced agent name -- the one place it is defined is
# agents/cfq-phase-worker.md, which resolves to this form (references/orchestrator.md,
# "Sub-agent type"). A record's `mode` is "orchestrator" exactly when this name shows up in
# `by_agent`, never derived from the `orchestratorMode` setting -- a failed spawn falls back to
# in-session implementation, and a record labelled from the setting would call that phase
# "orchestrator" and poison the comparison mode exists for.
WORKER_AGENT = "cfq:cfq-phase-worker"

RECOMMENDED_HEADING_RE = re.compile(r"^## Empfohlene Skills")
HEADING_RE = re.compile(r"^## ")
RECOMMENDED_ITEM_RE = re.compile(r"^- ([A-Za-z0-9:._-]+)")
TS_TRAILING_MS_RE = re.compile(r"\.\d+Z$")


def git_toplevel(cwd):
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def jqor(value, default):
    """Mirrors jq's `//`: only null (None) and false trigger the fallback, "" stays "" ."""
    return default if value is None or value is False else value


def transcript_path():
    # pwd-based resolution (matches ctx_usage.py), shared via the runtime adapter.
    return cfq_run("runtime", "transcript-path").stdout.strip()


def session_identity():
    """(transcript_path, session_id) for the running session -- the exact `transcript_path()`
    call and `CLAUDE_CODE_SESSION_ID` extraction `cmd_record_phase_or_planning` needs, factored
    into one helper so `telemetry show --session` reuses it verbatim instead of re-deriving
    session identity a second time."""
    return transcript_path(), os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def subagent_dir():
    # Same pwd-based resolution as transcript_path(), shared via the runtime adapter -- the
    # directory is derived, never guessed here (cfq_runtime.py owns every assumption about
    # Claude Code's on-disk layout).
    return cfq_run("runtime", "subagent-dir").stdout.strip()


def extract_recommended_skills(dir_, phase):
    if not phase:
        return []
    pf = pathlib.Path(dir_) / f"{phase}.md"
    if not pf.is_file():
        pf = pathlib.Path(dir_) / "done" / f"{phase}.md"
    if not pf.is_file():
        return []
    lines = pf.read_text().splitlines()
    start = None
    for i, line in enumerate(lines):
        if RECOMMENDED_HEADING_RE.match(line):
            start = i
            break
    if start is None:
        return []
    block = [lines[start]]
    for line in lines[start + 1:]:
        block.append(line)
        if HEADING_RE.match(line):
            break
    recommended = []
    for line in block:
        m = RECOMMENDED_ITEM_RE.match(line)
        if m:
            recommended.append(m.group(1))
    return recommended


def parse_transcript(tf):
    entries = []
    with open(tf) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def ts(value):
    if not value:
        return 0
    v = TS_TRAILING_MS_RE.sub("Z", value)
    try:
        dt = datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return 0
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def usage_field(item, field):
    return jqor(((item.get("message") or {}).get("usage") or {}).get(field), 0)


def sums(items):
    inp = sum(usage_field(it, "input_tokens") for it in items)
    out = sum(usage_field(it, "output_tokens") for it in items)
    cache_read = sum(usage_field(it, "cache_read_input_tokens") for it in items)
    cache_creation = sum(usage_field(it, "cache_creation_input_tokens") for it in items)
    return {
        "turns": len(items),
        "input": inp,
        "output": out,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        # cache_read repeats the same prefix on every turn -- summing it across turns counts
        # the same tokens dozens of times. billable_in is the part that is actually new per
        # turn and is the number to compare phases by; cache_read stays available as a raw
        # metric.
        "billable_in": inp + cache_creation,
    }


def bucket(items, keyfn):
    groups = {}
    order = []
    for it in items:
        k = keyfn(it)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(it)
    return {k: sums(groups[k]) for k in order}


def assistant_turns(entries, since, until):
    """type==assistant, timestamped entries whose timestamp falls inside (since, until] -- an
    empty bound on either side leaves that side unbounded, matching jqor's `//` convention."""
    return [
        e for e in entries
        if e.get("type") == "assistant"
        and (e.get("timestamp") or "") != ""
        and (since == "" or e.get("timestamp") > since)
        and (until == "" or e.get("timestamp") <= until)
    ]


def subagent_turns(since, until):
    """Every agent-*.jsonl in the resolved subagents/ directory, parsed with the same
    parse_transcript() the main transcript uses (sub-agent entries share its shape), filtered to
    the same (since, until] window the main-transcript turns were filtered to -- this is what
    keeps a per-phase record holding only that phase's own worker, not every sub-agent the
    session ever spawned."""
    d = subagent_dir()
    if not d or not os.path.isdir(d):
        return []
    entries = []
    for p in sorted(pathlib.Path(d).glob("agent-*.jsonl")):
        try:
            entries.extend(parse_transcript(str(p)))
        except (OSError, ValueError):
            continue
    return assistant_turns(entries, since, until)


def build_record(tf, since, kind, phase, batch, repo, recommended):
    entries = parse_transcript(tf)
    t = assistant_turns(entries, since, "")

    tools = {}
    for it in t:
        content = (it.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                name = c.get("name")
                tools[name] = tools.get(name, 0) + 1

    first_ts = t[0].get("timestamp") if t else None
    last_ts = t[-1].get("timestamp") if t else None
    last = t[-1] if t else {}

    sub = subagent_turns(since, jqor(last_ts, ""))
    by_agent = bucket(sub, lambda it: jqor(it.get("attributionAgent"), "-"))
    mode = "" if kind == "planning" else ("orchestrator" if WORKER_AGENT in by_agent else "classic")

    # subagent_worker/subagent_explore partition the same `sub` list `subagent` sums as a whole,
    # on the same attribution name `by_agent` already buckets by: WORKER_AGENT turns are phase-worker
    # activity, everything else (Explore included) is exploration. `subagent` itself stays the
    # unchanged sum of both, so nothing that reads it today breaks.
    worker_sub = [it for it in sub if jqor(it.get("attributionAgent"), "-") == WORKER_AGENT]
    explore_sub = [it for it in sub if jqor(it.get("attributionAgent"), "-") != WORKER_AGENT]

    return {
        "schema": 1,
        "kind": kind,
        "repo": repo,
        "batch": batch,
        "phase": phase,
        "mode": mode,
        "session_id": jqor(last.get("sessionId"), ""),
        "branch": jqor(last.get("gitBranch"), ""),
        "cc_version": jqor(last.get("version"), ""),
        "from": jqor(first_ts, ""),
        "until": jqor(last_ts, ""),
        "wallclock_s": (ts(last_ts) - ts(first_ts)) if t else 0,
        "totals": sums(t),
        "by_model": bucket(t, lambda it: jqor((it.get("message") or {}).get("model"), "?")),
        "by_effort": bucket(t, lambda it: jqor(it.get("effort"), "?")),
        "by_skill": bucket(t, lambda it: jqor(it.get("attributionSkill"), "-")),
        "by_plugin": bucket(t, lambda it: jqor(it.get("attributionPlugin"), "-")),
        "by_agent": by_agent,
        "tools": tools,
        "subagent": sums(sub),
        "subagent_worker": sums(worker_sub),
        "subagent_explore": sums(explore_sub),
        "skills_recommended": recommended,
    }


def last_until_for_session(jsonl_path, sid):
    matches = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("session_id") == sid:
                until = obj.get("until")
                matches.append("null" if until is None else until)
    since = matches[-1] if matches else ""
    return "" if since == "null" else since


def cmd_record_bootstrap(dir_, skill, call_count_s, duration_ms_s):
    if not call_count_s.isdigit():
        errors.die(f"{PROG}: callCount must be a non-negative integer")
    if not duration_ms_s.isdigit():
        errors.die(f"{PROG}: durationMs must be a non-negative integer")

    repo = git_toplevel(dir_)
    jsonl = cfq_lib_paths.telemetry_log(repo)
    rec = {
        "schema": 1,
        "kind": "bootstrap",
        "repo": repo,
        "batch": pathlib.Path(dir_).name,
        "skill": skill,
        "call_count": int(call_count_s),
        "duration_ms": int(duration_ms_s),
        "timestamp": render.now_iso(),
    }
    os.makedirs(os.path.dirname(jsonl), exist_ok=True)
    with open(jsonl, "a") as f:
        f.write(render.dump_json(rec) + "\n")
    print(f"telemetry: bootstrap {rec['skill']} {rec['call_count']} calls / {rec['duration_ms']} ms")


def cmd_record_phase_or_planning(dir_, kind, phase):
    tf, sid = session_identity()
    if not tf or not os.path.isfile(tf):
        print(f"{PROG}: no transcript found — skipped", file=sys.stderr)
        return

    repo = git_toplevel(dir_)
    jsonl = cfq_lib_paths.telemetry_log(repo)

    since = ""
    if os.path.isfile(jsonl) and sid:
        since = last_until_for_session(jsonl, sid)

    recommended = extract_recommended_skills(dir_, phase)
    batch = pathlib.Path(dir_).name
    rec = build_record(tf, since, kind, phase, batch, repo, recommended)

    os.makedirs(os.path.dirname(jsonl), exist_ok=True)
    with open(jsonl, "a") as f:
        f.write(render.dump_json(rec) + "\n")

    report_path = os.path.join(dir_, "report.json")
    if not os.path.isfile(report_path):
        render.write_json(report_path, {"repo": repo, "batch": batch, "started": render.now_iso(), "phases": []})
    data = json.loads(pathlib.Path(report_path).read_text())
    if kind == "planning":
        data["planning"] = rec
    elif data.get("phases"):
        data["phases"][-1]["telemetry"] = rec
    render.write_json(report_path, data)

    totals = rec["totals"]
    print(
        f"telemetry: {totals['turns']} turns, {totals['output']} out / "
        f"{totals['billable_in']} in ({totals['cache_read']} cached)"
    )


def cmd_record(rest):
    if len(rest) < 2:
        errors.die(USAGE)
    dir_, kind = rest[0], rest[1]
    if not os.path.isdir(dir_):
        errors.die(f"{PROG}: no such batch directory: {dir_}")

    if kind == "bootstrap":
        if len(rest) < 5:
            errors.die(USAGE)
        cmd_record_bootstrap(dir_, rest[2], rest[3], rest[4])
        return

    phase = rest[2] if len(rest) > 2 else ""
    cmd_record_phase_or_planning(dir_, kind, phase)


def cmd_sync(rest):
    repo = rest[0] if rest else git_toplevel(os.getcwd())
    if not repo:
        return

    target = cfq_run("settings", "get", "telemetrySyncRepo").stdout.strip()
    if target in ("", "null"):
        return

    src = cfq_lib_paths.telemetry_log(repo)
    if not os.path.isfile(src):
        return

    if not os.path.isdir(os.path.join(target, ".git")):
        print(f"{PROG}: {target} is no git repo — sync skipped", file=sys.stderr)
        return

    marker = os.path.join(cfq_lib_paths.cfq_repo_dir(repo), ".telemetry-synced")
    n = 0
    if os.path.isfile(marker):
        raw = pathlib.Path(marker).read_text().strip()
        n = int(raw) if raw.isdigit() else 0

    with open(src) as f:
        lines = f.readlines()
    total = len(lines)
    if total <= n:
        print("telemetry sync: nothing new")
        return

    name = f"{pathlib.Path(repo).name}.jsonl"
    target_file = os.path.join(target, name)
    with open(target_file, "a") as f:
        f.writelines(lines[n:])
    pathlib.Path(marker).write_text(f"{total}\n")

    added = total - n
    # Never fatal: a broken sync repo must not abort an implementation session.
    ok = (
        subprocess.run(["git", "-C", target, "add", "--", name]).returncode == 0
        and subprocess.run(
            ["git", "-C", target, "commit", "-q", "-m", f"telemetry: {pathlib.Path(repo).name} +{added}"]
        ).returncode == 0
        and subprocess.run(["git", "-C", target, "push", "-q"]).returncode == 0
    )
    if ok:
        print(f"telemetry sync: +{added} -> {target_file} (committed, pushed)")
    else:
        print(f"telemetry sync: +{added} written to {target_file}, git step failed (non-fatal)", file=sys.stderr)


def aggregate_show(records):
    """One JSON object out of a list of parsed telemetry.jsonl records -- the numbers `pfq`'s
    `Cost` line needs (turns, output, billable_in, cache_read, models, efforts) plus
    subagent_explore, so a planning session's own Explore-agent usage stops being invisible. Skips
    anything that isn't a `planning`/`phase` record structurally (a bootstrap entry has no
    `totals`) rather than raising on it."""
    turns = output = billable_in = cache_read = 0
    explore_turns = explore_output = 0
    model_keys, effort_keys = [], []
    for r in records:
        if not isinstance(r, dict):
            continue
        totals = r.get("totals") if isinstance(r.get("totals"), dict) else None
        if totals:
            turns += _totals_field(totals, "turns")
            output += _totals_field(totals, "output")
            billable_in += _totals_field(totals, "billable_in")
            cache_read += _totals_field(totals, "cache_read")
        by_model = r.get("by_model")
        if isinstance(by_model, dict):
            model_keys.extend(by_model.keys())
        by_effort = r.get("by_effort")
        if isinstance(by_effort, dict):
            effort_keys.extend(by_effort.keys())
        explore = r.get("subagent_explore")
        if isinstance(explore, dict):
            explore_turns += _totals_field(explore, "turns")
            explore_output += _totals_field(explore, "output")
    return {
        "turns": turns,
        "output": output,
        "billable_in": billable_in,
        "cache_read": cache_read,
        "models": ",".join(sorted(set(model_keys))),
        "efforts": ",".join(sorted(set(effort_keys))),
        "subagent_explore": {"turns": explore_turns, "output": explore_output},
    }


def _totals_field(totals, key):
    return jqor(totals.get(key) if isinstance(totals, dict) else None, 0)


def cmd_show(rest):
    if not rest:
        errors.die(f"usage: {PROG} show <repo-root> [--session]")
    repo_root, session_only = rest[0], "--session" in rest[1:]

    jsonl = cfq_lib_paths.telemetry_log(repo_root)
    records = []
    if os.path.isfile(jsonl):
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue

    if session_only:
        _, sid = session_identity()
        records = [r for r in records if isinstance(r, dict) and r.get("session_id") == sid]

    print(render.dump_json(aggregate_show(records)))


def main(argv):
    cmd = argv[0] if argv else ""
    rest = argv[1:]
    if cmd == "record":
        cmd_record(rest)
    elif cmd == "sync":
        cmd_sync(rest)
    elif cmd == "show":
        cmd_show(rest)
    else:
        errors.die(USAGE)


if __name__ == "__main__":
    main(sys.argv[1:])
