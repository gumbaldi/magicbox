"""Tests for scripts/cfq_portal.py -- the `portal sync`/`portal rebuild` data layer behind
`<repo>/.claude/cfq/reports/index.html`. The viewer shell itself is phase 02; this only checks
the `.js` data files `portal sync` writes into `<repo>/.claude/cfq/reports/data/`.
"""

import json
import re
import shutil
import sys
import unittest

from cfq_testlib import CfqTestCase, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import markdown as cfq_lib_markdown  # noqa: E402

DATA_FILE_RE = re.compile(
    r"^window\.CFQ_DATA = window\.CFQ_DATA \|\| \{\};\n"
    r"window\.CFQ_DATA\[(?P<key>.*?)\] = (?P<payload>.*);\n\Z",
    re.S,
)

SCHEMA2_TELEMETRY = {
    "totals": {"turns": 4, "output": 1000, "billable_in": 500, "cache_read": 0},
    "wallclock_s": 60,
    "by_model": {"sonnet": 1},
    "by_effort": {"medium": 1},
    "by_skill": {"-": 1},
    "skills_recommended": ["tdd"],
    "layers": {
        "main": {"turns": 2, "output": 600, "billable_in": 300},
        "main_explore": {"turns": 0, "output": 0, "billable_in": 0},
        "worker": {"turns": 2, "output": 400, "billable_in": 200},
        "worker_explore": {"turns": 0, "output": 0, "billable_in": 0},
    },
    "agents": [{"id": "agent-1", "type": "cfq:cfq-phase-worker", "depth": 1}],
}

SCHEMA1_TELEMETRY = {
    "totals": {"turns": 3, "output": 300, "billable_in": 150, "cache_read": 0},
    "wallclock_s": 30,
    "by_model": {"sonnet": 1},
    "by_effort": {"medium": 1},
    "by_skill": {"-": 1},
    "subagent_worker": {"turns": 1, "output": 100, "billable_in": 50},
}


