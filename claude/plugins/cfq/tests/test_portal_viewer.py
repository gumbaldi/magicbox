"""Runs the portal viewer's own pure-function unit tests (`tests/js/*.test.mjs`, batch 040 phase
02) under `node --test` -- skipped when Node isn't on `PATH`, so this stdlib `unittest` suite stays
fully runnable without it. `config/dependencies.txt` lists Node as a test-only dependency: the
viewer's runtime is plain HTML/CSS/JS with no build step, and this is the only place Node itself is
ever invoked."""

import shutil
import subprocess
import unittest

from cfq_testlib import PLUGIN_ROOT

JS_TESTS_DIR = PLUGIN_ROOT / "tests" / "js"


class PortalViewerJsTest(unittest.TestCase):
    def test_node_test_suite_passes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not found on PATH -- viewer JS tests are optional without it")

        # Explicit file arguments, not the bare directory: some Node versions' `--test <dir>`
        # positional form fails to resolve a directory it was just handed (MODULE_NOT_FOUND),
        # while passing each `*.test.mjs` file directly works reliably across versions.
        test_files = sorted(str(p) for p in JS_TESTS_DIR.glob("*.test.mjs"))
        self.assertTrue(test_files, f"no *.test.mjs files found under {JS_TESTS_DIR}")

        proc = subprocess.run(
            [node, "--test", *test_files],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
