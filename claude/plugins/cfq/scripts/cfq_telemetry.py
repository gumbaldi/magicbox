#!/usr/bin/env python3
# Usage: cfq_telemetry.py record <batch-dir> planning [--depth quick|thorough|docs] | phase <phase-slug>
#        cfq_telemetry.py record <batch-dir> bootstrap <skill-name> <callCount> <durationMs>
#        cfq_telemetry.py sync [<repo-root>]
#        cfq_telemetry.py show <repo-root> [--session]
#        cfq_telemetry.py settle <repo-root>
"""Telemetry for cfq. Aggregates the running session's transcript into the batch report and a
repo-local JSONL. Numbers, timestamps and names only -- never prompt text, never tool arguments.

Ported from cfq-telemetry.sh -- a port, not a redesign: the CLI contract (verbs, argument order,
JSON shapes, text output, exit codes) is the invariant this file preserves.

A "turn" is one API response, not one transcript line: Claude Code writes one line per content
block of a response, each repeating that response's `message.id` and usage, so lines are collapsed
to one entry per `message.id` (the last one) before anything is summed. A line without a
`message.id` counts as its own response.

A record is written provisional (`settled: false`, `rev: 1`): its session goes on after the commit
(the worker's closing message, the orchestrator's summary, the handoff). `settle` recomputes such a
record once, after its session has ended, and writes it back as `settled: true`, `rev: 2`.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors  # noqa: E402
from cfq_lib import harness  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import portal_hook  # noqa: E402
from cfq_lib import render  # noqa: E402
from cfq_lib.proc import cfq_run, settings_get  # noqa: E402
from cfq_lib.proc import git as proc_git  # noqa: E402

PROG = "cfq_telemetry.py"

USAGE = (
    f"usage: {PROG} record <batch-dir> planning [--depth quick|thorough|docs] | phase <phase-slug> | "
    "sync [<repo-root>] | "
    "show <repo-root> [--session] | settle <repo-root>"
)

# A session whose transcript (or any sub-agent transcript) changed within this many seconds may
# still be running; `settle` leaves its records alone until it has been quiet for that long.
SETTLE_QUIET_SECONDS = 120

# The phase worker's plugin-namespaced agent name -- the one place it is defined is
# agents/cfq-phase-worker.md, which resolves to this form (references/orchestrator.md,
# "Sub-agent type"). A record's `mode` is "orchestrator" exactly when this name shows up in
# `by_agent`, never derived from the `orchestratorMode` setting -- a failed spawn falls back to
# in-session implementation, and a record labelled from the setting would call that phase
# "orchestrator" and poison the comparison mode exists for.
WORKER_AGENT = "cfq:cfq-phase-worker"

TS_TRAILING_MS_RE = re.compile(r"\.\d+Z$")


def git_toplevel(cwd):
    proc = proc_git(cwd, "rev-parse", "--show-toplevel")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def jqor(value, default):
    """Mirrors jq's `//`: only null (None) and false trigger the fallback, "" stays "" ."""
    return default if value is None or value is False else value


def _runtime_args(verb, repo, session):
    args = ["runtime", verb]
    if repo:
        args += ["--repo", repo]
    if session:
        args += ["--session", session]
    return args


def transcript_path(repo="", session=""):
    # pwd-based resolution (matches ctx_usage.py), shared via the runtime adapter. `repo`/`session`
    # address a specific (typically ended) session instead of the running one.
    return cfq_run(*_runtime_args("transcript-path", repo, session)).stdout.strip()


def session_identity():
    """(transcript_path, session_id) for the running session -- the exact `transcript_path()`
    call and `CLAUDE_CODE_SESSION_ID` extraction `cmd_record_phase_or_planning` needs, factored
    into one helper so `telemetry show --session` reuses it verbatim instead of re-deriving
    session identity a second time."""
    return transcript_path(), cfq_run("runtime", "session-id").stdout.strip()


