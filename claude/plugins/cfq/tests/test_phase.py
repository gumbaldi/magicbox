"""Self-test for scripts/cfq_phase.py: `record`/`commit`/`reopen` as the transactional calls that
replace the improvised "move the file, then remember to call report append" sequence -- `commit`
additionally folds in the phase's own Git commit, push, SHA backfill and registry add.
"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import unittest
from unittest import mock

from cfq_testlib import CfqTestCase, write_status

import cfq_phase  # noqa: E402


class CommitStatusLineTest(unittest.TestCase):
    """Pure-function coverage for cfq_phase.py's `commit_status_line` (batch 035 phase 08) --
    `references/ifq-phase.md`'s **Commit Result Rendering** branch table, one function per branch."""

    def test_ok_pushed(self):
        line = cfq_phase.commit_status_line({"status": "OK", "branch": "main", "pushed": True})
        self.assertEqual(line["icon"], "done")
        self.assertEqual(line["detail"], "main · pushed")

    def test_ok_not_pushed_carries_push_error_as_sub(self):
        line = cfq_phase.commit_status_line({
            "status": "OK", "branch": "main", "pushed": False, "pushError": "connection refused",
        })
        self.assertEqual(line["icon"], "warn")
        self.assertEqual(line["detail"], "main · not pushed")
        self.assertEqual(line["sub"], ["connection refused"])

    def test_nothing_staged(self):
        line = cfq_phase.commit_status_line({"status": "NOTHING_STAGED"})
        self.assertEqual(line["icon"], "warn")
        self.assertEqual(line["detail"], "nothing staged")

    def test_commit_failed(self):
        line = cfq_phase.commit_status_line({"status": "COMMIT_FAILED", "detail": "hook rejected"})
        self.assertEqual(line["icon"], "fail")
        self.assertEqual(line["detail"], "hook rejected")

    def test_record_failed(self):
        line = cfq_phase.commit_status_line({
            "status": "RECORD_FAILED", "sha": "abc123", "detail": "disk full",
        })
        self.assertEqual(line["icon"], "fail")
        self.assertEqual(line["detail"], "disk full")

    def test_nothing_staged_differs_from_ok(self):
        ok_line = cfq_phase.commit_status_line({"status": "OK", "branch": "main", "pushed": True})
        staged_line = cfq_phase.commit_status_line({"status": "NOTHING_STAGED"})
        self.assertNotEqual(ok_line["text"], staged_line["text"])
        self.assertNotEqual(ok_line["icon"], staged_line["icon"])


class LastStderrLineTest(unittest.TestCase):
    """`cfq_phase._last_stderr_line` should surface git's own `error:`/`fatal:` line over the
    trailing hint line (`"in 'git help config'."`) that used to be all `pushError`/`COMMIT_FAILED`
    reported -- see the batch's finding."""

    def test_prefers_error_and_fatal_lines_over_trailing_hint(self):
        cases = [
            (
                "error: failed to push some refs to 'x'\nhint: foo\nhint: in 'git help config'.\n",
                "error: failed to push some refs to 'x'",
            ),
            (
                "fatal: The upstream branch ... does not match\n\nTo push ...\n",
                "fatal: The upstream branch ... does not match",
            ),
            ("some warning\nlast line\n", "last line"),
            ("", ""),
        ]
        for stderr, expected in cases:
            with self.subTest(stderr=stderr):
                self.assertEqual(cfq_phase._last_stderr_line(stderr), expected)


