"""Tests for scripts/cfq_portal.py -- the `portal sync`/`portal rebuild` data layer behind
`<repo>/.claude/cfq/reports/index.html`. The viewer shell itself is phase 02; this only checks
the `.js` data files `portal sync` writes into `<repo>/.claude/cfq/reports/data/`.
"""

import json
import pathlib
import re
import shutil
import sys
import unittest

from cfq_testlib import PLUGIN_ROOT, CfqTestCase, SCRIPTS_DIR

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

    def _sync(self, repo, *extra, env=None):
        proc = self.run_cfq("portal", "sync", str(repo), *extra, env=env)
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
                "index.html",
                "assets/viewer.js",
                "assets/style.css",
                "queue.js",
                "site.js",
                "batch/2026-09-23-demo.plan.js",
                "batch/2026-09-23-demo.impl.js",
                "entry/todo-2026-09-20-fix-thing.js",
                "entry/plan-2026-09-19-idea.js",
            },
        )
        self.assertEqual(result["unchanged"], 0)

        reports_dir = self._data_dir(repo).parent
        for rel in ("index.html", "assets/viewer.js", "assets/style.css"):
            self.assertTrue((reports_dir / rel).is_file(), f"{rel} was reported written but is missing")
        data_dir = self._data_dir(repo)
        for rel in ("queue.js", "site.js", "batch/2026-09-23-demo.plan.js", "batch/2026-09-23-demo.impl.js",
                    "entry/todo-2026-09-20-fix-thing.js", "entry/plan-2026-09-19-idea.js"):
            self.assertTrue((data_dir / rel).is_file(), f"{rel} was reported written but is missing")

        second = self._sync(repo)
        # The version stamp already matches -- the shell copy is skipped entirely (not even
        # reported as "unchanged", per the "an unchanged version copies nothing" contract).
        self.assertEqual(second["written"], [], "an unchanged fixture must rewrite nothing")
        self.assertEqual(second["unchanged"], 6)
        self.assertEqual(second["removed"], [])

    def test_queue_js_row_carries_unknown_deps(self):
        # An unnamed/deleted dependency doesn't block a batch on its own (cfq_scan.py's own
        # resolve_deps -- only a still-open dependency dir does that), but the viewer still needs
        # to name it, so `unknownDeps` travels through unmodified alongside `dependsOn`.
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        (repo / ".claude" / "cfq" / "impl" / "2026-09-23-demo" / ".dependsOn").write_text("gibtsnicht\n")
        self._sync(repo)

        _key, payload = self._payload(self._data_dir(repo) / "queue.js")
        row = payload["batches"][0]
        self.assertEqual(row["dependsOn"], ["gibtsnicht"])
        self.assertEqual(row["unknownDeps"], ["gibtsnicht"])

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
        self.assertEqual(result["unchanged"], 2)  # site.js and plan.js alone stay byte-identical

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

    # ---- rebuild --migrate: retiring the old per-batch HTML report (batch 040 phase 05) --------

    def test_migrate_removes_legacy_batch_html_but_keeps_the_shell(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        reports_dir = self._data_dir(repo).parent
        reports_dir.mkdir(parents=True, exist_ok=True)
        legacy_dated = reports_dir / "2026-09-23-demo.html"
        legacy_numbered = reports_dir / "038-2026-09-23-other.html"
        legacy_dated.write_text("<html>old per-batch report</html>")
        legacy_numbered.write_text("<html>old per-batch report</html>")
        (reports_dir / "index.html").write_text("<html>old collected index</html>")

        result = self.json_out(self.run_cfq("portal", "rebuild", str(repo), "--migrate"))
        self.assertEqual(result["status"], "OK")
        self.assertIn(str(legacy_dated), result["removed"])
        self.assertIn(str(legacy_numbered), result["removed"])
        self.assertFalse(legacy_dated.exists())
        self.assertFalse(legacy_numbered.exists())
        # The shell's own `index.html` survives migration -- it was already overwritten with the
        # real viewer shell by this same rebuild's ordinary sync step, not deleted by --migrate.
        self.assertEqual(
            (reports_dir / "index.html").read_text(), (PLUGIN_ROOT / "portal" / "index.html").read_text(),
        )

    def test_migrate_never_touches_assets_or_data(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        result = self.json_out(self.run_cfq("portal", "rebuild", str(repo), "--migrate"))
        self.assertEqual(result["status"], "OK")
        self.assertTrue((self._data_dir(repo) / "batch" / "2026-09-23-demo.plan.js").is_file())
        reports_dir = self._data_dir(repo).parent
        self.assertTrue((reports_dir / "assets" / "viewer.js").is_file())

    def test_rebuild_without_migrate_leaves_legacy_html_untouched(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        reports_dir = self._data_dir(repo).parent
        reports_dir.mkdir(parents=True, exist_ok=True)
        legacy = reports_dir / "2026-09-23-demo.html"
        legacy.write_text("<html>old</html>")

        result = self.json_out(self.run_cfq("portal", "rebuild", str(repo)))
        self.assertEqual(result["removed"], [])
        self.assertTrue(legacy.is_file(), "plain rebuild (no --migrate) must not touch legacy html")

    def test_migrate_removes_reportdir_mirror_legacy_html(self):
        repo = self.make_repo("alpha")
        self._build_batch(repo, "2026-09-23-a")
        report_dir = self._repos_dir / "shared-reports"
        mirror_dir = report_dir / "alpha"
        mirror_dir.mkdir(parents=True)
        legacy = mirror_dir / "2026-09-23-a.html"
        legacy.write_text("<html>old</html>")

        result = self.json_out(self.run_cfq(
            "portal", "rebuild", str(repo), "--migrate", env={"CFQ_REPORT_DIR": str(report_dir)},
        ))
        self.assertEqual(result["status"], "OK")
        self.assertIn(str(legacy), result["removed"])
        self.assertFalse(legacy.exists())

    # ---- install: the fixed viewer shell -------------------------------------------------------

    def _plugin_version(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        return data["version"]

    def _init_queue(self, repo):
        """A bare `.claude/cfq/` with no batches -- `cfq_scan.scan_repo()` treats a repo with no
        such directory at all as unregistered (`status: "NO_REPO"`, sync short-circuits before
        even reaching the install step), so every install-only test needs at least this much."""
        (repo / ".claude" / "cfq").mkdir(parents=True, exist_ok=True)

    def test_install_copies_shell_files_matching_portal_source(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        for src_name, rel in (
            ("index.html", "index.html"),
            ("viewer.js", "assets/viewer.js"),
            ("style.css", "assets/style.css"),
        ):
            self.assertEqual(
                (reports_dir / rel).read_text(),
                (PLUGIN_ROOT / "portal" / src_name).read_text(),
                f"{rel} was not copied verbatim from portal/{src_name}",
            )
        self.assertEqual((reports_dir / ".portal-version").read_text().strip(), self._plugin_version())

    def test_install_copies_nothing_when_version_stamp_already_matches(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        # A local edit to the installed shell must survive an unchanged-version resync -- the
        # phase's own contract ("an unchanged version copies nothing") means zero file operations,
        # not a content-diff rewrite back to the plugin's own source.
        (reports_dir / "assets" / "style.css").write_text("/* locally edited */")

        result = self._sync(repo)
        self.assertNotIn("index.html", result["written"])
        self.assertNotIn("assets/viewer.js", result["written"])
        self.assertNotIn("assets/style.css", result["written"])
        self.assertEqual((reports_dir / "assets" / "style.css").read_text(), "/* locally edited */")

    def test_install_recopies_shell_when_version_stamp_differs(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        (reports_dir / ".portal-version").write_text("0.0.0-stale")
        (reports_dir / "assets" / "style.css").write_text("/* stale */")

        result = self._sync(repo)
        self.assertIn("assets/style.css", result["written"])
        self.assertEqual(
            (reports_dir / "assets" / "style.css").read_text(),
            (PLUGIN_ROOT / "portal" / "style.css").read_text(),
        )
        self.assertEqual((reports_dir / ".portal-version").read_text().strip(), self._plugin_version())

    def test_data_site_js_carries_mode_and_repo_name(self):
        repo = self.make_repo("my-repo")
        self._init_queue(repo)
        self._sync(repo)

        key, payload = self._payload(self._data_dir(repo) / "site.js")
        self.assertEqual(key, "site")
        self.assertEqual(payload, {"mode": "repo", "repo": "my-repo"})

    def test_sync_without_reportdir_carries_no_mirror(self):
        repo = self.make_repo()
        self._init_queue(repo)
        result = self._sync(repo)
        self.assertIsNone(result["mirror"])

    # ---- reportDir mirror (batch 040 phase 03) --------------------------------------------------

    def test_reportdir_mirror(self):
        repo_a = self.make_repo("alpha")
        repo_b = self.make_repo("beta")
        self._build_batch(repo_a, "2026-09-23-a")
        self._build_batch(repo_b, "2026-09-23-b")

        report_dir = self._repos_dir / "shared-reports"
        report_dir.mkdir()
        env = {"CFQ_REPORT_DIR": str(report_dir)}

        result_a = self._sync(repo_a, env=env)
        result_b = self._sync(repo_b, env=env)

        # routine: both mirrored, repos.js has two rows -----------------------------------------
        self.assertEqual(result_a["mirror"]["status"], "OK")
        self.assertEqual(result_b["mirror"]["status"], "OK")

        for rel in ("index.html", "assets/viewer.js", "assets/style.css"):
            self.assertTrue((report_dir / rel).is_file(), f"global shell {rel} not installed")
        self.assertTrue((report_dir / ".portal-version").is_file())

        site_key, site_payload = self._payload(report_dir / "data" / "site.js")
        self.assertEqual(site_key, "site")
        self.assertEqual(site_payload, {"mode": "global"})

        repos_key, repos_payload = self._payload(report_dir / "data" / "repos.js")
        self.assertEqual(repos_key, "repos")
        self.assertEqual(len(repos_payload), 2)
        by_source = {r["source"]: r for r in repos_payload}
        self.assertIn(str(repo_a.resolve()), by_source)
        self.assertIn(str(repo_b.resolve()), by_source)
        row_a = by_source[str(repo_a.resolve())]
        self.assertEqual(row_a["name"], "alpha")
        self.assertEqual(row_a["mirror"], "alpha")
        self.assertIn("batches", row_a["counts"])

        for repo, mirror_name, batch_name in (
            (repo_a, "alpha", "2026-09-23-a"), (repo_b, "beta", "2026-09-23-b"),
        ):
            mirror_data = report_dir / mirror_name / "data"
            for rel in ("site.js", "queue.js", f"batch/{batch_name}.plan.js"):
                self.assertTrue((mirror_data / rel).is_file(), f"{mirror_name}: missing mirrored {rel}")
            _k, mirrored_queue = self._payload(mirror_data / "queue.js")
            _k2, repo_queue = self._payload(self._data_dir(repo) / "queue.js")
            self.assertEqual(mirrored_queue, repo_queue, f"{mirror_name}: mirrored queue.js diverges from repo-local")

        # a no-op re-sync of the same repo mirrors nothing new
        second = self._sync(repo_a, env=env)
        self.assertEqual(second["mirror"]["status"], "OK")
        self.assertEqual(second["mirror"]["written"], [])

    def test_reportdir_mirror_same_basename_gets_stable_distinct_directory(self):
        repo_1 = self.make_repo("dup")
        repo_2 = self.make_repo(str(pathlib.Path("nested") / "dup"))
        self._build_batch(repo_1, "2026-09-23-a")
        self._build_batch(repo_2, "2026-09-23-b")

        report_dir = self._repos_dir / "shared-reports"
        report_dir.mkdir()
        env = {"CFQ_REPORT_DIR": str(report_dir)}

        result_1 = self._sync(repo_1, env=env)
        result_2 = self._sync(repo_2, env=env)
        mirror_1 = result_1["mirror"]["written"]
        mirror_2 = result_2["mirror"]["written"]
        self.assertTrue(any(p.startswith("dup/data/") for p in mirror_1), mirror_1)
        second_mirror_dirs = {p.split("/", 1)[0] for p in mirror_2 if "/data/" in p}
        self.assertEqual(len(second_mirror_dirs), 1)
        second_mirror_dir = next(iter(second_mirror_dirs))
        self.assertNotEqual(second_mirror_dir, "dup")
        self.assertTrue(second_mirror_dir.startswith("dup-"), second_mirror_dir)

        repos_key, repos_payload = self._payload(report_dir / "data" / "repos.js")
        mirrors = {r["mirror"] for r in repos_payload}
        self.assertEqual(mirrors, {"dup", second_mirror_dir})

        # stable across a re-sync: the same repo keeps the same mirror name it was first assigned,
        # and an unchanged resync mirrors nothing new
        result_2_again = self._sync(repo_2, env=env)
        self.assertEqual(result_2_again["mirror"]["written"], [])
        _key, repos_payload_again = self._payload(report_dir / "data" / "repos.js")
        by_source = {r["source"]: r["mirror"] for r in repos_payload_again}
        self.assertEqual(by_source[str(repo_2.resolve())], second_mirror_dir)

    def test_reportdir_unwritable_falls_back_with_mirror_error(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")

        robase = self._repos_dir / "readonly-parent"
        robase.mkdir()
        bad_report_dir = robase / "reports"
        robase.chmod(0o555)
        try:
            result = self._sync(repo, env={"CFQ_REPORT_DIR": str(bad_report_dir)})
        finally:
            robase.chmod(0o755)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["mirror"]["status"], "ERROR")
        self.assertTrue(result["mirror"]["detail"])
        # the repo-local sync itself is unaffected by the mirror failure
        self.assertTrue((self._data_dir(repo) / "queue.js").is_file())
        self.assertTrue((self._data_dir(repo) / "batch/2026-09-23-demo.plan.js").is_file())


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
