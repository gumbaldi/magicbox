"""Migrated from test-ifq-preflight.sh (scripts/cfq_ifq_preflight.py, ported from
cfq-ifq-preflight.sh in batch `017` phase 11).

The stub renames `cfq_branch.py` and shadows it by filename -- `cfq-branch.sh` was ported to
Python in batch `017` phase 09 (see batch `014` phase 02 for the shadowing pattern itself).
"""

import json
import shutil
import sys
import time
import unittest

from cfq_testlib import CfqTestCase, PLUGIN_ROOT, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import text  # noqa: E402


class IfqPreflightTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        # Copies the whole scripts/ dir so cfq_ifq_preflight.py's own script_dir resolution
        # (and every sibling script it shells out to, e.g. cfq_resume.py -> cfq_branch.py)
        # resolves inside the copy, then swaps cfq_branch.py for a wrapper that logs every
        # invocation before delegating to the real binary. bin/ is copied alongside scripts/
        # (same relative layout as the real plugin) because internal sibling calls now route
        # through bin/cfq, which resolves its own NOUN_SCRIPT table relative to itself.
        self.scripts_copy = self._repos_dir / "scripts"
        shutil.copytree(PLUGIN_ROOT / "scripts", self.scripts_copy)
        shutil.copytree(PLUGIN_ROOT / "bin", self._repos_dir / "bin")
        real = self.scripts_copy / "cfq_branch_real.py"
        (self.scripts_copy / "cfq_branch.py").rename(real)
        self.count_log = self._repos_dir / "branch-calls.log"
        self.count_log.write_text("")
        stub = self.scripts_copy / "cfq_branch.py"
        stub.write_text(f"""#!/usr/bin/env python3
import subprocess
import sys

with open({str(self.count_log)!r}, "a") as f:
    f.write("call\\n")
sys.exit(subprocess.run([sys.executable, {str(real)!r}] + sys.argv[1:]).returncode)
""")
        stub.chmod(0o755)
        self.pf = self.scripts_copy / "cfq_ifq_preflight.py"

    def _run_pf(self, *args, home=None, env=None):
        run_env = {"HOME": str(home if home is not None else self.home)}
        if env:
            run_env.update(env)
        return self.run_clean("python3", str(self.pf), *args, env=run_env)

    def _calls(self):
        return len(self.count_log.read_text().splitlines())

    def _setup_repo(self, name):
        repo = self._repos_dir / name
        self.run_clean("git", "init", "-q", "-b", "main", str(repo))
        self.run_clean(
            "git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=a",
            "commit", "-q", "--allow-empty", "-m", "init",
        )
        self.run_clean(
            "python3", str(self.scripts_copy / "cfq_registry.py"), "add", str(repo),
        )
        return repo

    def test_no_repo(self):
        out = self.json_out(self._run_pf(str(self._repos_dir / "does-not-exist")))
        self.assertEqual(out["status"], "NO_REPO", msg=f"non-git status = {out}")
        self.assertNotIn("inbox", out, msg=f"NO_REPO result should carry no inbox key: {out}")

    # ---- inbox.overview (batch 037 phase 03) --------------------------------------------------

    def test_inbox_overview_matches_real_note_list_call(self):
        repo = self._setup_repo("inbox-overview-reg")
        plan_dir = repo / ".claude" / "cfq" / "plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "2026-01-01-first.md").write_text("# First\n\nDo it.\n")
        (plan_dir / "2026-01-02-second.md").write_text("# Second\n\nDo it too.\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["inbox"]["count"], 2, msg=f"inbox = {out['inbox']}")
        direct = self.run_clean(
            "python3", str(self.scripts_copy / "cfq_note.py"), "list", str(repo), "--overview",
        ).stdout.rstrip("\n")
        self.assertEqual(
            out["inbox"]["overview"], direct,
            msg=f"inbox.overview = {out['inbox']['overview']!r}, direct call = {direct!r}",
        )

    def test_inbox_overview_empty_plan_dir(self):
        repo = self._setup_repo("inbox-overview-empty")
        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["inbox"]["overview"], "INBOX  empty", msg=f"inbox = {out['inbox']}")
        self.assertEqual(out["inbox"]["count"], 0, msg=f"inbox = {out['inbox']}")

    def test_inbox_present_on_empty_result_path(self):
        # empty_result path (NO_BATCH, no open batch at all) -- the inbox key must still be
        # present here, since that is exactly when the user wants to see what still needs
        # planning.
        repo = self._setup_repo("inbox-no-open-batch")
        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "NO_BATCH", msg=f"status = {out}")
        self.assertIn("inbox", out, msg=f"inbox key missing on empty_result path: {out}")
        self.assertEqual(out["inbox"]["overview"], "INBOX  empty", msg=f"inbox = {out['inbox']}")

    def test_continue_mode_calls_branch_once(self):
        repo1 = self._setup_repo("continue-repo")
        batch = repo1 / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")
        self.run_clean("git", "-C", str(repo1), "branch", "cfq/2026-01-01-solo")

        self.count_log.write_text("")
        out = self.json_out(self._run_pf(str(repo1)))
        self.assertEqual(out["status"], "OK", msg=f"continue-mode status = {out}")
        self.assertEqual(out["branch"]["mode"], "continue", msg=f"expected continue mode = {out}")
        self.assertEqual(self._calls(), 1, msg=f"continue-mode cfq_branch.py calls = {self._calls()}, want 1")
        self.assertTrue(
            "implExploreModel" in out["policy"] and "implExploreModelComplex" in out["policy"],
            msg=f"policy missing implExploreModel/implExploreModelComplex: {out}",
        )
        self.assertTrue(
            "reportDir" in out["reporting"] and "htmlReport" in out["reporting"],
            msg=f"missing reporting object: {out}",
        )

    def test_use_ponytail_audit_not_in_policy(self):
        repo = self._setup_repo("ponytail-policy")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertNotIn("usePonytailAudit", out["policy"], msg=f"policy = {out['policy']}")

        out = self.json_out(self._run_pf(str(repo), env={"CFQ_USE_PONYTAIL": "false"}))
        self.assertNotIn("usePonytailAudit", out["policy"], msg=f"policy = {out['policy']}")

        # empty-result path (NO_BATCH) still emits policy, still without usePonytailAudit
        empty_repo = self._setup_repo("ponytail-policy-empty")
        out = self.json_out(self._run_pf(str(empty_repo)))
        self.assertEqual(out["status"], "NO_BATCH", msg=f"empty repo status = {out}")
        self.assertNotIn("usePonytailAudit", out["policy"], msg=f"NO_BATCH policy: {out}")

    def test_orchestrator_policy_present_and_true_by_default(self):
        repo = self._setup_repo("orch-default")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(
            out["policy"]["orchestratorMode"], True, msg=f"orchestratorMode default = {out['policy']}"
        )

    def test_orchestrator_models_falls_back_to_impl_models(self):
        repo = self._setup_repo("orch-fallback")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(
            out["policy"]["orchestratorModels"], ["sonnet"],
            msg=f"orchestratorModels should fall back to implModels: {out['policy']}",
        )

    def test_orchestrator_models_override_leaves_impl_models_untouched(self):
        repo = self._setup_repo("orch-override")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")

        out = self.json_out(self._run_pf(str(repo), env={"CFQ_ORCHESTRATOR_MODELS": "opus"}))
        self.assertEqual(
            out["policy"]["orchestratorModels"], ["opus"], msg=f"override = {out['policy']}"
        )
        self.assertEqual(
            out["policy"]["implModels"], ["sonnet"],
            msg=f"fallback substitution must not overwrite implModels: {out['policy']}",
        )

    def test_orchestrator_models_empty_is_a_legitimate_answer(self):
        repo = self._setup_repo("orch-both-empty")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")
        (repo / ".claude" / "cfq" / "settings.json").write_text(json.dumps({"implModels": []}))

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(
            out["policy"]["orchestratorModels"], [],
            msg=f"both empty should stay empty, not error: {out['policy']}",
        )

    def test_new_mode_calls_branch_twice_across_sequence(self):
        # new mode: preflight (1) + mutation's post-checkout confirm (1) = 2, combined across
        # the sequence.
        repo2 = self._setup_repo("new-repo")
        batch = repo2 / ".claude" / "cfq" / "impl" / "2026-01-01-fresh"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nL\n")

        self.count_log.write_text("")
        out = self.json_out(self._run_pf(str(repo2)))
        self.assertEqual(out["branch"]["mode"], "new", msg=f"expected new mode = {out}")
        branch = out["branch"]["branch"]
        self.run_clean("git", "-C", str(repo2), "checkout", "-q", "-b", branch)
        self.run_clean(
            "python3", str(self.scripts_copy / "cfq_branch.py"), "plan", str(repo2), "2026-01-01-fresh",
            env={"HOME": str(self.home)},
        )
        self.assertEqual(self._calls(), 2, msg=f"new-mode cfq_branch.py calls = {self._calls()}, want 2")

    def test_selection_filters(self):
        repo3 = self._setup_repo("multi-repo")
        qdir = repo3 / ".claude" / "cfq" / "impl"
        for name in ["2026-01-01-alpha", "2026-01-02-beta", "2026-01-03-blocked", "2026-01-04-planning"]:
            (qdir / name).mkdir(parents=True)
        (qdir / "2026-01-01-alpha" / "01-a.md").touch()
        (qdir / "2026-01-02-beta" / "01-b.md").touch()
        (qdir / "2026-01-03-blocked" / "01-c.md").touch()
        (qdir / "2026-01-04-planning" / "01-d.md").touch()
        (qdir / "2026-01-03-blocked" / ".dependsOn").write_text("2026-01-01-alpha\n")
        (qdir / "2026-01-04-planning" / ".planning").touch()

        out = self.json_out(self._run_pf(str(repo3)))
        self.assertEqual(out["status"], "OK", msg=f"multi status = {out}")
        self.assertEqual(
            out["batch"]["name"], "2026-01-01-alpha",
            msg=f"2+ selectable should auto-pick the first by order: {out}",
        )
        self.assertEqual(
            out["nextPhase"]["slug"], "01-a", msg=f"2+ selectable nextPhase: {out}"
        )
        got = sorted(b["name"] for b in out["selection"]["selectable"])
        self.assertEqual(got, ["2026-01-01-alpha", "2026-01-02-beta"], msg=f"selectable = {got}")
        self.assertEqual(
            [b["name"] for b in out["selection"]["blocked"]], ["2026-01-03-blocked"],
            msg=f"blocked = {out}",
        )
        self.assertEqual(
            out["selection"]["planning"], ["2026-01-04-planning"], msg=f"planning = {out}"
        )

        # --select round-trip resolves one of the ambiguous batches
        out = self.json_out(self._run_pf(str(repo3), "--select", "2026-01-02-beta"))
        self.assertEqual(
            out["batch"]["name"], "2026-01-02-beta", msg=f"--select did not resolve batch: {out}"
        )
        self.assertEqual(out["nextPhase"]["slug"], "01-b", msg=f"--select nextPhase: {out}")

    def test_multiple_selectable_high_priority_first(self):
        repo = self._setup_repo("multi-priority")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-01-01-alpha").mkdir(parents=True)
        (qdir / "2026-01-02-beta").mkdir(parents=True)
        (qdir / "2026-01-01-alpha" / "01-a.md").touch()
        (qdir / "2026-01-02-beta" / "01-b.md").touch()
        (qdir / "2026-01-02-beta" / ".priority").write_text("high\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"multi-priority status = {out}")
        self.assertEqual(
            out["batch"]["name"], "2026-01-02-beta",
            msg=f"flagged batch should be chosen over an earlier-named one: {out}",
        )

    def test_select_unavailable_batch(self):
        repo = self._setup_repo("select-unavailable")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-01-01-alpha").mkdir(parents=True)
        (qdir / "2026-01-02-blocked").mkdir(parents=True)
        (qdir / "2026-01-01-alpha" / "01-a.md").touch()
        (qdir / "2026-01-02-blocked" / "01-b.md").touch()
        (qdir / "2026-01-02-blocked" / ".dependsOn").write_text("2026-01-01-alpha\n")

        out = self.json_out(self._run_pf(str(repo), "--select", "2026-01-02-blocked"))
        self.assertEqual(out["status"], "SELECT_UNAVAILABLE", msg=f"blocked --select = {out}")
        self.assertIsNone(out["batch"], msg=f"blocked --select should leave batch null: {out}")
        self.assertEqual(
            [b["name"] for b in out["selection"]["blocked"]], ["2026-01-02-blocked"],
            msg=f"blocked --select selection = {out}",
        )

        out = self.json_out(self._run_pf(str(repo), "--select", "does-not-exist"))
        self.assertEqual(out["status"], "SELECT_UNAVAILABLE", msg=f"unknown --select = {out}")
        self.assertIsNone(out["batch"], msg=f"unknown --select should leave batch null: {out}")

    def test_blocked_only_auto_selects_unblocked_dep(self):
        # only blocked batches left -> BLOCKED never happens if an unblocked dep exists (a real,
        # unfinished dependency actually blocks)
        repo4 = self._setup_repo("blocked-only")
        (repo4 / ".claude" / "cfq" / "impl" / "2026-01-01-dep").mkdir(parents=True)
        (repo4 / ".claude" / "cfq" / "impl" / "2026-01-02-b").mkdir(parents=True)
        (repo4 / ".claude" / "cfq" / "impl" / "2026-01-01-dep" / "01-x.md").touch()
        (repo4 / ".claude" / "cfq" / "impl" / "2026-01-02-b" / "01-x.md").touch()
        (repo4 / ".claude" / "cfq" / "impl" / "2026-01-02-b" / ".dependsOn").write_text("2026-01-01-dep\n")
        out = self.json_out(self._run_pf(str(repo4)))
        self.assertEqual(out["status"], "OK", msg=f"blocked-only status = {out}")
        self.assertEqual(
            out["batch"]["name"], "2026-01-01-dep",
            msg=f"should auto-select the unblocked dep batch: {out}",
        )
        got = [b["name"] for b in out["selection"]["blocked"]]
        self.assertEqual(got, ["2026-01-02-b"], msg=f"blocked list = {got}")

    def test_unknown_dependency_never_blocks(self):
        # an unresolvable dependency name is surfaced but never blocks
        repo4b = self._setup_repo("unknown-dep")
        (repo4b / ".claude" / "cfq" / "impl" / "2026-01-01-b").mkdir(parents=True)
        (repo4b / ".claude" / "cfq" / "impl" / "2026-01-01-b" / "01-x.md").touch()
        (repo4b / ".claude" / "cfq" / "impl" / "2026-01-01-b" / ".dependsOn").write_text("does-not-exist\n")
        out = self.json_out(self._run_pf(str(repo4b)))
        self.assertEqual(out["status"], "OK", msg=f"unknown-dep should not block: {out}")
        self.assertEqual(
            out["batch"]["name"], "2026-01-01-b", msg=f"unknown-dep batch should be selectable: {out}"
        )

    def test_selection_entries_carry_goal_field(self):
        repo = self._setup_repo("goal-selection")
        qdir = repo / ".claude" / "cfq" / "impl"
        long_batch = qdir / "2026-01-01-alpha"
        long_batch.mkdir(parents=True)
        (long_batch / "01-a.md").touch()
        long_goal = " ".join(f"word{i}" for i in range(60))
        (long_batch / ".batch-context.md").write_text(f"# Batch Context\n\n## Goal\n\n{long_goal}\n")

        no_context_batch = qdir / "2026-01-02-beta"
        no_context_batch.mkdir(parents=True)
        (no_context_batch / "01-b.md").touch()

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"goal-selection status = {out}")
        by_name = {b["name"]: b for b in out["selection"]["selectable"]}
        self.assertIn("goal", by_name["2026-01-01-alpha"], msg=f"goal key missing: {out}")
        alpha_goal = by_name["2026-01-01-alpha"]["goal"]
        self.assertLessEqual(len(alpha_goal), 121, msg=f"goal not cut to 120: {alpha_goal!r}")
        self.assertTrue(alpha_goal.endswith("…"), msg=f"goal not ellipsized: {alpha_goal!r}")
        self.assertIsNone(by_name["2026-01-02-beta"]["goal"], msg=f"no context -> goal should be null: {out}")

    def test_resolved_batch_brief_text_contains_goal(self):
        repo = self._setup_repo("goal-resolved")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\n\nSolo batch goal.\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertIn(
            "goal: Solo batch goal.", out["batch"]["briefText"].splitlines(),
            msg=f"resolved batch briefText missing goal line: {out['batch']['briefText']!r}",
        )

    def test_all_done_not_finished_batch_resumes_with_null_next_phase(self):
        repo = self._setup_repo("all-done-not-finished")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-unfinished"
        (batch / "done").mkdir(parents=True)
        (batch / "done" / "01-a.md").touch()
        (batch / "done" / "02-b.md").touch()

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"all-done-not-finished status = {out}")
        self.assertEqual(
            out["selection"]["inProgress"], "2026-01-01-unfinished", msg=f"inProgress = {out}"
        )
        self.assertEqual(out["batch"]["name"], "2026-01-01-unfinished", msg=f"batch = {out}")
        self.assertIsNone(out["nextPhase"], msg=f"nextPhase should be null: {out}")
        self.assertIsNone(out["contextGate"], msg=f"contextGate should be null: {out}")

    def test_all_done_not_finished_batch_still_blocks_a_dependent(self):
        repo = self._setup_repo("unfinished-blocks-dependent")
        qdir = repo / ".claude" / "cfq" / "impl"
        a = qdir / "2026-01-01-a"
        (a / "done").mkdir(parents=True)
        (a / "done" / "01-x.md").touch()
        b = qdir / "2026-01-02-b"
        b.mkdir(parents=True)
        (b / "01-y.md").touch()
        (b / ".dependsOn").write_text("2026-01-01-a\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        self.assertEqual(out["batch"]["name"], "2026-01-01-a", msg=f"resolved batch = {out}")
        self.assertEqual(
            [x["name"] for x in out["selection"]["blocked"]], ["2026-01-02-b"], msg=f"blocked = {out}"
        )

    def test_zero_zero_batch_alone_is_no_batch(self):
        repo = self._setup_repo("zero-zero-alone")
        (repo / ".claude" / "cfq" / "impl" / "2026-01-01-empty").mkdir(parents=True)
        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "NO_BATCH", msg=f"0/0-only status = {out}")

    def test_no_batch(self):
        # nothing at all -> NO_BATCH
        repo5 = self._setup_repo("empty-repo")
        out = self.json_out(self._run_pf(str(repo5)))
        self.assertEqual(out["status"], "NO_BATCH", msg=f"empty-repo status = {out}")

    def test_multiple_in_progress(self):
        repo6 = self._setup_repo("multi-inprogress")
        qdir6 = repo6 / ".claude" / "cfq" / "impl"
        (qdir6 / "2026-01-01-a" / "done").mkdir(parents=True)
        (qdir6 / "2026-01-02-b" / "done").mkdir(parents=True)
        (qdir6 / "2026-01-01-a" / "01-x.md").touch()
        (qdir6 / "2026-01-01-a" / "done" / "00-y.md").touch()
        (qdir6 / "2026-01-02-b" / "01-x.md").touch()
        (qdir6 / "2026-01-02-b" / "done" / "00-y.md").touch()
        out = self.json_out(self._run_pf(str(repo6)))
        self.assertEqual(out["status"], "MULTIPLE_IN_PROGRESS", msg=f"multi-inprogress status = {out}")
        got = sorted(out["selection"]["multipleInProgress"])
        self.assertEqual(got, ["2026-01-01-a", "2026-01-02-b"], msg=f"multipleInProgress = {got}")

    def test_single_in_progress_auto_selects(self):
        repo7 = self._setup_repo("single-inprogress")
        qdir7 = repo7 / ".claude" / "cfq" / "impl"
        (qdir7 / "2026-01-01-inprog" / "done").mkdir(parents=True)
        (qdir7 / "2026-01-02-other").mkdir(parents=True)
        (qdir7 / "2026-01-01-inprog" / "01-a.md").touch()
        (qdir7 / "2026-01-01-inprog" / "done" / "00-x.md").touch()
        (qdir7 / "2026-01-02-other" / "01-b.md").touch()
        out = self.json_out(self._run_pf(str(repo7)))
        self.assertEqual(out["status"], "OK", msg=f"single-inprogress status = {out}")
        self.assertEqual(
            out["selection"]["inProgress"], "2026-01-01-inprog", msg=f"inProgress field = {out}"
        )
        self.assertEqual(
            out["batch"]["name"], "2026-01-01-inprog", msg=f"auto-selected batch = {out}"
        )

    def test_consistency_field_carried_through(self):
        repo = self._setup_repo("consistency-carry")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").touch()
        (batch / "02-b.md").touch()
        (batch / "report.json").write_text(json.dumps({
            "repo": "x", "batch": "2026-01-01-solo", "started": "t",
            "phases": [{"phase": "99-gone", "status": "green", "commit": "abc"}],
        }))
        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(
            out["batch"]["consistency"], "divergent",
            msg=f"a green ledger entry with no done/ file should carry through as divergent: {out}",
        )

    def test_failed_attempt(self):
        repo8 = self._setup_repo("failed-attempt")
        batch = repo8 / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nM\n")
        out = self.json_out(self._run_pf(str(repo8)))
        self.assertFalse(out["nextPhase"]["failedAttempt"]["found"], msg=f"no red entry yet: {out}")

        pf = batch / "_phase.json"
        pf.write_text(
            '{"phase":"01-a","status":"red","finished":"2026-01-01T00:00:00+00:00","summary":"boom",'
            '"deviations":[],"errors":["x"],"verification":"x","commit":""}'
        )
        self.run_clean(
            "python3", str(self.scripts_copy / "cfq_phase.py"), "record", str(batch), str(pf),
            "--no-telemetry", env={"HOME": str(self.home)},
        )
        out = self.json_out(self._run_pf(str(repo8)))
        self.assertTrue(out["nextPhase"]["failedAttempt"]["found"], msg=f"red entry not found: {out}")
        self.assertEqual(out["nextPhase"]["failedAttempt"]["note"], "boom", msg=f"failedAttempt note: {out}")

        # no report.json at all anywhere -> {"found": false}, no crash
        fresh_batch = repo8.parent / "fresh-no-report" / "2026-01-01-solo"
        fresh_batch.mkdir(parents=True)
        proc = self.run_clean(
            "python3", str(self.scripts_copy / "cfq_report.py"), "last-failure",
            str(fresh_batch), "01-a", env={"HOME": str(self.home)},
        )
        self.assertFalse(
            json.loads(proc.stdout)["found"],
            msg="last-failure on batch with no report.json should be found=false",
        )

    def test_context_gate_defaults_to_m(self):
        # contextGate defaults to M when ## Size is missing
        repo9 = self._setup_repo("no-size")
        batch = repo9 / ".claude" / "cfq" / "impl" / "2026-01-01-nosize"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n")
        out = self.json_out(self._run_pf(str(repo9)))
        self.assertEqual(out["contextGate"]["size"], "M", msg=f"missing ## Size should default to M: {out}")
        direct_gate = self.run_clean(
            "python3", str(self.scripts_copy / "ctx_usage.py"), "gate", "M",
            env={"HOME": str(self.home)},
        ).stdout
        # The original Bash test only ever looked for START/HANDOFF here, silently missing WARN
        # (the verdict ctx_usage.py returns when no statusline payload/transcript is reachable
        # under an isolated $HOME, as in this sandbox) -- broadened to all three verdicts so the
        # comparison is meaningful regardless of whether a live payload is resolvable.
        direct_verdict = next(
            (tok for tok in direct_gate.split() if tok in ("START", "HANDOFF", "WARN")), None
        )
        self.assertEqual(
            out["contextGate"]["verdict"], direct_verdict,
            msg="contextGate.verdict != ctx_usage.py gate's own verdict",
        )

    def test_deterministic_and_read_only(self):
        repo8 = self._setup_repo("failed-attempt-2")
        batch = repo8 / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nM\n")

        out1 = self._run_pf(str(repo8)).stdout
        out2 = self._run_pf(str(repo8)).stdout
        self.assertEqual(out1, out2, msg="two runs on the same fixture produced different output")

        marker = self._repos_dir / "marker"
        marker.touch()
        time.sleep(1)
        self._run_pf(str(repo8))
        changed = self.run_clean("find", str(repo8), "-newer", str(marker)).stdout
        self.assertEqual(changed, "", msg=f"run modified files under the fixture repo: {changed}")

    # ---- selection.queueText (batch 035 phase 03) --------------------------------------------

    def test_queue_text_three_open_batches(self):
        repo = self._setup_repo("queue-three")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "035-2026-09-22-ifq-batch-gate").mkdir(parents=True)
        (qdir / "035-2026-09-22-ifq-batch-gate" / "01-a.md").touch()
        (qdir / "036-2026-09-22-render-cleanup").mkdir(parents=True)
        (qdir / "036-2026-09-22-render-cleanup" / "01-b.md").touch()
        (qdir / "036-2026-09-22-render-cleanup" / ".dependsOn").write_text(
            "035-2026-09-22-ifq-batch-gate\n"
        )
        (qdir / "037-2026-09-23-cleanup-pass").mkdir(parents=True)
        (qdir / "037-2026-09-23-cleanup-pass" / "01-c.md").touch()
        (qdir / "037-2026-09-23-cleanup-pass" / ".planning").touch()

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        self.assertEqual(
            out["batch"]["name"], "035-2026-09-22-ifq-batch-gate", msg=f"chosen batch = {out}"
        )

        rows = [
            ["035", "2026-09-22", "ifq-batch-gate", "ready · selected"],
            ["036", "2026-09-22", "render-cleanup",
             "blocked → waits on 035-2026-09-22-ifq-batch-gate"],
            ["037", "2026-09-23", "cleanup-pass", "planning"],
        ]
        expected = "QUEUE · 3 open\n" + "\n".join(
            text.table(rows, headers=["#", "Date", "Topic", "Status"])
        )
        self.assertEqual(
            out["selection"]["queueText"], expected,
            msg=f"queueText = {out['selection']['queueText']!r}",
        )

    def test_queue_text_unknown_dependency_shown_in_same_cell(self):
        repo = self._setup_repo("queue-unknown-dep")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-01-01-alpha").mkdir(parents=True)
        (qdir / "2026-01-01-alpha" / "01-a.md").touch()
        (qdir / "2026-01-02-blocked").mkdir(parents=True)
        (qdir / "2026-01-02-blocked" / "01-b.md").touch()
        (qdir / "2026-01-02-blocked" / ".dependsOn").write_text(
            "2026-01-01-alpha\ndoes-not-exist\n"
        )

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        self.assertEqual(
            [b["name"] for b in out["selection"]["blocked"]], ["2026-01-02-blocked"],
            msg=f"blocked list = {out}",
        )
        qtext = out["selection"]["queueText"]
        lines = qtext.splitlines()
        self.assertEqual(lines[0], "QUEUE · 2 open", msg=f"header = {lines[0]!r}; row count changed")
        blocked_line = next(l for l in lines if "2026-01-02-blocked" in l)
        self.assertIn(
            "blocked → waits on 2026-01-01-alpha, does-not-exist ⚠️ unknown: does-not-exist",
            blocked_line, msg=f"blocked line = {blocked_line!r}",
        )

    def test_queue_text_high_priority_prefixed_and_sorted_first(self):
        repo = self._setup_repo("queue-high-priority")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-01-01-alpha").mkdir(parents=True)
        (qdir / "2026-01-01-alpha" / "01-a.md").touch()
        (qdir / "2026-01-02-beta").mkdir(parents=True)
        (qdir / "2026-01-02-beta" / "01-b.md").touch()
        (qdir / "2026-01-02-beta" / ".priority").write_text("high\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        self.assertEqual(out["batch"]["name"], "2026-01-02-beta", msg=f"chosen = {out}")
        lines = out["selection"]["queueText"].splitlines()
        data_lines = lines[2:]
        self.assertIn(
            "2026-01-02-beta", data_lines[0], msg=f"flagged batch not sorted first: {data_lines}"
        )
        self.assertIn(
            "high · ready · selected", data_lines[0], msg=f"flagged status wrong: {data_lines[0]!r}"
        )

    def test_queue_text_in_progress_not_marked_selected(self):
        repo = self._setup_repo("queue-inprogress")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-02-01-inprog" / "done").mkdir(parents=True)
        (qdir / "2026-02-01-inprog" / "done" / "00-x.md").touch()
        (qdir / "2026-02-01-inprog" / "01-y.md").touch()
        (qdir / "2026-02-02-other").mkdir(parents=True)
        (qdir / "2026-02-02-other" / "01-z.md").touch()

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        self.assertEqual(
            out["selection"]["inProgress"], "2026-02-01-inprog", msg=f"inProgress = {out}"
        )
        self.assertEqual(out["batch"]["name"], "2026-02-01-inprog", msg=f"chosen = {out}")
        lines = out["selection"]["queueText"].splitlines()
        self.assertEqual(lines[0], "QUEUE · 2 open", msg=f"header = {lines[0]!r}")
        inprog_line = next(l for l in lines if "2026-02-01-inprog" in l)
        self.assertIn("in progress", inprog_line, msg=f"in-progress row wrong: {inprog_line!r}")
        self.assertNotIn(
            "selected", inprog_line, msg=f"in-progress row wrongly marked selected: {inprog_line!r}"
        )

    def test_queue_text_present_on_no_batch_and_blocked(self):
        empty_repo = self._setup_repo("queue-empty")
        out = self.json_out(self._run_pf(str(empty_repo)))
        self.assertEqual(out["status"], "NO_BATCH", msg=f"status = {out}")
        self.assertIn("queueText", out["selection"], msg=f"queueText key missing: {out}")
        self.assertIsNone(
            out["selection"]["queueText"], msg=f"empty queue queueText should be null: {out}"
        )

        blocked_repo = self._setup_repo("queue-blocked-only")
        qdir = blocked_repo / ".claude" / "cfq" / "impl"
        # a 0/0 directory (no .md files) is never a candidate itself, but its mere existence
        # still blocks a real dependent -- see test_zero_zero_batch_alone_is_no_batch.
        (qdir / "2026-01-01-a").mkdir(parents=True)
        (qdir / "2026-01-02-blocked").mkdir(parents=True)
        (qdir / "2026-01-02-blocked" / "01-b.md").touch()
        (qdir / "2026-01-02-blocked" / ".dependsOn").write_text("2026-01-01-a\n")

        out = self.json_out(self._run_pf(str(blocked_repo)))
        self.assertEqual(out["status"], "BLOCKED", msg=f"status = {out}")
        self.assertIn("queueText", out["selection"], msg=f"queueText key missing: {out}")
        qtext = out["selection"]["queueText"]
        self.assertIsNotNone(qtext, msg=f"BLOCKED queueText should be non-empty: {out}")
        self.assertTrue(qtext.startswith("QUEUE · 1 open"), msg=f"queueText = {qtext!r}")

    # ---- statusLines (batch 035 phase 08) -----------------------------------------------------

    def test_status_lines_shape(self):
        repo = self._setup_repo("statuslines-shape")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").write_text("# T\n\n## Size\n\nS\n")

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        self.assert_status_lines_shape(out["statusLines"])
        labels = [e["label"] for e in out["statusLines"]]
        self.assertEqual(
            labels, ["Model Gate", "Plugin Boundaries", "Batch"], msg=f"labels = {labels}"
        )

        # empty_result path (NO_BATCH) still carries the first two, generically shaped, no Batch
        empty_repo = self._setup_repo("statuslines-shape-empty")
        out = self.json_out(self._run_pf(str(empty_repo)))
        self.assertEqual(out["status"], "NO_BATCH", msg=f"status = {out}")
        self.assert_status_lines_shape(out["statusLines"])
        self.assertEqual(
            [e["label"] for e in out["statusLines"]], ["Model Gate", "Plugin Boundaries"],
            msg=f"labels = {out['statusLines']}",
        )

    def test_model_gate_and_plugin_boundaries_lines(self):
        repo = self._setup_repo("model-gate-lines")
        batch = repo / ".claude" / "cfq" / "impl" / "2026-01-01-solo"
        batch.mkdir(parents=True)
        (batch / "01-a.md").touch()

        out = self.json_out(self._run_pf(str(repo)))
        gate = next(e for e in out["statusLines"] if e["label"] == "Model Gate")
        self.assertEqual(gate["icon"], "done", msg=f"gate = {gate}")
        # orchestratorMode defaults to true (test_orchestrator_policy_present_and_true_by_default)
        # -> the applicable list is orchestratorModels, not implModels.
        self.assertEqual(gate["detail"], "checked against orchestratorModels", msg=f"gate = {gate}")
        boundaries = next(e for e in out["statusLines"] if e["label"] == "Plugin Boundaries")
        self.assertEqual(boundaries["icon"], "done", msg=f"boundaries = {boundaries}")

        out = self.json_out(self._run_pf(str(repo), env={"CFQ_ALLOW_ANY_MODEL": "1"}))
        gate = next(e for e in out["statusLines"] if e["label"] == "Model Gate")
        self.assertEqual(gate["icon"], "skip", msg=f"gate = {gate}")
        self.assertEqual(gate["detail"], "skipped · allowAnyModel", msg=f"gate = {gate}")

    def test_batch_line_four_phrasings(self):
        # single selectable
        repo = self._setup_repo("batch-line-single")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-01-01-solo").mkdir(parents=True)
        (qdir / "2026-01-01-solo" / "01-a.md").touch()
        out = self.json_out(self._run_pf(str(repo)))
        entry = next(e for e in out["statusLines"] if e["label"] == "Batch")
        self.assertEqual(
            entry["detail"], "2026-01-01-solo · only open batch · 1 phases · mode=orchestrator",
            msg=f"single-selectable Batch detail = {entry}",
        )

        # multiple selectable -- order-picked default
        repo2 = self._setup_repo("batch-line-multi")
        qdir2 = repo2 / ".claude" / "cfq" / "impl"
        (qdir2 / "2026-01-01-alpha").mkdir(parents=True)
        (qdir2 / "2026-01-01-alpha" / "01-a.md").touch()
        (qdir2 / "2026-01-02-beta").mkdir(parents=True)
        (qdir2 / "2026-01-02-beta" / "01-b.md").touch()
        out2 = self.json_out(self._run_pf(str(repo2)))
        entry2 = next(e for e in out2["statusLines"] if e["label"] == "Batch")
        self.assertEqual(
            entry2["detail"], "2026-01-01-alpha · next in order · 1 phases · mode=orchestrator",
            msg=f"multiple-selectable Batch detail = {entry2}",
        )

        # --select explicit
        out3 = self.json_out(self._run_pf(str(repo2), "--select", "2026-01-02-beta"))
        entry3 = next(e for e in out3["statusLines"] if e["label"] == "Batch")
        self.assertEqual(
            entry3["detail"], "2026-01-02-beta · selected by argument · 1 phases · mode=orchestrator",
            msg=f"--select Batch detail = {entry3}",
        )

        # in-progress resume
        repo3 = self._setup_repo("batch-line-resume")
        qdir3 = repo3 / ".claude" / "cfq" / "impl"
        (qdir3 / "2026-01-01-inprog" / "done").mkdir(parents=True)
        (qdir3 / "2026-01-01-inprog" / "done" / "00-x.md").touch()
        (qdir3 / "2026-01-01-inprog" / "01-a.md").touch()
        out4 = self.json_out(self._run_pf(str(repo3)))
        entry4 = next(e for e in out4["statusLines"] if e["label"] == "Batch")
        self.assertEqual(
            entry4["detail"], "resumed 2026-01-01-inprog · 1/2 phases done · mode=orchestrator",
            msg=f"resumed Batch detail = {entry4}",
        )

    def test_queue_text_legacy_unnumbered_batch(self):
        repo = self._setup_repo("queue-legacy")
        qdir = repo / ".claude" / "cfq" / "impl"
        (qdir / "2026-01-01-legacy-slug").mkdir(parents=True)
        (qdir / "2026-01-01-legacy-slug" / "01-a.md").touch()

        out = self.json_out(self._run_pf(str(repo)))
        self.assertEqual(out["status"], "OK", msg=f"status = {out}")
        qtext = out["selection"]["queueText"]
        self.assertNotIn("None", qtext, msg=f"queueText contains a raw None: {qtext!r}")

        expected_row = text.table(
            [["2026-01-01-legacy-slug", "", "2026-01-01-legacy-slug", "ready · selected"]],
            headers=["#", "Date", "Topic", "Status"],
        )[-1]
        self.assertIn(expected_row, qtext, msg=f"legacy row = {qtext!r}")


if __name__ == "__main__":
    unittest.main()
