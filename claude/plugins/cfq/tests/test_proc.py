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

    def test_git_passes_input_to_stdin(self):
        blob = self.repo / "blob.txt"
        blob.write_text("abc\n")
        expected = proc.git(self.repo, "hash-object", "blob.txt")
        result = proc.git(self.repo, "hash-object", "--stdin", input="abc\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected.stdout)

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


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _make_repo(root, name, branch):
    """A repository whose first branch is `branch` (named explicitly, so the host's
    init.defaultBranch plays no role) with one commit."""
    repo = pathlib.Path(root) / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    return repo


class DefaultBranchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def _clone_of(self, branch):
        origin = _make_repo(self.root, "origin", branch)
        clone = pathlib.Path(self.root) / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(clone)], capture_output=True, check=True
        )
        _git(clone, "config", "user.email", "t@example.invalid")
        _git(clone, "config", "user.name", "t")
        return origin, clone

    def _rev(self, repo, ref):
        return _git(repo, "rev-parse", ref)

    def test_origin_head_names_the_default_branch(self):
        _origin, clone = self._clone_of("trunk")
        name, ref = proc.default_branch(clone, True)
        self.assertEqual(name, "trunk")
        self.assertEqual(self._rev(clone, ref), self._rev(clone, "refs/remotes/origin/trunk"))

    def test_without_origin_head_main_then_master_on_origin(self):
        _origin, clone = self._clone_of("main")
        _git(clone, "remote", "set-head", "origin", "-d")
        name, ref = proc.default_branch(clone, True)
        self.assertEqual(name, "main")
        self.assertEqual(self._rev(clone, ref), self._rev(clone, "refs/remotes/origin/main"))

    def test_without_origin_head_only_master_on_origin(self):
        _origin, clone = self._clone_of("master")
        _git(clone, "remote", "set-head", "origin", "-d")
        name, ref = proc.default_branch(clone, True)
        self.assertEqual(name, "master")
        self.assertEqual(self._rev(clone, ref), self._rev(clone, "refs/remotes/origin/master"))

    def test_remote_ref_wins_over_a_local_branch_that_is_behind(self):
        origin, clone = self._clone_of("main")
        _git(origin, "commit", "-q", "--allow-empty", "-m", "second")
        _git(clone, "fetch", "-q", "origin")
        remote_commit = self._rev(clone, "refs/remotes/origin/main")
        self.assertNotEqual(remote_commit, self._rev(clone, "refs/heads/main"))
        name, ref = proc.default_branch(clone, True)
        self.assertEqual(name, "main")
        self.assertEqual(self._rev(clone, ref), remote_commit)

    def test_not_remote_checked_uses_the_local_branch(self):
        origin, clone = self._clone_of("main")
        _git(origin, "commit", "-q", "--allow-empty", "-m", "second")
        _git(clone, "fetch", "-q", "origin")
        name, ref = proc.default_branch(clone, False)
        self.assertEqual(name, "main")
        self.assertEqual(self._rev(clone, ref), self._rev(clone, "refs/heads/main"))
        self.assertNotEqual(self._rev(clone, ref), self._rev(clone, "refs/remotes/origin/main"))

    def test_no_remote_only_master(self):
        repo = _make_repo(self.root, "solo", "master")
        name, ref = proc.default_branch(repo, False)
        self.assertEqual(name, "master")
        self.assertEqual(self._rev(repo, ref), self._rev(repo, "refs/heads/master"))

    def test_no_remote_neither_main_nor_master_falls_back_to_main(self):
        repo = _make_repo(self.root, "solo", "work")
        name, _ref = proc.default_branch(repo, False)
        self.assertEqual(name, "main")


if __name__ == "__main__":
    unittest.main()
