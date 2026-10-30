"""Codex runtime adapter. Only this module understands Codex session records."""

import json
import os
import pathlib
import re
import sys

from cfq_lib.env import home_dir
from cfq_lib.render import dump_json


def session_id():
    return os.environ.get("CFQ_SESSION_ID", "")


def transcript_path(session=""):
    sid = session or session_id()
    if not sid or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        return ""
    current = os.environ.get("CFQ_TRANSCRIPT_PATH", "")
    if sid == session_id() and current and pathlib.Path(current).is_file():
        return current
    root = home_dir() / ".codex" / "sessions"
    if not root.is_dir():
        return ""
    for p in root.rglob(f"*{sid}.jsonl"):
        if p.name.endswith(f"-{sid}.jsonl") and p.is_file():
            return str(p)
    return ""


def records(path):
    try:
        with open(path) as stream:
            return [json.loads(line) for line in stream if line.strip()]
    except (OSError, ValueError):
        return []


def _last(rows, kind):
    return next((r.get("payload") or {} for r in reversed(rows) if r.get("type") == kind), {})


def context():
    path = transcript_path()
    rows = records(path) if path else []
    usage = _last(rows, "token_usage_record").get("usage") or {}
    # Older Codex releases expose the last response through token_count instead.
    if not usage:
        for row in reversed(rows):
            p = row.get("payload") or {}
            if row.get("type") == "event_msg" and p.get("type") == "token_count":
                usage = (p.get("info") or {}).get("last_token_usage") or {}
                if usage:
                    break
    turn = _last(rows, "turn_context")
    model = os.environ.get("CFQ_MODEL") or turn.get("model")
    active_effort = turn.get("effort")
    window = turn.get("model_context_window")
    if not isinstance(window, int) or window <= 0:
        for row in reversed(rows):
            p = row.get("payload") or {}
            candidate = p.get("model_context_window") or (p.get("info") or {}).get("model_context_window")
            if isinstance(candidate, int) and candidate > 0:
                window = candidate
                break
    used = usage.get("input_tokens")
    if not isinstance(used, int):
        used = None
    cache_read = usage.get("cached_input_tokens", 0)
    cache_creation = usage.get("cache_write_input_tokens", 0)
    cache = None
    if used is not None:
        cache = {"fresh": max(0, used - cache_read - cache_creation),
                 "creation": cache_creation, "read": cache_read}
    status = "ok" if used is not None else "unavailable"
    code = None if used is not None else ("RUNTIME_UNBOUND" if not session_id() else "RUNTIME_SOURCE_MISSING")
    return {"status": status, "pct": used * 100 // window if used is not None and window else None,
            "windowSize": window, "used": used, "model": model, "effort": active_effort,
            "source": "codex-transcript" if rows else None,
            "note": f"{used}/{window or '?'}, src=codex-transcript" if used is not None else "Codex usage unavailable",
            "code": code, "diagnostic": None, "cache": cache, "rateLimits": None}


def main(argv):
    cmd = argv[0] if argv else ""
    rest = argv[1:]
    session = ""
    if "--session" in rest:
        i = rest.index("--session")
        if i + 1 >= len(rest):
            raise SystemExit("--session requires an id")
        session = rest[i + 1]
    if cmd == "session-id":
        print(session_id())
    elif cmd == "transcript-path":
        print(transcript_path(session))
    elif cmd == "subagent-dir":
        print("")
    elif cmd == "context":
        print(dump_json(context()))
    elif cmd == "model":
        print(dump_json(context()["model"]))
    elif cmd == "version":
        print(dump_json(_last(records(transcript_path()), "session_meta").get("cli_version")))
    elif cmd == "capabilities":
        print(dump_json({"statuslinePayload": False, "transcriptAvailable": bool(transcript_path())}))
    elif cmd == "plugins":
        print(dump_json({"status": "OK", "plugins": [], "ponytailMode": "unknown"}))
    elif cmd == "plugin-installed":
        print(dump_json({"installed": False}))
    elif cmd == "diagnose":
        path = transcript_path()
        result = context()
        print(dump_json({"sessionId": session_id() or None, "transcriptPath": path or None,
                         "result": result, "code": result["code"], "ccVersion": None,
                         "codexVersion": _last(records(path), "session_meta").get("cli_version")}))
    else:
        raise SystemExit(f"unsupported Codex runtime verb: {cmd}")
