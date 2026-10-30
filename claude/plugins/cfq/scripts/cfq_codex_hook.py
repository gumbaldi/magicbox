"""Codex hook: guard the queue and bind CFQ subprocesses to this session."""

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone

from cfq_guard import check_bash, check_write, deny


CFQ_COMMAND = re.compile(r"(?:^|\s|[;&|])(?:\S*/)?bin/cfq(?:\s|$)")
PATCH_TARGET = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File:|Move to:) (.+)$", re.MULTILINE)


def pretooluse(payload):
    tool = payload.get("tool_name")
    args = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or "/"
    command = args.get("command", "")
    if tool == "Bash":
        reason = check_bash(command, cwd)
        if reason:
            deny(reason)
            return
        if CFQ_COMMAND.search(command):
            sid = payload.get("session_id") or ""
            transcript = payload.get("transcript_path") or ""
            model = payload.get("model") or ""
            assignments = " ".join(
                f"{key}={shlex.quote(value)}" for key, value in (
                    ("CFQ_HARNESS", "codex"), ("CFQ_SESSION_ID", sid),
                    ("CFQ_TRANSCRIPT_PATH", transcript), ("CFQ_MODEL", model)
                )
            )
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                              "permissionDecision": "allow",
                              "updatedInput": {"command": f"export {assignments}; {command}"}}}))
    elif tool == "apply_patch":
        for raw in PATCH_TARGET.findall(command):
            target = pathlib.Path(raw)
            if not target.is_absolute():
                target = pathlib.Path(cwd) / target
            target = target.resolve()
            reason = check_write(str(target))
            if reason:
                deny(reason)
                return


def subagent_stop(payload):
    sid = payload.get("session_id") or ""
    aid = payload.get("agent_id") or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or not re.fullmatch(r"[A-Za-z0-9_-]+", aid):
        print("{}")
        return
    cwd = payload.get("cwd") or "."
    root = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if root.returncode != 0:
        print("{}")
        return
    queue = pathlib.Path(root.stdout.strip()) / ".claude" / "cfq"
    try:
        lock = json.loads((queue / ".lock").read_text())
    except (OSError, ValueError):
        lock = {}
    implementation = lock.get("session_id") == sid and lock.get("harness") == "codex"
    planning = (queue / ".codex-planning" / sid).is_file()
    if not implementation and not planning:
        print("{}")
        return
    transcript = payload.get("agent_transcript_path") or ""
    if not pathlib.Path(transcript).is_file():
        print("{}")
        return
    target_dir = queue / ".codex-agents" / sid
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{aid}.json"
    target.write_text(json.dumps({
        "id": aid, "type": payload.get("agent_type") or "unknown",
        "transcript": transcript, "turn_id": payload.get("turn_id") or "",
        "stopped": datetime.now(timezone.utc).isoformat(),
    }) + "\n")
    if implementation and payload.get("agent_type") in ("worker", "cfq-phase-worker"):
        batch = lock.get("batch") or ""
        batch_dir = queue / "impl" / batch
        if batch_dir.is_dir():
            from cfq_lib.proc import cfq_argv
            env = os.environ.copy()
            env.update({"CFQ_HARNESS": "codex", "CFQ_SESSION_ID": sid,
                        "CFQ_TRANSCRIPT_PATH": payload.get("transcript_path") or "",
                        "CFQ_MODEL": payload.get("model") or ""})
            subprocess.run(cfq_argv("telemetry", "refresh", str(batch_dir)),
                           env=env, capture_output=True, text=True)
    print("{}")


def main(argv):
    if argv not in (["pretooluse"], ["subagent-stop"]):
        raise SystemExit("usage: cfq_codex_hook.py pretooluse|subagent-stop")
    try:
        payload = json.load(sys.stdin)
        if argv[0] == "pretooluse":
            pretooluse(payload)
        else:
            subagent_stop(payload)
    except (ValueError, TypeError) as exc:
        print(f"cfq codex hook: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
