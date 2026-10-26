"""Migrated from test-brief-park.sh.

Self-test for scripts/cfq_brief.py (batch listing plus --phase announcement mode) and
scripts/cfq_park.py (batch directory creation, .priority/.dependsOn, Git exclude registration).
"""

import json
import subprocess
import textwrap
import unittest

from cfq_testlib import CfqTestCase, PhaseDirsStatus, write_status

from cfq_brief import parse_phase_body  # noqa: E402


class BriefTest(PhaseDirsStatus, CfqTestCase):
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

    def test_phase_announcement_wraps_long_goal_across_lines(self):
        batch = self._repos_dir / "2026-01-05-longgoal"
        batch.mkdir(parents=True)
        long_context = " ".join(f"word{i:03d}" for i in range(60))
        (batch / "01-longcontext.md").write_text(
            "# Long context phase\n\n## Context\n\n" + long_context + "\n\n"
            "## Affected Files\n\n- `/tmp/example/only.sh`\n"
        )
        out = self.run_cfq("brief", str(batch), "--phase", "01", check=True).stdout
        lines = out.splitlines()
        self.assertFalse(any(l.endswith(" ") for l in lines), f"trailing whitespace in: {out}")
        goal_lines = [l for l in lines if l.startswith("  Goal     ") or l.startswith(" " * 11)]
        self.assertGreater(len(goal_lines), 1, f"long context should wrap to several lines: {out}")
        self.assertLessEqual(len(goal_lines), 4, f"Goal block must not exceed 4 lines: {out}")
        self.assertTrue(goal_lines[0].startswith("  Goal     "), f"first Goal line missing prefix: {out}")
        for continuation in goal_lines[1:]:
            self.assertTrue(
                continuation.startswith(" " * 11) and not continuation.startswith("  Goal"),
                f"continuation line must be indented, not re-labelled: {out}",
            )
        self.assertTrue(goal_lines[-1].endswith("…"), f"truncated Goal block must end in an ellipsis: {out}")

    def test_phase_announcement_no_context_omits_goal_line(self):
        out = self.run_cfq("brief", str(self.batch), "--phase", "02", check=True).stdout
        lines = out.splitlines()
        self.assertFalse(
            any(l.startswith("  Goal") for l in lines),
            f"--phase 02 has no ## Context, Goal line must be omitted entirely: {out}",
        )
        self.assertFalse(any(l.endswith(" ") for l in lines), f"trailing whitespace in: {out}")

    def _steps_phase(self, name, changes):
        batch = self._repos_dir / name
        batch.mkdir(parents=True)
        (batch / "01-steps.md").write_text(
            "# Steps phase\n\n## Context\n\nCtx line.\n\n"
            "## Affected Files\n\n- `/tmp/example/only.sh`\n\n"
            f"## Changes\n\n{changes}\n\n"
            "## Verification\n\n```bash\necho done\n```\n"
        )
        return batch

    def test_phase_announcement_prints_steps_between_files_and_check(self):
        batch = self._steps_phase(
            "2026-01-07-threesteps",
            "1. First step.\n   - nested detail\n2. Second step.\n3. Third step.",
        )
        out = self.run_cfq("brief", str(batch), "--phase", "01", check=True).stdout.rstrip("\n")
        expected = (
            "PHASE 01 · Steps phase · Size M\n"
            "  Goal     Ctx line.\n"
            "  Files    only.sh\n"
            "  Steps    1. First step.\n"
            "           2. Second step.\n"
            "           3. Third step.\n"
            "  Check    echo done"
        )
        self.assertEqual(out, expected)

    def test_phase_announcement_caps_steps_at_ten(self):
        batch = self._steps_phase(
            "2026-01-08-twelvesteps", "\n".join(f"{i}. Step number {i}." for i in range(1, 13)),
        )
        lines = self.run_cfq("brief", str(batch), "--phase", "01", check=True).stdout.splitlines()
        steps = [l for l in lines if l.startswith("  Steps") or l.startswith(" " * 11)]
        self.assertEqual(len(steps), 11, lines)
        self.assertEqual(steps[-1], "           … +2 more steps")
        self.assertEqual(steps[-2], "           10. Step number 10.")
        self.assertFalse(any(l.endswith(" ") for l in lines))

    def test_phase_announcement_without_step_list_has_no_steps_label(self):
        batch = self._steps_phase("2026-01-09-prosechanges", "Just prose describing the change.")
        out = self.run_cfq("brief", str(batch), "--phase", "01", check=True).stdout
        self.assertNotIn("  Steps  ", out)

    def test_phase_announcement_long_step_lead_ends_in_ellipsis(self):
        long_lead = " ".join(f"word{i:03d}" for i in range(40))
        batch = self._steps_phase("2026-01-10-longstep", f"1. {long_lead}\n2. Short.")
        lines = self.run_cfq("brief", str(batch), "--phase", "01", check=True).stdout.splitlines()
        idx = next(i for i, l in enumerate(lines) if l.startswith("  Steps    1. "))
        self.assertTrue(lines[idx + 1].startswith(" " * 14), lines)
        self.assertTrue(lines[idx + 1].endswith("…"), lines)
        self.assertEqual(lines[idx + 2], "           2. Short.")
        self.assertFalse(any(l.endswith(" ") for l in lines))

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

    def test_phase_announcement_finds_phase_moved_to_skipped(self):
        write_status(self.batch, **{"01_complete": "skipped"})
        out = self.run_cfq("brief", str(self.batch), "--phase", "01", check=True).stdout
        self.assertIn(
            "PHASE 01 · Complete phase · Size S", out.splitlines(),
            f"--phase should find a phase lying in skipped/: {out}",
        )

    def test_default_brief_counts_open_and_error_phases_only(self):
        batch = self._repos_dir / "2026-01-05-states"
        batch.mkdir(parents=True)
        for n, name in (("01", "a"), ("02", "b"), ("03", "c"), ("04", "d")):
            (batch / f"{n}-{name}.md").write_text(f"# Phase {name}\n\n## Affected Files\n")
        write_status(batch, **{"01_a": "done", "02_b": "skipped", "03_c": "error"})

        out = self.run_cfq("brief", str(batch), check=True).stdout
        self.assertIn("2026-01-05-states  phases=2", out.splitlines(), f"header wrong: {out}")
        self.assertEqual(
            [l[:2] for l in out.splitlines()[1:] if l[:2].isdigit()], ["03", "04"], f"rows wrong: {out}",
        )

    def test_with_done_marks_skipped_phases_differently_from_done_ones(self):
        batch = self._repos_dir / "2026-01-06-markers"
        batch.mkdir(parents=True)
        for n, name in (("01", "a"), ("02", "b"), ("03", "c")):
            (batch / f"{n}-{name}.md").write_text(f"# Phase {name}\n\n## Affected Files\n")
        write_status(batch, **{"01_a": "done", "02_b": "skipped"})

        lines = self.run_cfq("brief", str(batch), "--with-done", check=True).stdout.splitlines()
        self.assertIn("2026-01-06-markers  phases=1", lines, f"header wrong: {lines}")
        self.assertTrue(any(l.startswith("✔ 01") for l in lines), f"done marker missing: {lines}")
        self.assertTrue(any(l.startswith("➖ 02") for l in lines), f"skipped marker missing: {lines}")
        self.assertTrue(any(l.startswith("03") for l in lines), f"open row missing: {lines}")
        self.assertFalse(any(l.startswith("✔ 02") for l in lines), f"skipped shown as done: {lines}")

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


