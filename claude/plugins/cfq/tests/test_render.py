"""Migrated from test-render.sh.

Self-test for the render mode of scripts/cfq_dash.py: an additive terminal render over the same
JSON the default invocation returns -- this file pins that one-code-path guarantee explicitly.
"""

import pathlib
import subprocess
import sys
import unittest

from cfq_testlib import CfqTestCase, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import render  # noqa: E402


class TestRender(CfqTestCase):
    auto_status = True

    def _plain_repo(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)

    # --- fixture builders, each returns the rendered text; shared by their own test and the
    # no-HTML-entity sweep below ---

    def _dash_two_repos_json_and_text(self):
        tmp = self._repos_dir / "dashroot"
        repo_a = tmp / "repo-a"
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "done").mkdir(parents=True)
        self._plain_repo(repo_a)
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "01-a.md").touch()
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "done" / "00-x.md").touch()
        repo_b = tmp / "repo-b"
        (repo_b / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo_b)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        json_out = self.json_out(self.run_cfq("dash", str(tmp), env=env))
        text = self.run_cfq("dash", "render", str(tmp), env=env).stdout
        return json_out, text

    def _dash_render_empty_registry(self):
        # Fresh HOME, not self.home -- cfq_scan.py registers every scanned repo into the
        # registry, so reusing self.home after another fixture's dash call would still find those
        # repos via the registry union, regardless of CFQ_SCAN_ROOTS.
        empty_home = self._repos_dir / "empty-registry-home"
        empty_home.mkdir()
        empty_root = self._repos_dir / "empty-root"
        empty_root.mkdir()
        return self.run_cfq(
            "dash", "render", str(empty_root), home=empty_home, env={"CFQ_SCAN_ROOTS": str(empty_root)},
        ).stdout

    def _dash_render_multiple_in_progress(self):
        mip_home = self._repos_dir / "mip-home"
        mip_home.mkdir()
        mip_tmp = self._repos_dir / "mip-root"
        mip_repo = mip_tmp / "repo-mip"
        for name in ("2026-01-01-a", "2026-01-02-b"):
            (mip_repo / ".claude" / "cfq" / "impl" / name / "done").mkdir(parents=True)
            (mip_repo / ".claude" / "cfq" / "impl" / name / "01-a.md").touch()
            (mip_repo / ".claude" / "cfq" / "impl" / name / "done" / "00-x.md").touch()
        self._plain_repo(mip_repo)
        return self.run_cfq(
            "dash", "render", str(mip_repo), home=mip_home, env={"CFQ_SCAN_ROOTS": str(mip_tmp)},
        ).stdout

    def _dash_render_ponytail_full(self):
        pony_tmp = self._repos_dir / "pony-root"
        pony_home = self._repos_dir / "pony-home"
        (pony_home / ".claude" / "plugins" / "cache" / "ponytail" / "ponytail" / "4.8.4").mkdir(parents=True)
        repo_p = pony_tmp / "repo-p"
        (repo_p / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo_p)
        return self.run_cfq(
            "dash", "render", str(pony_tmp), home=pony_home, env={"CFQ_SCAN_ROOTS": str(pony_tmp)},
        ).stdout

    def _dash_render_ponytail_off(self):
        pony_off_tmp = self._repos_dir / "pony-off-root"
        pony_off_home = self._repos_dir / "pony-off-home"
        (pony_off_home / ".claude" / "plugins" / "cache" / "ponytail" / "ponytail" / "4.8.4").mkdir(parents=True)
        (pony_off_home / ".config" / "ponytail").mkdir(parents=True)
        (pony_off_home / ".config" / "ponytail" / "config.json").write_text('{"defaultMode":"off"}')
        repo_q = pony_off_tmp / "repo-q"
        (repo_q / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo_q)
        return self.run_cfq(
            "dash", "render", str(pony_off_tmp), home=pony_off_home, env={"CFQ_SCAN_ROOTS": str(pony_off_tmp)},
        ).stdout

    # --- tests ---

    def test_dash_json_and_text_agree_on_repo_count(self):
        json_out, text = self._dash_two_repos_json_and_text()

        with self.subTest(mode="text"):
            self.assertIn(
                "| repo-a | 0 | 0 | 1/0 | 0 |", text, f"repo-a row missing/wrong in QUEUES:\n{text}",
            )
            self.assertIn(
                "| repo-b | 0 | 0 | 0/0 | 0 | OK |", text, f"repo-b row missing/wrong in QUEUES:\n{text}",
            )

        # Equivalence: render and the JSON default agree on repo count for the same fixture.
        with self.subTest(mode="json"):
            self.assertEqual(len(json_out["repos"]), 2, "JSON repos length")
        with self.subTest(mode="text"):
            render_repo_lines = sum(1 for line in text.splitlines() if line.startswith("| repo-"))
            self.assertEqual(render_repo_lines, 2, f"render repo row count = {render_repo_lines}")

    def test_dash_render_empty_registry_plain_sentence(self):
        empty_text = self._dash_render_empty_registry()
        self.assertIn("No repos with a queue yet.", empty_text, f"empty registry sentence missing:\n{empty_text}")
        self.assertNotIn("| Repo |", empty_text, "empty registry still rendered a table")

    def test_dash_render_multiple_in_progress(self):
        mip_text = self._dash_render_multiple_in_progress()
        self.assertIn("MULTIPLE_IN_PROGRESS", mip_text, f"MULTIPLE_IN_PROGRESS not surfaced:\n{mip_text}")
        self.assertIn("2026-01-01-a", mip_text, f"batch a dropped from MULTIPLE_IN_PROGRESS render:\n{mip_text}")
        self.assertIn("2026-01-02-b", mip_text, f"batch b dropped from MULTIPLE_IN_PROGRESS render:\n{mip_text}")

    def test_dash_render_ponytail_full_mode_warns(self):
        pony_text = self._dash_render_ponytail_full()
        self.assertIn("mode: full", pony_text, f"ponytail full mode not surfaced:\n{pony_text}")
        self.assertIn("cfq expects off", pony_text, f"ponytail warning text missing:\n{pony_text}")
        self.assertIn("⚠️ Plugins", pony_text, f"ponytail mode warning should force the ⚠️ icon:\n{pony_text}")

    def test_dash_render_ponytail_off_mode_no_warning(self):
        # `off` is ponytail's expected, configured state -- the mode clause vanishes entirely
        # rather than printing a redundant "mode: off" (see test_dash.py's plugins-line coverage).
        pony_off_text = self._dash_render_ponytail_off()
        self.assertNotIn("mode:", pony_off_text, f"mode clause should vanish when ponytailMode is off:\n{pony_off_text}")
        self.assertNotIn("cfq expects off", pony_off_text, "mode off should not carry a warning")

    def test_no_html_entity_in_any_rendered_terminal_output(self):
        _, text = self._dash_two_repos_json_and_text()
        empty_text = self._dash_render_empty_registry()
        mip_text = self._dash_render_multiple_in_progress()
        pony_text = self._dash_render_ponytail_full()
        pony_off_text = self._dash_render_ponytail_off()

        all_output = "\n".join(
            [text, empty_text, mip_text, pony_text, pony_off_text],
        )
        for entity in ("&nbsp;", "&amp;", "&#"):
            self.assertNotIn(entity, all_output, f"HTML entity {entity!r} found in rendered terminal output")


