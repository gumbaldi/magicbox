"""Normalize Codex token records into CFQ's existing report schema."""

import json
import pathlib
from datetime import datetime

import cfq_runtime_codex


def turns(path, since="", upper=""):
    rows = cfq_runtime_codex.records(path)
    model, effort = "?", "?"
    seen = set()
    out = []
    for row in rows:
        payload = row.get("payload") or {}
        if row.get("type") == "turn_context":
            model = payload.get("model") or model
            effort = payload.get("effort") or effort
        if row.get("type") != "token_usage_record":
            continue
        stamp = row.get("timestamp") or ""
        if not stamp or (since and stamp <= since) or (upper and stamp > upper):
            continue
        response_id = payload.get("response_id") or (stamp, len(out))
        if response_id in seen:
            continue
        seen.add(response_id)
        usage = payload.get("usage") or {}
        if not isinstance(usage.get("input_tokens"), int):
            continue
        out.append({"timestamp": stamp, "model": model, "effort": effort, "usage": usage})
    return out


def total(items):
    input_all = sum(t["usage"].get("input_tokens", 0) for t in items)
    cached = sum(t["usage"].get("cached_input_tokens", 0) for t in items)
    creation = sum(t["usage"].get("cache_write_input_tokens", 0) for t in items)
    return {"turns": len(items), "input": max(0, input_all - cached - creation),
            "output": sum(t["usage"].get("output_tokens", 0) for t in items),
            "cache_read": cached, "cache_creation": creation,
            "billable_in": max(0, input_all - cached)}


def grouped(items, key):
    out = {}
    for item in items:
        out.setdefault(item.get(key) or "?", []).append(item)
    return {name: total(group) for name, group in out.items()}


def layer(items, agents):
    return {**total(items), "models": sorted({t["model"] for t in items}),
            "efforts": sorted({t["effort"] for t in items}), "count": agents,
            "by_model": grouped(items, "model")}


def add_totals(items):
    keys = ("turns", "input", "output", "cache_read", "cache_creation", "billable_in")
    return {key: sum(item.get(key, 0) for item in items) for key in keys}


def agent_nodes(repo, sid, since, upper):
    directory = pathlib.Path(repo) / ".claude" / "cfq" / ".codex-agents" / sid
    nodes, grouped_turns = [], {"main_explore": [], "worker": [], "worker_explore": []}
    if not directory.is_dir():
        return nodes, grouped_turns
    for meta_file in sorted(directory.glob("*.json")):
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, ValueError):
            continue
        path = meta.get("transcript") or ""
        if not pathlib.Path(path).is_file():
            continue
        agent_turns = turns(path)
        if not agent_turns:
            continue
        first = agent_turns[0]["timestamp"]
        if (since and first <= since) or (upper and first > upper):
            continue
        kind = meta.get("type") or "unknown"
        parent = meta.get("parent")
        layer_name = "worker" if kind in ("worker", "cfq-phase-worker") else (
            "worker_explore" if parent and any(n["id"] == parent and n["layer"] == "worker" for n in nodes)
            else "main_explore"
        )
        grouped_turns[layer_name].extend(agent_turns)
        nodes.append({"id": meta.get("id") or meta_file.stem, "type": kind,
                      "description": "", "depth": 2 if parent else 1, "parent": parent,
                      "layer": layer_name, "totals": total(agent_turns),
                      "models": sorted({t["model"] for t in agent_turns}),
                      "by_model": grouped(agent_turns, "model"),
                      "efforts": sorted({t["effort"] for t in agent_turns})})
    return nodes, grouped_turns


def _seconds(start, end):
    try:
        return max(0, int((datetime.fromisoformat(end.replace("Z", "+00:00")) -
                           datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()))
    except (ValueError, TypeError):
        return 0


def build_record(path, since, kind, phase, batch, repo, upper="", session=""):
    main = turns(path, since, upper)
    sid = session or cfq_runtime_codex.session_id()
    nodes, agent_turns = agent_nodes(repo, sid, since, upper)
    sub = [t for group in agent_turns.values() for t in group]
    worker = agent_turns["worker"]
    explore = agent_turns["main_explore"] + agent_turns["worker_explore"]
    first = main[0]["timestamp"] if main else ""
    last = main[-1]["timestamp"] if main else ""
    layers = {"main": layer(main, 1)}
    layers.update({key: layer(value, sum(n["layer"] == key for n in nodes))
                   for key, value in agent_turns.items()})
    by_agent = {name: add_totals([n["totals"] for n in nodes if n["type"] == name])
                for name in {n["type"] for n in nodes}}
    return {"schema": 3, "harness": "codex", "kind": kind, "repo": repo, "batch": batch,
            "phase": phase, "mode": "" if kind == "planning" else ("orchestrator" if worker else "classic"),
            "session_id": sid, "branch": "", "cc_version": "", "since": since,
            "settled": False, "rev": 1, "from": first, "until": last,
            "wallclock_s": _seconds(first, last), "totals": total(main),
            "by_model": grouped(main, "model"), "by_effort": grouped(main, "effort"),
            "by_skill": {"-": total(main)}, "by_plugin": {"cfq": total(main)},
            "by_agent": by_agent, "tools": {}, "subagent": total(sub),
            "subagent_worker": total(worker), "subagent_explore": total(explore),
            "agents": nodes, "layers": layers}
