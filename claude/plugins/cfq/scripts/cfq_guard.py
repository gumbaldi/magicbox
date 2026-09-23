#!/usr/bin/env python3
# Usage: cfq_guard.py pretooluse   (reads a PreToolUse hook payload as JSON on stdin)
"""PreToolUse guard: denies shell mutations and `done/` writes under `<repo>/.claude/cfq/`.

The incident this exists for: `rm -rf` on a batch's `done/` directory, issued from inside the
batch directory while cleaning up after a `mv` typo. `.claude/cfq` is git-excluded, so that delete
had no commit, no reflog, no recovery. Phases 01-05 gave every legitimate mutation of the queue a
deterministic `bin/cfq` subcommand; this guard makes the improvised shell path that caused the
incident impossible instead of merely discouraged.

Paths are resolved against the payload's `cwd`, not matched as a literal string -- the incident's
own command (`rm -rf done/` from inside the batch dir) would slip past a literal `.claude/cfq`
match.

Fail-open by design. An exception anywhere in here allows the call and writes one diagnostic line
to stderr instead of denying. A guard that crashes closed would fail every `Bash` call in every
session -- a worse outcome than the risk it manages, now that the deterministic commands from
phases 01-05 are what the skills actually instruct. Do not "fix" this without re-reading
`.batch-context.md`'s Decisions section for batch 019.
"""

import json
import os
import pathlib
import posixpath
import re
import shlex
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import paths as cfq_lib_paths  # noqa: E402

PROG = "cfq_guard.py"

QUEUE_REL = cfq_lib_paths.QUEUE_DIR_REL  # ".claude/cfq"
QUEUE_COMPONENTS = cfq_lib_paths.QUEUE_DIR_COMPONENTS

# argv[0] basenames treated as destructive when resolved into the queue. `sed` only counts with
# `-i` (in place); a plain `sed` read never mutates anything.
DESTRUCTIVE_BASENAMES = {"rm", "rmdir", "mv", "cp", "truncate", "shred", "dd", "ln", "install"}

# Process wrappers whose own argv[0] is never the command actually run -- `check_destructive_call`/
# `check_find` must see the wrapped command, not the wrapper, or `env rm -rf .claude/cfq` slips
# past unchecked.
WRAPPER_BASENAMES = {"env", "sudo", "nice", "nohup", "timeout", "command", "exec", "xargs", "time"}
SHELL_BASENAMES = {"bash", "sh", "zsh", "dash"}
MAX_WRAPPER_RECURSION = 3

NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_WRAPPER_ALTERNATION = "|".join(sorted(WRAPPER_BASENAMES))
# A destructive verb only counts in "command position": at the start of the string, right after
# `;`/`&&`/`||`/`|`/a newline/`(` (the char class matches the last character of any of those
# multi-char operators too), or right after one of `WRAPPER_BASENAMES`. This keeps the fallback
# from denying a verb word that merely appears as a substring elsewhere -- inside a quoted grep
# pattern, a filename, or similar -- the way a naive "appears anywhere" search would.
DESTRUCTIVE_VERB_RE = re.compile(
    r"(?:^|[;&|(\n]\s*|\b(?:" + _WRAPPER_ALTERNATION + r")\b\s+)"
    r"(rm|rmdir|mv|cp|truncate|shred|dd|ln|install|sed)\b"
)
# Where a command segment ends, for the `sed` case below -- must not look past the next separator
# for a trailing `-i` that actually belongs to some later command.
SEGMENT_END_RE = re.compile(r"[;&|(\n]")
# A target starting with `&` right after the `>`/`>>` (e.g. `2>&1`, `>&2`, `>&-`) is a file-
# descriptor duplication, not a path -- it never names a file and must never be resolved as a
# guard target. `&>file`/`&>>file` are real file redirects: there the `&` sits *before* the `>`,
# so the character captured is the filename itself, and the lookahead below still lets them through.
REDIRECT_RE = re.compile(r">>?\s*(?!&)(\S+)")

# `<<WORD`, `<<-WORD`, `<<'WORD'`, `<<"WORD"` -- a heredoc operator on a command line. The
# lookbehind/lookahead exclude `<<<` (a here-string, single-line, no body) from matching as `<<`
# followed by a `<`-prefixed word.
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-)?\s*(?:'([^']*)'|\"([^\"]*)\"|(\S+))")

SUGGEST_PHASE_RECORD = "bin/cfq phase record <batch-dir> <phase-json-file>"
SUGGEST_PHASE_REOPEN = "bin/cfq phase reopen <batch-dir> <phase-slug>"
SUGGEST_TRASH_PUT = "bin/cfq trash put <repo-root> <path>"
SUGGEST_BATCH_READY = "bin/cfq batch ready <batch-dir>"
SUGGEST_PROBE_CLEANUP = "bin/cfq layout probe-cleanup <repo-root>"


def touches_queue(resolved_posix_path):
    parts = [p for p in resolved_posix_path.split("/") if p]
    for i in range(len(parts) - 1):
        if (parts[i], parts[i + 1]) == QUEUE_COMPONENTS:
            return True
    return False


