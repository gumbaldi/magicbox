"""Migrated from test-finish.sh.

Self-test for scripts/cfq-finish.sh -- the batch-done sequence: move into impl/done, release the
lock unconditionally (even on a mid-sequence changelog failure), skip cleanly when the changelog is
disabled or no planning snapshot exists, and gate report.html rendering on htmlReport.
"""

import json
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from cfq_testlib import CfqTestCase, PLUGIN_ROOT, SCRIPTS_DIR

import cfq_changelog  # noqa: E402
import cfq_finish  # noqa: E402
from cfq_lib import proc as proc_lib  # noqa: E402

# The suite's own default (`tests/cfq_testlib.py`'s `_base_env()`) sets `CFQ_PORTAL_SYNC=0` so
# every other test's directory-content assertions stay unaffected by the portal sync `finish`
# triggers as a side effect -- only a test that actually asserts on the portal's own data files
# opts back in via `env=ON` (same convention `test_portal_triggers.py` already uses).
ON = {"CFQ_PORTAL_SYNC": "1"}


class StatusLineRenderingTest(unittest.TestCase):
    """Pure-function coverage for cfq_finish.py's line renderers (batch 035 phase 08) -- no
    subprocess, no fixture repo, since none of these read anything beyond the dict they're handed."""

    def test_language_line_no_issues(self):
        line = cfq_finish.language_line({"issues": 0, "findings": []})
        self.assertEqual(line["icon"], "done")
        self.assertEqual(line["detail"], "no issues")

    def test_language_line_with_issues_and_sampled_prose(self):
        line = cfq_finish.language_line({
            "issues": 2, "findings": ["missing: x"], "prose": {"truncated": True},
        })
        self.assertEqual(line["icon"], "warn")
        self.assertEqual(line["detail"], "2 issues · sampled")
        self.assertEqual(line["sub"], ["missing: x"])

    def test_maintenance_line_variants(self):
        self.assertEqual(cfq_finish.maintenance_line("OFF")["detail"], "off")
        self.assertEqual(cfq_finish.maintenance_line("NOT_DUE 5")["detail"], "not due (5 commits)")
        due = cfq_finish.maintenance_line("DUE 12")
        self.assertEqual(due["icon"], "warn")
        self.assertEqual(due["detail"], "due (12 commits) · run /pfq")

    def test_security_diff_line_skips_without_snapshot(self):
        self.assertIsNone(cfq_finish.security_diff_line({"planning": {}, "now": {}, "new": {}}))

    def test_security_diff_line_reports_the_delta_only(self):
        line = cfq_finish.security_diff_line({
            "planning": {"high": 1}, "now": {"high": 3}, "new": {"high": 2},
        })
        self.assertEqual(line["icon"], "warn")
        self.assertEqual(line["detail"], "high: +2")

    def test_changelog_line_variants(self):
        self.assertEqual(cfq_finish.changelog_line("changelogFile empty")["icon"], "skip")
        self.assertEqual(cfq_finish.changelog_line("error")["icon"], "fail")
        self.assertEqual(cfq_finish.changelog_line("2026-01-01-x done · 3 phases")["icon"], "done")

    def test_branch_line_variants(self):
        line = cfq_finish.branch_line("cfq/002-b", "cfq/001-a")
        self.assertEqual((line["label"], line["icon"], line["detail"]), ("Branch", "done", "cfq/002-b · from cfq/001-a"))
        line = cfq_finish.branch_line("cfq/002-b", "")
        self.assertEqual((line["icon"], line["detail"]), ("done", "cfq/002-b"))
        for branch in ("", "HEAD"):
            line = cfq_finish.branch_line(branch, "cfq/001-a")
            self.assertEqual((line["icon"], line["detail"]), ("skip", "no branch"))

    def test_branch_line_push_suffixes(self):
        def line(state, ahead=0, behind=0):
            return cfq_finish.branch_line(
                "cfq/002-b", "cfq/001-a", {"state": state, "ahead": ahead, "behind": behind},
            )

        base = "cfq/002-b · from cfq/001-a"
        for expected_icon, expected, entry in (
            ("done", f"{base} · pushed", line("pushed")),
            ("warn", f"{base} · ahead 2 · not pushed", line("ahead", 2)),
            ("warn", f"{base} · behind 3", line("behind", 0, 3)),
            ("warn", f"{base} · diverged (ahead 1, behind 2)", line("diverged", 1, 2)),
            ("warn", f"{base} · not pushed", line("not-pushed")),
            ("warn", f"{base} · push state unknown", line("unknown")),
        ):
            self.assertEqual((entry["icon"], entry["detail"]), (expected_icon, expected))
        for branch in ("", "HEAD"):
            entry = cfq_finish.branch_line(branch, "cfq/001-a", {"state": "pushed", "ahead": 0, "behind": 0})
            self.assertEqual((entry["icon"], entry["detail"]), ("skip", "no branch"))

    def test_telemetry_line_variants(self):
        entry = cfq_finish.telemetry_line("", True, "")
        self.assertEqual((entry["icon"], entry["detail"]), ("skip", "sync off · telemetrySyncRepo is empty"))
        entry = cfq_finish.telemetry_line("", True, "/tmp/tel")
        self.assertEqual((entry["icon"], entry["detail"]), ("done", "nothing to sync · target /tmp/tel"))
        entry = cfq_finish.telemetry_line("synced 3 records", True, "/tmp/tel")
        self.assertEqual((entry["icon"], entry["detail"]), ("done", "synced 3 records"))
        entry = cfq_finish.telemetry_line("boom", False, "/tmp/tel")
        self.assertEqual((entry["icon"], entry["detail"]), ("warn", "boom"))

    def test_attach_errors_creates_a_line_when_none_existed(self):
        lines = [cfq_finish.language_line({"issues": 0, "findings": []}), None]
        cfq_finish.attach_errors(lines, ["security: cfq_security.py failed"])
        present = [line for line in lines if line is not None]
        security_line = next(line for line in present if line["label"] == "Security Diff")
        self.assertEqual(security_line["icon"], "warn")
        self.assertIn("security: cfq_security.py failed", security_line["sub"])

    def test_attach_errors_downgrades_a_done_line_to_warn(self):
        lines = [cfq_finish.changelog_line("2026-01-01-x done · 3 phases")]
        cfq_finish.attach_errors(lines, ["changelog: git commit/push failed"])
        self.assertEqual(lines[0]["icon"], "warn")
        self.assertIn("changelog: git commit/push failed", lines[0]["sub"])


