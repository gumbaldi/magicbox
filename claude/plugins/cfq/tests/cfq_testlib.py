"""Shared harness for the cfq test suite.

Not a test module itself — the name deliberately does not match ``test*.py`` so
``unittest discover`` and ``pytest`` both skip it while still importing it.
"""

import json
import os
import pathlib
import subprocess
import tempfile
import unittest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
CFQ_BIN = PLUGIN_ROOT / "bin" / "cfq"


class CfqTestCase(unittest.TestCase):
    def setUp(self):
        home_dir = tempfile.TemporaryDirectory()
        self.addCleanup(home_dir.cleanup)
        self.home = pathlib.Path(home_dir.name)

        repos_dir = tempfile.TemporaryDirectory()
        self.addCleanup(repos_dir.cleanup)
        self._repos_dir = pathlib.Path(repos_dir.name)

    def _base_env(self):
        return {k: v for k, v in os.environ.items() if not k.startswith("CFQ_")}

    def run_cfq(self, *args, home=None, env=None, cwd=None, check=False):
        run_env = self._base_env()
        run_env["HOME"] = str(home if home is not None else self.home)
        if env:
            run_env.update(env)
        return subprocess.run(
            [str(CFQ_BIN), *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=run_env,
            check=check,
        )

    def run_clean(self, *args, env=None, cwd=None, check=False):
        run_env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "")}
        if env:
            run_env.update(env)
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            cwd=cwd,
            env=run_env,
            check=check,
        )

    def json_out(self, proc):
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(f"could not parse JSON, raw stdout: {proc.stdout!r}")

    def make_repo(self, name="repo"):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
        (d / "README.md").write_text("init\n")
        subprocess.run(["git", "add", "README.md"], cwd=d, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, check=True)
        return d


def sh_source(script, func, *args):
    proc = subprocess.run(
        ["bash", "-c", '. "$1"; shift; "$@"', "_", str(script), func, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout
