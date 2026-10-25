"""Shared bin/cfq / git subprocess helpers -- the common module behind the cfq_argv/cfq_run/git/
capture/settings_get/is_git_repo copies that used to live separately in about 20 scripts under
scripts/cfq_*.py, left over from the per-script shell-to-Python ports, plus the default-branch
resolution (default_branch) that several scripts share. Only the wrapper bodies live here;
parsing a command's output and deciding what to do with a nonzero exit stay with each caller.
"""

import os
import pathlib
import shutil
import subprocess

CFQ_BIN = pathlib.Path(__file__).resolve().parents[2] / "bin" / "cfq"

_IS_WINDOWS = os.name == "nt"

ORIGIN_PREFIX = "refs/remotes/origin/"
HEADS_PREFIX = "refs/heads/"


def cfq_argv(*args):
    """argv that runs bin/cfq with args. Native Windows Python can't exec a shebang script
    (WinError 193), so there it goes through the bash on PATH -- resolved with shutil.which
    and passed as an absolute path, because a bare "bash" makes CreateProcess pick System32's
    WSL launcher before PATH."""
    if not _IS_WINDOWS:
        return [str(CFQ_BIN), *args]
    bash = shutil.which("bash")
    if bash is None:
        raise RuntimeError(
            "cfq: bash not found on PATH -- on Windows cfq needs Git Bash to run bin/cfq"
        )
    return [bash, str(CFQ_BIN), *args]


def cfq_run(*args, env=None):
    return subprocess.run(cfq_argv(*args), capture_output=True, text=True, env=env)


def cfq_run_merged(*args):
    """Mirrors the shell version's `$("$cfq" ... 2>&1)` -- stdout and stderr combined."""
    return subprocess.run(
        cfq_argv(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
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


def _ref_exists(repo, ref):
    return git(repo, "rev-parse", "--verify", "-q", ref).returncode == 0


def default_branch(repo, rchecked):
    """(name, ref) of the default branch: `origin/HEAD`, else `main`, else `master` -- looked up on
    `origin` once remote-checked, then (and when offline) among the local branches, falling back to
    `main`. `ref` is the `origin` ref when remote-checked and present, else the local ref."""
    if rchecked:
        result = git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
        name = result.stdout.strip() if result.returncode == 0 else ""
        if name.startswith("origin/"):
            name = name[len("origin/"):]
        if not name:
            name = next(
                (n for n in ("main", "master") if _ref_exists(repo, ORIGIN_PREFIX + n)), ""
            )
        if name:
            origin_ref = ORIGIN_PREFIX + name
            return name, origin_ref if _ref_exists(repo, origin_ref) else HEADS_PREFIX + name
    for name in ("main", "master"):
        if _ref_exists(repo, HEADS_PREFIX + name):
            return name, HEADS_PREFIX + name
    return "main", HEADS_PREFIX + "main"
