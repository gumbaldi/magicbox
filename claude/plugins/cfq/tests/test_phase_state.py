"""cfq_lib/phase_state.py: the module that owns a batch's status.json and the done/ + skipped/
mirror directories. Imported directly -- there is no CLI to drive."""

import json
import pathlib
import tempfile
import unittest

import cfq_testlib  # noqa: F401  (puts scripts/ on sys.path)
from cfq_lib import phase_state as ps  # noqa: E402


class PhaseStateTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.batch = pathlib.Path(tmp.name).resolve() / "batch"
        self.batch.mkdir()

    def make_plans(self, *names):
        for n in names:
            (self.batch / f"{n}.md").write_text(f"# {n}\n")

    def setup_batch(self, *names):
        self.make_plans(*names)
        ps.init(self.batch)
        ps.sync_files(self.batch)

    def status_of(self, slug):
        return {p["slug"]: p for p in ps.phases(self.batch)}[slug]

    def assert_code(self, code, fn, *args, **kwargs):
        with self.assertRaises(ps.PhaseStateError) as cm:
            fn(*args, **kwargs)
        self.assertEqual(cm.exception.code, code)


class TestRoutine(PhaseStateTestCase):
    def test_init_writes_empty_file(self):
        ps.init(self.batch)
        self.assertEqual(
            json.loads((self.batch / "status.json").read_text()), {"schema": 1, "phases": {}}
        )

    def test_init_never_overwrites(self):
        self.setup_batch("01-a")
        ps.init(self.batch)
        self.assertIn("01-a", ps.load(self.batch)["phases"])

    def test_sync_adds_open_and_read_side(self):
        ps.init(self.batch)
        self.make_plans("02-b", "01-a")
        self.assertEqual(ps.sync_files(self.batch), {"added": ["01-a", "02-b"], "removed": []})
        phases = ps.phases(self.batch)
        self.assertEqual([p["slug"] for p in phases], ["01-a", "02-b"])
        self.assertEqual([p["num"] for p in phases], ["01", "02"])
        self.assertEqual([p["status"] for p in phases], ["open", "open"])
        self.assertEqual(phases[0]["path"], self.batch / "01-a.md")
        self.assertEqual(
            ps.counts(self.batch), {"open": 2, "done": 0, "error": 0, "skipped": 0}
        )
        self.assertEqual(ps.next_pending(self.batch), "01-a")

    def test_status_file_is_byte_stable_and_sorted(self):
        self.setup_batch("02-b", "01-a")
        first = (self.batch / "status.json").read_bytes()
        ps.sync_files(self.batch)
        self.assertEqual((self.batch / "status.json").read_bytes(), first)
        keys = list(json.loads(first)["phases"])
        self.assertEqual(keys, sorted(keys))

    def test_open_to_done_moves_file(self):
        self.setup_batch("01-a")
        path = ps.transition(self.batch, "01-a", "done")
        self.assertEqual(path, self.batch / "done" / "01-a.md")
        self.assertTrue(path.is_file())
        self.assertFalse((self.batch / "01-a.md").exists())
        self.assertIn("at", ps.load(self.batch)["phases"]["01-a"])

    def test_open_to_error_keeps_file_in_root(self):
        self.setup_batch("01-a")
        ps.transition(self.batch, "01-a", "error")
        self.assertTrue((self.batch / "01-a.md").is_file())
        self.assertEqual(self.status_of("01-a")["status"], "error")

    def test_error_to_done_and_done_to_open(self):
        self.setup_batch("01-a")
        ps.transition(self.batch, "01-a", "error")
        ps.transition(self.batch, "01-a", "done")
        self.assertTrue((self.batch / "done" / "01-a.md").is_file())
        ps.transition(self.batch, "01-a", "open")
        self.assertTrue((self.batch / "01-a.md").is_file())
        self.assertFalse((self.batch / "done" / "01-a.md").exists())

    def test_open_to_skipped_records_reason_and_previous(self):
        self.setup_batch("01-a")
        path = ps.transition(self.batch, "01-a", "skipped", reason="obsolete")
        self.assertEqual(path, self.batch / "skipped" / "01-a.md")
        entry = ps.load(self.batch)["phases"]["01-a"]
        self.assertEqual(entry["status"], "skipped")
        self.assertEqual(entry["reason"], "obsolete")
        self.assertEqual(entry["previous"], "open")

    def test_error_to_skipped_records_previous_error(self):
        self.setup_batch("01-a")
        ps.transition(self.batch, "01-a", "error")
        ps.transition(self.batch, "01-a", "skipped")
        entry = ps.load(self.batch)["phases"]["01-a"]
        self.assertEqual(entry["previous"], "error")
        self.assertNotIn("reason", entry)

    def test_unskip_restores_previous_status(self):
        self.setup_batch("01-a", "02-b")
        ps.transition(self.batch, "01-a", "skipped", reason="r")
        path, restored = ps.unskip(self.batch, "01-a")
        self.assertEqual((path, restored), (self.batch / "01-a.md", "open"))
        entry = ps.load(self.batch)["phases"]["01-a"]
        self.assertEqual(entry["status"], "open")
        self.assertNotIn("reason", entry)
        self.assertNotIn("previous", entry)
        ps.transition(self.batch, "02-b", "error")
        ps.transition(self.batch, "02-b", "skipped")
        self.assertEqual(ps.unskip(self.batch, "02-b")[1], "error")
        self.assertTrue((self.batch / "02-b.md").is_file())
        self.assertFalse((self.batch / "skipped" / "02-b.md").exists())


