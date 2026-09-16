"""Behavior tests for bin/cfq note plan|todo (scripts/cfq_note.py).

Replaces the agent composing `plan/<YYYY-MM-DD>-<slug>.md` / `todo/<YYYY-MM-DD>-<slug>.md`
itself -- date, slug normalisation and target directory are convention (see phase 04's
.batch-context.md and .claude/cfq/impl/.../04-note-ready-probe-and-skills.md).
"""

import datetime
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

        inbox = self.home / ".claude" / "code-for-queue" / "framework-inbox"
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
        return self.home / ".claude" / "code-for-queue" / "framework-inbox"

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


if __name__ == "__main__":
    unittest.main()