def resolve(cwd, arg):
    if posixpath.isabs(arg):
        return posixpath.normpath(arg)
    return posixpath.normpath(posixpath.join(cwd or "/", arg))


def suggestion_for(resolved_path, *, is_mv=False, mv_dest_in_done=False, mv_source_in_done=False):
    basename = posixpath.basename(resolved_path)
    if is_mv and mv_dest_in_done:
        return SUGGEST_PHASE_RECORD
    if is_mv and mv_source_in_done:
        return SUGGEST_PHASE_REOPEN
    if basename == ".planning":
        return SUGGEST_BATCH_READY
    if basename == ".writeprobe":
        return SUGGEST_PROBE_CLEANUP
    return SUGGEST_TRASH_PUT


def build_reason(resolved_path, suggestion):
    return (
        f"cfq guard: denied a direct mutation of '{resolved_path}' under {QUEUE_REL}. "
        f"{QUEUE_REL} is git-excluded, so this would be unrecoverable -- no commit, no reflog, "
        f"no restore. Use `{suggestion}` instead."
    )


def path_in_done(resolved_path):
    """`.../impl/<batch>/done/**` or `.../impl/done/<batch>/**`, anchored under the queue --
    including the `done` directory itself, not only entries inside it (a plain `rm -rf done`
    from inside a batch directory is the incident this guard exists for)."""
    parts = [p for p in resolved_path.replace("\\", "/").split("/") if p]
    for i in range(len(parts) - 1):
        if (parts[i], parts[i + 1]) == QUEUE_COMPONENTS:
            rest = parts[i + 2:]
            if rest[:1] == ["impl"] and "done" in rest[1:]:
                return True
    return False


def split_simple_commands(command):
    """Splits on `;`, `&&`, `||`, `|` and newlines, respecting quotes. Raises ValueError on an
    unbalanced quote so the caller can fall back to a substring check.

    Inside a double-quoted span a backslash escapes the next character (`\\"`, `\\\\`, `\\$`,
    `` \\` ``) rather than being taken literally -- matching POSIX and `shlex.split()`, which
    parses the resulting per-segment argv further down and already gets this right. Inside single
    quotes nothing is escaped, POSIX again: an apostrophe can only be closed by another apostrophe.
    """
    parts = []
    buf = []
    i = 0
    n = len(command)
    quote = None
    while i < n:
        c = command[i]
        if quote == '"':
            if c == "\\" and i + 1 < n and command[i + 1] in ('"', "\\", "$", "`"):
                buf.append(c)
                buf.append(command[i + 1])
                i += 2
                continue
            buf.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if quote == "'":
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
            i += 2
            continue
        if c == "\n" or c == ";":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        if c in ("|", "&") and i + 1 < n and command[i + 1] == c:
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        if c == "|":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if quote is not None:
        raise ValueError("unbalanced quote")
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def strip_heredocs(command):
    """Removes heredoc body lines (the lines between a `<<WORD`/`<<-WORD`/`<<'WORD'`/`<<"WORD"`
    operator and the line that repeats `WORD`) from `command` before it is handed to
    `split_simple_commands()`. A heredoc body is data, not a command -- a note body written this
    way (`bin/cfq note plan ... - <<'EOF'`) commonly contains apostrophes, `.claude/cfq` paths, and
    words like `rm`/`sed`, none of which are ever meant to be parsed as shell commands. The command
    line carrying the `<<` operator itself (including any `>`/`>>` redirect on it) is kept and
    still checked normally."""
    lines = command.split("\n")
    result = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        result.append(line)
        i += 1
        for m in HEREDOC_RE.finditer(line):
            word = m.group(2)
            if word is None:
                word = m.group(3)
            if word is None:
                word = m.group(4)
            strip_leading_tabs = m.group(1) == "-"
            while i < n:
                candidate = lines[i]
                comparable = candidate.lstrip("\t") if strip_leading_tabs else candidate
                i += 1
                if comparable == word:
                    break
    return "\n".join(result)


def check_find(argv, cwd):
    if not argv or os.path.basename(argv[0]) != "find":
        return None
    has_delete = "-delete" in argv
    has_exec_rm = False
    if "-exec" in argv:
        idx = argv.index("-exec")
        if idx + 1 < len(argv) and os.path.basename(argv[idx + 1]).startswith("rm"):
            has_exec_rm = True
    if not (has_delete or has_exec_rm):
        return None
    root = "."
    for a in argv[1:]:
        if not a.startswith("-"):
            root = a
            break
    resolved = resolve(cwd, root)
    return resolved if touches_queue(resolved) else None


def check_redirect(simple_command, cwd):
    for target in REDIRECT_RE.findall(simple_command):
        resolved = resolve(cwd, target)
        if touches_queue(resolved):
            return resolved
    return None