class TestEdge(PhaseStateTestCase):
    def test_next_pending_returns_error_phase_first(self):
        self.setup_batch("01-a", "02-b", "03-c")
        ps.transition(self.batch, "01-a", "done")
        ps.transition(self.batch, "02-b", "error")
        self.assertEqual(ps.next_pending(self.batch), "02-b")

    def test_next_pending_skips_done_and_skipped(self):
        self.setup_batch("01-a", "02-b", "03-c")
        ps.transition(self.batch, "01-a", "done")
        ps.transition(self.batch, "02-b", "skipped")
        self.assertEqual(ps.next_pending(self.batch), "03-c")

    def test_next_pending_none_when_nothing_pending(self):
        self.setup_batch("01-a", "02-b")
        ps.transition(self.batch, "01-a", "done")
        ps.transition(self.batch, "02-b", "skipped")
        self.assertIsNone(ps.next_pending(self.batch))
        self.assertIsNone(ps.next_pending(self.batch) if not ps.phases(self.batch) else None)

    def test_resolve_slug(self):
        self.setup_batch("02-b", "03-baz")
        self.assertEqual(ps.resolve_slug(self.batch, "03"), "03-baz")
        self.assertEqual(ps.resolve_slug(self.batch, "03-baz"), "03-baz")
        self.assertEqual(ps.resolve_slug(self.batch, "3"), "03-baz")

    def test_locate_in_every_directory(self):
        self.setup_batch("01-a", "02-b", "03-c")
        ps.transition(self.batch, "02-b", "done")
        ps.transition(self.batch, "03-c", "skipped")
        self.assertEqual(ps.locate(self.batch, "01-a"), self.batch / "01-a.md")
        self.assertEqual(ps.locate(self.batch, "02-b"), self.batch / "done" / "02-b.md")
        self.assertEqual(ps.locate(self.batch, "03-c"), self.batch / "skipped" / "03-c.md")
        self.assertIsNone(ps.locate(self.batch, "09-none"))

    def test_sync_removes_only_open_entries_without_file(self):
        self.setup_batch("01-a", "02-b", "03-c")
        ps.transition(self.batch, "02-b", "error")
        (self.batch / "01-a.md").unlink()
        (self.batch / "02-b.md").unlink()
        result = ps.sync_files(self.batch)
        self.assertEqual(result["removed"], ["01-a"])
        phases = ps.load(self.batch)["phases"]
        self.assertNotIn("01-a", phases)
        self.assertEqual(phases["02-b"]["status"], "error")

    def test_annotate_leaves_status_alone(self):
        self.setup_batch("01-a")
        ps.transition(self.batch, "01-a", "skipped")
        ps.annotate(self.batch, "01-a", inbox="2026-10-04-x.md")
        entry = ps.load(self.batch)["phases"]["01-a"]
        self.assertEqual(entry["status"], "skipped")
        self.assertEqual(entry["inbox"], "2026-10-04-x.md")
        self.assertEqual(self.status_of("01-a")["inbox"], "2026-10-04-x.md")

    def test_sync_adopts_files_by_location(self):
        ps.init(self.batch)
        (self.batch / "done").mkdir()
        (self.batch / "skipped").mkdir()
        (self.batch / "done" / "01-a.md").write_text("x")
        (self.batch / "skipped" / "02-b.md").write_text("x")
        (self.batch / "03-c.md").write_text("x")
        ps.sync_files(self.batch)
        phases = ps.load(self.batch)["phases"]
        self.assertEqual(phases["01-a"]["status"], "done")
        self.assertEqual(phases["02-b"]["status"], "skipped")
        self.assertEqual(phases["02-b"]["previous"], "open")
        self.assertEqual(phases["03-c"]["status"], "open")

    def test_sync_never_changes_an_existing_entry(self):
        self.setup_batch("01-a", "02-b")
        ps.transition(self.batch, "01-a", "done")
        before = ps.load(self.batch)["phases"]["01-a"]
        (self.batch / "done" / "01-a.md").rename(self.batch / "01-a.md")
        (self.batch / "02-b.md").rename(self.batch / "02-b.md.bak")
        (self.batch / "02-b.md.bak").rename(self.batch / "02-b.md")
        ps.sync_files(self.batch)
        self.assertEqual(ps.load(self.batch)["phases"]["01-a"], before)

    def test_mismatches(self):
        self.setup_batch("01-a", "02-b")
        ps.transition(self.batch, "01-a", "done")
        (self.batch / "done" / "01-a.md").rename(self.batch / "01-a.md")
        (self.batch / "03-c.md").write_text("x")
        (self.batch / "02-b.md").unlink()
        found = {(m["slug"], m["kind"]) for m in ps.mismatches(self.batch)}
        self.assertEqual(
            found, {("01-a", "location"), ("03-c", "no_entry"), ("02-b", "no_file")}
        )

    def test_mismatches_empty_when_consistent(self):
        self.setup_batch("01-a", "02-b")
        ps.transition(self.batch, "01-a", "done")
        self.assertEqual(ps.mismatches(self.batch), [])

    def test_snapshot_and_restore(self):
        self.setup_batch("01-a")
        before = ps.load(self.batch)
        snap = ps.snapshot(self.batch, "01-a")
        ps.transition(self.batch, "01-a", "done")
        ps.restore(self.batch, "01-a", snap)
        self.assertEqual(ps.load(self.batch), before)
        self.assertTrue((self.batch / "01-a.md").is_file())
        self.assertFalse((self.batch / "done" / "01-a.md").exists())

    def test_snapshot_restore_from_skipped(self):
        self.setup_batch("01-a")
        ps.transition(self.batch, "01-a", "skipped", reason="r")
        before = ps.load(self.batch)
        snap = ps.snapshot(self.batch, "01-a")
        ps.unskip(self.batch, "01-a")
        ps.restore(self.batch, "01-a", snap)
        self.assertEqual(ps.load(self.batch), before)
        self.assertTrue((self.batch / "skipped" / "01-a.md").is_file())


