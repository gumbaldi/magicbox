"""Unit tests for cfq_lib/tools.py, the `requiredTools` checker (batch 059 phase 04). Entries are
tool names that are only looked up, never executed -- the marker-file case pins that down."""

import pathlib
import sys
import tempfile
import unittest

from cfq_testlib import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import tools  # noqa: E402


class CheckTest(unittest.TestCase):
    def test_python_module_present(self):
        self.assertEqual(tools.check(["py:json"]), {"entries": ["py:json"], "missing": []})

    def test_python_module_missing(self):
        got = tools.check(["py:cfq_no_such_module"])
        self.assertEqual(got["missing"], ["py:cfq_no_such_module"])

    def test_path_lookup_present(self):
        self.assertEqual(tools.check(["sh"])["missing"], [])

    def test_path_lookup_missing(self):
        self.assertEqual(tools.check(["cfq-no-such-tool"])["missing"], ["cfq-no-such-tool"])

    def test_command_is_missing_and_never_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = pathlib.Path(tmp) / "marker"
            entry = f"touch {marker}"
            got = tools.check([entry])
            self.assertEqual(got["missing"], [entry])
            self.assertFalse(marker.exists(), msg="an entry was executed")

    def test_malformed_python_entries_are_missing(self):
        got = tools.check(["py:a.b", "py:"])
        self.assertEqual(got["missing"], ["py:a.b", "py:"])

    def test_shell_characters_and_slashes_are_missing(self):
        entries = ["a;b", "/bin/sh", "a b", "$(x)"]
        self.assertEqual(tools.check(entries)["missing"], entries)

    def test_entries_stripped_order_kept_empties_dropped(self):
        got = tools.check([" py:json ", "", "cfq-no-such-tool", "  "])
        self.assertEqual(got["entries"], ["py:json", "cfq-no-such-tool"])
        self.assertEqual(got["missing"], ["cfq-no-such-tool"])

    def test_empty_and_none(self):
        self.assertEqual(tools.check([]), {"entries": [], "missing": []})
        self.assertEqual(tools.check(None), {"entries": [], "missing": []})

    def test_find_spec_error_counts_as_missing(self):
        # a submodule-less name whose parent import would raise cannot occur without a dot; patch
        # find_spec itself to prove the guard.
        import importlib.util
        real = importlib.util.find_spec
        importlib.util.find_spec = lambda name: (_ for _ in ()).throw(ValueError("boom"))
        try:
            self.assertEqual(tools.check(["py:json"])["missing"], ["py:json"])
        finally:
            importlib.util.find_spec = real


class StatusEntryTest(unittest.TestCase):
    def test_no_entries_is_none(self):
        self.assertIsNone(tools.status_entry(tools.check([]), blocking=True))
        self.assertIsNone(tools.status_entry(tools.check([]), blocking=False))

    def test_all_present(self):
        e = tools.status_entry(tools.check(["py:json", "sh"]), blocking=True)
        self.assertEqual((e["label"], e["icon"], e["detail"]), ("Required Tools", "done", "2 present"))

    def test_missing_blocking(self):
        result = tools.check(["py:json", "cfq-no-a", "cfq-no-b"])
        e = tools.status_entry(result, blocking=True)
        self.assertEqual(e["icon"], "fail")
        self.assertEqual(e["detail"], "missing: cfq-no-a, cfq-no-b · install them, then re-run /ifq")

    def test_missing_warning(self):
        e = tools.status_entry(tools.check(["cfq-no-a"]), blocking=False)
        self.assertEqual(e["icon"], "warn")
        self.assertEqual(e["detail"], "missing: cfq-no-a · /ifq stops until they are installed")


if __name__ == "__main__":
    unittest.main()