class TestJqAlt(unittest.TestCase):
    def test_routine(self):
        self.assertEqual(render.jq_alt("a", "b"), "a")
        self.assertEqual(render.jq_alt(None, "b"), "b")
        self.assertEqual(render.jq_alt(False, "b"), "b")

    def test_variadic(self):
        self.assertEqual(render.jq_alt(None, None, "see detail"), "see detail")

    def test_falsy_but_valid_values_are_not_rejected(self):
        # jq's `//` only rejects `null` and `false`, never `0` or `""` -- unlike Python's `or`.
        self.assertEqual(render.jq_alt(0, "b"), 0)
        self.assertEqual(render.jq_alt("", "b"), "")

    def test_exhausted_falls_back_to_none(self):
        self.assertIsNone(render.jq_alt(None))
        self.assertIsNone(render.jq_alt())

    def test_two_arg_default_none_shape(self):
        self.assertIsNone(render.jq_alt(None, None))


class WriteAtomicTest(unittest.TestCase):
    def test_write_text_atomic_writes_overwrites_and_leaves_no_tmp(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "f.txt")
            render.write_text_atomic(target, "one")
            self.assertEqual(pathlib.Path(target).read_text(), "one")
            render.write_text_atomic(target, "two\n")
            self.assertEqual(pathlib.Path(target).read_text(), "two\n")
            self.assertEqual(os.listdir(d), ["f.txt"])

    def test_write_json_bytes_unchanged(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "f.json")
            render.write_json(target, {"a": [1, 2], "b": "é"})
            self.assertEqual(
                pathlib.Path(target).read_text(encoding="utf-8"),
                '{\n  "a": [\n    1,\n    2\n  ],\n  "b": "é"\n}\n',
            )
            self.assertEqual(os.listdir(d), ["f.json"])


if __name__ == "__main__":
    unittest.main()