class TestMustFail(PhaseStateTestCase):
    def test_load_without_file(self):
        self.assert_code("STATUS_FILE_MISSING", ps.load, self.batch)
        self.assertFalse(ps.exists(self.batch))

    def test_load_invalid_json(self):
        (self.batch / "status.json").write_text("{not json")
        self.assert_code("STATUS_FILE_INVALID", ps.load, self.batch)

    def test_load_wrong_shape(self):
        (self.batch / "status.json").write_text("[]")
        self.assert_code("STATUS_FILE_INVALID", ps.load, self.batch)

    def test_invalid_transitions(self):
        self.setup_batch("01-a", "02-b")
        ps.transition(self.batch, "01-a", "done")
        self.assert_code("INVALID_TRANSITION", ps.transition, self.batch, "01-a", "skipped")
        ps.transition(self.batch, "02-b", "skipped")
        self.assert_code("INVALID_TRANSITION", ps.transition, self.batch, "02-b", "done")
        self.assert_code("INVALID_TRANSITION", ps.transition, self.batch, "02-b", "open")

    def test_open_to_open(self):
        self.setup_batch("01-a")
        self.assert_code("INVALID_TRANSITION", ps.transition, self.batch, "01-a", "open")

    def test_unknown_status(self):
        self.setup_batch("01-a")
        self.assert_code("INVALID_TRANSITION", ps.transition, self.batch, "01-a", "bogus")

    def test_unskip_on_non_skipped(self):
        self.setup_batch("01-a")
        self.assert_code("INVALID_TRANSITION", ps.unskip, self.batch, "01-a")

    def test_unknown_phase(self):
        self.setup_batch("01-a")
        self.assert_code("UNKNOWN_PHASE", ps.resolve_slug, self.batch, "09")
        self.assert_code("UNKNOWN_PHASE", ps.transition, self.batch, "09-x", "done")
        self.assert_code("UNKNOWN_PHASE", ps.unskip, self.batch, "09-x")
        self.assert_code("UNKNOWN_PHASE", ps.annotate, self.batch, "09-x", a=1)


class TestFallback(PhaseStateTestCase):
    def test_failed_write_moves_file_back(self):
        self.setup_batch("01-a")
        # write_json stages through status.json.tmp; a directory there makes the write fail
        # after load() has already succeeded and the plan file has already moved.
        (self.batch / "status.json.tmp").mkdir()
        with self.assertRaises(OSError):
            ps.transition(self.batch, "01-a", "done")
        self.assertTrue((self.batch / "01-a.md").is_file())
        self.assertFalse((self.batch / "done" / "01-a.md").exists())
        self.assertEqual(ps.load(self.batch)["phases"]["01-a"]["status"], "open")


if __name__ == "__main__":
    unittest.main()