def subagent_dir(repo="", session=""):
    # Same resolution as transcript_path(), shared via the runtime adapter -- the directory is
    # derived, never guessed here (cfq_runtime.py owns every assumption about Claude Code's
    # on-disk layout).
    if harness.codex():
        sid = session or cfq_run("runtime", "session-id").stdout.strip()
        return str(pathlib.Path(repo) / ".claude/cfq/.codex-agents" / sid) if repo and sid else ""
    return cfq_run(*_runtime_args("subagent-dir", repo, session)).stdout.strip()


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


def model_key(item):
    return jqor((item.get("message") or {}).get("model"), "?")


def collapse_responses(entries):
    """One entry per API response: group by `message.id`, keep the last entry of each group, in
    order of first occurrence. An entry without a `message.id` stays its own response. Claude Code
    writes one transcript line per content block, each repeating the response's usage, so summing
    uncollapsed lines inflates every number."""
    out = []
    index = {}
    for e in entries:
        mid = (e.get("message") or {}).get("id")
        if mid is None or mid == "":
            out.append(e)
        elif mid in index:
            out[index[mid]] = e
        else:
            index[mid] = len(out)
            out.append(e)
    return out


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
    empty bound on either side leaves that side unbounded, matching jqor's `//` convention.
    These are transcript lines, not yet responses -- callers pass them through
    collapse_responses() before summing."""
    return [
        e for e in entries
        if e.get("type") == "assistant"
        and (e.get("timestamp") or "") != ""
        and (since == "" or e.get("timestamp") > since)
        and (until == "" or e.get("timestamp") <= until)
    ]


def agent_id_from_path(p):
    """"agent-<id>.jsonl" -> "<id>" -- the id shared verbatim by the sibling
    "agent-<id>.meta.json" and by another agent's own "parentAgentId" (verified against real
    session directories: both name the same string with no further transformation)."""
    name = p.stem
    return name[len("agent-"):] if name.startswith("agent-") else name


def read_agent_meta(subdir, agent_id):
    """The sibling agent-<id>.meta.json for one sub-agent transcript -- agentType, description,
    spawnDepth, parentAgentId (at depth >= 2). None on a missing or malformed file; callers treat
    that the same as "no meta" rather than raising, since a sub-agent transcript predates this
    sibling file existing at all on some hosts."""
    p = pathlib.Path(subdir) / f"agent-{agent_id}.meta.json"
    try:
        with open(p) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parent_chain(parent, meta_by_id):
    """Yields (id, meta) for each ancestor, nearest first, walking `parentAgentId` through
    meta_by_id -- which is built from every meta file in the directory (not just the attributed
    agents), so a depth->=3 agent still resolves through an intermediate parent that has no turns
    of its own here. Stops at a missing/malformed meta. `seen` guards a cyclical parentAgentId from
    looping forever; real sessions never produce one, but a malformed meta file must not hang this."""
    seen = set()
    cur = parent
    while cur and cur not in seen:
        seen.add(cur)
        pmeta = meta_by_id.get(cur)
        if not isinstance(pmeta, dict):
            break
        yield cur, pmeta
        cur = pmeta.get("parentAgentId") or None


def _resolve_layer(agent_type, depth, parent, meta_by_id):
    """worker = type WORKER_AGENT. worker_explore = any agent whose parent chain reaches a
    worker. Everything else -- a depth-1 non-worker, or a chain that runs out (missing/malformed
    meta) before reaching a worker -- is main_explore."""
    if agent_type == WORKER_AGENT:
        return "worker"
    for _, pmeta in _parent_chain(parent, meta_by_id):
        if jqor(pmeta.get("agentType"), "") == WORKER_AGENT:
            return "worker_explore"
    return "main_explore"


def _root_meta(meta, parent, meta_by_id):
    """The meta of the depth-1 agent at the top of an agent's parent chain (the agent's own meta
    when it has no parent); the last reachable one when the chain runs out."""
    root = meta
    for _, pmeta in _parent_chain(parent, meta_by_id):
        root = pmeta
    return root


def tool_use_timestamps(entries):
    """{tool_use.id: timestamp of the transcript line carrying it} over every assistant line of
    the main transcript -- the spawn time of the Agent call an agent's meta `toolUseId` names."""
    out = {}
    for e in entries:
        if e.get("type") != "assistant" or not e.get("timestamp"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tid = c.get("id")
                if tid and tid not in out:
                    out[tid] = e["timestamp"]
    return out


def collect_agent_nodes(since, upper, tool_ts, subagents_dir):
    """One node per agent-<id>.jsonl attributed to the record window (since, upper]. An agent
    belongs to the record when its root's `toolUseId` maps (via `tool_ts`) to a main-transcript
    timestamp inside the window; with no usable link, when the agent's own first response is
    inside it. An attributed agent contributes all of its responses, unclipped. Each node's
    `layer` comes from _resolve_layer(); a missing or unreadable meta counts as depth 1, type
    taken from the turn's own attributionAgent, no parent. Returns (nodes, turns_by_id):
    build_record() needs the raw per-agent turn lists again to sum each layer via sums()."""
    d = subagents_dir
    if not d or not os.path.isdir(d):
        return [], {}

    files = sorted(pathlib.Path(d).glob("agent-*.jsonl"))
    meta_by_id = {agent_id_from_path(p): read_agent_meta(d, agent_id_from_path(p)) for p in files}

    nodes = []
    turns_by_id = {}
    for p in files:
        aid = agent_id_from_path(p)
        try:
            entries = parse_transcript(str(p))
        except (OSError, ValueError):
            continue
        turns = collapse_responses(assistant_turns(entries, "", ""))
        if not turns:
            continue

        meta = meta_by_id.get(aid)
        fallback_type = jqor(turns[0].get("attributionAgent"), "-")
        if isinstance(meta, dict):
            agent_type = jqor(meta.get("agentType"), fallback_type)
            description = jqor(meta.get("description"), "")
            depth = jqor(meta.get("spawnDepth"), 1)
            parent = meta.get("parentAgentId") or None
        else:
            agent_type = fallback_type
            description = ""
            depth = 1
            parent = None

        root = _root_meta(meta, parent, meta_by_id)
        link = root.get("toolUseId") if isinstance(root, dict) else None
        stamp = tool_ts.get(link) if link else None
        if not stamp:
            stamp = turns[0].get("timestamp")
        if not (since == "" or stamp > since) or not (upper == "" or stamp <= upper):
            continue

        turns_by_id[aid] = turns
        nodes.append({
            "id": aid,
            "type": agent_type,
            "description": description,
            "depth": depth,
            "parent": parent,
            "layer": _resolve_layer(agent_type, depth, parent, meta_by_id),
            "totals": sums(turns),
            "models": sorted({model_key(it) for it in turns}),
            "by_model": bucket(turns, model_key),
            "efforts": sorted({jqor(it.get("effort"), "?") for it in turns}),
        })
    return nodes, turns_by_id


def _layer_summary(turns, agents):
    models = sorted({m for a in agents for m in a["models"]})
    efforts = sorted({e for a in agents for e in a["efforts"]})
    return {
        **sums(turns), "models": models, "efforts": efforts, "count": len(agents),
        "by_model": bucket(turns, model_key),
    }


def build_layers(t, nodes, turns_by_id):
    """The four cost layers the report tree groups by: main is the session's own transcript (`t`,
    same list `totals` sums -- count is always 1); main_explore/worker/worker_explore partition
    `nodes` by their resolved `layer`. Invariant (asserted in tests, not just here): main +
    main_explore + worker + worker_explore == totals + subagent, field by field -- main equals
    totals by construction, and every node's turns land in exactly one of the other three layers,
    so their union reproduces `sub` (the attributed agents' own responses) exactly."""
    main_models = sorted({model_key(it) for it in t})
    main_efforts = sorted({jqor(it.get("effort"), "?") for it in t})
    layers = {"main": {
        **sums(t), "models": main_models, "efforts": main_efforts, "count": 1,
        "by_model": bucket(t, model_key),
    }}
    for layer_name in ("main_explore", "worker", "worker_explore"):
        agents = [n for n in nodes if n["layer"] == layer_name]
        turns = [it for n in agents for it in turns_by_id[n["id"]]]
        layers[layer_name] = _layer_summary(turns, agents)
    return layers


def build_record(tf, since, kind, phase, batch, repo, upper="", subagents_dir=""):
    """`upper` bounds the main-transcript window like `since` bounds it from below (default
    unbounded); the same (since, upper] window decides which sub-agents belong to the record.
    `subagents_dir` is the `subagents/` directory of the session `tf` belongs to -- the caller
    resolves it, because settling a record from another session needs that session's directory,
    not the running one's. The record is provisional: `settled: False`, `rev: 1`."""
    entries = parse_transcript(tf)
    raw = assistant_turns(entries, since, upper)
    t = collapse_responses(raw)

    # Tools are counted over the uncollapsed lines (a response's blocks are spread across its
    # lines), each distinct tool_use.id once; a block without an id counts once per occurrence.
    tools = {}
    seen_tool_ids = set()
    for it in raw:
        content = (it.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tid = c.get("id")
                if tid is not None and tid != "":
                    if tid in seen_tool_ids:
                        continue
                    seen_tool_ids.add(tid)
                name = c.get("name")
                tools[name] = tools.get(name, 0) + 1

    first_ts = raw[0].get("timestamp") if raw else None
    last_ts = raw[-1].get("timestamp") if raw else None
    last = raw[-1] if raw else {}

    until = jqor(last_ts, "")
    agent_nodes, agent_turns_by_id = collect_agent_nodes(
        since, upper, tool_use_timestamps(entries), subagents_dir,
    )
    sub = [it for n in agent_nodes for it in agent_turns_by_id[n["id"]]]
    by_agent = bucket(sub, lambda it: jqor(it.get("attributionAgent"), "-"))
    mode = "" if kind == "planning" else ("orchestrator" if WORKER_AGENT in by_agent else "classic")

    # subagent_worker/subagent_explore partition the same `sub` list `subagent` sums as a whole,
    # on the same attribution name `by_agent` already buckets by: WORKER_AGENT turns are phase-worker
    # activity, everything else (Explore included) is exploration. `subagent` itself stays the
    # unchanged sum of both, so nothing that reads it today breaks.
    worker_sub = [it for it in sub if jqor(it.get("attributionAgent"), "-") == WORKER_AGENT]
    explore_sub = [it for it in sub if jqor(it.get("attributionAgent"), "-") != WORKER_AGENT]

    # The four cost layers the per-agent nodes group into (`agents`/`layers`, schema 2; `by_model`
    # on both, schema 3) -- additive, on top of the unchanged `by_agent`/`subagent*` fields above.
    layers = build_layers(t, agent_nodes, agent_turns_by_id)

    return {
        "schema": 3,
        "kind": kind,
        "repo": repo,
        "batch": batch,
        "phase": phase,
        "mode": mode,
        "session_id": jqor(last.get("sessionId"), ""),
        "branch": jqor(last.get("gitBranch"), ""),
        "cc_version": jqor(last.get("version"), ""),
        "since": since,
        "settled": False,
        "rev": 1,
        "from": jqor(first_ts, ""),
        "until": jqor(last_ts, ""),
        "wallclock_s": (ts(last_ts) - ts(first_ts)) if raw else 0,
        "totals": sums(t),
        "by_model": bucket(t, model_key),
        "by_effort": bucket(t, lambda it: jqor(it.get("effort"), "?")),
        "by_skill": bucket(t, lambda it: jqor(it.get("attributionSkill"), "-")),
        "by_plugin": bucket(t, lambda it: jqor(it.get("attributionPlugin"), "-")),
        "by_agent": by_agent,
        "tools": tools,
        "subagent": sums(sub),
        "subagent_worker": sums(worker_sub),
        "subagent_explore": sums(explore_sub),
        "agents": agent_nodes,
        "layers": layers,
    }


def last_until_for_session(jsonl_path, sid):
    """The greatest `until` among the session's lines -- not the last line's: a settled record is
    appended after later ones and carries an `until` that may be older or newer than its
    neighbours'. ISO timestamps compare lexicographically."""
    untils = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("session_id") == sid:
                until = obj.get("until")
                if isinstance(until, str) and until:
                    untils.append(until)
    return max(untils) if untils else ""


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


def _phase_count(dir_):
    """Number of phases in the batch's status.json; 0 when the file is missing or unreadable."""
    try:
        data = json.loads(pathlib.Path(dir_, "status.json").read_text())
        return len(data.get("phases") or {})
    except (OSError, ValueError, AttributeError):
        return 0


def cmd_record_phase_or_planning(dir_, kind, phase, depth=""):
    tf, sid = session_identity()
    if not tf or not os.path.isfile(tf):
        print(f"{PROG}: no transcript found — skipped", file=sys.stderr)
        return

    repo = git_toplevel(dir_)
    jsonl = cfq_lib_paths.telemetry_log(repo)

    since = ""
    if os.path.isfile(jsonl) and sid:
        since = last_until_for_session(jsonl, sid)

    batch = pathlib.Path(dir_).name
    if harness.codex():
        import cfq_telemetry_codex
        rec = cfq_telemetry_codex.build_record(tf, since, kind, phase, batch, repo, session=sid)
    else:
        rec = build_record(tf, since, kind, phase, batch, repo, subagents_dir=subagent_dir())
    if kind == "planning":
        rec["interview_depth"] = depth
        rec["phase_count"] = _phase_count(dir_)
    if rec["totals"]["turns"] == 0:
        print(f"{PROG}: record for '{phase or 'planning'}' has 0 turns — transcript {tf} holds nothing in this window",
              file=sys.stderr)

    os.makedirs(os.path.dirname(jsonl), exist_ok=True)
    with open(jsonl, "a") as f:
        f.write(render.dump_json(rec) + "\n")

    report_path = os.path.join(dir_, "report.json")
    if not os.path.isfile(report_path):
        render.write_json(report_path, {"repo": repo, "batch": batch, "started": render.now_iso(), "phases": []})
    data = json.loads(pathlib.Path(report_path).read_text())
    if kind == "planning":
        data["planning"] = rec
        render.write_json(report_path, data)
        if harness.codex() and sid:
            (pathlib.Path(repo) / ".claude/cfq/.codex-planning" / sid).unlink(missing_ok=True)
    elif data.get("phases"):
        last = data["phases"][-1]
        # Only attach telemetry to the entry it actually belongs to: a phase plan naming
        # `telemetry record ... phase <slug>` as its own verification step runs it *before*
        # `phase commit` appends that phase's own entry, so the last entry in report.json is
        # still the *previous* phase at that point. Attaching there would silently overwrite
        # that phase's own telemetry snapshot (see batch 032). The raw record is never lost --
        # it's already on telemetry.jsonl above -- report.json is simply left untouched.
        if isinstance(last, dict) and last.get("phase") == phase:
            last["telemetry"] = rec
            render.write_json(report_path, data)
        else:
            last_phase = last.get("phase") if isinstance(last, dict) else last
            print(
                f"{PROG}: report.json's last phase is '{last_phase}', not '{phase}' -- "
                "telemetry kept in telemetry.jsonl only",
                file=sys.stderr,
            )

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

    args, depth = list(rest[2:]), ""
    if "--depth" in args:
        i = args.index("--depth")
        if i + 1 >= len(args) or args[i + 1] not in ("quick", "thorough", "docs"):
            errors.die(USAGE)
        depth = args[i + 1]
        del args[i:i + 2]
    phase = args[0] if args else ""
    cmd_record_phase_or_planning(dir_, kind, phase, depth)


def cmd_refresh(rest):
    """Refresh the last Codex phase after its worker's SubagentStop hook has supplied its transcript."""
    if len(rest) != 1:
        errors.die(f"usage: {PROG} refresh <batch-dir>")
    batch_dir = pathlib.Path(rest[0])
    report_path = batch_dir / "report.json"
    try:
        report = json.loads(report_path.read_text())
        entry = report["phases"][-1]
        old = entry["telemetry"]
    except (OSError, ValueError, IndexError, KeyError, TypeError):
        print("UNAVAILABLE")
        return
    sid = cfq_run("runtime", "session-id").stdout.strip()
    if old.get("harness") != "codex" or old.get("session_id") != sid or old.get("kind") != "phase":
        print("UNAVAILABLE")
        return
    import cfq_runtime_codex
    import cfq_telemetry_codex
    path = cfq_runtime_codex.transcript_path(sid)
    if not path:
        print("UNAVAILABLE")
        return
    new = cfq_telemetry_codex.build_record(
        path, old.get("since") or "", "phase", old.get("phase") or "",
        old.get("batch") or batch_dir.name, old.get("repo") or "", session=sid,
    )
    new["rev"] = int(old.get("rev") or 1) + 1
    entry["telemetry"] = new
    render.write_json(report_path, report)
    with open(cfq_lib_paths.telemetry_log(new["repo"]), "a") as stream:
        stream.write(render.dump_json(new) + "\n")
    portal_hook.sync(new["repo"], batches=[batch_dir.name])
    print("OK")


def _record_objects(data):
    """Every telemetry record embedded in one parsed report.json: the top-level `planning` object
    and each phase entry's `telemetry` object, as the live dicts so a caller can rewrite them in
    place."""
    out = []
    planning = data.get("planning")
    if isinstance(planning, dict):
        out.append(planning)
    for entry in data.get("phases") or []:
        tele = entry.get("telemetry") if isinstance(entry, dict) else None
        if isinstance(tele, dict):
            out.append(tele)
    return out


def _newest_mtime(tf, subdir):
    paths = [tf]
    if subdir and os.path.isdir(subdir):
        paths += [os.path.join(subdir, n) for n in os.listdir(subdir)]
    newest = 0.0
    for p in paths:
        try:
            newest = max(newest, os.stat(p).st_mtime)
        except OSError:
            continue
    return newest


def _recompute(old, tf, subdir, upper):
    """The settled replacement of `old`: same window start, bounded above by the next record of
    the same session. None when the transcript cannot be read (treated like a vanished one)."""
    try:
        if old.get("harness") == "codex":
            import cfq_telemetry_codex
            new = cfq_telemetry_codex.build_record(
                tf, old.get("since") or "", old.get("kind"), jqor(old.get("phase"), ""),
                old.get("batch"), old.get("repo"), upper=upper, session=old.get("session_id") or "",
            )
        else:
            new = build_record(
                tf, old.get("since") or "", old.get("kind"), jqor(old.get("phase"), ""),
                old.get("batch"), old.get("repo"), upper=upper, subagents_dir=subdir,
            )
    except (OSError, ValueError):
        return None
    if not new["session_id"]:
        new["session_id"] = old.get("session_id", "")
    for key in ("interview_depth", "phase_count"):
        if key in old:
            new[key] = old[key]
    return new


def cmd_settle(rest):
    """Recompute every provisional record whose session has ended, exactly once -- see the module
    docstring. Runs as a side effect of the next cfq mutation in the repo (`portal_hook.sync()`),
    never from a hook of its own."""
    if not rest:
        errors.die(f"usage: {PROG} settle <repo-root>")
    repo = rest[0]
    impl = cfq_lib_paths.impl_dir(repo)
    if not os.path.isdir(impl):
        print(render.dump_json({"status": "NO_REPO", "settled": 0, "pending": 0}))
        return

    reports = {}
    for pattern in ("*/report.json", "done/*/report.json"):
        for p in sorted(pathlib.Path(impl).glob(pattern)):
            try:
                data = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                reports[str(p)] = data

    # Window upper bound per record: the smallest `since` of a later record of the same session.
    sinces = {}
    for data in reports.values():
        for r in _record_objects(data):
            if r.get("session_id") and isinstance(r.get("since"), str):
                sinces.setdefault(r["session_id"], set()).add(r["since"])

    running = cfq_run("runtime", "session-id").stdout.strip()
    now = time.time()
    settled, pending, appended, dirty = 0, 0, [], set()
    for path, data in reports.items():
        for rec in _record_objects(data):
            if rec.get("settled") is not False:
                continue
            sid = rec.get("session_id") or ""
            if sid and sid == running:
                pending += 1
                continue
            if rec.get("harness") == "codex" and sid:
                import cfq_runtime_codex
                tf = cfq_runtime_codex.transcript_path(sid)
                subdir = str(pathlib.Path(repo) / ".claude/cfq/.codex-agents" / sid) if tf else ""
            else:
                tf = transcript_path(repo, sid) if sid else ""
                subdir = subagent_dir(repo, sid) if tf else ""
            if tf and now - _newest_mtime(tf, subdir) < SETTLE_QUIET_SECONDS:
                pending += 1
                continue

            since = rec.get("since") or ""
            later = [s for s in sinces.get(sid, ()) if s > since]
            new = _recompute(rec, tf, subdir, min(later) if later else "") if tf else None
            rev = rec.get("rev") if isinstance(rec.get("rev"), int) else 1
            if new is None:
                new = dict(rec)
            new["settled"] = True
            new["rev"] = rev + 1
            rec.clear()
            rec.update(new)
            appended.append(new)
            dirty.add(path)
            settled += 1

    for path in sorted(dirty):
        render.write_json(path, reports[path])
    if appended:
        jsonl = cfq_lib_paths.telemetry_log(repo)
        os.makedirs(os.path.dirname(jsonl), exist_ok=True)
        with open(jsonl, "a") as f:
            for rec in appended:
                f.write(render.dump_json(rec) + "\n")
    print(render.dump_json({"status": "OK", "settled": settled, "pending": pending}))


def cmd_sync(rest):
    repo = rest[0] if rest else git_toplevel(os.getcwd())
    if not repo:
        return

    target = settings_get(repo, "telemetrySyncRepo")
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
    # Deliberately not proc_git: these do not capture output, so git's own errors reach the terminal.
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


LAYER_NAMES = ("main", "main_explore", "worker", "worker_explore")


def _record_layers(r):
    """The four cost layers for one stored telemetry.jsonl record -- same fallback
    cfq_report.py's `phase_layer_sums()` uses, since a planning or phase record read back off
    disk carries exactly the shape either wrote it in (`build_record()`'s own return value).
    Reads `layers` when present (schema 2). An older schema-1 record derives them: `main` =
    `totals`, `worker` = `subagent_worker` (falling back to the legacy collapsed `subagent` only
    when `subagent_worker` is entirely absent), `main_explore` = `subagent_explore`,
    `worker_explore` = empty (no such split existed before schema 2)."""
    r = r if isinstance(r, dict) else {}
    layers = r.get("layers")
    if isinstance(layers, dict):
        return {name: layers.get(name) if isinstance(layers.get(name), dict) else {} for name in LAYER_NAMES}
    worker = r.get("subagent_worker")
    if worker is None:
        worker = r.get("subagent")
    return {
        "main": r.get("totals") if isinstance(r.get("totals"), dict) else {},
        "main_explore": r.get("subagent_explore") if isinstance(r.get("subagent_explore"), dict) else {},
        "worker": worker if isinstance(worker, dict) else {},
        "worker_explore": {},
    }


def aggregate_show(records):
    """One JSON object out of a list of parsed telemetry.jsonl records -- the numbers `pfq`'s
    `Cost` line needs. `turns`/`output`/`billable_in` are whole-session sums: every record's four
    cost layers (`main`, `main_explore`, `worker`, `worker_explore`, read via `_record_layers()`)
    added together, so a planning session's own Explore- or worker-agent usage is never invisible
    at the top level. `cache_read` stays sourced from each record's own `totals.cache_read` only
    (unaffected by the layer split -- cache reads aren't meaningfully additive across layers the
    way turns/output are). `layers` carries the same four sums separately, so a caller that wants
    the split (rather than only the total) doesn't have to re-derive it; `subagent_explore` stays
    as its own key with the unchanged shape, so the existing key keeps working. Skips anything
    that isn't a `planning`/`phase` record structurally (a bootstrap entry has no `totals`) rather
    than raising on it."""
    cache_read = 0
    model_keys, effort_keys = [], []
    layer_totals = {name: {"turns": 0, "output": 0, "billable_in": 0} for name in LAYER_NAMES}
    for r in records:
        if not isinstance(r, dict):
            continue
        totals = r.get("totals") if isinstance(r.get("totals"), dict) else None
        if totals:
            cache_read += _totals_field(totals, "cache_read")
        by_model = r.get("by_model")
        if isinstance(by_model, dict):
            model_keys.extend(by_model.keys())
        by_effort = r.get("by_effort")
        if isinstance(by_effort, dict):
            effort_keys.extend(by_effort.keys())

        layers = _record_layers(r)
        for name in LAYER_NAMES:
            for field in ("turns", "output", "billable_in"):
                layer_totals[name][field] += _totals_field(layers[name], field)

    turns = sum(layer_totals[name]["turns"] for name in LAYER_NAMES)
    output = sum(layer_totals[name]["output"] for name in LAYER_NAMES)
    billable_in = sum(layer_totals[name]["billable_in"] for name in LAYER_NAMES)

    return {
        "turns": turns,
        "output": output,
        "billable_in": billable_in,
        "cache_read": cache_read,
        "models": ",".join(sorted(set(model_keys))),
        "efforts": ",".join(sorted(set(effort_keys))),
        "subagent_explore": {
            "turns": layer_totals["main_explore"]["turns"],
            "output": layer_totals["main_explore"]["output"],
        },
        "layers": layer_totals,
    }


def _totals_field(totals, key):
    return jqor(totals.get(key) if isinstance(totals, dict) else None, 0)


def latest_revs(records):
    """Keep only the highest `rev` per (session_id, kind, batch, phase, since): a settled record is
    appended next to its provisional one, never replacing it on disk. A record without `rev`
    counts as rev 0, so it loses against any revision of the same key and is otherwise kept as
    it is."""
    def key_of(r):
        return tuple(r.get(k) for k in ("session_id", "kind", "batch", "phase", "since"))

    best = {}
    for i, r in enumerate(records):
        if isinstance(r, dict) and isinstance(r.get("rev"), int):
            key = key_of(r)
            if key not in best or r["rev"] > records[best[key]]["rev"]:
                best[key] = i
    return [
        r for i, r in enumerate(records)
        if not isinstance(r, dict) or best.get(key_of(r), i) == i
    ]


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

    records = latest_revs(records)
    if session_only:
        _, sid = session_identity()
        records = [r for r in records if isinstance(r, dict) and r.get("session_id") == sid]

    print(render.dump_json(aggregate_show(records)))


def main(argv):
    cmd = argv[0] if argv else ""
    rest = argv[1:]
    if cmd == "record":
        cmd_record(rest)
    elif cmd == "refresh":
        cmd_refresh(rest)
    elif cmd == "sync":
        cmd_sync(rest)
    elif cmd == "show":
        cmd_show(rest)
    elif cmd == "settle":
        cmd_settle(rest)
    else:
        errors.die(USAGE)


if __name__ == "__main__":
    main(sys.argv[1:])
