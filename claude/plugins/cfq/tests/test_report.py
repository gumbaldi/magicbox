"""Migrated from test-report.sh.

Self-test for scripts/cfq_report.py: append/set-commit/summary/html/last-failure/security plus
the index/detail surface.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

from cfq_testlib import CfqTestCase, PLUGIN_ROOT, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_report  # noqa: E402
from cfq_lib import markdown as cfq_lib_markdown  # noqa: E402


class TestReport(CfqTestCase):
    def _batch(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _report_json(self, batch):
        return json.loads((batch / "report.json").read_text())

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
        # 1-11 as before, then the always-appended (7-field) tail (fields 12-15 are absent here
        # since neither phase has any telemetry at all, let alone worker activity):
        # total_billable_in, planning_turns, planning_billable_in, explore_turns, explore_output,
        # worker_explore_turns, worker_explore_output, all zero.
        expected = f"{batch.name}\t2\t1\t1\t1\t2026-01-01T11:00:00+01:00\t0\t0\t0\t\t\t0\t0\t0\t0\t0\t0\t0"
        self.assertEqual(s, expected, f"summary = {s}")

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
        # would always exec the real, unstubbed scripts/ directory. Copies the whole `scripts/`
        # tree plus `bin/`, preserving the real `bin/../scripts` layout (the same rule every other
        # filename-shadowing test double in this suite already follows), rather than the handful of
        # files that would technically suffice for this one call.
        scan_calls = self._repos_dir / "scan-call-count"
        scripts_dir = PLUGIN_ROOT / "scripts"
        stub_root = self._repos_dir / "stub-cfq"
        stub_scripts = stub_root / "scripts"
        shutil.copytree(scripts_dir, stub_scripts)
        shutil.copytree(PLUGIN_ROOT / "bin", stub_root / "bin")
        scan_calls.write_text("")
        stub_scan = stub_scripts / "cfq_scan.py"
        stub_scan.write_text(f"""#!/usr/bin/env python3
import pathlib, subprocess, sys
with open({str(scan_calls)!r}, "a") as fh:
    fh.write("x\\n")
