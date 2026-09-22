"""Self-test for scripts/cfq_phase.py: `record`/`commit`/`reopen` as the transactional calls that
replace the improvised "move the file, then remember to call report append" sequence -- `commit`
additionally folds in the phase's own Git commit, push, SHA backfill and registry add.
"""

import json
import pathlib
import unittest

from cfq_testlib import CfqTestCase

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


if __name__ == "__main__":
    unittest.main()