class BriefOrchestratorGateTest(PhaseDirsStatus, CfqTestCase):
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


class BriefUntitledPhaseTest(PhaseDirsStatus, CfqTestCase):
    """A phase file without a `# ` heading no longer crashes `parse_phase_body` -- the title falls
    back to the file's own stem (`NN-slug`) everywhere brief renders it, see
    .claude/cfq/impl/044-.../05-phase-title-fallback-and-lint.md."""
    def setUp(self):
        super().setUp()
        self.batch = self._repos_dir / "2026-01-08-untitled"
        self.batch.mkdir(parents=True)
        (self.batch / "01-normal-step.md").write_text(textwrap.dedent("""\
            # Normal step

            ## Size

            S

            ## Affected Files

            - `/tmp/example/foo.sh`
            """))
        (self.batch / "02-untitled-step.md").write_text(textwrap.dedent("""\
            ## Size

            M

            ## Affected Files

            - `/tmp/example/bar.sh`
            """))

    def test_overview_shows_stem_for_untitled_phase(self):
        out = self.run_cfq("brief", str(self.batch), "--overview", check=True).stdout
        self.assertIn("02-untitled-step", out, f"overview row for 02 must show the stem fallback: {out}")
        self.assertNotIn("None", out, f"overview must never print the literal None: {out}")

    def test_with_done_shows_stem_never_none(self):
        out = self.run_cfq("brief", str(self.batch), "--with-done", check=True).stdout
        self.assertIn("02-untitled-step", out, f"brief listing must show the stem fallback: {out}")
        self.assertNotIn("None", out, f"brief listing must never print the literal None: {out}")

    def test_phase_announcement_shows_stem_fallback(self):
        out = self.run_cfq(
            "brief", str(self.batch), "--phase", "02", "--classic-fallback", check=True,
        ).stdout
        self.assertIn(
            "PHASE 02 · 02-untitled-step", out, f"--phase announcement must show the stem fallback: {out}",
        )

    def test_normal_phase_title_regression(self):
        out = self.run_cfq(
            "brief", str(self.batch), "--phase", "01", "--classic-fallback", check=True,
        ).stdout
        self.assertIn(
            "PHASE 01 · Normal step", out, f"normal phase's own `# ` title regressed: {out}",
        )


