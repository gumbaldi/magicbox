"""Migrated from test-branch.sh (bin/cfq branch — branch-per-batch resolution)."""

import unittest

from cfq_testlib import CfqTestCase


class BranchTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo,
        )

    def _plan(self, batch, repo=None):
        return self.run_cfq("branch", "plan", str(repo or self.repo), batch, check=True)

    def test_no_existing_branch_legacy_slug(self):
        # No existing branch, legacy-style batch dir -> new, branch is cfq/<batch-dir>, base
        # main.
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(out["mode"], "new", msg=f"mode -> {out}")
        self.assertEqual(out["branch"], "cfq/2026-01-01-mytopic", msg=f"branch -> {out}")
        self.assertEqual(out["batch"], "2026-01-01-mytopic", msg=f"batch -> {out}")
        self.assertIsNone(out["batchNumber"], msg=f"legacy batchNumber should be null -> {out}")
        self.assertEqual(out["base"], "main", msg=f"base -> {out}")
        self.assertEqual(out["baseRef"], "refs/heads/main", msg=f"baseRef -> {out}")
        self.assertEqual(out["baseSource"], "newestBranch", msg=f"baseSource -> {out}")
        self.assertEqual(out["defaultBranch"], "main", msg=f"defaultBranch -> {out}")
        self.assertEqual(len(out["options"]), 1, msg=f"options -> {out}")
        self.assertNotIn("candidates", out, msg=f"candidates key -> {out}")

    def test_numbered_batch_dir(self):
        # Numbered batch dir -> new, branch is cfq/<numbered-dir>, batchNumber extracted.
        out = self.json_out(self._plan("001-2026-01-01-numbered"))
        self.assertEqual(out["mode"], "new", msg=f"numbered mode -> {out}")
        self.assertEqual(
            out["branch"], "cfq/001-2026-01-01-numbered", msg=f"numbered branch -> {out}"
        )
        self.assertEqual(out["batchNumber"], 1, msg=f"numbered batchNumber -> {out}")

    def test_plan_reads_the_repository_tier_of_branch_per_batch(self):
        # Global stays at its default (true); only the repository says false, and the automatic
        # lookup is off -- so "off" can only come from the repository passed to `branch plan`.
        self.run_cfq("settings", "set", "--repo", str(self.repo), "branchPerBatch", "false", check=True)
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(out["mode"], "off", msg=f"repo-level branchPerBatch=false ignored -> {out}")

    def test_stray_version_branches_ignored(self):
        # Stray vX.Y branches in the repo never influence the new branch name (no version
        # scanning).
        self.run_clean("git", "branch", "v0.9-a", cwd=self.repo)
        self.run_clean("git", "branch", "v0.10-b", cwd=self.repo)
        self.run_clean("git", "branch", "v0.48-x", cwd=self.repo)
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(
            out["branch"], "cfq/2026-01-01-mytopic",
            msg=f"stray vX.Y branches affected the new branch -> {out}",
        )
        names = [o["name"] for o in out["options"]]
        self.assertNotIn(
            "v0.9-a", names, msg=f"stray non-ahead vX.Y branches leaked into options -> {out}"
        )
        self.assertNotIn("v0.10-b", names, msg=f"stray vX.Y branches leaked -> {out}")
        self.assertNotIn("v0.48-x", names, msg=f"stray vX.Y branches leaked -> {out}")

    def test_existing_legacy_branch_continues(self):
        # Existing legacy vX.Y-<slug> branch -> continue, resumable without special-casing.
        self.run_clean("git", "branch", "v0.3-mytopic", cwd=self.repo)
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(out["mode"], "continue", msg=f"continue mode -> {out}")
        self.assertEqual(out["branch"], "v0.3-mytopic", msg=f"continue branch -> {out}")
        # No origin at all -> offline, remoteState falls back to "unknown".
        self.assertEqual(out["remoteState"], "unknown", msg=f"offline remoteState -> {out}")
        self.assertFalse(out["pushable"], msg=f"offline pushable -> {out}")
        self.assertEqual(out["unpushed"], [], msg=f"offline unpushed -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"continue uncontained -> {out}")
        self.assertEqual(out["uncontainedCount"], 0, msg=f"continue uncontainedCount -> {out}")
        self.assertEqual(out["options"], [], msg=f"continue options -> {out}")
        self.assertNotIn("candidates", out, msg=f"continue candidates key -> {out}")

    def test_remote_only_branch_continues(self):
        # Remote-only branch for the slug -> same continue result.
        self.run_clean("git", "branch", "v0.48-x", cwd=self.repo)
        remote = self._repos_dir / "remote.git"
        self.run_clean("git", "init", "-q", "--bare", str(remote))
        self.run_clean("git", "remote", "add", "origin", str(remote), cwd=self.repo)
        self.run_clean("git", "push", "-q", "origin", "v0.48-x:v0.3-mytopic", cwd=self.repo)
        self.run_clean("git", "fetch", "-q", "origin", cwd=self.repo)
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(out["mode"], "continue", msg=f"remote continue mode -> {out}")
        self.assertEqual(out["branch"], "v0.3-mytopic", msg=f"remote continue branch -> {out}")

    def test_persisted_changelog_branch_wins(self):
        # A branch persisted in the changelog for this batch wins over the suffix-match
        # fallback.
        changelog_repo = self._repos_dir / "changelog-repo"
        changelog_repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=changelog_repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=changelog_repo,
        )
        self.run_cfq(
            "changelog", "init", str(changelog_repo), "cfq/2026-02-01-persisted", "main",
            "2026-02-01-persisted", check=True,
        )
        self.run_clean("git", "branch", "cfq/2026-02-01-persisted", cwd=changelog_repo)
        self.run_clean("git", "branch", "some-other-branch-ending-persisted", cwd=changelog_repo)
        out = self.json_out(self._plan("2026-02-01-persisted", repo=changelog_repo))
        self.assertEqual(out["mode"], "continue", msg=f"persisted-branch continue mode -> {out}")
        self.assertEqual(
            out["branch"], "cfq/2026-02-01-persisted", msg=f"persisted branch not preferred -> {out}"
        )

        # Persisted branch since deleted -> falls through to the suffix-match fallback, not a
        # dangling continue.
        self.run_clean("git", "branch", "-q", "-D", "cfq/2026-02-01-persisted", cwd=changelog_repo)
        out = self.json_out(self._plan("2026-02-01-persisted", repo=changelog_repo))
        self.assertEqual(out["mode"], "continue", msg=f"deleted-persisted-branch fallback mode -> {out}")
        self.assertEqual(
            out["branch"], "some-other-branch-ending-persisted",
            msg=f"deleted-persisted-branch fallback did not use suffix match -> {out}",
        )

    def test_branch_per_batch_off(self):
        # branchPerBatch=false -> off (no env var for this key, set it via settings.json).
        cfq_home = self.home / ".claude" / "cfq"
        cfq_home.mkdir(parents=True)
        (cfq_home / "settings.json").write_text('{"branchPerBatch": false}\n')
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(out["mode"], "off", msg=f"off mode -> {out}")
        self.assertIsNone(out["branch"], msg=f"off branch should be null -> {out}")
        self.assertFalse(out["dirty"], msg=f"off dirty -> {out}")
        self.assertFalse(out["changelogDirty"], msg=f"off changelogDirty -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"off uncontained -> {out}")
        self.assertEqual(out["uncontainedCount"], 0, msg=f"off uncontainedCount -> {out}")
        self.assertEqual(out["options"], [], msg=f"off options -> {out}")
        self.assertNotIn("candidates", out, msg=f"off candidates key -> {out}")

    def test_newer_non_batch_branch_is_the_recommendation(self):
        # A non-`cfq/` branch with a strictly newer commit than main is the recommendation, and
        # is reported as a non-batch branch.
        self.run_clean("git", "checkout", "-q", "-b", "v0.50-ahead", cwd=self.repo)
        date = "2030-01-01T00:00:00"
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "ahead", cwd=self.repo,
            env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        )
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        out = self.json_out(self._plan("2026-01-02-newtopic"))
        self.assertEqual(out["mode"], "new", msg=f"options-case mode -> {out}")
        self.assertEqual(out["base"], "v0.50-ahead", msg=f"base -> {out}")
        self.assertEqual(out["baseRef"], "refs/heads/v0.50-ahead", msg=f"baseRef -> {out}")
        self.assertEqual(out["baseSource"], "newestBranch", msg=f"baseSource -> {out}")
        self.assertFalse(out["options"][0]["isCfq"], msg=f"isCfq -> {out}")

    def test_local_main_behind_origin_is_not_fast_forwarded(self):
        # (a) local main purely behind origin/main -> no longer read or mutated on the `new`
        # path; base still "main", but baseRef points straight into refs/remotes/origin.
        ff_repo = self._repos_dir / "ff-repo"
        ff_repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=ff_repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=ff_repo,
        )
        ff_remote = self._repos_dir / "ff-remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", "main", str(ff_remote))
        self.run_clean("git", "remote", "add", "origin", str(ff_remote), cwd=ff_repo)
        self.run_clean("git", "push", "-q", "origin", "main", cwd=ff_repo)
        self.run_clean("git", "checkout", "-q", "-b", "topic", cwd=ff_repo)
        ff_clone = self._repos_dir / "ff-clone"
        self.run_clean("git", "clone", "-q", str(ff_remote), str(ff_clone))
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "remote-ahead", cwd=ff_clone,
        )
        self.run_clean("git", "push", "-q", "origin", "main", cwd=ff_clone)

        out = self.json_out(self._plan("2026-03-01-fftopic", repo=ff_repo))
        self.assertEqual(out["remoteChecked"], True, msg=f"ff remoteChecked -> {out}")
        self.assertEqual(out["mode"], "new", msg=f"ff mode -> {out}")
        self.assertEqual(out["base"], "main", msg=f"ff base -> {out}")
        self.assertEqual(out["baseRef"], "refs/remotes/origin/main", msg=f"ff baseRef -> {out}")
        self.assertIsNone(out["remoteWarning"], msg=f"ff remoteWarning -> {out}")
        local_main = self.run_clean("git", "rev-parse", "refs/heads/main", cwd=ff_repo).stdout.strip()
        remote_main = self.run_clean(
            "git", "rev-parse", "refs/remotes/origin/main", cwd=ff_repo
        ).stdout.strip()
        self.assertNotEqual(local_main, remote_main, msg="local main must not be mutated by `plan`")

    def test_no_origin_configured(self):
        # (b) no origin configured at all -> behaves exactly as before (remoteChecked false).
        noorigin_repo = self._repos_dir / "no-origin-repo"
        noorigin_repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=noorigin_repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=noorigin_repo,
        )
        out = self.json_out(self._plan("2026-03-02-nooriginit", repo=noorigin_repo))
        self.assertEqual(out["remoteChecked"], False, msg=f"no-origin remoteChecked -> {out}")
        self.assertEqual(out["mode"], "new", msg=f"no-origin mode -> {out}")
        self.assertEqual(out["base"], "main", msg=f"no-origin base -> {out}")
        self.assertEqual(out["baseRef"], "refs/heads/main", msg=f"no-origin baseRef -> {out}")
        self.assertIsNone(out["remoteWarning"], msg=f"no-origin remoteWarning -> {out}")

    def test_local_main_ahead_of_origin_never_auto_resolved(self):
        # (c) local main ahead of origin/main with an unpushed commit -> stop, never
        # auto-resolve.
        ahead_repo = self._repos_dir / "ahead-repo"
        ahead_repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=ahead_repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=ahead_repo,
        )
        ahead_remote = self._repos_dir / "ahead-remote.git"
        self.run_clean("git", "init", "-q", "--bare", str(ahead_remote))
        self.run_clean("git", "remote", "add", "origin", str(ahead_remote), cwd=ahead_repo)
        self.run_clean("git", "push", "-q", "origin", "main", cwd=ahead_repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "unpushed", cwd=ahead_repo,
        )
        out = self.json_out(self._plan("2026-03-03-aheadtopic", repo=ahead_repo))
        self.assertEqual(out["remoteChecked"], True, msg=f"ahead remoteChecked -> {out}")
        self.assertEqual(out["mode"], "new", msg=f"ahead mode -> {out}")
        self.assertEqual(out["base"], "main", msg=f"ahead base -> {out}")
        self.assertEqual(out["baseRef"], "refs/remotes/origin/main", msg=f"ahead baseRef -> {out}")
        self.assertIsNotNone(out["remoteWarning"], msg=f"ahead remoteWarning should be set -> {out}")
        local_main = self.run_clean("git", "rev-parse", "refs/heads/main", cwd=ahead_repo).stdout.strip()
        remote_main = self.run_clean(
            "git", "rev-parse", "refs/remotes/origin/main", cwd=ahead_repo
        ).stdout.strip()
        self.assertNotEqual(local_main, remote_main, msg="ahead local main must not be auto-resolved")

    def test_persisted_continue_branch_fast_forwarded(self):
        # (d) a persisted continue branch purely behind its own origin/<branch> ->
        # fast-forwarded.
        cont_repo = self._repos_dir / "cont-repo"
        cont_repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=cont_repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=cont_repo,
        )
        cont_remote = self._repos_dir / "cont-remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", "main", str(cont_remote))
        self.run_clean("git", "remote", "add", "origin", str(cont_remote), cwd=cont_repo)
        self.run_cfq(
            "changelog", "init", str(cont_repo), "cfq/2026-03-04-conttopic", "main",
            "2026-03-04-conttopic", check=True,
        )
        self.run_clean("git", "branch", "cfq/2026-03-04-conttopic", cwd=cont_repo)
        self.run_clean(
            "git", "push", "-q", "origin", "main", "cfq/2026-03-04-conttopic", cwd=cont_repo
        )
        cont_clone = self._repos_dir / "cont-clone"
        self.run_clean("git", "clone", "-q", str(cont_remote), str(cont_clone))
        self.run_clean("git", "checkout", "-q", "cfq/2026-03-04-conttopic", cwd=cont_clone)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "remote-ahead-branch", cwd=cont_clone,
        )
        self.run_clean("git", "push", "-q", "origin", "cfq/2026-03-04-conttopic", cwd=cont_clone)

        out = self.json_out(self._plan("2026-03-04-conttopic", repo=cont_repo))
        self.assertEqual(out["mode"], "continue", msg=f"cont mode -> {out}")
        self.assertEqual(out["branch"], "cfq/2026-03-04-conttopic", msg=f"cont branch -> {out}")
        self.assertEqual(out["remoteChecked"], True, msg=f"cont remoteChecked -> {out}")
        self.assertIsNone(out["remoteWarning"], msg=f"cont remoteWarning -> {out}")
        self.assertEqual(out["remoteState"], "behind", msg=f"cont remoteState -> {out}")
        local = self.run_clean(
            "git", "rev-parse", "refs/heads/cfq/2026-03-04-conttopic", cwd=cont_repo
        ).stdout.strip()
        remote = self.run_clean(
            "git", "rev-parse", "refs/remotes/origin/cfq/2026-03-04-conttopic", cwd=cont_repo
        ).stdout.strip()
        self.assertEqual(local, remote, msg="local continue branch was not fast-forwarded")

    def _make_continue_repo(self, batch, branch_name):
        """origin + a persisted `branch_name` for `batch`, returns (repo, remote)."""
        repo = self._repos_dir / f"{batch}-repo"
        repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=repo,
        )
        remote = self._repos_dir / f"{batch}-remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", "main", str(remote))
        self.run_clean("git", "remote", "add", "origin", str(remote), cwd=repo)
        self.run_cfq(
            "changelog", "init", str(repo), branch_name, "main", batch, check=True,
        )
        # Mirrors the real flow: by the time `/ifq` reaches `branch plan`, `cfq_lock.py` has
        # already run `layout ensure`, so the queue's own untracked state is Git-excluded and
        # never shows up as a dirty tree on its own.
        self.run_cfq("layout", "ensure", str(repo), check=True)
        self.run_clean("git", "branch", branch_name, cwd=repo)
        self.run_clean("git", "push", "-q", "origin", "main", branch_name, cwd=repo)
        return repo, remote

    def test_continue_behind_checked_out(self):
        # (behind, checked out, clean) -> fast-forward via `merge --ff-only` since `update-ref`
        # cannot move the ref of the branch that is currently HEAD.
        batch = "2026-03-05-checkedout"
        branch_name = f"cfq/{batch}"
        repo, remote = self._make_continue_repo(batch, branch_name)
        self.run_clean("git", "checkout", "-q", branch_name, cwd=repo)
        clone = self._repos_dir / "checkedout-clone"
        self.run_clean("git", "clone", "-q", str(remote), str(clone))
        self.run_clean("git", "checkout", "-q", branch_name, cwd=clone)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "remote-ahead", cwd=clone,
        )
        self.run_clean("git", "push", "-q", "origin", branch_name, cwd=clone)

        out = self.json_out(self._plan(batch, repo=repo))
        self.assertEqual(out["mode"], "continue", msg=f"checked-out behind mode -> {out}")
        self.assertEqual(out["remoteState"], "behind", msg=f"checked-out behind remoteState -> {out}")
        self.assertIsNone(out["remoteWarning"], msg=f"checked-out behind remoteWarning -> {out}")
        head = self.run_clean("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        origin_ref = self.run_clean(
            "git", "rev-parse", f"refs/remotes/origin/{branch_name}", cwd=repo
        ).stdout.strip()
        self.assertEqual(head, origin_ref, msg="checked-out behind branch was not fast-forwarded")

    def test_continue_behind_checked_out_dirty(self):
        # (behind, checked out, dirty) -> nothing moves, remoteWarning names the dirty tree.
        batch = "2026-03-06-dirtycheckedout"
        branch_name = f"cfq/{batch}"
        repo, remote = self._make_continue_repo(batch, branch_name)
        self.run_clean("git", "checkout", "-q", branch_name, cwd=repo)
        clone = self._repos_dir / "dirty-clone"
        self.run_clean("git", "clone", "-q", str(remote), str(clone))
        self.run_clean("git", "checkout", "-q", branch_name, cwd=clone)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "remote-ahead", cwd=clone,
        )
        self.run_clean("git", "push", "-q", "origin", branch_name, cwd=clone)
        (repo / "dirty.txt").write_text("uncommitted\n")

        before_head = self.run_clean("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        out = self.json_out(self._plan(batch, repo=repo))
        self.assertEqual(out["mode"], "continue", msg=f"dirty checked-out mode -> {out}")
        self.assertIsNotNone(out["remoteWarning"], msg=f"dirty checked-out remoteWarning -> {out}")
        after_head = self.run_clean("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        self.assertEqual(before_head, after_head, msg="dirty checked-out branch ref must not move")

    def test_continue_ahead(self):
        # (ahead) -> remoteState "ahead", pushable, unpushed lists hash + subject.
        batch = "2026-03-07-ahead"
        branch_name = f"cfq/{batch}"
        repo, _remote = self._make_continue_repo(batch, branch_name)
        self.run_clean("git", "checkout", "-q", branch_name, cwd=repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "unpushed change", cwd=repo,
        )
        self.run_clean("git", "checkout", "-q", "main", cwd=repo)

        out = self.json_out(self._plan(batch, repo=repo))
        self.assertEqual(out["remoteState"], "ahead", msg=f"ahead remoteState -> {out}")
        self.assertTrue(out["pushable"], msg=f"ahead pushable -> {out}")
        self.assertEqual(len(out["unpushed"]), 1, msg=f"ahead unpushed -> {out}")
        self.assertIn("unpushed change", out["unpushed"][0], msg=f"ahead unpushed content -> {out}")

    def test_continue_diverged(self):
        # (diverged) -> remoteState "diverged", not pushable, warning names both counts.
        batch = "2026-03-08-diverged"
        branch_name = f"cfq/{batch}"
        repo, remote = self._make_continue_repo(batch, branch_name)
        clone = self._repos_dir / "diverged-clone"
        self.run_clean("git", "clone", "-q", str(remote), str(clone))
        self.run_clean("git", "checkout", "-q", branch_name, cwd=clone)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "remote-side", cwd=clone,
        )
        self.run_clean("git", "push", "-q", "origin", branch_name, cwd=clone)

        self.run_clean("git", "checkout", "-q", branch_name, cwd=repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "local-side", cwd=repo,
        )
        self.run_clean("git", "checkout", "-q", "main", cwd=repo)

        out = self.json_out(self._plan(batch, repo=repo))
        self.assertEqual(out["remoteState"], "diverged", msg=f"diverged remoteState -> {out}")
        self.assertFalse(out["pushable"], msg=f"diverged pushable -> {out}")
        self.assertIsNotNone(out["remoteWarning"], msg=f"diverged remoteWarning -> {out}")

    def test_offline_options_from_local_branches(self):
        # Offline (no origin) -> options fall back to local `git branch`, every one
        # localOnly. An unmerged local numbered cfq/ branch now becomes the chain base.
        self.run_clean("git", "checkout", "-q", "-b", "cfq/001-2026-01-01-offline", cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "offline", cwd=self.repo,
        )
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        out = self.json_out(self._plan("2026-02-08-topic"))
        self.assertEqual(out["remoteChecked"], False, msg=f"offline remoteChecked -> {out}")
        self.assertEqual(
            out["base"], "cfq/001-2026-01-01-offline", msg=f"offline base -> {out}"
        )
        self.assertEqual(
            out["baseRef"], "refs/heads/cfq/001-2026-01-01-offline", msg=f"offline baseRef -> {out}"
        )
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"offline baseSource -> {out}")
        opt = out["options"][0]
        self.assertTrue(opt["localOnly"], msg=f"offline localOnly -> {opt}")

    def test_changelog_only_modification_is_changelog_dirty_not_dirty(self):
        # A tracked changelog file that only carries the queue's own reservations/updates ->
        # changelogDirty, but not dirty -- expected dirt, not a blocker.
        self.run_cfq("layout", "ensure", str(self.repo), check=True)
        self.run_cfq(
            "changelog", "init", str(self.repo), "cfq/2026-05-01-seed", "main",
            "2026-05-01-seed", check=True,
        )
        changelog_path = self.repo / ".claude" / "cfq" / "changelog.yml"
        self.run_clean("git", "add", "-f", str(changelog_path), cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "-q", "-m", "seed changelog", cwd=self.repo,
        )
        self.run_cfq(
            "changelog", "reserve", str(self.repo), "5", "005-2026-05-02-other", check=True,
        )
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertFalse(out["dirty"], msg=f"changelog-only dirty -> {out}")
        self.assertTrue(out["changelogDirty"], msg=f"changelog-only changelogDirty -> {out}")

    def test_other_tracked_dirt_sets_dirty(self):
        (self.repo / "scratch.txt").write_text("uncommitted\n")
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertTrue(out["dirty"], msg=f"other-file dirty -> {out}")
        self.assertFalse(out["changelogDirty"], msg=f"other-file changelogDirty -> {out}")

    def test_untracked_queue_state_never_counts_as_dirty(self):
        # Nothing under .claude/ is tracked -- git collapses the whole untracked subtree to one
        # "?? .claude/" line unless --untracked-files=all forces it to expand to actual file
        # paths. Without that flag this line would not match the ".claude/cfq/" prefix check and
        # would misreport a fresh queue as dirty.
        queue_dir = self.repo / ".claude" / "cfq" / "impl" / "001-x"
        queue_dir.mkdir(parents=True)
        (queue_dir / "01-a.md").write_text("phase\n")
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertFalse(out["dirty"], msg=f"queue-state dirty -> {out}")
        self.assertFalse(out["changelogDirty"], msg=f"queue-state changelogDirty -> {out}")

    def test_untracked_dirt_outside_queue_still_sets_dirty(self):
        # Same collapsed-".claude/" situation, but with an untracked file that is not under
        # .claude/cfq/ next to it -- --untracked-files=all must not make the queue's own state
        # swallow unrelated dirt.
        queue_dir = self.repo / ".claude" / "cfq" / "impl" / "001-x"
        queue_dir.mkdir(parents=True)
        (queue_dir / "01-a.md").write_text("phase\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "new.py").write_text("x = 1\n")
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertTrue(out["dirty"], msg=f"unrelated untracked dirt -> {out}")

    def test_plan_outside_git_repo_reports_no_repo(self):
        non_repo = self._repos_dir / "not-a-repo"
        non_repo.mkdir()
        proc = self._plan("2026-01-01-mytopic", repo=non_repo)
        self.assertNotIn("Traceback", proc.stderr, msg=f"raw traceback -> {proc.stderr}")
        out = self.json_out(proc)
        self.assertEqual(out["status"], "NO_REPO", msg=f"non-repo status -> {out}")
        self.assertEqual(out["repo"]["root"], str(non_repo), msg=f"non-repo root -> {out}")

    def test_continue_mode_also_reports_dirty(self):
        self.run_clean("git", "branch", "v0.3-mytopic", cwd=self.repo)
        (self.repo / "scratch.txt").write_text("uncommitted\n")
        out = self.json_out(self._plan("2026-01-01-mytopic"))
        self.assertEqual(out["mode"], "continue", msg=f"continue mode -> {out}")
        self.assertTrue(out["dirty"], msg=f"continue dirty -> {out}")


def day(n):
    """A commit date far enough ahead of any test repo's real-clock `init` commit that a branch
    carrying it is strictly newer than `main` unless a test says otherwise."""
    return f"2030-01-{n:02d}T00:00:00"


A = "cfq/001-2026-01-01-a"
B = "cfq/002-2026-01-02-b"


class BranchPlanBaseOptionsTest(CfqTestCase):
    """`bin/cfq branch plan`'s `new`-mode recommendation and option list once `origin` is the
    source of truth."""

    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo,
        )
        self.remote = self._repos_dir / "remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.run_clean("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "main", cwd=self.repo)

    def _plan(self, batch="2026-02-01-topic"):
        return self.run_cfq("branch", "plan", str(self.repo), batch, check=True)

    def _commit(self, date, msg="c"):
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", msg, cwd=self.repo, env=env,
        )

    def _branch(self, name, date, push=True, start="main"):
        self.run_clean("git", "checkout", "-q", "-b", name, start, cwd=self.repo)
        self._commit(date, name)
        if push:
            self.run_clean("git", "push", "-q", "-u", "origin", name, cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)

    def _commit_on(self, name, date):
        self.run_clean("git", "checkout", "-q", name, cwd=self.repo)
        self._commit(date, f"more-{name}")
        self.run_clean("git", "push", "-q", "origin", name, cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)

    def _ff_main_to(self, name):
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        self.run_clean("git", "merge", "-q", "--ff-only", name, cwd=self.repo)
        self.run_clean("git", "push", "-q", "origin", "main", cwd=self.repo)

    def _option(self, out, role):
        for o in out["options"]:
            if o["role"] == role:
                return o
        self.fail(f"option with role {role} not found in {out['options']}")

    def _depends_on(self, batch, *deps):
        batch_dir = self.repo / ".claude" / "cfq" / "impl" / batch
        batch_dir.mkdir(parents=True, exist_ok=True)
        (batch_dir / ".dependsOn").write_text("\n".join(deps) + "\n")

    def _names(self, entries):
        return [e["name"] for e in entries]

    def test_routine_chain(self):
        self._branch(A, day(1))
        self._branch(B, day(2), start=A)
        out = self.json_out(self._plan())
        self.assertEqual(out["mode"], "new", msg=f"mode -> {out}")
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["baseRef"], f"refs/remotes/origin/{B}", msg=f"baseRef -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(len(out["options"]), 1, msg=f"options -> {out}")
        self.assertEqual(out["options"][0]["role"], "recommended", msg=f"role -> {out}")
        self.assertTrue(out["options"][0]["isCfq"], msg=f"isCfq -> {out}")
        self.assertEqual(out["uncontainedCount"], 0, msg=f"uncontainedCount -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")
        self.assertNotIn("candidates", out, msg=f"candidates key -> {out}")

    def test_newest_branch_not_a_batch_branch(self):
        self._branch(B, day(2))
        self._branch("feature", day(3))
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], "feature", msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "newestBranch", msg=f"baseSource -> {out}")
        first, second = out["options"][0], out["options"][1]
        self.assertFalse(first["isCfq"], msg=f"isCfq -> {first}")
        self.assertEqual(self._names(first["uncontained"]), [B], msg=f"uncontained -> {first}")
        self.assertEqual(second["role"], "highestBatch", msg=f"role -> {second}")
        self.assertEqual(second["name"], B, msg=f"name -> {second}")
        self.assertFalse(second["containedInBase"], msg=f"containedInBase -> {second}")

    def test_newest_branch_not_a_batch_branch_contains_highest_batch(self):
        self._branch(B, day(2))
        self._branch("feature", day(3), start=B)
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], "feature", msg=f"base -> {out}")
        self.assertTrue(out["options"][1]["containedInBase"], msg=f"containedInBase -> {out}")
        self.assertEqual(out["options"][0]["uncontainedCount"], 0, msg=f"count -> {out}")

    def test_default_branch_is_the_newest(self):
        self._branch(B, day(2))
        self._commit_on("main", day(5))
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], "main", msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "newestBranch", msg=f"baseSource -> {out}")
        self.assertTrue(out["options"][0]["isDefault"], msg=f"isDefault -> {out}")
        self.assertEqual(out["options"][1]["name"], B, msg=f"second option -> {out}")

    def test_tie_goes_to_the_highest_batch_branch(self):
        self._branch(B, day(2))
        self._ff_main_to(B)
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(len(out["options"]), 1, msg=f"options -> {out}")

    def test_older_batch_with_newer_commit_is_offered_as_newest_commit(self):
        self._branch(A, day(1))
        self._branch(B, day(2))
        self._commit_on(A, day(3))
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(self._names(out["options"][0]["uncontained"]), [A], msg=f"unc -> {out}")
        second = out["options"][1]
        self.assertEqual(second["role"], "newestCommit", msg=f"role -> {second}")
        self.assertEqual(second["name"], A, msg=f"name -> {second}")
        self.assertEqual(self._names(second["uncontained"]), [B], msg=f"unc -> {second}")

    def test_older_sibling_only_warns(self):
        self._branch(A, day(1))
        self._branch(B, day(2))
        out = self.json_out(self._plan())
        self.assertEqual(len(out["options"]), 1, msg=f"options -> {out}")
        self.assertEqual(self._names(out["options"][0]["uncontained"]), [A], msg=f"unc -> {out}")
        self.assertEqual(self._names(out["uncontained"]), [A], msg=f"top-level unc -> {out}")
        self.assertFalse(out["uncontained"][0]["dependency"], msg=f"dependency -> {out}")
        self.assertNotIn("newer", out["uncontained"][0], msg=f"newer key -> {out}")

    def test_merged_batch_branch_never_uncontained(self):
        self._branch(A, day(1))
        self._branch(B, day(2))
        self._ff_main_to(A)
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")
        self.assertEqual(out["uncontainedCount"], 0, msg=f"uncontainedCount -> {out}")

    def test_only_the_default_branch(self):
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], "main", msg=f"base -> {out}")
        self.assertEqual(out["baseRef"], "refs/remotes/origin/main", msg=f"baseRef -> {out}")
        self.assertEqual(out["baseSource"], "newestBranch", msg=f"baseSource -> {out}")
        self.assertEqual(len(out["options"]), 1, msg=f"options -> {out}")
        self.assertTrue(out["options"][0]["isDefault"], msg=f"isDefault -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")

    def test_uncontained_is_capped_at_five(self):
        names = [f"cfq/00{n}-2026-01-0{n}-s" for n in range(1, 8)]
        for n, name in enumerate(names, start=1):
            self._branch(name, day(n))
        out = self.json_out(self._plan())
        self.assertEqual(out["base"], names[6], msg=f"base -> {out}")
        self.assertEqual(out["uncontainedCount"], 6, msg=f"count -> {out}")
        self.assertEqual(
            self._names(out["uncontained"]), list(reversed(names[1:6])), msg=f"unc -> {out}"
        )

    def test_remote_only_branch_listed(self):
        self._branch("topic-remote", day(1))
        self.run_clean("git", "branch", "-q", "-D", "topic-remote", cwd=self.repo)
        opt = self._option(self.json_out(self._plan()), "recommended")
        self.assertEqual(opt["name"], "topic-remote", msg=f"name -> {opt}")
        self.assertFalse(opt["localOnly"], msg=f"remote-only localOnly -> {opt}")
        self.assertEqual(opt["ref"], "refs/remotes/origin/topic-remote", msg=f"ref -> {opt}")

    def test_local_only_branch_listed(self):
        self._branch("topic-local", day(1), push=False)
        opt = self._option(self.json_out(self._plan()), "recommended")
        self.assertEqual(opt["name"], "topic-local", msg=f"name -> {opt}")
        self.assertTrue(opt["localOnly"], msg=f"local-only -> {opt}")
        self.assertEqual(opt["ref"], "refs/heads/topic-local", msg=f"ref -> {opt}")

    def test_recommended_option_behind_its_own_remote(self):
        self._branch("topic-behind", day(1))
        self.run_clean("git", "checkout", "-q", "topic-behind", cwd=self.repo)
        self._commit(day(2), "on-remote")
        self.run_clean("git", "push", "-q", "origin", "topic-behind", cwd=self.repo)
        self.run_clean("git", "reset", "-q", "--hard", "HEAD~1", cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        opt = self._option(self.json_out(self._plan()), "recommended")
        self.assertEqual(opt["name"], "topic-behind", msg=f"name -> {opt}")
        self.assertGreater(opt["behindRemote"], 0, msg=f"behindRemote -> {opt}")
        self.assertEqual(opt["ref"], "refs/remotes/origin/topic-behind", msg=f"ref -> {opt}")

    def test_origin_head_never_an_option(self):
        self.run_clean("git", "remote", "set-head", "origin", "main", cwd=self.repo)
        self._branch(A, day(1))
        out = self.json_out(self._plan())
        self.assertNotIn("HEAD", self._names(out["options"]), msg=f"origin/HEAD leaked -> {out}")

    def test_default_branch_follows_origin_head(self):
        self._branch(A, day(1))
        self._branch(B, day(2))
        self.run_clean("git", "push", "-q", "origin", f"{A}:trunk", cwd=self.repo)
        self.run_clean("git", "remote", "set-head", "origin", "trunk", cwd=self.repo)
        out = self.json_out(self._plan())
        self.assertEqual(out["defaultBranch"], "trunk", msg=f"defaultBranch -> {out}")
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        # A is merged into origin/trunk (not into origin/main), so it is not "unmerged" here.
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")

    def test_default_branch_main_without_origin_head(self):
        out = self.json_out(self._plan())
        self.assertEqual(out["defaultBranch"], "main", msg=f"defaultBranch -> {out}")

    def test_default_branch_master_only_repo(self):
        repo = self._repos_dir / "master-repo"
        repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "master", cwd=repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=repo,
        )
        out = self.json_out(self.run_cfq("branch", "plan", str(repo), "2026-02-01-topic", check=True))
        self.assertEqual(out["defaultBranch"], "master", msg=f"defaultBranch -> {out}")
        self.assertEqual(out["base"], "master", msg=f"base -> {out}")

    def test_no_origin_options_come_from_local_branches(self):
        repo = self._repos_dir / "offline-repo"
        repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=repo,
        )
        out = self.json_out(self.run_cfq("branch", "plan", str(repo), "2026-02-01-topic", check=True))
        self.assertEqual(len(out["options"]), 1, msg=f"options -> {out}")
        self.assertTrue(out["options"][0]["isDefault"], msg=f"isDefault -> {out}")
        self.assertTrue(out["options"][0]["localOnly"], msg=f"localOnly -> {out}")
        for name, date in ((A, day(1)), ("feature", day(2))):
            self.run_clean("git", "checkout", "-q", "-b", name, "main", cwd=repo)
            env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
            self.run_clean(
                "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
                "commit", "--allow-empty", "-q", "-m", name, cwd=repo, env=env,
            )
            self.run_clean("git", "checkout", "-q", "main", cwd=repo)
        out = self.json_out(self.run_cfq("branch", "plan", str(repo), "2026-02-01-topic", check=True))
        self.assertEqual(out["base"], "feature", msg=f"base -> {out}")
        self.assertEqual(self._names(out["options"]), ["feature", A], msg=f"options -> {out}")
        for o in out["options"]:
            self.assertTrue(o["localOnly"], msg=f"localOnly -> {o}")

    def test_dependson_dependency_already_in_newest_branch(self):
        self._branch(A, day(1))
        self._branch(B, day(2), start=A)
        c = "cfq/003-2026-01-03-c"
        self._branch(c, day(3), start=B)
        self._depends_on("2026-02-10-topic", "001-2026-01-01-a")
        out = self.json_out(self._plan("2026-02-10-topic"))
        self.assertEqual(out["base"], c, msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")

    def test_dependson_missing_from_base_flagged_as_dependency(self):
        self._branch(A, day(1))
        z = "cfq/999-2026-01-09-newer-unrelated"
        self._branch(z, day(9))
        self._depends_on("2026-02-10-topic", "001-2026-01-01-a")
        out = self.json_out(self._plan("2026-02-10-topic"))
        self.assertEqual(out["base"], z, msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(self._names(out["uncontained"]), [A], msg=f"uncontained -> {out}")
        self.assertTrue(out["uncontained"][0]["dependency"], msg=f"dependency -> {out}")

    def test_dependson_chain_dependency_contained_in_base(self):
        self._branch(A, day(1))
        self._branch(B, day(2), start=A)
        self._depends_on("2026-02-11-topic", "001-2026-01-01-a", "002-2026-01-02-b")
        out = self.json_out(self._plan("2026-02-11-topic"))
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")

    def test_dependson_merged_dep_contributes_nothing(self):
        self._branch(A, day(1))
        self._ff_main_to(A)
        self._depends_on("2026-02-12-topic", "001-2026-01-01-a")
        out = self.json_out(self._plan("2026-02-12-topic"))
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")
        self.assertEqual(out["uncontainedCount"], 0, msg=f"uncontainedCount -> {out}")

    def test_dependson_merged_dep_still_chains(self):
        self._branch(A, day(1))
        self._ff_main_to(A)
        self._branch(B, day(2))
        self._depends_on("2026-02-19-topic", "001-2026-01-01-a")
        out = self.json_out(self._plan("2026-02-19-topic"))
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")

    def test_dependson_two_independent_deps_one_flagged(self):
        self._branch(A, day(1))
        self._branch(B, day(2))
        self._depends_on("2026-02-13-topic", "001-2026-01-01-a", "002-2026-01-02-b")
        out = self.json_out(self._plan("2026-02-13-topic"))
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(self._names(out["uncontained"]), [A], msg=f"uncontained -> {out}")
        self.assertTrue(out["uncontained"][0]["dependency"], msg=f"dependency -> {out}")

    def test_dependson_non_numbered_branch_appended_as_dependency(self):
        self._branch("cfq/2026-01-01-legacy", day(1))
        self._branch(B, day(2))
        self._depends_on("2026-02-14-topic", "2026-01-01-legacy")
        out = self.json_out(self._plan("2026-02-14-topic"))
        self.assertEqual(out["base"], B, msg=f"base -> {out}")
        self.assertEqual(out["baseSource"], "highestBatch", msg=f"baseSource -> {out}")
        self.assertEqual(len(out["uncontained"]), 1, msg=f"uncontained -> {out}")
        entry = out["uncontained"][0]
        self.assertEqual(entry["name"], "cfq/2026-01-01-legacy", msg=f"name -> {out}")
        self.assertTrue(entry["dependency"], msg=f"dependency -> {out}")
        self.assertIn("lastCommit", entry, msg=f"lastCommit -> {out}")
        self.assertNotIn("newer", entry, msg=f"newer key -> {out}")

    def test_dependson_dependencies_listed_first(self):
        self._branch(A, day(1))
        self._branch(B, day(2))
        c = "cfq/003-2026-01-03-c"
        self._branch(c, day(3))
        self._depends_on("2026-02-15-topic", "001-2026-01-01-a")
        out = self.json_out(self._plan("2026-02-15-topic"))
        self.assertEqual(self._names(out["uncontained"]), [A, B], msg=f"uncontained -> {out}")
        self.assertTrue(out["uncontained"][0]["dependency"], msg=f"dependency -> {out}")
        self.assertFalse(out["uncontained"][1]["dependency"], msg=f"dependency -> {out}")

    def test_dependson_missing_branch_ignored(self):
        self._depends_on("2026-02-14-topic", "999-2026-01-01-ghost")
        out = self.json_out(self._plan("2026-02-14-topic"))
        self.assertEqual(out["base"], "main", msg=f"base -> {out}")
        self.assertEqual(out["uncontained"], [], msg=f"uncontained -> {out}")

class BranchListTest(CfqTestCase):
    """`bin/cfq branch list` -- the ten newest branches plus the default branch, rendered."""

    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo,
        )
        self.remote = self._repos_dir / "remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.run_clean("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "main", cwd=self.repo)

    def _list(self, *extra, repo=None):
        return self.run_cfq("branch", "list", str(repo or self.repo), *extra, check=True)

    def _branch(self, name, date, push=True, start="main"):
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        self.run_clean("git", "checkout", "-q", "-b", name, start, cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", name, cwd=self.repo, env=env,
        )
        if push:
            self.run_clean("git", "push", "-q", "-u", "origin", name, cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)

    def _rows(self, out):
        return out["listText"].splitlines()[1:]

    def _row(self, out, name):
        for line in self._rows(out):
            if line.split()[1] == name:
                return line
        self.fail(f"no row for {name} in {out['listText']}")

    def test_routine(self):
        self._branch(A, day(1))
        self._branch("feature", day(2), start=A)
        out = self.json_out(self._list())
        self.assertEqual(out["status"], "OK", msg=f"status -> {out}")
        self.assertEqual(out["names"], ["feature", A, "main"], msg=f"names -> {out}")
        self.assertEqual(out["total"], 3, msg=f"total -> {out}")
        lines = out["listText"].splitlines()
        self.assertEqual(lines[0], "BRANCHES · newest 3 of 3", msg=f"header -> {lines}")
        self.assertEqual([l.split()[0] for l in lines[1:]], ["1", "2", "3"], msg=f"rows -> {lines}")
        self.assertEqual(out["recommended"], "feature", msg=f"recommended -> {out}")
        self.assertEqual(out["defaultBranch"], "main", msg=f"defaultBranch -> {out}")
        self.assertTrue(self._row(out, "feature").endswith("recommended"), msg=f"{lines}")
        self.assertIn("default", self._row(out, "main"), msg=f"{lines}")
        self.assertRegex(self._row(out, A), r"2030-01-01", msg=f"date -> {lines}")

    def test_more_than_ten_branches_appends_the_default_branch(self):
        for n in range(1, 13):
            self._branch(f"f{n:02d}", day(n))
        out = self.json_out(self._list())
        self.assertEqual(len(out["names"]), 11, msg=f"names -> {out}")
        self.assertEqual(out["names"][-1], "main", msg=f"names -> {out}")
        self.assertEqual(out["names"][0], "f12", msg=f"names -> {out}")
        self.assertEqual(out["total"], 13, msg=f"total -> {out}")
        lines = out["listText"].splitlines()
        self.assertEqual(lines[0], "BRANCHES · newest 10 of 13", msg=f"header -> {lines}")
        self.assertEqual(len(lines), 12, msg=f"lines -> {lines}")
        self.assertEqual(lines[-1].split()[0], "11", msg=f"last row -> {lines}")

    def test_default_branch_among_the_newest_is_listed_once(self):
        for n in range(1, 12):
            self._branch(f"f{n:02d}", day(n))
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "newer", cwd=self.repo,
            env={"GIT_AUTHOR_DATE": day(20), "GIT_COMMITTER_DATE": day(20)},
        )
        self.run_clean("git", "push", "-q", "origin", "main", cwd=self.repo)
        out = self.json_out(self._list())
        self.assertEqual(len(out["names"]), 10, msg=f"names -> {out}")
        self.assertEqual(out["names"].count("main"), 1, msg=f"names -> {out}")
        self.assertEqual(len(self._rows(out)), 10, msg=f"rows -> {out}")

    def test_missing_batch_branches(self):
        c = "cfq/003-2026-01-03-c"
        self._branch(A, day(1))
        self._branch(B, day(2), start=A)
        self._branch(c, day(3), start=B)
        out = self.json_out(self._list())
        self.assertTrue(self._row(out, A).endswith("missing 2 cfq branches"), msg=out["listText"])
        self.assertTrue(self._row(out, B).endswith("missing 1 cfq branch"), msg=out["listText"])
        self.assertNotIn("missing", self._row(out, c), msg=out["listText"])
        self.assertTrue(
            self._row(out, "main").endswith("default · missing 3 cfq branches"), msg=out["listText"]
        )

    def test_local_only(self):
        self._branch("loc", day(1), push=False)
        self._branch("feature", day(2))
        out = self.json_out(self._list())
        self.assertIn("local only", self._row(out, "loc"), msg=out["listText"])
        self.assertNotIn("local only", self._row(out, "feature"), msg=out["listText"])

    def test_limit(self):
        for n in range(1, 6):
            self._branch(f"f{n:02d}", day(n))
        out = self.json_out(self._list("--limit", "3"))
        self.assertEqual(out["names"], ["f05", "f04", "f03", "main"], msg=f"names -> {out}")
        lines = out["listText"].splitlines()
        self.assertEqual(lines[0], "BRANCHES · newest 3 of 6", msg=f"header -> {lines}")
        self.assertEqual(len(lines), 5, msg=f"lines -> {lines}")

    def test_equal_commit_time_orders_by_batch_number_then_name(self):
        self._branch(A, day(1))
        self._branch(B, day(1))
        self._branch("zeta", day(1))
        self._branch("alpha", day(1))
        out = self.json_out(self._list())
        self.assertEqual(
            out["names"], [B, A, "alpha", "zeta", "main"], msg=f"names -> {out}"
        )

    def test_no_trailing_whitespace(self):
        self._branch(A, day(1))
        self._branch("feature", day(2))
        out = self.json_out(self._list())
        for line in out["listText"].splitlines():
            self.assertEqual(line, line.rstrip(), msg=f"trailing whitespace -> {line!r}")

    def test_without_origin_still_prints(self):
        lone = self._repos_dir / "lone"
        lone.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=lone)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=lone,
        )
        self.run_clean("git", "branch", "feature", cwd=lone)
        out = self.json_out(self._list(repo=lone))
        self.assertEqual(out["status"], "OK", msg=f"status -> {out}")
        self.assertEqual(sorted(out["names"]), ["feature", "main"], msg=f"names -> {out}")
        self.assertEqual(out["defaultBranch"], "main", msg=f"defaultBranch -> {out}")
        self.assertTrue(out["listText"].startswith("BRANCHES · newest 2 of 2"), msg=out)

    def test_outside_git_repo_reports_no_repo(self):
        non_repo = self._repos_dir / "not-a-repo"
        non_repo.mkdir()
        proc = self._list(repo=non_repo)
        self.assertNotIn("Traceback", proc.stderr, msg=f"raw traceback -> {proc.stderr}")
        out = self.json_out(proc)
        self.assertEqual(out["status"], "NO_REPO", msg=f"status -> {out}")


class BranchCheckTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir()
        self.run_clean("git", "init", "-q", "-b", "main", cwd=self.repo)
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo,
        )

    def _check(self, name, repo=None):
        return self.run_cfq("branch", "check", str(repo or self.repo), name, check=True)

    def _add_origin(self, repo=None):
        repo = repo or self.repo
        remote = self._repos_dir / f"{repo.name}-remote.git"
        self.run_clean("git", "init", "-q", "--bare", "-b", "main", str(remote))
        self.run_clean("git", "remote", "add", "origin", str(remote), cwd=repo)
        self.run_clean("git", "push", "-q", "origin", "main", cwd=repo)
        return remote

    def _commit(self, repo=None, msg="commit", date=None):
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else None
        self.run_clean(
            "git", "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "--allow-empty", "-q", "-m", msg, cwd=repo or self.repo, env=env,
        )

    def test_routine_same_commit(self):
        # origin/feature and local feature at the same commit -> OK, ref is the origin ref,
        # ahead/behind both 0.
        self._add_origin()
        self.run_clean("git", "checkout", "-q", "-b", "feature", cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["status"], "OK", msg=f"routine status -> {out}")
        self.assertEqual(out["ref"], "refs/remotes/origin/feature", msg=f"routine ref -> {out}")
        self.assertEqual(out["behind"], 0, msg=f"routine behind -> {out}")
        self.assertEqual(out["ahead"], 0, msg=f"routine ahead -> {out}")
        self.assertFalse(out["localOnly"], msg=f"routine localOnly -> {out}")

    def test_remote_only_resolves_through_origin(self):
        # Branch pushed, local ref deleted -> resolves through origin/, localOnly false.
        self._add_origin()
        self.run_clean("git", "checkout", "-q", "-b", "feature", cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        self.run_clean("git", "branch", "-q", "-D", "feature", cwd=self.repo)
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["status"], "OK", msg=f"remote-only status -> {out}")
        self.assertFalse(out["localOnly"], msg=f"remote-only localOnly -> {out}")
        self.assertEqual(out["ref"], "refs/remotes/origin/feature", msg=f"remote-only ref -> {out}")

    def test_local_only_never_pushed(self):
        # Branch created locally, never pushed -> localOnly true, ref is the local ref.
        self.run_clean("git", "branch", "feature", cwd=self.repo)
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["status"], "OK", msg=f"local-only status -> {out}")
        self.assertTrue(out["localOnly"], msg=f"local-only localOnly -> {out}")
        self.assertEqual(out["ref"], "refs/heads/feature", msg=f"local-only ref -> {out}")

    def test_behind_origin(self):
        # Local reset one commit back from origin/<name> -> behind 1, ahead 0.
        self._add_origin()
        self.run_clean("git", "checkout", "-q", "-b", "feature", cwd=self.repo)
        self._commit(msg="ahead-on-remote")
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        self.run_clean("git", "reset", "-q", "--hard", "HEAD~1", cwd=self.repo)
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["behind"], 1, msg=f"behind -> {out}")
        self.assertEqual(out["ahead"], 0, msg=f"behind-case ahead -> {out}")

    def test_ahead_of_origin(self):
        # One local commit not pushed -> ahead 1, behind 0.
        self._add_origin()
        self.run_clean("git", "checkout", "-q", "-b", "feature", cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        self._commit(msg="unpushed")
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["ahead"], 1, msg=f"ahead -> {out}")
        self.assertEqual(out["behind"], 0, msg=f"ahead-case behind -> {out}")

    def test_diverged(self):
        # One local and one remote commit from a common base -> ahead 1, behind 1.
        self._add_origin()
        self.run_clean("git", "checkout", "-q", "-b", "feature", cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        clone = self._repos_dir / "clone"
        self.run_clean("git", "clone", "-q", str(self._repos_dir / f"{self.repo.name}-remote.git"), str(clone))
        self.run_clean("git", "checkout", "-q", "feature", cwd=clone)
        self._commit(repo=clone, msg="remote-side")
        self.run_clean("git", "push", "-q", "origin", "feature", cwd=clone)
        self._commit(msg="local-side")
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["ahead"], 1, msg=f"diverged ahead -> {out}")
        self.assertEqual(out["behind"], 1, msg=f"diverged behind -> {out}")

    def test_newer_candidate_reported(self):
        # A second branch with a later committer date is reported as newerCandidate.
        self._add_origin()
        self.run_clean("git", "checkout", "-q", "-b", "feature", cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "-b", "newer-topic", "main", cwd=self.repo)
        self._commit(msg="newer", date="2030-01-01T00:00:00")
        self.run_clean("git", "push", "-q", "-u", "origin", "newer-topic", cwd=self.repo)
        out = self.json_out(self._check("feature"))
        self.assertIsNotNone(out["newerCandidate"], msg=f"newerCandidate -> {out}")
        self.assertEqual(out["newerCandidate"]["name"], "newer-topic", msg=f"newerCandidate name -> {out}")
        self.assertTrue(out["newerCandidate"]["lastCommit"], msg=f"newerCandidate lastCommit -> {out}")

    def test_check_reports_batch_role_and_uncontained(self):
        # Two sibling batch branches: checking the higher one names the lower as uncontained;
        # the default branch is flagged and misses both.
        self._add_origin()
        for name, date in ((A, day(1)), (B, day(2))):
            self.run_clean("git", "checkout", "-q", "-b", name, "main", cwd=self.repo)
            self._commit(msg=name, date=date)
            self.run_clean("git", "push", "-q", "-u", "origin", name, cwd=self.repo)
            self.run_clean("git", "checkout", "-q", "main", cwd=self.repo)
        out = self.json_out(self._check(B))
        self.assertTrue(out["isCfq"], msg=f"isCfq -> {out}")
        self.assertFalse(out["isDefault"], msg=f"isDefault -> {out}")
        self.assertEqual([u["name"] for u in out["uncontained"]], [A], msg=f"unc -> {out}")
        self.assertEqual(out["uncontainedCount"], 1, msg=f"count -> {out}")
        out = self.json_out(self._check("main"))
        self.assertFalse(out["isCfq"], msg=f"main isCfq -> {out}")
        self.assertTrue(out["isDefault"], msg=f"main isDefault -> {out}")
        self.assertEqual(out["uncontainedCount"], 2, msg=f"main count -> {out}")

    def test_check_batch_adds_dependency_branches(self):
        # A non-batch dependency branch only shows up when --batch names the batch that depends
        # on it, and is then flagged `dependency: true`.
        self._add_origin()
        dep = "cfq/2026-01-01-legacy"
        self.run_clean("git", "checkout", "-q", "-b", dep, "main", cwd=self.repo)
        self._commit(msg="dep", date=day(1))
        self.run_clean("git", "push", "-q", "-u", "origin", dep, cwd=self.repo)
        self.run_clean("git", "checkout", "-q", "-b", "feature", "main", cwd=self.repo)
        self.run_clean("git", "push", "-q", "-u", "origin", "feature", cwd=self.repo)
        batch_dir = self.repo / ".claude" / "cfq" / "impl" / "2026-02-14-topic"
        batch_dir.mkdir(parents=True)
        (batch_dir / ".dependsOn").write_text("2026-01-01-legacy\n")
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["uncontained"], [], msg=f"without --batch -> {out}")
        proc = self.run_cfq(
            "branch", "check", str(self.repo), "feature", "--batch", "2026-02-14-topic", check=True
        )
        out = self.json_out(proc)
        self.assertEqual([u["name"] for u in out["uncontained"]], [dep], msg=f"--batch -> {out}")
        self.assertTrue(out["uncontained"][0]["dependency"], msg=f"dependency -> {out}")
        self.assertEqual(out["uncontainedCount"], 1, msg=f"count -> {out}")

    def test_unknown_name_unresolved(self):
        # A name that exists nowhere -> UNRESOLVED, exit 0, ref null.
        proc = self._check("does-not-exist")
        self.assertEqual(proc.returncode, 0, msg=f"unresolved exit code -> {proc}")
        out = self.json_out(proc)
        self.assertEqual(out["status"], "UNRESOLVED", msg=f"unresolved status -> {out}")
        self.assertIsNone(out["ref"], msg=f"unresolved ref -> {out}")

    def test_offline_no_origin(self):
        # No origin at all -> OK, remoteChecked false, local ref used.
        self.run_clean("git", "branch", "feature", cwd=self.repo)
        out = self.json_out(self._check("feature"))
        self.assertEqual(out["status"], "OK", msg=f"offline status -> {out}")
        self.assertFalse(out["remoteChecked"], msg=f"offline remoteChecked -> {out}")
        self.assertEqual(out["ref"], "refs/heads/feature", msg=f"offline ref -> {out}")


if __name__ == "__main__":
    unittest.main()
