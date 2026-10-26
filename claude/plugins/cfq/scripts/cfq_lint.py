#!/usr/bin/env python3
# Usage: cfq_lint.py <batch-dir>
"""Lints a parked batch of phase plans before pfq hands it off. Reports, never repairs, never
aborts on soft findings (`depends`, `changes-steps` and `summary-missing` are warn-only and never
affect the exit code).

Three rules resolve a file that no phase has created yet, against the plan itself: a bare absolute
path that is not on disk is accepted while a pending phase creates it (an earlier phase of the same
batch, or any phase of a `.dependsOn` batch that is still queued); a second phase that marks the
same path `(new)` is a `duplicate-new` finding; and `stale-new` is a `warn:` line, not a finding,
for the next pending phase of a batch that has left planning (no `.planning` file).

Ported from cfq-lint.sh -- a port, not a redesign: every finding string, the `warn:` prefix, the
exit-code rule and the `## Size` degradation are carried over verbatim.
"""

import argparse
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_brief import _repo_root_from_batch_dir, has_numbered_steps, parse_phase_body  # noqa: E402
from cfq_lib import phase_state, proc as cfq_proc, queue as cfq_queue  # noqa: E402

PROG = "cfq_lint.py"

BULLET_RE = re.compile(r"^- `([^`]*)`")


def has_heading(text, heading):
    pattern = re.compile(rf"^## {re.escape(heading)}(?:\s|$)", re.MULTILINE)
    return bool(pattern.search(text))


def extract_section(text, heading):
    """Mirrors the shell version's awk state machine, not a sed range: stops before the next
    "## " heading (or at end-of-file), excluding both the opening heading line and the closing
    one -- a sed range would print through EOF when the heading is the file's last one."""
    pattern_start = re.compile(rf"^## {re.escape(heading)}(?:\s|$)")
    out = []
    started = False
    for line in text.split("\n"):
        if not started:
            if pattern_start.match(line):
                started = True
            continue
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def extract_files_section(text):
    """Mirrors `sed -n '/^## Affected Files/,/^## /p'`: inclusive of both the opening heading and
    the closing one (or EOF) -- fine here since only the `- \\`...\\`` bullet lines are used."""
    out = []
    started = False
    for line in text.split("\n"):
        if not started:
            if line.startswith("## Affected Files"):
                started = True
                out.append(line)
            continue
        out.append(line)
        if line.startswith("## "):
            break
    return "\n".join(out)


def phase_num(name):
    return name[:2] if len(name) >= 3 and name[2] == "-" and name[:2].isdigit() else None


def affected_entries(text):
    """The `(path, is_new)` pairs of a phase text's `## Affected Files` bullets."""
    out = []
    for line in extract_files_section(text).split("\n"):
        if not line.startswith("- `"):
            continue
        m = BULLET_RE.match(line)
        path = m.group(1) if m else ""
        if path:
            out.append((path, "(new)" in line))
    return out


def _creators_of(batch_dir, label_prefix, own, creators):
    try:
        recs = phase_state.phases(batch_dir)
    except phase_state.PhaseStateError:
        return
    for rec in recs:
        if rec["path"] is None:
            continue
        for path, is_new in affected_entries(rec["path"].read_text()):
            if is_new and path.startswith("/"):
                creators.setdefault(path, []).append({
                    "label": label_prefix + rec["slug"], "slug": rec["slug"],
                    "status": rec["status"], "own": own,
                })


def collect_creators(d):
    """absolute path -> creators (`label`, `slug`, `status`, `own`): the phases of `d` itself,
    then those of each `.dependsOn` batch lying next to `d` (not under `done/`)."""
    creators = {}
    _creators_of(d, "", True, creators)
    for dep in cfq_queue.read_depends(d):
        dep_dir = d.parent / dep
        if dep_dir.is_dir():
            _creators_of(dep_dir, dep + "/", False, creators)
    return creators


def _qualifies(creator, prefix):
    if creator["status"] not in phase_state.PENDING:
        return False
    return not creator["own"] or creator["slug"][:2] < prefix