class BriefOverviewTest(PhaseDirsStatus, CfqTestCase):
    """`bin/cfq brief <batch-dir> --overview` -- the shared batch-overview block `ifq`'s start
    gate (phase 04) and `pfq`'s final report (phase 05) both render, see
    .claude/cfq/impl/035-.../02-batch-overview-block.md."""
    def _phase(self, batch, filename, title, size=None):
        body = f"# {title}\n"
        if size is not None:
            body += f"\n## Size\n\n{size}\n"
        body += "\n## Affected Files\n"
        (batch / filename).write_text(body)

    def test_overview_mixed_batch_counts_done_error_and_open(self):
        batch = self._repos_dir / "007-2026-02-01-overview"
        done_dir = batch / "done"
        done_dir.mkdir(parents=True)
        self._phase(batch, "done/01-first.md", "First phase", "S")
        self._phase(batch, "02-second.md", "Second phase", "M")
        self._phase(batch, "03-third.md", "Third phase", "L")
        write_status(batch, **{"02_second": "error"})

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 007 · 2026-02-01 · overview",
            "3 phases planned · 1 done · 1 error",
            "  #   Phase         Size  Status",
            "  01  First phase   S     done",
            "      → done/01-first.md",
            "  02  Second phase  M     error",
            "      → 02-second.md",
            "  03  Third phase   L     open",
            "      → 03-third.md",
            "",
            f"  Plans    {batch.resolve()}",
        ])
        self.assertEqual(out, expected, f"mixed overview block wrong: {out}")

    def test_overview_shows_every_state_and_names_error_and_skipped_counts(self):
        batch = self._repos_dir / "008-2026-02-02-states"
        batch.mkdir(parents=True)
        for name, title in (("01-a", "A"), ("02-b", "B"), ("03-c", "C"), ("04-d", "D")):
            self._phase(batch, f"{name}.md", f"Phase {title}", "S")
        write_status(batch, **{
            "01_a": "done", "02_b": {"status": "skipped", "reason": "obsolete"}, "03_c": "error",
        })

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 008 · 2026-02-02 · states",
            "4 phases planned · 1 done · 1 error · 1 skipped",
            "  #   Phase    Size  Status",
            "  01  Phase A  S     done",
            "      → done/01-a.md",
            "  02  Phase B  S     skipped",
            "      → skipped/02-b.md",
            "  03  Phase C  S     error",
            "      → 03-c.md",
            "  04  Phase D  S     open",
            "      → 04-d.md",
            "",
            f"  Plans    {batch.resolve()}",
        ])
        self.assertEqual(out, expected, f"every-state overview block wrong: {out}")

    def test_overview_without_status_file_fails(self):
        self.auto_status = False
        batch = self._repos_dir / "009-2026-02-03-nostatus"
        batch.mkdir(parents=True)
        self._phase(batch, "01-a.md", "A", "S")

        proc = self.run_cfq("brief", str(batch), "--overview")
        self.assertEqual(proc.returncode, 1, msg=f"stderr = {proc.stderr!r}")
        self.assertIn("status.json", proc.stderr, msg=f"stderr = {proc.stderr!r}")

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
            "      → 01-alpha.md",
            "  02  Beta phase   S     open",
            "      → 02-beta.md",
            "",
            f"  Plans    {batch.resolve()}",
        ])
        self.assertEqual(
            out, expected,
            f"no-report.json overview block wrong (must not raise, must omit red clause): {out}",
        )

    def test_overview_missing_batch_context_omits_context_block(self):
        batch = self._repos_dir / "009-2026-02-03-nogoal"
        batch.mkdir(parents=True)
        self._phase(batch, "01-only.md", "Only phase")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        lines = out.splitlines()
        self.assertEqual(lines[0], "BATCH 009 · 2026-02-03 · nogoal", f"header wrong: {out}")
        self.assertEqual(lines[1], "1 phases planned · 0 done", f"count line wrong: {out}")
        self.assertEqual(
            lines[2], "  #   Phase       Size  Status",
            f"table must start right after the count line, no context block or blank lines: {out}",
        )
        self.assertEqual(lines[4], "      → 01-only.md", f"pointer line missing: {out}")

    def test_overview_long_goal_is_never_cut(self):
        batch = self._repos_dir / "010-2026-02-04-longgoal"
        batch.mkdir(parents=True)
        self._phase(batch, "01-x.md", "X phase")
        long_goal = " ".join(f"word{i}" for i in range(80))
        (batch / ".batch-context.md").write_text(
            f"# Batch Context\n\n## Goal\n\n{long_goal}\n\n## Decisions\n\n- irrelevant\n"
        )

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        self.assertNotIn("…", out, f"the goal must not be cut: {out}")
        self.assertIn("word79", out, f"the last goal word must survive: {out}")
        lines = out.splitlines()
        self.assertEqual(lines[2], "", f"blank line before the context block: {out}")
        self.assertEqual(lines[3], "  Goal", f"labelled Goal block expected: {out}")
        self.assertIn("  Decisions", lines)
        self.assertIn("    - irrelevant", lines)
        table_idx = lines.index("  #   Phase    Size  Status")
        self.assertEqual(lines[table_idx - 1], "", f"blank line after the context block: {out}")

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
            "      → 01-y.md",
            "",
            f"  Plans    {batch.resolve()}",
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
            "      → 04-x.md",
            "",
            f"  Plans    {batch.resolve()}",
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


class BriefOverviewDecisionsAndPathTest(PhaseDirsStatus, CfqTestCase):
    """`--overview`'s three additions: `.batch-context.md`'s `## Decisions`, each phase's own `##
    Context` excerpt under its table row, and a closing `Plans` line naming the batch directory --
    see .claude/cfq/impl/044-.../08-overview-with-decisions-summaries-path.md."""
    def _phase(self, batch, filename, title, size=None, context_lines=None):
        body = f"# {title}\n"
        if size is not None:
            body += f"\n## Size\n\n{size}\n"
        if context_lines is not None:
            body += "\n## Context\n\n" + "\n".join(context_lines) + "\n"
        body += "\n## Affected Files\n"
        (batch / filename).write_text(body)

    def test_routine_decisions_context_excerpts_and_plans_path(self):
        batch = self._repos_dir / "013-2026-02-07-decisions"
        batch.mkdir(parents=True)
        (batch / ".batch-context.md").write_text(
            "# Batch Context\n\n"
            "## Goal\n\nDo the thing well.\n\n"
            "## Decisions\n\n"
            "- First decision bullet about something.\n"
            "- Second decision bullet about something else.\n"
        )
        self._phase(
            batch, "01-first.md", "First phase", "S",
            context_lines=["First phase context line one.", "First phase context line two."],
        )
        self._phase(
            batch, "02-second.md", "Second phase", "M",
            context_lines=["Second phase context line one.", "Second phase context line two."],
        )

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 013 · 2026-02-07 · decisions",
            "2 phases planned · 0 done",
            "",
            "  Goal",
            "    Do the thing well.",
            "  Decisions",
            "    - First decision bullet about something.",
            "    - Second decision bullet about something else.",
            "",
            "  #   Phase         Size  Status",
            "  01  First phase   S     open",
            "      First phase context line one. First phase context line two.",
            "      → 01-first.md",
            "  02  Second phase  M     open",
            "      Second phase context line one. Second phase context line two.",
            "      → 02-second.md",
            "",
            f"  Plans    {batch.resolve()}",
        ])
        self.assertEqual(out, expected, f"routine decisions/excerpts/path overview block wrong: {out}")
        self.assertNotIn("Portal", out, f"a batch outside a queue layout has no portal line: {out}")
        self.assertFalse(
            any(l.endswith(" ") for l in out.splitlines()),
            f"no overview line may end in a space: {out!r}",
        )

    def test_no_decisions_section_omits_decisions_label(self):
        batch = self._repos_dir / "014-2026-02-08-nodecisions"
        batch.mkdir(parents=True)
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\n\nJust a goal.\n")
        self._phase(batch, "01-first.md", "First phase")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 014 · 2026-02-08 · nodecisions",
            "1 phases planned · 0 done",
            "",
            "  Goal",
            "    Just a goal.",
            "",
            "  #   Phase        Size  Status",
            "  01  First phase  M     open",
            "      → 01-first.md",
            "",
            f"  Plans    {batch.resolve()}",
        ])
        self.assertEqual(out, expected, f"no-Decisions overview block wrong: {out}")

    def test_phase_without_context_omits_excerpt_line_not_blank(self):
        batch = self._repos_dir / "015-2026-02-09-nocontext"
        batch.mkdir(parents=True)
        self._phase(batch, "01-first.md", "First phase", "S")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        expected = "\n".join([
            "BATCH 015 · 2026-02-09 · nocontext",
            "1 phases planned · 0 done",
            "  #   Phase        Size  Status",
            "  01  First phase  S     open",
            "      → 01-first.md",
            "",
            f"  Plans    {batch.resolve()}",
        ])
        self.assertEqual(
            out, expected,
            f"a phase without ## Context must have no excerpt line and no stray blank line: {out}",
        )

    def test_twenty_decision_bullets_are_never_cut(self):
        batch = self._repos_dir / "016-2026-02-10-longdecisions"
        batch.mkdir(parents=True)
        long_decisions = "\n".join(f"- decisionword{i} decisionword{i}" for i in range(20))
        (batch / ".batch-context.md").write_text(f"# Batch Context\n\n## Decisions\n\n{long_decisions}\n")
        self._phase(batch, "01-first.md", "First phase")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        lines = out.splitlines()
        self.assertEqual(
            len([l for l in lines if l.startswith("    - ")]), 20,
            f"20 decision bullets must produce 20 bullet lines: {out}",
        )
        self.assertFalse(any(l.endswith("…") for l in lines), f"no line may be cut: {out}")
        self.assertFalse(
            any(l.endswith(" ") for l in lines),
            f"no overview line may end in a space: {out!r}",
        )

    def test_batch_in_queue_layout_ends_with_portal_line_unless_html_report_off(self):
        repo = self._repos_dir / "portalrepo"
        batch = repo / ".claude" / "cfq" / "impl" / "018-2026-02-12-portal"
        batch.mkdir(parents=True)
        self._phase(batch, "01-first.md", "First phase")

        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout.rstrip("\n")
        lines = out.splitlines()
        self.assertEqual(lines[-2], f"  Plans    {batch.resolve()}", out)
        self.assertEqual(
            lines[-1],
            f"  Portal   file://{repo}/.claude/cfq/reports/index.html#/batch/018-2026-02-12-portal",
            out,
        )

        (repo / ".claude" / "cfq" / "settings.json").write_text('{"htmlReport": false}\n')
        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout
        self.assertNotIn("Portal", out)
        self.assertIn("  Plans    ", out)

    def test_with_done_and_phase_modes_unaffected_by_decisions_and_context(self):
        batch = self._repos_dir / "017-2026-02-11-unaffected"
        done_dir = batch / "done"
        done_dir.mkdir(parents=True)
        (batch / ".batch-context.md").write_text(
            "# Batch Context\n\n## Goal\n\nGoal text.\n\n## Decisions\n\n- Some decision.\n"
        )
        self._phase(batch, "done/01-first.md", "First phase", context_lines=["Context line."])
        self._phase(batch, "02-second.md", "Second phase", context_lines=["Context line."])

        with_done_out = self.run_cfq("brief", str(batch), "--with-done", check=True).stdout
        self.assertNotIn("Decisions", with_done_out, f"--with-done must not gain the Decisions block: {with_done_out}")
        self.assertNotIn("Plans", with_done_out, f"--with-done must not gain the Plans line: {with_done_out}")

        phase_out = self.run_cfq(
            "brief", str(batch), "--phase", "02", "--classic-fallback", check=True,
        ).stdout
        self.assertNotIn("Decisions", phase_out, f"--phase must not gain the Decisions block: {phase_out}")
        self.assertNotIn("Plans", phase_out, f"--phase must not gain the Plans line: {phase_out}")


