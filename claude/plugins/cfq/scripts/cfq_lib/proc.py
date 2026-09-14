"""Shared bin/cfq / git subprocess helpers -- the common module behind the cfq_run/git/capture/
settings_get/is_git_repo copies that used to live separately in about 20 scripts under
scripts/cfq_*.py, left over from the per-script shell-to-Python ports. Only the wrapper bodies
live here; parsing a command's output and deciding what to do with a nonzero exit stay with each
caller.
"""

import pathlib
import subprocess

CFQ_BIN = pathlib.Path(__file__).resolve().parents[2] / "bin" / "cfq"


def cfq_run(*args, env=None):
    return subprocess.run([str(CFQ_BIN), *args], capture_output=True, text=True, env=env)


def cfq_run_merged(*args):
    """Mirrors the shell version's `$("$cfq" ... 2>&1)` -- stdout and stderr combined."""
    return subprocess.run(
        [str(CFQ_BIN), *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def git(repo, *args, check=False):
    """`git -C <repo> <args>`, always capture_output/text. check=True uses subprocess's own check
    semantics (raises CalledProcessError on a nonzero exit) -- a caller that needs the ported
    shell's `set -eu` die-on-failure behaviour instead (cfq_branch.py) keeps its own local
    wrapper on top of this one."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check
    )


def capture(proc):
    """Mirrors `$(cmd 2>/dev/null || true)`: whatever the command printed to stdout, trailing
    newlines stripped, regardless of exit code."""
    return proc.stdout.rstrip("\n")


def is_git_repo(repo):
    return git(repo, "rev-parse", "--git-dir").returncode == 0


def settings_get(repo, key):
    return cfq_run("settings", "get", "--repo", str(repo), key).stdout.strip()