sys.exit(subprocess.run(["python3", {str(scripts_dir / 'cfq_scan.py')!r}, *sys.argv[1:]]).returncode)
""")
        stub_scan.chmod(0o755)

        # Direct invocation of the stubbed copy, matching the Bash original.
        proc = subprocess.run(
            ["python3", str(stub_scripts / "cfq_report.py"), "index"],
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
        # RED/MIXED show up as glyphs, not words -- phase 06 replaces the bold-word status column
        # with the shape-coded glyph. Deep render coverage (grouping, --limit, the blank-line
        # separator regression) lives in TestIndexText below, not duplicated here.
        idx_text = self.run_cfq(
            "report", "index", "--text", env={"CFQ_SCAN_ROOTS": str(self._repos_dir)},
        ).stdout
        self.assertIn("❌", idx_text, "--text missing the RED glyph")
        self.assertIn("⚠️", idx_text, "--text missing the MIXED glyph")
        self.assertNotIn("RED", idx_text, "--text still carries the word RED")
        self.assertNotIn("MIXED", idx_text, "--text still carries the word MIXED")

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

    # ---- html: batch 040 phase 05 -- a thin `portal sync` alias, no file of its own -----------

    def test_html_is_a_thin_portal_alias(self):
        repo = self._repos_dir / "repo-html-alias"
        batch_name = "2026-07-01-htmlalias"
        batch = repo / ".claude" / "cfq" / "impl" / batch_name
        batch.mkdir(parents=True)
        cfq_report.append_phase(
            str(batch),
            '{"phase":"01-a","status":"green","finished":"2026-07-01T10:00:00+01:00","summary":"ok",'
            '"deviations":[],"errors":[],"verification":"tests -> PASS","commit":"7770000"}',
            record_telemetry=False,
        )

        out = self.run_cfq("report", "html", str(batch)).stdout.strip()
        self.assertEqual(
            out, f"file://{repo}/.claude/cfq/reports/index.html#/batch/{batch_name}",
            f"html alias did not print the portal's batch route: {out}",
        )
        self.assertFalse((batch / "report.html").exists(), "html alias must not write a batch-dir report.html")
        self.assertFalse(
            (repo / ".claude" / "cfq" / "reports" / f"{batch_name}.html").exists(),
            "html alias must not write a flat <batch>.html file",
        )
        self.assertTrue(
            (repo / ".claude" / "cfq" / "reports" / "data" / "batch" / f"{batch_name}.impl.js").is_file(),
            "html alias did not sync this batch's own data into the portal",
        )
        self.assertTrue(
            (repo / ".claude" / "cfq" / "reports" / "index.html").is_file(),
            "html alias did not install the portal shell",
        )

    def test_html_without_a_resolvable_repo_root_fails_loudly(self):
        # A batch directory not nested under `.claude/cfq/impl(/done)/` at all has nowhere for a
        # portal to live -- the alias must refuse, not silently degrade or write a fallback file.
        batch = self._batch("2026-07-02-noreporoot")
        proc = self.run_cfq("report", "html", str(batch))
        self.assertNotEqual(proc.returncode, 0, "html alias should fail without a resolvable repo root")
        self.assertTrue(len(proc.stderr) > 0, "no stderr message for an unresolvable repo root")

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

    def test_summary_falls_back_to_collapsed_subagent_when_subagent_worker_key_is_absent(self):
        # A report written before this phase has no `subagent_worker` key at all -- the phase's
        # own compatibility shim, for data already on disk (never for code): fields 12-15 fall
        # back to the old collapsed `subagent` value instead of raising or silently dropping the
        # split.
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
        # existing fields (1-6) unchanged in shape
        self.assertEqual(fields[:6], [batch.name, "2", "2", "0", "0", "2026-01-08T12:00:00+01:00"])
        # totals are now whole-batch: main (10+5=15) + worker (6+0=6), no Explore activity here.
        total_output, planning_output, total_turns = fields[6], fields[7], fields[8]
        self.assertEqual((total_output, planning_output, total_turns), ("2200", "0", "21"))
        # fields 12-15: orchestrator_turns (main), orchestrator_output (main), worker_turns,
        # worker_output -- read straight from the layers, not `total - worker` -- then the
        # always-appended tail (total_billable_in, planning_turns, planning_billable_in,
        # explore_turns, explore_output, worker_explore_turns, worker_explore_output), all zero
        # since this old-style fixture carries none of billable_in/planning/subagent_explore.
        self.assertEqual(
            fields[11:], ["15", "1500", "6", "700", "0", "0", "0", "0", "0", "0", "0"],
        )
        self.assertEqual(
            int(fields[11]) + int(fields[13]), int(total_turns),
            "main + worker turns must add up to the whole-batch total (no Explore activity here)",
        )
        self.assertEqual(
            int(fields[12]) + int(fields[14]), int(total_output),
            "main + worker output must add up to the whole-batch total (no Explore activity here)",
        )

    def test_summary_uses_subagent_worker_and_explore_when_present(self):
        # Post-change data: subagent_worker/subagent_explore are both populated, and a planning
        # record is present too. Fields 12-15 must be sourced from subagent_worker only -- the
        # Explore turns must not leak into the worker split -- and totals are now whole-batch,
        # planning included: main (4 planning + 10 phase = 14), explore (2), worker (6).
        batch = self._batch("2026-01-11-worker-and-explore")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-11-worker-and-explore",
            "started": "2026-01-11T10:00:00+01:00",
            "planning": {
                "totals": {"turns": 4, "output": 400, "billable_in": 150, "cache_read": 5},
            },
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-11T11:00:00+01:00",
                    "telemetry": {
                        "totals": {"turns": 10, "output": 1000, "billable_in": 600},
                        "subagent": {"turns": 8, "output": 750},
                        "subagent_worker": {"turns": 6, "output": 700},
                        "subagent_explore": {"turns": 2, "output": 50},
                        "by_model": {}, "by_effort": {},
                    },
                },
            ],
        }))
        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        fields = s.split("\t")
        total_output, planning_output, total_turns = fields[6], fields[7], fields[8]
        # whole-batch: main(4+10=14 turns, 400+1000=1400 out) + explore(2, 50) + worker(6, 700)
        self.assertEqual((total_output, planning_output, total_turns), ("2150", "400", "22"))
        # 12-15: main (14/1400), worker split sourced from subagent_worker (6/700), not the
        # collapsed subagent (8/750)
        self.assertEqual(fields[11:15], ["14", "1400", "6", "700"])
        # tail: total_billable_in (150 planning + 600 phase), planning_turns, planning_billable_in,
        # explore_turns, explore_output, worker_explore_turns, worker_explore_output
        self.assertEqual(fields[15:], ["750", "4", "150", "2", "50", "0", "0"])

    def test_summary_explore_only_phase_is_not_counted_as_worker(self):
        # The regression from Context, reproduced directly: a phase whose only sub-agent activity
        # is an Explore agent must not trip the `worker_output > 0 or worker_turns > 0` gate --
        # fields 12-15 stay absent, exactly as a phase with no sub-agent activity at all. Totals
        # are whole-batch: main (5) + explore (3) = 8 turns, 500 + 200 = 700 output.
        batch = self._batch("2026-01-12-explore-only")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-12-explore-only", "started": "2026-01-12T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-12T11:00:00+01:00",
                    "telemetry": {
                        "totals": {"turns": 5, "output": 500, "billable_in": 300},
                        "subagent": {"turns": 3, "output": 200},
                        "subagent_worker": {"turns": 0, "output": 0},
                        "subagent_explore": {"turns": 3, "output": 200},
                        "by_model": {}, "by_effort": {},
                    },
                },
            ],
        }))
        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        fields = s.split("\t")
        # fields 1-11 as normal, no 12-15 worker block, then the always-appended (now 7-field) tail
        self.assertEqual(len(fields), 18, f"expected no fields 12-15, got row {fields}")
        self.assertEqual(fields[6:11], ["700", "0", "8", "", ""])
        self.assertEqual(fields[11:], ["300", "0", "0", "3", "200", "0", "0"])

    def test_summary_orchestrator_worker_invariant_never_negative(self):
        # The regression case from Context, asserted directly: a fixture reproducing batch 034's
        # shape -- a classic-mode batch whose phases ran Explore agents but no phase worker --
        # must yield orchestrator_turns >= 0. Checked over several representative fixtures so no
        # future change can silently reintroduce a negative turn count.
        fixtures = [
            # batch 034's shape: heavy Explore usage, no phase worker at all.
            {
                "repo": "", "batch": "2026-01-13-classic-heavy-explore", "started": "2026-01-13T10:00:00+01:00",
                "phases": [
                    {
                        "phase": f"0{i}-a", "status": "green", "finished": f"2026-01-13T1{i}:00:00+01:00",
                        "telemetry": {
                            "totals": {"turns": 5, "output": 500},
                            "subagent": {"turns": 40, "output": 4000},
                            "subagent_worker": {"turns": 0, "output": 0},
                            "subagent_explore": {"turns": 40, "output": 4000},
                            "by_model": {}, "by_effort": {},
                        },
                    }
                    for i in range(1, 4)
                ],
            },
            # a genuine orchestrator-mode batch.
            {
                "repo": "", "batch": "2026-01-14-orchestrator", "started": "2026-01-14T10:00:00+01:00",
                "phases": [
                    {
                        "phase": "01-a", "status": "green", "finished": "2026-01-14T11:00:00+01:00",
                        "telemetry": {
                            "totals": {"turns": 10, "output": 1000},
                            "subagent": {"turns": 6, "output": 700},
                            "subagent_worker": {"turns": 6, "output": 700},
                            "subagent_explore": {"turns": 0, "output": 0},
                            "by_model": {}, "by_effort": {},
                        },
                    },
                ],
            },
        ]
        for report in fixtures:
            batch = self._batch(report["batch"])
            (batch / "report.json").write_text(json.dumps(report))
            s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
            fields = s.split("\t")
            total_turns = int(fields[8])
            if len(fields) == 18:
                # No phase worker ever ran (subagent_worker is zero on every phase) -- the
                # heavy-Explore batch-034 shape. Fields 12-15 must be absent entirely, which is
                # itself the fix: a negative number can never be printed for a split that isn't
                # emitted.
                continue
            orchestrator_turns, worker_turns = int(fields[11]), int(fields[13])
            self.assertGreaterEqual(orchestrator_turns, 0, f"{report['batch']}: orchestrator_turns went negative")
            self.assertGreaterEqual(worker_turns, 0, f"{report['batch']}: worker_turns went negative")
            self.assertEqual(
                orchestrator_turns + worker_turns, total_turns,
                f"{report['batch']}: orchestrator_turns + worker_turns must sum back to total_turns"
                " (no Explore activity in this fixture)",
            )

    def test_summary_batch_035_regression_shape_no_field_negative(self):
        # The exact defect from Context: batch 035 printed orchestrator_turns = -401 because
        # total_turns (main only, no worker) minus worker_turns went deeply negative. Reproduced
        # here with the numbers named in the phase plan (totals.turns = 9, subagent_worker.turns
        # = 86) -- a genuinely disjoint pool, main and worker never overlapping -- and asserted
        # that no field is ever negative, the row's total is main + worker (no subtraction), and
        # the four-layer invariant holds.
        batch = self._batch("2026-01-15-batch-035-shape")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-15-batch-035-shape", "started": "2026-01-15T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-15T11:00:00+01:00",
                    "telemetry": {
                        "totals": {"turns": 9, "output": 900},
                        "subagent_worker": {"turns": 86, "output": 8600},
                        "by_model": {}, "by_effort": {},
                    },
                },
            ],
        }))
        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        fields = s.split("\t")
        for f in fields[6:]:
            if f == "":
                continue
            self.assertGreaterEqual(int(f), 0, f"field went negative: {fields}")
        total_output, total_turns = int(fields[6]), int(fields[8])
        self.assertEqual(total_turns, 95, f"total_turns = {fields}")
        self.assertEqual(total_output, 9500, f"total_output = {fields}")
        orchestrator_turns, orchestrator_output, worker_turns, worker_output = (
            int(fields[11]), int(fields[12]), int(fields[13]), int(fields[14]),
        )
        self.assertEqual(orchestrator_turns, 9, "field 12 must be the session's own (main) turns")
        self.assertEqual(worker_turns, 86)
        self.assertEqual(orchestrator_turns + worker_turns, total_turns)
        self.assertEqual(orchestrator_output + worker_output, total_output)

    def test_summary_schema2_layers_read_directly_worker_explore_populated(self):
        # A schema-2 telemetry record carries its own `layers` object -- read as-is, never
        # re-derived from the (here deliberately bogus) `totals`, and the one fixture in this
        # class that populates `worker_explore` -- the new tail fields must carry real numbers.
        batch = self._batch("2026-01-16-schema2-layers")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-16-schema2-layers", "started": "2026-01-16T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green", "finished": "2026-01-16T11:00:00+01:00",
                    "telemetry": {
                        "schema": 2,
                        "totals": {"turns": 999, "output": 99999, "billable_in": 99999},
                        "layers": {
                            "main": {"turns": 3, "output": 300, "billable_in": 100},
                            "main_explore": {"turns": 1, "output": 50, "billable_in": 0},
                            "worker": {"turns": 6, "output": 700, "billable_in": 200},
                            "worker_explore": {"turns": 2, "output": 150, "billable_in": 0},
                        },
                        "by_model": {}, "by_effort": {},
                    },
                },
            ],
        }))
        s = self.run_cfq("report", "summary", str(batch)).stdout.rstrip("\n")
        fields = s.split("\t")
        total_output, planning_output, total_turns = fields[6], fields[7], fields[8]
        self.assertEqual((total_output, planning_output, total_turns), ("1200", "0", "12"))
        # 12-15: main (3/300), worker (6/700) -- straight off `layers`, ignoring the bogus `totals`
        self.assertEqual(fields[11:15], ["3", "300", "6", "700"])
        # tail: total_billable_in (100+0+200+0), planning_turns, planning_billable_in,
        # explore_turns, explore_output, worker_explore_turns, worker_explore_output
        self.assertEqual(fields[15:], ["300", "0", "0", "1", "50", "2", "150"])

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
        # Fields 1-11 stay exactly as before (no Explore/worker activity, so whole-batch totals
        # equal the old main-only totals too); fields 12-15 are still absent (no worker activity);
        # the always-appended (now 7-field) tail is all zero since this fixture carries none of
        # billable_in/planning/subagent_explore/subagent_worker.
        expected = (
            f"{batch.name}\t1\t1\t0\t0\t2026-01-09T11:00:00+01:00\t1000\t0\t10\tsonnet\tmedium"
            "\t0\t0\t0\t0\t0\t0\t0"
        )
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
        expected2 = f"{batch2.name}\t1\t1\t0\t0\t2026-01-10T11:00:00+01:00\t300\t0\t3\t\t\t0\t0\t0\t0\t0\t0\t0"
        self.assertEqual(s2, expected2, "pre-feature report (no subagent key) grew a worker split it must not have")


# ---- phase 06: `report index --text` -- one section per repo, newest first, limited, the status
# column shape-coded (glyph, not word), and the regression test for the pasted defect: a table
# row must never be directly followed by a non-blank line.

class TestIndexText(CfqTestCase):
    def setUp(self):
        super().setUp()
        # fmt_short goes through datetime.astimezone(), which reads the machine's local timezone
        # -- pinned to UTC so the expected short-date strings below are portable.
        self._orig_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._orig_tz
        time.tzset()
        super().tearDown()

    def _batch(self, repo, name, phases, started="2026-05-01T08:00:00+00:00"):
        d = self._repos_dir / repo / ".claude" / "cfq" / "impl" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.json").write_text(json.dumps({
            "repo": str(self._repos_dir / repo), "batch": name, "started": started, "phases": phases,
        }))
        return d

    def _phase(self, slug, status, finished=None, telemetry_until=None, turns=0, output=0, billable_in=None):
        p = {
            "phase": slug, "status": status, "summary": "ok",
            "deviations": [], "errors": [], "verification": "PASS", "commit": "",
        }
        if finished is not None:
            p["finished"] = finished
        if telemetry_until is not None:
            totals = {"output": output, "turns": turns}
            # `billable_in` only goes into `totals` when a caller passes it -- omitting it here is
            # exactly what a report written before phase 06 looks like on disk, no separate fixture
            # shape needed for that case.
            if billable_in is not None:
                totals["billable_in"] = billable_in
            p["telemetry"] = {"until": telemetry_until, "totals": totals}
        return p

    def _run_text(self, *extra_args):
        return self.run_cfq(
            "report", "index", "--text", *extra_args, env={"CFQ_SCAN_ROOTS": str(self._repos_dir)},
        ).stdout

    def test_two_repos_grouped_newest_group_first_and_rows_date_descending(self):
        self._batch("repo-a", "2026-05-01-one", [self._phase("01-a", "green", "2026-05-01T09:00:00+00:00")])
        self._batch("repo-a", "2026-05-02-two", [self._phase("01-a", "green", "2026-05-02T09:00:00+00:00")])
        self._batch("repo-a", "2026-05-03-three", [self._phase("01-a", "green", "2026-05-03T09:00:00+00:00")])
        self._batch("repo-b", "2026-05-10-later", [self._phase("01-a", "green", "2026-05-10T09:00:00+00:00")])

        text = self._run_text()
        self.assertEqual(text.count("### "), 2, f"expected two group headers:\n{text}")
        # repo-b's only batch is the newest overall -> its group comes first.
        self.assertLess(
            text.index("### repo-b"), text.index("### repo-a"), f"groups not newest-first:\n{text}",
        )
        # within repo-a, rows are newest-first: three, two, one.
        pos_three = text.index("2026-05-03-three")
        pos_two = text.index("2026-05-02-two")
        pos_one = text.index("2026-05-01-one")
        self.assertTrue(pos_three < pos_two < pos_one, f"rows not date-descending within group:\n{text}")

    def test_blank_line_after_every_group_table(self):
        # The regression test for the pasted defect: a Markdown renderer reads a table row
        # directly followed by a non-blank line as a further row of that same table.
        self._batch("repo-a", "2026-05-01-one", [self._phase("01-a", "green", "2026-05-01T09:00:00+00:00")])
        self._batch("repo-b", "2026-05-02-two", [self._phase("01-a", "green", "2026-05-02T09:00:00+00:00")])
        text = self._run_text()
        lines = text.split("\n")
        # Only the rows following the `|---|` separator are data rows -- the header line above it
        # also starts with `| `, and its very next line (the separator itself) is on purpose not
        # blank, so it must not be mistaken for the row this test actually checks.
        in_table = False
        checked = 0
        for i, line in enumerate(lines):
            if line.startswith("|---"):
                in_table = True
                continue
            if in_table:
                if line.startswith("| "):
                    continue
                self.assertEqual(
                    line, "", f"no blank line after the last table row of a group:\n{text}",
                )
                checked += 1
                in_table = False
        self.assertEqual(checked, 2, f"expected to check both groups' tables:\n{text}")

    def test_limit_per_repo_group(self):
        for i in range(1, 4):
            self._batch(
                "repo-a", f"2026-05-0{i}-b{i}", [self._phase("01-a", "green", f"2026-05-0{i}T09:00:00+00:00")],
            )

        default_text = self._run_text()
        self.assertEqual(
            default_text.count("| 2026-05-0"), 3, f"default limit truncated a 3-batch repo:\n{default_text}",
        )
        self.assertNotIn("more", default_text, f"default limit printed a spurious 'more' hint:\n{default_text}")

        limited = self._run_text("--limit", "2")
        self.assertEqual(limited.count("| 2026-05-0"), 2, f"--limit 2 did not truncate to 2 rows:\n{limited}")
        self.assertIn(
            "… 1 more · --limit 0 shows all", limited, f"--limit 2 missing the 'more' hint:\n{limited}",
        )

        unlimited = self._run_text("--limit", "0")
        self.assertEqual(unlimited.count("| 2026-05-0"), 3, f"--limit 0 truncated:\n{unlimited}")
        self.assertNotIn("more", unlimited, f"--limit 0 printed a spurious 'more' hint:\n{unlimited}")

    def test_glyphs_replace_status_words(self):
        self._batch("repo-a", "2026-05-01-green", [self._phase("01-a", "green", "2026-05-01T09:00:00+00:00")])
        self._batch("repo-a", "2026-05-02-red", [self._phase("01-a", "red", "2026-05-02T09:00:00+00:00")])
        self._batch("repo-a", "2026-05-03-mixed", [
            self._phase("01-a", "red", "2026-05-03T09:00:00+00:00"),
            self._phase("01-a", "green", "2026-05-03T10:00:00+00:00"),
        ])
        text = self._run_text()
        self.assertIn("✅", text, f"missing the GREEN glyph:\n{text}")
        self.assertIn("❌", text, f"missing the RED glyph:\n{text}")
        self.assertIn("⚠️", text, f"missing the MIXED glyph:\n{text}")
        self.assertNotIn("GREEN", text, f"status word GREEN still present:\n{text}")
        self.assertNotIn("RED", text, f"status word RED still present:\n{text}")
        self.assertNotIn("MIXED", text, f"status word MIXED still present:\n{text}")

    def test_rendered_marker_column_and_no_file_url(self):
        self._batch(
            "repo-a", "2026-05-01-rendered", [self._phase("01-a", "green", "2026-05-01T09:00:00+00:00")],
        )
        self._batch(
            "repo-a", "2026-05-02-unrendered", [self._phase("01-a", "green", "2026-05-02T09:00:00+00:00")],
        )
        # `rendered` now means "the portal has this batch's own data" -- simulated directly by
        # dropping the one data file `portal sync` would have written, rather than a `.html` file.
        data_dir = self._repos_dir / "repo-a" / ".claude" / "cfq" / "reports" / "data" / "batch"
        data_dir.mkdir(parents=True)
        (data_dir / "2026-05-01-rendered.impl.js").write_text("window.CFQ_DATA = {};")

        text = self._run_text()
        self.assertNotIn("file://", text, f"a file:// line leaked into the listing:\n{text}")
        rows = [l for l in text.split("\n") if l.startswith("| 2026-05-0")]
        rendered_row = next(l for l in rows if "2026-05-01-rendered" in l)
        unrendered_row = next(l for l in rows if "2026-05-02-unrendered" in l)
        rendered_cells = [c.strip() for c in rendered_row.strip("|").split("|")]
        unrendered_cells = [c.strip() for c in unrendered_row.strip("|").split("|")]
        self.assertEqual(rendered_cells[-1], "✓", f"rendered row missing its marker: {rendered_row!r}")
        self.assertEqual(unrendered_cells[-1], "", f"unrendered row should have an empty marker: {unrendered_row!r}")

    def test_date_is_the_phase_finish_not_the_batch_start(self):
        self._batch(
            "repo-a", "2026-05-01-untilphase",
            [self._phase("01-a", "green", telemetry_until="2026-05-01T15:30:00+00:00")],
            started="2026-04-01T08:00:00+00:00",
        )
        text = self._run_text()
        self.assertIn("01.05 15:30", text, f"date cell is not the phase's telemetry.until:\n{text}")
        self.assertNotIn("01.04", text, f"date cell fell back to the batch's started:\n{text}")

    def test_no_reports_sentence_unchanged(self):
        text = self._run_text().rstrip("\n")
        self.assertEqual(
            text,
            "No batch has a report yet — reports have existed only since v0.2, so older batches never got one.",
        )

    def test_turns_and_in_columns_present_between_out_and_marker(self):
        self._batch(
            "repo-a", "2026-05-01-cols",
            [self._phase(
                "01-a", "green", telemetry_until="2026-05-01T09:00:00+00:00",
                turns=7, output=12345, billable_in=6789,
            )],
        )
        text = self._run_text()
        header = next(l for l in text.split("\n") if l.startswith("| Batch"))
        cols = [c.strip() for c in header.strip("|").split("|")]
        self.assertEqual(cols.index("Turns"), cols.index("Out") + 1, f"Turns not right after Out:\n{header}")
        self.assertEqual(cols.index("In"), cols.index("Turns") + 1, f"In not right after Turns:\n{header}")
        self.assertEqual(cols.index("📄"), cols.index("In") + 1, f"the marker column moved:\n{header}")

        row = next(l for l in text.split("\n") if "2026-05-01-cols" in l)
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(cells[cols.index("Turns")], "7", f"Turns cell wrong:\n{row}")
        self.assertEqual(cells[cols.index("In")], "7k", f"In cell not fmt_tokens-formatted:\n{row}")

    def test_pre_phase_06_report_in_renders_dash_not_zero(self):
        self._batch(
            "repo-a", "2026-05-01-preexisting",
            [self._phase("01-a", "green", telemetry_until="2026-05-01T09:00:00+00:00", turns=3, output=500)],
        )
        text = self._run_text()
        header = next(l for l in text.split("\n") if l.startswith("| Batch"))
        cols = [c.strip() for c in header.strip("|").split("|")]
        row = next(l for l in text.split("\n") if "2026-05-01-preexisting" in l)
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(
            cells[cols.index("In")], "–", f"pre-phase-06 report must render '–' for In, not 0:\n{row}",
        )
        self.assertEqual(len(cells), len(cols), f"row column count drifted from header:\n{row}")

    def test_every_row_column_count_matches_header(self):
        # Three distinct fixture shapes at once, so a ragged row from any one of them cannot slip
        # through: a phase-06 report, a pre-phase-06 report, and a phase with no telemetry totals
        # key at all.
        self._batch(
            "repo-a", "2026-05-01-full",
            [self._phase(
                "01-a", "green", telemetry_until="2026-05-01T09:00:00+00:00",
                turns=1, output=100, billable_in=200,
            )],
        )
        self._batch(
            "repo-a", "2026-05-02-legacy",
            [self._phase("01-a", "green", telemetry_until="2026-05-02T09:00:00+00:00", turns=2, output=200)],
        )
        self._batch("repo-a", "2026-05-03-notelemetry", [self._phase("01-a", "green")])
        text = self._run_text()
        lines = text.split("\n")
        header = next(l for l in lines if l.startswith("| Batch"))
        expected_cols = len(header.strip("|").split("|"))
        data_rows = [l for l in lines if l.startswith("| 2026-05-0")]
        self.assertEqual(len(data_rows), 3, f"expected all three fixture rows:\n{text}")
        for row in data_rows:
            self.assertEqual(
                len(row.strip("|").split("|")), expected_cols, f"ragged row, column count drifted:\n{row}",
            )


# ---- phase 01: derivation helpers cfq_report.py's detail/index rendering all funnel through --
# pure functions over a phase dict, no batch directory, no subprocess.

class TestDerivations(unittest.TestCase):
    def setUp(self):
        # fmt_short goes through datetime.astimezone(), which reads the machine's
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
        self.assertEqual(cfq_report.fmt_short("2026-09-21T13:16:49.329Z"), "21.09 13:16")

    def test_parse_ts_offset_timestamp(self):
        self.assertEqual(cfq_report.fmt_short("2026-01-01T10:30:00+02:00"), "01.01 08:30")

    def test_parse_ts_empty_string_returns_none_and_empty_display(self):
        self.assertIsNone(cfq_report.parse_ts(""))
        self.assertEqual(cfq_report.fmt_short(""), "")

    def test_parse_ts_malformed_returns_none_not_an_exception(self):
        self.assertIsNone(cfq_report.parse_ts("not-a-date"))
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


# ---- cfq_lib.markdown's base subset (the renderer batch 040 phase 01 split out of this module)
# -- still live, used by cfq_portal.py's pre-rendered phase-file/queue-entry bodies. Pure
# functions over literal strings, no files, no project-specific nouns. `MarkdownExtensionTest` in
# tests/test_portal.py covers the extensions cfq_portal.py added on top (keep_h1, ordered lists);
# this class covers the base subset this module used to render itself.

class TestMarkdownSubset(unittest.TestCase):
    # -- md_min: routine / structural cases --------------------------------------------------

    def test_routine_heading_paragraph_and_list(self):
        out = cfq_lib_markdown.md_min(
            "## Heading\n\nA paragraph.\n\n- one\n- two\n- three\n"
        )
        self.assertIn("<h3>Heading</h3>", out)
        self.assertIn("<p>A paragraph.</p>", out)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<li>two</li>", out)
        self.assertIn("<li>three</li>", out)

    def test_wrapped_bullet_continuation_stays_one_li_not_a_paragraph(self):
        out = cfq_lib_markdown.md_min("- first line of the item\n  wraps onto this line\n")
        self.assertEqual(out.count("<li>"), 1)
        self.assertNotIn("<p>", out)
        self.assertIn("<li>first line of the item wraps onto this line</li>", out)

    # -- md_inline -----------------------------------------------------------------------------

    def test_inline_bold_and_code(self):
        self.assertEqual(cfq_lib_markdown.md_inline("**bold**"), "<strong>bold</strong>")
        self.assertEqual(cfq_lib_markdown.md_inline("`code`"), "<code>code</code>")

    def test_inline_backtick_span_wins_over_bold_inside_it(self):
        out = cfq_lib_markdown.md_inline("`a **b** c`")
        self.assertNotIn("<strong>", out)
        self.assertEqual(out, "<code>a **b** c</code>")

    # -- escaping --------------------------------------------------------------------------------

    def test_escaping_happens_before_this_function_is_reached(self):
        # md_min escapes each emitted value itself (via esc()) -- feeding it raw HTML must come
        # out neutralised, never as a literal live tag.
        out = cfq_lib_markdown.md_min("A line with <script>alert(1)</script> in it.")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script", out)

    # -- edge cases ------------------------------------------------------------------------------

    def test_empty_string_returns_empty(self):
        self.assertEqual(cfq_lib_markdown.md_min(""), "")

    def test_only_blank_lines_returns_empty(self):
        self.assertEqual(cfq_lib_markdown.md_min("\n\n\n"), "")

    def test_single_hash_title_alone_is_skipped_entirely(self):
        out = cfq_lib_markdown.md_min("# Batch Context\n")
        self.assertEqual(out, "")

    # -- fall-through: outside the documented subset ------------------------------------------

    def test_blockquote_and_table_line_fall_back_to_paragraph_text(self):
        out = cfq_lib_markdown.md_min("> a quote\n\n| a | table |\n")
        self.assertNotIn("<blockquote", out)
        self.assertNotIn("<table", out)
        self.assertIn("<p>", out)
        self.assertIn("&gt; a quote", out)
        self.assertIn("| a | table |", out)


if __name__ == "__main__":
    unittest.main()
