"""Migrated from test-brief-park.sh.

Self-test for scripts/cfq_brief.py (batch listing plus --phase announcement mode) and
scripts/cfq_park.py (batch directory creation, .priority/.dependsOn, Git exclude registration).
"""

import subprocess
import textwrap
import unittest

from cfq_testlib import CfqTestCase


class BriefTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self._repos_dir / "2026-01-01-briefme"
        self.batch.mkdir(parents=True)
        (self.batch / ".priority").write_text("high\n")
        (self.batch / ".dependsOn").write_text("2026-01-02-otherbatch\n")

        (self.batch / "01-complete.md").write_text(textwrap.dedent("""\
            # Complete phase

            ## Size

            S

            ## Context

            First context line.
            Second context line.

            ## Affected Files

            - `/tmp/example/foo.sh`
            - `/tmp/example/bar.sh`

            ## Verification

            ```bash
            bash tests/test-foo.sh
            echo done
            ```
            """))

        (self.batch / "02-incomplete.md").write_text(textwrap.dedent("""\
            # Incomplete phase

            ## Affected Files

            - `/tmp/example/only.sh`
            """))

    def test_batch_listing(self):
        out = self.run_cfq("brief", str(self.batch), check=True).stdout
        lines = out.splitlines()
        self.assertIn(
            "2026-01-01-briefme  priority=high  phases=2", lines, f"header line wrong: {out}",
        )
        self.assertIn(
            "dependsOn: 2026-01-02-otherbatch", lines, f"dependsOn line missing: {out}",
        )
        self.assertTrue(
            any(l.startswith("01  Complete phase  [S]  First context line. Second context line. ")
                for l in lines),
            f"complete phase line wrong: {out}",
        )
        self.assertTrue(
            any(l.startswith("02  Incomplete phase  [M]") for l in lines),
            f"incomplete phase should default to [M]: {out}",
        )

    def test_phase_announcement_mode(self):
        out = self.run_cfq("brief", str(self.batch), "--phase", "01", check=True).stdout.rstrip("\n")
        expected = (
            "PHASE 01 · Complete phase · Size S\n"
            "  Goal     First context line. Second context line.\n"
            "  Files    foo.sh, bar.sh\n"
            "  Check    bash tests/test-foo.sh"
        )
        self.assertEqual(out, expected, f"--phase 01 block wrong: {out}")

    def test_phase_announcement_defaults_size_and_omits_check(self):
        out = self.run_cfq("brief", str(self.batch), "--phase", "02", check=True).stdout
        lines = out.splitlines()
        self.assertIn(
            "PHASE 02 · Incomplete phase · Size M", lines, f"--phase 02 header wrong: {out}",
        )
        self.assertIn("  Files    only.sh", lines, f"--phase 02 files line wrong: {out}")
        self.assertFalse(
            any(l.startswith("  Check") for l in lines),
            f"--phase 02 should omit Check line entirely: {out}",
        )

    def test_phase_announcement_unknown_number(self):
        proc = self.run_cfq("brief", str(self.batch), "--phase", "99")
        self.assertNotEqual(proc.returncode, 0, "--phase 99 should exit non-zero")
        self.assertEqual(proc.stdout, "", f"--phase 99 should print no partial block: {proc.stdout}")
        self.assertTrue(proc.stderr, "--phase 99 should print a message on stderr")

    def test_phase_announcement_finds_phase_moved_to_done(self):
        done = self.batch / "done"
        done.mkdir()
        (self.batch / "01-complete.md").rename(done / "01-complete.md")
        out = self.run_cfq("brief", str(self.batch), "--phase", "01", check=True).stdout
        self.assertIn(
            "PHASE 01 · Complete phase · Size S", out.splitlines(),
            f"--phase should find a phase already moved to done/: {out}",
        )

    def test_with_done_flag_lists_done_then_open(self):
        batch = self._repos_dir / "2026-01-04-withdone"
        done_dir = batch / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "01-first.md").write_text("# First phase\n\n## Affected Files\n")
        (batch / "02-second.md").write_text("# Second phase\n\n## Affected Files\n")
        (batch / "03-third.md").write_text("# Third phase\n\n## Affected Files\n")

        default_out = self.run_cfq("brief", str(batch), check=True).stdout
        self.assertIn(
            "2026-01-04-withdone  phases=2", default_out.splitlines(), f"header wrong: {default_out}",
        )
        self.assertFalse(
            any(l.startswith("✔") for l in default_out.splitlines()),
            f"default output must not list done phases: {default_out}",
        )

        out = self.run_cfq("brief", str(batch), "--with-done", check=True).stdout
        lines = out.splitlines()
        self.assertIn(
            "2026-01-04-withdone  phases=2", lines, f"--with-done must still count open only: {out}",
        )
        self.assertTrue(
            any(l.startswith("✔ 01") for l in lines), f"done phase 01 missing: {out}",
        )
        done_idx = next(i for i, l in enumerate(lines) if l.startswith("✔ 01"))
        second_idx = next(i for i, l in enumerate(lines) if l.startswith("02"))
        third_idx = next(i for i, l in enumerate(lines) if l.startswith("03"))
        self.assertLess(done_idx, second_idx, "done phases must print before open phases")
        self.assertLess(second_idx, third_idx, "open phases must stay in number order")

    def test_with_done_all_done_keeps_phases_zero(self):
        batch = self._repos_dir / "2026-01-05-alldone"
        done_dir = batch / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "01-first.md").write_text("# First phase\n\n## Affected Files\n")
        (done_dir / "02-second.md").write_text("# Second phase\n\n## Affected Files\n")

        out = self.run_cfq("brief", str(batch), "--with-done", check=True).stdout
        lines = out.splitlines()
        self.assertIn("2026-01-05-alldone  phases=0", lines, f"phases=0 line wrong: {out}")
        self.assertTrue(any(l.startswith("✔ 01") for l in lines), f"done phase 01 missing: {out}")
        self.assertTrue(any(l.startswith("✔ 02") for l in lines), f"done phase 02 missing: {out}")

    def test_with_done_unknown_flag_rejected(self):
        proc = self.run_cfq("brief", str(self.batch), "--nonsense")
        self.assertNotEqual(proc.returncode, 0, "--nonsense should exit non-zero")
        self.assertEqual(proc.stdout, "", f"--nonsense should print no partial output: {proc.stdout}")
        self.assertTrue(proc.stderr, "--nonsense should print a message on stderr")

    def test_unflagged_batch_omits_priority_clause(self):
        unflagged = self._repos_dir / "2026-01-03-unflagged"
        unflagged.mkdir()
        (unflagged / "01-a.md").write_text("# A phase\n\n## Affected Files\n")
        out = self.run_cfq("brief", str(unflagged), check=True).stdout
        self.assertIn(
            "2026-01-03-unflagged  phases=1", out.splitlines(), f"unflagged header line wrong: {out}",
        )

    def test_goal_line_from_batch_context(self):
        (self.batch / ".batch-context.md").write_text(textwrap.dedent("""\
            # Batch Context

            ## Goal

            First goal line.
            Second goal line.

            ## Decisions

            - Some decision that must not leak into the brief.
            """))
        out = self.run_cfq("brief", str(self.batch), check=True).stdout
        lines = out.splitlines()
        header_idx = lines.index("2026-01-01-briefme  priority=high  phases=2")
        goal_idx = lines.index("goal: First goal line. Second goal line.")
        depends_idx = lines.index("dependsOn: 2026-01-02-otherbatch")
        self.assertEqual(goal_idx, header_idx + 1, f"goal line must directly follow header: {out}")
        self.assertLess(goal_idx, depends_idx, f"goal line must precede dependsOn: {out}")
        self.assertNotIn("Some decision", out, f"## Decisions leaked into brief output: {out}")

    def test_goal_line_cut_at_word_boundary(self):
        long_goal = " ".join(f"word{i}" for i in range(80))
        (self.batch / ".batch-context.md").write_text(f"# Batch Context\n\n## Goal\n\n{long_goal}\n")
        out = self.run_cfq("brief", str(self.batch), check=True).stdout
        goal_line = next(l for l in out.splitlines() if l.startswith("goal: "))
        goal_text = goal_line[len("goal: "):]
        self.assertLessEqual(len(goal_text), 301, f"goal line too long: {goal_line}")
        self.assertTrue(goal_text.endswith("…"), f"goal line must end in an ellipsis: {goal_line}")
        self.assertNotIn(" …", goal_text[-3:], f"cut must land on a word boundary: {goal_line}")
        self.assertTrue(long_goal.startswith(goal_text[:-1].rstrip()), f"cut text must be a prefix: {goal_line}")

    def test_no_batch_context_omits_goal_line(self):
        out = self.run_cfq("brief", str(self.batch), check=True).stdout
        self.assertFalse(
            any(l.startswith("goal:") for l in out.splitlines()), f"unexpected goal line: {out}",
        )

    def test_batch_context_without_goal_heading_omits_goal_line(self):
        (self.batch / ".batch-context.md").write_text("# Batch Context\n\n## Decisions\n\n- x\n")
        out = self.run_cfq("brief", str(self.batch), check=True).stdout
        self.assertFalse(
            any(l.startswith("goal:") for l in out.splitlines()), f"unexpected goal line: {out}",
        )

    def test_batch_context_with_empty_goal_omits_goal_line(self):
        (self.batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\n\n## Decisions\n\n- x\n")
        out = self.run_cfq("brief", str(self.batch), check=True).stdout
        self.assertFalse(
            any(l.startswith("goal:") for l in out.splitlines()), f"unexpected goal line: {out}",
        )

    def test_with_done_flag_also_prints_goal_line(self):
        (self.batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\n\nGoal text.\n")
        out = self.run_cfq("brief", str(self.batch), "--with-done", check=True).stdout
        lines = out.splitlines()
        header_idx = lines.index("2026-01-01-briefme  priority=high  phases=2")
        self.assertEqual(lines[header_idx + 1], "goal: Goal text.", f"--with-done goal line wrong: {out}")

    def test_phase_mode_omits_goal_line(self):
        (self.batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\n\nGoal text.\n")
        out = self.run_cfq("brief", str(self.batch), "--phase", "01", check=True).stdout
        self.assertFalse(
            any(l.startswith("goal:") for l in out.splitlines()), f"--phase must not print goal line: {out}",
        )


class BriefOrchestratorGateTest(CfqTestCase):
    """--phase's deterministic mode gate: bin/cfq brief --phase refuses to serve the classic-mode
    phase announcement while orchestratorMode is on for the owning repo, see
    references/orchestrator.md section 6."""

    def setUp(self):
        super().setUp()
        self.repo = self.make_repo("gaterepo")
        self.batch = self.repo / ".claude/cfq/impl/2026-01-01-gateme"
        self.batch.mkdir(parents=True)
        (self.batch / "01-first.md").write_text(textwrap.dedent("""\
            # First phase

            ## Size

            S

            ## Affected Files

            - `/tmp/example/foo.sh`
            """))

    def _set_orchestrator_mode(self, value):
        self.run_cfq(
            "settings", "set", "--repo", str(self.repo), "orchestratorMode", value,
            home=self.home, check=True,
        )

    def test_routine_case_mode_off_prints_announcement(self):
        self._set_orchestrator_mode("false")
        proc = self.run_cfq("brief", str(self.batch), "--phase", "01", home=self.home)
        self.assertEqual(proc.returncode, 0, f"mode off should exit 0: {proc.stderr}")
        self.assertIn("PHASE 01 · First phase · Size S", proc.stdout, f"announcement missing: {proc.stdout}")

    def test_blocked_case_mode_on_refuses(self):
        self._set_orchestrator_mode("true")
        proc = self.run_cfq("brief", str(self.batch), "--phase", "01", home=self.home)
        self.assertEqual(proc.returncode, 2, f"mode on should exit 2: {proc.stdout} / {proc.stderr}")
        self.assertEqual(proc.stdout, "", f"mode on should print no stdout: {proc.stdout}")
        self.assertIn("MODE_MISMATCH", proc.stderr, f"stderr missing MODE_MISMATCH: {proc.stderr}")
        self.assertIn("worker brief", proc.stderr, f"stderr missing fallback hint: {proc.stderr}")

    def test_fallback_case_classic_fallback_flag_passes_gate(self):
        self._set_orchestrator_mode("true")
        proc = self.run_cfq(
            "brief", str(self.batch), "--phase", "01", "--classic-fallback", home=self.home,
        )
        self.assertEqual(proc.returncode, 0, f"--classic-fallback should exit 0: {proc.stderr}")
        self.assertIn(
            "PHASE 01 · First phase · Size S", proc.stdout, f"announcement missing: {proc.stdout}",
        )

    def test_unaffected_case_batch_mode_ignores_gate(self):
        self._set_orchestrator_mode("true")
        proc = self.run_cfq("brief", str(self.batch), home=self.home)
        self.assertEqual(proc.returncode, 0, f"batch mode should ignore the gate: {proc.stderr}")
        proc_with_done = self.run_cfq("brief", str(self.batch), "--with-done", home=self.home)
        self.assertEqual(
            proc_with_done.returncode, 0, f"--with-done should ignore the gate: {proc_with_done.stderr}",
        )

    def test_edge_case_batch_dir_outside_queue_layout_has_no_gate(self):
        self._set_orchestrator_mode("true")
        stray = self._repos_dir / "not-under-a-queue"
        stray.mkdir()
        (stray / "01-first.md").write_text("# First phase\n\n## Affected Files\n")
        proc = self.run_cfq("brief", str(stray), "--phase", "01", home=self.home)
        self.assertEqual(
            proc.returncode, 0, f"unresolvable repo root must never gate: {proc.stderr}",
        )
        self.assertIn("PHASE 01 · First phase", proc.stdout, f"announcement missing: {proc.stdout}")


class ParkTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.park_home = self._repos_dir / "parkhome"
        self.park_home.mkdir()
        self.parkrepo = self.make_repo("parkrepo")

    def _park(self, batch, priority, *depends_on):
        return self.run_cfq(
            "park", str(self.parkrepo), batch, priority, *depends_on, home=self.park_home,
        ).stdout.strip()

    def test_park_creates_priority_and_depends_on(self):
        d1 = self._park("2026-01-01-test", "high", "2026-01-01-dep-a", "2026-01-01-dep-b")
        batchdir = self.parkrepo / ".claude/cfq/impl/2026-01-01-test"
        self.assertEqual(d1, str(batchdir), f"printed dir wrong: {d1}")
        self.assertEqual((batchdir / ".priority").read_text().strip(), "high", "\".priority\" wrong")
        self.assertEqual(
            (batchdir / ".dependsOn").read_text().strip(),
            "2026-01-01-dep-a\n2026-01-01-dep-b",
            f"\".dependsOn\" wrong: {(batchdir / '.dependsOn').read_text()}",
        )
        exclude = (self.parkrepo / ".git/info/exclude").read_text()
        self.assertIn(".claude/cfq/impl/\n", exclude, "git exclude entry missing")
        repos_json = (self.park_home / ".claude/code-for-queue/repos.json").read_text()
        self.assertIn(str(self.parkrepo), repos_json, "repo not registered")

        # no dependsOn entries -> no file; normal priority -> no .priority file either
        self._park("2026-01-02-nodeps", "normal")
        self.assertFalse(
            (self.parkrepo / ".claude/cfq/impl/2026-01-02-nodeps/.dependsOn").exists(),
            ".dependsOn should not exist when no entries were passed",
        )
        self.assertFalse(
            (self.parkrepo / ".claude/cfq/impl/2026-01-02-nodeps/.priority").exists(),
            ".priority should not exist for normal priority",
        )

        # re-park an existing high batch as normal: .priority must be removed, not left stale
        d1normal = self._park("2026-01-01-test", "normal")
        self.assertEqual(d1, d1normal, "re-park printed a different dir")
        self.assertFalse(
            (batchdir / ".priority").exists(), "re-park to normal should remove .priority",
        )

        # re-run with the same arguments: idempotent, no duplicate exclude line
        before = (self.parkrepo / ".git/info/exclude").read_text()
        d1again = self._park("2026-01-01-test", "high", "2026-01-01-dep-a", "2026-01-01-dep-b")
        after = (self.parkrepo / ".git/info/exclude").read_text()
        self.assertEqual(d1, d1again, "second run printed a different dir")
        self.assertEqual(before, after, "second run duplicated the exclude entry")
        self.assertEqual(
            after.count("# BEGIN cfq-managed"), 1, "exclude block not exactly once",
        )

    def test_park_invalid_priority_rejected(self):
        proc = self.run_cfq(
            "park", str(self.parkrepo), "2026-01-03-bad", "nope", home=self.park_home,
        )
        self.assertNotEqual(proc.returncode, 0, "invalid priority should exit non-zero")


if __name__ == "__main__":
    unittest.main()
