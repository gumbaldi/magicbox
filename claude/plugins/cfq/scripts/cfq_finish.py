#!/usr/bin/env python3
# Usage: cfq_finish.py <repo-root> <batch-dir> <branch>
"""Runs the batch-done sequence (move, register, language check, maintenance check, security
diff, changelog, telemetry sync) in a fixed order and prints one JSON object. The lock release is
guaranteed via a `finally` -- a mid-sequence failure must never leave the repo locked. The
`statusLines` array also carries a `Branch` line (the batch branch, the branch it was cut from and
its push state) and the object a `branch` field with those values (`push` is `{state, ahead,
behind}`, `null` without a branch).

The language checks compare against the batch's own base branch (the changelog block's `base:`,
`origin` first, then local), so a batch cut from an unmerged predecessor is checked only for its
own changes; the default branch is the fallback when no base is recorded or the base branch no
longer exists.

Ported from cfq-finish.sh -- a port, not a redesign: the nine-call order, the per-call failure
handling (each recorded in `errors`, none aborts the sequence) and every output field are the
invariant this file preserves. The `try/finally` below replaces the shell version's `trap ... EXIT`
one-for-one.
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cfq_changelog  # noqa: E402
from cfq_lib import paths, phase_state, portal_hook, render, text as cfq_text  # noqa: E402
from cfq_lib.proc import (  # noqa: E402
    capture, cfq_argv, cfq_run, cfq_run_merged, default_branch, git, settings_get,
)

PROG = "cfq_finish.py"


def batch_base(repo_root, batch_name):
    """The `base:` value of the batch's changelog block, or `""` when `changelogFile` is empty,
    the file is missing, no block matches or the block has no `base:`."""
    changelog_file = cfq_changelog.changelog_file(repo_root)
    if not changelog_file or not pathlib.Path(changelog_file).is_file():
        return ""
    start = cfq_changelog.find_block_start(changelog_file, "  batch:", batch_name)
    if start is None:
        return ""
    lines = cfq_changelog.read_lines(changelog_file)
    return cfq_changelog.block_field(cfq_changelog.block_text(lines, start), "  base:") or ""


def lang_base_ref(repo_root, base, default_ref):
    """The reference the language checks compare against: `origin/<base>` when that branch exists
    on `origin`, else `<base>` when it exists locally, else `default_ref` (also for an empty
    `base`). The default branch itself keeps `default_ref`. No fetch -- the refs on disk decide."""
    if base and default_ref not in (f"refs/remotes/origin/{base}", f"refs/heads/{base}"):
        for ref, name in ((f"refs/remotes/origin/{base}", f"origin/{base}"),
                          (f"refs/heads/{base}", base)):
            if git(repo_root, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
                return name
    return default_ref


def load_json_or(text, default):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


# ---- status-line rendering (batch 035 phase 08) --------------------------------------------
# Each line below renders exactly the field `references/ifq-batch-end.md`'s **Batch-Done Report
# Fields** section already names for it -- the aggregator resolves the structural half
# deterministically; a source that needs judgment (the `lang.prose` sample) stays the model's own
# addition on top, documented there rather than re-derived here.

def language_line(lang_json):
    issues = lang_json.get("issues", 0)
    if issues == 0:
        return cfq_text.status_entry("Language", "done", "no issues")
    detail = f"{issues} issues"
    if (lang_json.get("prose") or {}).get("truncated"):
        detail += " · sampled"
    return cfq_text.status_entry("Language", "warn", detail, sub=lang_json.get("findings") or [])


def maintenance_line(maintenance):
    parts = maintenance.split()
    status = parts[0] if parts else ""
    n = parts[1] if len(parts) > 1 else None
    if status == "OFF":
        return cfq_text.status_entry("Maintenance", "skip", "off")
    if status == "NOT_DUE":
        return cfq_text.status_entry("Maintenance", "skip", f"not due ({n} commits)")
    if status == "DUE":
        return cfq_text.status_entry("Maintenance", "warn", f"due ({n} commits) · run /pfq")
    return cfq_text.status_entry("Maintenance", "warn", maintenance or "unknown")


def security_diff_line(security):
    planning = security.get("planning") or {}
    now = security.get("now") or {}
    if not planning and not now:
        return None  # no planning snapshot to diff against -- skip without comment
    new = security.get("new") or {}
    if not new:
        return cfq_text.status_entry("Security Diff", "done", "no new findings")
    detail = ", ".join(f"{k}: +{v}" for k, v in new.items())
    return cfq_text.status_entry("Security Diff", "warn", detail)


def changelog_line(changelog):
    if changelog == "changelogFile empty":
        return cfq_text.status_entry("Changelog", "skip", "changelogFile empty")
    if changelog == "error":
        return cfq_text.status_entry("Changelog", "fail", "error")
    return cfq_text.status_entry("Changelog", "done", changelog)


def push_state(repo_root, branch):
    """The batch branch's push state, read from `refs/remotes/origin/<branch>` with no fetch (so
    "as of the last push or fetch of this clone"): `{"state", "ahead", "behind"}` where `state` is
    `not-pushed` (no remote-tracking ref), `pushed`, `ahead`, `behind`, `diverged` or `unknown`.
    Never raises."""
    unknown = {"state": "unknown", "ahead": 0, "behind": 0}
    try:
        ref = f"refs/remotes/origin/{branch}"
        if git(repo_root, "rev-parse", "--verify", "--quiet", ref).returncode != 0:
            return {"state": "not-pushed", "ahead": 0, "behind": 0}
        proc = git(repo_root, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
        if proc.returncode != 0:
            return unknown
        ahead, behind = (int(n) for n in proc.stdout.split())
    except (OSError, ValueError):
        return unknown
    if ahead and behind:
        state = "diverged"
    elif ahead:
        state = "ahead"
    elif behind:
        state = "behind"
    else:
        state = "pushed"
    return {"state": state, "ahead": ahead, "behind": behind}


def push_suffix(push):
    state, ahead, behind = push["state"], push["ahead"], push["behind"]
    return {
        "not-pushed": "not pushed",
        "pushed": "pushed",
        "ahead": f"ahead {ahead} · not pushed",
        "behind": f"behind {behind}",
        "diverged": f"diverged (ahead {ahead}, behind {behind})",
    }.get(state, "push state unknown")


def branch_line(branch, base, push=None):
    """The `Branch` line: the batch's branch, when the changelog records one the branch it was cut
    from and, when `push` (see `push_state`) is given, the push state. An empty or detached
    (`HEAD`) branch argument renders `➖ no branch`."""
    if not branch or branch == "HEAD":
        return cfq_text.status_entry("Branch", "skip", "no branch")
    detail = f"{branch} · from {base}" if base else branch
    if push is None:
        return cfq_text.status_entry("Branch", "done", detail)
    icon = "done" if push["state"] == "pushed" else "warn"
    return cfq_text.status_entry("Branch", icon, f"{detail} · {push_suffix(push)}")


def skipped_line(skipped, written, failed):
    """The `Skipped` line: what became of the batch's skipped phases. `skipped` is the number of
    skipped phases, `written` the number of inbox entries that exist for them, `failed` whether
    anything went wrong writing them (the error text itself attaches as a sub line)."""
    detail = f"{skipped} phases · {written} inbox entries"
    if failed:
        return cfq_text.status_entry("Skipped", "warn", detail)
    if not skipped:
        return cfq_text.status_entry("Skipped", "skip", "none")
    return cfq_text.status_entry("Skipped", "done", detail)


def telemetry_line(telemetry, ok, sync_repo=""):
    """The `Telemetry` line: the sync's own output when there is one, else why there was none."""
    if not ok or telemetry:
        return cfq_text.status_entry("Telemetry", "done" if ok else "warn", telemetry)
    if not sync_repo:
        return cfq_text.status_entry("Telemetry", "skip", "sync off · telemetrySyncRepo is empty")
    return cfq_text.status_entry("Telemetry", "done", f"nothing to sync · target {sync_repo}")


