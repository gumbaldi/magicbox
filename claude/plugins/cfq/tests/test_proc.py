"""Unit tests for cfq_lib/proc.py, the shared bin/cfq / git subprocess helper module (batch
022 phase 01). Exercises the module directly rather than through `bin/cfq`, since these are
library-level guarantees other scripts import against."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cfq_testlib import PLUGIN_ROOT, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import proc  # noqa: E402


class ProcTest(unittest.TestCase):
    def setUp(self):
        home_dir = tempfile.TemporaryDirectory()
        self.addCleanup(home_dir.cleanup)
        self.home = pathlib.Path(home_dir.name)

        repo_dir = tempfile.TemporaryDirectory()
        self.addCleanup(repo_dir.cleanup)
        self.repo = pathlib.Path(repo_dir.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CFQ_")}
        self.env["HOME"] = str(self.home)

    def test_cfq_bin_resolves_from_module_location_not_caller(self):
        self.assertEqual(proc.CFQ_BIN, PLUGIN_ROOT / "bin" / "cfq")
        self.assertTrue(proc.CFQ_BIN.is_file())

    def test_git_returncode_and_is_git_repo(self):
        self.assertEqual(proc.git(self.repo, "rev-parse", "--git-dir").returncode, 0)
        self.assertTrue(proc.is_git_repo(self.repo))

        with tempfile.TemporaryDirectory() as non_repo:
            self.assertFalse(proc.is_git_repo(pathlib.Path(non_repo)))

    def test_git_check_flag_matches_subprocess_semantics(self):
        result = proc.git(self.repo, "no-such-cmd")
        self.assertNotEqual(result.returncode, 0, msg="check=False must not raise")

        with self.assertRaises(subprocess.CalledProcessError):
            proc.git(self.repo, "no-such-cmd", check=True)

    def test_capture_strips_trailing_newlines_only(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="  value \n\n")
        self.assertEqual(proc.capture(result), "  value ")

    def test_cfq_run_and_settings_get(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            result = proc.cfq_run(
                "settings", "get", "--repo", str(self.repo), "codeLanguage", env=self.env
            )
            value = proc.settings_get(self.repo, "codeLanguage")

        self.assertEqual(result.returncode, 0)
        self.assertIsInstance(result.stdout, str)
        self.assertEqual(value, result.stdout.strip())

    def test_cfq_run_merged_combines_stderr_into_stdout(self):
        result = proc.cfq_run_merged("no-such-noun")
        self.assertIn("unknown noun", result.stdout)

    def test_cfq_argv_non_windows_skips_bash_lookup(self):
        with mock.patch.object(proc, "_IS_WINDOWS", False), \
                mock.patch("shutil.which") as which:
            result = proc.cfq_argv("registry", "list")
        self.assertEqual(result, [str(proc.CFQ_BIN), "registry", "list"])
        which.assert_not_called()

    def test_cfq_argv_windows_resolves_git_bash(self):
        bash_path = "C:/Program Files/Git/usr/bin/bash.exe"
        with mock.patch.object(proc, "_IS_WINDOWS", True), \
                mock.patch("shutil.which", return_value=bash_path) as which:
            result = proc.cfq_argv("registry", "list")
        self.assertEqual(result, [bash_path, str(proc.CFQ_BIN), "registry", "list"])
        which.assert_called_once_with("bash")

    def test_cfq_argv_windows_no_args(self):
        bash_path = "C:/Program Files/Git/usr/bin/bash.exe"
        with mock.patch.object(proc, "_IS_WINDOWS", True), \
                mock.patch("shutil.which", return_value=bash_path):
            result = proc.cfq_argv()
        self.assertEqual(result, [bash_path, str(proc.CFQ_BIN)])

    def test_cfq_argv_windows_no_bash_on_path_raises(self):
        with mock.patch.object(proc, "_IS_WINDOWS", True), \
                mock.patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                proc.cfq_argv("x")
        self.assertIn("Git Bash", str(ctx.exception))

    def test_cfq_run_and_cfq_run_merged_route_through_cfq_argv_on_windows(self):
        bash_path = "C:/Program Files/Git/usr/bin/bash.exe"
        with mock.patch.object(proc, "_IS_WINDOWS", True), \
                mock.patch("shutil.which", return_value=bash_path), \
                mock.patch.object(proc.subprocess, "run") as run:
            proc.cfq_run("a", env={"K": "v"})
            proc.cfq_run_merged("a")

        self.assertEqual(run.call_count, 2)
        run_args, run_kwargs = run.call_args_list[0]
        merged_args, _merged_kwargs = run.call_args_list[1]
        self.assertEqual(run_args[0][0], bash_path)
        self.assertEqual(run_kwargs.get("env"), {"K": "v"})
        self.assertEqual(merged_args[0][0], bash_path)


if __name__ == "__main__":
    unittest.main()
