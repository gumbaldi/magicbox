"""Runs the portal viewer's own pure-function unit tests (`tests/js/*.test.mjs`, batch 040 phase
02) under `node --test` -- skipped when Node isn't on `PATH`, so this stdlib `unittest` suite stays
fully runnable without it. `config/dependencies.txt` lists Node as a test-only dependency: the
viewer's runtime is plain HTML/CSS/JS with no build step, and this is the only place Node itself is
ever invoked."""

import os
import re
import shutil
import subprocess
import unittest

import test_portal  # the module, not its test class: importing the class would rediscover its tests
from cfq_testlib import PLUGIN_ROOT, CfqTestCase

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


class PortalViewerEndToEndTest(CfqTestCase):
    """Runs the viewer against the files a real `portal sync` wrote (batch 050 phase 15). The
    original defect of that batch -- a viewer requesting data files under paths the data layer
    never writes -- went unnoticed because no test did exactly this."""

    # the shared fixture builder of tests/test_portal.py, borrowed as plain functions
    _cfq = test_portal.PortalTest._cfq
    _write = test_portal.PortalTest._write
    _build_world = test_portal.PortalTest._build_world

    def test_viewer_walks_every_view_over_a_real_sync(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not found on PATH -- viewer JS tests are optional without it")

        repo = self.make_repo("e2e")
        self._build_world(repo)
        report_dir = self._repos_dir / "shared-reports"
        report_dir.mkdir()
        sync = self.run_cfq("portal", "sync", str(repo), env={"CFQ_REPORT_DIR": str(report_dir)})
        self.assertEqual(sync.returncode, 0, msg=sync.stderr)
        self.assertEqual(self.json_out(sync)["status"], "OK", msg=sync.stdout)

        env = dict(os.environ)
        env["CFQ_PORTAL_DIR"] = str(repo / ".claude" / "cfq" / "reports")
        env["CFQ_PORTAL_GLOBAL_DIR"] = str(report_dir)
        proc = subprocess.run(
            [node, "--test", str(JS_TESTS_DIR / "e2e.test.mjs")],
            capture_output=True, text=True, env=env,
        )
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, msg=out)
        self.assertRegex(out, r"skipped 0", msg=out)
        self.assertRegex(out, r"pass 2\b", msg=out)


if __name__ == "__main__":
    unittest.main()