def report_line(html_report, repo_root, batch_name):
    """The `Report` status line -- the portal sync itself already ran as this same `finish` call's
    own side effect (`cfq_lib/portal_hook.py`, fired unconditionally below), so this only names
    where it landed: the batch's own route inside the (already-synced) portal, or `➖ off` when
    `htmlReport` turns the automatic sync off."""
    if html_report != "true":
        return cfq_text.status_entry("Report", "skip", "off · bin/cfq portal sync renders on demand")
    return cfq_text.status_entry("Report", "done", paths.portal_batch_url(repo_root, batch_name))


def lock_line(lock):
    return cfq_text.status_entry("Lock", "done", lock)


STEP_LABEL = {
    "lang": "Language", "maintenance": "Maintenance", "security": "Security Diff",
    "changelog": "Changelog", "branch": "Branch", "telemetry": "Telemetry", "skipped": "Skipped",
}


def attach_errors(status_lines, errs):
    """Each `.errors` entry (`"<step>: <message>"`) attaches as a `sub` line under its matching
    entry above rather than becoming a new `statusLines` entry of its own -- the sequence step
    already has a line, the error is detail on it. A step whose own line was skipped entirely (e.g.
    `security` with no planning snapshot to diff) gets a fresh `⚠️` line created here instead, so a
    genuine failure is never hidden behind an omitted line. A step with no matching label at all
    (e.g. `registry`, which never gets a status line of its own) is left in `errors` only,
    unchanged. Mutates `status_lines` in place, `None` placeholders included -- the caller filters
    those out once every error has been attached."""
    by_label = {line["label"]: line for line in status_lines if line is not None}
    for e in errs:
        step, _, _ = e.partition(":")
        label = STEP_LABEL.get(step.strip())
        if label is None:
            continue
        line = by_label.get(label)
        if line is None:
            line = cfq_text.status_entry(label, "warn", "failed")
            status_lines.append(line)
            by_label[label] = line
        else:
            line["icon"] = "warn" if line["icon"] == "done" else line["icon"]
        line["sub"].append(e)
        line["text"] = "\n".join(
            [cfq_text.status_line(line["icon"], line["label"], line["detail"])]
            + [cfq_text.sub_line(s) for s in line["sub"]]
        )


