#!/usr/bin/env python3
# Usage: cfq_finish.py <repo-root> <batch-dir> <branch>
"""Runs the batch-done sequence (move, register, language check, maintenance check, security
diff, changelog, telemetry sync) in a fixed order and prints one JSON object. The lock release is
guaranteed via a `finally` -- a mid-sequence failure must never leave the repo locked.

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

from cfq_lib import paths, portal_hook, render, text as cfq_text  # noqa: E402
from cfq_lib.proc import capture, cfq_argv, cfq_run, cfq_run_merged, git, settings_get  # noqa: E402

PROG = "cfq_finish.py"


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


def telemetry_line(telemetry, ok):
    return cfq_text.status_entry("Telemetry", "done" if ok else "warn", telemetry)


def report_line(html_report, repo_root, batch_name):
    """The `Report` status line -- the portal sync itself already ran as this same `finish` call's
    own side effect (`cfq_lib/portal_hook.py`, fired unconditionally below), so this only names
    where it landed: the batch's own route inside the (already-synced) portal, or `➖ off` when
    `htmlReport` turns the automatic sync off."""
    if html_report != "true":
        return cfq_text.status_entry("Report", "skip", "off · /rfq renders on demand")
    return cfq_text.status_entry("Report", "done", paths.portal_batch_url(repo_root, batch_name))


def lock_line(lock):
    return cfq_text.status_entry("Lock", "done", lock)


STEP_LABEL = {
    "lang": "Language", "maintenance": "Maintenance", "security": "Security Diff",
    "changelog": "Changelog", "telemetry": "Telemetry",
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

        lang_json = {"issues": 0, "findings": []}
        proc = cfq_run_merged("lang", str(repo_root), "--changed", "main")
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

        prose_proc = cfq_run_merged("lang", "prose", str(repo_root), "main")
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
            done_phase_dir = batch_dir / "done"
            phases = len(list(done_phase_dir.glob("[0-9][0-9]-*.md"))) if done_phase_dir.is_dir() else 0
            fin_proc = cfq_run_merged("changelog", "finish", str(repo_root), branch, str(batch_dir))
            fin_out = capture(fin_proc)
            if fin_proc.returncode == 0:
                changelog = f"{batch_dir.name} done · {phases} phases"
                status_out = git(repo_root, "status", "--porcelain", "--", changelog_file).stdout
                if status_out.strip():
                    ok = (
                        git(repo_root, "add", changelog_file).returncode == 0
                        and git(
                            repo_root, "commit", "-q",
                            "-m", f"Mark {branch} batch done in the changelog",
                            "-m", "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>",
                        ).returncode == 0
                        and git(repo_root, "push", "-q").returncode == 0
                    )
                    if ok:
                        changelog = f"{changelog} · committed"
                    else:
                        add_error("changelog", f"git commit/push of {changelog_file} failed")
            else:
                add_error("changelog", fin_out)
                changelog = "error"

        tel_proc = cfq_run_merged("telemetry", "sync", str(repo_root))
        telemetry = capture(tel_proc)
        if tel_proc.returncode != 0:
            add_error("telemetry", telemetry)

        html_report = capture(cfq_run("settings", "get", "--repo", str(repo_root), "htmlReport"))
        portal_hook.sync(str(repo_root), batches=[batch_dir.name])

        status_lines = [
            language_line(lang_json),
            maintenance_line(maintenance),
            security_diff_line({"planning": planning_json, "now": now_json, "new": new_json}),
            changelog_line(changelog),
            telemetry_line(telemetry, tel_proc.returncode == 0),
            report_line(html_report, str(repo_root), batch_dir.name),
            lock_line("released"),
        ]
        attach_errors(status_lines, errs)

        print(render.dump_json({
            "moved": str(batch_dir), "lang": lang_json, "maintenance": maintenance,
            "security": {"planning": planning_json, "now": now_json, "new": new_json},
            "changelog": changelog, "telemetry": telemetry, "lock": "released", "errors": errs,
            "statusLines": [line for line in status_lines if line is not None],
        }))
    finally:
        subprocess.run(cfq_argv("lock", "release", str(repo_root)), capture_output=True, text=True)


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
