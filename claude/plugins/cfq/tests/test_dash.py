"""Migrated from test-dash.sh.

Self-test for scripts/cfq-dash.sh: repo rollup, thisRepo scoping, and the settings marker
mapping (default/global/repo/env source and masked-value display).
"""

import subprocess
import unittest

from cfq_testlib import CfqTestCase


class TestDash(CfqTestCase):
    def _plain_repo(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)

    def test_repo_rollup_and_render(self):
        tmp = self._repos_dir / "dashroot"

        # repo-a: registered, one open batch (high priority, 1 open + 1 done phase). A real git
        # repo so cfq-dash.sh's git rev-parse resolves it as "this repo" when cwd is inside it.
        repo_a = tmp / "repo-a"
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "done").mkdir(parents=True)
        self._plain_repo(repo_a)
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "01-a.md").touch()
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "done" / "00-x.md").touch()
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / ".priority").write_text("high")

        # repo-b: registered, no batches at all -- the rollup must read OK, never crash on empty
        # batches.
        repo_b = tmp / "repo-b"
        (repo_b / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo_b)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}

        # 1. Two registered repos, one with an open batch -> .repos has exactly two entries, each
        # appearing once, counters matching what was created on disk.
        out = self.json_out(self.run_cfq("dash", env=env))
        self.assertEqual(out["status"], "OK", f"status = {out['status']}")
        self.assertEqual(len(out["repos"]), 2, f"repos length = {len(out['repos'])}")
        a = [r for r in out["repos"] if r["path"] == str(repo_a)]
        self.assertEqual(len(a), 1, f"repo-a should appear exactly once, got {a}")
        self.assertEqual(
            {k: a[0][k] for k in ("open", "done", "status")}, {"open": 1, "done": 0, "status": "IN_PROGRESS"},
            f"repo-a rollup = {a[0]}",
        )
        b = [r for r in out["repos"] if r["path"] == str(repo_b)][0]
        self.assertEqual(
            {k: b[k] for k in ("open", "done", "status")}, {"open": 0, "done": 0, "status": "OK"},
            f"repo-b rollup = {b}",
        )

        # 1b. `render` is additive, not a substitute: same fixture, JSON default above is
        # untouched, and the terminal render mentions both repos. Deep render coverage (tables,
        # MULTIPLE_IN_PROGRESS, equivalence, no-HTML-entity) lives in test_render.py, not
        # duplicated here.
        rendered = self.run_cfq("dash", "render", str(tmp), env=env).stdout
        self.assertIn("repo-a", rendered, "render output missing repo-a")
        self.assertIn("repo-b", rendered, "render output missing repo-b")

        # 2. Run from inside a registered repo -> .thisRepo.batches lists that repo's batches only.
        out_inside = self.json_out(self.run_cfq("dash", cwd=str(repo_a), env=env))
        this = [b["name"] for b in out_inside["thisRepo"]["batches"]]
        self.assertEqual(this, ["2026-01-01-demo"], f"thisRepo.batches = {this}")

        # 3. Run from a directory that is not a registered repo -> .thisRepo is null, .repos
        # still populated, status still OK.
        outside = self._repos_dir / "outside"
        self._plain_repo(outside)
        out_outside = self.json_out(self.run_cfq("dash", cwd=str(outside), env=env))
        self.assertIsNone(out_outside["thisRepo"], "thisRepo should be null outside a registered repo")
        self.assertEqual(len(out_outside["repos"]), 2, "repos should stay populated")
        self.assertEqual(out_outside["status"], "OK", f"status should stay OK, got {out_outside['status']}")

        # 4. No repos at all -> status NO_REPO, empty .repos, no crash. A fresh HOME, not
        # self.home -- repo-a/repo-b got registered into self.home's registry above, and the scan
        # unions the registry with CFQ_SCAN_ROOTS, so reusing self.home would still find them.
        empty_root = self._repos_dir / "empty-root"
        empty_root.mkdir()
        empty_home = self._repos_dir / "empty-home"
        empty_home.mkdir()
        out_empty = self.json_out(
            self.run_cfq("dash", home=empty_home, env={"CFQ_SCAN_ROOTS": str(empty_root)}),
        )
        self.assertEqual(out_empty["status"], "NO_REPO", f"empty status = {out_empty['status']}")
        self.assertEqual(out_empty["repos"], [], f"empty repos = {out_empty['repos']}")

    def test_settings_marker_mapping(self):
        # 5. Marker mapping, one case per --sources value (default/global/repo/env:process), plus
        # the env:process must-fall-back to the masked file value (not just the env value), plus
        # env:repo-legacy.
        mroot = self._repos_dir / "mroot"
        mfixture = mroot / "mfixture"
        (mfixture / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(mfixture)

        def run_dash(env=None):
            merged = {"CFQ_SCAN_ROOTS": str(mroot)}
            if env:
                merged.update(env)
            return self.json_out(self.run_cfq("dash", cwd=str(mfixture), env=merged))

        def key_row(key, out):
            return next(s for s in out["settings"] if s["key"] == key)

        d = key_row("maintenanceEvery", run_dash())
        self.assertEqual(d["marker"], "D", f"default marker = {d}")

        self.run_cfq("settings", "set", "maintenanceEvery", "20")
        g = key_row("maintenanceEvery", run_dash())
        self.assertEqual(g["marker"], "G", f"global marker = {g}")

        self.run_cfq("settings", "set", "--repo", str(mfixture), "maintenanceEvery", "5")
        r = key_row("maintenanceEvery", run_dash())
        self.assertEqual(r["marker"], "R", f"repo marker = {r}")

        envp = key_row("maintenanceEvery", run_dash(env={"CFQ_MAINTENANCE_EVERY": "99"}))
        self.assertEqual(envp["marker"], "E", f"env:process marker = {envp}")

        self.run_cfq("settings", "set", "--repo", str(mfixture), "docLevel", "full")
        envd = key_row("docLevel", run_dash(env={"CFQ_DOC_LEVEL": "minimal"}))
        self.assertEqual(envd["value"], "minimal", f"docLevel effective value = {envd}")
        self.assertEqual(
            envd["maskedValue"], "full",
            f"docLevel maskedValue must be the repo file value, not just the env value, got {envd}",
        )
        self.assertEqual(envd["maskedSource"], "repo", f"docLevel maskedSource = {envd}")

        (mfixture / ".claude" / "settings.json").write_text('{"env":{"CFQ_DOC_LEVEL":"standard"}}')
        envl = key_row("docLevel", run_dash(env={"CFQ_DOC_LEVEL": "standard"}))
        self.assertEqual(envl["marker"], "E", f"env:repo-legacy marker = {envl}")
        self.assertEqual(envl["source"], "env:repo-legacy", f"env:repo-legacy source = {envl}")


if __name__ == "__main__":
    unittest.main()