class PortalTest(CfqTestCase):
    # ---- fixture builders --------------------------------------------------------------------

    def _build_batch(self, repo, batch_name, with_report=True, schema1=False):
        impl = repo / ".claude" / "cfq" / "impl" / batch_name
        impl.mkdir(parents=True)
        (impl / ".batch-context.md").write_text(
            "# Batch Context\n\n"
            "## Goal\nBuild the portal.\nA second goal line, ignored by the first-line reader.\n\n"
            "## Decisions\n- Decision one\n- Decision two\n\n"
            "## Invariants\nNever break the build.\n"
        )
        (impl / "01-first.md").write_text(
            "# First phase\n\n## Size\n\nM\n\n## Context\n\n"
            "Some context with <script>alert(1)</script> in it.\n"
        )
        done = impl / "done"
        done.mkdir()
        (done / "00-setup.md").write_text("# Setup phase\n\n## Size\n\nS\n\n## Context\n\nSetup context.\n")

        if with_report:
            tel = SCHEMA1_TELEMETRY if schema1 else SCHEMA2_TELEMETRY
            report = {
                "repo": str(repo), "batch": batch_name, "started": "2026-09-23T10:00:00+02:00",
                "phases": [{
                    "phase": "00-setup", "status": "green", "summary": "did setup",
                    "commit": "abc123", "deviations": [], "errors": [], "triggers": [],
                    "filesTouched": ["x.py"], "parkedPlanEntries": [], "verification": "ok",
                    "finished": "2026-09-23T10:30:00+02:00", "telemetry": tel,
                }],
                "security": [
                    {"available": True, "counts": {"low": 1}, "findings": [], "at": "2026-09-23T10:00:00+02:00"},
                ],
            }
            (impl / "report.json").write_text(json.dumps(report))
        return impl

    def _add_todo(self, repo, filename="2026-09-20-fix-thing.md", with_check=True):
        d = repo / ".claude" / "cfq" / "todo"
        d.mkdir(parents=True, exist_ok=True)
        body = "# Fix the thing\n\nSome todo body.\n"
        if with_check:
            body += "\ncheck: true\n"
        (d / filename).write_text(body)
        return d / filename

    def _add_plan_entry(self, repo, filename="2026-09-19-idea.md"):
        d = repo / ".claude" / "cfq" / "plan"
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_text("# An idea\n\nDetails about the idea.\n")
        return d / filename

    def _data_dir(self, repo):
        return repo / ".claude" / "cfq" / "reports" / "data"

    def _payload(self, path):
        m = DATA_FILE_RE.match(path.read_text())
        self.assertIsNotNone(m, f"unexpected data-file shape in {path}: {path.read_text()[:200]!r}")
        return json.loads(m.group("key")), json.loads(m.group("payload"))

    def _sync(self, repo, *extra):
        proc = self.run_cfq("portal", "sync", str(repo), *extra)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return self.json_out(proc)

    # ---- routine: fresh sync writes everything, a no-op re-sync writes nothing ----------------

    def test_fresh_sync_writes_every_file_then_second_sync_writes_nothing(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        self._add_todo(repo)
        self._add_plan_entry(repo)

        result = self._sync(repo)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["removed"], [])
        self.assertEqual(
            set(result["written"]),
            {
                "queue.js",
                "batch/2026-09-23-demo.plan.js",
                "batch/2026-09-23-demo.impl.js",
                "entry/todo-2026-09-20-fix-thing.js",
                "entry/plan-2026-09-19-idea.js",
            },
        )
        self.assertEqual(result["unchanged"], 0)

        data_dir = self._data_dir(repo)
        for rel in result["written"]:
            self.assertTrue((data_dir / rel).is_file(), f"{rel} was reported written but is missing")

        second = self._sync(repo)
        self.assertEqual(second["written"], [], "an unchanged fixture must rewrite nothing")
        self.assertEqual(second["unchanged"], 5)
        self.assertEqual(second["removed"], [])

    def test_queue_js_lists_batch_and_entries(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        self._add_todo(repo)
        self._add_plan_entry(repo)
        self._sync(repo)

        key, payload = self._payload(self._data_dir(repo) / "queue.js")
        self.assertEqual(key, "queue")
        self.assertEqual(len(payload["batches"]), 1)
        row = payload["batches"][0]
        self.assertEqual(row["name"], "2026-09-23-demo")
        self.assertEqual(row["status"], "in_progress")  # one phase done, one still open
        self.assertEqual(row["goal"], "Build the portal.")
        self.assertGreater(row["cost"]["total"]["output"], 0)
        self.assertEqual(row["cost"]["total"]["output"], sum(
            row["cost"]["layers"][name]["output"] for name in
            ("main", "main_explore", "worker", "worker_explore")
        ))

        entries = {e["id"]: e for e in payload["entries"]}
        self.assertEqual(entries["todo-2026-09-20-fix-thing"]["check"], True)
        self.assertEqual(entries["todo-2026-09-20-fix-thing"]["origin"], "todo")
        self.assertEqual(entries["plan-2026-09-19-idea"]["check"], False)
        self.assertEqual(entries["plan-2026-09-19-idea"]["origin"], "plan")
        self.assertNotIn("bodyHtml", entries["plan-2026-09-19-idea"], "queue.js entries stay summaries")

    # ---- routine: a changed report.json rewrites only that batch's impl.js and queue.js -------

    def test_changed_report_json_rewrites_only_impl_and_queue(self):
        repo = self.make_repo()
        impl = self._build_batch(repo, "2026-09-23-demo")
        self._sync(repo)

        report = json.loads((impl / "report.json").read_text())
        # Schema 2 reads cost from `layers`, not `totals` (cfq_report.phase_layer_sums prefers
        # `layers` whenever it's present) -- changing `totals` alone would leave every layer-sum
        # consumer (queue.js's per-batch cost) byte-identical, so the fixture edits the field the
        # layer reader actually looks at.
        report["phases"][0]["telemetry"]["layers"]["main"]["output"] = 9999
        (impl / "report.json").write_text(json.dumps(report))

        result = self._sync(repo)
        self.assertEqual(set(result["written"]), {"queue.js", "batch/2026-09-23-demo.impl.js"})
        self.assertEqual(result["unchanged"], 1)  # plan.js alone stays byte-identical

    # ---- edge: no report.json yet -> no impl.js -------------------------------------------------

    def test_batch_without_report_json_has_no_impl_js(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo", with_report=False)
        result = self._sync(repo)

        self.assertNotIn("batch/2026-09-23-demo.impl.js", result["written"])
        self.assertFalse((self._data_dir(repo) / "batch/2026-09-23-demo.impl.js").exists())
        self.assertTrue((self._data_dir(repo) / "batch/2026-09-23-demo.plan.js").exists())

    # ---- edge: a closed plan entry's data file is removed --------------------------------------

    def test_closed_entry_data_file_is_removed(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        entry = self._add_plan_entry(repo)
        self._sync(repo)
        self.assertTrue((self._data_dir(repo) / "entry/plan-2026-09-19-idea.js").is_file())

        entry.unlink()  # simulates `note close`'s move into plan/done/
        result = self._sync(repo)
        self.assertIn("entry/plan-2026-09-19-idea.js", result["removed"])
        self.assertFalse((self._data_dir(repo) / "entry/plan-2026-09-19-idea.js").exists())

    def test_deleted_batch_data_files_are_removed(self):
        repo = self.make_repo()
        impl = self._build_batch(repo, "2026-09-23-demo")
        self._sync(repo)

        shutil.rmtree(impl)
        result = self._sync(repo)
        self.assertIn("batch/2026-09-23-demo.plan.js", result["removed"])
        self.assertIn("batch/2026-09-23-demo.impl.js", result["removed"])

    # ---- edge: phase text containing <script> comes out escaped --------------------------------

    def test_phase_body_html_is_escaped(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        self._sync(repo)

        _key, payload = self._payload(self._data_dir(repo) / "batch/2026-09-23-demo.plan.js")
        phase = next(p for p in payload["phases"] if p["slug"] == "01-first")
        self.assertIn("&lt;script&gt;", phase["bodyHtml"])
        self.assertNotIn("<script>", phase["bodyHtml"])
        self.assertEqual(phase["title"], "First phase")
        self.assertEqual(phase["size"], "M")
        self.assertEqual(phase["state"], "open")

        done_phase = next(p for p in payload["phases"] if p["slug"] == "00-setup")
        self.assertEqual(done_phase["state"], "done")
        self.assertIn("<h1>Setup phase</h1>", done_phase["bodyHtml"])

    # ---- fallback: schema-1 report.json still yields layer sums --------------------------------

    def test_schema1_report_yields_layer_sums(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo", schema1=True)
        self._sync(repo)

        _key, payload = self._payload(self._data_dir(repo) / "batch/2026-09-23-demo.impl.js")
        cost = payload["cost"]
        self.assertEqual(cost["layers"]["main"]["turns"], SCHEMA1_TELEMETRY["totals"]["turns"])
        self.assertEqual(
            cost["layers"]["worker"]["turns"], SCHEMA1_TELEMETRY["subagent_worker"]["turns"],
        )
        self.assertEqual(cost["layers"]["worker_explore"]["turns"], 0)
        # `totals` and `subagent_worker` are disjoint pools in schema 1 (the same invariant
        # cfq_report.cmd_summary relies on) -- the whole-batch total is their sum, not `totals`
        # alone.
        self.assertEqual(
            cost["total"]["turns"],
            SCHEMA1_TELEMETRY["totals"]["turns"] + SCHEMA1_TELEMETRY["subagent_worker"]["turns"],
        )

    # ---- --batch filter: unselected batches keep their existing files, gain no new ones --------

    def test_batch_filter_only_regenerates_named_batches(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-alpha")
        self._build_batch(repo, "2026-09-23-beta")

        result = self._sync(repo, "--batch", "2026-09-23-alpha")
        self.assertIn("batch/2026-09-23-alpha.plan.js", result["written"])
        self.assertNotIn("batch/2026-09-23-beta.plan.js", result["written"])
        self.assertFalse((self._data_dir(repo) / "batch/2026-09-23-beta.plan.js").exists())
        # queue.js and every entry file are always recomputed, filter or not
        self.assertIn("queue.js", result["written"])

    def test_rebuild_is_sync_over_everything(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-alpha")
        self._build_batch(repo, "2026-09-23-beta")

        proc = self.run_cfq("portal", "rebuild", str(repo))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        result = self.json_out(proc)
        self.assertIn("batch/2026-09-23-alpha.plan.js", result["written"])
        self.assertIn("batch/2026-09-23-beta.plan.js", result["written"])


# ---- cfq_lib.markdown's extensions over cfq_report.py's original md_min/md_inline --------------

class MarkdownExtensionTest(unittest.TestCase):
    def test_h1_dropped_by_default_unchanged_from_before(self):
        self.assertEqual(cfq_lib_markdown.md_min("# Batch Context\n"), "")

    def test_h1_kept_as_title_when_requested(self):
        out = cfq_lib_markdown.md_min("# Batch Context\n\nBody text.\n", keep_h1=True)
        self.assertEqual(out, "<h1>Batch Context</h1><p>Body text.</p>")

    def test_fenced_code_block_escaped_never_inline_formatted(self):
        out = cfq_lib_markdown.md_min("```\n**not bold** <tag>\n```\n")
        self.assertIn("<pre><code>", out)
        self.assertIn("&lt;tag&gt;", out)
        self.assertNotIn("<strong>", out)
        self.assertIn("**not bold**", out)  # inline markers pass through literally inside a fence

    def test_unterminated_fence_still_renders_its_content(self):
        out = cfq_lib_markdown.md_min("```\nstill here\n")
        self.assertIn("<pre><code>still here</code></pre>", out)

    def test_ordered_list_renders_as_ol(self):
        out = cfq_lib_markdown.md_min("1. one\n2. two\n")
        self.assertIn("<ol>", out)
        self.assertEqual(out.count("<li>"), 2)
        self.assertIn("<li>one</li>", out)

    def test_switching_from_bullet_to_ordered_closes_the_first_list(self):
        out = cfq_lib_markdown.md_min("- bullet\n1. numbered\n")
        self.assertIn("<ul><li>bullet</li></ul>", out)
        self.assertIn("<ol><li>numbered</li></ol>", out)


if __name__ == "__main__":
    unittest.main()
