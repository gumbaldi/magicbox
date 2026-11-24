"""Tests for the phase commit hook trust store (`cfq_lib/hook_trust.py`) and the
`settings trust-hook` verb."""

import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

from cfq_testlib import CFQ_BIN, CfqTestCase

from cfq_lib import hook_trust

HOOK = "echo checked"


class HookTrustModuleTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.make_repo()

    def test_nothing_trusted_by_default(self):
        self.assertFalse(hook_trust.is_trusted(self.repo, HOOK))
        self.assertEqual(hook_trust.status(self.repo, HOOK), "untrusted")

    def test_store_lives_under_home_claude_cfq(self):
        self.assertEqual(hook_trust.store_path(), self.home / ".claude" / "cfq" / "trusted-hooks.json")

    def test_trust_then_is_trusted(self):
        hook_trust.trust(self.repo, HOOK)
        self.assertTrue(hook_trust.is_trusted(self.repo, HOOK))
        self.assertEqual(hook_trust.status(self.repo, HOOK), "trusted")

    def test_changed_command_is_untrusted(self):
        hook_trust.trust(self.repo, HOOK)
        self.assertFalse(hook_trust.is_trusted(self.repo, HOOK + " --more"))

    def test_other_repo_is_untrusted(self):
        hook_trust.trust(self.repo, HOOK)
        other = self.make_repo("other")
        self.assertFalse(hook_trust.is_trusted(other, HOOK))

    def test_revoke_removes_entry(self):
        hook_trust.trust(self.repo, HOOK)
        self.assertTrue(hook_trust.revoke(self.repo))
        self.assertFalse(hook_trust.is_trusted(self.repo, HOOK))
        self.assertFalse(hook_trust.revoke(self.repo))

    def test_empty_command_is_unset(self):
        self.assertEqual(hook_trust.status(self.repo, ""), "unset")
        self.assertFalse(hook_trust.is_trusted(self.repo, ""))

    def test_corrupt_file_reads_as_nothing_trusted(self):
        path = hook_trust.store_path()
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        self.assertFalse(hook_trust.is_trusted(self.repo, HOOK))
        path.write_text("[1, 2]")
        self.assertFalse(hook_trust.is_trusted(self.repo, HOOK))

    def test_stored_shape_is_realpath_to_sha256_only(self):
        hook_trust.trust(self.repo, HOOK)
        content = json.loads(hook_trust.store_path().read_text())
        self.assertEqual(content, {os.path.realpath(self.repo): hook_trust.command_hash(HOOK)})
        self.assertEqual(len(hook_trust.command_hash(HOOK)), 64)

    @unittest.skipIf(sys.platform == "win32", "POSIX file modes")
    def test_file_mode_is_0600(self):
        hook_trust.trust(self.repo, HOOK)
        self.assertEqual(hook_trust.store_path().stat().st_mode & 0o777, 0o600)


class TrustHookCliTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.store = self.home / ".claude" / "cfq" / "trusted-hooks.json"
        self.run_cfq("settings", "set", "--repo", str(self.repo), "phaseCommitCommand", HOOK, check=True)

    def test_without_terminal_fails_and_writes_nothing(self):
        proc = self.run_cfq("settings", "trust-hook", "--repo", str(self.repo))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stderr)["status"], "NOT_A_TERMINAL")
        self.assertFalse(self.store.exists())

    def test_status_and_revoke_work_without_terminal(self):
        proc = self.run_cfq("settings", "trust-hook", "--repo", str(self.repo), "--status")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "untrusted")
        self.assertEqual(out["hash"], hook_trust.command_hash(HOOK)[:12])
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps({os.path.realpath(self.repo): hook_trust.command_hash(HOOK)}))
        proc = self.run_cfq("settings", "trust-hook", "--repo", str(self.repo), "--status")
        self.assertEqual(self.json_out(proc)["status"], "trusted")
        proc = self.run_cfq("settings", "trust-hook", "--repo", str(self.repo), "--revoke")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.store.read_text()), {})

    def _run_in_pty(self, answer, *extra):
        import pty

        master, slave = pty.openpty()
        env = self._base_env()
        env["HOME"] = str(self.home)
        try:
            proc = subprocess.Popen(
                [str(CFQ_BIN), "settings", "trust-hook", "--repo", str(self.repo), *extra],
                stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=env, close_fds=True,
            )
            os.close(slave)
            slave = None
            os.write(master, answer.encode())
            _, err = proc.communicate(timeout=30)
        finally:
            if slave is not None:
                os.close(slave)
            os.close(master)
        return proc.returncode, err.decode()

    @unittest.skipIf(sys.platform == "win32", "needs a pseudo-terminal")
    def test_terminal_yes_stores_hash(self):
        code, err = self._run_in_pty("y\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            json.loads(self.store.read_text()),
            {os.path.realpath(self.repo): hook_trust.command_hash(HOOK)},
        )

    @unittest.skipIf(sys.platform == "win32", "needs a pseudo-terminal")
    def test_terminal_no_or_empty_stores_nothing(self):
        for answer in ("n\n", "\n"):
            code, err = self._run_in_pty(answer)
            self.assertEqual(code, 0, err)
            self.assertFalse(self.store.exists())

    @unittest.skipIf(sys.platform == "win32", "needs a pseudo-terminal")
    def test_terminal_with_empty_command_exits_1(self):
        self.run_cfq("settings", "unset", "--repo", str(self.repo), "phaseCommitCommand", check=True)
        code, _ = self._run_in_pty("y\n")
        self.assertEqual(code, 1)
        self.assertFalse(self.store.exists())


if __name__ == "__main__":
    unittest.main()
