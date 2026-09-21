"""Migrated from test-report.sh.

Self-test for scripts/cfq_report.py: append/set-commit/summary/html/last-failure/security plus
the index/detail surface.
"""

import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from cfq_testlib import CFQ_BIN, CfqTestCase, PLUGIN_ROOT, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_report  # noqa: E402


class TestReport(CfqTestCase):
    def _batch(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _report_json(self, batch):
        return json.loads((batch / "report.json").read_text())

    def test_extract_goal_matches_parse_phase_body_equivalent(self):
        # extract_goal is parse_phase_body's "context" field run through truncate_words at a
        # 320-char budget (raised from 220, which used to cut mid-sentence with no ellipsis) --
        # this pins the combined result as a literal, word-truncated with a trailing ellipsis.
        planfile = self._repos_dir / "phase-for-extract-goal.md"
        planfile.write_text(
            "# Phase 01 — Something\n\n"
            "## Size\n\nM\n\n"
            "## Context\n\n"
            "This is the first context line and it is reasonably long to help push us toward "
            "the two hundred and twenty character truncation boundary for testing purposes "
            "here now.\n"
            "This is the second context line, also fairly long, to make sure the combined "
            "length of both lines together comfortably exceeds two hundred twenty characters "
            "total.\n"
            "This third line should never be collected because extraction stops after two "
            "non-empty lines are gathered.\n\n"
            "## Affected Files\n\n"
            "- `/tmp/foo.py`\n"
        )
        expected = (
            "This is the first context line and it is reasonably long to help push us toward "
            "the two hundred and twenty character truncation boundary for testing purposes "
            "here now. This is the second context line, also fairly long, to make sure the "
            "combined length of both lines together comfortably exceeds two hundred twenty…"
        )
        self.assertEqual(cfq_report.extract_goal(str(planfile)), expected)

    def test_extract_goal_missing_file_returns_empty_string(self):
        missing = self._repos_dir / "does-not-exist.md"
        self.assertEqual(cfq_report.extract_goal(str(missing)), "")

    def _append_raises(self, dir_, phase_json):
        """Calls append_phase() expecting its errors.die() validation to fire (SystemExit),
        capturing what it printed to stderr the same way a subprocess call's `proc.stderr` used
        to."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
            cfq_report.append_phase(dir_, phase_json, record_telemetry=False)
        self.assertNotEqual(ctx.exception.code, 0)
        return buf.getvalue()

    def test_append_and_set_commit(self):
        batch = self._batch("2026-01-01-demo")

        # record_telemetry=False mirrors the old fixture's empty HOME (append's automatic
        # telemetry call finding no transcript, fail-soft, no-op) -- this batch stays a "report
        # without telemetry" fixture on purpose.
        cfq_report.append_phase(
            str(batch),
            '{"phase":"01-a","status":"green","finished":"2026-01-01T10:00:00+01:00","summary":"ok",'
            '"deviations":["Plan sagte X, gebaut Y"],"errors":[],"verification":"tests -> PASS","commit":"abc1234"}',
            record_telemetry=False,
        )
        cfq_report.append_phase(
            str(batch),
            '{"phase":"02-b","status":"red","finished":"2026-01-01T11:00:00+01:00","summary":"fehlgeschlagen",'
            '"deviations":[],"errors":["Verifikation rot: 1 Test <failed>"],"verification":"tests -> FAIL","commit":""}',
            record_telemetry=False,
        )

        self.run_cfq("report", "set-commit", str(batch), "01-a", "def5678")
        c = self._report_json(batch)["phases"][0]["commit"]
        self.assertEqual(c, "def5678", f"set-commit did not update commit = {c}")

        # Unknown phase: set-commit must fail loudly instead of silently returning the file
        # unchanged. Passing the bare number where the report carries the full slug used to exit
        # 0 and leave the commit field null forever -- the whole reason this check exists.
        before = (batch / "report.json").read_text()
        proc = self.run_cfq("report", "set-commit", str(batch), "01", "9999999")
        self.assertNotEqual(proc.returncode, 0, "set-commit with an unknown phase should exit non-zero")
        self.assertTrue(len(proc.stderr) > 0, "set-commit gave no stderr message for an unknown phase")
        after = (batch / "report.json").read_text()
        self.assertEqual(before, after, "set-commit modified report.json despite an unknown phase")

        # A batch whose report.json has an empty phases array hits the same path, not a jq crash.
        emptyph = self._batch("2026-01-04-emptyphases")
        (emptyph / "report.json").write_text(
            '{"repo":"","batch":"2026-01-04-emptyphases","started":"2026-01-04T10:00:00+01:00","phases":[]}\n'
        )
        proc = self.run_cfq("report", "set-commit", str(emptyph), "01-a", "aaa1111")
        self.assertNotEqual(proc.returncode, 0, "set-commit on an empty phases array should exit non-zero")

        # The routine case still works after the change -- same phase, a second overwrite.
        self.run_cfq("report", "set-commit", str(batch), "01-a", "ccc3333")
        c = self._report_json(batch)["phases"][0]["commit"]
        self.assertEqual(c, "ccc3333", f"set-commit no longer updates a known phase = {c}")

        # append validates the phase field before anything is persisted: NN-slug only.
        badph = self._batch("2026-01-05-badphase")

        # bare number -- the batch-009 shape that started this
        stderr = self._append_raises(str(badph), '{"phase":"01","status":"green","summary":"x"}')
        self.assertTrue(len(stderr) > 0, "append gave no stderr message for a bare phase number")
        self.assertFalse((badph / "report.json").exists(), "append created report.json despite rejecting the phase value")

        # missing phase field entirely
        self._append_raises(str(badph), '{"status":"green","summary":"x"}')

        # empty phase field
        self._append_raises(str(badph), '{"phase":"","status":"green","summary":"x"}')

        # routine case still accepted, and it is what creates report.json
        cfq_report.append_phase(str(badph), '{"phase":"03-c","status":"green","summary":"x"}', record_telemetry=False)
        self.assertEqual(
            self._report_json(badph)["phases"][-1]["phase"], "03-c",
            "append no longer accepts a well-formed phase slug",
        )

        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        expected = f"{batch.name}\t2\t1\t1\t1\t2026-01-01T11:00:00+01:00\t0\t0\t0\t\t"
        self.assertEqual(s, expected, f"summary = {s}")

        out = self.run_clean(str(CFQ_BIN), "report", "html", str(batch)).stdout.strip()
        self.assertEqual(out, str(batch / "report.html"), f"html path (default reportDir) = {out}")
        self.assertTrue((batch / "report.html").is_file(), "report.html not created")

        html = (batch / "report.html").read_text()
        self.assertIn("01-a", html, "report.html missing 01-a")
        self.assertIn("02-b", html, "report.html missing 02-b")
        self.assertIn("1 Test &lt;failed&gt;", html, "error text not HTML-escaped")
        self.assertEqual(html.count('class="tele"'), 0, "report.html has telemetry markup despite no telemetry data")

        lf = self.json_out(self.run_cfq("report", "last-failure", str(batch), "02-b"))
        self.assertTrue(lf["found"], f"last-failure should find 02-b's red entry: {lf}")
        self.assertEqual(lf["note"], "fehlgeschlagen", f"last-failure note: {lf}")

        lf = self.json_out(self.run_cfq("report", "last-failure", str(batch), "01-a"))
        self.assertFalse(lf["found"], f"01-a is green, last-failure should be false: {lf}")

        noreport = self._batch("2026-01-03-noreport")
        lf = self.json_out(self.run_cfq("report", "last-failure", str(noreport), "01-a"))
        self.assertFalse(lf["found"], f"last-failure on missing report.json should be false, not crash: {lf}")

        self.run_cfq("report", "security", str(batch), '{"status":"ok","critical":0,"high":0}')
        self.run_cfq("report", "security", str(batch), '{"status":"ok","critical":0,"high":1}')
        sec = len(self._report_json(batch)["security"])
        self.assertEqual(sec, 2, f"security snapshots = {sec}, want 2")

        # security on a fresh batch must create report.json -- this is the planning-time path,
        # where no phase has been appended yet.
        fresh = self._batch("2026-01-02-fresh")
        self.run_cfq("report", "security", str(fresh), '{"available":false,"counts":{}}')
        self.assertTrue((fresh / "report.json").exists(), "security did not create report.json")
        fresh_report = self._report_json(fresh)
        self.assertEqual(len(fresh_report["security"]), 1, f"fresh security snapshots = {len(fresh_report['security'])}, want 1")
        self.assertEqual(fresh_report["batch"], "2026-01-02-fresh", f"batch = {fresh_report['batch']}")

    def test_index_and_detail(self):
        # repo-p: alpha (open, all-green) and beta (archived, red with no later retry)
        repo_p = self._repos_dir / "repo-p"
        alpha = repo_p / ".claude" / "cfq" / "impl" / "2026-02-01-alpha"
        beta = repo_p / ".claude" / "cfq" / "impl" / "done" / "2026-02-02-beta"
        alpha.mkdir(parents=True)
        beta.mkdir(parents=True)
        (alpha / "report.json").write_text(json.dumps({
            "repo": "/repo-p", "batch": "2026-02-01-alpha", "started": "2026-02-01T09:00:00+01:00",
            "phases": [
                {"phase": "01-a", "status": "green", "finished": "2026-02-01T10:00:00+01:00", "summary": "ok",
                 "deviations": [], "errors": [], "verification": "tests -> PASS", "commit": "aaa1111"},
                {"phase": "02-b", "status": "green", "finished": "2026-02-01T11:00:00+01:00", "summary": "ok2",
                 "deviations": ["dev1"], "errors": [], "verification": "tests -> PASS", "commit": "aaa2222"},
            ],
        }))
        (beta / "report.json").write_text(json.dumps({
            "repo": "/repo-p", "batch": "2026-02-02-beta", "started": "2026-02-02T08:00:00+01:00",
            "phases": [
                {"phase": "01-a", "status": "red", "finished": "2026-02-02T09:00:00+01:00", "summary": "boom",
                 "deviations": [], "errors": ["stacktrace line"], "verification": "tests -> FAIL", "commit": ""},
            ],
        }))

        # repo-q: gamma (open, phase 01-a red then retried green -> MIXED)
        repo_q = self._repos_dir / "repo-q"
        gamma = repo_q / ".claude" / "cfq" / "impl" / "2026-02-03-gamma"
        gamma.mkdir(parents=True)
        (gamma / "report.json").write_text(json.dumps({
            "repo": "/repo-q", "batch": "2026-02-03-gamma", "started": "2026-02-03T08:00:00+01:00",
            "phases": [
                {"phase": "01-a", "status": "red", "finished": "2026-02-03T09:00:00+01:00", "summary": "first try failed",
                 "deviations": [], "errors": ["err"], "verification": "FAIL", "commit": ""},
                {"phase": "01-a", "status": "green", "finished": "2026-02-03T10:00:00+01:00", "implemented": "fixed",
                 "deviations": [], "errors": [], "verification": "PASS", "commit": "ccc3333"},
            ],
        }))

        # Call-counting stub for the N+1-regression guard: index must call cfq_scan.py exactly
        # once, regardless of how many report-bearing batches exist. cfq_report.py resolves its
        # own SCRIPT_DIR from its own path, so the stub has to be invoked directly by path --
        # this is the one case in this file that cannot go through bin/cfq, since the dispatcher
        # would always exec the real, unstubbed scripts/ directory.
        scan_calls = self._repos_dir / "scan-call-count"
        stub_dir = self._repos_dir / "stub-scripts"
        stub_dir.mkdir()
        scripts_dir = PLUGIN_ROOT / "scripts"
        (stub_dir / "cfq_report.py").write_bytes((scripts_dir / "cfq_report.py").read_bytes())
        (stub_dir / "cfq_brief.py").write_bytes((scripts_dir / "cfq_brief.py").read_bytes())
        shutil.copytree(scripts_dir / "cfq_lib", stub_dir / "cfq_lib")
        scan_calls.write_text("")
        stub_scan = stub_dir / "cfq_scan.py"
        stub_scan.write_text(f"""#!/usr/bin/env python3
import pathlib, subprocess, sys
with open({str(scan_calls)!r}, "a") as fh:
    fh.write("x\\n")
sys.exit(subprocess.run(["python3", {str(scripts_dir / 'cfq_scan.py')!r}, *sys.argv[1:]]).returncode)
""")
        stub_scan.chmod(0o755)

        # Direct invocation of the stubbed copy, matching the Bash original.
        proc = subprocess.run(
            ["python3", str(stub_dir / "cfq_report.py"), "index"],
            capture_output=True, text=True,
            env={**self._base_env(), "HOME": str(self.home), "CFQ_SCAN_ROOTS": str(self._repos_dir)},
        )
        idx = self.json_out(proc)
        self.assertEqual(len(idx), 3, f"index (no filter) length = {len(idx)}")

        calls = len(scan_calls.read_text().splitlines())
        self.assertEqual(calls, 1, f"index should call cfq_scan.py exactly once, got {calls}")

        st_alpha = next(e["status"] for e in idx if e["batch"] == "2026-02-01-alpha")
        self.assertEqual(st_alpha, "GREEN", f"alpha status = {st_alpha}")
        st_beta = next(e["status"] for e in idx if e["batch"] == "2026-02-02-beta")
        self.assertEqual(st_beta, "RED", f"beta status = {st_beta}")
        st_gamma = next(e["status"] for e in idx if e["batch"] == "2026-02-03-gamma")
        self.assertEqual(st_gamma, "MIXED", f"gamma status = {st_gamma}")

        dev_alpha = next(e["deviations"] for e in idx if e["batch"] == "2026-02-01-alpha")
        self.assertEqual(dev_alpha, 1, f"alpha deviations = {dev_alpha}")

        first = idx[0]["batch"]
        self.assertEqual(first, "2026-02-03-gamma", f"index should sort newest-first, got {first} first")

        idx_repo = self.json_out(self.run_cfq(
            "report", "index", "--repo", "repo-q", env={"CFQ_SCAN_ROOTS": str(self._repos_dir)},
        ))
        self.assertEqual(len(idx_repo), 1, f"--repo filter did not narrow to 1: {idx_repo}")
        self.assertEqual(idx_repo[0]["batch"], "2026-02-03-gamma", f"--repo filter wrong batch: {idx_repo}")

        idx_batch = self.json_out(self.run_cfq(
            "report", "index", "--batch", "alpha", env={"CFQ_SCAN_ROOTS": str(self._repos_dir)},
        ))
        self.assertEqual(len(idx_batch), 1, f"--batch filter did not narrow to 1: {idx_batch}")
        self.assertEqual(idx_batch[0]["batch"], "2026-02-01-alpha", f"--batch filter wrong batch: {idx_batch}")

        # --any matches either field, deduped, no separate merge on the caller's side
        idx_any = self.json_out(self.run_cfq(
            "report", "index", "--any", "repo-q", env={"CFQ_SCAN_ROOTS": str(self._repos_dir)},
        ))
        self.assertEqual(len(idx_any), 1, f"--any filter did not narrow to 1: {idx_any}")

        # --text is additive, not a substitute: same fixture, JSON above is untouched, and
        # RED/MIXED show up visibly marked. Deep render coverage (zero-cost dash, no-HTML-entity)
        # lives in test_render.py, not duplicated here.
        idx_text = self.run_cfq(
            "report", "index", "--text", env={"CFQ_SCAN_ROOTS": str(self._repos_dir)},
        ).stdout
        self.assertIn("**RED**", idx_text, "--text missing marked RED row")
        self.assertIn("**MIXED**", idx_text, "--text missing marked MIXED row")

        # detail on a batch with no report.json -> clear not-found result, no crash
        noreport_batch = repo_p / ".claude" / "cfq" / "impl" / "nope"
        noreport_batch.mkdir(parents=True)
        det_missing = self.json_out(self.run_cfq("report", "detail", str(noreport_batch)))
        self.assertFalse(det_missing["found"], f"detail on missing report.json should be found:false: {det_missing}")

        # detail on gamma: overall status MIXED, both attempts present
        det = self.json_out(self.run_cfq("report", "detail", str(gamma)))
        self.assertTrue(det["found"], "detail found = false for gamma")
        self.assertEqual(det["status"], "MIXED", f"detail status = {det['status']}")
        self.assertEqual(len(det["phases"]), 2, "detail phases length != 2")
        # gamma's second attempt carries `implemented`, not `summary` -- proves cmd_detail's
        # "summary" field is wired to phase_summary(), not a raw `summary` key read.
        self.assertEqual(det["phases"][1]["summary"], "fixed", f"detail summary via `implemented` = {det['phases'][1]}")

        # detail's verification-excerpt bound: a long verification log must not be dumped in full
        long_batch = repo_p / ".claude" / "cfq" / "impl" / "2026-02-04-longlog"
        long_batch.mkdir(parents=True)
        long_verification = "\n".join(f"line {i}" for i in range(200))
        (long_batch / "report.json").write_text(json.dumps({
            "repo": "/repo-p", "batch": "2026-02-04-longlog", "started": "2026-02-04T08:00:00+01:00",
            "phases": [
                {"phase": "01-a", "status": "green", "finished": "2026-02-04T09:00:00+01:00", "summary": "ok",
                 "deviations": [], "errors": [], "verification": long_verification, "commit": "ddd4444"},
            ],
        }))
        det_long = self.json_out(self.run_cfq("report", "detail", str(long_batch)))
        vlines = det_long["phases"][0]["verification"].count("\n")
        self.assertLess(vlines, 200, f"detail should bound verification output, got {vlines} lines")

    def test_html_report_dir_and_index(self):
        rd = self._repos_dir / "reportdir"
        rd.mkdir()
        repo_x = self._repos_dir / "repo-x"
        batch_x_name = "2026-03-01-goaltest"
        batch_x = repo_x / ".claude" / "cfq" / "impl" / "done" / batch_x_name
        (batch_x / "done").mkdir(parents=True)
        (batch_x / "done" / "01-a.md").write_text("""# A phase

## Context

This phase adds the goal-extraction test.
It covers the two-line context excerpt.

## Size

M
""")
        cfq_report.append_phase(
            str(batch_x),
            '{"phase":"01-a","status":"green","finished":"2026-03-01T10:00:00+01:00","summary":"ok",'
            '"deviations":[],"errors":[],"verification":"tests -> PASS","commit":"eee5555"}',
            record_telemetry=False,
        )

        env = {"CFQ_REPORT_DIR": str(rd), "CFQ_SCAN_ROOTS": str(self._repos_dir)}
        out_x = self.run_cfq("report", "html", str(batch_x), env=env).stdout.strip()
        self.assertEqual(out_x, str(rd / "repo-x" / f"{batch_x_name}.html"), f"reportDir html path = {out_x}")
        self.assertTrue((rd / "repo-x" / f"{batch_x_name}.html").is_file(), f"collected report.html not created: {out_x}")
        self.assertTrue((rd / "index.html").is_file(), "index.html not created")
        html_x = (rd / "repo-x" / f"{batch_x_name}.html").read_text()
        self.assertIn("This phase adds the goal-extraction test", html_x, "report.html missing phase goal text")
        self.assertIn('<header class="batch">', html_x, "report.html missing the header block")
        self.assertIn("<dt>Repo</dt>", html_x, "report.html header missing the Repo pair")
        self.assertIn("<dt>Started</dt>", html_x, "report.html header missing the Started pair")
        # phase 03 fills the overview placeholder in; this batch has no .batch-context.md, so the
        # slot renders empty and neither the placeholder comment nor the section survives.
        self.assertNotIn("<!-- overview -->", html_x, "overview placeholder not filled in")
        self.assertNotIn('<section class="overview">', html_x, "overview section rendered despite no .batch-context.md")
        # phase 04 fills the phase-table placeholder in; this batch has one phase, so the section
        # renders and the placeholder comment no longer survives.
        self.assertNotIn("<!-- phase-table -->", html_x, "phase-table placeholder not filled in")
        self.assertIn('<section class="phase-table">', html_x, "report.html missing the rendered phase table")
        self.assertNotIn("Dauer", html_x, "report.html still carries the German Dauer label")
        self.assertNotIn("Implementierung", html_x, "report.html still carries the German Implementierung label")
        index_html = (rd / "index.html").read_text()
        self.assertIn(batch_x_name, index_html, f"index.html missing batch {batch_x_name}")
        n_links = index_html.count("<a href=")
        self.assertGreaterEqual(n_links, 1, f"index.html has no links: {n_links}")

        # edge: batch whose phase file no longer exists -> phase still renders, goal omitted, no crash
        batch_y_name = "2026-03-02-nogoal"
        batch_y = repo_x / ".claude" / "cfq" / "impl" / "done" / batch_y_name
        (batch_y / "done").mkdir(parents=True)
        cfq_report.append_phase(
            str(batch_y),
            '{"phase":"01-a","status":"green","finished":"2026-03-02T10:00:00+01:00","summary":"ok",'
            '"deviations":[],"errors":[],"verification":"tests -> PASS","commit":"fff6666"}',
            record_telemetry=False,
        )
        out_y = self.run_cfq("report", "html", str(batch_y), env=env).stdout.strip()
        self.assertTrue(len(out_y) > 0, f"html for missing-plan-file batch not created: {out_y}")
        html_y = (rd / "repo-x" / f"{batch_y_name}.html").read_text()
        self.assertNotIn('class="goal"', html_y, "goal markup present despite no plan file")

        # edge: called twice -> overwritten not duplicated, index still lists the batch once
        out_x2 = self.run_cfq("report", "html", str(batch_x), env=env).stdout.strip()
        self.assertEqual(out_x2, out_x, f"second html call path differs: {out_x2}")
        count_x = len(list((rd / "repo-x").glob(f"{batch_x_name}.html")))
        self.assertEqual(count_x, 1, f"duplicate html file for batch_x: {count_x}")
        index_html = (rd / "index.html").read_text()
        href_count = index_html.count(f"repo-x/{batch_x_name}.html")
        self.assertEqual(href_count, 1, f"index.html links batch_x more than once: {href_count}")

        # must-fall-back: reportDir pointing at a path that cannot be created -> non-zero exit,
        # stderr message, batch-directory file NOT silently written instead
        robase = self._repos_dir / "readonly-parent"
        robase.mkdir()
        badrd = robase / "reports"
        robase.chmod(0o555)
        try:
            proc = self.run_cfq(
                "report", "html", str(batch_x),
                env={"CFQ_REPORT_DIR": str(badrd), "CFQ_SCAN_ROOTS": str(self._repos_dir)},
            )
        finally:
            robase.chmod(0o755)
        self.assertNotEqual(proc.returncode, 0, "html should fail when reportDir cannot be created")
        self.assertTrue(len(proc.stderr) > 0, "no stderr message on reportDir mkdir failure")
        self.assertFalse(
            (batch_x / "report.html").exists(), "fell back to writing batch-dir report.html on reportDir failure",
        )

    def test_html_repo_local_default_and_index(self):
        # change 1: an empty reportDir (the new default) resolves to <repo-root>/.claude/cfq/
        # reports/<batch>.html rather than inside the batch directory -- the required fixture
        # case: the first test running the shared body renderer against a path derived from the
        # batch directory itself.
        repo_y = self._repos_dir / "repo-y"
        batch_y_name = "2026-04-01-repolocal"
        batch_y = repo_y / ".claude" / "cfq" / "impl" / batch_y_name
        batch_y.mkdir(parents=True)
        cfq_report.append_phase(
            str(batch_y),
            '{"phase":"01-a","status":"green","finished":"2026-04-01T10:00:00+01:00","summary":"ok",'
            '"deviations":[],"errors":[],"verification":"tests -> PASS","commit":"1110000"}',
            record_telemetry=False,
        )

        env = {"CFQ_SCAN_ROOTS": str(self._repos_dir)}
        out = self.run_cfq("report", "html", str(batch_y), env=env).stdout.strip()
        expected_path = repo_y / ".claude" / "cfq" / "reports" / f"{batch_y_name}.html"
        self.assertEqual(out, str(expected_path), f"repo-local default html path = {out}")
        self.assertTrue(expected_path.is_file(), "repo-local report.html not created")
        self.assertFalse((batch_y / "report.html").exists(), "report.html must not also land in the batch dir")

        html_y = expected_path.read_text()
        self.assertIn('<header class="batch">', html_y, "report.html missing the header block")
        self.assertIn("<dt>Repo</dt>", html_y, "report.html header missing the Repo pair")
        self.assertIn("<dt>Started</dt>", html_y, "report.html header missing the Started pair")
        # phase 03 fills the overview placeholder in; this batch has no .batch-context.md, so the
        # slot renders empty and neither the placeholder comment nor the section survives.
        self.assertNotIn("<!-- overview -->", html_y, "overview placeholder not filled in")
        self.assertNotIn('<section class="overview">', html_y, "overview section rendered despite no .batch-context.md")
        # phase 04 fills the phase-table placeholder in; this batch has one phase, so the section
        # renders and the placeholder comment no longer survives.
        self.assertNotIn("<!-- phase-table -->", html_y, "phase-table placeholder not filled in")
        self.assertIn('<section class="phase-table">', html_y, "report.html missing the rendered phase table")
        self.assertNotIn("Dauer", html_y, "report.html still carries the German Dauer label")
        self.assertNotIn("Implementierung", html_y, "report.html still carries the German Implementierung label")

        # change 3: the repo-local default also regenerates index.html in that same reports/
        # directory, with a flat href -- not the shared-reportDir <repoBase>/<batch>.html shape,
        # since the reports/ dir is already repo-local.
        index_path = repo_y / ".claude" / "cfq" / "reports" / "index.html"
        self.assertTrue(index_path.is_file(), "repo-local index.html not created")
        index_html = index_path.read_text()
        self.assertIn(f'<a href="{batch_y_name}.html">', index_html, "repo-local index link not flat/relative")

        # change 3, scoping: a batch from a different repo must never show up in repo_y's own
        # local index, even though the underlying scan is cross-repo -- "listing that repo's
        # batches" per the phase, not everyone else's.
        repo_z = self._repos_dir / "repo-z"
        batch_z_name = "2026-04-02-otherrepo"
        batch_z = repo_z / ".claude" / "cfq" / "impl" / batch_z_name
        batch_z.mkdir(parents=True)
        cfq_report.append_phase(
            str(batch_z),
            '{"phase":"01-a","status":"green","finished":"2026-04-02T10:00:00+01:00","summary":"ok",'
            '"deviations":[],"errors":[],"verification":"tests -> PASS","commit":"2220000"}',
            record_telemetry=False,
        )
        self.run_cfq("report", "html", str(batch_y), env=env)  # regenerate repo_y's own index
        index_html = index_path.read_text()
        self.assertNotIn(batch_z_name, index_html, "repo-y's local index picked up a batch from another repo")

        # change 4: batch_z has a report.json but no rendered HTML anywhere -- the global table
        # still lists it, but prints no file:// line for it.
        idx_text = self.run_cfq("report", "index", "--text", env=env).stdout
        self.assertIn(batch_z_name, idx_text, "unrendered batch missing from the table")
        unrendered_path = repo_z / ".claude" / "cfq" / "reports" / f"{batch_z_name}.html"
        self.assertNotIn(f"file://{unrendered_path}", idx_text, "file:// line printed for an unrendered report")

    def test_html_telemetry_mode_and_worker_split(self):
        # change 5: the detail/HTML renderer surfaces phase 02's `mode` and, when the worker
        # share is non-zero, the orchestrator/worker split.
        batch = self._batch("2026-05-01-orchestrator-html")
        cfq_report.append_phase(
            str(batch),
            json.dumps({
                "phase": "01-a", "status": "green", "finished": "2026-05-01T10:00:00+01:00",
                "summary": "ok", "deviations": [], "errors": [], "verification": "tests -> PASS",
                "commit": "3330000",
                "telemetry": {
                    "totals": {"turns": 10, "output": 1000},
                    "subagent": {"turns": 6, "output": 700},
                    "by_model": {}, "by_effort": {}, "mode": "orchestrator",
                },
            }),
            record_telemetry=False,
        )
        out = self.run_clean(str(CFQ_BIN), "report", "html", str(batch)).stdout.strip()
        self.assertEqual(out, str(batch / "report.html"), f"html path (default reportDir) = {out}")
        html = (batch / "report.html").read_text()
        self.assertIn('<dt>Mode</dt><dd>orchestrator</dd>', html, "mode not rendered")
        self.assertIn(
            '<dt>Orchestrator / worker</dt><dd>4/6 turns · 300/700 out</dd>', html,
            "orchestrator/worker split not rendered correctly",
        )

        # A record predating phase 02 (no mode, no subagent activity) must render exactly as
        # before -- no empty Mode/Split column, no "None".
        batch2 = self._batch("2026-05-02-classic-html")
        cfq_report.append_phase(
            str(batch2),
            json.dumps({
                "phase": "01-a", "status": "green", "finished": "2026-05-02T10:00:00+01:00",
                "summary": "ok", "deviations": [], "errors": [], "verification": "tests -> PASS",
                "commit": "4440000",
                "telemetry": {"totals": {"turns": 3, "output": 300}, "by_model": {}, "by_effort": {}},
            }),
            record_telemetry=False,
        )
        out2 = self.run_clean(str(CFQ_BIN), "report", "html", str(batch2)).stdout.strip()
        self.assertEqual(out2, str(batch2 / "report.html"), f"html path (default reportDir) = {out2}")
        html2 = (batch2 / "report.html").read_text()
        self.assertNotIn('<dt>Mode</dt>', html2, "Mode column rendered despite no mode field")
        self.assertNotIn('<dt>Orchestrator / worker</dt>', html2, "Split column rendered despite no subagent activity")

        # A third fixture whose by_skill holds only "-" must omit the Skills pair entirely,
        # rather than rendering an empty value (the "-" sentinel is skills_str's own "unknown").
        batch3 = self._batch("2026-05-03-only-dash-skill")
        cfq_report.append_phase(
            str(batch3),
            json.dumps({
                "phase": "01-a", "status": "green", "finished": "2026-05-03T10:00:00+01:00",
                "summary": "ok", "deviations": [], "errors": [], "verification": "tests -> PASS",
                "commit": "5550000",
                "telemetry": {
                    "totals": {"turns": 3, "output": 300}, "by_model": {}, "by_effort": {},
                    "by_skill": {"-": 3},
                },
            }),
            record_telemetry=False,
        )
        self.run_clean(str(CFQ_BIN), "report", "html", str(batch3))
        html3 = (batch3 / "report.html").read_text()
        self.assertNotIn('<dt>Skills</dt>', html3, "Skills pair rendered despite by_skill holding only '-'")

    def test_html_stylesheet_defines_every_colour_on_root(self):
        # A colour must never get its only definition inside a @media block -- dark mode and the
        # print stylesheet only redefine tokens the bare :root block already declares.
        batch = self._batch("2026-06-01-stylecheck")
        cfq_report.append_phase(
            str(batch),
            '{"phase":"01-a","status":"green","finished":"2026-06-01T10:00:00+01:00","summary":"ok",'
            '"deviations":[],"errors":[],"verification":"tests -> PASS","commit":"6660000"}',
            record_telemetry=False,
        )
        self.run_clean(str(CFQ_BIN), "report", "html", str(batch))
        html = (batch / "report.html").read_text()

        style_match = re.search(r"<style>(.*?)</style>", html, re.S)
        self.assertIsNotNone(style_match, "no <style> block found in report.html")
        css = style_match.group(1)

        root_match = re.search(r":root\s*\{([^}]*)\}", css)
        self.assertIsNotNone(root_match, "no bare :root block found in the stylesheet")
        root_props = set(re.findall(r"(--[\w-]+)\s*:", root_match.group(1)))
        self.assertGreater(len(root_props), 0, "bare :root block defines no custom properties")

        media_root_blocks = re.findall(r"@media[^{]*\{\s*:root\s*\{([^}]*)\}\s*\}", css, re.S)
        self.assertGreater(len(media_root_blocks), 0, "no @media :root override block found (dark mode / print)")
        for block in media_root_blocks:
            for prop in re.findall(r"(--[\w-]+)\s*:", block):
                self.assertIn(
                    prop, root_props,
                    f"custom property {prop} is redefined inside a @media block but never defined on bare :root",
                )

    # ---- skills (phase 04: `cfq report skills` replaces the retired `jq` filter over
    # report.json's telemetry.skills_recommended / telemetry.by_skill) ------------------------

    def test_skills_overlapping_recommendations_deduplicated_and_sorted(self):
        batch = self._batch("2026-01-05-skills")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-05-skills", "started": "2026-01-05T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green",
                    "telemetry": {
                        "skills_recommended": ["tdd", "code-review"],
                        "by_skill": {"tdd": 5, "-": 2},
                    },
                },
                {
                    "phase": "02-b", "status": "green",
                    "telemetry": {
                        "skills_recommended": ["code-review", "dataviz"],
                        "by_skill": {"-": 3},
                    },
                },
            ],
        }))
        out = self.json_out(self.run_cfq("report", "skills", str(batch), check=True))
        self.assertEqual(out["recommended"], ["code-review", "dataviz", "tdd"])
        self.assertEqual(out["used"], ["tdd"])

    def test_skills_phase_without_telemetry_is_skipped_not_a_crash(self):
        batch = self._batch("2026-01-06-no-telemetry")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-06-no-telemetry", "started": "2026-01-06T10:00:00+01:00",
            "phases": [{"phase": "01-a", "status": "green"}],
        }))
        out = self.json_out(self.run_cfq("report", "skills", str(batch), check=True))
        self.assertEqual(out["recommended"], [])
        self.assertEqual(out["used"], [])

    def test_skills_empty_phases_array_both_lists_empty(self):
        batch = self._batch("2026-01-07-empty")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-07-empty", "started": "2026-01-07T10:00:00+01:00",
            "phases": [],
        }))
        out = self.json_out(self.run_cfq("report", "skills", str(batch), check=True))
        self.assertEqual(out["recommended"], [])
        self.assertEqual(out["used"], [])

    # ---- summary orchestrator/worker split (phase 05: `report summary` surfaces the subagent
    # token split cfq_telemetry.py already computes, additive so a classic-mode report is unaffected)

    def test_summary_splits_orchestrator_and_worker_when_subagent_sums_present(self):
        batch = self._batch("2026-01-08-orchestrator")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-08-orchestrator", "started": "2026-01-08T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-08T11:00:00+01:00",
                    "telemetry": {
                        "totals": {"turns": 10, "output": 1000},
                        "subagent": {"turns": 6, "output": 700},
                        "by_model": {}, "by_effort": {},
                    },
                },
                {
                    "phase": "02-b", "status": "green", "finished": "2026-01-08T12:00:00+01:00",
                    "telemetry": {
                        "totals": {"turns": 5, "output": 500},
                        "subagent": {"turns": 0, "output": 0},
                        "by_model": {}, "by_effort": {},
                    },
                },
            ],
        }))
        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        fields = s.split("\t")
        # existing fields (1-11) unchanged in shape
        self.assertEqual(fields[:6], [batch.name, "2", "2", "0", "0", "2026-01-08T12:00:00+01:00"])
        total_output, planning_output, total_turns = fields[6], fields[7], fields[8]
        self.assertEqual((total_output, planning_output, total_turns), ("1500", "0", "15"))
        # new fields 12-15: orchestrator_turns, orchestrator_output, worker_turns, worker_output
        self.assertEqual(fields[11:], ["9", "800", "6", "700"])
        self.assertEqual(int(fields[11]) + int(fields[13]), int(total_turns), "orchestrator + worker turns must add up to the existing total")
        self.assertEqual(int(fields[12]) + int(fields[14]), int(total_output), "orchestrator + worker output must add up to the existing total")

    def test_summary_classic_mode_no_subagent_sums_is_byte_identical(self):
        batch = self._batch("2026-01-09-classic")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-09-classic", "started": "2026-01-09T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-09T11:00:00+01:00",
                    "telemetry": {
                        "totals": {"turns": 10, "output": 1000},
                        "subagent": {"turns": 0, "output": 0},
                        "by_model": {"sonnet": {}}, "by_effort": {"medium": {}},
                    },
                },
            ],
        }))
        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        expected = f"{batch.name}\t1\t1\t0\t0\t2026-01-09T11:00:00+01:00\t1000\t0\t10\tsonnet\tmedium"
        self.assertEqual(s, expected, "classic-mode report grew a worker split it must not have")

        # A report predating this feature -- no `subagent` key at all -- must degrade the same way.
        batch2 = self._batch("2026-01-10-pre-feature")
        (batch2 / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-10-pre-feature", "started": "2026-01-10T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-10T11:00:00+01:00",
                    "telemetry": {"totals": {"turns": 3, "output": 300}, "by_model": {}, "by_effort": {}},
                },
            ],
        }))
        s2 = self.run_cfq("report", "summary", str(batch2)).stdout.rstrip("\n")
        expected2 = f"{batch2.name}\t1\t1\t0\t0\t2026-01-10T11:00:00+01:00\t300\t0\t3\t\t"
        self.assertEqual(s2, expected2, "pre-feature report (no subagent key) grew a worker split it must not have")


# ---- phase 01: derivation helpers cfq_report.py's html/detail/index rendering all funnel
# through -- pure functions over a phase dict, no batch directory, no subprocess.

class TestDerivations(unittest.TestCase):
    def setUp(self):
        # fmt_datetime/fmt_short go through datetime.astimezone(), which reads the machine's
        # local timezone -- pinned to UTC for the run so the expected strings below are portable.
        self._orig_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._orig_tz
        time.tzset()

    # -- phase_summary --------------------------------------------------------------------

    def test_phase_summary_only_implemented(self):
        self.assertEqual(cfq_report.phase_summary({"implemented": "built X"}), "built X")

    def test_phase_summary_only_summary(self):
        self.assertEqual(cfq_report.phase_summary({"summary": "did Y"}), "did Y")

    def test_phase_summary_both_implemented_wins(self):
        self.assertEqual(
            cfq_report.phase_summary({"implemented": "built X", "summary": "did Y"}), "built X",
        )

    def test_phase_summary_neither_is_empty_string_not_none(self):
        self.assertEqual(cfq_report.phase_summary({}), "")

    # -- phase_finished / batch_finished ---------------------------------------------------

    def test_phase_finished_prefers_finished_field(self):
        self.assertEqual(
            cfq_report.phase_finished({"finished": "2026-01-01T10:00:00+01:00"}),
            "2026-01-01T10:00:00+01:00",
        )

    def test_phase_finished_falls_back_to_telemetry_until(self):
        self.assertEqual(
            cfq_report.phase_finished({"telemetry": {"until": "2026-01-01T11:00:00Z"}}),
            "2026-01-01T11:00:00Z",
        )

    def test_phase_finished_neither_is_empty_string(self):
        self.assertEqual(cfq_report.phase_finished({}), "")

    def test_batch_finished_is_the_maximum_not_the_last_element(self):
        # Written out of time order: 01-a's retry (latest) sits in the middle of the array.
        data = {
            "started": "2026-01-01T00:00:00+01:00",
            "phases": [
                {"phase": "02-b", "finished": "2026-01-01T09:00:00+01:00"},
                {"phase": "01-a", "finished": "2026-01-01T12:00:00+01:00"},
                {"phase": "03-c", "finished": "2026-01-01T10:00:00+01:00"},
            ],
        }
        self.assertEqual(cfq_report.batch_finished(data), "2026-01-01T12:00:00+01:00")

    def test_batch_finished_falls_back_to_started_with_no_timestamps(self):
        data = {
            "started": "2026-01-02T00:00:00+01:00",
            "phases": [{"phase": "01-a"}, {"phase": "02-b"}],
        }
        self.assertEqual(cfq_report.batch_finished(data), "2026-01-02T00:00:00+01:00")

    # -- parse_ts / fmt_* -------------------------------------------------------------------

    def test_parse_ts_z_with_fractional_seconds(self):
        self.assertEqual(cfq_report.fmt_datetime("2026-09-21T13:16:49.329Z"), "2026-09-21 13:16")
        self.assertEqual(cfq_report.fmt_short("2026-09-21T13:16:49.329Z"), "21.09 13:16")

    def test_parse_ts_offset_timestamp(self):
        self.assertEqual(cfq_report.fmt_datetime("2026-01-01T10:30:00+02:00"), "2026-01-01 08:30")

    def test_parse_ts_empty_string_returns_none_and_empty_display(self):
        self.assertIsNone(cfq_report.parse_ts(""))
        self.assertEqual(cfq_report.fmt_datetime(""), "")
        self.assertEqual(cfq_report.fmt_short(""), "")

    def test_parse_ts_malformed_returns_none_not_an_exception(self):
        self.assertIsNone(cfq_report.parse_ts("not-a-date"))
        self.assertEqual(cfq_report.fmt_datetime("not-a-date"), "")
        self.assertEqual(cfq_report.fmt_short("not-a-date"), "")

    def test_fmt_duration_minutes_and_hours(self):
        self.assertEqual(cfq_report.fmt_duration(46), "0:46")
        self.assertEqual(cfq_report.fmt_duration(73), "1:13")
        self.assertEqual(cfq_report.fmt_duration(3723), "1:02:03")

    def test_fmt_duration_zero_and_none_are_dash(self):
        self.assertEqual(cfq_report.fmt_duration(0), "–")
        self.assertEqual(cfq_report.fmt_duration(None), "–")

    def test_fmt_int_groups_and_degrades(self):
        self.assertEqual(cfq_report.fmt_int(1582736), "1,582,736")
        self.assertEqual(cfq_report.fmt_int(0), "0")
        self.assertEqual(cfq_report.fmt_int(None), "–")
        self.assertEqual(cfq_report.fmt_int("not-a-number"), "–")

    # -- phase_topic --------------------------------------------------------------------------

    def test_phase_topic_leading_number(self):
        self.assertEqual(cfq_report.phase_topic("01-widget-loader"), "Widget loader")

    def test_phase_topic_two_digit_number_and_short_words(self):
        self.assertEqual(cfq_report.phase_topic("10-a-b-c"), "A b c")

    def test_phase_topic_no_leading_number(self):
        self.assertEqual(cfq_report.phase_topic("no-number-here"), "No number here")

    # -- phase_row ----------------------------------------------------------------------------

    def test_phase_row_full_record(self):
        phase = {
            "phase": "01-note-sweep-verb", "status": "green", "commit": "9f2b46a2",
            "telemetry": {
                "wallclock_s": 73,
                "until": "2026-09-21T15:16:00+02:00",
                "totals": {"turns": 23, "output": 11610, "billable_in": 87111, "cache_read": 1582736},
            },
        }
        row = cfq_report.phase_row(phase)
        self.assertEqual(row["slug"], "01-note-sweep-verb")
        self.assertEqual(row["nr"], "01")
        self.assertEqual(row["topic"], "Note sweep verb")
        self.assertEqual(row["status"], "green")
        self.assertEqual(row["glyph"], "✅")
        self.assertEqual(row["finished"], "2026-09-21T15:16:00+02:00")
        self.assertEqual(row["duration_s"], 73)
        self.assertEqual(row["duration_disp"], "1:13")
        self.assertEqual(row["turns"], 23)
        self.assertEqual(row["out"], 11610)
        self.assertEqual(row["billable_in"], 87111)
        self.assertEqual(row["cache_read"], 1582736)
        self.assertEqual(row["commit"], "9f2b46a2")

    def test_phase_row_without_telemetry_yields_zeros_not_none(self):
        row = cfq_report.phase_row({"phase": "02-x", "status": "red"})
        self.assertEqual(row["duration_s"], 0)
        self.assertEqual(row["duration_disp"], "–")
        self.assertEqual(row["turns"], 0)
        self.assertEqual(row["out"], 0)
        self.assertEqual(row["billable_in"], 0)
        self.assertEqual(row["cache_read"], 0)
        self.assertEqual(row["finished"], "")
        self.assertEqual(row["finished_disp"], "")
        self.assertEqual(row["commit"], "")

    # -- truncate_words -------------------------------------------------------------------------

    def test_truncate_words_shorter_than_limit_unchanged(self):
        self.assertEqual(cfq_report.truncate_words("short text", 320), "short text")

    def test_truncate_words_cuts_at_space_before_limit(self):
        self.assertEqual(
            cfq_report.truncate_words("one two three four five", 15), "one two three…",
        )

    def test_truncate_words_single_token_longer_than_limit_hard_cuts(self):
        self.assertEqual(cfq_report.truncate_words("a" * 30, 10), "a" * 10 + "…")


# ---- phase 04: the phase table -- one row per report.json phase record, including every retry
# attempt. Pure function over literal `phases` lists / report.json dicts, no project-specific
# nouns, no cfq verbs in the data.

class TestPhaseTable(unittest.TestCase):
    def setUp(self):
        # fmt_datetime goes through datetime.astimezone(), which reads the machine's local
        # timezone -- pinned to UTC so timestamps in the fixtures below are portable.
        self._orig_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._orig_tz
        time.tzset()

    def test_routine_two_green_phases_full_telemetry(self):
        phases = [
            {
                "phase": "01-widget-loader", "status": "green",
                "telemetry": {
                    "wallclock_s": 73, "until": "2026-09-21T15:16:00+02:00",
                    "totals": {"turns": 23, "output": 11610, "billable_in": 87111, "cache_read": 1582736},
                },
            },
            {
                "phase": "02-widget-saver", "status": "green",
                "telemetry": {
                    "wallclock_s": 46, "until": "2026-09-21T15:30:00+02:00",
                    "totals": {"turns": 12, "output": 8868, "billable_in": 20475, "cache_read": 1027912},
                },
            },
        ]
        html = cfq_report.phase_table_html(phases)
        self.assertEqual(html.count("<tr class="), 2, "expected exactly one <tr> per phase")
        self.assertEqual(html.count("✅"), 2, "expected the green glyph in both status cells")
        self.assertIn('href="#p-01-widget-loader"', html, "topic cell missing anchor to phase 01")
        self.assertIn('href="#p-02-widget-saver"', html, "topic cell missing anchor to phase 02")
        # tfoot sums turns/out across both rows: 23+12=35 turns, 11610+8868=20478 out.
        self.assertIn(">35<", html, "tfoot turns total incorrect")
        self.assertIn(">20,478<", html, "tfoot out total incorrect")

    def test_retry_three_records_two_phase_numbers(self):
        # A phase that went red and was re-run appends a second record for the same phase number
        # -- every attempt gets its own row, in record order.
        phases = [
            {"phase": "01-widget-loader", "status": "red",
             "telemetry": {"wallclock_s": 30, "totals": {"turns": 5, "output": 1000, "billable_in": 2000, "cache_read": 3000}}},
            {"phase": "01-widget-loader", "status": "green",
             "telemetry": {"wallclock_s": 40, "totals": {"turns": 6, "output": 1500, "billable_in": 2500, "cache_read": 3500}}},
            {"phase": "02-widget-saver", "status": "green",
             "telemetry": {"wallclock_s": 50, "totals": {"turns": 7, "output": 2000, "billable_in": 3000, "cache_read": 4000}}},
        ]
        html = cfq_report.phase_table_html(phases)
        self.assertEqual(html.count("<tr class="), 3, "red-then-green retry must not collapse to two rows")
        self.assertEqual(html.count('<tr class="red">'), 1)
        self.assertEqual(html.count('<tr class="green">'), 2)
        self.assertIn(">18<", html, "tfoot turns total must sum all three attempts (5+6+7)")
        self.assertIn(">4,500<", html, "tfoot out total must sum all three attempts (1000+1500+2000)")

    def test_missing_telemetry_renders_dash_and_zero_without_raising(self):
        phases = [{"phase": "03-widget-mover", "status": "green"}]
        html = cfq_report.phase_table_html(phases)
        self.assertIn("<td>–</td>", html, "Finished cell should show a dash, not a blank cell")
        self.assertIn('<td class="n">–</td>', html, "Duration cell should show a dash for zero duration")
        # 4 zero-derived cells (turns/out/in/cache) in the body row, and the same 4 in the tfoot
        # total -- the single row's own totals -- for 8 occurrences overall.
        self.assertEqual(html.count('<td class="n">0</td>'), 8, "turns/out/in/cache should each render 0, not raise")
        # The footer total is unaffected by the missing telemetry -- it degrades the same way.
        self.assertIn('<td class="n">–</td><td class="n">0</td><td class="n">0</td>'
                       '<td class="n">0</td><td class="n">0</td></tr></tfoot>', html)

    def test_empty_phase_list_returns_empty_string(self):
        self.assertEqual(cfq_report.phase_table_html([]), "")
        with tempfile.TemporaryDirectory() as td:
            doc = cfq_report.render_report_html({"batch": "x", "phases": []}, {}, td)
        self.assertNotIn('<section class="phase-table">', doc, "empty phase list must render no table section")
        self.assertNotIn("<!-- phase-table -->", doc, "placeholder must not survive into the rendered document")

    def test_anchor_contract_hrefs_match_ids_in_document(self):
        phases = [
            {"phase": "01-widget-loader", "status": "green",
             "telemetry": {"wallclock_s": 30, "totals": {"turns": 5, "output": 1000, "billable_in": 2000, "cache_read": 3000}}},
            {"phase": "02-widget-saver", "status": "red",
             "telemetry": {"wallclock_s": 40, "totals": {"turns": 6, "output": 1500, "billable_in": 2500, "cache_read": 3500}}},
        ]
        with tempfile.TemporaryDirectory() as td:
            doc = cfq_report.render_report_html({"batch": "x", "phases": phases}, {}, td)
        hrefs = set(re.findall(r'href="#(p-[^"]+)"', doc))
        ids = set(re.findall(r'id="(p-[^"]+)"', doc))
        self.assertTrue(hrefs, "no phase-table anchors found in the rendered document")
        self.assertEqual(hrefs, ids, "every phase-table href must have a matching section.phase id, and vice versa")


# ---- phase 03: the Markdown subset renderer for .batch-context.md -> the report's Overview
# section. Pure functions over literal strings, no files, no project-specific nouns.

class TestMarkdownSubset(unittest.TestCase):
    # -- md_min: routine / structural cases --------------------------------------------------

    def test_routine_heading_paragraph_and_list(self):
        out = cfq_report.md_min(
            "## Heading\n\nA paragraph.\n\n- one\n- two\n- three\n"
        )
        self.assertIn("<h3>Heading</h3>", out)
        self.assertIn("<p>A paragraph.</p>", out)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<li>two</li>", out)
        self.assertIn("<li>three</li>", out)

    def test_wrapped_bullet_continuation_stays_one_li_not_a_paragraph(self):
        out = cfq_report.md_min("- first line of the item\n  wraps onto this line\n")
        self.assertEqual(out.count("<li>"), 1)
        self.assertNotIn("<p>", out)
        self.assertIn("<li>first line of the item wraps onto this line</li>", out)

    # -- md_inline -----------------------------------------------------------------------------

    def test_inline_bold_and_code(self):
        self.assertEqual(cfq_report.md_inline("**bold**"), "<strong>bold</strong>")
        self.assertEqual(cfq_report.md_inline("`code`"), "<code>code</code>")

    def test_inline_backtick_span_wins_over_bold_inside_it(self):
        out = cfq_report.md_inline("`a **b** c`")
        self.assertNotIn("<strong>", out)
        self.assertEqual(out, "<code>a **b** c</code>")

    # -- escaping --------------------------------------------------------------------------------

    def test_escaping_happens_before_this_function_is_reached(self):
        # md_min escapes each emitted value itself (via esc()) -- feeding it raw HTML must come
        # out neutralised, never as a literal live tag.
        out = cfq_report.md_min("A line with <script>alert(1)</script> in it.")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script", out)

    # -- edge cases ------------------------------------------------------------------------------

    def test_empty_string_returns_empty(self):
        self.assertEqual(cfq_report.md_min(""), "")

    def test_only_blank_lines_returns_empty(self):
        self.assertEqual(cfq_report.md_min("\n\n\n"), "")

    def test_single_hash_title_alone_is_skipped_entirely(self):
        out = cfq_report.md_min("# Batch Context\n")
        self.assertEqual(out, "")

    # -- fall-through: outside the documented subset ------------------------------------------

    def test_blockquote_and_table_line_fall_back_to_paragraph_text(self):
        out = cfq_report.md_min("> a quote\n\n| a | table |\n")
        self.assertNotIn("<blockquote", out)
        self.assertNotIn("<table", out)
        self.assertIn("<p>", out)
        self.assertIn("&gt; a quote", out)
        self.assertIn("| a | table |", out)


class TestOverview(unittest.TestCase):
    def _dir_with_context(self, tmp_path, body):
        (tmp_path).mkdir(parents=True, exist_ok=True)
        (tmp_path / ".batch-context.md").write_text(body)
        return str(tmp_path)

    def test_all_five_sections_renders_only_goal_decisions_non_goals(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._dir_with_context(pathlib.Path(td), (
                "# Batch Context\n\n"
                "## Goal\n\nMake it work.\n\n"
                "## Decisions\n\n- **One.** Do the thing.\n\n"
                "## Invariants\n\n- Never break this.\n\n"
                "## Cross-Phase Contracts\n\n- Phase 01 -> all.\n\n"
                "## Non-Goals\n\n- Not doing that.\n"
            ))
            out = cfq_report.overview_html(d)
            self.assertIn('<section class="overview">', out)
            self.assertIn("<h3>Goal</h3>", out)
            self.assertIn("<h3>Decisions</h3>", out)
            self.assertIn("<h3>Non-Goals</h3>", out)
            self.assertNotIn("Invariants", out)
            self.assertNotIn("Cross-Phase Contracts", out)

    def test_only_goal_present_no_empty_headings_for_the_rest(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._dir_with_context(pathlib.Path(td), "# Batch Context\n\n## Goal\n\nJust this.\n")
            out = cfq_report.overview_html(d)
            self.assertIn("<h3>Goal</h3>", out)
            self.assertNotIn("<h3>Decisions</h3>", out)
            self.assertNotIn("<h3>Non-Goals</h3>", out)

    def test_no_batch_context_file_returns_empty_and_html_has_no_section(self):
        with tempfile.TemporaryDirectory() as td:
            d = str(pathlib.Path(td))
            self.assertEqual(cfq_report.overview_html(d), "")
            doc = cfq_report.render_report_html(
                {"batch": "x", "phases": []}, {}, d,
            )
            self.assertNotIn('<section class="overview">', doc)
            self.assertIn("<!doctype html>", doc)

    def test_lowercase_heading_still_found(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._dir_with_context(pathlib.Path(td), "# Batch Context\n\n## non-goals\n\n- x\n")
            out = cfq_report.overview_html(d)
            self.assertIn("<h3>Non-Goals</h3>", out)


# ---- phase 05: `triggers`/`filesTouched`/`parkedPlanEntries` sections in phase_html, plus the
# `security` block -- recorded data report.json already carries but the HTML never rendered.

class TestPhaseExtras(unittest.TestCase):
    def _phase(self, **overrides):
        base = {"phase": "01-a", "status": "green"}
        base.update(overrides)
        return base

    def test_all_five_arrays_populated_render_in_order(self):
        phase = self._phase(
            triggers=["omitted"],
            deviations=["did X instead of Y"],
            errors=["boom"],
            filesTouched=["src/widget.py"],
            parkedPlanEntries=["plan/2026-09-21-followup.md"],
        )
        html = cfq_report.phase_html(phase, {})
        headings = re.findall(r"<h4>([^<]*)</h4>", html)
        self.assertEqual(
            headings,
            ["Triggers", "Deviations", "Errors", "Files touched", "Parked plan entries"],
        )

    def test_triggers_empty_absent_and_null_render_no_heading(self):
        for label, kwargs in (("empty", {"triggers": []}), ("absent", {}), ("null", {"triggers": None})):
            with self.subTest(label=label):
                phase = self._phase(
                    deviations=["d"], errors=["e"], filesTouched=["f"], parkedPlanEntries=["p"], **kwargs,
                )
                html = cfq_report.phase_html(phase, {})
                self.assertNotIn("<h4>Triggers</h4>", html)
                self.assertIn("<h4>Deviations</h4>", html)
                self.assertIn("<h4>Errors</h4>", html)
                self.assertIn("<h4>Files touched</h4>", html)
                self.assertIn("<h4>Parked plan entries</h4>", html)

    def test_files_touched_empty_absent_and_null_render_no_heading(self):
        for label, kwargs in (("empty", {"filesTouched": []}), ("absent", {}), ("null", {"filesTouched": None})):
            with self.subTest(label=label):
                phase = self._phase(
                    triggers=["t"], deviations=["d"], errors=["e"], parkedPlanEntries=["p"], **kwargs,
                )
                html = cfq_report.phase_html(phase, {})
                self.assertNotIn("<h4>Files touched</h4>", html)
                self.assertIn("<h4>Triggers</h4>", html)
                self.assertIn("<h4>Deviations</h4>", html)
                self.assertIn("<h4>Errors</h4>", html)
                self.assertIn("<h4>Parked plan entries</h4>", html)

    def test_parked_plan_entries_empty_absent_and_null_render_no_heading(self):
        for label, kwargs in (
            ("empty", {"parkedPlanEntries": []}), ("absent", {}), ("null", {"parkedPlanEntries": None}),
        ):
            with self.subTest(label=label):
                phase = self._phase(
                    triggers=["t"], deviations=["d"], errors=["e"], filesTouched=["f"], **kwargs,
                )
                html = cfq_report.phase_html(phase, {})
                self.assertNotIn("<h4>Parked plan entries</h4>", html)
                self.assertIn("<h4>Triggers</h4>", html)
                self.assertIn("<h4>Deviations</h4>", html)
                self.assertIn("<h4>Errors</h4>", html)
                self.assertIn("<h4>Files touched</h4>", html)

    def test_files_touched_entries_wrapped_in_code_triggers_are_not(self):
        phase = self._phase(triggers=["dependency"], filesTouched=["src/widget.py"])
        html = cfq_report.phase_html(phase, {})
        self.assertIn("<li><code>src/widget.py</code></li>", html)
        self.assertIn("<li>dependency</li>", html)

    def test_entry_with_markup_is_escaped(self):
        phase = self._phase(triggers=["<b>x</b>"], filesTouched=["<b>x</b>"])
        html = cfq_report.phase_html(phase, {})
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>x</b>", html)


class TestSecuritySection(unittest.TestCase):
    def setUp(self):
        # fmt_datetime goes through datetime.astimezone(), which reads the machine's local
        # timezone -- pinned to UTC so the snapshot timestamp below is portable.
        self._orig_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._orig_tz
        time.tzset()

    def test_available_false_with_hint_renders_one_muted_line_no_counts_grid(self):
        data = {"security": [{
            "available": False, "counts": {}, "findings": [],
            "hint": "Dependabot and code scanning return nothing for this repo",
            "at": "2026-09-21T15:02:00+02:00",
        }]}
        html = cfq_report.security_html(data)
        self.assertIn('<section class="security">', html)
        self.assertEqual(html.count("<p"), 1)
        self.assertIn("Dependabot and code scanning return nothing for this repo", html)
        self.assertNotIn('<dl class="meta">', html)

    def test_available_true_with_counts_and_two_findings_renders_grid_and_list(self):
        data = {"security": [{
            "available": True,
            "counts": {"critical": 1, "high": 2, "low": 0},
            "findings": [
                {"severity": "high", "title": "Outdated dependency"},
                "A bare-string finding",
            ],
        }]}
        html = cfq_report.security_html(data)
        self.assertIn('<dl class="meta">', html)
        self.assertEqual(html.count("<li"), 2)
        self.assertIn("A bare-string finding", html)

    def test_available_true_empty_counts_and_findings_is_nothing_to_show(self):
        data = {"security": [{"available": True, "counts": {}, "findings": []}]}
        html = cfq_report.security_html(data)
        self.assertNotIn("<ul>", html)
        self.assertNotIn('<dl class="meta">', html)

    def test_missing_or_empty_security_key_returns_empty_string_and_no_section(self):
        for data in ({}, {"security": []}):
            self.assertEqual(cfq_report.security_html(data), "")
        with tempfile.TemporaryDirectory() as td:
            doc = cfq_report.render_report_html({"batch": "x", "phases": []}, {}, td)
        self.assertNotIn('<section class="security">', doc)

    def test_last_entry_used_when_multiple_snapshots(self):
        data = {"security": [
            {"available": False, "hint": "first"},
            {"available": True, "counts": {"critical": 3}, "findings": []},
        ]}
        html = cfq_report.security_html(data)
        self.assertIn('<dl class="meta">', html)
        self.assertNotIn("first", html)

    def test_section_placed_between_phase_table_and_main(self):
        data = {
            "batch": "x",
            "security": [{"available": True, "counts": {"critical": 1}, "findings": []}],
            "phases": [{"phase": "01-a", "status": "green"}],
        }
        with tempfile.TemporaryDirectory() as td:
            doc = cfq_report.render_report_html(data, {}, td)
        table_idx = doc.index('<section class="phase-table">')
        security_idx = doc.index('<section class="security">')
        main_idx = doc.index("<main>")
        self.assertLess(table_idx, security_idx, "security section must come after the phase table")
        self.assertLess(security_idx, main_idx, "security section must come before <main>")


if __name__ == "__main__":
    unittest.main()
