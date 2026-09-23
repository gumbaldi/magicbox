"""Migrated from test-brief-park.sh.

Self-test for scripts/cfq_brief.py (batch listing plus --phase announcement mode) and
scripts/cfq_park.py (batch directory creation, .priority/.dependsOn, Git exclude registration).
"""

import json
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


class BriefOverviewTest(CfqTestCase):
    """`bin/cfq brief <batch-dir> --overview` -- the shared batch-overview block `ifq`'s start
    gate (phase 04) and `pfq`'s final report (phase 05) both render, see
    .claude/cfq/impl/035-.../02-batch-overview-block.md."""

    def _phase(self, batch, filename, title, size=None):
        body = f"# {title}\n"
        if size is not None:
            body += f"\n## Size\n\n{size}\n"
        body += "\n## Affected Files\n"
        (batch / filename).write_text(body)

    def test_overview_mixed_batch_counts_done_red_and_open(self):
        batch = self._repos_dir / "007-2026-02-01-overview"
        done_dir = batch / "done"
        done_dir.mkdir(parents=True)
        self._phase(batch, "done/01-first.md", "First phase", "S")
        self._phase(batch, "02-second.md", "Second phase", "M")
        self._phase(batch, "03-third.md", "Third phase", "L")
        (batch / "report.json").write_text(json.dumps({
            "phases": [{"phase": "02-second", "status": "red"}],
        }))

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 007 · 2026-02-01 · overview",
            "3 phases planned · 1 done · 1 red",
            "  #   Phase         Size  Status",
            "  01  First phase   S     done",
            "  02  Second phase  M     red",
            "  03  Third phase   L     open",
        ])
        self.assertEqual(out, expected, f"mixed overview block wrong: {out}")

    def test_overview_all_open_no_report_json_omits_red_clause(self):
        batch = self._repos_dir / "008-2026-02-02-noreport"
        batch.mkdir(parents=True)
        self._phase(batch, "01-alpha.md", "Alpha phase")
        self._phase(batch, "02-beta.md", "Beta phase", "S")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 008 · 2026-02-02 · noreport",
            "2 phases planned · 0 done",
            "  #   Phase        Size  Status",
            "  01  Alpha phase  M     open",
            "  02  Beta phase   S     open",
        ])
        self.assertEqual(
            out, expected,
            f"no-report.json overview block wrong (must not raise, must omit red clause): {out}",
        )

    def test_overview_missing_batch_context_omits_goal_paragraph(self):
        batch = self._repos_dir / "009-2026-02-03-nogoal"
        batch.mkdir(parents=True)
        self._phase(batch, "01-only.md", "Only phase")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        lines = out.splitlines()
        self.assertEqual(lines[0], "BATCH 009 · 2026-02-03 · nogoal", f"header wrong: {out}")
        self.assertEqual(lines[1], "1 phases planned · 0 done", f"count line wrong: {out}")
        self.assertEqual(
            lines[2], "  #   Phase       Size  Status",
            f"table must start right after the count line, no goal paragraph or blank lines: {out}",
        )

    def test_overview_long_goal_wraps_to_six_lines_with_ellipsis(self):
        batch = self._repos_dir / "010-2026-02-04-longgoal"
        batch.mkdir(parents=True)
        self._phase(batch, "01-x.md", "X phase")
        long_goal = " ".join(f"word{i}" for i in range(80))
        (batch / ".batch-context.md").write_text(
            f"# Batch Context\n\n## Goal\n\n{long_goal}\n\n## Decisions\n\n- irrelevant\n"
        )

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 010 · 2026-02-04 · longgoal",
            "1 phases planned · 0 done",
            "",
            "  word0 word1 word2 word3 word4 word5 word6 word7 word8 word9 word10",
            "  word11 word12 word13 word14 word15 word16 word17 word18 word19",
            "  word20 word21 word22 word23 word24 word25 word26 word27 word28",
            "  word29 word30 word31 word32 word33 word34 word35 word36 word37",
            "  word38 word39 word40 word41 word42 word43 word44 word45 word46",
            "  word47 word48 word49 word50 word51 word52 word53 word54 word55…",
            "",
            "  #   Phase    Size  Status",
            "  01  X phase  M     open",
        ])
        self.assertEqual(out, expected, f"long-goal overview block wrong: {out}")
        self.assertNotIn(
            "## Decisions", out, f"## Decisions must not leak into the overview block: {out}",
        )

    def test_overview_legacy_unnumbered_batch_name(self):
        batch = self._repos_dir / "2026-01-06-legacyoverview"
        batch.mkdir(parents=True)
        self._phase(batch, "01-y.md", "Y phase")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 2026-01-06-legacyoverview",
            "1 phases planned · 0 done",
            "  #   Phase    Size  Status",
            "  01  Y phase  M     open",
        ])
        self.assertEqual(out, expected, f"legacy unnumbered overview block wrong: {out}")
        self.assertNotIn("None", out, f"legacy header must never print 'None': {out}")

    def test_overview_red_then_green_ledger_entry_never_shows_red(self):
        batch = self._repos_dir / "011-2026-02-05-redthengreen"
        batch.mkdir(parents=True)
        self._phase(batch, "04-x.md", "X phase")
        (batch / "report.json").write_text(json.dumps({
            "phases": [
                {"phase": "04-x", "status": "red"},
                {"phase": "04-x", "status": "green"},
            ],
        }))

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 011 · 2026-02-05 · redthengreen",
            "1 phases planned · 0 done",
            "  #   Phase    Size  Status",
            "  04  X phase  M     open",
        ])
        self.assertEqual(
            out, expected,
            f"a phase whose latest ledger entry is green must never render as red: {out}",
        )

    def test_overview_and_with_done_are_mutually_exclusive(self):
        batch = self._repos_dir / "012-2026-02-06-mutex"
        batch.mkdir(parents=True)
        self._phase(batch, "01-a.md", "A phase")

        proc = self.run_cfq("brief", str(batch), "--overview", "--with-done")
        self.assertNotEqual(proc.returncode, 0, "--overview and --with-done together should exit non-zero")


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
        repos_json = (self.park_home / ".claude/cfq/repos.json").read_text()
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


