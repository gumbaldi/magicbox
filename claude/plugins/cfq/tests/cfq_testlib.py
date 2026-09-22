"""Shared harness for the cfq test suite.

Not a test module itself — the name deliberately does not match ``test*.py`` so
``unittest discover`` and ``pytest`` both skip it while still importing it.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
CFQ_BIN = PLUGIN_ROOT / "bin" / "cfq"

sys.path.insert(0, str(SCRIPTS_DIR))
from cfq_lib import text as cfq_text  # noqa: E402


class CfqTestCase(unittest.TestCase):
    def setUp(self):
        """Both roots are .resolve()d immediately: on macOS the system temp dir sits under
        /var, itself a symlink to /private/var, so the raw tempfile path and the canonical path
        `git rev-parse --show-toplevel` (or any other realpath-ing lookup) returns are two
        different strings for the same directory. Every fixture built from an unresolved root
        would then silently fail every registry/scan/preflight comparison downstream -- resolving
        once here keeps every derived path canonical from the start, matching what a real
        invocation always gets (repo roots reach `registry add` only after a skill's own
        `git rev-parse --show-toplevel`)."""
        home_dir = tempfile.TemporaryDirectory()
        self.addCleanup(home_dir.cleanup)
        self.home = pathlib.Path(home_dir.name).resolve()

        repos_dir = tempfile.TemporaryDirectory()
        self.addCleanup(repos_dir.cleanup)
        self._repos_dir = pathlib.Path(repos_dir.name).resolve()

    def _base_env(self):
        """Strips CFQ_* plus the host's own XDG_CONFIG_HOME/PONYTAIL_DEFAULT_MODE -- both are
        read directly from os.environ by cfq_doctor.py/cfq_runtime.py regardless of the `home=`
        override, so a CI runner that happens to set XDG_CONFIG_HOME leaks its (nonexistent)
        ponytail config into every test unless a test opts back in via its own `env=`."""
        return {
            k: v for k, v in os.environ.items()
            if not k.startswith("CFQ_") and k not in ("XDG_CONFIG_HOME", "PONYTAIL_DEFAULT_MODE")
        }

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

    def assert_status_lines_shape(self, entries):
        """Generic contract check for a `statusLines` array (batch 035 phase 08): every entry
        carries exactly the five keys `status_entry` produces, and `text` is `status_line`
        (plus one `sub_line` per `sub` entry) applied to that same entry's own fields -- covers a
        newly added line automatically, no per-line test needed."""
        for entry in entries:
            self.assertEqual(
                set(entry.keys()), {"label", "icon", "detail", "sub", "text"},
                msg=f"statusLines entry has the wrong key set: {entry}",
            )
            expected = cfq_text.status_line(entry["icon"], entry["label"], entry["detail"])
            if entry["sub"]:
                expected = "\n".join([expected] + [cfq_text.sub_line(s) for s in entry["sub"]])
            self.assertEqual(entry["text"], expected, msg=f"text mismatch for entry: {entry}")

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

    def minimal_path(self, *bins, rename=None):
        """Builds a throwaway PATH directory containing only the given commands (symlinked
        in), so a missing dependency in a test is real, not accidental. `rename` maps a name to
        create in the directory to the real command it should resolve to (e.g.
        {"python": "python3"}, to simulate a host that only has `python` on PATH)."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        dir_path = pathlib.Path(d.name)
        for b in bins:
            p = shutil.which(b)
            if p:
                (dir_path / b).symlink_to(p)
        for name, real in (rename or {}).items():
            p = shutil.which(real)
            if p:
                (dir_path / name).symlink_to(p)
        return str(dir_path)
