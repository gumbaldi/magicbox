"""Migrated from test-lock.sh (bin/cfq lock acquire/release/status, takeover)."""

import json
import os
import time
import unittest

from cfq_testlib import CfqTestCase


class LockTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir(parents=True)
        self.lock = self.repo / ".claude" / "cfq" / ".lock"
        slug = str(self.repo).replace("/", "-")
        self.tdir = self.home / ".claude" / "projects" / slug

    def acquire(self, session, batch):
        return self.run_cfq(
            "lock", "acquire", str(self.repo), batch, env={"CLAUDE_CODE_SESSION_ID": session}
        )

    def release(self, session):
        return self.run_cfq(
            "lock", "release", str(self.repo), env={"CLAUDE_CODE_SESSION_ID": session}
        )

    def status(self):
        return self.run_cfq("lock", "status", str(self.repo))

    def test_01_fresh_acquire(self):
        proc = self.acquire("sidA", "batchA")
        self.assertEqual(proc.stdout.strip(), "OK batchA", msg="fresh acquire = " + proc.stdout)
        self.assertTrue(self.lock.is_file(), msg="lock file not created")

    def test_02_foreign_session_still_fresh_rejected(self):
        self.acquire("sidA", "batchA")
        proc = self.acquire("sidB", "batchB")
        self.assertNotEqual(
            proc.returncode, 0, msg="foreign acquire on a fresh lock should fail, got: " + proc.stderr
        )
        self.assertTrue(
            proc.stderr.startswith("LOCKED"), msg="rejection message = " + proc.stderr
        )

    def test_03_same_session_again_idempotent(self):
        self.acquire("sidA", "batchA")
        proc = self.acquire("sidA", "batchA")
        self.assertEqual(
            proc.stdout.strip(),
            "OK batchA (already held by this session)",
            msg="idempotent acquire = " + proc.stdout,
        )

    def test_04_stale_transcript_takeover(self):
        self.acquire("sidA", "batchA")
        self.tdir.mkdir(parents=True)
        transcript = self.tdir / "sidA.jsonl"
        transcript.touch()
        old = time.time() - 40 * 60
        os.utime(transcript, (old, old))

        proc = self.acquire("sidB", "batchB")
        self.assertIn("TAKEOVER", proc.stderr, msg="expected TAKEOVER, got: " + proc.stderr)

        holder = json.loads(self.lock.read_text())["session_id"]
        self.assertEqual(holder, "sidB", msg=f"holder after takeover = {holder}, want sidB")

    def test_05_fresh_transcript_rejected_again(self):
        self.acquire("sidA", "batchA")
        self.tdir.mkdir(parents=True)
        transcript_a = self.tdir / "sidA.jsonl"
        transcript_a.touch()
        old = time.time() - 40 * 60
        os.utime(transcript_a, (old, old))
        self.acquire("sidB", "batchB")
        (self.tdir / "sidB.jsonl").touch()

        proc = self.acquire("sidC", "batchC")
        self.assertNotEqual(
            proc.returncode,
            0,
            msg="acquire against a fresh transcript should fail, got: " + proc.stderr,
        )
        self.assertTrue(
            proc.stderr.startswith("LOCKED"), msg="rejection message = " + proc.stderr
        )

    def test_06_no_transcript_fallback_epoch_age(self):
        self.acquire("sidD", "batchD")
        data = json.loads(self.lock.read_text())
        data["epoch"] -= 3000
        self.lock.write_text(json.dumps(data))

        proc = self.acquire("sidE", "batchE")
        self.assertIn(
            "TAKEOVER", proc.stderr, msg="expected fallback TAKEOVER, got: " + proc.stderr
        )
        holder = json.loads(self.lock.read_text())["session_id"]
        self.assertEqual(
            holder, "sidE", msg=f"holder after fallback takeover = {holder}, want sidE"
        )

    def test_07_foreign_release_rejected_holder_release_frees(self):
        self.acquire("sidE", "batchE")
        proc = self.release("sidF")
        self.assertNotEqual(proc.returncode, 0, msg="foreign release should fail, got: " + proc.stderr)
        self.assertTrue(self.lock.is_file(), msg="lock removed by a foreign release")

        proc = self.release("sidE")
        self.assertEqual(proc.stdout.strip(), "FREE", msg="holder release = " + proc.stdout)
        self.assertFalse(self.lock.is_file(), msg="lock file still present after release")

    def test_08_status_free_alive_dead(self):
        proc = self.status()
        self.assertEqual(proc.stdout.strip(), "FREE", msg="status on unlocked repo = " + proc.stdout)

        self.acquire("sidG", "batchG")
        proc = self.status()
        self.assertTrue(
            proc.stdout.strip().startswith("ALIVE sidG batchG "),
            msg="status after acquire = " + proc.stdout,
        )

        data = json.loads(self.lock.read_text())
        data["epoch"] -= 3000
        self.lock.write_text(json.dumps(data))
        proc = self.status()
        self.assertTrue(
            proc.stdout.strip().startswith("DEAD sidG batchG "),
            msg="status once stale = " + proc.stdout,
        )

        self.release("sidG")


if __name__ == "__main__":
    unittest.main()