class FinishTest(CfqTestCase):
    auto_status = True

    def run_cfq(self, *args, env=None, **kwargs):
        # A real implementation session always has a harness session id.
        return super().run_cfq(*args, env={"CLAUDE_CODE_SESSION_ID": "finish-test", **(env or {})}, **kwargs)

    def _new_repo(self, name):
        # The fixture pins the branch name so the tests do not depend on the host's
        # init.defaultBranch.
        repo = self.make_repo(name)
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
        return repo

    def _new_batch(self, repo, name):
        d = repo / ".claude/cfq/impl" / name
        (d / "done").mkdir(parents=True)
        (d / ".priority").write_text("medium\n")
        (d / "done" / "01-a.md").write_text("# A phase\n")
        return d

    def test_happy_path(self):
        home = self._repos_dir / "home1"
        (home / ".claude/cfq").mkdir(parents=True)
        # No remote in the fixture: an enabled changelog would fail its push and add an error.
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"changelogFile": ""}))
        repo = self._new_repo("repo1")
        batch = self._new_batch(repo, "2026-01-01-happy")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-happy", home=home, check=True)

        proc = self.run_cfq("finish", str(repo), str(batch), "v0.1-happy", home=home, check=True)
        out = self.json_out(proc)
        self.assertTrue(
            (repo / ".claude/cfq/impl/done/2026-01-01-happy").is_dir(),
            f"batch not moved into impl/done: {out}",
        )
        self.assertFalse(
            (repo / ".claude/cfq/impl/2026-01-01-happy").exists(),
            "batch still present at its old location",
        )
        self.assertEqual(out["lock"], "released", f"lock field: {out}")
        lockstatus = self.run_cfq("lock", "status", str(repo), home=home).stdout.strip()
        self.assertEqual(lockstatus, "FREE", f"lock not actually released: {lockstatus}")

        report = json.loads(
            (repo / ".claude/cfq/impl/done/2026-01-01-happy/report.json").read_text()
        )
        fin = report["finish"]
        self.assertEqual(
            sorted(fin), ["at", "changelog", "errors", "lang", "maintenance", "security", "skipped"],
        )
        self.assertEqual(fin["skipped"], [])
        self.assertEqual(sorted(fin["lang"]), ["findings", "issues"])
        self.assertIsInstance(fin["lang"]["issues"], int)
        self.assertIsInstance(fin["lang"]["findings"], list)
        self.assertEqual(sorted(fin["security"]), ["new", "now", "planning"])
        self.assertEqual(fin["errors"], [])
        self.assertEqual(fin["errors"], out["errors"])
        self.assertNotIn("prose", fin["lang"])

    def test_second_finish_replaces_the_finish_object(self):
        home = self._repos_dir / "home-twice"
        home.mkdir()
        repo = self._new_repo("repo-twice")
        name = "2026-01-01-twice"
        batch = self._new_batch(repo, name)
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)
        self.run_cfq("finish", str(repo), str(batch), "v0.1-twice", home=home, check=True)
        moved = repo / ".claude/cfq/impl/done" / name
        first = json.loads((moved / "report.json").read_text())["finish"]

        self.run_cfq("finish", str(repo), str(moved), "v0.1-twice", home=home, check=True)
        data = json.loads((moved / "report.json").read_text())
        self.assertIsInstance(data["finish"], dict)
        self.assertEqual(sorted(data["finish"]), sorted(first))
        self.assertEqual(
            sum(1 for k in data if k == "finish"), 1, "finish must exist exactly once",
        )

    def test_live_lock_held_by_different_session_blocks_finish(self):
        # A new session must acquire the stale lock before finishing this batch.
        home = self._repos_dir / "home-lockmismatch"
        home.mkdir()
        repo = self._new_repo("repo-lockmismatch")
        name = "2026-01-01-lockmismatch"
        batch = self._new_batch(repo, name)
        self.run_cfq(
            "lock", "acquire", str(repo), name, home=home,
            env={"CLAUDE_CODE_SESSION_ID": "sidA"}, check=True,
        )

        out = self.run_cfq(
            "finish", str(repo), str(batch), "v0.1-lockmismatch", home=home,
            env={"CLAUDE_CODE_SESSION_ID": "sidB"},
        )
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("LOCKED", out.stderr)
        self.assertTrue(batch.is_dir())
        lockstatus = self.run_cfq("lock", "status", str(repo), home=home).stdout.strip()
        self.assertIn("ALIVE sidA", lockstatus)

    def test_mid_sequence_changelog_failure_still_completes(self):
        # Point changelogFile at a path inside a read-only directory -- cfq-changelog.sh finish
        # fails to write, cfq-finish.sh must still complete the rest of the sequence and release
        # the lock.
        home = self._repos_dir / "home2"
        (home / ".claude/cfq").mkdir(parents=True)
        repo = self._new_repo("repo2")
        batch = self._new_batch(repo, "2026-01-01-brokenchangelog")
        self.run_cfq(
            "lock", "acquire", str(repo), "2026-01-01-brokenchangelog", home=home, check=True,
        )

        readonlydir = repo / "readonlydir"
        readonlydir.mkdir()
        (home / ".claude/cfq/settings.json").write_text(
            json.dumps({"changelogFile": "readonlydir/changelog.yml"})
        )
        readonlydir.chmod(0o555)
        try:
            proc = self.run_cfq(
                "finish", str(repo), str(batch), "v0.1-brokenchangelog", home=home, check=True,
            )
        finally:
            readonlydir.chmod(0o755)

        out = self.json_out(proc)
        self.assertTrue(
            (repo / ".claude/cfq/impl/done/2026-01-01-brokenchangelog").is_dir(),
            f"sequence did not complete the move: {out}",
        )
        self.assertEqual(out["lock"], "released", f"lock field on failure path: {out}")
        lockstatus = self.run_cfq("lock", "status", str(repo), home=home).stdout.strip()
        self.assertEqual(
            lockstatus, "FREE", f"lock not released after mid-sequence failure: {lockstatus}",
        )
        self.assertGreater(len(out["errors"]), 0, f"errors should be non-empty: {out}")
        self.assertTrue(
            any(e.startswith("changelog:") for e in out["errors"]),
            f"no changelog error recorded: {out}",
        )
        report = json.loads(
            (repo / ".claude/cfq/impl/done/2026-01-01-brokenchangelog/report.json").read_text()
        )
        self.assertEqual(report["finish"]["errors"], out["errors"])
        self.assertTrue(any(e.startswith("changelog:") for e in report["finish"]["errors"]))

    def test_ignored_changelog_is_force_added_and_pushed_with_upstream(self):
        # The repo's own .gitignore covers the changelog and the batch branch has no upstream yet:
        # finish force-adds the file, commits it and the -u fallback push succeeds.
        home = self._repos_dir / "home-forced"
        home.mkdir()
        repo = self._new_repo("repo-forced")
        bare = self._repos_dir / "origin-forced.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
        (repo / ".gitignore").write_text(".claude/cfq/changelog.yml\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "ignore"], check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "cfq/forced"], check=True)
        name = "2026-01-01-forced"
        batch = self._new_batch(repo, name)
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "cfq/forced", home=home, check=True)
        )
        self.assertIn("force-added", out["changelog"], f"changelog field: {out}")
        self.assertIn("committed", out["changelog"], f"changelog field: {out}")
        self.assertFalse(
            any(e.startswith("changelog:") for e in out["errors"]), f"unexpected errors: {out}",
        )
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True,
        ).stdout.split()
        self.assertIn(".claude/cfq/changelog.yml", tracked)
        upstream = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "@{u}"],
            capture_output=True, text=True,
        )
        self.assertEqual(upstream.returncode, 0, f"no upstream after finish: {upstream.stderr}")

    def test_changelog_file_empty_is_not_an_error(self):
        home = self._repos_dir / "home3"
        (home / ".claude/cfq").mkdir(parents=True)
        repo = self._new_repo("repo3")
        batch = self._new_batch(repo, "2026-01-01-nochangelog")
        self.run_cfq(
            "lock", "acquire", str(repo), "2026-01-01-nochangelog", home=home, check=True,
        )
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"changelogFile": ""}))

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "v0.1-nochangelog", home=home, check=True)
        )
        self.assertEqual(
            out["changelog"], "changelogFile empty", f"changelog field should say empty: {out}",
        )
        self.assertFalse(
            any(e.startswith("changelog:") for e in out["errors"]),
            f"changelogFile empty must not be an error: {out}",
        )
        self.assertTrue(
            (repo / ".claude/cfq/impl/done/2026-01-01-nochangelog").is_dir(),
            f"sequence did not complete: {out}",
        )

    def test_no_planning_snapshot_is_not_an_error(self):
        home = self._repos_dir / "home4"
        home.mkdir()
        repo = self._new_repo("repo4")
        # No report.json at all -- simulates a batch that predates the planning-time security
        # snapshot.
        batch = self._new_batch(repo, "2026-01-01-nosnapshot")
        self.run_cfq(
            "lock", "acquire", str(repo), "2026-01-01-nosnapshot", home=home, check=True,
        )

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "v0.1-nosnapshot", home=home, check=True)
        )
        self.assertEqual(
            out["security"]["new"], {}, f"security.new should be empty without a planning snapshot: {out}",
        )
        self.assertFalse(
            any(e.startswith("security:") for e in out["errors"]),
            f"missing planning snapshot must not be an error: {out}",
        )

    def test_unwritable_report_json_is_left_alone(self):
        # The security step normally creates report.json; a directory in its place keeps the file
        # from existing, so finish has nothing to persist into and must create nothing.
        home = self._repos_dir / "home-noreport"
        (home / ".claude/cfq").mkdir(parents=True)
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"changelogFile": ""}))
        repo = self._new_repo("repo-noreport")
        name = "2026-01-01-noreport"
        batch = self._new_batch(repo, name)
        (batch / "report.json").mkdir()
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)
        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "v0.1-noreport", home=home, check=True)
        )
        moved = repo / ".claude/cfq/impl/done" / name
        self.assertTrue((moved / "report.json").is_dir(), "report.json must stay untouched")
        self.assertIn("lang", out)
        self.assertEqual(out["lock"], "released")

    def test_report_line_is_a_wsl_url_on_wsl(self):
        home = self._repos_dir / "home5w"
        (home / ".claude/cfq").mkdir(parents=True)
        repo = self._new_repo("repo5w")
        batch = self._new_batch(repo, "2026-01-01-htmlwsl")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-htmlwsl", home=home, check=True)
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"htmlReport": True}))

        proc = self.run_cfq(
            "finish", str(repo), str(batch), "v0.1-htmlwsl", home=home,
            env={**ON, "CFQ_HOST_PLATFORM": "wsl", "CFQ_WSL_DISTRO": "TestDistro"}, check=True,
        )
        report_line = next(e for e in self.json_out(proc)["statusLines"] if e["label"] == "Report")
        self.assertEqual(
            report_line["detail"],
            f"file://wsl.localhost/TestDistro{repo}/.claude/cfq/reports/index.html"
            "#/batch/2026-01-01-htmlwsl",
        )

    def test_html_report_auto_renders_when_enabled(self):
        # `finish` no longer writes a `.html` file itself -- `htmlReport: true` lets the portal
        # sync it already triggers (`cfq_lib/portal_hook.py`) actually run, and this batch's own
        # data lands in the portal.
        home = self._repos_dir / "home5"
        (home / ".claude/cfq").mkdir(parents=True)
        repo = self._new_repo("repo5")
        batch = self._new_batch(repo, "2026-01-01-htmlon")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-htmlon", home=home, check=True)
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"htmlReport": True}))

        proc = self.run_cfq(
            "finish", str(repo), str(batch), "v0.1-htmlon", home=home,
            env={**ON, "CFQ_HOST_PLATFORM": "posix"}, check=True,
        )
        out = self.json_out(proc)
        report_line = next(e for e in out["statusLines"] if e["label"] == "Report")
        self.assertEqual(report_line["icon"], "done", f"report line: {report_line}")
        self.assertEqual(
            report_line["detail"],
            f"file://{repo}/.claude/cfq/reports/index.html#/batch/2026-01-01-htmlon",
            f"report line: {report_line}",
        )
        self.assertTrue(
            (repo / ".claude/cfq/reports/data/batch/2026-01-01-htmlon.js").is_file(),
            "htmlReport=true should auto-sync this batch's own data into the portal",
        )
        self.assertFalse(
            (repo / ".claude/cfq/impl/done/2026-01-01-htmlon/report.html").exists(),
            "report.html must never land inside the batch directory",
        )
        self.assertFalse(
            (repo / ".claude/cfq/reports/2026-01-01-htmlon.html").exists(),
            "no flat <batch>.html file is written any more",
        )

    def test_html_report_explicit_off(self):
        home = self._repos_dir / "home6"
        (home / ".claude/cfq").mkdir(parents=True)
        repo = self._new_repo("repo6")
        batch = self._new_batch(repo, "2026-01-01-htmloff")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-htmloff", home=home, check=True)
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"htmlReport": False}))

        proc = self.run_cfq(
            "finish", str(repo), str(batch), "v0.1-htmloff", home=home, env=ON, check=True,
        )
        out = self.json_out(proc)
        report_line = next(e for e in out["statusLines"] if e["label"] == "Report")
        self.assertEqual(report_line["icon"], "skip", f"report line: {report_line}")
        self.assertEqual(report_line["detail"], "off · bin/cfq portal sync renders on demand", f"report line: {report_line}")
        self.assertFalse(
            (repo / ".claude/cfq/impl/done/2026-01-01-htmloff/report.html").exists(),
            "explicit htmlReport=false must not auto-render report.html",
        )
        self.assertFalse(
            (repo / ".claude/cfq/reports/data/batch/2026-01-01-htmloff.js").exists(),
            "explicit htmlReport=false must not sync the portal either",
        )

    def test_html_report_default_on(self):
        # The actual behaviour change: a repo with no settings file at all now renders, since
        # htmlReport now defaults to true.
        home = self._repos_dir / "home8"
        home.mkdir()
        repo = self._new_repo("repo8")
        batch = self._new_batch(repo, "2026-01-01-htmldefault")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-htmldefault", home=home, check=True)

        self.run_cfq(
            "finish", str(repo), str(batch), "v0.1-htmldefault", home=home, env=ON, check=True,
        )
        self.assertTrue(
            (repo / ".claude/cfq/reports/data/batch/2026-01-01-htmldefault.js").is_file(),
            "default htmlReport=true should auto-sync this batch's own data into the portal",
        )

    def test_already_in_impl_done_completes_normally(self):
        # Edge: the batch directory handed in is already inside impl/done/ (batch_dir == moved)
        # -- the move is skipped, the rest of the sequence runs against it in place.
        home = self._repos_dir / "home7"
        home.mkdir()
        repo = self._new_repo("repo7")
        done_dir = repo / ".claude/cfq/impl/done"
        batch = done_dir / "2026-01-01-alreadydone"
        (batch / "done").mkdir(parents=True)
        (batch / "done" / "01-a.md").write_text("# A phase\n")
        self.run_cfq(
            "lock", "acquire", str(repo), "2026-01-01-alreadydone", home=home, check=True,
        )

        out = self.json_out(
            self.run_cfq(
                "finish", str(repo), str(batch), "v0.1-alreadydone", home=home, check=True,
            )
        )
        self.assertTrue(batch.is_dir(), f"batch should still be in place: {out}")
        self.assertEqual(out["lock"], "released", f"lock field: {out}")
        lockstatus = self.run_cfq("lock", "status", str(repo), home=home).stdout.strip()
        self.assertEqual(lockstatus, "FREE", f"lock not released: {lockstatus}")

    def test_hard_failure_before_move_still_releases_lock(self):
        # The trap, made explicit: a failure so early the sequence never even produces JSON on
        # stdout must still release the lock -- the counterpart to
        # test_mid_sequence_changelog_failure_still_completes, which asserts the sequence
        # *completes* despite a failure. This one asserts the lock guarantee holds even when it
        # does not complete at all.
        home = self._repos_dir / "home8"
        home.mkdir()
        repo = self._new_repo("repo8")
        batch = self._new_batch(repo, "2026-01-01-hardfail")
        self.run_cfq(
            "lock", "acquire", str(repo), "2026-01-01-hardfail", home=home, check=True,
        )

        impl_dir = repo / ".claude/cfq/impl"
        impl_dir.chmod(0o555)
        try:
            proc = self.run_cfq(
                "finish", str(repo), str(batch), "v0.1-hardfail", home=home,
            )
        finally:
            impl_dir.chmod(0o755)

        self.assertNotEqual(proc.returncode, 0, f"expected a hard failure: {proc.stdout!r}")
        lockstatus = self.run_cfq("lock", "status", str(repo), home=home).stdout.strip()
        self.assertEqual(
            lockstatus, "FREE", f"lock not released after a hard failure: {lockstatus}",
        )

    def test_status_lines_shape_and_labels(self):
        home = self._repos_dir / "home-statuslines"
        home.mkdir()
        repo = self._new_repo("repo-statuslines")
        batch = self._new_batch(repo, "2026-01-01-statuslines")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-statuslines", home=home, check=True)

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "v0.1-statuslines", home=home, check=True)
        )
        self.assert_status_lines_shape(out["statusLines"])
        labels = [e["label"] for e in out["statusLines"]]
        # No `origin` remote and no `package.json` on this fixture -> cfq_security.py's `counts`
        # comes back `{}` on both sides of the diff, so `Security Diff` is the one line correctly
        # omitted here (no planning snapshot, nothing to compare) -- see security_diff_line.
        self.assertEqual(
            labels, [
                "Language", "Maintenance", "Changelog", "Branch", "Skipped", "Telemetry", "Report", "Lock",
            ],
            msg=f"labels = {labels}",
        )
        lock = next(e for e in out["statusLines"] if e["label"] == "Lock")
        self.assertEqual(lock["icon"], "done", msg=f"lock = {lock}")
        self.assertEqual(lock["detail"], "released", msg=f"lock = {lock}")

    def test_errors_attach_as_sub_lines_not_new_entries(self):
        home = self._repos_dir / "home-erroraslsub"
        (home / ".claude/cfq").mkdir(parents=True)
        repo = self._new_repo("repo-erroraslsub")
        batch = self._new_batch(repo, "2026-01-01-erroraslsub")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-erroraslsub", home=home, check=True)

        readonlydir = repo / "readonlydir"
        readonlydir.mkdir()
        (home / ".claude/cfq/settings.json").write_text(
            json.dumps({"changelogFile": "readonlydir/changelog.yml"})
        )
        readonlydir.chmod(0o555)
        try:
            out = self.json_out(
                self.run_cfq(
                    "finish", str(repo), str(batch), "v0.1-erroraslsub", home=home, check=True,
                )
            )
        finally:
            readonlydir.chmod(0o755)

        self.assertGreater(len(out["errors"]), 0, f"errors should be non-empty: {out}")
        self.assert_status_lines_shape(out["statusLines"])
        labels = [e["label"] for e in out["statusLines"]]
        self.assertEqual(
            labels, [
                "Language", "Maintenance", "Changelog", "Branch", "Skipped", "Telemetry", "Report", "Lock",
            ],
            msg=f"a changelog error must not add a new statusLines entry: {labels}",
        )
        changelog_line = next(e for e in out["statusLines"] if e["label"] == "Changelog")
        self.assertTrue(
            any(sub.startswith("changelog:") for sub in changelog_line["sub"]),
            msg=f"changelog error should appear as a sub line: {changelog_line}",
        )
        self.assertNotEqual(
            changelog_line["icon"], "done", msg=f"an errored step must not stay 'done': {changelog_line}",
        )

    # ---- batch 051 phase 07: skipped phases leave an inbox entry --------------------------------

    PLAN_TEXT = (
        "# Third phase\n\n## Size\n\nS\n\n## Changes\n\n```bash\n# not a heading\n"
        "echo hi\n```\n\n### Detail\n\nText.\n"
    )

    def _skipped_batch(self, repo, name, reason="obsolete"):
        """Two done phases and phase 03 skipped through a real `phase skip` call."""
        d = repo / ".claude/cfq/impl" / name
        (d / "done").mkdir(parents=True)
        (d / ".priority").write_text("medium\n")
        (d / "done" / "01-a.md").write_text("# A phase\n")
        (d / "done" / "02-b.md").write_text("# B phase\n")
        (d / "03-c.md").write_text(self.PLAN_TEXT)
        args = ["phase", "skip", str(d), "03"]
        if reason:
            args += ["--reason", reason]
        self.run_cfq(*args, check=True)
        return d

    def _finish_skipped(self, tag, reason="obsolete", changelog=False, prepare=None):
        home = self._repos_dir / f"home-{tag}"
        (home / ".claude/cfq").mkdir(parents=True)
        # No remote in the fixture: an enabled changelog would fail its push and add an error.
        settings = {} if changelog else {"changelogFile": ""}
        (home / ".claude/cfq/settings.json").write_text(json.dumps(settings))
        repo = self._new_repo(f"repo-{tag}")
        name = f"2026-01-01-{tag}"
        batch = self._skipped_batch(repo, name, reason)
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)
        if prepare:
            prepare(repo)
        proc = self.run_cfq("finish", str(repo), str(batch), f"v0.1-{tag}", home=home, check=True)
        return repo, home, name, self.json_out(proc)

    def _inbox(self, repo):
        return sorted((repo / ".claude/cfq/plan").glob("*.md"))

    def test_skipped_phase_leaves_one_inbox_entry(self):
        repo, _home, name, out = self._finish_skipped("skipinbox", changelog=True)
        line = next(e for e in out["statusLines"] if e["label"] == "Skipped")
        self.assertEqual((line["icon"], line["detail"]), ("done", "1 phases · 1 inbox entries"), line)
        labels = [e["label"] for e in out["statusLines"]]
        self.assertEqual(labels.index("Skipped"), labels.index("Branch") + 1)

        entries = self._inbox(repo)
        self.assertEqual(len(entries), 1, entries)
        text = entries[0].read_text()
        self.assertTrue(text.startswith("# "), text)
        archived = repo / ".claude/cfq/impl/done" / name / "skipped/03-c.md"
        self.assertTrue(archived.is_file())
        origin = text.split("## Origin", 1)[1].split("## Skipped plan", 1)[0]
        for needle in (name, "03-c", "obsolete", str(archived)):
            self.assertIn(needle, origin)
        self.assertIn("## Skipped plan", text)
        self.assertIn("Third phase", text.split("## Skipped plan", 1)[1])

        self.assertIn(f"{name} done · 2 phases · 1 skipped", out["changelog"])
        status = json.loads((repo / ".claude/cfq/impl/done" / name / "status.json").read_text())
        self.assertEqual(status["phases"]["03-c"]["inbox"], entries[0].name)
        fin = json.loads((repo / ".claude/cfq/impl/done" / name / "report.json").read_text())["finish"]
        self.assertEqual(fin["skipped"], ["03-c"])

    def test_skipped_plan_headings_are_demoted_outside_code_fences(self):
        repo, _home, _name, _out = self._finish_skipped("skipdemote")
        plan = self._inbox(repo)[0].read_text().split("## Skipped plan", 1)[1]
        self.assertIn("\n### Third phase\n", plan)
        self.assertIn("\n#### Size\n", plan)
        self.assertIn("\n#### Changes\n", plan)
        self.assertIn("\n##### Detail\n", plan)
        self.assertIn("\n# not a heading\n", plan)

    def test_skipped_second_finish_writes_no_second_entry(self):
        repo, home, name, _out = self._finish_skipped("skiptwice")
        moved = repo / ".claude/cfq/impl/done" / name
        self.run_cfq("finish", str(repo), str(moved), "v0.1-skiptwice", home=home, check=True)
        self.assertEqual(len(self._inbox(repo)), 1)

    def test_skip_without_reason_says_none_given(self):
        repo, _home, _name, _out = self._finish_skipped("skipnoreason", reason=None)
        text = self._inbox(repo)[0].read_text()
        self.assertIn("none given", text.split("## Origin", 1)[1])

    def test_no_skipped_phase_gets_a_none_line_and_no_entry(self):
        home = self._repos_dir / "home-noskip"
        home.mkdir()
        repo = self._new_repo("repo-noskip")
        batch = self._new_batch(repo, "2026-01-01-noskip")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-noskip", home=home, check=True)
        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "v0.1-noskip", home=home, check=True)
        )
        line = next(e for e in out["statusLines"] if e["label"] == "Skipped")
        self.assertEqual((line["icon"], line["detail"]), ("skip", "none"), line)
        self.assertEqual(self._inbox(repo), [])

    def test_skipped_inbox_failure_still_completes_with_a_warning(self):
        def block_plan_dir(repo):
            shutil.rmtree(repo / ".claude/cfq/plan", ignore_errors=True)
            (repo / ".claude/cfq/plan").write_text("not a directory\n")

        repo, _home, name, out = self._finish_skipped("skipfail", prepare=block_plan_dir)
        self.assertTrue((repo / ".claude/cfq/impl/done" / name).is_dir())
        self.assertEqual(out["lock"], "released")
        self.assertTrue(any(e.startswith("skipped:") for e in out["errors"]), out["errors"])
        line = next(e for e in out["statusLines"] if e["label"] == "Skipped")
        self.assertEqual(line["icon"], "warn", line)
        status = json.loads((repo / ".claude/cfq/impl/done" / name / "status.json").read_text())
        self.assertNotIn("inbox", status["phases"]["03-c"])

    def _lang_refs(self, repo, tag, changelog=None, branch=None):
        """Runs finish on `repo` with a logging shim in front of cfq_lang.py and returns the
        reference each of the two language checks received (changed-files check, prose check).
        `changelog` is the text of a changelog file in the repo; None leaves `changelogFile` empty."""
        home = self._repos_dir / f"home-{tag}"
        (home / ".claude/cfq").mkdir(parents=True)
        settings = {"changelogFile": ""}
        if changelog is not None:
            (repo / "CHANGELOG.yml").write_text(changelog)
            settings = {"changelogFile": "CHANGELOG.yml"}
        (home / ".claude/cfq/settings.json").write_text(json.dumps(settings))
        batch = self._new_batch(repo, "2026-01-01-" + tag)
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-" + tag, home=home, check=True)

        shim_root = self._repos_dir / f"shim-{tag}"
        shim_root.mkdir()
        scripts_copy = shim_root / "scripts"
        shutil.copytree(SCRIPTS_DIR, scripts_copy)
        bin_copy = shim_root / "bin"
        shutil.copytree(PLUGIN_ROOT / "bin", bin_copy)
        log_file = shim_root / "lang.log"
        log_file.write_text("")
        orig = scripts_copy / "cfq_lang.py"
        real = scripts_copy / "cfq_lang_real.py"
        orig.rename(real)
        orig.write_text(f"""#!/usr/bin/env python3
import subprocess
import sys

with open({str(log_file)!r}, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(subprocess.run([sys.executable, {str(real)!r}] + sys.argv[1:]).returncode)
""")
        orig.chmod(0o755)

        run_env = self._base_env()
        run_env["HOME"] = str(home)
        run_env["CLAUDE_CODE_SESSION_ID"] = "finish-test"
        proc = subprocess.run(
            [str(bin_copy / "cfq"), "finish", str(repo), str(batch),
             "v0.1-" + tag if branch is None else branch],
            capture_output=True, text=True, env=run_env,
        )
        self.assertEqual(proc.returncode, 0, f"finish via copy failed: {proc.stderr}")
        calls = [line.split() for line in log_file.read_text().splitlines() if line]
        changed = [c for c in calls if "--changed" in c]
        prose = [c for c in calls if c and c[0] == "prose"]
        self.assertEqual(len(changed), 1, calls)
        self.assertEqual(len(prose), 1, calls)
        return changed[0][-1], prose[0][-1], json.loads(proc.stdout)

    def _rev(self, repo, ref):
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_language_checks_use_the_detected_default_branch(self):
        repo = self._new_repo("repo-master")
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "master"], check=True)
        changed_ref, prose_ref, _out = self._lang_refs(repo, "master")
        self.assertEqual(changed_ref, prose_ref)
        self.assertEqual(changed_ref, proc_lib.default_branch(str(repo), True)[1])
        self.assertEqual(self._rev(repo, changed_ref), self._rev(repo, "master"))

    def test_language_checks_compare_against_origin_first(self):
        source = self._new_repo("repo-source")
        clone = self._repos_dir / "repo-clone"
        subprocess.run(["git", "clone", "-q", str(source), str(clone)], check=True)
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(clone), "config", key, value], check=True)
        (source / "more.txt").write_text("more\n")
        subprocess.run(["git", "-C", str(source), "add", "more.txt"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "more"], check=True)
        subprocess.run(["git", "-C", str(clone), "fetch", "-q", "origin"], check=True)
        self.assertNotEqual(self._rev(clone, "main"), self._rev(clone, "origin/main"))

        changed_ref, prose_ref, _out = self._lang_refs(clone, "clone")
        self.assertEqual(changed_ref, prose_ref)
        self.assertEqual(self._rev(clone, changed_ref), self._rev(clone, "origin/main"))

    def test_language_check_survives_a_repo_without_a_default_branch(self):
        repo = self._new_repo("repo-work")
        subprocess.run(["git", "-C", str(repo), "branch", "-M", "work"], check=True)
        _changed, _prose, out = self._lang_refs(repo, "work")
        self.assertTrue(any(e["label"] == "Language" for e in out["statusLines"]), out)

    # ---- push state of the batch branch -------------------------------------------------------

    def _pushed_clone(self, name):
        """A clone on `cfq/push` whose branch is pushed to a bare `origin` and identical to it."""
        bare = self._repos_dir / f"{name}-origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        repo = self._new_repo(name)
        self._git(repo, "remote", "add", "origin", str(bare))
        self._git(repo, "checkout", "-q", "-b", "cfq/push")
        self._git(repo, "push", "-q", "-u", "origin", "cfq/push")
        return repo

    def _commit_file(self, repo, fname):
        (repo / fname).write_text(fname + "\n")
        self._git(repo, "add", fname)
        self._git(repo, "commit", "-q", "-m", fname)

    def test_push_state_variants(self):
        repo = self._pushed_clone("repo-push-state")
        self.assertEqual(
            cfq_finish.push_state(repo, "cfq/push"), {"state": "pushed", "ahead": 0, "behind": 0},
        )
        self._commit_file(repo, "local.txt")
        self.assertEqual(
            cfq_finish.push_state(repo, "cfq/push"), {"state": "ahead", "ahead": 1, "behind": 0},
        )
        self.assertEqual(
            cfq_finish.push_state(repo, "cfq/never"), {"state": "not-pushed", "ahead": 0, "behind": 0},
        )

    def test_push_state_behind_and_diverged(self):
        repo = self._pushed_clone("repo-push-behind")
        other = self._repos_dir / "repo-push-other"
        subprocess.run(
            ["git", "clone", "-q", "-b", "cfq/push",
             str(self._repos_dir / "repo-push-behind-origin.git"), str(other)], check=True,
        )
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            self._git(other, "config", key, value)
        self._commit_file(other, "remote.txt")
        self._git(other, "push", "-q")
        self._git(repo, "fetch", "-q", "origin")
        self.assertEqual(
            cfq_finish.push_state(repo, "cfq/push"), {"state": "behind", "ahead": 0, "behind": 1},
        )
        self._commit_file(repo, "local.txt")
        self.assertEqual(
            cfq_finish.push_state(repo, "cfq/push"), {"state": "diverged", "ahead": 1, "behind": 1},
        )

    def test_push_state_unknown_outside_a_repository(self):
        # The ref lookup succeeds only inside a repository; a non-repository is "not pushed", and
        # an unreadable rev-list is "unknown" -- neither may raise.
        with mock.patch.object(cfq_finish, "git", side_effect=OSError("no git")):
            self.assertEqual(cfq_finish.push_state("/nowhere", "b")["state"], "unknown")

    def test_finish_reports_the_push_state(self):
        home = self._repos_dir / "home-pushstate"
        (home / ".claude/cfq").mkdir(parents=True)
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"changelogFile": ""}))
        repo = self._pushed_clone("repo-pushstate")
        name = "2026-01-01-pushstate"
        batch = self._new_batch(repo, name)
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "cfq/push", home=home, check=True)
        )
        self.assertEqual(out["branch"]["push"], {"state": "pushed", "ahead": 0, "behind": 0})
        line = next(e for e in out["statusLines"] if e["label"] == "Branch")
        self.assertEqual((line["icon"], line["detail"]), ("done", "cfq/push · pushed"))
        telemetry = next(e for e in out["statusLines"] if e["label"] == "Telemetry")
        self.assertEqual(
            (telemetry["icon"], telemetry["detail"]),
            ("skip", "sync off · telemetrySyncRepo is empty"),
        )

    def test_finish_without_a_remote_says_not_pushed(self):
        home = self._repos_dir / "home-nopush"
        (home / ".claude/cfq").mkdir(parents=True)
        (home / ".claude/cfq/settings.json").write_text(json.dumps({"changelogFile": ""}))
        repo = self._new_repo("repo-nopush")
        name = "2026-01-01-nopush"
        batch = self._new_batch(repo, name)
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "cfq/nopush", home=home, check=True)
        )
        self.assertEqual(sorted(out["branch"]["push"]), ["ahead", "behind", "state"])
        self.assertEqual(out["branch"]["push"]["state"], "not-pushed")
        line = next(e for e in out["statusLines"] if e["label"] == "Branch")
        self.assertEqual((line["icon"], line["detail"]), ("warn", "cfq/nopush · not pushed"))

    def test_finish_with_a_configured_sync_target_and_nothing_to_sync(self):
        home = self._repos_dir / "home-synctarget"
        (home / ".claude/cfq").mkdir(parents=True)
        target = self._repos_dir / "tel-target"
        (home / ".claude/cfq/settings.json").write_text(
            json.dumps({"changelogFile": "", "telemetrySyncRepo": str(target)})
        )
        repo = self._new_repo("repo-synctarget")
        name = "2026-01-01-synctarget"
        batch = self._new_batch(repo, name)
        self.run_cfq("lock", "acquire", str(repo), name, home=home, check=True)

        out = self.json_out(
            self.run_cfq("finish", str(repo), str(batch), "cfq/sync", home=home, check=True)
        )
        telemetry = next(e for e in out["statusLines"] if e["label"] == "Telemetry")
        self.assertEqual(
            (telemetry["icon"], telemetry["detail"]),
            ("done", f"nothing to sync · target {target}"),
        )

    # ---- the language checks compare against the batch's own base branch --------------------

    def _git(self, repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    def _chain_repo(self, name):
        """A repository on `cfq/002-b`, cut from the unmerged predecessor `cfq/001-a`, which
        carries one commit `main` lacks."""
        repo = self._new_repo(name)
        self._git(repo, "checkout", "-q", "-b", "cfq/001-a")
        (repo / "a.txt").write_text("a\n")
        self._git(repo, "add", "a.txt")
        self._git(repo, "commit", "-q", "-m", "predecessor")
        self._git(repo, "checkout", "-q", "-b", "cfq/002-b")
        return repo

    def _clone_chain_repo(self, name):
        """A clone of a repository with `main` and `cfq/001-a`: `origin/cfq/001-a` exists, a local
        `cfq/001-a` is cut from `main` (a different commit), and `cfq/002-b` is checked out."""
        source = self._new_repo(name + "-source")
        self._git(source, "checkout", "-q", "-b", "cfq/001-a")
        (source / "a.txt").write_text("a\n")
        self._git(source, "add", "a.txt")
        self._git(source, "commit", "-q", "-m", "predecessor")
        self._git(source, "checkout", "-q", "main")
        clone = self._repos_dir / name
        subprocess.run(["git", "clone", "-q", str(source), str(clone)], check=True)
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            self._git(clone, "config", key, value)
        self._git(clone, "branch", "cfq/001-a", "main")
        self._git(clone, "checkout", "-q", "-b", "cfq/002-b", "origin/cfq/001-a")
        return clone

    @staticmethod
    def _changelog(tag, base):
        lines = ["- batchNumber: 2", f"  batch: 2026-01-01-{tag}", "  branch: cfq/002-b"]
        if base is not None:
            lines.append(f"  base: {base}")
        return "\n".join(lines + ["  status: running", ""])

    def _assert_lang_ref(self, repo, tag, base, expected, changelog="block"):
        """Both `lang` calls receive the same reference, equal to `expected`, and `finish` completes with a `Language` status line."""
        text = self._changelog(tag, base) if changelog == "block" else changelog
        changed_ref, prose_ref, out = self._lang_refs(repo, tag, changelog=text)
        self.assertEqual(changed_ref, prose_ref)
        self.assertEqual(self._rev(repo, changed_ref), self._rev(repo, expected))
        self.assertTrue(any(e["label"] == "Language" for e in out["statusLines"]), out)
        return changed_ref

    def test_language_checks_use_the_recorded_base_branch(self):
        repo = self._chain_repo("repo-base")
        self.assertNotEqual(self._rev(repo, "cfq/001-a"), self._rev(repo, "main"))
        self._assert_lang_ref(repo, "base", "cfq/001-a", "cfq/001-a")

    def test_language_checks_prefer_the_base_branch_on_origin(self):
        clone = self._clone_chain_repo("repo-base-origin")
        self.assertNotEqual(self._rev(clone, "cfq/001-a"), self._rev(clone, "origin/cfq/001-a"))
        ref = self._assert_lang_ref(clone, "baseorigin", "cfq/001-a", "origin/cfq/001-a")
        self.assertEqual(ref, "origin/cfq/001-a")

    def test_language_checks_with_the_default_branch_as_base(self):
        repo = self._chain_repo("repo-base-default")
        ref = self._assert_lang_ref(repo, "basedefault", "main", "main")
        self.assertEqual(ref, proc_lib.default_branch(str(repo), True)[1])

    def test_language_checks_fall_back_for_a_legacy_block(self):
        repo = self._chain_repo("repo-base-legacy")
        ref = self._assert_lang_ref(repo, "baselegacy", None, "main")
        self.assertEqual(ref, proc_lib.default_branch(str(repo), True)[1])

    def test_language_checks_fall_back_when_the_base_branch_is_gone(self):
        repo = self._chain_repo("repo-base-gone")
        self._git(repo, "branch", "-D", "cfq/001-a")
        ref = self._assert_lang_ref(repo, "basegone", "cfq/001-a", "main")
        self.assertEqual(ref, proc_lib.default_branch(str(repo), True)[1])

    def test_language_checks_fall_back_without_a_changelog(self):
        repo = self._chain_repo("repo-base-nolog")
        changed_ref, prose_ref, out = self._lang_refs(repo, "basenolog")
        self.assertEqual(changed_ref, prose_ref)
        self.assertEqual(changed_ref, proc_lib.default_branch(str(repo), True)[1])
        self.assertTrue(any(e["label"] == "Language" for e in out["statusLines"]), out)

    # ---- the Branch line --------------------------------------------------------------------

    def _branch_entry(self, repo, tag, base, branch="cfq/002-b"):
        text = self._changelog(tag, base)
        _c, _p, out = self._lang_refs(repo, tag, changelog=text, branch=branch)
        entries = [e for e in out["statusLines"] if e["label"] == "Branch"]
        self.assertEqual(len(entries), 1, out["statusLines"])
        self.assert_status_lines_shape(out["statusLines"])
        labels = [e["label"] for e in out["statusLines"]]
        self.assertEqual(labels.index("Branch"), labels.index("Changelog") + 1)
        return entries[0], out

    def test_branch_line_names_the_branch_and_its_base(self):
        repo = self._chain_repo("repo-branch-routine")
        entry, out = self._branch_entry(repo, "branchroutine", "cfq/001-a")
        self.assertEqual((entry["icon"], entry["detail"]), ("warn", "cfq/002-b · from cfq/001-a · not pushed"))
        self.assertEqual(
            out["branch"],
            {"name": "cfq/002-b", "base": "cfq/001-a",
             "push": {"state": "not-pushed", "ahead": 0, "behind": 0}},
        )

    def test_branch_line_without_a_recorded_base_names_the_branch_alone(self):
        repo = self._chain_repo("repo-branch-nobase")
        entry, out = self._branch_entry(repo, "branchnobase", None)
        self.assertEqual((entry["icon"], entry["detail"]), ("warn", "cfq/002-b · not pushed"))
        self.assertEqual(out["branch"]["base"], "")
        self.assertEqual(out["branch"]["push"]["state"], "not-pushed")

    def test_branch_line_for_a_detached_head_is_skipped(self):
        repo = self._chain_repo("repo-branch-detached")
        entry, out = self._branch_entry(repo, "branchdetached", "cfq/001-a", branch="HEAD")
        self.assertEqual((entry["icon"], entry["detail"]), ("skip", "no branch"))
        self.assertEqual(out["branch"], {"name": "", "base": "cfq/001-a", "push": None})

    def test_batch_base_reads_the_blocks_base(self):
        repo = self._chain_repo("repo-batch-base")
        (repo / "CHANGELOG.yml").write_text(
            self._changelog("other", "cfq/009-z") + self._changelog("mine", "cfq/001-a")
        )
        with mock.patch.object(cfq_changelog, "settings_get", return_value="CHANGELOG.yml"):
            self.assertEqual(cfq_finish.batch_base(str(repo), "2026-01-01-mine"), "cfq/001-a")
            self.assertEqual(cfq_finish.batch_base(str(repo), "2026-01-01-none"), "")
        with mock.patch.object(cfq_changelog, "settings_get", return_value=""):
            self.assertEqual(cfq_finish.batch_base(str(repo), "2026-01-01-mine"), "")

    def test_nine_subcalls_run_in_expected_order(self):
        # Order: cfq-finish.sh runs its nine sub-nouns as a sequence where later steps depend on
        # earlier state -- wrap each with a logging shim and assert their first-occurrence order.
        home = self._repos_dir / "home9"
        home.mkdir()
        repo = self._new_repo("repo9")
        batch = self._new_batch(repo, "2026-01-01-order")
        self.run_cfq("lock", "acquire", str(repo), "2026-01-01-order", home=home, check=True)

        scripts_copy = self._repos_dir / "scripts"
        shutil.copytree(SCRIPTS_DIR, scripts_copy)
        bin_copy = self._repos_dir / "bin"
        shutil.copytree(PLUGIN_ROOT / "bin", bin_copy)

        log_file = self._repos_dir / "order.log"
        log_file.write_text("")
        noun_to_script = {
            "registry": "cfq_registry.py",
            "lang": "cfq_lang.py",
            "maintenance": "cfq_maintenance.py",
            "security": "cfq_security.py",
            "report": "cfq_report.py",
            "settings": "cfq_settings.py",
            "changelog": "cfq_changelog.py",
            "telemetry": "cfq_telemetry.py",
            "lock": "cfq_lock.py",
        }
        for noun, script_name in noun_to_script.items():
            orig = scripts_copy / script_name
            real = scripts_copy / script_name.replace(".py", "_real.py")
            orig.rename(real)
            # Imported (cfq_finish reads the changelog through cfq_changelog), the shim hands the
            # real module's names through instead of running the command.
            orig.write_text(f"""#!/usr/bin/env python3
import subprocess
import sys

if __name__ != "__main__":
    from {real.stem} import *  # noqa: F401,F403
else:
    with open({str(log_file)!r}, "a") as f:
        f.write({noun!r} + " " + " ".join(sys.argv[1:]) + "\\n")
    sys.exit(subprocess.run([sys.executable, {str(real)!r}] + sys.argv[1:]).returncode)
""")
            orig.chmod(0o755)

        run_env = self._base_env()
        run_env["HOME"] = str(home)
        run_env["CLAUDE_CODE_SESSION_ID"] = "finish-test"
        proc = subprocess.run(
            [str(bin_copy / "cfq"), "finish", str(repo), str(batch), "v0.1-order"],
            capture_output=True, text=True, env=run_env,
        )
        self.assertEqual(proc.returncode, 0, f"finish via copy failed: {proc.stderr}")

        # `settings` is used internally by nearly every other script (to read its own config),
        # so its first log line is not necessarily cfq-finish.sh's own direct call -- only its
        # two direct calls (changelogFile, htmlReport) carry those exact argument tails; the
        # changelogFile read comes first, as the language checks look up the batch's base branch.
        calls = [line for line in log_file.read_text().splitlines() if line]
        self.assertTrue(calls[0].startswith("lock status "), calls)
        first_index = {}
        for i, line in enumerate(calls):
            noun = line.split(" ", 1)[0]
            if noun == "lock" and not line.startswith("lock release "):
                continue
            if noun == "settings" and not line.endswith("changelogFile") \
                    and not line.endswith("htmlReport"):
                continue
            first_index.setdefault(noun, i)
        expected = [
            "registry", "settings", "lang", "maintenance", "security", "report", "changelog",
            "telemetry", "lock",
        ]
        for noun in expected:
            self.assertIn(noun, first_index, f"{noun} never directly called: {calls}")
        actual_order = sorted(expected, key=lambda n: first_index[n])
        self.assertEqual(actual_order, expected, f"call order mismatch, raw log: {calls}")


if __name__ == "__main__":
    unittest.main()
