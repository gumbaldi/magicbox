"""Behavior tests for bin/cfq trash put|list|restore (scripts/cfq_trash.py, cfq_lib/trash.py).

`.claude/cfq/` is git-excluded, so trash is the only sanctioned way to remove anything under it --
these tests pin the put/restore round-trip and the failure modes phase 06's guard relies on (see
.batch-context.md's Decisions).
"""

import unittest

from cfq_testlib import CfqTestCase


class TrashTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.cfq_dir = self.repo / ".claude" / "cfq"
        self.cfq_dir.mkdir(parents=True)

    def test_put_then_list_shows_one_entry(self):
        target = self.cfq_dir / "impl" / "batch-a" / "01-phase.md"
        target.parent.mkdir(parents=True)
        target.write_text("plan\n")

        entry_id = self.run_cfq("trash", "put", str(self.repo), str(target), check=True).stdout.strip()
        self.assertTrue(entry_id)
        self.assertFalse(target.exists())

        listing = self.json_out(self.run_cfq("trash", "list", str(self.repo), "--json", check=True))
        self.assertEqual(len(listing), 1, f"expected one entry: {listing!r}")
        self.assertEqual(listing[0]["id"], entry_id)
        self.assertEqual(listing[0]["originalPath"], str(target))
        self.assertEqual(listing[0]["kind"], "file")

    def test_put_then_restore_directory_restores_both_files(self):
        done_dir = self.cfq_dir / "impl" / "batch-b" / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "01-a.md").write_text("a\n")
        (done_dir / "02-b.md").write_text("b\n")

        entry_id = self.run_cfq("trash", "put", str(self.repo), str(done_dir), check=True).stdout.strip()
        self.assertFalse(done_dir.exists())

        restored = self.run_cfq("trash", "restore", str(self.repo), entry_id, check=True).stdout.strip()
        self.assertEqual(restored, str(done_dir))
        self.assertEqual((done_dir / "01-a.md").read_text(), "a\n")
        self.assertEqual((done_dir / "02-b.md").read_text(), "b\n")

    def test_put_then_restore_file_byte_identical(self):
        target = self.cfq_dir / "todo" / "note.md"
        target.parent.mkdir(parents=True)
        content = "keep this exact content\n"
        target.write_text(content)

        entry_id = self.run_cfq("trash", "put", str(self.repo), str(target), check=True).stdout.strip()
        restored = self.run_cfq("trash", "restore", str(self.repo), entry_id, check=True).stdout.strip()
        self.assertEqual(restored, str(target))
        self.assertEqual(target.read_text(), content)

    def test_two_puts_in_same_second_produce_distinct_entries(self):
        a = self.cfq_dir / "todo" / "a.md"
        b = self.cfq_dir / "todo" / "b.md"
        a.parent.mkdir(parents=True)
        a.write_text("a\n")
        b.write_text("b\n")

        id_a = self.run_cfq("trash", "put", str(self.repo), str(a), check=True).stdout.strip()
        id_b = self.run_cfq("trash", "put", str(self.repo), str(b), check=True).stdout.strip()

        self.assertNotEqual(id_a, id_b, "two puts in the same run collided on the same entry id")
        listing = self.json_out(self.run_cfq("trash", "list", str(self.repo), "--json", check=True))
        self.assertEqual({e["id"] for e in listing}, {id_a, id_b})

    def test_restore_onto_occupied_path_without_force_fails_and_changes_nothing(self):
        target = self.cfq_dir / "todo" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("original\n")
        entry_id = self.run_cfq("trash", "put", str(self.repo), str(target), check=True).stdout.strip()
        target.write_text("new occupant\n")

        proc = self.run_cfq("trash", "restore", str(self.repo), entry_id)
        self.assertNotEqual(proc.returncode, 0, "restore onto an occupied path should fail")
        self.assertEqual(target.read_text(), "new occupant\n", "occupant must be left untouched")
        listing = self.json_out(self.run_cfq("trash", "list", str(self.repo), "--json", check=True))
        self.assertEqual(len(listing), 1, "failed restore must not consume the trash entry")

    def test_restore_onto_occupied_path_with_force_trashes_occupant_first(self):
        target = self.cfq_dir / "todo" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("original\n")
        entry_id = self.run_cfq("trash", "put", str(self.repo), str(target), check=True).stdout.strip()
        target.write_text("new occupant\n")

        restored = self.run_cfq(
            "trash", "restore", str(self.repo), entry_id, "--force", check=True
        ).stdout.strip()
        self.assertEqual(restored, str(target))
        self.assertEqual(target.read_text(), "original\n")

        listing = self.json_out(self.run_cfq("trash", "list", str(self.repo), "--json", check=True))
        self.assertEqual(len(listing), 1, "the displaced occupant should itself land in the trash")
        self.assertEqual(listing[0]["originalPath"], str(target))

    def test_put_outside_cfq_dir_fails_out_of_scope_and_deletes_nothing(self):
        outside = self.repo / "README.md"
        self.assertTrue(outside.exists())

        proc = self.run_cfq("trash", "put", str(self.repo), str(outside))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("OUT_OF_SCOPE", proc.stderr)
        self.assertTrue(outside.exists(), "a rejected put must not delete anything")

    def test_restore_unknown_entry_fails_no_such_entry(self):
        proc = self.run_cfq("trash", "restore", str(self.repo), "20260101T000000Z-00")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("NO_SUCH_ENTRY", proc.stderr)


if __name__ == "__main__":
    unittest.main()
