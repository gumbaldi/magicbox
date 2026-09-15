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


if __name__ == "__main__":
    unittest.main()