def check_destructive_call(argv, cwd):
    if not argv:
        return None
    base = os.path.basename(argv[0])
    is_destructive = base in DESTRUCTIVE_BASENAMES
    if base == "sed":
        is_destructive = any(a == "-i" or a.startswith("-i") for a in argv[1:])
    if not is_destructive:
        return None

    targets = [resolve(cwd, a) for a in argv[1:] if not a.startswith("-")]
    hits = [t for t in targets if touches_queue(t)]
    if not hits:
        return None

    if base == "mv" and len(targets) >= 2:
        source, dest = targets[0], targets[-1]
        return suggestion_for(
            dest if touches_queue(dest) else source,
            is_mv=True,
            mv_dest_in_done=path_in_done(dest),
            mv_source_in_done=path_in_done(source) and not path_in_done(dest),
        ), (dest if touches_queue(dest) else source)

    return suggestion_for(hits[0]), hits[0]


def substring_fallback(command):
    normalized = command.replace("\\", "/")
    if QUEUE_REL not in normalized:
        return None
    for m in DESTRUCTIVE_VERB_RE.finditer(normalized):
        verb = m.group(1)
        if verb == "sed":
            # `sed` only counts with an `-i` flag, same as `check_destructive_call` -- a plain
            # `sed -n`/`sed -e` read never mutates anything. Only look within this one command
            # segment, not past the next separator.
            end_match = SEGMENT_END_RE.search(normalized, m.end())
            segment_end = end_match.start() if end_match else len(normalized)
            segment = normalized[m.end():segment_end]
            if not re.search(r"(?:^|\s)-i\S*", segment):
                continue
        return build_reason(QUEUE_REL, SUGGEST_TRASH_PUT)
    return None


def unwrap_process_wrappers(argv):
    """Strips a chain of `env`/`sudo`/`nice`/`nohup`/`timeout`/`command`/`exec`/`xargs`/`time` off
    the front of argv, so the guard inspects the command actually run rather than the wrapper
    launching it -- `env rm -rf .claude/cfq` and `sudo rm -r .claude/cfq` must be denied exactly
    like a bare `rm`."""
    argv = list(argv)
    while argv and os.path.basename(argv[0]) in WRAPPER_BASENAMES:
        base = os.path.basename(argv[0])
        argv = argv[1:]
        while argv and argv[0].startswith("-"):
            argv = argv[1:]
        if base == "env":
            while argv and ENV_ASSIGN_RE.match(argv[0]):
                argv = argv[1:]
        if base in ("timeout", "nice") and argv and NUMERIC_RE.match(argv[0]):
            argv = argv[1:]
    return argv


def check_bash(command, cwd, depth=0):
    stripped = strip_heredocs(command)
    try:
        simple_commands = split_simple_commands(stripped)
    except ValueError:
        return substring_fallback(stripped)

    effective_cwd = cwd or "/"
    for sc in simple_commands:
        redirect_hit = check_redirect(sc, effective_cwd)
        if redirect_hit:
            return build_reason(redirect_hit, suggestion_for(redirect_hit))

        try:
            argv = shlex.split(sc)
        except ValueError:
            fallback = substring_fallback(sc)
            if fallback:
                return fallback
            continue

        if not argv:
            continue

        if os.path.basename(argv[0]) == "cd" and len(argv) > 1:
            effective_cwd = resolve(effective_cwd, argv[1])
            continue

        argv = unwrap_process_wrappers(argv)
        if not argv:
            continue

        if os.path.basename(argv[0]) in SHELL_BASENAMES and "-c" in argv \
                and depth < MAX_WRAPPER_RECURSION:
            idx = argv.index("-c")
            if idx + 1 < len(argv):
                inner_hit = check_bash(argv[idx + 1], effective_cwd, depth=depth + 1)
                if inner_hit:
                    return inner_hit
                continue

        find_hit = check_find(argv, effective_cwd)
        if find_hit:
            return build_reason(find_hit, SUGGEST_TRASH_PUT)

        result = check_destructive_call(argv, effective_cwd)
        if result:
            suggestion, hit = result
            return build_reason(hit, suggestion)

    return None


def check_write(file_path):
    if not file_path:
        return None
    if path_in_done(file_path):
        # A file only belongs in done/ via the phase-record transaction (the move + ledger
        # entry); a raw Write/Edit landing there directly is never the sanctioned path in
        # either direction, so phase record -- not reopen -- is the correct pointer.
        return build_reason(file_path.replace("\\", "/"), SUGGEST_PHASE_RECORD)
    return None


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def cmd_pretooluse(_args):
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # fail-open: an unparseable payload must not brick every Bash call
        print(f"{PROG}: could not parse hook payload, allowing call: {exc}", file=sys.stderr)
        return

    try:
        tool_name = payload.get("tool_name", "")
        cwd = payload.get("cwd") or "/"
        tool_input = payload.get("tool_input") or {}

        reason = None
        if tool_name == "Bash":
            reason = check_bash(tool_input.get("command", ""), cwd)
        elif tool_name in ("Write", "Edit"):
            reason = check_write(tool_input.get("file_path", ""))

        if reason:
            deny(reason)
    except Exception as exc:  # fail-open, see module docstring
        print(f"{PROG}: internal error, allowing call: {exc}", file=sys.stderr)


def main(argv):
    if argv[:1] != ["pretooluse"]:
        print(f"usage: {PROG} pretooluse", file=sys.stderr)
        sys.exit(1)
    cmd_pretooluse(argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
