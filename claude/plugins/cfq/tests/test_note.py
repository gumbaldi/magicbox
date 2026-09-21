"""Behavior tests for bin/cfq note plan|todo (scripts/cfq_note.py).

Replaces the agent composing `plan/<YYYY-MM-DD>-<slug>.md` / `todo/<YYYY-MM-DD>-<slug>.md`
itself -- date, slug normalisation and target directory are convention (see phase 04's
.batch-context.md and .claude/cfq/impl/.../04-note-ready-probe-and-skills.md).
"""

import datetime
import pathlib
import unittest

from cfq_testlib import CfqTestCase


class NoteTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.today = datetime.date.today().isoformat()

    def _body_file(self, content="# Title\n\nbody\n"):
        f = self._repos_dir / "body.md"
        f.write_text(content)
        return f

    def test_plan_entry_written_at_expected_path(self):
        body = self._body_file("# Finding\n\nsomething noticed\n")
        out = self.run_cfq(
            "note", "plan", str(self.repo), "Merge Batch 019", str(body), check=True,
        ).stdout.strip()

        expected = self.repo / ".claude" / "cfq" / "plan" / f"{self.today}-merge-batch-019.md"
        self.assertEqual(out, str(expected))
        self.assertEqual(expected.read_text(), "# Finding\n\nsomething noticed\n")

        inbox = self.home / ".claude" / "cfq" / "framework-inbox"
        self.assertFalse(
            inbox.exists(), "note plan without --framework must never create the inbox directory"
        )

    def test_todo_entry_written_at_expected_path(self):
        body = self._body_file("# Do the thing\n\none sentence.\n")
        out = self.run_cfq(
            "note", "todo", str(self.repo), "follow up", str(body), check=True,
        ).stdout.strip()

        expected = self.repo / ".claude" / "cfq" / "todo" / f"{self.today}-follow-up.md"
        self.assertEqual(out, str(expected))
        self.assertEqual(expected.read_text(), "# Do the thing\n\none sentence.\n")

    def test_slug_normalisation_spaces_capitals_trailing_period(self):
        body = self._body_file()
        out = self.run_cfq(
            "note", "todo", str(self.repo), "Merge  Batch. ", str(body), check=True,
        ).stdout.strip()
        expected = self.repo / ".claude" / "cfq" / "todo" / f"{self.today}-merge-batch.md"
        self.assertEqual(out, str(expected))

    def test_slug_normalising_to_empty_string_is_an_error(self):
        body = self._body_file()
        proc = self.run_cfq("note", "todo", str(self.repo), "...", str(body))
        self.assertNotEqual(proc.returncode, 0, "an empty-after-normalisation slug must fail")
        target_dir = self.repo / ".claude" / "cfq" / "todo"
        self.assertFalse(
            any(target_dir.glob(f"{self.today}-*.md")) if target_dir.is_dir() else False,
            "no file should have been written for an empty slug",
        )

    def test_existing_target_fails_and_leaves_it_unchanged(self):
        body = self._body_file()
        self.run_cfq("note", "plan", str(self.repo), "dup", str(body), check=True)
        target = self.repo / ".claude" / "cfq" / "plan" / f"{self.today}-dup.md"
        before = target.read_text()

        body2 = self._body_file("different content\n")
        proc = self.run_cfq("note", "plan", str(self.repo), "dup", str(body2))
        self.assertNotEqual(proc.returncode, 0, "writing onto an existing entry must fail")
        self.assertIn("EXISTS", proc.stderr)
        self.assertEqual(target.read_text(), before, "existing entry's bytes must be unchanged")

    def test_missing_body_file_fails(self):
        missing = self._repos_dir / "does-not-exist.md"
        proc = self.run_cfq("note", "plan", str(self.repo), "whatever", str(missing))
        self.assertNotEqual(proc.returncode, 0, "a missing body file must fail")

    def _inbox_dir(self):
        return self.home / ".claude" / "cfq" / "framework-inbox"

    # frameworkRepo unset: --framework always lands in the global inbox, never the repo's own
    # plan/.
    def test_framework_flag_unset_writes_to_global_inbox(self):
        body = self._body_file("# cfq finding\n\nabout cfq itself\n")
        out = self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "cfq finding", str(body), check=True,
        ).stdout.strip()

        expected = self._inbox_dir() / f"{self.today}-cfq-finding.md"
        self.assertEqual(out, str(expected))
        self.assertEqual(expected.read_text(), "# cfq finding\n\nabout cfq itself\n")

        repo_plan_dir = self.repo / ".claude" / "cfq" / "plan"
        self.assertFalse(
            any(repo_plan_dir.glob("*.md")) if repo_plan_dir.is_dir() else False,
            "no entry should land in the repo's own plan/ when frameworkRepo is unset",
        )

    # frameworkRepo set to the repo itself: --framework writes the ordinary plan/ entry, nothing
    # in the inbox.
    def test_framework_flag_when_repo_is_framework_repo_writes_ordinary_plan_entry(self):
        self.run_cfq(
            "settings", "set", "frameworkRepo", str(self.repo), home=self.home, check=True
        )
        body = self._body_file("# cfq finding\n\nabout cfq itself\n")
        out = self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "cfq finding", str(body), check=True,
        ).stdout.strip()

        expected = self.repo / ".claude" / "cfq" / "plan" / f"{self.today}-cfq-finding.md"
        self.assertEqual(out, str(expected))
        self.assertEqual(expected.read_text(), "# cfq finding\n\nabout cfq itself\n")

        inbox = self._inbox_dir()
        self.assertFalse(
            any(inbox.glob("*.md")) if inbox.is_dir() else False,
            "nothing should land in the inbox when the target repo is frameworkRepo",
        )

    # frameworkRepo set to a *different* repo: the entry still goes to the inbox, never into the
    # other repo -- the cross-repo write stays impossible.
    def test_framework_flag_with_different_framework_repo_still_uses_inbox(self):
        other = self.make_repo("framework-repo")
        self.run_cfq("settings", "set", "frameworkRepo", str(other), home=self.home, check=True)

        body = self._body_file("# cfq finding\n\nabout cfq itself\n")
        out = self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "cfq finding", str(body), check=True,
        ).stdout.strip()

        expected = self._inbox_dir() / f"{self.today}-cfq-finding.md"
        self.assertEqual(out, str(expected))

        other_plan_dir = other / ".claude" / "cfq" / "plan"
        self.assertFalse(
            any(other_plan_dir.glob("*.md")) if other_plan_dir.is_dir() else False,
            "the cross-repo write must stay impossible -- a session never writes into a second repo",
        )
        repo_plan_dir = self.repo / ".claude" / "cfq" / "plan"
        self.assertFalse(
            any(repo_plan_dir.glob("*.md")) if repo_plan_dir.is_dir() else False,
        )

    # note import <repo> with frameworkRepo == <repo> and two inbox entries: both files move into
    # <repo>/.claude/cfq/plan/, the inbox is empty afterwards.
    def test_import_moves_entries_when_repo_is_framework_repo(self):
        body1 = self._body_file("# finding one\n\nbody one\n")
        self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "finding one", str(body1), check=True,
        )
        body2 = self._body_file("# finding two\n\nbody two\n")
        self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "finding two", str(body2), check=True,
        )

        inbox = self._inbox_dir()
        self.assertEqual(
            len(list(inbox.glob("*.md"))), 2, "both entries should be in the inbox before import"
        )

        self.run_cfq(
            "settings", "set", "frameworkRepo", str(self.repo), home=self.home, check=True
        )

        out = self.json_out(
            self.run_cfq("note", "import", str(self.repo), check=True)
        )
        expected_one = self.repo / ".claude" / "cfq" / "plan" / f"{self.today}-finding-one.md"
        expected_two = self.repo / ".claude" / "cfq" / "plan" / f"{self.today}-finding-two.md"
        self.assertEqual(out["status"], "OK")
        self.assertCountEqual(out["imported"], [str(expected_one), str(expected_two)])
        self.assertEqual(expected_one.read_text(), "# finding one\n\nbody one\n")
        self.assertEqual(expected_two.read_text(), "# finding two\n\nbody two\n")
        self.assertEqual(list(inbox.glob("*.md")), [], "inbox must be empty after import")

    # note import <repo> with frameworkRepo unset or pointing elsewhere: exit 0, nothing moved.
    def test_import_skips_when_repo_is_not_framework_repo(self):
        out = self.json_out(self.run_cfq("note", "import", str(self.repo), check=True))
        self.assertEqual(out, {"status": "OK", "imported": [], "skipped": "not frameworkRepo"})

        other = self.make_repo("elsewhere")
        self.run_cfq("settings", "set", "frameworkRepo", str(other), home=self.home, check=True)
        out = self.json_out(self.run_cfq("note", "import", str(self.repo), check=True))
        self.assertEqual(out, {"status": "OK", "imported": [], "skipped": "not frameworkRepo"})

    # Collision case: an inbox entry whose filename already exists in plan/ stays in the inbox
    # and is reported in errors; the other entries still import. Nothing is ever overwritten.
    def test_import_collision_stays_in_inbox_others_still_import(self):
        body1 = self._body_file("# finding\n\ninbox body\n")
        self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "finding", str(body1), check=True,
        )
        body2 = self._body_file("# other finding\n\nother body\n")
        self.run_cfq(
            "note", "plan", "--framework", str(self.repo), "other finding", str(body2), check=True,
        )
        self.run_cfq(
            "settings", "set", "frameworkRepo", str(self.repo), home=self.home, check=True
        )

        plan_dir = self.repo / ".claude" / "cfq" / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        colliding = plan_dir / f"{self.today}-finding.md"
        colliding.write_text("already there\n")

        out = self.json_out(self.run_cfq("note", "import", str(self.repo), check=True))
        expected_other = plan_dir / f"{self.today}-other-finding.md"
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["imported"], [str(expected_other)])
        self.assertIn(str(colliding), out.get("errors", []))
        self.assertEqual(colliding.read_text(), "already there\n", "existing entry must not be overwritten")
        self.assertEqual(expected_other.read_text(), "# other finding\n\nother body\n")

        inbox = self._inbox_dir()
        remaining = list(inbox.glob("*.md"))
        self.assertEqual(len(remaining), 1, "the colliding entry must stay in the inbox")
        self.assertEqual(remaining[0].name, f"{self.today}-finding.md")

    # note merge-todo composes the whole card itself -- title, ready-to-run merge command and a
    # `check:` line -- so the line can never be forgotten the way a model-composed card leaves it
    # out (see .batch-context.md for phase 01's rationale).
    def test_merge_todo_writes_card_with_check_line(self):
        branch = "cfq/030-2026-09-20-some-slug"
        out = self.run_cfq(
            "note", "merge-todo", str(self.repo), branch, check=True,
        ).stdout.strip()

        expected = (
            self.repo / ".claude" / "cfq" / "todo"
            / f"{self.today}-merge-cfq-030-2026-09-20-some-slug.md"
        )
        self.assertEqual(out, str(expected))

        content = expected.read_text()
        lines = content.splitlines()
        self.assertTrue(lines[0].startswith("# "), "card must open with an H1 title")
        self.assertIn(f"git checkout main && git merge --ff-only {branch}", content)
        check_lines = [line for line in lines if line.startswith("check: ")]
        self.assertEqual(len(check_lines), 1, "card must carry exactly one check: line")

    # Edge case that actually bites: normalise_slug() maps anything outside [a-z0-9-] to nothing,
    # so a raw branch slug with a "/" would collapse the segment boundary (cfq030-x) unless the
    # subcommand translates "/" to "-" itself before normalising.
    def test_merge_todo_branch_slash_keeps_segment_boundary(self):
        branch = "cfq/030-x"
        out = self.run_cfq(
            "note", "merge-todo", str(self.repo), branch, check=True,
        ).stdout.strip()

        expected = self.repo / ".claude" / "cfq" / "todo" / f"{self.today}-merge-cfq-030-x.md"
        self.assertEqual(out, str(expected))

    # The check: line must try origin/main first and fall back to local main -- a repo without a
    # remote still closes its cards, and a stale/missing origin ref leaves the card open rather
    # than reporting a merge that hasn't happened (never a false positive). Same resolution order
    # as cfq_branch.py:331/341.
    def test_merge_todo_check_line_tries_origin_then_local_main(self):
        branch = "cfq/030-x"
        out = self.run_cfq(
            "note", "merge-todo", str(self.repo), branch, check=True,
        ).stdout.strip()

        content = pathlib.Path(out).read_text()
        expected_check = (
            "check: git merge-base --is-ancestor cfq/030-x origin/main 2>/dev/null "
            "|| git merge-base --is-ancestor cfq/030-x main"
        )
        self.assertIn(expected_check, content)

    # Same day, same branch, twice: the second call must fail with the existing EXISTS error and
    # must not overwrite the first card -- merge-todo inherits cmd_note's write path rather than
    # inventing its own overwrite behaviour.
    def test_merge_todo_twice_same_day_fails_and_leaves_first_card_unchanged(self):
        branch = "cfq/030-x"
        self.run_cfq("note", "merge-todo", str(self.repo), branch, check=True)
        target = self.repo / ".claude" / "cfq" / "todo" / f"{self.today}-merge-cfq-030-x.md"
        before = target.read_text()

        proc = self.run_cfq("note", "merge-todo", str(self.repo), branch)
        self.assertNotEqual(proc.returncode, 0, "writing onto an existing card must fail")
        self.assertIn("EXISTS", proc.stderr)
        self.assertEqual(target.read_text(), before, "existing card's bytes must be unchanged")

    # Empty/missing inbox directory: exit 0, imported: [], no directory created as a side effect.
    def test_import_with_missing_inbox_directory(self):
        self.run_cfq(
            "settings", "set", "frameworkRepo", str(self.repo), home=self.home, check=True
        )
        inbox = self._inbox_dir()
        self.assertFalse(inbox.exists(), "inbox must not exist yet for this test to be meaningful")

        out = self.json_out(self.run_cfq("note", "import", str(self.repo), check=True))
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["imported"], [])
        self.assertFalse(inbox.exists(), "importing must not create the inbox directory")


