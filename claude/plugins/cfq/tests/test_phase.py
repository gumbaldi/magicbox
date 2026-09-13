"""Self-test for scripts/cfq_phase.py: `record` and `reopen` as the one transactional call that
replaces the improvised "move the file, then remember to call report append" sequence.
"""

import json
import pathlib
import unittest

from cfq_testlib import CfqTestCase


class TestPhase(CfqTestCase):
    def _batch(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_phase_md(self, batch, slug):
        (batch / f"{slug}.md").write_text(f"# Phase {slug}\n")

    def _write_report(self, batch, phases):
        (batch / "report.json").write_text(json.dumps(
            {"repo": "", "batch": batch.name, "started": "2026-01-01T10:00:00+01:00", "phases": phases},
        ) + "\n")

    def _phase_file(self, batch, obj):
        f = batch / "_phase.json"
        f.write_text(json.dumps(obj))
        return f

    def _report_json(self, batch):
        return json.loads((batch / "report.json").read_text())

    def test_record_green_moves_file_and_appends(self):
        batch = self._batch("2026-02-01-demo")
        self._write_phase_md(batch, "03-some-slug")
        self._write_report(batch, [])
        pf = self._phase_file(batch, {
            "phase": "03-some-slug", "status": "green", "summary": "ok",
            "deviations": [], "errors": [], "verification": "tests -> PASS", "commit": "",
        })

        self.assertFalse((batch / "done").exists(), "done/ should not pre-exist")
        proc = self.run_cfq("phase", "record", str(batch), str(pf), "--no-telemetry")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        done_path = batch / "done" / "03-some-slug.md"
        self.assertTrue(done_path.is_file(), "green record should move the .md file into done/")
        self.assertFalse((batch / "03-some-slug.md").exists(), "the open .md file should be gone")
        self.assertEqual(proc.stdout.strip(), str(done_path))

        phases = self._report_json(batch)["phases"]
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0]["phase"], "03-some-slug")
        self.assertEqual(phases[0]["status"], "green")

    def test_record_red_appends_without_moving(self):
        batch = self._batch("2026-02-02-demo")
        self._write_phase_md(batch, "04-other-slug")
        self._write_report(batch, [])
        pf = self._phase_file(batch, {
            "phase": "04-other-slug", "status": "red", "summary": "fehlgeschlagen",
            "deviations": [], "errors": ["tests failed"], "verification": "tests -> FAIL", "commit": "",
        })

        proc = self.run_cfq("phase", "record", str(batch), str(pf), "--no-telemetry")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        root_path = batch / "04-other-slug.md"
        self.assertTrue(root_path.is_file(), "red record must leave the .md file in place")
        self.assertFalse((batch / "done").exists(), "red record must not create done/")
        self.assertEqual(proc.stdout.strip(), str(root_path))

        phases = self._report_json(batch)["phases"]
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0]["status"], "red")

    def test_record_already_recorded(self):
        batch = self._batch("2026-02-03-demo")
        (batch / "done").mkdir()
        (batch / "done" / "05-slug.md").write_text("# Phase 05\n")
        self._write_report(batch, [{"phase": "05-slug", "status": "green", "commit": "abc"}])
        pf = self._phase_file(batch, {"phase": "05-slug", "status": "green", "summary": "again"})

        before = (batch / "report.json").read_text()
        proc = self.run_cfq("phase", "record", str(batch), str(pf), "--no-telemetry")
        self.assertNotEqual(proc.returncode, 0, "recording an already-done phase must fail")
        err = json.loads(proc.stderr)
        self.assertEqual(err.get("status"), "ALREADY_RECORDED")
        after = (batch / "report.json").read_text()
        self.assertEqual(before, after, "ledger must stay unchanged for ALREADY_RECORDED")

    def test_reopen_moves_back_and_marks_last_matching_entry(self):
        batch = self._batch("2026-02-04-demo")
        (batch / "done").mkdir()
        (batch / "done" / "06-slug.md").write_text("# Phase 06\n")
        self._write_report(batch, [
            {"phase": "06-slug", "status": "green", "commit": "aaa1111"},
            {"phase": "06-slug", "status": "green", "commit": "bbb2222"},
        ])

        proc = self.run_cfq("phase", "reopen", str(batch), "06-slug")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        root_path = batch / "06-slug.md"
        self.assertTrue(root_path.is_file(), "reopen must move the file back to the batch root")
        self.assertFalse((batch / "done" / "06-slug.md").exists())
        self.assertEqual(proc.stdout.strip(), str(root_path))

        phases = self._report_json(batch)["phases"]
        self.assertNotIn("reopened", phases[0], "only the last matching entry gets marked")
        self.assertIn("reopened", phases[1])
        self.assertEqual(phases[1]["status"], "green", "reopen must not touch status")
        self.assertEqual(phases[1]["commit"], "bbb2222", "reopen must not touch commit")

    def test_reopen_not_done(self):
        batch = self._batch("2026-02-05-demo")
        self._write_report(batch, [])

        proc = self.run_cfq("phase", "reopen", str(batch), "07-slug")
        self.assertNotEqual(proc.returncode, 0, "reopening a phase that isn't in done/ must fail")
        err = json.loads(proc.stderr)
        self.assertEqual(err.get("status"), "NOT_DONE")

    def test_record_rejects_bare_phase_number(self):
        batch = self._batch("2026-02-06-demo")
        self._write_phase_md(batch, "08-slug")
        pf = self._phase_file(batch, {"phase": "08", "status": "green", "summary": "x"})

        proc = self.run_cfq("phase", "record", str(batch), str(pf), "--no-telemetry")
        self.assertNotEqual(proc.returncode, 0, "record should reject a bare phase number")
        self.assertIn("full phase slug", proc.stderr)
        self.assertFalse((batch / "report.json").exists(), "nothing should be written")
        self.assertTrue((batch / "08-slug.md").is_file(), "nothing should be moved")
        self.assertFalse((batch / "done").exists())

    def test_record_transaction_rolls_back_on_move_failure(self):
        batch = self._batch("2026-02-07-demo")
        self._write_phase_md(batch, "09-slug")
        self._write_report(batch, [{"phase": "01-prior", "status": "green", "commit": "zzz"}])
        # A plain file named "done" makes mkdir(parents=True, exist_ok=True) fail the same way a
        # read-only done/ directory would, portably.
        (batch / "done").write_text("not a directory\n")

        before = (batch / "report.json").read_text()
        pf = self._phase_file(batch, {"phase": "09-slug", "status": "green", "summary": "x"})
        proc = self.run_cfq("phase", "record", str(batch), str(pf), "--no-telemetry")

        self.assertNotEqual(proc.returncode, 0)
        after = (batch / "report.json").read_text()
        self.assertEqual(before, after, "report.json must be byte-identical after a failed move")
        self.assertTrue((batch / "09-slug.md").is_file(), "the .md file must stay in place")


if __name__ == "__main__":
    unittest.main()