class TestPhase(CfqTestCase):
    def _batch(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_phase_md(self, batch, slug):
        (batch / f"{slug}.md").write_text(f"# Phase {slug}\n")

    def _write_report(self, batch, phases):
        """Writes the ledger and, last, the batch's status.json from the plan files lying there
        -- every fixture builds its phase files first, so one call covers them all."""
        (batch / "report.json").write_text(json.dumps(
            {"repo": "", "batch": batch.name, "started": "2026-01-01T10:00:00+01:00", "phases": phases},
        ) + "\n")
        write_status(batch)

    def _phase_file(self, batch, obj):
        f = batch / "_phase.json"
        f.write_text(json.dumps(obj))
        return f

    def _report_json(self, batch):
        return json.loads((batch / "report.json").read_text())

    # ---- fixtures for `commit`: a real repo (optionally with a bare remote), mirroring
    # test_branch.py's own temp-repo + bare-remote pattern -----------------------------------

    def _init_repo(self, name, branch="main"):
        # Repo-level (not just per-command `-c`) identity: `phase commit` calls a plain `git
        # commit` internally, with no `-c` of its own -- it must find a usable identity already
        # configured on the repo, exactly as a real checkout would have one.
        repo = self._repos_dir / name
        repo.mkdir(parents=True, exist_ok=True)
        self.run_clean("git", "init", "-q", "-b", branch, cwd=repo)
        self.run_clean("git", "config", "user.email", "a@b.c", cwd=repo)
        self.run_clean("git", "config", "user.name", "a", cwd=repo)
        self.run_clean("git", "commit", "--allow-empty", "-q", "-m", "init", cwd=repo)
        return repo

    def _add_bare_remote(self, repo, branch="main"):
        remote = self._repos_dir / f"{repo.name}-remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", branch, str(remote))
        self.run_clean("git", "remote", "add", "origin", str(remote), cwd=repo)
        self.run_clean("git", "push", "-q", "origin", branch, cwd=repo)
        return remote

    def _git_batch(self, repo_name, batch_name, with_remote=True):
        repo = self._init_repo(repo_name)
        if with_remote:
            self._add_bare_remote(repo)
        batch = repo / ".claude" / "cfq" / "impl" / batch_name
        batch.mkdir(parents=True)
        return repo, batch

    def _stage_change(self, repo, filename="feature.txt", content="built\n"):
        (repo / filename).write_text(content)
        self.run_clean("git", "add", filename, cwd=repo)

    def _head_sha(self, repo):
        return self.run_clean("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()

    def _trailer(self, repo, key):
        return self.run_clean(
            "git", "log", "-1", f"--format=%(trailers:key={key},valueonly)", cwd=repo,
        ).stdout.strip()

    def _message_file(self, batch, text="Implement the phase\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"):
        f = batch / "_message.txt"
        f.write_text(text)
        return f

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
        write_status(batch)
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

    def test_commit_green_routine_moves_records_commits_and_pushes(self):
        repo, batch = self._git_batch("commit-repo", "042-2026-03-01-committopic")
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {
            "phase": "01-a", "status": "green", "summary": "ok",
            "deviations": [], "errors": [], "verification": "tests -> PASS", "commit": "",
        })
        msg = self._message_file(batch)

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(msg))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.json_out(proc)
        self.assertEqual(body["status"], "OK")
        self.assertTrue(body["pushed"], f"push should succeed against the bare remote: {body}")
        self.assertEqual(body["branch"], "main")
        self.assertTrue(body["sha"], "sha should be non-empty")
        self.assert_status_lines_shape(body["statusLines"])
        self.assertEqual(body["statusLines"][0]["label"], "Commit")
        self.assertEqual(body["statusLines"][0]["icon"], "done")

        done_path = batch / "done" / "01-a.md"
        self.assertTrue(done_path.is_file(), "green commit should move the .md file into done/")
        self.assertFalse((batch / "01-a.md").exists())

        phases = self._report_json(batch)["phases"]
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0]["commit"], body["sha"])

        self.assertEqual(self._head_sha(repo), body["sha"])
        self.assertEqual(self._trailer(repo, "CFQ-Batch-Number"), "42")
        self.assertEqual(self._trailer(repo, "CFQ-Batch"), "042-2026-03-01-committopic")
        self.assertEqual(self._trailer(repo, "CFQ-Phase"), "01-a")
        self.assertEqual(self._trailer(repo, "CFQ-Phase-Status"), "green")

        remote_sha = self.run_clean(
            "git", "log", "-1", "--format=%H", "origin/main", cwd=repo,
        ).stdout.strip()
        self.assertEqual(remote_sha, body["sha"], "commit should have been pushed to the bare remote")

        registered = self.run_cfq("registry", "list").stdout
        self.assertIn(str(repo), registered, "repo should be registered by phase commit")

    def _commit_phase_diffstat(self, repo, batch, stage):
        """Runs `stage()` to stage a change, commits phase 01-a through `phase commit` and returns
        the recorded entry."""
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        stage()
        pf = self._phase_file(batch, {
            "phase": "01-a", "status": "green", "summary": "ok",
            "deviations": [], "errors": [], "verification": "tests -> PASS", "commit": "",
        })
        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(self._message_file(batch)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.json_out(proc)["status"], "OK")
        return self._report_json(batch)["phases"][0]

    def test_commit_records_diffstat_for_modified_and_added_files(self):
        repo, batch = self._git_batch("ds-repo", "043-2026-03-01-diffstat")
        (repo / "old.txt").write_text("a\nb\nc\nd\n")
        self.run_clean("git", "add", "old.txt", cwd=repo)
        self.run_clean("git", "commit", "-q", "-m", "base", cwd=repo)

        def stage():
            (repo / "old.txt").write_text("a\nX\nY\nZ\nc\nd\n")  # +3 / -1 (b replaced by X,Y,Z)
            (repo / "new.txt").write_text("1\n2\n3\n4\n5\n")
            self.run_clean("git", "add", "old.txt", "new.txt", cwd=repo)

        entry = self._commit_phase_diffstat(repo, batch, stage)
        self.assertEqual(entry["diffstat"], {
            "files": 2, "insertions": 8, "deletions": 1,
            "paths": [
                {"path": "new.txt", "added": 5, "deleted": 0},
                {"path": "old.txt", "added": 3, "deleted": 1},
            ],
        })

    def test_commit_diffstat_binary_file_has_null_counts(self):
        repo, batch = self._git_batch("ds-bin-repo", "044-2026-03-01-diffstat")

        def stage():
            (repo / "blob.bin").write_bytes(b"\x00\x01\x02\xff\x00")
            (repo / "t.txt").write_text("x\n")
            self.run_clean("git", "add", "blob.bin", "t.txt", cwd=repo)

        stat = self._commit_phase_diffstat(repo, batch, stage)["diffstat"]
        self.assertEqual(stat["files"], 2)
        self.assertEqual((stat["insertions"], stat["deletions"]), (1, 0))
        self.assertIn({"path": "blob.bin", "added": None, "deleted": None}, stat["paths"])

    def test_commit_diffstat_leaves_out_queue_paths(self):
        repo, batch = self._git_batch("ds-queue-repo", "045-2026-03-01-diffstat")

        def stage():
            (repo / "keep.txt").write_text("k\n")
            queue_file = repo / ".claude" / "cfq" / "todo" / "x.md"
            queue_file.parent.mkdir(parents=True)
            queue_file.write_text("q\nq\nq\n")
            self.run_clean("git", "add", "keep.txt", cwd=repo)
            self.run_clean("git", "add", "-f", ".claude/cfq/todo/x.md", cwd=repo)

        stat = self._commit_phase_diffstat(repo, batch, stage)["diffstat"]
        self.assertEqual(stat, {
            "files": 1, "insertions": 1, "deletions": 0,
            "paths": [{"path": "keep.txt", "added": 1, "deleted": 0}],
        })

    def test_commit_diffstat_rename_is_deletion_plus_addition(self):
        repo, batch = self._git_batch("ds-rename-repo", "046-2026-03-01-diffstat")
        (repo / "before.txt").write_text("one\ntwo\nthree\n")
        self.run_clean("git", "add", "before.txt", cwd=repo)
        self.run_clean("git", "commit", "-q", "-m", "base", cwd=repo)

        def stage():
            self.run_clean("git", "mv", "before.txt", "after.txt", cwd=repo)

        stat = self._commit_phase_diffstat(repo, batch, stage)["diffstat"]
        self.assertEqual(stat["paths"], [
            {"path": "after.txt", "added": 3, "deleted": 0},
            {"path": "before.txt", "added": 0, "deleted": 3},
        ])
        self.assertEqual((stat["files"], stat["insertions"], stat["deletions"]), (2, 3, 3))

    def test_commit_diffstat_helper_returns_none_on_git_failure(self):
        repo = self._init_repo("ds-fail-repo")
        self.assertIsNone(cfq_phase.commit_diffstat(str(repo), "0" * 40))

    def test_commit_survives_diffstat_failure(self):
        repo, batch = self._git_batch("ds-nofail-repo", "047-2026-03-01-diffstat")
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {
            "phase": "01-a", "status": "green", "summary": "ok",
            "deviations": [], "errors": [], "verification": "tests -> PASS", "commit": "",
        })
        args = argparse.Namespace(
            dir=str(batch), phase_file=str(pf), message_file=str(self._message_file(batch)),
        )
        out = io.StringIO()
        env = {"HOME": str(self.home), "CFQ_PORTAL_SYNC": "0"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(cfq_phase, "commit_diffstat", return_value=None), \
                contextlib.redirect_stdout(out):
            cfq_phase.cmd_commit(args)
        self.assertEqual(json.loads(out.getvalue())["status"], "OK")
        entry = self._report_json(batch)["phases"][0]
        self.assertTrue(entry["commit"])
        self.assertNotIn("diffstat", entry)

    def _checkout_off_base(self, repo, branch, base="origin/main"):
        self.run_clean("git", "checkout", "-q", "-b", branch, base, cwd=repo)

    def _upstream(self, repo):
        return self.run_clean(
            "git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=repo,
        ).stdout.strip()

    def test_commit_pushes_when_upstream_is_base_branch(self):
        repo, batch = self._git_batch("commit-repo-3", "2026-03-07-thirdtopic")
        self._checkout_off_base(repo, "cfq/002-x")
        self.assertEqual(
            self._upstream(repo), "origin/main",
            "precondition: git's own branch.autoSetupMerge default must still track the base branch"
            " here, or this test no longer reproduces the finding",
        )

        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})
        msg = self._message_file(batch)

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(msg))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.json_out(proc)
        self.assertTrue(body["pushed"], f"push should retarget to the branch's own name: {body}")

        remote_branches = self.run_clean("git", "ls-remote", "origin", "cfq/002-x", cwd=repo).stdout
        self.assertTrue(remote_branches.strip(), "cfq/002-x should now exist on the remote")
        self.assertEqual(
            self._upstream(repo), "origin/cfq/002-x",
            "upstream should now be retracked to the branch's own name",
        )

    def test_commit_second_phase_after_retracking_uses_plain_push(self):
        repo, batch = self._git_batch("commit-repo-4", "2026-03-08-fourthtopic")
        self._checkout_off_base(repo, "cfq/003-y")
        self._write_phase_md(batch, "01-a")
        self._write_phase_md(batch, "02-b")
        self._write_report(batch, [])

        self._stage_change(repo, "one.txt")
        pf1 = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})
        proc1 = self.run_cfq("phase", "commit", str(batch), str(pf1), str(self._message_file(batch, "First\n")))
        self.assertEqual(proc1.returncode, 0, proc1.stderr)
        self.assertEqual(self._upstream(repo), "origin/cfq/003-y", "first commit should have retracked")

        self._stage_change(repo, "two.txt", "more\n")
        pf2 = self._phase_file(batch, {"phase": "02-b", "status": "green", "summary": "ok"})
        proc2 = self.run_cfq("phase", "commit", str(batch), str(pf2), str(self._message_file(batch, "Second\n")))
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        body2 = self.json_out(proc2)
        self.assertTrue(body2["pushed"], f"second phase's plain push should still succeed: {body2}")

    def test_commit_second_phase_on_same_branch_still_pushes(self):
        repo, batch = self._git_batch("commit-repo-2", "2026-03-02-secondtopic")
        self._write_phase_md(batch, "01-a")
        self._write_phase_md(batch, "02-b")
        self._write_report(batch, [])

        self._stage_change(repo, "one.txt")
        pf1 = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})
        proc1 = self.run_cfq("phase", "commit", str(batch), str(pf1), str(self._message_file(batch, "First\n")))
        self.assertEqual(proc1.returncode, 0, proc1.stderr)

        self._stage_change(repo, "two.txt", "more\n")
        pf2 = self._phase_file(batch, {"phase": "02-b", "status": "green", "summary": "ok"})
        proc2 = self.run_cfq("phase", "commit", str(batch), str(pf2), str(self._message_file(batch, "Second\n")))
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        body2 = self.json_out(proc2)
        self.assertTrue(body2["pushed"], f"second phase's plain push should still succeed: {body2}")

    def test_commit_nothing_staged_aborts(self):
        repo, batch = self._git_batch("commit-empty", "2026-03-03-emptytopic", with_remote=False)
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        pf = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})
        msg = self._message_file(batch)
        before_sha = self._head_sha(repo)

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(msg))
        self.assertNotEqual(proc.returncode, 0, "commit with nothing staged should fail")
        body = self.json_out(proc)
        self.assertEqual(body["status"], "NOTHING_STAGED")
        self.assert_status_lines_shape(body["statusLines"])
        commit_line = body["statusLines"][0]
        self.assertEqual(commit_line["label"], "Commit")
        self.assertEqual(commit_line["detail"], "nothing staged")
        self.assertNotEqual(
            commit_line["text"], cfq_phase.commit_status_line(
                {"status": "OK", "branch": "main", "pushed": True},
            )["text"],
            msg="NOTHING_STAGED's rendered Commit line must differ from OK's",
        )
        self.assertTrue((batch / "01-a.md").is_file(), "phase file must stay in place")
        self.assertEqual(self._report_json(batch)["phases"], [], "no ledger entry should be written")
        self.assertEqual(self._head_sha(repo), before_sha, "no commit should have been made")

    def test_commit_rejects_red_status(self):
        repo, batch = self._git_batch("commit-red", "2026-03-04-redtopic", with_remote=False)
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {"phase": "01-a", "status": "red", "summary": "boom", "errors": ["x"]})
        msg = self._message_file(batch)

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(msg))
        self.assertNotEqual(proc.returncode, 0, "commit should reject a red phase")
        self.assertIn("phase record", proc.stderr, "error should point to phase record for red phases")

    def test_commit_push_failure_is_non_fatal(self):
        repo, batch = self._git_batch("commit-badremote", "2026-03-05-badremotetopic", with_remote=False)
        self.run_clean(
            "git", "remote", "add", "origin", str(self._repos_dir / "does-not-exist.git"), cwd=repo,
        )
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})
        msg = self._message_file(batch)

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(msg))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.json_out(proc)
        self.assertEqual(body["status"], "OK")
        self.assertFalse(body["pushed"], f"push against an unreachable remote should be reported, not fatal: {body}")
        self.assertTrue(body.get("pushError"), "pushError should be non-empty when push fails")

        self.assertTrue((batch / "done" / "01-a.md").is_file(), "the phase should still be recorded")
        phases = self._report_json(batch)["phases"]
        self.assertEqual(phases[0]["commit"], body["sha"], "the commit SHA should still be backfilled")

    def test_commit_failure_leaves_phase_untouched(self):
        repo, batch = self._git_batch("commit-hookfail", "2026-03-06-hookfailtopic", with_remote=False)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})
        msg = self._message_file(batch)
        before_sha = self._head_sha(repo)

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(msg))
        self.assertNotEqual(proc.returncode, 0, "a failing pre-commit hook should fail the transaction")
        body = self.json_out(proc)
        self.assertEqual(body["status"], "COMMIT_FAILED")

        self.assertEqual(self._head_sha(repo), before_sha, "no commit should have been made")
        self.assertTrue((batch / "01-a.md").is_file(), "phase file must stay in the batch dir")
        self.assertFalse((batch / "done").exists(), "done/ must not be created")
        self.assertEqual(self._report_json(batch)["phases"], [], "no ledger entry should be written")

    # ---- status.json: every verb moves the phase's status and file together --------------------

    def _phases_status(self, batch):
        return json.loads((batch / "status.json").read_text())["phases"]

    def _record(self, batch, slug, status):
        pf = self._phase_file(batch, {
            "phase": slug, "status": status, "summary": "s", "errors": ["x"] if status == "red" else [],
        })
        return self.run_cfq("phase", "record", str(batch), str(pf), "--no-telemetry")

    def test_record_sets_status_done_or_error_and_retry_ends_done(self):
        batch = self._batch("2026-04-01-status")
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])

        self.assertEqual(self._record(batch, "01-a", "red").returncode, 0)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "error")
        self.assertTrue((batch / "01-a.md").is_file())
        self.assertFalse((batch / "done").exists())

        proc = self._record(batch, "01-a", "red")
        self.assertEqual(proc.returncode, 0, "a retried phase may go red again: " + proc.stderr)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "error")

        self.assertEqual(self._record(batch, "01-a", "green").returncode, 0)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "done")
        self.assertTrue((batch / "done" / "01-a.md").is_file())
        self.assertFalse((batch / "01-a.md").exists())

    def test_record_rolls_status_back_when_the_ledger_append_fails(self):
        batch = self._batch("2026-04-02-status")
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        (batch / "report.json").unlink()
        (batch / "report.json").mkdir()

        proc = self._record(batch, "01-a", "green")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "open")
        self.assertTrue((batch / "01-a.md").is_file(), "the file must be back in the batch root")
        self.assertFalse((batch / "done" / "01-a.md").exists())

    def test_commit_sets_status_done(self):
        repo, batch = self._git_batch("commit-status", "2026-04-03-statustopic", with_remote=False)
        self._write_phase_md(batch, "01-a")
        self._write_report(batch, [])
        self._stage_change(repo)
        pf = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "ok"})

        proc = self.run_cfq("phase", "commit", str(batch), str(pf), str(self._message_file(batch)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "done")

    def test_reopen_sets_status_open(self):
        batch = self._batch("2026-04-04-status")
        (batch / "done").mkdir()
        (batch / "done" / "01-a.md").write_text("# Phase 01\n")
        self._write_report(batch, [{"phase": "01-a", "status": "green", "commit": "aaa"}])
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "done")

        proc = self.run_cfq("phase", "reopen", str(batch), "01-a")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "open")
        self.assertTrue((batch / "01-a.md").is_file())
        self.assertIn("reopened", self._report_json(batch)["phases"][0])

    def test_reopen_rolls_status_back_when_the_ledger_write_fails(self):
        batch = self._batch("2026-04-05-status")
        (batch / "done").mkdir()
        (batch / "done" / "01-a.md").write_text("# Phase 01\n")
        self._write_report(batch, [{"phase": "01-a", "status": "green", "commit": "aaa"}])
        # a directory in the way of the tmp file makes render.write_json fail after the move
        (batch / "report.json.tmp").mkdir()

        proc = self.run_cfq("phase", "reopen", str(batch), "01-a")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "done")
        self.assertTrue((batch / "done" / "01-a.md").is_file())
        self.assertFalse((batch / "01-a.md").exists())

    # ---- skip / unskip -------------------------------------------------------------------------

    def _skip_batch(self, name, **status):
        batch = self._batch(name)
        for slug in ("01-a", "02-b", "03-c"):
            self._write_phase_md(batch, slug)
        self._write_report(batch, [])
        write_status(batch, **status)
        return batch

    def test_skip_open_phase_records_state_file_and_ledger(self):
        batch = self._skip_batch("2026-04-10-skip")

        proc = self.run_cfq("phase", "skip", str(batch), "02", "--reason", "obsolete")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.json_out(proc)
        self.assertEqual(body["status"], "OK")
        self.assertEqual(body["phase"], "02-b")
        self.assertEqual(body["previous"], "open")
        self.assertEqual(body["reason"], "obsolete")
        self.assertEqual(body["path"], str(batch / "skipped" / "02-b.md"))
        self.assert_status_lines_shape(body["statusLines"])
        self.assertEqual(body["statusLines"][0]["label"], "Skip")
        self.assertEqual(body["statusLines"][0]["detail"], "02-b · was open · obsolete")

        self.assertTrue((batch / "skipped" / "02-b.md").is_file())
        self.assertFalse((batch / "02-b.md").exists())
        entry = self._phases_status(batch)["02-b"]
        self.assertEqual(
            (entry["status"], entry["reason"], entry["previous"]), ("skipped", "obsolete", "open"))

        ledger = self._report_json(batch)["phases"]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(
            {k: ledger[0][k] for k in ("phase", "status", "summary", "previous")},
            {"phase": "02-b", "status": "skipped", "summary": "obsolete", "previous": "open"},
        )
        self.assertTrue(ledger[0]["finished"])

    def test_skip_error_phase_then_unskip_returns_it_to_error(self):
        batch = self._skip_batch("2026-04-11-skip", **{"01_a": "error"})

        proc = self.run_cfq("phase", "skip", str(batch), "01-a", "--reason", "later")
        self.assertEqual(self.json_out(proc)["previous"], "error")
        self.assertEqual(self._report_json(batch)["phases"][0]["previous"], "error")

        proc = self.run_cfq("phase", "unskip", str(batch), "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.json_out(proc)
        self.assertEqual((body["status"], body["phase"], body["restored"]), ("OK", "01-a", "error"))
        self.assertEqual(body["statusLines"][0]["label"], "Unskip")
        self.assertEqual(body["statusLines"][0]["detail"], "01-a · back to error")
        self.assertEqual(self._phases_status(batch)["01-a"]["status"], "error")
        self.assertTrue((batch / "01-a.md").is_file())
        self.assertFalse((batch / "skipped" / "01-a.md").exists())
        self.assertIn("unskipped", self._report_json(batch)["phases"][0])

    def test_unskip_marks_the_last_open_skip_entry_only(self):
        batch = self._skip_batch("2026-04-12-skip")
        for _ in range(2):
            self.run_cfq("phase", "skip", str(batch), "01-a", check=True)
            self.run_cfq("phase", "unskip", str(batch), "01-a", check=True)
        self.run_cfq("phase", "skip", str(batch), "01-a", check=True)
        self.run_cfq("phase", "unskip", str(batch), "01-a", check=True)

        ledger = self._report_json(batch)["phases"]
        self.assertEqual(len(ledger), 3)
        self.assertTrue(all("unskipped" in e for e in ledger))

    def test_skip_accepts_slug_and_stores_empty_reason_without_flag(self):
        batch = self._skip_batch("2026-04-13-skip")
        proc = self.run_cfq("phase", "skip", str(batch), "03-c")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = self.json_out(proc)
        self.assertEqual((body["phase"], body["reason"]), ("03-c", ""))
        self.assertEqual(body["statusLines"][0]["detail"], "03-c · was open")
        self.assertEqual(self._report_json(batch)["phases"][0]["summary"], "")
        self.assertNotIn("reason", self._phases_status(batch)["03-c"])

    def test_skip_refuses_done_and_already_skipped_and_changes_nothing(self):
        batch = self._skip_batch("2026-04-14-skip", **{"01_a": "done"})
        self.run_cfq("phase", "skip", str(batch), "02", check=True)
        before = ((batch / "status.json").read_text(), (batch / "report.json").read_text())

        for ref in ("01", "02"):
            with self.subTest(ref=ref):
                proc = self.run_cfq("phase", "skip", str(batch), ref)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(json.loads(proc.stderr)["status"], "INVALID_TRANSITION")
        after = ((batch / "status.json").read_text(), (batch / "report.json").read_text())
        self.assertEqual(before, after)
        self.assertTrue((batch / "done" / "01-a.md").is_file())
        self.assertTrue((batch / "skipped" / "02-b.md").is_file())

    def test_unskip_refuses_a_phase_that_is_not_skipped(self):
        batch = self._skip_batch("2026-04-15-skip")
        proc = self.run_cfq("phase", "unskip", str(batch), "01")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stderr)["status"], "NOT_SKIPPED")
        self.assertTrue((batch / "01-a.md").is_file())

    def test_skip_and_unskip_unknown_phase(self):
        batch = self._skip_batch("2026-04-16-skip")
        for verb in ("skip", "unskip"):
            with self.subTest(verb=verb):
                proc = self.run_cfq("phase", verb, str(batch), "09")
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(json.loads(proc.stderr)["status"], "UNKNOWN_PHASE")

    def test_every_verb_refuses_a_batch_without_status_json(self):
        batch = self._batch("2026-04-17-nostatus")
        self._write_phase_md(batch, "01-a")
        (batch / "done").mkdir()
        (batch / "done" / "02-b.md").write_text("# Phase 02\n")
        pf = self._phase_file(batch, {"phase": "01-a", "status": "green", "summary": "x"})
        msg = self._message_file(batch)

        calls = [
            ("record", str(batch), str(pf), "--no-telemetry"),
            ("commit", str(batch), str(pf), str(msg)),
            ("reopen", str(batch), "02-b"),
            ("skip", str(batch), "01-a"),
            ("unskip", str(batch), "01-a"),
        ]
        for call in calls:
            with self.subTest(verb=call[0]):
                proc = self.run_cfq("phase", *call)
                self.assertNotEqual(proc.returncode, 0)
                err = json.loads(proc.stderr)
                self.assertEqual(err["status"], "STATUS_FILE_MISSING")
                self.assertEqual(err["detail"], str(batch))
        self.assertTrue((batch / "01-a.md").is_file())
        self.assertTrue((batch / "done" / "02-b.md").is_file())
        self.assertFalse((batch / "skipped").exists())

    def test_every_verb_refuses_an_unreadable_status_json(self):
        batch = self._skip_batch("2026-04-18-badstatus")
        (batch / "status.json").write_text("{not json")
        proc = self.run_cfq("phase", "skip", str(batch), "01")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stderr)["status"], "STATUS_FILE_INVALID")
        self.assertTrue((batch / "01-a.md").is_file())

    def test_skip_falls_back_when_the_ledger_append_fails(self):
        batch = self._skip_batch("2026-04-19-skip", **{"01_a": "error"})
        (batch / "report.json").unlink()
        (batch / "report.json").mkdir()

        proc = self.run_cfq("phase", "skip", str(batch), "01-a")
        self.assertNotEqual(proc.returncode, 0)
        entry = self._phases_status(batch)["01-a"]
        self.assertEqual(entry["status"], "error")
        self.assertNotIn("previous", entry)
        self.assertTrue((batch / "01-a.md").is_file())
        self.assertFalse((batch / "skipped" / "01-a.md").exists())


if __name__ == "__main__":
    unittest.main()