class NoteListTest(CfqTestCase):
    """Behavior tests for `bin/cfq note list` -- renders the plan/ inbox without consuming it,
    see phase 05's .batch-context.md and .claude/cfq/impl/.../05-plan-inbox-list-and-consume.md."""

    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.plan_dir = self.repo / ".claude" / "cfq" / "plan"

    def _write_entry(self, filename, content):
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        f = self.plan_dir / filename
        f.write_text(content)
        return f

    def test_three_entries_mixed_creation_order_sorted_output(self):
        # Written out of filename order on purpose -- the listing must sort by filename, not by
        # creation order.
        self._write_entry("2026-01-03-third.md", "# Third\n\nbody\n")
        self._write_entry("2026-01-01-first.md", "# First\n\nbody\n")
        self._write_entry("2026-01-02-second.md", "# Second\n\nbody\n")

        out = self.json_out(self.run_cfq("note", "list", str(self.repo), check=True))
        self.assertEqual(
            [e["filename"] for e in out],
            ["2026-01-01-first.md", "2026-01-02-second.md", "2026-01-03-third.md"],
        )
        self.assertEqual(out[0]["date"], "2026-01-01")
        self.assertEqual(out[0]["slug"], "first")
        self.assertEqual(out[0]["title"], "First")
        self.assertEqual(out[0]["path"], str(self.plan_dir / "2026-01-01-first.md"))

    def test_entry_with_no_heading_falls_back_to_first_non_empty_line(self):
        self._write_entry("2026-01-01-noheading.md", "\nJust a plain first line.\n\nMore body.\n")
        out = self.json_out(self.run_cfq("note", "list", str(self.repo), check=True))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Just a plain first line.")
        self.assertEqual(out[0]["excerpt"], "More body.")

    def test_single_long_paragraph_excerpt_is_truncated_with_ellipsis(self):
        long_line = " ".join(f"word{i}" for i in range(60))
        self.assertGreater(len(long_line), 200)
        self._write_entry("2026-01-01-long.md", f"# Long finding\n\n{long_line}\n")

        out = self.json_out(self.run_cfq("note", "list", str(self.repo), check=True))
        excerpt = out[0]["excerpt"]
        self.assertLessEqual(len(excerpt), 201, f"excerpt too long: {excerpt!r}")
        self.assertTrue(excerpt.endswith("…"), f"excerpt must end in an ellipsis: {excerpt!r}")
        self.assertTrue(long_line.startswith(excerpt[:-1].rstrip()), f"cut text must be a prefix: {excerpt!r}")

    def test_plan_done_entry_is_not_listed(self):
        self._write_entry("2026-01-01-visible.md", "# Visible\n\nbody\n")
        done_dir = self.plan_dir / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "2026-01-01-consumed.md").write_text("# Consumed\n\nbody\n")

        out = self.json_out(self.run_cfq("note", "list", str(self.repo), check=True))
        self.assertEqual([e["filename"] for e in out], ["2026-01-01-visible.md"])

    def test_empty_plan_dir_returns_empty_list(self):
        self.plan_dir.mkdir(parents=True)
        proc = self.run_cfq("note", "list", str(self.repo))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.json_out(proc), [])

    def test_missing_plan_dir_returns_empty_list(self):
        self.assertFalse(self.plan_dir.exists())
        proc = self.run_cfq("note", "list", str(self.repo))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.json_out(proc), [])

    def test_text_rendering_lists_date_title_and_excerpt(self):
        self._write_entry("2026-01-01-first.md", "# First finding\n\nsomething noticed here.\n")
        out = self.run_cfq(
            "note", "list", str(self.repo), "--text", check=True,
        ).stdout
        self.assertIn("2026-01-01  First finding  something noticed here.", out.splitlines())
        self.assertNotIn("&nbsp;", out, "padding must use real spaces, never HTML entities")

    def test_text_rendering_empty_inbox(self):
        self.plan_dir.mkdir(parents=True)
        out = self.run_cfq(
            "note", "list", str(self.repo), "--text", check=True,
        ).stdout
        self.assertIn("No planning requests waiting in the queue.", out)


if __name__ == "__main__":
    unittest.main()