# ---- inbox entries for skipped phases (batch 051 phase 07) ---------------------------------

def demote_headings(text, by=2):
    """Pushes every Markdown heading outside a fenced code block down `by` levels (capped at 6),
    so a plan's own `# Title` can sit inside the inbox entry's `## Skipped plan` section."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            rest = line[level:]
            if level <= 6 and (not rest or rest[0] in " \t"):
                line = "#" * min(level + by, 6) + rest
        out.append(line)
    return "\n".join(out)


def skipped_entry_body(batch_name, rec, plan_path):
    """The `plan/` inbox entry for one skipped phase: H1 title, `## Finding`, `## Origin` (batch,
    phase, reason, the archived plan file) and `## Skipped plan` (the plan text, headings demoted)."""
    try:
        plan_text = pathlib.Path(plan_path).read_text()
    except OSError:
        plan_text = "(the archived plan file could not be read)\n"
    title = rec["slug"]
    for line in plan_text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip() or title
            break
    return (
        f"# Skipped phase {rec['slug']}: {title}\n\n"
        "## Finding\n\n"
        f"Phase {rec['slug']} was skipped and never implemented when batch {batch_name} finished. "
        "Whether to plan it again is still an open decision.\n\n"
        "## Origin\n\n"
        f"- Batch: {batch_name}\n"
        f"- Phase: {rec['slug']}\n"
        f"- Reason: {rec.get('reason') or 'none given'}\n"
        f"- Plan file: {plan_path}\n\n"
        "## Skipped plan\n\n"
        f"{demote_headings(plan_text)}\n"
    )


def write_skipped_entries(repo_root, batch_dir, add_error):
    """One `plan/` inbox entry per skipped phase that has no `inbox` annotation yet, written
    through `note plan --batch` (so batch 050's notes ledger records it) and annotated back into
    status.json. Returns (skipped slugs, number of phases with an inbox entry); a failure is added
    through `add_error` and never raises."""
    try:
        skipped = [r for r in phase_state.phases(batch_dir) if r["status"] == "skipped"]
    except phase_state.PhaseStateError as exc:
        add_error("skipped", f"{exc.code}: {exc.message}")
        return [], 0
    written = 0
    for rec in skipped:
        if rec.get("inbox"):
            written += 1
            continue
        slug = rec["slug"]
        plan_path = rec["path"] or batch_dir / phase_state.SUBDIR["skipped"] / f"{slug}.md"
        try:
            proc = subprocess.run(
                cfq_argv("note", "plan", str(repo_root), f"skipped-{batch_dir.name}-{slug}", "-",
                         "--batch", batch_dir.name),
                input=skipped_entry_body(batch_dir.name, rec, plan_path),
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                add_error("skipped", f"{slug}: could not write the inbox entry: "
                          f"{(proc.stderr or proc.stdout).strip()}")
                continue
            lines = proc.stdout.strip().splitlines()
            phase_state.annotate(batch_dir, slug, inbox=pathlib.Path(lines[-1]).name)
            written += 1
        except (OSError, IndexError, phase_state.PhaseStateError) as exc:
            add_error("skipped", f"{slug}: could not write the inbox entry: {exc}")
    return [r["slug"] for r in skipped], written


def cmd_finish(args):
    repo_root = args.repo_root
    batch_dir = pathlib.Path(str(args.batch_dir).rstrip("/"))
    branch = args.branch

    errs = []

    def add_error(step, message):
        errs.append(f"{step}: {message}")

    try:
        done_dir = pathlib.Path(paths.impl_done_dir(str(repo_root)))
        done_dir.mkdir(parents=True, exist_ok=True)
        moved = done_dir / batch_dir.name
        if batch_dir.is_dir() and batch_dir != moved:
            shutil.move(str(batch_dir), str(moved))
        batch_dir = moved

        if cfq_run("registry", "add", str(repo_root)).returncode != 0:
            add_error("registry", "cfq_registry.py add failed")

        errs_before = len(errs)
        skipped_slugs, skipped_written = write_skipped_entries(repo_root, batch_dir, add_error)
        skipped_failed = len(errs) > errs_before

        lang_json = {"issues": 0, "findings": []}
        # True: the `origin` refs on disk are used when present; this call does not fetch.
        _, default_ref = default_branch(repo_root, True)
        batch_base_name = batch_base(repo_root, batch_dir.name)
        base_ref = lang_base_ref(repo_root, batch_base_name, default_ref)
        proc = cfq_run_merged("lang", str(repo_root), "--changed", base_ref)
        out = capture(proc)
        if proc.returncode == 0:
            data = load_json_or(out, None)
            if data is not None:
                lang_json = {
                    "issues": len(data.get("missing", [])) + len(data.get("stray", []))
                    + len(data.get("unfiled", [])),
                    "findings": (
                        [f"missing: {m}" for m in data.get("missing", [])]
                        + [f"stray: {m}" for m in data.get("stray", [])]
                        + [f"unfiled: {m}" for m in data.get("unfiled", [])]
                    ),
                }
        else:
            add_error("lang", out)

        prose_proc = cfq_run_merged("lang", "prose", str(repo_root), base_ref)
        prose_out = capture(prose_proc)
        if prose_proc.returncode == 0:
            prose_val = load_json_or(prose_out, None)
            if prose_val is not None:
                lang_json = {**lang_json, "prose": prose_val}
        else:
            add_error("lang", prose_out)

        maintenance = "unknown"
        maint_proc = cfq_run_merged("maintenance", "due", str(repo_root))
        maint_out = capture(maint_proc)
        if maint_proc.returncode == 0:
            maintenance = maint_out
        else:
            add_error("maintenance", maint_out)

        report_path = batch_dir / "report.json"
        existed_before = 0
        if report_path.is_file():
            data = load_json_or(report_path.read_text(), None)
            if data is not None:
                existed_before = len(data.get("security", []))

        planning_json = {}
        now_json = {}
        new_json = {}
        sec_proc = cfq_run_merged("security", str(repo_root))
        sec_now = capture(sec_proc)
        if sec_proc.returncode == 0:
            if cfq_run("report", "security", str(batch_dir), sec_now).returncode == 0:
                data = load_json_or(report_path.read_text(), None) if report_path.is_file() else None
                security_list = data.get("security", []) if data is not None else []
                now_json = (security_list[-1].get("counts") if security_list else {}) or {}
                if existed_before > 0:
                    planning_json = (security_list[0].get("counts") if security_list else {}) or {}
                    for key, n_val in now_json.items():
                        delta = n_val - planning_json.get(key, 0)
                        if delta > 0:
                            new_json[key] = delta
            else:
                add_error("security", "cfq_report.py security failed")
        else:
            add_error("security", sec_now)

        changelog = "changelogFile empty"
        changelog_file = settings_get(repo_root, "changelogFile")
        if changelog_file:
            try:
                phase_counts = phase_state.counts(batch_dir)
            except phase_state.PhaseStateError as exc:
                phase_counts = {"done": 0, "skipped": 0}
                if not skipped_failed:
                    add_error("skipped", f"{exc.code}: {exc.message}")
                    skipped_failed = True
            phases = phase_counts["done"]
            fin_proc = cfq_run_merged("changelog", "finish", str(repo_root), branch, str(batch_dir))
            fin_out = capture(fin_proc)
            if fin_proc.returncode == 0:
                changelog = f"{batch_dir.name} done · {phases} phases"
                if phase_counts["skipped"]:
                    changelog += f" · {phase_counts['skipped']} skipped"
                msg = (
                    f"Mark {branch} batch done in the changelog\n\n"
                    "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
                )
                commit_proc = cfq_run("changelog", "commit", str(repo_root), msg)
                result = capture(commit_proc)
                if commit_proc.returncode != 0:
                    add_error("changelog", f"git commit of {changelog_file} failed: {commit_proc.stderr.strip() or result}")
                elif result in ("committed", "forced"):
                    pushed = (
                        git(repo_root, "push", "-q").returncode == 0
                        or git(repo_root, "push", "-q", "-u", "origin", branch).returncode == 0
                    )
                    if pushed:
                        suffix = "force-added (ignored by repo) · committed" if result == "forced" else "committed"
                        changelog = f"{changelog} · {suffix}"
                    else:
                        add_error("changelog", f"git push of {changelog_file} failed")
            else:
                add_error("changelog", fin_out)
                changelog = "error"

        tel_proc = cfq_run_merged("telemetry", "sync", str(repo_root))
        telemetry = capture(tel_proc)
        if tel_proc.returncode != 0:
            add_error("telemetry", telemetry)

        html_report = capture(cfq_run("settings", "get", "--repo", str(repo_root), "htmlReport"))
        sync_repo = capture(cfq_run("settings", "get", "--repo", str(repo_root), "telemetrySyncRepo"))
        push = push_state(repo_root, branch) if branch and branch != "HEAD" else None
        if report_path.is_file():
            try:
                data = json.loads(report_path.read_text())
                data["finish"] = {
                    "at": render.now_iso(),
                    "lang": {"issues": lang_json["issues"], "findings": lang_json["findings"]},
                    "maintenance": maintenance,
                    "security": {"planning": planning_json, "now": now_json, "new": new_json},
                    "changelog": changelog,
                    "skipped": skipped_slugs,
                    "errors": list(errs),
                }
                render.write_json(str(report_path), data)
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                add_error("report", f"could not persist the finish result: {exc}")
        portal_hook.sync(str(repo_root), batches=[batch_dir.name])

        status_lines = [
            language_line(lang_json),
            maintenance_line(maintenance),
            security_diff_line({"planning": planning_json, "now": now_json, "new": new_json}),
            changelog_line(changelog),
            branch_line(branch, batch_base_name, push),
            skipped_line(len(skipped_slugs), skipped_written, skipped_failed),
            telemetry_line(telemetry, tel_proc.returncode == 0, sync_repo),
            report_line(html_report, str(repo_root), batch_dir.name),
            lock_line("released"),
        ]
        attach_errors(status_lines, errs)

        print(render.dump_json({
            "moved": str(batch_dir), "lang": lang_json, "maintenance": maintenance,
            "security": {"planning": planning_json, "now": now_json, "new": new_json},
            "changelog": changelog, "telemetry": telemetry, "lock": "released", "errors": errs,
            "branch": {
                "name": "" if not branch or branch == "HEAD" else branch, "base": batch_base_name,
                "push": push,
            },
            "statusLines": [line for line in status_lines if line is not None],
        }))
    finally:
        subprocess.run(
            cfq_argv("lock", "release", str(repo_root), "--batch", batch_dir.name),
            capture_output=True, text=True,
        )


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    parser.add_argument("repo_root")
    parser.add_argument("batch_dir")
    parser.add_argument("branch")
    parser.set_defaults(func=cmd_finish)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