class BriefReviewTest(PhaseDirsStatus, CfqTestCase):
    """`bin/cfq brief <batch-dir> --review [--phases NN,...]` -- the Plan-Mode digest, see
    .claude/cfq/impl/049-.../01-review-digest-renderer.md."""
    def _review_batch(self, name):
        repo = self._repos_dir / "revrepo"
        batch = repo / ".claude" / "cfq" / "impl" / name
        batch.mkdir(parents=True)
        return repo, batch

    def _phase(self, batch, filename, title="Phase", size="S", context=None, files=None,
               changes=None, verify=None):
        body = f"# {title}\n\n## Size\n\n{size}\n"
        if context is not None:
            body += f"\n## Context\n\n{context}\n"
        if files is not None:
            body += "\n## Affected Files\n\n" + "\n".join(files) + "\n"
        if changes is not None:
            body += f"\n## Changes\n\n{changes}\n"
        if verify is not None:
            body += f"\n## Verification\n\n```bash\n{verify}\n```\n"
        path = batch / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def _review(self, batch, *extra, check=True):
        return self.run_cfq("brief", str(batch), "--review", *extra, check=check)

    def _no_trailing_space(self, out):
        for line in out.splitlines():
            self.assertFalse(line.endswith(" "), f"line ends in a space: {line!r}")

    def test_routine_full_digest(self):
        repo, batch = self._review_batch("020-2026-03-01-review")
        (batch / ".batch-context.md").write_text(
            "# Batch Context\n\n"
            "## Goal\n\nMake the thing reviewable.\n\n"
            "## Decisions\n\n- First decision.\n- Second decision.\n\n"
            "## Non-Goals\n\n- No third thing.\n"
        )
        self._phase(
            batch, "01-first.md", "First phase", "S",
            context="First paragraph line.\n\nSecond paragraph line.",
            files=[f"- `{repo}/src/a.py`", f"- `{repo}/tests/test_a.py` (new)"],
            changes=(
                "1. Write the test in `tests/test_a.py`.\n"
                "   - detail one\n"
                "   - detail two\n"
                "2. Change `src/a.py` to pass it."
            ),
            verify="python3 -m unittest tests.test_a",
        )
        out = self._review(batch).stdout
        self._no_trailing_space(out)
        expected = "\n".join([
            "BATCH 020 · 2026-03-01 · review",
            "1 phases planned · 0 done",
            "",
            "  Goal",
            "    Make the thing reviewable.",
            "  Decisions",
            "    - First decision.",
            "    - Second decision.",
            "  Non-Goals",
            "    - No third thing.",
            "",
            "PHASE 01 · First phase · Size S",
            "  Context",
            "    First paragraph line.",
            "",
            "    Second paragraph line.",
            "  Files",
            "    src/a.py",
            "    tests/test_a.py (new)",
            "  Changes",
            "    1. Write the test in `tests/test_a.py`. (+2 details)",
            "    2. Change `src/a.py` to pass it.",
            "  Verify   python3 -m unittest tests.test_a",
            "  Edit     .claude/cfq/impl/020-2026-03-01-review/01-first.md",
            "",
            f"  Plans    {batch.resolve()}",
            f"  Context  {batch.resolve()}/.batch-context.md",
            f"  Portal   file://{repo}/.claude/cfq/reports/index.html#/batch/020-2026-03-01-review",
        ])
        self.assertEqual(out.rstrip("\n"), expected)

    def test_long_decision_bullet_wraps_never_cut(self):
        _, batch = self._review_batch("022-2026-03-01-longdec")
        words = " ".join(f"word{i}" for i in range(60))
        (batch / ".batch-context.md").write_text(f"## Decisions\n\n- {words}\n")
        self._phase(batch, "01-a.md")
        out = self._review(batch).stdout
        self._no_trailing_space(out)
        self.assertNotIn("…", out)
        lines = out.splitlines()
        start = lines.index("    - " + lines[lines.index("  Decisions") + 1][6:])
        block = lines[start:]
        self.assertTrue(block[1].startswith("      word"), block[:3])
        self.assertFalse(block[1].startswith("       "), block[:3])
        for line in lines[:next(n for n, l in enumerate(lines) if l.startswith('PHASE'))]:
            self.assertLessEqual(len(line), 72, line)
        joined = " ".join(l.strip() for l in lines[start:start + 12])
        self.assertIn("word59", joined)

    def test_bullets_without_numbered_steps_become_steps(self):
        _, batch = self._review_batch("023-2026-03-01-bullets")
        self._phase(batch, "01-a.md", changes="- Do the first thing.\n- Do the second thing.")
        out = self._review(batch).stdout
        self.assertIn("  Changes\n    1. Do the first thing.\n    2. Do the second thing.\n", out)

    def test_fence_line_is_not_a_step_and_counts_as_detail(self):
        _, batch = self._review_batch("024-2026-03-01-fence")
        self._phase(
            batch, "01-a.md",
            changes="1. Run the command.\n```bash\n1. not a step\n```\n2. Second step.",
        )
        out = self._review(batch).stdout
        self.assertIn("    1. Run the command. (+1 detail)\n    2. Second step.\n", out)
        self.assertNotIn("not a step", out)

    def test_long_step_lead_truncates_but_keeps_details_suffix(self):
        _, batch = self._review_batch("025-2026-03-01-longstep")
        words = " ".join(f"alpha{i}" for i in range(80))
        self._phase(batch, "01-a.md", changes=f"1. {words}\n   - x\n   - y\n   - z")
        out = self._review(batch).stdout
        self._no_trailing_space(out)
        lines = out.splitlines()
        i = lines.index("  Changes")
        step = lines[i + 1:i + 4]
        self.assertIn("…", step[-1])
        self.assertTrue(step[-1].endswith(" (+3 details)"), step)
        self.assertEqual(lines[i + 4], "  Edit     .claude/cfq/impl/025-2026-03-01-longstep/01-a.md")

    def test_phase_without_context_and_verification_omits_labels(self):
        _, batch = self._review_batch("026-2026-03-01-bare")
        self._phase(batch, "01-a.md", files=["- `/x/y.py`"], changes="1. Only step.")
        out = self._review(batch).stdout
        self._no_trailing_space(out)
        self.assertNotIn("  Context\n", out)
        self.assertNotIn("Verify", out)
        self.assertIn("  Changes", out)

    def test_no_batch_context_prints_no_context_block_or_footer_line(self):
        repo, batch = self._review_batch("027-2026-03-01-noctx")
        self._phase(batch, "01-a.md", changes="1. Step.")
        out = self._review(batch).stdout
        lines = out.splitlines()
        self.assertEqual(lines[2], "")
        self.assertTrue(lines[3].startswith("PHASE 01"), lines[:4])
        self.assertNotIn("  Context  ", out)
        self.assertIn(f"  Plans    {batch.resolve()}", out)

    def test_batch_outside_queue_layout_has_absolute_paths_and_no_portal(self):
        batch = self._repos_dir / "021-2026-03-01-loose"
        batch.mkdir(parents=True)
        path = self._phase(batch, "01-a.md", files=["- `/abs/where/x.py`"], changes="1. Step.")
        out = self._review(batch).stdout
        self.assertIn("    /abs/where/x.py\n", out)
        self.assertIn(f"  Edit     {path.resolve()}\n", out)
        self.assertNotIn("Portal", out)

    def test_html_report_false_drops_portal_line(self):
        repo, batch = self._review_batch("028-2026-03-01-noportal")
        self._phase(batch, "01-a.md", changes="1. Step.")
        (repo / ".claude" / "cfq" / "settings.json").write_text('{"htmlReport": false}\n')
        out = self._review(batch).stdout
        self.assertNotIn("Portal", out)
        self.assertIn("  Plans    ", out)

    def test_done_phase_renders_first_marked_done(self):
        repo, batch = self._review_batch("029-2026-03-01-donefirst")
        self._phase(batch, "done/01-old.md", "Old phase", changes="1. Old step.")
        self._phase(batch, "02-new.md", "New phase", changes="1. New step.")
        out = self._review(batch).stdout
        self.assertIn("PHASE 01 · Old phase · Size S · done", out)
        self.assertLess(out.index("PHASE 01"), out.index("PHASE 02"))
        self.assertIn("  Edit     .claude/cfq/impl/029-2026-03-01-donefirst/done/01-old.md", out)
        self.assertIn("2 phases planned · 1 done", out)

    def test_prose_changes_falls_back_to_first_paragraph_max_six_lines(self):
        _, batch = self._review_batch("030-2026-03-01-prose")
        prose = " ".join(f"prose{i}" for i in range(200))
        self._phase(batch, "01-a.md", changes=f"{prose}\n\nSecond paragraph.")
        out = self._review(batch).stdout
        self._no_trailing_space(out)
        lines = out.splitlines()
        i = lines.index("  Changes")
        end = next(n for n in range(i + 1, len(lines)) if not lines[n].startswith("    "))
        self.assertEqual(end - i - 1, 6, lines[i:end + 1])
        self.assertTrue(lines[end - 1].endswith("…"))
        self.assertNotIn("Second paragraph", out)

    def test_phases_option_prints_only_selected_blocks(self):
        _, batch = self._review_batch("031-2026-03-01-only")
        (batch / ".batch-context.md").write_text("## Goal\n\nSomething.\n")
        self._phase(batch, "01-a.md", "Alpha", changes="1. A.")
        self._phase(batch, "02-b.md", "Beta", changes="1. B.")
        out = self._review(batch, "--phases", "02").stdout
        self.assertTrue(out.startswith("PHASE 02 · Beta"), out)
        self.assertNotIn("BATCH", out)
        self.assertNotIn("PHASE 01", out)
        self.assertNotIn("Plans", out)
        self.assertNotIn("Goal", out)

    def test_unknown_phase_exits_one(self):
        _, batch = self._review_batch("032-2026-03-01-unknown")
        self._phase(batch, "01-a.md")
        r = self._review(batch, "--phases", "09", check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no phase 09", r.stderr)

    def test_phases_without_review_exits_two(self):
        _, batch = self._review_batch("033-2026-03-01-bad")
        self._phase(batch, "01-a.md")
        r = self.run_cfq("brief", str(batch), "--phases", "01")
        self.assertEqual(r.returncode, 2)

    # ---- --changed (phase 03 of batch 049) ---------------------------------------------------

    def _changed_batch(self, name):
        repo, batch = self._review_batch(name)
        (batch / ".batch-context.md").write_text("## Goal\n\nSomething.\n")
        self._phase(batch, "01-a.md", "Alpha", changes="1. A step.")
        self._phase(batch, "02-b.md", "Beta", changes="1. B step.")
        self.run_cfq("batch", "review", str(batch), check=True)
        return batch

    def test_changed_nothing_changed(self):
        batch = self._changed_batch("040-2026-03-01-c0")
        out = self._review(batch, "--changed").stdout
        self.assertEqual(out.strip(), "no changes since last review")

    def test_changed_prints_only_changed_phase(self):
        batch = self._changed_batch("041-2026-03-01-c1")
        self._phase(batch, "02-b.md", "Beta", changes="1. B rewritten step.")
        out = self._review(batch, "--changed").stdout
        self.assertIn("1 changed since last review", out)
        self.assertIn("PHASE 02 · Beta", out)
        self.assertIn("B rewritten step.", out)
        self.assertNotIn("PHASE 01", out)
        self.assertNotIn("Goal", out)
        self.assertIn("BATCH", out)

    def test_changed_context_edit_prints_context_block(self):
        batch = self._changed_batch("042-2026-03-01-c2")
        (batch / ".batch-context.md").write_text("## Goal\n\nSomething else.\n")
        out = self._review(batch, "--changed").stdout
        self.assertIn("Something else.", out)
        self.assertNotIn("PHASE 01", out)

    def test_changed_new_and_removed_phase(self):
        batch = self._changed_batch("043-2026-03-01-c3")
        self._phase(batch, "03-c.md", "Gamma", changes="1. C step.")
        (batch / "01-a.md").unlink()
        out = self._review(batch, "--changed").stdout
        self.assertIn("2 changed since last review", out)
        self.assertIn("PHASE 03 · Gamma", out)
        self.assertIn("  Removed  01-a.md", out)

    def test_changed_without_snapshot_exits_one(self):
        _, batch = self._review_batch("044-2026-03-01-c4")
        self._phase(batch, "01-a.md")
        r = self._review(batch, "--changed", check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cfq batch review", r.stderr)

    def test_changed_bad_option_combinations_exit_two(self):
        batch = self._changed_batch("045-2026-03-01-c5")
        r = self._review(batch, "--changed", "--phases", "01", check=False)
        self.assertEqual(r.returncode, 2)
        r = self.run_cfq("brief", str(batch), "--changed")
        self.assertEqual(r.returncode, 2)


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

    # ---- planning-marker lifecycle (phase 01 of batch 043: the marker is born at `batch
    # allocate`, not at `park` -- these three cover park's remaining role, the fallback for a
    # caller that skips allocate) --------------------------------------------------------------

    def test_park_on_new_dir_writes_planning(self):
        # a caller that skips `batch allocate` and parks directly still gets a marker, since the
        # directory park creates itself is brand new
        batchdir = self.parkrepo / ".claude/cfq/impl/2026-01-10-freshpark"
        self.assertFalse(batchdir.exists(), "fixture must start without the batch directory")
        self._park("2026-01-10-freshpark", "normal")
        self.assertTrue(
            (batchdir / ".planning").is_file(), "park on a brand-new directory did not write .planning",
        )

    def test_park_refreshes_existing_planning(self):
        batchdir = self.parkrepo / ".claude/cfq/impl/2026-01-11-refresh"
        batchdir.mkdir(parents=True)
        old = "2026-01-01T00:00:00+00:00\n"
        (batchdir / ".planning").write_text(old)

        proc = self.run_cfq(
            "park", str(self.parkrepo), "2026-01-11-refresh", "normal", home=self.park_home,
        )
        self.assertEqual(proc.returncode, 0, f"park should exit 0: {proc.stderr}")
        self.assertEqual(
            proc.stdout.strip(), str(batchdir), f"stdout must be exactly the batch path: {proc.stdout!r}",
        )
        self.assertEqual(proc.stderr, "", f"refreshing an existing marker must not warn: {proc.stderr!r}")
        self.assertNotEqual(
            (batchdir / ".planning").read_text(), old, "park did not refresh the existing .planning marker",
        )

    def test_park_after_ready_does_not_resurrect_planning(self):
        batch = "2026-01-12-afterready"
        batchdir = self.parkrepo / ".claude/cfq/impl" / batch
        self._park(batch, "normal")
        self.assertTrue((batchdir / ".planning").exists(), "fixture setup: first park must write .planning")

        self.run_cfq("batch", "ready", str(batchdir), home=self.park_home, check=True)
        self.assertFalse((batchdir / ".planning").exists(), "fixture setup: batch ready must remove .planning")

        proc = self.run_cfq(
            "park", str(self.parkrepo), batch, "high", home=self.park_home,
        )
        self.assertEqual(proc.returncode, 0, f"re-park after ready should still exit 0: {proc.stderr}")
        self.assertEqual(
            proc.stdout.strip(), str(batchdir), f"stdout must be exactly the batch path: {proc.stdout!r}",
        )
        self.assertFalse(
            (batchdir / ".planning").exists(), "re-park after `batch ready` must not resurrect .planning",
        )
        self.assertIn("already ready", proc.stderr, f"stderr missing the already-ready warning: {proc.stderr!r}")
        self.assertEqual(
            (batchdir / ".priority").read_text().strip(), "high",
            ".priority must still be rewritten from the second call's arguments",
        )

    def test_park_on_review_batch_leaves_review_and_creates_no_planning(self):
        batch = "2026-01-13-inreview"
        batchdir = self.parkrepo / ".claude/cfq/impl" / batch
        batchdir.mkdir(parents=True)
        (batchdir / ".review").write_text('{"since": "x"}\n')

        proc = self.run_cfq(
            "park", str(self.parkrepo), batch, "normal", home=self.park_home,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((batchdir / ".review").read_text(), '{"since": "x"}\n')
        self.assertFalse((batchdir / ".planning").exists())
        self.assertEqual(proc.stderr, "")

    # ---- status.json follows the phase files (batch 051 phase 02) -----------------------------

    def _phase_status(self, batchdir):
        return {
            k: v["status"]
            for k, v in json.loads((batchdir / "status.json").read_text())["phases"].items()
        }

    def test_park_lists_adds_and_drops_phase_files(self):
        batch = "2026-01-14-statuspark"
        batchdir = self.parkrepo / ".claude/cfq/impl" / batch
        batchdir.mkdir(parents=True)
        (batchdir / "01-a.md").write_text("# A\n")
        (batchdir / "02-b.md").write_text("# B\n")
        self._park(batch, "normal")
        self.assertEqual(self._phase_status(batchdir), {"01-a": "open", "02-b": "open"})
        (batchdir / "03-c.md").write_text("# C\n")
        self._park(batch, "normal")
        self.assertEqual(
            self._phase_status(batchdir), {"01-a": "open", "02-b": "open", "03-c": "open"},
        )
        (batchdir / "02-b.md").unlink()
        self._park(batch, "normal")
        self.assertEqual(self._phase_status(batchdir), {"01-a": "open", "03-c": "open"})

    def test_park_without_allocate_still_ends_with_a_status_file(self):
        self._park("2026-01-15-noalloc", "normal")
        batchdir = self.parkrepo / ".claude/cfq/impl/2026-01-15-noalloc"
        self.assertEqual(self._phase_status(batchdir), {})

    def test_park_with_an_invalid_status_file_fails_and_keeps_it(self):
        batch = "2026-01-16-badstatus"
        batchdir = self.parkrepo / ".claude/cfq/impl" / batch
        batchdir.mkdir(parents=True)
        (batchdir / "status.json").write_text("{not json")
        proc = self.run_cfq("park", str(self.parkrepo), batch, "normal", home=self.park_home)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("STATUS_FILE_INVALID", proc.stderr)
        self.assertEqual((batchdir / "status.json").read_text(), "{not json")


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

    def test_name_collision_in_plan_done_gets_a_suffix(self):
        done_dir = self.plan_dir / "done"
        done_dir.mkdir(parents=True)
        entry = self.plan_dir / "2026-01-01-x.md"
        entry.write_text("B")
        (done_dir / "2026-01-01-x.md").write_text("A")

        proc = self._park("2026-02-04-batch", from_plan=entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((done_dir / "2026-01-01-x.md").read_text(), "A")
        self.assertEqual((done_dir / "2026-01-01-x-2.md").read_text(), "B")
        self.assertFalse(entry.exists(), "the source must be gone")

    def test_second_collision_in_plan_done_gets_suffix_3(self):
        done_dir = self.plan_dir / "done"
        done_dir.mkdir(parents=True)
        entry = self.plan_dir / "2026-01-01-x.md"
        entry.write_text("C")
        (done_dir / "2026-01-01-x.md").write_text("A")
        (done_dir / "2026-01-01-x-2.md").write_text("B")

        proc = self._park("2026-02-04-batch", from_plan=entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((done_dir / "2026-01-01-x.md").read_text(), "A")
        self.assertEqual((done_dir / "2026-01-01-x-2.md").read_text(), "B")
        self.assertEqual((done_dir / "2026-01-01-x-3.md").read_text(), "C")
        self.assertFalse(entry.exists())

    def test_one_collision_among_three_entries_holds_none_back(self):
        done_dir = self.plan_dir / "done"
        done_dir.mkdir(parents=True)
        first = self.plan_dir / "2026-01-01-a.md"
        middle = self.plan_dir / "2026-01-02-b.md"
        last = self.plan_dir / "2026-01-03-c.md"
        for f, body in ((first, "1"), (middle, "2"), (last, "3")):
            f.write_text(body)
        (done_dir / "2026-01-02-b.md").write_text("old")

        proc = self._park("2026-02-04-batch", from_plan=[first, middle, last])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for f in (first, middle, last):
            self.assertFalse(f.exists(), f"{f.name} must be gone")
        self.assertEqual((done_dir / "2026-01-01-a.md").read_text(), "1")
        self.assertEqual((done_dir / "2026-01-02-b.md").read_text(), "old")
        self.assertEqual((done_dir / "2026-01-02-b-2.md").read_text(), "2")
        self.assertEqual((done_dir / "2026-01-03-c.md").read_text(), "3")

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

    # --- batch 050 phase 07: fromPlan ledger ---

    def _from_plan(self, batch):
        path = self.parkrepo / ".claude" / "cfq" / "impl" / batch / "report.json"
        return json.loads(path.read_text()).get("fromPlan")

    def test_single_entry_recorded(self):
        proc = self._park("2026-03-01-batch", from_plan=self.entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._from_plan("2026-03-01-batch"), [self.entry.name])

    def test_two_entries_recorded_sorted(self):
        second = self.plan_dir / "2026-01-02-second-finding.md"
        second.write_text("# Second\n")
        self._park("2026-03-02-batch", from_plan=[second, self.entry])
        self.assertEqual(
            self._from_plan("2026-03-02-batch"), sorted([self.entry.name, second.name]),
        )

    def test_repeated_park_leaves_list_unchanged(self):
        self._park("2026-03-03-batch", from_plan=self.entry)
        proc = self._park("2026-03-03-batch", from_plan=self.entry)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._from_plan("2026-03-03-batch"), [self.entry.name])

    def test_missing_report_json_gets_standard_skeleton(self):
        self._park("2026-03-04-batch", from_plan=self.entry)
        path = self.parkrepo / ".claude" / "cfq" / "impl" / "2026-03-04-batch" / "report.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["batch"], "2026-03-04-batch")
        self.assertEqual(data["phases"], [])
        self.assertIn("started", data)

    def test_no_flag_creates_no_report_json(self):
        self._park("2026-03-05-batch")
        path = self.parkrepo / ".claude" / "cfq" / "impl" / "2026-03-05-batch" / "report.json"
        self.assertFalse(path.exists())


class ParsePhaseBodySectionBoundaryTest(unittest.TestCase):
    def test_routine_context_stays_unchanged(self):
        body = textwrap.dedent("""\
            # Some phase

            ## Context

            Line one.
            Line two.

            ## Affected Files

            - `/tmp/example/foo.sh`
            """)
        fields = parse_phase_body(body)
        self.assertEqual(fields["context"], "Line one. Line two. ")
        self.assertEqual(fields["files"], ["foo.sh"])

    def test_one_line_context_does_not_swallow_next_heading(self):
        body = textwrap.dedent("""\
            # Some phase

            ## Context

            Only line.

            ## Affected Files

            - `/tmp/example/foo.sh`
            """)
        fields = parse_phase_body(body)
        self.assertEqual(fields["context"], "Only line. ")
        self.assertNotIn("## Affected Files", fields["context"])
        self.assertEqual(fields["files"], ["foo.sh"])

    def test_one_line_context_heading_on_very_next_line(self):
        body = textwrap.dedent("""\
            # Some phase

            ## Context
            Only line.
            ## Affected Files
            - `/tmp/example/foo.sh`
            """)
        fields = parse_phase_body(body)
        self.assertEqual(fields["context"], "Only line. ")
        self.assertNotIn("## Affected Files", fields["context"])
        self.assertEqual(fields["files"], ["foo.sh"])

    def test_empty_context(self):
        body = textwrap.dedent("""\
            # Some phase

            ## Context
            ## Affected Files
            - `/tmp/example/foo.sh`
            """)
        fields = parse_phase_body(body)
        self.assertEqual(fields["context"], "")
        self.assertEqual(fields["files"], ["foo.sh"])

    def test_empty_size(self):
        body = textwrap.dedent("""\
            # Some phase

            ## Size

            ## Context

            Ctx line.
            """)
        fields = parse_phase_body(body)
        self.assertIsNone(fields["size"])
        self.assertEqual(fields["context"], "Ctx line. ")

    def test_size_then_verification_still_parses(self):
        body = textwrap.dedent("""\
            # Some phase

            ## Size

            S

            ## Verification

            ```bash
            echo ok
            ```
            """)
        fields = parse_phase_body(body)
        self.assertEqual(fields["size"], "S")
        self.assertEqual(fields["check"], "echo ok")


if __name__ == "__main__":
    unittest.main()


class PhaseModelHeadingTest(PhaseDirsStatus, CfqTestCase):
    """The optional `## Model` heading: parsed like `## Size`, rendered in the phase header and the
    overview's size cell; classic-mode `--phase` shows it as not applied."""

    def _batch(self, name, model_block):
        batch = self._repos_dir / name
        batch.mkdir(parents=True)
        (batch / "01-first.md").write_text(
            "# First phase\n\n## Size\n\nS\n\n" + model_block
            + "## Context\n\nCtx line.\n\n## Affected Files\n\n- `/tmp/example/foo.sh`\n"
        )
        return batch

    def test_routine_model_parses_and_renders_in_header_and_overview(self):
        fields = parse_phase_body("# P\n\n## Size\n\nS\n\n## Model\n\nhaiku\n\n## Context\n\nx\n")
        self.assertEqual(fields["model"], "haiku")
        from cfq_brief import render_phase
        head = render_phase("01", fields).splitlines()[0]
        self.assertEqual(head, "PHASE 01 · P · Size S · Model haiku")

        batch = self._batch("model-overview", "## Model\n\nhaiku\n\n")
        out = self.run_cfq("brief", str(batch), "--overview", check=True).stdout
        self.assertRegex(out, r"01  First phase  S · haiku  open")

    def test_edge_empty_heading_gives_none_and_renders_like_no_heading(self):
        body = "# P\n\n## Size\n\nS\n\n## Model\n\n## Context\n\nx\n"
        fields = parse_phase_body(body)
        self.assertIsNone(fields["model"])
        self.assertEqual(fields["context"], "x ")
        from cfq_brief import render_phase
        plain = parse_phase_body("# P\n\n## Size\n\nS\n\n## Context\n\nx\n")
        self.assertIsNone(plain["model"])
        self.assertEqual(render_phase("01", fields), render_phase("01", plain))

    def test_edge_capitalised_model_is_lowercased(self):
        fields = parse_phase_body("# P\n\n## Model\n\nHaiku extra words\n")
        self.assertEqual(fields["model"], "haiku")

    def test_classic_phase_output_says_not_applied(self):
        batch = self._batch("model-classic", "## Model\n\nhaiku\n\n")
        out = self.run_cfq("brief", str(batch), "--phase", "01", check=True).stdout.splitlines()
        self.assertEqual(out[0], "PHASE 01 · First phase · Size S · Model haiku (not applied: classic mode)")
        out = self.run_cfq(
            "brief", str(batch), "--phase", "01", "--classic-fallback", check=True,
        ).stdout.splitlines()
        self.assertIn("(not applied: classic mode)", out[0])

    def test_worker_default_keeps_plain_model_clause(self):
        from cfq_brief import render_phase
        fields = parse_phase_body("# P\n\n## Model\n\nhaiku\n")
        self.assertEqual(render_phase("01", fields).splitlines()[0], "PHASE 01 · P · Size M · Model haiku")
        self.assertEqual(
            render_phase("01", fields, model_applies=False).splitlines()[0],
            "PHASE 01 · P · Size M · Model haiku (not applied: classic mode)",
        )