class ParkFromPlanTest(CfqTestCase):
    """`park ... --from-plan <path>` consumes the plan-inbox entry `cfq note list` showed --
    see phase 05's .batch-context.md and
    .claude/cfq/impl/.../05-plan-inbox-list-and-consume.md."""

    def setUp(self):
        super().setUp()
        self.park_home = self._repos_dir / "parkhome-fromplan"
        self.park_home.mkdir()
        self.parkrepo = self.make_repo("parkrepo-fromplan")
        self.plan_dir = self.parkrepo / ".claude" / "cfq" / "plan"
        self.plan_dir.mkdir(parents=True)
        self.entry = self.plan_dir / "2026-01-01-finding.md"
        self.entry.write_text("# Finding\n\nsomething\n")

    def _park(self, batch, from_plan=None, priority="normal"):
        args = ["park", str(self.parkrepo), batch, priority]
        if from_plan is not None:
            entries = from_plan if isinstance(from_plan, (list, tuple)) else [from_plan]
            for entry in entries:
                args += ["--from-plan", str(entry)]
        return self.run_cfq(*args, home=self.park_home)

    def test_normal_move_into_plan_done(self):
        proc = self._park("2026-02-01-batch", from_plan=self.entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        moved = self.plan_dir / "done" / self.entry.name
        self.assertTrue(moved.is_file(), "entry should have moved into plan/done/")
        self.assertFalse(self.entry.exists(), "entry should no longer be at its original path")
        self.assertEqual(moved.read_text(), "# Finding\n\nsomething\n")

    def test_rerun_of_the_same_call_is_a_noop(self):
        self._park("2026-02-01-batch", from_plan=self.entry)
        moved = self.plan_dir / "done" / self.entry.name
        before = moved.read_text()

        proc = self._park("2026-02-01-batch", from_plan=self.entry)
        self.assertEqual(proc.returncode, 0, f"re-run must be a no-op, not an error: {proc.stderr}")
        self.assertEqual(moved.read_text(), before, "already-consumed entry must stay unchanged")

    def test_path_outside_plan_dir_is_rejected(self):
        outside = self._repos_dir / "outside.md"
        outside.write_text("not a plan entry\n")

        proc = self._park("2026-02-02-batch", from_plan=outside)
        self.assertNotEqual(proc.returncode, 0, "a path outside plan/ must be rejected")
        self.assertTrue(outside.exists(), "the outside file must be left untouched")
        self.assertFalse(
            (self.plan_dir / "done").exists(), "nothing should be moved on a rejected path",
        )

    def test_missing_plan_done_dir_is_created(self):
        done_dir = self.plan_dir / "done"
        self.assertFalse(done_dir.exists())
        proc = self._park("2026-02-03-batch", from_plan=self.entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(done_dir.is_dir())

    def test_name_collision_in_plan_done_is_an_error(self):
        done_dir = self.plan_dir / "done"
        done_dir.mkdir(parents=True)
        collision = done_dir / self.entry.name
        collision.write_text("already parked\n")

        proc = self._park("2026-02-04-batch", from_plan=self.entry)
        self.assertNotEqual(proc.returncode, 0, "a name collision in plan/done/ must be an error")
        self.assertIn(str(self.entry), proc.stderr, f"source path missing from error: {proc.stderr}")
        self.assertIn(str(collision), proc.stderr, f"target path missing from error: {proc.stderr}")
        self.assertTrue(self.entry.exists(), "source must be left in place on collision")
        self.assertEqual(
            collision.read_text(), "already parked\n", "existing plan/done/ entry must not be overwritten",
        )

    def test_park_without_the_flag_is_unaffected(self):
        proc = self._park("2026-02-05-batch")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.plan_dir / "done").exists(), "no --from-plan means no move at all")
        self.assertTrue(self.entry.exists(), "the plan entry must be left untouched")

    def test_repeatable_flag_moves_every_valid_entry(self):
        second = self.plan_dir / "2026-01-02-second-finding.md"
        second.write_text("# Second finding\n\nsomething else\n")

        proc = self._park("2026-02-06-batch", from_plan=[self.entry, second])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        done = self.plan_dir / "done"
        self.assertTrue((done / self.entry.name).is_file(), "first entry should have moved")
        self.assertTrue((done / second.name).is_file(), "second entry should have moved")
        self.assertFalse(self.entry.exists(), "first entry should no longer be at its original path")
        self.assertFalse(second.exists(), "second entry should no longer be at its original path")

    def test_one_invalid_path_among_several_moves_nothing(self):
        outside = self._repos_dir / "outside-multi.md"
        outside.write_text("not a plan entry\n")

        proc = self._park("2026-02-07-batch", from_plan=[self.entry, outside])
        self.assertNotEqual(proc.returncode, 0, "an invalid path among several must be rejected")
        self.assertTrue(self.entry.exists(), "the valid entry must be left in place, not moved")
        self.assertTrue(outside.exists(), "the outside file must be left untouched")
        self.assertFalse(
            (self.plan_dir / "done").exists(),
            "nothing should be moved when any one of the paths is invalid",
        )

    def test_retried_park_with_entries_already_in_plan_done_is_a_noop(self):
        second = self.plan_dir / "2026-01-03-third-finding.md"
        second.write_text("# Third finding\n\nsomething else again\n")

        self._park("2026-02-08-batch", from_plan=[self.entry, second])
        done = self.plan_dir / "done"
        first_before = (done / self.entry.name).read_text()
        second_before = (done / second.name).read_text()

        proc = self._park("2026-02-08-batch", from_plan=[self.entry, second])
        self.assertEqual(proc.returncode, 0, f"retried park must be a no-op, not an error: {proc.stderr}")
        self.assertEqual((done / self.entry.name).read_text(), first_before, "first entry must stay unchanged")
        self.assertEqual((done / second.name).read_text(), second_before, "second entry must stay unchanged")


if __name__ == "__main__":
    unittest.main()