def lint_open_file(f, findings, warn_findings, impl_models=None, creators=None,
                   relaxed=False, next_pending=None):
    """`impl_models` is the repo's `implModels` list, or None when it could not be read (the
    caller has warned once already, so `## Model` goes unchecked). `creators` is
    collect_creators()'s map; `relaxed` is true for a batch without `.planning` and
    `next_pending` the slug of its next pending phase (stale-new is warn-only for that one)."""
    creators = creators or {}
    name = f.name
    text = f.read_text()

    if not any(line.startswith("# ") for line in text.split("\n")):
        findings.append(f"{name}: title: missing # heading")

    for heading in ("Context", "Affected Files", "Changes", "Verification", "Size"):
        if not has_heading(text, heading):
            findings.append(f"{name}: sections: missing {heading} heading")

    if has_heading(text, "Verification"):
        verification = extract_section(text, "Verification")
        lines = verification.split("\n")
        has_cmd = any(line.startswith("```") or re.search(r"`[^`]+`", line) for line in lines)
        if not has_cmd:
            findings.append(f"{name}: verification-cmd: no runnable command in Verification")
        if not re.search(r"expect|PASS|exit 0|prints|must", verification, re.IGNORECASE):
            findings.append(f"{name}: verification-expect: no expected result stated")

    if has_heading(text, "Model") and impl_models is not None:
        model = parse_phase_body(text)["model"]
        if model is None:
            findings.append(f"{name}: model: ## Model heading has no value")
        elif model not in [m.lower() for m in impl_models]:
            findings.append(
                f"{name}: model: '{model}' is not in implModels ({', '.join(impl_models)})"
            )

    if has_heading(text, "Changes"):
        if not re.search(r"\S", extract_section(text, "Changes")):
            findings.append(f"{name}: changes-empty: Changes section is empty")
        elif not has_numbered_steps(text):
            warn_findings.append(f"warn: {name}: changes-steps: Changes has no numbered top-level step")

    if not has_heading(text, "Summary"):
        warn_findings.append(f"warn: {name}: summary-missing: no ## Summary section")

    if has_heading(text, "Affected Files"):
        files_section = extract_files_section(text)
        if not any(line.startswith("- `") for line in files_section.split("\n")):
            findings.append(f"{name}: files-empty: Affected Files has no entries")

        prefix = f.stem[:2]
        for path, is_new in affected_entries(text):
            if not path.startswith("/"):
                findings.append(f"{name}: abspath: {path} is not absolute")
                continue
            made_by = creators.get(path, [])
            qualifying = [c for c in made_by if _qualifies(c, prefix)]
            if is_new:
                if qualifying:
                    findings.append(
                        f"{name}: duplicate-new: {path} is created by {qualifying[0]['label']}; "
                        "list it without (new)")
                elif os.path.exists(path):
                    if relaxed and f.stem == next_pending:
                        warn_findings.append(f"warn: {name}: stale-new: {path} already exists")
                    else:
                        findings.append(f"{name}: stale-new: {path} already exists")
            elif not os.path.exists(path) and not qualifying:
                msg = f"{name}: missing: {path} does not exist"
                if made_by:
                    first = made_by[0]
                    later = first["own"] and first["status"] in phase_state.PENDING
                    reason = "runs later" if later else f"is {first['status']}"
                    msg += f" (created by {first['label']}, which {reason})"
                findings.append(msg)


def check_numbering(all_files, batch_name, findings):
    nums = sorted(phase_num(f.name) for f in all_files if phase_num(f.name))
    seen = {}
    for num in nums:
        seen[num] = seen.get(num, 0) + 1
    dups = sorted(num for num, count in seen.items() if count > 1)
    if dups:
        findings.append(f"{batch_name}: numbering: duplicate phase number(s): {' '.join(dups)}")

    expected = 1
    for cur in sorted(seen):
        want = f"{expected:02d}"
        if cur != want:
            findings.append(f"{batch_name}: numbering: gap before {cur}, expected {want}")
            break
        expected += 1


