"""Migrated from test-layout-migration.sh (scripts/migrations/cfq-layout-v1.sh — the one-off,
no-noun repo-local layout upgrade utility, invoked directly by path per the batch's own decision
to keep it isolated; see batch 013 phase 06 notes)."""

import unittest

from cfq_testlib import CfqTestCase, PLUGIN_ROOT

MIGRATION_SH = PLUGIN_ROOT / "scripts" / "migrations" / "cfq-layout-v1.sh"


class LayoutMigrationTest(CfqTestCase):
    def _new_repo(self, name):
        d = self._repos_dir / name
        d.mkdir()
        self.run_clean("git", "init", "-q", cwd=d)
        return d

    def _migrate(self, subcmd, *args, home=None):
        run_env = {"HOME": str(home if home is not None else self.home)}
        return self.run_clean("bash", str(MIGRATION_SH), subcmd, *args, env=run_env)

    def test_old_root_only_migrates_without_data_loss(self):
        # 1. Old-root-only fixture migrates without data loss, old root removed
        repo = self._new_repo("repo1")
        old = repo / ".claude" / "code-for-queue"
        (old / "impl" / "2026-01-01-a" / "done").mkdir(parents=True)
        (old / "plan").mkdir(parents=True)
        (old / "todo").mkdir(parents=True)
        (old / "impl" / "2026-01-01-a" / "01-x.md").write_text("phase-content\n")
        (old / "telemetry.jsonl").write_text('{"a":1}\n')
        (old / ".maintenance").touch()

        out = self.json_out(self._migrate("apply", "--all-known", str(repo)))
        self.assertEqual(out["repos"][0]["result"], "migrated", msg=f"old-root-only result: {out}")
        self.assertEqual(
            (repo / ".claude" / "cfq" / "impl" / "2026-01-01-a" / "01-x.md").read_text(),
            "phase-content\n", msg="phase file bytes lost",
        )
        self.assertTrue(
            (repo / ".claude" / "cfq" / "impl" / "2026-01-01-a" / "done").is_dir(),
            msg="done/ subdir lost",
        )
        self.assertTrue((repo / ".claude" / "cfq" / "telemetry.jsonl").is_file(), msg="telemetry.jsonl not moved")
        self.assertTrue((repo / ".claude" / "cfq" / ".maintenance").is_file(), msg=".maintenance not moved")
        self.assertFalse((repo / ".claude" / "code-for-queue").is_dir(), msg="old root not removed")

        # 2. Repeated migration is a no-op
        out = self.json_out(self._migrate("apply", "--all-known", str(repo)))
        self.assertEqual(
            out["repos"][0]["result"], "already-canonical", msg=f"repeat migration not a no-op: {out}"
        )

    def test_both_roots_merge_deterministically(self):
        # 3. Both roots, non-conflicting entries merge deterministically
        repo = self._new_repo("repo3")
        old = repo / ".claude" / "code-for-queue"
        new = repo / ".claude" / "cfq"
        (old / "impl" / "2026-01-01-a").mkdir(parents=True)
        (new / "impl" / "2026-01-02-b").mkdir(parents=True)
        (new / "impl" / "done").mkdir(parents=True)
        (old / "impl" / "2026-01-01-a" / "01.md").write_text("old\n")
        (new / "impl" / "2026-01-02-b" / "01.md").write_text("new\n")

        out = self.json_out(self._migrate("apply", "--all-known", str(repo)))
        self.assertEqual(out["repos"][0]["result"], "migrated", msg=f"merge result: {out}")
        self.assertEqual(
            (new / "impl" / "2026-01-01-a" / "01.md").read_text(), "old\n",
            msg="merged old entry missing",
        )
        self.assertEqual(
            (new / "impl" / "2026-01-02-b" / "01.md").read_text(), "new\n",
            msg="existing new entry disturbed",
        )
        self.assertFalse(old.is_dir(), msg="old root not removed after merge")

    def test_conflicting_content_reported_never_overwritten(self):
        # 4. Conflicting same-name content is reported, never overwritten
        repo = self._new_repo("repo4")
        old = repo / ".claude" / "code-for-queue"
        new = repo / ".claude" / "cfq"
        (old / "impl" / "2026-01-01-a").mkdir(parents=True)
        (new / "impl" / "2026-01-01-a").mkdir(parents=True)
        (old / "impl" / "2026-01-01-a" / "01.md").write_text("old-version\n")
        (new / "impl" / "2026-01-01-a" / "01.md").write_text("new-version\n")

        plan_out = self.json_out(self._migrate("plan", "--all-known", str(repo)))
        self.assertEqual(
            plan_out["repos"][0]["result"], "conflict", msg=f"plan should report conflict: {plan_out}"
        )
        self.assertEqual(
            plan_out["repos"][0]["code"], "CFQ_LAYOUT_MIGRATION_CONFLICT",
            msg=f"missing conflict code: {plan_out}",
        )

        apply_out = self.json_out(self._migrate("apply", "--all-known", str(repo)))
        self.assertEqual(
            apply_out["repos"][0]["result"], "conflict", msg=f"apply should report conflict: {apply_out}"
        )
        self.assertEqual(
            (old / "impl" / "2026-01-01-a" / "01.md").read_text(), "old-version\n",
            msg="old content overwritten",
        )
        self.assertEqual(
            (new / "impl" / "2026-01-01-a" / "01.md").read_text(), "new-version\n",
            msg="new content overwritten",
        )

    def test_discovery_finds_registry_current_and_scanroot_repos(self):
        # 5. Discovery: registry repos, current repo, and old-root repos beneath scanRoots
        scanhome = self._repos_dir / "scanhome"
        scanhome.mkdir()
        scanroot = self._repos_dir / "scanroot"
        scanroot.mkdir()
        found = scanroot / "found"
        (found / ".claude" / "code-for-queue" / "plan").mkdir(parents=True)
        self.run_cfq("settings", "set", "scanRoots", str(scanroot), home=scanhome, check=True)
        reg_repo = self._new_repo("reg-repo")
        self.run_cfq("registry", "add", str(reg_repo), home=scanhome, check=True)
        current = self._new_repo("current")

        proc = self._migrate("discover", str(current), home=scanhome)
        disc = proc.stdout
        self.assertIn(str(found), disc.splitlines(), msg="scanRoots repo not discovered")
        self.assertIn(str(reg_repo), disc.splitlines(), msg="registry repo not discovered")
        self.assertIn(str(current), disc.splitlines(), msg="current repo not discovered")

    def test_stale_registry_entries_reported_and_pruned(self):
        # 6. Stale registry entries are reported (and pruned) rather than retained as phantom
        # repos
        stalehome = self._repos_dir / "stalehome"
        stalehome.mkdir()
        gone = self._repos_dir / "does-not-exist"
        self.run_cfq("registry", "add", str(gone), home=stalehome, check=True)
        out = self.json_out(self._migrate("apply", "--all-known", home=stalehome))
        self.assertEqual(
            out["repos"][0]["result"], "stale", msg=f"stale registry entry not reported: {out}"
        )
        remaining = self.run_cfq("registry", "list", home=stalehome).stdout
        self.assertEqual(remaining, "", msg=f"stale entry not pruned from registry: {remaining}")


if __name__ == "__main__":
    unittest.main()
