"""Self-test for `cfq_lib/portal_hook.py`: every mutating verb's `portal sync` side effect,
wired at zero model-token cost -- see `04-portal-sync-triggers.md`'s Affected Files list.

The suite's own default (`tests/cfq_testlib.py`'s `_base_env()`) sets `CFQ_PORTAL_SYNC=0` so
every *other* test's directory-content assertions stay exactly as they were before this phase --
only this module opts back in, per test, via `env=ON`.
"""

import json
import subprocess

from cfq_testlib import CfqTestCase

import cfq_portal  # noqa: E402

ON = {"CFQ_PORTAL_SYNC": "1"}


class PortalTriggersTest(CfqTestCase):
    def _new_repo(self, name):
        repo = self.make_repo(name)
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
        return repo

    def _data(self, repo):
        return repo / ".claude" / "cfq" / "reports" / "data"

    def _payload(self, path):
        return cfq_portal.read_data_payload(path)

    # ---- routine: park -> ready -> lock acquire -> phase commit -> finish ----------------------

    def test_routine_lifecycle_keeps_the_portal_current(self):
        home = self._repos_dir / "home-routine"
        home.mkdir()
        repo = self._new_repo("repo-routine")
        batch_name = "2026-01-01-widget"

        park = self.run_cfq("park", str(repo), batch_name, "normal", home=home, env=ON, check=True)
        batch_dir = repo / ".claude" / "cfq" / "impl" / batch_name
        self.assertEqual(park.stdout.strip(), str(batch_dir))

        queue_path = self._data(repo) / "queue.js"
        plan_path = self._data(repo) / "batch" / f"{batch_name}.js"
        self.assertTrue(queue_path.is_file(), "park should trigger a portal sync")
        self.assertTrue(plan_path.is_file(), "park should write the batch's own data file")
        queue = self._payload(queue_path)
        self.assertIn(batch_name, [b["name"] for b in queue["batches"]], "queue.js should list the batch")

        self.run_cfq("batch", "ready", str(batch_dir), home=home, env=ON, check=True)
        self.assertFalse((batch_dir / ".planning").exists(), "ready should remove the marker")

        self.run_cfq("lock", "acquire", str(repo), batch_name, home=home, env=ON, check=True)
        self.assertTrue(queue_path.is_file(), "lock acquire should re-sync without erroring")

        (batch_dir / "01-a.md").write_text("# A phase\n\n## Size\n\nS\n")
        (repo / "feature.txt").write_text("built\n")
        subprocess.run(["git", "-C", str(repo), "add", "feature.txt"], check=True)
        phase_file = batch_dir / "_phase.json"
        phase_file.write_text(json.dumps({
            "phase": "01-a", "status": "green", "summary": "ok",
            "deviations": [], "errors": [], "verification": "tests -> PASS", "commit": "",
        }))
        message_file = batch_dir / "_message.txt"
        message_file.write_text("Implement the phase\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n")

        commit = self.run_cfq(
            "phase", "commit", str(batch_dir), str(phase_file), str(message_file),
            home=home, env=ON, check=True,
        )
        self.assertEqual(self.json_out(commit)["status"], "OK")

        impl_path = self._data(repo) / "batch" / f"{batch_name}.js"
        self.assertTrue(impl_path.is_file(), "phase commit should write the batch's own data file")
        impl = self._payload(impl_path)
        self.assertEqual([p["slug"] for p in impl["phases"]], ["01-a"])
        self.assertEqual([len(p["attempts"]) for p in impl["phases"]], [1])

        finish = self.run_cfq(
            "finish", str(repo), str(batch_dir), "v0.1-widget", home=home, env=ON, check=True,
        )
        self.json_out(finish)

        queue = self._payload(queue_path)
        row = next(b for b in queue["batches"] if b["name"] == batch_name)
        self.assertEqual(row["status"], "done", "finish should re-sync the batch as done")

    # ---- routine: note plan -> entry appears; note close -> entry removed ----------------------

    def test_routine_note_plan_then_close(self):
        home = self._repos_dir / "home-note"
        home.mkdir()
        repo = self.make_repo("repo-note")
        body = self._repos_dir / "finding-body.md"
        body.write_text("# A finding\n\nSome detail worth writing down.\n")

        self.run_cfq("note", "plan", str(repo), "a-finding", str(body), home=home, env=ON, check=True)

        entry_dir = self._data(repo) / "entry"
        self.assertTrue(entry_dir.is_dir(), "note plan should trigger a portal sync")
        entry_files = list(entry_dir.glob("plan-*.js"))
        self.assertEqual(len(entry_files), 1, "note plan should write exactly one entry data file")

        listed = json.loads(self.run_cfq("note", "list", str(repo), home=home, check=True).stdout)
        entry_path = listed[0]["path"]

        self.run_cfq(
            "note", "close", str(repo), entry_path, "--reason", "done elsewhere",
            home=home, env=ON, check=True,
        )
        # a closed entry stays in the archive: same data file, now marked done with its reason
        closed_files = list(entry_dir.glob("plan-*.js"))
        self.assertEqual(len(closed_files), 1, "note close should keep the closed entry's data file")
        closed = self._payload(closed_files[0])
        self.assertEqual(closed["state"], "done")
        self.assertIn("done elsewhere", closed["closed"])

    # ---- edge: htmlReport=false turns every automatic sync off, no reports/ at all -------------

    def test_edge_html_report_false_writes_nothing(self):
        home = self._repos_dir / "home-off"
        (home / ".claude" / "cfq").mkdir(parents=True)
        (home / ".claude" / "cfq" / "settings.json").write_text(json.dumps({"htmlReport": False}))
        repo = self.make_repo("repo-off")

        self.run_cfq("park", str(repo), "2026-01-01-off", "normal", home=home, env=ON, check=True)

        self.assertFalse(
            (repo / ".claude" / "cfq" / "reports").exists(),
            "htmlReport=false must leave reports/ entirely unwritten",
        )

    # ---- must hold: a portal sync failure never changes the triggering verb's own output -------

    def test_must_hold_portal_failure_leaves_the_triggering_verb_untouched(self):
        home = self._repos_dir / "home-fail"
        home.mkdir()
        batch_name = "2026-01-01-blocked"

        baseline_repo = self.make_repo("repo-fail-baseline")
        baseline = self.run_cfq(
            "park", str(baseline_repo), batch_name, "normal", home=home, check=True,
        )  # suite default CFQ_PORTAL_SYNC=0 -- a run with the portal fully off.

        repo = self.make_repo("repo-fail")
        reports_dir = repo / ".claude" / "cfq" / "reports"
        reports_dir.mkdir(parents=True)
        reports_dir.chmod(0o555)
        try:
            broken = self.run_cfq("park", str(repo), batch_name, "normal", home=home, env=ON)
        finally:
            reports_dir.chmod(0o755)

        self.assertEqual(broken.returncode, baseline.returncode)
        self.assertEqual(
            broken.stdout.replace(str(repo), str(baseline_repo)), baseline.stdout,
            "a portal sync failure must never change the triggering verb's own stdout",
        )
        self.assertIn("portal sync failed (non-fatal)", broken.stderr)

    # ---- telemetry settle rides along with every mutation, ahead of the portal sync -----------

    def _repo_with_provisional_record(self, name):
        """A repo whose finished-session telemetry record (transcript long gone) is still
        provisional, as `phase commit` leaves it."""
        repo = self.make_repo(name)
        batch_dir = repo / ".claude" / "cfq" / "impl" / "2026-01-01-widget"
        batch_dir.mkdir(parents=True)
        record = {
            "schema": 3, "kind": "phase", "phase": "01-a", "batch": "2026-01-01-widget",
            "repo": str(repo), "session_id": "ended-session", "since": "", "settled": False, "rev": 1,
            "totals": {"turns": 2},
        }
        (batch_dir / "report.json").write_text(json.dumps({
            "repo": str(repo), "batch": "2026-01-01-widget", "started": "2026-01-01T00:00:00Z",
            "phases": [{"phase": "01-a", "status": "green", "summary": "ok", "telemetry": record}],
        }))
        return repo, batch_dir

    def _telemetry_of(self, batch_dir):
        return json.loads((batch_dir / "report.json").read_text())["phases"][0]["telemetry"]

    def _note_plan(self, repo, home, env=ON):
        body = self._repos_dir / f"body-{repo.name}.md"
        body.write_text("# A finding\n\nSome detail.\n")
        return self.run_cfq("note", "plan", str(repo), "a-finding", str(body), home=home, env=env)

    def test_mutating_verb_settles_telemetry_before_the_portal_sync(self):
        home = self._repos_dir / "home-settle"
        home.mkdir()
        repo, batch_dir = self._repo_with_provisional_record("repo-settle")

        proc = self._note_plan(repo, home)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        self.assertEqual(self._telemetry_of(batch_dir)["settled"], True)
        batch = self._payload(self._data(repo) / "batch" / "2026-01-01-widget.js")
        self.assertTrue(
            batch["phases"][0]["attempts"][0]["settled"],
            "the portal sync that follows must already see the settled record",
        )

    def test_settle_runs_with_html_report_false(self):
        home = self._repos_dir / "home-settle-off"
        (home / ".claude" / "cfq").mkdir(parents=True)
        (home / ".claude" / "cfq" / "settings.json").write_text(json.dumps({"htmlReport": False}))
        repo, batch_dir = self._repo_with_provisional_record("repo-settle-off")

        self.assertEqual(self._note_plan(repo, home).returncode, 0)

        self.assertEqual(self._telemetry_of(batch_dir)["settled"], True)
        self.assertFalse((repo / ".claude" / "cfq" / "reports").exists(), "no portal output at all")

    def test_portal_sync_off_switch_suppresses_settle_too(self):
        home = self._repos_dir / "home-settle-env"
        home.mkdir()
        repo, batch_dir = self._repo_with_provisional_record("repo-settle-env")

        self.assertEqual(self._note_plan(repo, home, env={"CFQ_PORTAL_SYNC": "0"}).returncode, 0)

        self.assertEqual(self._telemetry_of(batch_dir)["settled"], False)

    def test_failing_settle_leaves_the_verbs_exit_code_and_stdout_untouched(self):
        home = self._repos_dir / "home-settle-fail"
        home.mkdir()
        baseline_repo = self.make_repo("repo-settle-baseline")
        baseline = self._note_plan(baseline_repo, home, env={"CFQ_PORTAL_SYNC": "0"})

        repo, batch_dir = self._repo_with_provisional_record("repo-settle-fail")
        batch_dir.chmod(0o555)  # settle cannot write report.json back -> it exits non-zero
        try:
            broken = self._note_plan(repo, home)
        finally:
            batch_dir.chmod(0o755)

        self.assertEqual(broken.returncode, baseline.returncode)
        self.assertEqual(broken.stdout.replace(str(repo), str(baseline_repo)), baseline.stdout)
        self.assertIn("telemetry settle failed (non-fatal)", broken.stderr)