def check_status(d, batch_name, findings):
    """status.json against the plan files: blocking findings, never `warn:`. Returns the
    `{slug: status}` map it read (empty when the file is missing or unreadable), which
    pending_files() uses to decide what to lint."""
    if not phase_state.exists(d):
        findings.append(f"{batch_name}: status: missing status.json")
        return {}
    try:
        entries = {slug: e["status"] for slug, e in phase_state.load(d)["phases"].items()}
        mismatches = phase_state.mismatches(d)
    except phase_state.PhaseStateError:
        findings.append(f"{batch_name}: status: status.json is not valid JSON")
        return {}
    for m in mismatches:
        slug = m["slug"]
        if m["kind"] == "no_entry":
            findings.append(f"{batch_name}: status: {slug} has no status entry")
        elif m["kind"] == "no_file":
            findings.append(f"{batch_name}: status: {slug} entry has no file")
        else:
            parent = pathlib.Path(m["path"]).parent
            where = "the batch root" if parent == d else f"{parent.name}/"
            findings.append(f"{batch_name}: status: {slug} is {m['status']} but lies in {where}")
    return entries


def pending_files(d, entries):
    """The plan files lint checks for headings: those of `open`/`error` phases. A file without
    an entry (or any file when status.json is unreadable) counts by where it lies, the same
    adoption rule as phase_state.sync_files()."""
    out = []
    for slug, path in sorted(phase_state.phase_files(d).items()):
        status = entries.get(slug)
        if status is None:
            if path.parent == d:
                out.append(path)
        elif status in phase_state.PENDING:
            out.append(path)
    return out


def check_priority(d, batch_name, findings):
    priority_file = d / ".priority"
    if priority_file.is_file():
        p = priority_file.read_text().strip()
        if p != "high":
            findings.append(f"{batch_name}: priority: .priority is '{p}', want high or no file")


def check_batch_context(d, batch_name, findings):
    ctx_file = d / ".batch-context.md"
    if not ctx_file.is_file():
        findings.append(f"{batch_name}: batch-context: missing .batch-context.md")
        return
    ctx_text = ctx_file.read_text()
    if not has_heading(ctx_text, "Goal"):
        findings.append(f"{batch_name}: batch-context: .batch-context.md missing ## Goal heading")
        return
    if not re.search(r"\S", extract_section(ctx_text, "Goal")):
        findings.append(f"{batch_name}: batch-context: ## Goal section is empty")


def check_depends(d, batch_name, warn_findings):
    repo_qdir = d.parent
    for dep in cfq_queue.read_depends(d):
        if not (repo_qdir / dep).is_dir() and not (repo_qdir / "done" / dep).is_dir():
            warn_findings.append(f"warn: {batch_name}: depends: {dep} does not exist")


def read_impl_models(d):
    """The repo's `implModels` list for the batch at `d`, or None when it cannot be read."""
    repo = _repo_root_from_batch_dir(d)
    if repo is None:
        return None
    proc = cfq_proc.cfq_run("settings", "list", "--repo", str(repo))
    if proc.returncode != 0:
        return None
    try:
        models = json.loads(proc.stdout)["implModels"]
    except (ValueError, KeyError, TypeError):
        return None
    return models if isinstance(models, list) else None


def cmd_lint(args):
    d = pathlib.Path(str(args.batch_dir).rstrip("/"))
    if not d.is_dir():
        print(f"{PROG}: no such batch directory: {d}", file=sys.stderr)
        sys.exit(1)
    batch_name = d.name

    all_files = sorted(phase_state.phase_files(d).values())
    n = len(all_files)

    findings = []
    warn_findings = []

    entries = check_status(d, batch_name, findings)
    files = pending_files(d, entries)
    impl_models = None
    if any(has_heading(f.read_text(), "Model") for f in files):
        impl_models = read_impl_models(d)
        if impl_models is None:
            warn_findings.append("warn: model: implModels unavailable, ## Model not checked")
    creators = collect_creators(d)
    relaxed = not (d / ".planning").exists()
    try:
        next_pending = phase_state.next_pending(d)
    except phase_state.PhaseStateError:
        next_pending = None
    for f in files:
        lint_open_file(f, findings, warn_findings, impl_models, creators, relaxed, next_pending)

    check_numbering(all_files, batch_name, findings)
    check_priority(d, batch_name, findings)
    check_batch_context(d, batch_name, findings)
    check_depends(d, batch_name, warn_findings)

    for line in findings:
        print(line)
    for line in warn_findings:
        print(line)

    if not findings:
        print(f"OK {n} phases")
        sys.exit(0)
    sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    parser.add_argument("batch_dir")
    parser.set_defaults(func=cmd_lint)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
