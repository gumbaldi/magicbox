"""Self-test for `cfq batch verify`/`cfq batch recover` (scripts/cfq_lib/consistency.py,
scripts/cfq_batch_id.py) -- pinning the trailer parsing and the cross-source comparison against a
real git repo with hand-written commits carrying `CFQ-*` trailers, rather than exploring it in a
shell. See `.batch-context.md`: this is the fix for the incident where `done/` disappeared and the
batch went silently invisible (`impl/014-2026-09-03-port-core-scripts-to-python/` in this repo).
"""

import json
import os
import subprocess
import time
import unittest

from cfq_testlib import CfqTestCase


class BatchVerifyTest(CfqTestCase):
    def _repo(self, name):
        return self.make_repo(name)

    def _batch_dir(self, repo, batch):
        return repo / ".claude" / "cfq" / "impl" / batch

    def _write_report(self, batch_dir, phases):
        batch_dir.mkdir(parents=True, exist_ok=True)
        (batch_dir / "report.json").write_text(json.dumps({
            "repo": "", "batch": batch_dir.name, "started": "2026-01-01T00:00:00+00:00",
            "phases": phases,
        }))

    def _report(self, batch_dir):
        return json.loads((batch_dir / "report.json").read_text())

    def _commit_phase(self, repo, batch, phase, message="work"):
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m",
             f"{message}\n\nCFQ-Batch: {batch}\nCFQ-Phase: {phase}\nCFQ-Phase-Status: green\n"],
            check=True,
        )
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()

    def _changelog_target(self, repo):
        return repo / ".claude" / "cfq" / "changelog.yml"

    def _write_changelog_block(self, repo, batch, status, phases=None):
        target = self._changelog_target(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "- batchNumber: null", f"  batch: {batch}", f"  branch: cfq/{batch}",
            f"  status: {status}", "  legacy: true",
        ]
        if phases:
            lines.append("  phases:")
            for phase, phase_status, summary in phases:
                lines.append(f'    - phase: "{phase}"')
                lines.append(f'      status: "{phase_status}"')
                lines.append(f'      summary: "{summary}"')
        with open(target, "a") as f:
            f.write("\n".join(lines) + "\n")

    def _verify(self, repo, batch=None):
        args = ["batch", "verify", str(repo), "--json"]
        if batch is not None:
            args += ["--batch", batch]
        return self.run_cfq(*args)

    def _findings(self, repo, batch=None):
        return self.json_out(self._verify(repo, batch))["findings"]

    def _batch_level_codes(self, findings):
        return sorted(f["code"] for f in findings if f["phase"] is None)

    def _recover(self, repo, batch, dry_run=False):
        args = ["batch", "recover", str(repo), "--batch", batch]
        if dry_run:
            args.append("--dry-run")
        return self.run_cfq(*args)

    # ---- routine: everything agrees -----------------------------------------------------------

    def test_routine_healthy_batch_has_no_findings(self):
        repo = self._repo("healthy")
        batch = "2026-04-01-healthy"
        batch_dir = self._batch_dir(repo, batch)
        (batch_dir / "done").mkdir(parents=True)
        (batch_dir / "03-c.md").write_text("# open\n")

        sha1 = self._commit_phase(repo, batch, "01-a")
        (batch_dir / "done" / "01-a.md").write_text("# 01-a\n")
        sha2 = self._commit_phase(repo, batch, "02-b")
        (batch_dir / "done" / "02-b.md").write_text("# 02-b\n")

        self._write_report(batch_dir, [
            {"phase": "01-a", "status": "green", "commit": sha1},
            {"phase": "02-b", "status": "green", "commit": sha2},
        ])
        self._write_changelog_block(repo, batch, "in-progress", phases=[
            ("01-a", "green", "did a"), ("02-b", "green", "did b"),
        ])

        proc = self._verify(repo, batch)
        self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr} stdout={proc.stdout}")
        self.assertEqual(self.json_out(proc)["findings"], [], msg=proc.stdout)

    # ---- the 014 shape: archived-but-not-moved ------------------------------------------------

    def test_complete_batch_with_empty_done_reports_and_recovers(self):
        repo = self._repo("archived-shape")
        batch = "2026-04-02-fourteen-shape"
        batch_dir = self._batch_dir(repo, batch)
        batch_dir.mkdir(parents=True)

        phases = []
        shas = {}
        for slug in ("01-a", "02-b", "03-c", "04-d", "05-e"):
            sha = self._commit_phase(repo, batch, slug)
            shas[slug] = sha
            phases.append({"phase": slug, "status": "green", "commit": sha})
        self._write_report(batch_dir, phases)

        proc = self._verify(repo, batch)
        self.assertNotEqual(proc.returncode, 0)
        findings = self.json_out(proc)["findings"]
        self.assertEqual(self._batch_level_codes(findings), ["COMPLETE_NOT_ARCHIVED"], msg=findings)
        self.assertEqual(
            sorted(f["phase"] for f in findings if f["code"] == "DONE_FILE_MISSING"),
            ["01-a", "02-b", "03-c", "04-d", "05-e"],
            msg=findings,
        )

        # recover: no trash entries exist for any of these -> every DONE_FILE_MISSING becomes
        # TEXT_UNRECOVERABLE, and the COMPLETE_NOT_ARCHIVED repair only prints the finish command.
        rproc = self._recover(repo, batch)
        self.assertNotEqual(rproc.returncode, 0, msg=rproc.stdout)
        self.assertIn(f"finish {repo} {batch_dir}", rproc.stdout, msg=rproc.stdout)
        for slug in shas:
            self.assertIn(f"TEXT_UNRECOVERABLE {slug}", rproc.stdout, msg=rproc.stdout)

        after = self._findings(repo, batch)
        self.assertEqual(
            sorted(f["code"] for f in after if f["phase"] is not None),
            ["TEXT_UNRECOVERABLE"] * 5, msg=after,
        )
        self.assertFalse((batch_dir / "done").is_dir() and any((batch_dir / "done").iterdir()),
                          msg="recover must never write a phase .md file back")

    # ---- ledger loss: report.json wiped, trailers intact ------------------------------------

    def test_recover_reconstructs_missing_ledger_entries(self):
        repo = self._repo("ledger-loss")
        batch = "2026-04-03-ledger-loss"
        batch_dir = self._batch_dir(repo, batch)
        (batch_dir / "done").mkdir(parents=True)
        (batch_dir / "04-open.md").write_text("# open\n")

        shas = {}
        for slug in ("01-a", "02-b", "03-c"):
            shas[slug] = self._commit_phase(repo, batch, slug, message=f"finish {slug}")
            (batch_dir / "done" / f"{slug}.md").write_text(f"# {slug}\n")
        self._write_report(batch_dir, [])  # the ledger loss: reset to empty

        findings = self._findings(repo, batch)
        self.assertEqual(
            sorted(f["phase"] for f in findings), ["01-a", "02-b", "03-c"], msg=findings,
        )
        self.assertTrue(all(f["code"] == "LEDGER_MISSING_PHASE" for f in findings), msg=findings)

        # --dry-run must not write anything.
        dry = self._recover(repo, batch, dry_run=True)
        self.assertEqual(self._report(batch_dir)["phases"], [], msg="dry-run must not touch report.json")
        self.assertIn("LEDGER_MISSING_PHASE", dry.stdout)

        rproc = self._recover(repo, batch)
        self.assertEqual(rproc.returncode, 0, msg=rproc.stdout)

        phases = {p["phase"]: p for p in self._report(batch_dir)["phases"]}
        for slug, sha in shas.items():
            self.assertIn(slug, phases, msg=phases)
            self.assertEqual(phases[slug]["status"], "green")
            self.assertEqual(phases[slug]["commit"], sha)
            self.assertTrue(phases[slug]["recovered"])
            self.assertNotIn("deviations", phases[slug], "never fabricate a deviations array")

        self.assertEqual(self._findings(repo, batch), [], msg="report.json is fully reconstructed now")

    # ---- stale .planning marker --------------------------------------------------------------

    def test_stale_planning_flagged_and_removed(self):
        repo = self._repo("stale-planning")
        batch = "2026-04-04-stale-planning"
        batch_dir = self._batch_dir(repo, batch)
        batch_dir.mkdir(parents=True)
        for slug in ("01-a", "02-b", "03-c", "04-d"):
            (batch_dir / f"{slug}.md").write_text("# open\n")
        marker = batch_dir / ".planning"
        marker.touch()
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(marker, (two_days_ago, two_days_ago))

        findings = self._findings(repo, batch)
        self.assertEqual([f["code"] for f in findings], ["STALE_PLANNING"], msg=findings)

        rproc = self._recover(repo, batch)
        self.assertEqual(rproc.returncode, 0, msg=rproc.stdout)
        self.assertFalse(marker.exists(), "recover must remove a stale .planning marker")
        self.assertEqual(self._findings(repo, batch), [])

    def test_fresh_planning_marker_is_not_flagged(self):
        repo = self._repo("fresh-planning")
        batch = "2026-04-05-fresh-planning"
        batch_dir = self._batch_dir(repo, batch)
        batch_dir.mkdir(parents=True)
        (batch_dir / "01-a.md").write_text("# open\n")
        (batch_dir / ".planning").touch()  # written "just now"

        findings = self._findings(repo, batch)
        self.assertEqual(findings, [], msg="an actively-planning batch must not be flagged stale")

    # ---- a file in done/ nobody remembers ------------------------------------------------------

    def test_done_file_unrecorded(self):
        repo = self._repo("unrecorded")
        batch = "2026-04-06-unrecorded"
        batch_dir = self._batch_dir(repo, batch)
        (batch_dir / "done").mkdir(parents=True)
        (batch_dir / "done" / "01-mystery.md").write_text("# mystery\n")

        findings = self._findings(repo, batch)
        self.assertEqual(
            [(f["code"], f["phase"]) for f in findings], [("DONE_FILE_UNRECORDED", "01-mystery")],
            msg=findings,
        )

    # ---- text truly gone: trash restore vs. permanent loss ------------------------------------

    def test_recover_restores_done_file_from_trash(self):
        repo = self._repo("trash-restore")
        batch = "2026-04-07-trash-restore"
        batch_dir = self._batch_dir(repo, batch)
        (batch_dir / "done").mkdir(parents=True)
        (batch_dir / "02-open.md").write_text("# still open\n")  # keeps COMPLETE_NOT_ARCHIVED out of it
        done_file = batch_dir / "done" / "01-a.md"
        done_file.write_text("# 01-a\n")
        sha = self._commit_phase(repo, batch, "01-a")
        self._write_report(batch_dir, [{"phase": "01-a", "status": "green", "commit": sha}])

        self.run_cfq("trash", "put", str(repo), str(done_file), check=True)
        self.assertFalse(done_file.exists())

        findings = self._findings(repo, batch)
        self.assertEqual([f["code"] for f in findings], ["DONE_FILE_MISSING"], msg=findings)

        rproc = self._recover(repo, batch)
        self.assertEqual(rproc.returncode, 0, msg=rproc.stdout)
        self.assertTrue(done_file.is_file(), "recover should have restored the file from cfq trash")
        self.assertIn("restored from trash", rproc.stdout)
        self.assertEqual(self._findings(repo, batch), [])

    def test_recover_marks_text_unrecoverable_when_trash_is_empty(self):
        repo = self._repo("no-trash")
        batch = "2026-04-08-no-trash"
        batch_dir = self._batch_dir(repo, batch)
        batch_dir.mkdir(parents=True)
        (batch_dir / "02-open.md").write_text("# still open\n")  # keeps COMPLETE_NOT_ARCHIVED out of it
        sha = self._commit_phase(repo, batch, "01-a")
        self._write_report(batch_dir, [{"phase": "01-a", "status": "green", "commit": sha}])
        (batch_dir / "done").mkdir()  # exists, but 01-a.md is simply gone, never trashed

        findings = self._findings(repo, batch)
        self.assertEqual(
            [(f["code"], f["phase"]) for f in findings], [("DONE_FILE_MISSING", "01-a")], msg=findings,
        )

        rproc = self._recover(repo, batch)
        self.assertNotEqual(rproc.returncode, 0)
        self.assertIn("TEXT_UNRECOVERABLE 01-a", rproc.stdout, msg=rproc.stdout)
        self.assertFalse((batch_dir / "done" / "01-a.md").exists(), "recover must never fabricate the file")
        self.assertEqual(list((batch_dir / "done").iterdir()), [], "done/ must stay empty")

        # the finding stays TEXT_UNRECOVERABLE from here on, not DONE_FILE_MISSING again.
        after = self._findings(repo, batch)
        self.assertEqual(
            [(f["code"], f["phase"]) for f in after], [("TEXT_UNRECOVERABLE", "01-a")], msg=after,
        )

    # ---- verify with no --batch scans every open batch in the repo ----------------------------

    def test_verify_no_batch_scans_every_open_batch(self):
        repo = self._repo("scan-all")
        batch_a = "2026-04-09-a"
        batch_b = "2026-04-10-b"
        dir_a = self._batch_dir(repo, batch_a)
        dir_b = self._batch_dir(repo, batch_b)
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_b / "01-a.md").write_text("# open\n")
        marker = dir_b / ".planning"
        marker.touch()
        two_days_ago = time.time() - 2 * 24 * 3600
        os.utime(marker, (two_days_ago, two_days_ago))
        sha = self._commit_phase(repo, batch_a, "01-a")
        self._write_report(dir_a, [{"phase": "01-a", "status": "green", "commit": sha}])

        proc = self._verify(repo)
        self.assertNotEqual(proc.returncode, 0)
        findings = self.json_out(proc)["findings"]
        batches_seen = {f["batch"] for f in findings}
        self.assertEqual(batches_seen, {batch_a, batch_b}, msg=findings)


if __name__ == "__main__":
    unittest.main()
